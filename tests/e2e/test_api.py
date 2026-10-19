import time

import pytest
from fastapi.testclient import TestClient

from knowledgeops.api.app import create_app


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        c.headers['X-API-Key'] = settings.api_key.get_secret_value()
        yield c


def wait_task(client, task_id):
    end = time.monotonic() + 15
    while time.monotonic() < end:
        task = client.get('/api/v1/tasks/' + task_id).json()
        if task['status'] in ('succeeded', 'failed'):
            assert task['status'] == 'succeeded', task.get('error')
            return task
        time.sleep(.05)
    raise AssertionError('task did not finish')


def test_pdf_to_report_http(client):
    from tests_pdf_fixture import sample_pdf
    imported = client.post('/api/v1/documents', files={'file': ('guide.pdf', sample_pdf(), 'application/pdf')})
    assert imported.status_code == 202
    doc = wait_task(client, imported.json()['task_id'])
    assert doc['result']['doc_id']
    result = client.post('/api/v1/query', json={'query': 'Redis AOF', 'rerank': True})
    assert result.status_code == 200 and result.json()['hits'][0]['rerank_score'] is not None
    run = client.post('/api/v1/research', json={'question': 'Redis AOF persistence'}).json()
    task = wait_task(client, run['task_id'])
    citation = next(c for c in task['result']['citations'] if c['page'] == 1)
    chunk = client.get(f"/api/v1/documents/{citation['doc_id']}/chunks/{citation['chunk_id']}").json()
    assert citation['quote'] in chunk['text'] and citation['page'] == 1
    events = client.get(f"/api/v1/tasks/{run['task_id']}/events").json()
    assert any(e['type'] == 'tool_completed' for e in events['events'])
    assert not client.get(f"/api/v1/tasks/{run['task_id']}/events?after={events['next_after']}").json()['events']
    follow = client.post('/api/v1/research', json={'question': 'Redis RDB?', 'session_id': run['session_id']}).json()
    assert wait_task(client, follow['task_id'])['result']['citations']
    assert client.get('/health/ready').status_code == 200


def test_auth_validation_and_ui(client):
    assert client.get('/').status_code == 200
    js = client.get('/assets/app.js').text
    assert 'textContent' in js and '.innerHTML' not in js
    assert client.get('/api/v1/documents', headers={'X-API-Key': 'wrong'}).status_code == 401
    assert client.post('/api/v1/research', json={'question':'q','limits':{'max_steps':999}}).status_code == 422
    assert client.post('/api/v1/query', json={'query':'q','top_k':999}).status_code == 422
    assert client.post('/api/v1/documents', files={'file':('../bad.txt', b'text')}).status_code == 422
    assert client.get('/api/v1/tasks/missing').status_code == 404
    assert client.get('/api/v1/documents/a/chunks/b').status_code == 404


def test_upload_limit(settings):
    settings.max_upload_bytes = 1024
    with TestClient(create_app(settings)) as c:
        response = c.post('/api/v1/documents', headers={'X-API-Key':settings.api_key.get_secret_value()},
                          files={'file':('big.txt', b'x'*2048)})
        assert response.status_code == 413


def test_empty_research_http(client):
    task = client.post('/api/v1/research', json={'question':'No documents exist'}).json()
    assert wait_task(client, task['task_id'])['result']['insufficient_evidence']
