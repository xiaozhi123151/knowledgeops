import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'reports'


def metadata(mode):
    commit = subprocess.run(['git','rev-parse','HEAD'], cwd=ROOT, capture_output=True, text=True, check=False)
    dirty = subprocess.run(['git','status','--porcelain'], cwd=ROOT, capture_output=True, text=True, check=False)
    sources = sorted((ROOT/'src').rglob('*')) + [ROOT/'pyproject.toml', ROOT/'uv.lock']
    source_hash = hashlib.sha256()
    for path in sources:
        if path.is_file() and path.suffix in ('.py','.js','.css','.html','.tiktoken','.toml','.lock'):
            source_hash.update(path.relative_to(ROOT).as_posix().encode()+b'\0'+path.read_bytes())
    return {'at_utc':datetime.now(timezone.utc).isoformat(), 'mode':mode, 'source_sha256':source_hash.hexdigest(),
            'git_commit':commit.stdout.strip(), 'working_tree_dirty':bool(dirty.stdout.strip()),
            'python':sys.version.split()[0], 'platform':platform.platform(),
            'dependencies':{name:version(name) for name in ['fastapi','pydantic','langgraph','qdrant-client','redis','rank-bm25']},
            'quality_warning':'OFFLINE TEST DOUBLES; NOT real model quality or production latency' if mode == 'offline' else
                              'See the per-provider and corpus boundary in this artifact; small samples are not production accuracy.'}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


@contextmanager
def api_client(mode, base_url='http://127.0.0.1:8000', report_prefix='run'):
    load_dotenv(ROOT / '.env', override=False)
    REPORTS.mkdir(exist_ok=True)
    process, temp, log = None, None, None
    if mode == 'offline':
        temp = tempfile.TemporaryDirectory(prefix='knowledgeops-')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base_url = f'http://127.0.0.1:{port}'
        env = {**os.environ, 'KO_MODE':'offline', 'KO_DATA_DIR':temp.name,
               'KO_LLM_PROVIDER':'mock',
               'KO_API_KEY':'offline-local-only', 'PYTHONUTF8':'1', 'KO_POLL_SECONDS':'0.05'}
        log = (REPORTS / f'{report_prefix}-server.log').open('w', encoding='utf-8')
        process = subprocess.Popen([sys.executable,'-m','uvicorn','knowledgeops.api.app:create_app','--factory',
                                    '--host','127.0.0.1','--port',str(port),'--log-level','warning'],
                                   cwd=ROOT, env=env, stdout=log, stderr=log,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    key = 'offline-local-only' if mode == 'offline' else os.environ.get('KO_API_KEY', '')
    client = httpx.Client(base_url=base_url, headers={'X-API-Key':key}, timeout=190)
    try:
        deadline = time.monotonic() + (35 if mode == 'offline' else 5)
        while True:
            try:
                ready = client.get('/health/ready', timeout=3)
                if ready.status_code == 200:
                    info = ready.json()
                    if info['mode'] != mode:
                        raise RuntimeError(f'Expected {mode}, server is {info["mode"]}; refusing misleading evaluation')
                    break
            except httpx.TransportError:
                pass
            if time.monotonic() > deadline or (process and process.poll() is not None):
                raise RuntimeError(f'API not ready at {base_url}; see reports/{report_prefix}-server.log')
            time.sleep(.1)
        yield client, info
    finally:
        client.close()
        if process:
            if os.name == 'nt' and process.poll() is None:
                # Windows venv python.exe may be a launcher with a child interpreter.
                # Terminating only the launcher leaks the server and its SQLite handles.
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],
                               capture_output=True, check=False,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            elif process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if log:
            log.close()
        if temp:
            for attempt in range(5):
                try:
                    temp.cleanup()
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(.2)


def request(client, method, path, **kwargs):
    response = client.request(method, '/api/v1' + path, **kwargs)
    response.raise_for_status()
    return response.json()


def wait_task(client, task_id, timeout=190):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = request(client, 'GET', '/tasks/' + task_id)
        if result['status'] in ('succeeded','failed','interrupted'):
            return result
        time.sleep(.05)
    raise TimeoutError(f'Task {task_id} not complete after {timeout}s')


def import_file(client, path):
    task = request(client, 'POST', '/documents', files={'file':(path.name,path.read_bytes())})
    result = wait_task(client, task['task_id'])
    if result['status'] != 'succeeded':
        raise RuntimeError(result['error'])
    return result['result']['doc_id']
