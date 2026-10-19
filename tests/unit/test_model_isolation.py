import asyncio
import multiprocessing as mp
import time

import pytest

from knowledgeops.providers.reranker import IsolatedCrossEncoder


def slow_model(pipe, marker):
    pipe.recv()
    time.sleep(.3)
    marker.write_text('late result')
    pipe.send(('ok', [1.0]))


async def test_timeout_terminates_compute(settings, tmp_path):
    scorer = IsolatedCrossEncoder(settings)
    ctx = mp.get_context('spawn')
    scorer.pipe, child = ctx.Pipe()
    marker = tmp_path / 'late'
    scorer.process = ctx.Process(target=slow_model, args=(child, marker), daemon=True)
    scorer.process.start()
    child.close()
    with pytest.raises(TimeoutError, match='RERANKER_TIMEOUT'):
        await scorer.score('query', ['text'], timeout=.02)
    assert scorer.process is None
    await asyncio.sleep(.4)
    assert not marker.exists()
