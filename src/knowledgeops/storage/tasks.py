import json
import time
import uuid

from knowledgeops.storage.db import dumps


class LeaseLost(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    pass


class TaskStore:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings

    def limits(self, overrides=None):
        result = {k: getattr(self.settings, k) for k in
                  ('max_steps', 'max_llm_calls', 'max_tool_calls', 'token_budget', 'task_timeout')}
        for k, v in (overrides or {}).items():
            if v is not None:
                if k not in result or v > result[k] or v <= 0:
                    raise ValueError('LIMIT_CAN_ONLY_BE_LOWERED: ' + k)
                result[k] = v
        return result

    def create(self, kind, payload, session_id=None, overrides=None):
        task_id, now = uuid.uuid4().hex, time.time()
        limits = self.limits(overrides)
        budget = {'steps': 0, 'llm_calls': 0, 'tool_calls': 0, 'tokens': 0, 'estimated': False}
        with self.db.connect() as c:
            c.execute('INSERT INTO tasks(task_id,kind,session_id,payload,status,created,updated,limits_json,budget) '
                      'VALUES(?,?,?,?,?,?,?,?,?)', (task_id, kind, session_id, dumps(payload), 'queued', now, now,
                                                  dumps(limits), dumps(budget)))
            if session_id:
                c.execute('INSERT OR IGNORE INTO sessions(session_id) VALUES(?)', (session_id,))
        self.event(task_id, 'queued', {'kind': kind})
        return task_id

    def get(self, task_id):
        with self.db.connect() as c:
            row = c.execute('SELECT * FROM tasks WHERE task_id=?', (task_id,)).fetchone()
            if not row:
                return None
            value = dict(row)
            for key in ('payload', 'result', 'budget', 'limits_json'):
                value[key] = json.loads(value[key]) if value[key] else None
            return value

    def candidates(self):
        with self.db.connect() as c:
            return [r[0] for r in c.execute(
                "SELECT task_id FROM tasks WHERE status IN ('queued','interrupted') OR "
                "(status='running' AND lease < ?) ORDER BY created LIMIT 100", (time.time(),))]

    def worker_heartbeat(self):
        with self.db.connect() as c:
            c.execute("INSERT OR REPLACE INTO meta VALUES('worker_heartbeat',?)", (str(time.time()),))

    def worker_ready(self):
        with self.db.connect() as c:
            row = c.execute("SELECT value FROM meta WHERE key='worker_heartbeat'").fetchone()
            return bool(row and time.time() - float(row[0]) < self.settings.lease_seconds * 2)

    def claim(self, task_id, owner):
        now = time.time()
        with self.db.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT * FROM tasks WHERE task_id=?', (task_id,)).fetchone()
            if not row or row['status'] in ('succeeded', 'failed'):
                return False
            if row['status'] == 'running' and (row['lease'] or 0) >= now:
                return False
            if row['session_id'] and c.execute(
                "SELECT 1 FROM tasks WHERE session_id=? AND task_id != ? AND status IN "
                "('queued','running','interrupted') AND created < ? LIMIT 1",
                (row['session_id'], task_id, row['created'])).fetchone():
                return False
            limits = json.loads(row['limits_json'])
            c.execute("UPDATE tasks SET status='running',owner=?,lease=?,updated=?,started=COALESCE(started,?),"
                      "deadline=COALESCE(deadline,?) WHERE task_id=?",
                      (owner, now+self.settings.lease_seconds, now, now, now+limits['task_timeout'], task_id))
        self.event(task_id, 'claimed', {'resumed': row['started'] is not None})
        return True

    def assert_owner(self, c, task_id, owner):
        row = c.execute('SELECT * FROM tasks WHERE task_id=?', (task_id,)).fetchone()
        if not row or row['status'] != 'running' or row['owner'] != owner or row['lease'] < time.time():
            raise LeaseLost('TASK_LEASE_LOST')
        return row

    def heartbeat(self, task_id, owner):
        with self.db.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            self.assert_owner(c, task_id, owner)
            c.execute('UPDATE tasks SET lease=? WHERE task_id=?',
                      (time.time()+self.settings.lease_seconds, task_id))

    def reserve(self, task_id, owner, counter=None, tokens=0):
        with self.db.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = self.assert_owner(c, task_id, owner)
            if row['deadline'] <= time.time():
                raise BudgetExceeded('TASK_DEADLINE_EXCEEDED')
            budget, limits = json.loads(row['budget']), json.loads(row['limits_json'])
            if counter:
                budget[counter] += 1
                if budget[counter] > limits['max_' + counter]:
                    raise BudgetExceeded('BUDGET_EXCEEDED: ' + counter)
            budget['tokens'] += tokens
            if tokens:
                budget['pending_estimates'] = budget.get('pending_estimates', 0) + 1
                budget['estimated'] = True
            if budget['tokens'] > limits['token_budget']:
                raise BudgetExceeded('BUDGET_EXCEEDED: tokens')
            c.execute('UPDATE tasks SET budget=?,updated=? WHERE task_id=?',
                      (dumps(budget), time.time(), task_id))

    def settle(self, task_id, owner, reserved, actual):
        with self.db.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = self.assert_owner(c, task_id, owner)
            budget = json.loads(row['budget'])
            if actual is None:
                budget['estimated'] = True
            else:
                if not isinstance(actual, int) or actual < 0:
                    raise ValueError('INVALID_PROVIDER_USAGE')
                budget['tokens'] += actual - reserved
                budget['pending_estimates'] = max(0, budget.get('pending_estimates', 1) - 1)
                budget['estimated'] = budget['pending_estimates'] > 0
            c.execute('UPDATE tasks SET budget=? WHERE task_id=?', (dumps(budget), task_id))
            exceeded = budget['tokens'] > json.loads(row['limits_json'])['token_budget']
        if exceeded:
            raise BudgetExceeded('BUDGET_EXCEEDED: provider reported excess tokens')

    def cached(self, task_id, key):
        with self.db.connect() as c:
            row = c.execute('SELECT result FROM tool_results WHERE task_id=? AND call_key=?',
                            (task_id, key)).fetchone()
            return json.loads(row[0]) if row else None

    def cache(self, task_id, owner, key, result):
        with self.db.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            self.assert_owner(c, task_id, owner)
            c.execute('INSERT OR IGNORE INTO tool_results VALUES(?,?,?)', (task_id, key, dumps(result)))

    def event(self, task_id, event_type, data=None):
        with self.db.connect() as c:
            c.execute('INSERT INTO events(task_id,at,type,data) VALUES(?,?,?,?)',
                      (task_id, time.time(), event_type, dumps(data or {})))

    def events(self, task_id, after=0):
        with self.db.connect() as c:
            values = [dict(r) for r in c.execute('SELECT * FROM events WHERE task_id=? AND seq>? '
                                                'ORDER BY seq LIMIT 1000', (task_id, after))]
            for value in values:
                value['data'] = json.loads(value['data'])
            return values

    def finish(self, task_id, owner, result=None, error=None, interrupted=False):
        status = 'interrupted' if interrupted else ('failed' if error else 'succeeded')
        with self.db.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            self.assert_owner(c, task_id, owner)
            c.execute('UPDATE tasks SET status=?,result=?,error=?,updated=?,owner=NULL,lease=NULL WHERE task_id=?',
                      (status, dumps(result) if result is not None else None, error, time.time(), task_id))
        self.event(task_id, status, {'error': error} if error else {})

    def resume(self, task_id):
        with self.db.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT * FROM tasks WHERE task_id=?', (task_id,)).fetchone()
            if not row:
                raise KeyError(task_id)
            if row['status'] not in ('interrupted', 'running') or (
                row['status'] == 'running' and row['lease'] >= time.time()
            ):
                raise ValueError('TASK_NOT_RESUMABLE')
            if row['deadline'] and row['deadline'] <= time.time():
                raise ValueError('TASK_DEADLINE_EXCEEDED')
            c.execute("UPDATE tasks SET status='queued',owner=NULL,lease=NULL WHERE task_id=?", (task_id,))
        self.event(task_id, 'resume_requested')

    def history(self, session_id):
        with self.db.connect() as c:
            row = c.execute('SELECT messages FROM sessions WHERE session_id=?', (session_id,)).fetchone()
            return json.loads(row[0]) if row else []

    def complete_research(self, task_id, owner, session_id, question, report):
        # Session history and terminal status commit together: replay cannot append a duplicate turn.
        with self.db.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            self.assert_owner(c, task_id, owner)
            if session_id:
                row = c.execute('SELECT messages FROM sessions WHERE session_id=?', (session_id,)).fetchone()
                messages = json.loads(row[0]) if row else []
                messages += [{'role': 'user', 'content': question},
                             {'role': 'assistant', 'content': dumps(report)}]
                c.execute('UPDATE sessions SET messages=? WHERE session_id=?', (dumps(messages[-8:]), session_id))
            c.execute("UPDATE tasks SET status='succeeded',result=?,owner=NULL,lease=NULL,updated=? WHERE task_id=?",
                      (dumps(report), time.time(), task_id))
        self.event(task_id, 'succeeded')
