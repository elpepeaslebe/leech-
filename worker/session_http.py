"""
Headless account factory. use.ai signup is two unauthenticated POSTs and needs
NO password, NO email verification (fake emails are accepted; emailVerified stays
null). One free message per account, unlimited accounts per IP -> no proxies.

create_account() -> {email, user_id, cookie_header, token}

Uses curl_cffi for browser TLS impersonation to bypass Cloudflare TLS fingerprinting.
Tor circuit rotation via NEWNYM prevents rate limiting.
"""
import asyncio
import pathlib
import time
import uuid
import logging

from . import config
from .email_gen import gen_email

log = logging.getLogger("session_http")

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36")

_tor_nynym_lock = asyncio.Lock()


async def renew_tor_circuit() -> bool:
    """Send NEWNYM to Tor control port to get a new exit IP."""
    async with _tor_nynym_lock:
        try:
            cookie_path = pathlib.Path(config.TOR_DATA_DIR) / "control_auth_cookie"
            if not cookie_path.exists():
                cookie_path = pathlib.Path(__file__).resolve().parent.parent / "tor_data" / "control_auth_cookie"
            if not cookie_path.exists():
                log.warning("Tor cookie not found")
                return False

            cookie_hex = cookie_path.read_bytes().hex()
            port = getattr(config, "TOR_CONTROL_PORT", 9051)

            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", port), timeout=5)

            writer.write(f'AUTHENTICATE {cookie_hex}\r\n'.encode())
            await writer.drain()
            auth_resp = await asyncio.wait_for(reader.readline(), timeout=5)
            auth_str = auth_resp.decode().strip()

            if "250" not in auth_str:
                log.warning("Tor auth failed: %s", auth_str)
                writer.close()
                await writer.wait_closed()
                return False

            writer.write(b'SIGNAL NEWNYM\r\n')
            await writer.drain()
            nynm_resp = await asyncio.wait_for(reader.readline(), timeout=5)
            nynm_str = nynm_resp.decode().strip()

            writer.close()
            await writer.wait_closed()

            ok = "250" in nynm_str
            if ok:
                log.info("Tor circuit renewed")
            else:
                log.warning("Tor NEWNYM failed: %s", nynm_str)
            return ok
        except Exception as e:
            log.warning("Tor NEWNYM error: %s: %s", type(e).__name__, e)
            return False


async def create_account(proxy: str | None = None) -> dict:
    """Sign up a throwaway account using curl_cffi with browser TLS impersonation."""
    from curl_cffi.requests import AsyncSession

    email = gen_email()
    proxy_url = proxy or ("socks5://127.0.0.1:9050" if getattr(config, "PROXY_TOR", False) else None)

    async with AsyncSession(impersonate="chrome", proxy=proxy_url, timeout=20) as c:
        # Step 1: email-login (may return 403 but account is still created)
        try:
            r1 = await c.post(f"{config.AUTH_BASE}/email-login",
                              json={"email": email},
                              headers={"Content-Type": "application/json"})
            log.debug("email-login %d for %s", r1.status_code, email)
        except Exception as e:
            log.debug("email-login error (non-fatal): %s", e)

        # Step 2: sign-in/credentials (this is what actually creates the session)
        r2 = await c.post(f"{config.AUTH_BASE}/sign-in/credentials", json={
            "email": email,
            "mixpanelUserId": str(uuid.uuid4()),
            "guestId": str(uuid.uuid4()),
            "mid": str(uuid.uuid4()),
        })
        r2.raise_for_status()
        token = r2.headers.get("set-auth-token", "")

        # Step 3: get-session
        s = await c.get(f"{config.AUTH_BASE}/get-session")
        if s.status_code != 200 or s.text in ("", "null"):
            raise RuntimeError(f"get-session empty after signup ({s.status_code})")
        j = s.json()
        user_id = j["user"]["id"]
        cookie_header = "; ".join(f"{k}={v}" for k, v in c.cookies.items())

        # Pre-fetch WS tokens
        ws_tokens = None
        try:
            r_token = await c.get(f"{config.AUTH_BASE}/token")
            r_att = await c.post(f"{config.AUTH_BASE}/app-attestation", json={"priorToken": ""})
            if r_token.status_code == 200 and r_att.status_code == 200:
                ws_t = r_token.json().get("token", "")
                ws_at = r_att.json().get("token", "")
                expires_in = float(r_att.json().get("expiresIn") or 300)
                if ws_t and ws_at:
                    now = time.time()
                    ws_tokens = {"token": ws_t, "app_token": ws_at,
                                 "at": now, "expires_at": now + max(30, expires_in)}
        except Exception:
            pass

    log.info("created account %s (userId=%s)", email, user_id[:8])
    acct = {"email": email, "user_id": user_id,
            "cookie_header": cookie_header, "token": token}
    if ws_tokens:
        acct["_ws_tokens"] = ws_tokens
    return acct


async def get_ws_tokens(acct: dict, proxy: str | None = None) -> tuple[str, str]:
    from curl_cffi.requests import AsyncSession

    lock = acct.get("_ws_lock")
    if lock is None:
        lock = acct["_ws_lock"] = asyncio.Lock()
    async with lock:
        cached = acct.get("_ws_tokens")
        if cached and time.time() < cached.get("expires_at", 0) - 30:
            return cached["token"], cached["app_token"]

        proxy_url = proxy or ("socks5://127.0.0.1:9050" if getattr(config, "PROXY_TOR", False) else None)
        hdrs = {"Cookie": acct["cookie_header"], "Origin": "https://use.ai",
                "Referer": "https://use.ai/", "User-Agent": _UA}

        async with AsyncSession(impersonate="chrome", proxy=proxy_url, timeout=20) as c:
            for part in acct["cookie_header"].split("; "):
                if "=" in part:
                    k, v = part.split("=", 1)
                    c.cookies.set(k, v, domain=".use.ai")

            r, r2 = await asyncio.gather(
                c.get(f"{config.AUTH_BASE}/token", headers=hdrs),
                c.post(f"{config.AUTH_BASE}/app-attestation",
                       json={"priorToken": (cached or {}).get("app_token", "")},
                       headers=hdrs),
            )
            r.raise_for_status()
            r2.raise_for_status()
            token = r.json().get("token", "")
            attestation = r2.json()
            app_token = attestation.get("token", "")
            expires_in = float(attestation.get("expiresIn") or 300)

        if not token or not app_token:
            raise RuntimeError("token/app-attestation mint returned empty")
        now = time.time()
        acct["_ws_tokens"] = {"token": token, "app_token": app_token,
                              "at": now, "expires_at": now + max(30, expires_in)}
        return token, app_token
