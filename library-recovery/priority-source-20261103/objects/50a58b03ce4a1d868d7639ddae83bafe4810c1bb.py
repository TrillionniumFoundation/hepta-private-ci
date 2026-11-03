import sqlite3
import re
import pathlib
import json
import hashlib

source = pathlib.Path('/workspace/shared/taskflow-observation-current/codex-rs/hepta-automation/src/pending_occurrence_scan.rs').read_text()
def query(name):
    if name == 'PENDING_OCCURRENCE_WINDOW_SQL':
        return re.search(r'macro_rules! pending_occurrence_window_sql\s*\{\s*\(\)\s*=>\s*\{\s*"([^"]+)"', source).group(1)
    return re.search(name + r': &str\s*=\s*"([^"]+)"', source).group(1)
window = query('PENDING_OCCURRENCE_WINDOW_SQL')
point = query('PENDING_OCCURRENCE_LOOKUP_SQL')
results = []
for retained in (100, 1000, 10000):
    for state in ('running', 'succeeded'):
        connection = sqlite3.connect(':memory:')
        connection.executescript('CREATE TABLE automation_tasks(task_id TEXT PRIMARY KEY,owner_agent_id TEXT,thread_id TEXT,prompt TEXT); CREATE TABLE automation_occurrence_lifecycle(task_id TEXT,occurrence INTEGER,owner_agent_id TEXT,state TEXT,recovery_phase TEXT,updated_at_ms INTEGER,PRIMARY KEY(task_id,occurrence)); CREATE INDEX automation_occurrence_recovery_idx ON automation_occurrence_lifecycle(owner_agent_id,recovery_phase,updated_at_ms,task_id,occurrence); CREATE INDEX automation_occurrence_task_state_idx ON automation_occurrence_lifecycle(task_id,state,occurrence);')
        connection.executemany('INSERT INTO automation_tasks VALUES(?,?,?,?)', ((f'task-{index:06}', 'owner', 'thread', 'prompt') for index in range(1, retained + 1)))
        connection.execute("INSERT INTO automation_occurrence_lifecycle SELECT task_id,1,owner_agent_id,?,'awaiting_terminal',1 FROM automation_tasks", (state,))
        plan = connection.execute('EXPLAIN QUERY PLAN ' + window, (0, retained)).fetchall()
        assert all('TEMP B-TREE' not in str(row) for row in plan)
        operations = [0]
        def progress():
            operations[0] += 1
            return int(operations[0] > 8192)
        connection.set_progress_handler(progress, 1)
        first = connection.execute('SELECT rowid FROM automation_occurrence_lifecycle ORDER BY rowid LIMIT 1').fetchone()[0]
        last = connection.execute('SELECT rowid FROM automation_occurrence_lifecycle ORDER BY rowid DESC LIMIT 1').fetchone()[0]
        rows = connection.execute(window, (0, last)).fetchall()
        target = connection.execute(point, ('task-000001', 1, 'owner')).fetchone()
        connection.set_progress_handler(None, 0)
        assert (first, last, len(rows), rows[-1][0]) == (1, retained, 64, 64)
        assert bool(target) == (state == 'running')
        results.append({'retained': retained, 'state': state, 'vm_steps': operations[0], 'physical_rows': len(rows), 'plan': plan})
        connection.close()
for state in ('running', 'succeeded'):
    counts = [row['vm_steps'] for row in results if row['state'] == state]
    assert max(counts) - min(counts) <= 64
result = {'scope': 'Python SQLite exact-query plan/VM probe; native SQLx tests authored but unrun', 'sqlite_version': sqlite3.sqlite_version, 'window_sql_sha256': hashlib.sha256(window.encode()).hexdigest(), 'point_sql_sha256': hashlib.sha256(point.encode()).hexdigest(), 'measurements': results, 'limitations': '64 rows and flat VM counts are not a hard byte, memory, physical I/O or wall-clock bound'}
pathlib.Path('/workspace/shared/taskflow-ordinary-audit/SQL_WORK_BOUND.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
