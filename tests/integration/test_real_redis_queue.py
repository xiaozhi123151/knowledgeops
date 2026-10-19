import asyncio
import os
import uuid

import pytest

from knowledgeops.worker.queue import RedisQueue

pytestmark = [pytest.mark.live, pytest.mark.retrieval_live]


async def test_real_stream_duplicate_delivery_and_pending_reclaim(settings):
    if os.getenv("KO_RUN_RETRIEVAL_TESTS") != "1":
        pytest.skip("UNVERIFIED: set KO_RUN_RETRIEVAL_TESTS=1 with real Redis")
    config = settings.model_copy(update={"redis_url": "redis://127.0.0.1:6379/0", "lease_seconds": 1})
    first, second = RedisQueue(config), RedisQueue(config)
    stream = "knowledgeops:test:" + uuid.uuid4().hex
    first.stream = second.stream = stream
    first.lease_ms = second.lease_ms = 20
    try:
        await first.initialize()
        await second.initialize()
        await first.enqueue("same-task")
        await first.enqueue("same-task")
        a = await first.take()
        assert a[1]["task_id"] == "same-task"
        await asyncio.sleep(0.05)
        reclaimed = await second.take()
        assert reclaimed == a
        await second.ack(reclaimed[0])
        duplicate = await second.take()
        assert duplicate[0] != a[0] and duplicate[1]["task_id"] == "same-task"
        await second.ack(duplicate[0])
        assert (await second.client.xpending(stream, second.group))["pending"] == 0
    finally:
        await first.client.delete(stream)
        await first.close()
        await second.close()
