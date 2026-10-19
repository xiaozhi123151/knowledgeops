import asyncio
import contextlib
import logging
import time
import uuid

from redis.asyncio import Redis
from redis.exceptions import RedisError, ResponseError

logger = logging.getLogger(__name__)


class RedisQueue:
    stream, group = 'knowledgeops:tasks', 'knowledgeops:workers'

    def __init__(self, settings):
        self.client = Redis.from_url(settings.redis_url, decode_responses=True,
                                     socket_connect_timeout=2, socket_timeout=3)
        self.consumer = uuid.uuid4().hex
        self.lease_ms = int(settings.lease_seconds * 1000)

    async def initialize(self):
        try:
            await self.client.xgroup_create(self.stream, self.group, id='0', mkstream=True)
        except ResponseError as exc:
            if 'BUSYGROUP' not in str(exc):
                raise

    async def enqueue(self, task_id):
        await self.client.xadd(self.stream, {'task_id': task_id}, maxlen=10000, approximate=True)

    async def take(self):
        reclaimed = await self.client.xautoclaim(self.stream, self.group, self.consumer,
                                                min_idle_time=self.lease_ms, count=1)
        if reclaimed[1]:
            return reclaimed[1][0]
        rows = await self.client.xreadgroup(self.group, self.consumer, {self.stream: '>'}, count=1, block=500)
        return rows[0][1][0] if rows else None

    async def ack(self, message_id):
        await self.client.xack(self.stream, self.group, message_id)

    async def close(self):
        await self.client.aclose()


async def worker_loop(runtime):
    """One worker. Ledger reconciliation repairs lost queue notifications and Redis restarts."""
    last_scan = 0.0
    while True:
        runtime.store.worker_heartbeat()
        if runtime.settings.mode == 'offline':
            for task_id in runtime.store.candidates():
                await runtime.runner.execute(task_id)
            await asyncio.sleep(runtime.settings.poll_seconds)
            continue
        try:
            if time.monotonic() - last_scan > 2:
                await runtime.queue.initialize()
                for task_id in runtime.store.candidates():
                    await runtime.queue.enqueue(task_id)
                last_scan = time.monotonic()
            item = await runtime.queue.take()
            if item:
                message_id, payload = item
                task_id = payload.get('task_id')
                if task_id:
                    await runtime.runner.execute(task_id)
                await runtime.queue.ack(message_id)
        except RedisError:
            logger.warning('Redis unavailable; durable tasks retained for reconciliation')
            await asyncio.sleep(1)


async def stop_worker(future):
    if future:
        future.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await future
