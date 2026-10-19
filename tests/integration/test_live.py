import os
from pathlib import Path

import httpx
import pytest

from scripts.common import import_file, request, wait_task

pytestmark = pytest.mark.live


@pytest.fixture
def live_client():
    from dotenv import dotenv_values
    env = {**dotenv_values(), **os.environ}
    if os.getenv('KO_RUN_LIVE_TESTS') != '1':
        pytest.skip('UNVERIFIED: set KO_RUN_LIVE_TESTS=1 with live API, Qdrant, Redis, LLM, Embedding and CrossEncoder')
    key = env.get('KO_API_KEY')
    if not key:
        pytest.fail('Live tests explicitly enabled but KO_API_KEY is missing')
    with httpx.Client(base_url=os.getenv('KO_TEST_BASE_URL','http://127.0.0.1:8000'),
                      headers={'X-API-Key':key},timeout=190) as client:
        readiness = client.get('/health/ready')
        readiness.raise_for_status()
        info = readiness.json()
        assert info['mode'] == 'live', 'Refuse counting offline substitutes as live integration'
        assert all(info['checks'].values())
        yield client


def test_live_pdf_hybrid_and_real_report(live_client):
    root = Path(__file__).parents[2]
    import_file(live_client,root/'examples'/'sample.pdf')
    result = request(live_client,'POST','/query',json={'query':'Redis AOF persistence','rerank':True})
    assert result['mode'] == 'live' and result['hits'] and result['hits'][0]['rerank_score'] is not None
    task = request(live_client,'POST','/research',json={'question':'Explain Redis AOF using the imported PDF.'})
    completed = wait_task(live_client,task['task_id'])
    assert completed['status'] == 'succeeded', completed['error']
    assert completed['result']['citations']
    for citation in completed['result']['citations']:
        chunk = request(live_client,'GET',f"/documents/{citation['doc_id']}/chunks/{citation['chunk_id']}")
        assert citation['quote'] in chunk['text']


def test_live_worker_consumes_durable_task(live_client):
    task = request(live_client,'POST','/documents',files={'file':('live-probe.txt',b'Live probe: vector index readiness.')})
    assert wait_task(live_client,task['task_id'])['status'] == 'succeeded'
