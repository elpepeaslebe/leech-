"""
Headless account factory. use.ai signup is two unauthenticated POSTs and needs
NO password, NO email verification (fake emails are accepted; emailVerified stays
null). One free message per account, unlimited accounts per IP -> no proxies.

create_account() -> {email, user_id, cookie_header, token}
"""
import asyncio
import time
import uuid
import logging

import httpx

from . import config
from .email_gen import gen_email
from .free_proxy_pool import get_proxy_url

log = logging.getLogger("session_http")

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36")
_HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://use.ai",
    "Referer": "https://use.ai/",
    "User-Agent": _UA,
}


async def create_account(proxy: str | None = None) -> dict:
    """Sign up a throwaway account. Tries direct IP first, falls back to proxy pool on 403."""
    email = gen_email()

    # Try direct IP first (fast path)
    try:
        async with httpx.AsyncClient(timeout=15, headers=_HEADERS) as c:
            r1 = await c.post(f"{config.AUTH_BASE}/email-login", json={"email": email})
            r1.raise_for_status()
            return await _finish_signup(c, email)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            log.info("direct IP blocked (403), falling back to proxy pool...")
        else:
            raise

    # Fallback: try proxy pool (get one proxy, try it once)
    proxy_url = await get_proxy_url()
    if not proxy_url:
        raise RuntimeError("direct IP blocked (403) and no working proxies available")

    email = gen_email()  # fresh email for proxy attempt
    try:
        async with httpx.AsyncClient(timeout=15, headers=_HEADERS, proxy=proxy_url) as c:
            r1 = await c.post(f"{config.AUTH_BASE}/email-login", json={"email": email})
            r1.raise_for_status()
            return await _finish_signup(c, email)
    except httpx.HTTPStatusError as e:
        log.warning("proxy %s also failed: %s", proxy_url, e.response.status_code)
        raise


async def _finish_signup(c: httpx.AsyncClient, email: str) -> dict:
    """Complete the signup flow after email-login succeeds."""
    r2 = await c.post(f"{config.AUTH_BASE}/sign-in/credentials", json={
        "email": email,
        "mixpanelUserId": str(uuid.uuid4()),
        "guestId": str(uuid.uuid4()),
        "mid": str(uuid.uuid4()),
    })
    r2.raise_for_status()
    token = r2.headers.get("set-auth-token", "")

    s = await c.get(f"{config.AUTH_BASE}/get-session")
    if s.status_code != 200 or s.text in ("", "null"):
        raise RuntimeError(f"get-session empty after signup ({s.status_code})")
    j = s.json()
    user_id = j["user"]["id"]
    cookie_header = "; ".join(f"{k}={v}" for k, v in c.cookies.items())

    # Pre-fetch WS tokens during signup so get_ws_tokens never needs to be called
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
        pass  # not fatal, get_ws_tokens will retry later

    log.info("created account %s (userId=%s)", email, user_id[:8])
    acct = {"email": email, "user_id": user_id,
            "cookie_header": cookie_header, "token": token}
    if ws_tokens:
        acct["_ws_tokens"] = ws_tokens
    return acct


async def get_ws_tokens(acct: dict, proxy: str | None = None) -> tuple[str, str]:
    cached = acct.get("_ws_tokens")
    if cached and time.time() < cached.get("expires_at", 0) - 30:
        return cached["token"], cached["app_token"]
    hdrs = {"Cookie": acct["cookie_header"], "Origin": "https://use.ai",
            "Referer": "https://use.ai/", "User-Agent": _UA}

    # Try direct IP first, fall back to proxy
    for attempt_proxy in [None, proxy or await get_proxy_url()]:
        if attempt_proxy is None and proxy is None:
            # Try direct
            try:
                async with httpx.AsyncClient(timeout=15, headers=hdrs) as c:
                    r, r2 = await asyncio.gather(
                        c.get(f"{config.AUTH_BASE}/token"),
                        c.post(f"{config.AUTH_BASE}/app-attestation",
                               json={"priorToken": (cached or {}).get("app_token", "")}),
                    )
                    r.raise_for_status()
                    r2.raise_for_status()
                    return _cache_ws_tokens(acct, r, r2, cached)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 403:
                    continue  # try proxy
                raise
        elif attempt_proxy:
            try:
                async with httpx.AsyncClient(timeout=15, headers=hdrs, proxy=attempt_proxy) as c:
                    r, r2 = await asyncio.gather(
                        c.get(f"{config.AUTH_BASE}/token"),
                        c.post(f"{config.AUTH_BASE}/app-attestation",
                               json={"priorToken": (cached or {}).get("app_token", "")}),
                    )
                    r.raise_for_status()
                    r2.raise_for_status()
                    return _cache_ws_tokens(acct, r, r2, cached)
            except Exception:
                continue
    raise RuntimeError("get_ws_tokens failed: direct IP blocked and no working proxy")


def _cache_ws_tokens(acct, r, r2, cached) -> tuple[str, str]:
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
