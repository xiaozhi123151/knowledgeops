import subprocess
import sys
import time
from pathlib import Path

import pytest

from knowledgeops.config import Settings
from knowledgeops.storage.db import Database
from knowledgeops.storage.tasks import TaskStore


@pytest.mark.process
def test_kill_and_restart_preserves_budget_and_evidence(tmp_path):
    helper = Path(__file__).parents[1] / 'helpers' / 'recovery_process.py'
    with (tmp_path / 'process.log').open('w', encoding='utf-8') as log:
        child = subprocess.Popen([sys.executable, str(helper), str(tmp_path), 'crash'], stdout=log, stderr=log)
        try:
            until = time.monotonic() + 25
            while not (tmp_path / 'crash-ready').exists() and child.poll() is None and time.monotonic() < until:
                time.sleep(.05)
            assert (tmp_path / 'crash-ready').exists(), (tmp_path / 'process.log').read_text(encoding='utf-8')
            task_id = (tmp_path / 'task-id').read_text()
            store = TaskStore(Database(tmp_path), Settings(_env_file=None, data_dir=tmp_path))
            before = store.get(task_id)['budget']
            assert before['llm_calls'] >= 2
            child.kill()
            child.wait(timeout=5)
            time.sleep(1.2)  # Deliberately wait for the child's one-second lease to expire.
            replay = subprocess.run([sys.executable, str(helper), str(tmp_path), 'resume'],
                                    stdout=log, stderr=log, timeout=25)
            assert replay.returncode == 0, (tmp_path / 'process.log').read_text(encoding='utf-8')
            final = store.get(task_id)
            assert final['status'] == 'succeeded', final['error']
            assert final['budget']['tokens'] >= before['tokens']
            assert final['budget']['llm_calls'] > before['llm_calls']
            assert len(final['result']['citations']) == 1
            events = store.events(task_id)
            searches = [e for e in events if e['type'] == 'tool_completed' and e['data']['name'] == 'knowledge_search']
            assert len(searches) == 1
            assert any(e['type'] == 'claimed' and e['data'].get('resumed') for e in events)
            assert len(store.history('resume-test')) == 2
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
