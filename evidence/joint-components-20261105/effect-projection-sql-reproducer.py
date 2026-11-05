"""SQL-level reproducer for the frozen Hepta effect-frontier omission.

This executes the exact SELECTs extracted from the upstream Rust source against
its upstream SQLite migrations. It is not a Rust/native or PQ end-to-end test.
"""
from pathlib import Path
import hashlib
import json
import re
import sqlite3

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'original/codex-rs/hepta-evidence/src/recovery_effect_frontier.rs'
MIGRATIONS = ROOT / 'source-evidence/migrations'
SHA = '1556a4df6e279055fd8196f81a4ca2fe0f19384a'
DOMAIN = b'hepta.evidence.provider-effect-frontier.v1'

def digest(data):
    return hashlib.sha256(data).hexdigest()

def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'))

queries = re.findall(r'\(\s*"(intent|ack|uncertainty)",\s*"(SELECT.*?)",\s*\)', SOURCE.read_text(), re.S)
assert len(queries) == 3
connection = sqlite3.connect(':memory:')
connection.row_factory = sqlite3.Row
connection.execute('PRAGMA foreign_keys = ON')
for name in ['0007_provider_effect_evidence.sql', '0008_provider_effect_ack_source.sql', '0016_provider_effect_observation_history.sql']:
    connection.executescript((MIGRATIONS / name).read_text())
key = 'provider-effect:v1:' + digest(b'projection regression operation')
payload = digest(b'exact effect payload')
operation = digest(b'original provider operation')
intent = {'schema_version': 1, 'key': key, 'payload_sha256': payload}
ack = dict(intent, provider_operation_id_sha256=operation, status='completed')
uncertainty = dict(intent, reason_code='lost_response')
intent_json, ack_json, uncertainty_json = map(canonical, [intent, ack, uncertainty])
connection.execute('INSERT INTO provider_effect_intents(effect_key,payload_sha256,schema_version,payload_json,record_sha256,recorded_at_ms) VALUES(?,?,?,?,?,?)', (key,payload,1,intent_json,digest(intent_json.encode()),1))
connection.execute('INSERT INTO provider_effect_uncertainties(effect_key,payload_sha256,reason_code,schema_version,payload_json,record_sha256,recorded_at_ms) VALUES(?,?,?,?,?,?,?)', (key,payload,'lost_response',1,uncertainty_json,digest(uncertainty_json.encode()),2))
connection.execute('INSERT INTO provider_effect_acknowledgements(effect_key,payload_sha256,provider_operation_id_sha256,status,schema_version,payload_json,record_sha256,recorded_at_ms,source) VALUES(?,?,?,?,?,?,?,?,?)', (key,payload,operation,'completed',1,ack_json,digest(ack_json.encode()),3,'status_lookup'))

def upstream_snapshot():
    previous = digest(DOMAIN + b'\0')
    count = 0
    for kind, query in queries:
        lower = -(1 << 63)
        while lower is not None:
            rows = connection.execute(query, (lower,256)).fetchall()
            if not rows:
                break
            for row in rows:
                assert row['seq'] > 0
                assert digest(row['payload_json'].encode()) == row['record_sha256']
                assert row['source'] is not None
                parts = [kind.encode(),row['seq'].to_bytes(8,'big',signed=True),row['effect_key'].encode(),row['record_sha256'].encode(),row['recorded_at_ms'].to_bytes(8,'big',signed=True),row['source'].encode()]
                message = DOMAIN + b'\0' + previous.encode()
                for part in parts:
                    message += len(part).to_bytes(8,'big') + part
                previous = digest(message)
                count += 1
                lower = row['seq']+1 if row['seq'] < (1<<63)-1 else None
    return count, previous

for table in ['provider_effect_intents','provider_effect_acknowledgements','provider_effect_uncertainties']:
    connection.execute(f'DROP TRIGGER {table}_no_update')
before = upstream_snapshot()
results=[]
for table,column,value in [
    ('provider_effect_intents','payload_sha256',digest(b'changed projection')),
    ('provider_effect_acknowledgements','payload_sha256',digest(b'changed projection')),
    ('provider_effect_acknowledgements','provider_operation_id_sha256',digest(b'changed operation')),
    ('provider_effect_acknowledgements','status','accepted'),
    ('provider_effect_uncertainties','payload_sha256',digest(b'changed projection')),
    ('provider_effect_uncertainties','reason_code','different_reason'),
]:
    old=connection.execute(f'SELECT {column} FROM {table}').fetchone()[0]
    connection.execute(f'UPDATE {table} SET {column}=?',(value,))
    after=upstream_snapshot()
    row=connection.execute(f'SELECT * FROM {table}').fetchone()
    payload_key=column
    assert row[column] != json.loads(row['payload_json'])[payload_key]
    assert after == before
    results.append({'table':table,'changed_column':column,'canonical_projection_disagrees':True,'upstream_snapshot_unchanged':True})
    connection.execute(f'UPDATE {table} SET {column}=?',(old,))
    assert upstream_snapshot()==before
print(json.dumps({'source_commit':SHA,'level':'SQLite + exact upstream SELECTs and digest encoding; native Rust not executed','sqlite_version':sqlite3.sqlite_version,'snapshot_rows':before[0],'snapshot_sha256':before[1],'omitted_projection_cases':results},indent=2))
