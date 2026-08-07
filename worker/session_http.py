"""
Headless account factory. Uses curl_cffi for browser TLS impersonation.
Multi-circuit Tor for parallel signup across multiple exit IPs.
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


class TorCircuit:
    def __init__(self, socks, control_port, data_dir, max_used=4):
        self.socks = socks
        self.control_port = control_port
        self.data_dir = pathlib.Path(data_dir)
        self.max_used = max_used
        self.used = 0
        self.lock = asyncio.Lock()

    async def renew(self):
        async with self.lock:
            try:
                cookie_path = self.data_dir / "control_auth_cookie"
                if not cookie_path.exists():
                    return False
                cookie_hex = cookie_path.read_bytes().hex()
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection("127.0.0.1", self.control_port), timeout=5)
                writer.write(f'AUTHENTICATE {cookie_hex}\r\n'.encode())
                await writer.drain()
                await asyncio.wait_for(reader.readline(), timeout=5)
                writer.write(b'SIGNAL NEWNYM\r\n')
                await writer.drain()
                resp = await asyncio.wait_for(reader.readline(), timeout=5)
                writer.close()
                await writer.wait_closed()
                self.used = 0
                return "250" in resp.decode()
            except Exception as e:
                log.warning("Tor renew error %s: %s", self.socks, e)
                return False

    async def maybe_renew(self):
        async with self.lock:
            if self.used >= self.max_used:
                await self.renew()
                await asyncio.sleep(2)

    async def mark_used(self):
        async with self.lock:
            self.used += 1


_circuits: list[TorCircuit] = []


def _get_circuits() -> list[TorCircuit]:
    global _circuits
    if not _circuits:
        for c in getattr(config, "TOR_CIRCUITS", []):
            _circuits.append(TorCircuit(
                c["socks"], c["control"], c["data"],
                max_used=getattr(config, "TOR_MAX_PER_CIRCUIT", 4)))
    if not _circuits:
        _circuits = [TorCircuit(
            getattr(config, "TOR_SOCKS", "socks5://127.0.0.1:9050"),
            getattr(config, "TOR_CONTROL_PORT", 9051),
            getattr(config, "TOR_DATA_DIR", "tor_data"),
            max_used=getattr(config, "TOR_NEWNYM_EVERY", 4))]
    return _circuits


async def renew_tor_circuit() -> bool:
    circuits = _get_circuits()
    for c in circuits:
        async with c.lock:
            if c.used >= c.max_used:
                return await c.renew()
    return await circuits[0].renew()


async def get_next_circuit() -> TorCircuit:
    circuits = _get_circuits()
    best = min(circuits, key=lambda c: c.used)
    await best.maybe_renew()
    return best


async def create_account(proxy: str | None = None) -> dict:
    """Sign up: get best circuit, create account via Tor."""
    from curl_cffi.requests import AsyncSession

    email = gen_email()

    # Get best available circuit
    circuit = None
    if proxy is None and getattr(config, "PROXY_TOR", False):
        circuit = await get_next_circuit()
        proxy_url = circuit.socks
    elif proxy:
        proxy_url = proxy
    else:
        proxy_url = None

    async with AsyncSession(impersonate="chrome", proxy=proxy_url, timeout=20) as c:
        # Step 1: email-login (non-fatal)
        try:
            await c.post(f"{config.AUTH_BASE}/email-login",
                         json={"email": email},
                         headers={"Content-Type": "application/json"})
        except Exception:
            pass

        # Step 2: sign-in/credentials
        r2 = await c.post(f"{config.AUTH_BASE}/sign-in/credentials", json={
            "email": email,
            "mixpanelUserId": str(uuid.uuid4()),
            "guestId": str(uuid.uuid4()),
            "mid": str(uuid.uuid4()),
        })

        if r2.status_code == 429 and circuit:
            await circuit.renew()
            raise RuntimeError("429 rate limited")

        r2.raise_for_status()
        token = r2.headers.get("set-auth-token", "")

        # Step 3: get-session
        s = await c.get(f"{config.AUTH_BASE}/get-session")
        if s.status_code != 200 or s.text in ("", "null"):
            raise RuntimeError(f"get-session empty ({s.status_code})")
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

    if circuit:
        await circuit.mark_used()

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
