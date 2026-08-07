"""
Warm account pool. Signup is ~1s of HTTP; keeping a few ready accounts in memory
takes it out of the hot path so a request only pays for the WS stream.

Each account is single-use (1 free message). The background loop tops the pool
back up to ACCOUNT_POOL_SIZE; acquire() hands one out, or signs up inline if the
pool is drained (graceful degradation under burst load).

Rotates Tor circuits via NEWNYM every TOR_NEWNYM_EVERY accounts to avoid rate limiting.
"""
import asyncio
import logging
import time

from . import config
from .session_http import create_account, renew_tor_circuit

log = logging.getLogger("account_pool")


class AccountPool:
    def __init__(self):
        self.size = getattr(config, "ACCOUNT_POOL_SIZE", 200)
        self.ttl = getattr(config, "ACCOUNT_TTL_SEC", 600)
        self.refill_sec = getattr(config, "ACCOUNT_POOL_REFILL_SEC", 1)
        self._q: asyncio.Queue | None = None
        self._task: asyncio.Task | None = None
        self._consec_fails = 0
        self._since_renew = 0

    def _queue(self) -> asyncio.Queue:
        if self._q is None:
            self._q = asyncio.Queue(maxsize=self.size)
        return self._q

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
            asyncio.create_task(self._initial_fill())
            log.info("account pool started (target=%d, refill=%ds)", self.size, self.refill_sec)

    async def _initial_fill(self) -> None:
        """Aggressively fill pool on startup."""
        await asyncio.sleep(1)
        q = self._queue()
        deficit = min(self.size, 50)
        created = await self._fill_batch(deficit)
        log.info("initial fill: +%d accounts", created)

    async def _maybe_renew_tor(self):
        """Rotate Tor circuit every N accounts."""
        nym_every = getattr(config, "TOR_NEWNYM_EVERY", 2)
        self._since_renew += 1
        if self._since_renew >= nym_every:
            self._since_renew = 0
            ok = await renew_tor_circuit()
            if ok:
                await asyncio.sleep(getattr(config, "TOR_NEWNYM_DELAY", 3))

    async def _fill_batch(self, count: int) -> int:
        """Create accounts sequentially with Tor rotation (avoid 429)."""
        success = 0
        for i in range(count):
            try:
                await self._maybe_renew_tor()
                a = await create_account()
                a["_born"] = time.time()
                q = self._queue()
                if not q.full():
                    await q.put(a)
                    success += 1
            except Exception as e:
                log.warning("account signup failed: %s", e)
                if "429" in str(e):
                    await asyncio.sleep(3)
                    await renew_tor_circuit()
                    await asyncio.sleep(3)
        return success

    async def _loop(self) -> None:
        while True:
            try:
                q = self._queue()
                deficit = self.size - q.qsize()

                if deficit > 0:
                    batch = min(deficit, 5)
                    created = await self._fill_batch(batch)

                    if created > 0:
                        self._consec_fails = 0
                        log.info("pool +%d (now=%d/%d)", created, q.qsize(), self.size)
                    else:
                        self._consec_fails += 1
                        log.warning("batch failed (%d consecutive)", self._consec_fails)
            except Exception as e:
                log.warning("pool loop error: %s", e)

            delay = self.refill_sec
            if self._consec_fails > 3:
                delay = min(2 * self._consec_fails, 20)
            await asyncio.sleep(delay)

    async def acquire(self) -> dict:
        """A warm account if one is ready (and not stale); otherwise sign up inline."""
        q = self._queue()
        dropped = 0
        while not q.empty():
            try:
                a = q.get_nowait()
            except asyncio.QueueEmpty:
                break
            if time.time() - a.get("_born", 0) < self.ttl:
                return a
            dropped += 1
        if dropped:
            log.info("dropped %d stale account(s); pool will refill", dropped)
        return await create_account()

    def ready(self) -> int:
        """Only accounts that would actually survive acquire()'s TTL check."""
        if not self._q:
            return 0
        now = time.time()
        return sum(1 for a in self._q._queue
                   if now - a.get("_born", 0) < self.ttl)


POOL = AccountPool()
