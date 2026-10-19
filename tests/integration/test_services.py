from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from knowledgeops.api.app import create_app
from knowledgeops.harness.trace import Trace
from knowledgeops.worker.queue import RedisQueue


def test_web_import_and_dependency_health(settings, monkeypatch):
    monkeypatch.setattr('knowledgeops.ingestion.service.fetch_page', lambda url: (
        b'<html><main><h1>Vector knowledge</h1><p>Qdrant indexes vectors.</p></main></html>', url))
    from http_helpers import wait_task
    with TestClient(create_app(settings)) as client:
        client.headers['X-API-Key'] = settings.api_key.get_secret_value()
        task = client.post('/api/v1/documents/url', json={'url':'https://example.test/note'}).json()
        assert wait_task(client, task['task_id'])['result']['doc_id']
        hit = client.post('/api/v1/query', json={'query':'Qdrant vectors'}).json()['hits'][0]
        assert hit['chunk']['source'] == 'https://example.test/note'
        monkeypatch.setattr(client.app.state.runtime.engine.client, 'get_collections',
                            MagicMock(side_effect=ConnectionError('injected Qdrant outage')))
        assert client.get('/health/ready').status_code == 503
        assert client.get('/health/live').status_code == 200


async def test_queue_protocol_and_deferred_notification(settings):
    queue = RedisQueue(settings)
    real_client = queue.client
    queue.client = MagicMock()
    queue.client.xautoclaim = AsyncMock(return_value=['0-0', [('1-0', {'task_id':'a'})], []])
    queue.client.xack = AsyncMock()
    queue.client.xadd = AsyncMock()
    await queue.enqueue('a')
    assert await queue.take() == ('1-0', {'task_id':'a'})
    await queue.ack('1-0')
    queue.client.xack.assert_awaited_once_with(queue.stream, queue.group, '1-0')
    await real_client.aclose()


async def test_trace_is_optional_and_export_failure_is_nonfatal(settings):
    trace = Trace(settings)
    assert trace.status == 'disabled'
    trace.emit('event', {'task_id':'a'})
    trace.client = MagicMock()
    trace.client.start_as_current_observation.side_effect = ConnectionError('injected trace failure')
    trace.emit('event', {'task_id':'a'})
    await trace.close()
    assert trace.client.start_as_current_observation.called


async def test_queue_failure_keeps_durable_task(settings):
    from knowledgeops.runtime import Runtime
    runtime = await Runtime(settings).start()
    try:
        runtime.queue = MagicMock()
        runtime.queue.enqueue = AsyncMock(side_effect=RedisConnectionError('offline'))
        runtime.queue.close = AsyncMock()
        task_id = runtime.store.create('ingest', {'url':'https://example.test'})
        await runtime.notify(task_id)
        assert runtime.store.get(task_id)['status'] == 'queued'
        assert runtime.store.events(task_id)[-1]['type'] == 'queue_deferred'
    finally:
        await runtime.close()


async def test_chunked_request_body_limit():
    from knowledgeops.api.middleware import RequestBodyLimit
    async def app(scope, receive, send):
        await receive()
        await receive()
    chunks = iter([{'type':'http.request','body':b'x'*8,'more_body':True},
                   {'type':'http.request','body':b'x'*8,'more_body':False}])
    async def receive():
        return next(chunks)
    messages = []
    async def send(message):
        messages.append(message)
    await RequestBodyLimit(app, 10)({'type':'http','headers':[]}, receive, send)
    assert messages[0]['status'] == 413
