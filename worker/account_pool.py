"""
Warm account pool with multi-circuit Tor. Each circuit handles up to
TOR_MAX_PER_CIRCUIT signups before auto-renewing. Multiple circuits
run in parallel for maximum throughput.
"""
import asyncio
import logging
import time

from . import config
from .session_http import create_account, _get_circuits

log = logging.getLogger("account_pool")


class AccountPool:
    def __init__(self):
        self.size = getattr(config, "ACCOUNT_POOL_SIZE", 200)
        self.ttl = getattr(config, "ACCOUNT_TTL_SEC", 600)
        self.refill_sec = getattr(config, "ACCOUNT_POOL_REFILL_SEC", 1)
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
            asyncio.create_task(self._initial_fill())
            circuits = _get_circuits()
            log.info("account pool started (target=%d, circuits=%d)",
                     self.size, len(circuits))

    async def _initial_fill(self) -> None:
        """Fill pool using all circuits in parallel."""
        await asyncio.sleep(1)
        q = self._queue()
        deficit = min(self.size, 50)
        created = await self._fill_batch(deficit)
        log.info("initial fill: +%d accounts", created)

    async def _fill_batch(self, count: int) -> int:
        """Create accounts using multiple circuits in parallel."""
        circuits = _get_circuits()
        per_circuit = max(1, count // len(circuits))
        remainder = count - (per_circuit * len(circuits))

        async def _worker(circuit):
            n = per_circuit + (1 if circuit == circuits[0] else 0)
            n = min(n, count)
            success = 0
            for _ in range(n):
                try:
                    await circuit.maybe_renew()
                    a = await create_account()
                    a["_born"] = time.time()
                    q = self._queue()
                    if not q.full():
                        await q.put(a)
                        success += 1
                except Exception as e:
                    log.warning("signup failed (circuit %s): %s",
                                circuit.socks.split(":")[-1], e)
                    if "429" in str(e):
                        await circuit.renew()
                        await asyncio.sleep(2)
            return success

        results = await asyncio.gather(
            *[_worker(c) for c in circuits],
            return_exceptions=True)

        total = sum(r for r in results if isinstance(r, int))
        return total

    async def _loop(self) -> None:
        while True:
            try:
                q = self._queue()
                deficit = self.size - q.qsize()

                if deficit > 0:
                    batch = min(deficit, 10)
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
