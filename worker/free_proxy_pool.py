"""
Simple proxy pool: load proxies from cache file, rotate them.
No background refresh - just use what we have and refresh manually.
"""
import asyncio
import json
import logging
import random
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("free_proxy_pool")

_CACHE_FILE = Path(__file__).resolve().parent.parent / "proxy_cache.json"
_pool: list[str] = []
_last_load: float = 0
_load_interval = 60  # reload cache every 60s


def _load():
    global _pool, _last_load
    if time.time() - _last_load < _load_interval and _pool:
        return
    if _CACHE_FILE.exists():
        try:
            data = json.loads(_CACHE_FILE.read_text())
            _pool = data.get("proxies", [])
            _last_load = time.time()
        except Exception:
            pass


def start_background_refresh():
    """No-op - we use cached proxies only."""
    pass


async def get_proxy_url() -> Optional[str]:
    _load()
    if not _pool:
        return None
    return random.choice(_pool)


def pool_size() -> int:
    _load()
    return len(_pool)
