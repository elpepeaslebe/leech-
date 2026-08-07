"""
High-speed account pool. Creates accounts in parallel batches for maximum throughput.
Each account is single-use (1 free message). The background loop fills the pool
to ACCOUNT_POOL_SIZE using concurrent batch creation.
"""
import asyncio
import logging
import time

from . import config
from .session_http import create_account

log = logging.getLogger("account_pool")


class AccountPool:
    def __init__(self):
        self.size = getattr(config, "ACCOUNT_POOL_SIZE", 1000)
        self.ttl = getattr(config, "ACCOUNT_TTL_SEC", 600)
        self.refill_sec = getattr(config, "ACCOUNT_POOL_REFILL_SEC", 0.5)
        self.batch_size = getattr(config, "ACCOUNT_BATCH_SIZE", 50)
        self.batch_concurrency = getattr(config, "ACCOUNT_BATCH_CONCURRENCY", 80)
        self._q: asyncio.Queue | None = None
        self._task: asyncio.Task | None = None
        self._consec_fails = 0

    def _queue(self) -> asyncio.Queue:
        if self._q is None:
            self._q = asyncio.Queue(maxsize=self.size)
        return self._q

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
            # Fast initial fill: create first batch immediately
            asyncio.create_task(self._initial_fill())
            log.info("account pool started (target=%d, batch=%d, concurrency=%d)",
                     self.size, self.batch_size, self.batch_concurrency)

    async def _initial_fill(self) -> None:
        """Aggressively fill pool on startup."""
        await asyncio.sleep(1)  # wait for server to be ready
        q = self._queue()
        deficit = min(self.size, 100)  # fill up to 100 immediately
        created = await self._fill_batch(deficit)
        log.info("initial fill: +%d accounts", created)

    async def _create_one(self) -> dict | None:
        """Create one account. Returns dict or None on failure."""
        try:
            a = await create_account()
            a["_born"] = time.time()
            return a
        except Exception as e:
            log.warning("account signup failed: %s", e)
            return None

    async def _fill_batch(self, count: int) -> int:
        """Create `count` accounts in parallel. Returns number of successes."""
        sem = asyncio.Semaphore(self.batch_concurrency)
        results = []

        async def _worker():
            async with sem:
                return await self._create_one()

        tasks = [_worker() for _ in range(count)]
        done = await asyncio.gather(*tasks, return_exceptions=True)

        success = 0
        for r in done:
            if isinstance(r, dict) and r:
                q = self._queue()
                if not q.full():
                    await q.put(r)
                    success += 1
        return success

    async def _loop(self) -> None:
        while True:
            try:
                q = self._queue()
                deficit = self.size - q.qsize()

                if deficit > 0:
                    batch = min(deficit, self.batch_size)
                    created = await self._fill_batch(batch)

                    if created > 0:
                        self._consec_fails = 0
                        log.info("pool +%d (now=%d/%d)", created, q.qsize(), self.size)
                    else:
                        self._consec_fails += 1
                        log.warning("batch failed (%d consecutive)", self._consec_fails)
            except Exception as e:
                log.warning("pool loop error: %s", e)

            # Back off on consecutive failures
            delay = self.refill_sec
            if self._consec_fails > 3:
                delay = min(0.5 * self._consec_fails, 10)
            await asyncio.sleep(delay)

    async def acquire(self) -> dict:
        """A warm account if one is ready (and not stale); otherwise sign up inline."""
        q = self._queue()
        while not q.empty():
            try:
                a = q.get_nowait()
            except asyncio.QueueEmpty:
                break
            if time.time() - a.get("_born", 0) < self.ttl:
                return a               # fresh enough -> use it
            # stale -> drop and try the next one
        return await create_account()  # drained -> inline signup

    def ready(self) -> int:
        return self._q.qsize() if self._q else 0


POOL = AccountPool()
