import asyncio
import hmac
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi import Query as QueryParam
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from knowledgeops.api.middleware import RequestBodyLimit
from knowledgeops.config import Settings
from knowledgeops.runtime import Runtime
from knowledgeops.schemas import Query, Research, URLImport
from knowledgeops.storage.tasks import TaskStore


def create_app(settings=None):
    settings = settings or Settings()
    @asynccontextmanager
    async def lifespan(app):
        runtime = await Runtime(settings).start(background_worker=settings.mode == 'offline')
        app.state.runtime = runtime
        try:
            yield
        finally:
            await runtime.close()
    app = FastAPI(title='KnowledgeOps', version='0.1.0', lifespan=lifespan)
    app.add_middleware(RequestBodyLimit, max_bytes=settings.max_upload_bytes + 65536)

    async def authorize(x_api_key: str = Header(default='')):
        if not hmac.compare_digest(x_api_key.encode(), settings.api_key.get_secret_value().encode()):
            raise HTTPException(401, 'Invalid API key')

    router = APIRouter(prefix='/api/v1', dependencies=[Depends(authorize)])

    def runtime():
        return app.state.runtime

    def task_or_404(task_id):
        task = runtime().store.get(task_id)
        if task is None:
            raise HTTPException(404, 'Task not found')
        # Payloads and lease owner are internal, not public task state.
        return {k: v for k, v in task.items() if k not in ('payload', 'owner', 'lease')}

    @router.post('/documents', status_code=202)
    async def upload(file: Annotated[UploadFile, File()]):
        data = bytearray()
        try:
            while block := await file.read(65536):
                data.extend(block)
                if len(data) > settings.max_upload_bytes:
                    raise HTTPException(413, 'UPLOAD_TOO_LARGE')
            payload = await asyncio.to_thread(runtime().ingestion.save_upload, bytes(data), file.filename)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            await file.close()
        task_id = runtime().store.create('ingest', payload)
        await runtime().notify(task_id)
        return {'task_id': task_id, 'mode': settings.mode}

    @router.post('/documents/url', status_code=202)
    async def import_url(request: URLImport):
        task_id = runtime().store.create('ingest', request.model_dump())
        await runtime().notify(task_id)
        return {'task_id': task_id, 'mode': settings.mode}

    @router.get('/documents')
    async def documents():
        return {'documents': runtime().db.documents(), 'mode': settings.mode}

    @router.delete('/documents/{doc_id}')
    async def delete_document(doc_id: str):
        try:
            if not await runtime().ingestion.delete(doc_id):
                raise HTTPException(404, 'Document not found')
        except (ConnectionError, TimeoutError) as exc:
            raise HTTPException(503, 'DELETE_DEPENDENCY_FAILED; retry deletion') from exc
        return {'deleted': doc_id, 'raw_files_retained': True}

    @router.get('/documents/{doc_id}/chunks/{chunk_id}')
    async def source(doc_id: str, chunk_id: str):
        chunk = runtime().db.chunk(doc_id, chunk_id)
        if not chunk:
            raise HTTPException(404, 'Source chunk not found')
        return chunk

    @router.post('/query')
    async def query(request: Query):
        try:
            async with asyncio.timeout(settings.tool_timeout):
                return await runtime().engine.search(request)
        except TimeoutError as exc:
            raise HTTPException(504, 'RETRIEVAL_TIMEOUT') from exc
        except Exception as exc:
            raise HTTPException(503, 'RETRIEVAL_DEPENDENCY_FAILED') from exc

    @router.post('/research', status_code=202)
    async def research(request: Research):
        session_id = request.session_id or uuid.uuid4().hex
        try:
            # Validate before any task is persisted.
            TaskStore(runtime().db, settings).limits(request.limits.model_dump(exclude_none=True))
            task_id = runtime().store.create('research', {'question': request.question}, session_id=session_id,
                                              overrides=request.limits.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        await runtime().notify(task_id)
        return {'task_id': task_id, 'session_id': session_id, 'mode': settings.mode}

    @router.get('/tasks/{task_id}')
    async def task_status(task_id: str):
        return {**task_or_404(task_id), 'mode': settings.mode}

    @router.get('/tasks/{task_id}/events')
    async def task_events(task_id: str, after: int = QueryParam(0, ge=0)):
        task_or_404(task_id)
        events = runtime().store.events(task_id, after)
        return {'events': events, 'next_after': events[-1]['seq'] if events else after}

    @router.post('/tasks/{task_id}/resume', status_code=202)
    async def resume(task_id: str):
        task_or_404(task_id)
        try:
            runtime().store.resume(task_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        await runtime().notify(task_id)
        return {'task_id': task_id, 'mode': settings.mode}

    @app.get('/health/live')
    async def live():
        return {'status': 'alive', 'mode': settings.mode}

    @app.get('/health/ready')
    async def ready():
        rt = runtime()
        checks = {'sqlite': False, 'qdrant': False, 'redis': settings.mode == 'offline',
                  'worker': rt.store.worker_ready() if settings.mode == 'live' else
                  (rt.worker is not None and not rt.worker.done())}
        try:
            rt.db.version()
            checks['sqlite'] = True
            await asyncio.wait_for(asyncio.to_thread(rt.engine.client.get_collections), timeout=2)
            checks['qdrant'] = True
            if rt.queue:
                checks['redis'] = bool(await asyncio.wait_for(rt.queue.client.ping(), timeout=2))
        except Exception:
            pass
        return JSONResponse({'ready': all(checks.values()), 'checks': checks, 'mode': settings.mode,
                             'trace': rt.trace.status,
                             'index_fingerprint': rt.engine.fingerprint,
                             'llm_provider': settings.resolved_llm_provider,
                             'llm_is_mock': settings.resolved_llm_provider == 'mock',
                             'retrieval_is_mock': settings.resolved_embedding_provider == 'mock' or
                                                  settings.resolved_reranker_provider == 'mock',
                             'qdrant_backend': settings.resolved_qdrant_backend,
                             'providers': {'llm': rt.llm.name, 'embedding': rt.embedding.name,
                                           'reranker': rt.reranker.name}},
                            status_code=200 if all(checks.values()) else 503)

    app.include_router(router)
    web = Path(__file__).parents[1] / 'web'
    app.mount('/assets', StaticFiles(directory=web), name='assets')
    @app.get('/', include_in_schema=False)
    async def index():
        return FileResponse(web / 'index.html')
    return app
