"""Recheck original G archive bytes and outcomes, without native execution."""
import hashlib
import io
import json
import re
import tarfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NATIVE = ROOT / 'readback/native'
FORMAT = ROOT / 'readback/formatter/records'
HEAD = '9d9bdfbaeeec3c618f3fc80e2f663a29c13f4b27'
TREE = '07192603a5164f4b5d4da24e37595be2a0a04777'
EXPECTED = {
    'app_runtime::tests::episodic_embedding_keeps_the_store_but_removes_implicit_memory_paths',
    'episodic_import::source_read::tests::episodic_source_observation_follows_commit_generation_not_ack_order',
    'production_composition::tests::episodic_control::drain::episodic_import_cancellation_cannot_overtake_owner_settlement',
    'production_composition::tests::episodic_control::episodic_config_cannot_create_a_missing_production_writer',
    'production_composition::tests::episodic_control::episodic_control_replays_original_commit_then_rejects_revoked_context',
    'production_composition::tests::episodic_control::episodic_wire_without_configured_source_cannot_mutate_original_owner',
}

def sha(value):
    return hashlib.sha256(value).hexdigest()

def blob(value):
    return hashlib.sha1(b'blob ' + str(len(value)).encode() + b'\0' + value).hexdigest()

def load(path):
    return json.loads(path.read_text())

for name, size, digest, git in [
    ('native.tar.xz', 49292, '3babe551f6a029803467dbc89f5ea949c88b93916bb20c3638bb5ba276b50a75', '887bd1823ce74a0e579dac39deae6bd9a77fae8c'),
    ('formatter.tar.xz', 41624, 'd2fee84f30985c162ef778c9956c033c74f252bef8be5a7c03ae84c290056c14', '82b44ef97739e5e1afb1fb993d16de1545517a4e'),
    ('static.tar.xz', 20424, '791f0503aa970ea041ce4e4bf1f485bd280657593ba2c2127b4a5d16e95ce1af', '37cb563274566a559352724e36a1f52c7cfb69be'),
]:
    raw = (ROOT / name).read_bytes()
    assert len(raw) == size and sha(raw) == digest and blob(raw) == git

manifest = load(NATIVE / 'FILE_MANIFEST.json')
actual = {str(p.relative_to(NATIVE)) for p in NATIVE.rglob('*') if p.is_file()}
assert len(manifest) == 66
assert {row['path'] for row in manifest} | {'FILE_MANIFEST.json'} == actual
for row in manifest:
    raw = (NATIVE / row['path']).read_bytes()
    assert len(raw) == row['bytes'] and sha(raw) == row['sha256']
index = load(ROOT / 'G_COMPLETE_EVIDENCE_INDEX.json')
assert index['archive_member_manifest']['entries'] == manifest
assert sha((NATIVE / 'INPUT.json').read_bytes()) == '207c3f7969198cb6564113aaf6fccdb1a5f028c34cdb90bd8e85866576aca9e2'

result = load(NATIVE / 'NATIVE_RESULT.json')
assert result['status'] == 'passed' and result['failure'] is None
assert result['source_sha'] == HEAD and result['source_tree'] == TREE
assert result['ignored_provider_case_selected'] is False
assert result['provider_requests_authorized'] is False
assert datetime.fromisoformat(result['finished_at']) < datetime.fromisoformat(result['deadline_utc'])
before = load(NATIVE / 'records/source-before.json')
after = load(NATIVE / 'records/source-after.json')
assert before == after == {'head': HEAD, 'tree': TREE, 'status': ''}
assert result['source_after'] == after
assert result['original_after'] == {'head':'0c32926cfec58d986477fc72ba3a4787ab75fde9','tree':'0d5aa1544aad103f9099c7c8347d8075d6ecc76e','status':''}
for name in ('source-rewrites.patch', 'index-rewrites.patch'):
    assert (NATIVE / 'records' / name).read_bytes() == b''
receipt_checks = []
for phase in ('format', 'v8-inputs', 'codex-cli-build', 'agentd-tests', 'fix-codex-hepta-agentd'):
    receipt = load(NATIVE / 'records' / (phase + '.json'))
    raw = (NATIVE / 'records' / receipt['log_file']).read_bytes()
    assert sha(raw) == receipt['log_sha256'] and len(raw) == receipt['log_bytes']
    assert receipt['source_sha'] == receipt['tested_sha'] == HEAD
    assert receipt['before'] == receipt['after']
    assert receipt['before']['commit'] == HEAD and receipt['before']['tree'] == TREE and not receipt['before']['dirty']
    assert receipt['status'] == 'passed' and receipt['exit_code'] == receipt['command_exit_code'] == receipt['returncode'] == 0
    assert not receipt['timed_out'] and not receipt['output_limit_exceeded']
    receipt_checks.append({'phase':phase, 'log_bytes':len(raw), 'log_sha256':sha(raw)})
receipt = load(NATIVE / 'records/agentd-tests.json')
command = receipt['command']
assert command[0:2] == ['just','test'] and '--no-capture' in command and '--run-ignored' not in command
assert command[command.index('--retries') + 1] == '0'
assert set(re.findall(r'test\(=([^)]*)\)', command[command.index('-E') + 1])) == EXPECTED
text = (NATIVE / 'records' / receipt['log_file']).read_text()
text = re.sub(r'\x1b\[[0-9;]*m', '', text)
rows = re.findall(r'^\s*PASS\s+\[[^]]+\]\s+\(\s*\d+/\d+\)\s+(\S+)\s+(\S+)\s*$', text, re.M)
assert len(rows) == len(set(rows)) == 6
assert {package for package, _ in rows} == {'codex-hepta-agentd'}
assert {case for _, case in rows} == EXPECTED
assert not re.search(r'^\s*(?:FAIL|RETRY|TRY\s+[2-9])\b', text, re.M)
assert re.findall(r'Nextest run ID ([0-9a-f-]+)', text) == ['b58361b0-49b7-47f2-a15a-43ee34823b29']
assert re.search(r'Summary\s+\[[^]]+\]\s+6 tests run: 6 passed, 782 skipped', text)
assert sorted(re.findall(r'^episodic-drain-case-complete:(commit|revoke|panic)\s*$', text, re.M)) == ['commit','panic','revoke']
binary = load(NATIVE / 'records/codex-binary.json')
binary_after = load(NATIVE / 'records/codex-binary-after.json')
assert binary['sha256'] == binary_after['sha256'] == '49bfbb583bc08a549f8f023880875d2541473f5ec9b3ddd613298855fdf3e976'
assert binary['bytes'] == binary_after['bytes'] == 559365856
assert binary_after['matches_initial'] and binary_after['source_sha'] == HEAD
assert binary['source_sha'] == HEAD and binary['source_tree'] == TREE
env = load(NATIVE / 'records/environment-controls.json')
assert not env['ignored_provider_case_selected'] and env['provider_enabled_variables'] == []

formatted = load(FORMAT / 'FORMAT_RESULT.json')
assert formatted['formatter_exit_code'] == 0 and formatted['formatter_paths_outside_candidate'] == []
assert formatted['model_calls_run'] == formatted['builds_run'] == formatted['tests_run'] == 0
assert len(formatted['artifacts']) == 34 and len(formatted['steps']) == 26
for row in formatted['artifacts']:
    raw = (FORMAT / row['path']).read_bytes()
    assert sha(raw) == row['sha256'] and len(raw) == row['bytes']
for step in formatted['steps']:
    raw = (FORMAT / step['log']).read_bytes()
    assert step['exit_code'] == 0
    assert sha(raw) == step['log_sha256'] and len(raw) == step['log_bytes']
for suffix in ('head', 'tree', 'status'):
    assert (FORMAT / ('donor-before-' + suffix + '.log')).read_bytes() == (FORMAT / ('donor-after-' + suffix + '.log')).read_bytes()
source_files = load(FORMAT / 'FILE_MANIFEST.json')
assert len(source_files) == 4
with tarfile.open(NATIVE / 'records/changed-source-before.tar.xz', 'r:xz') as archive:
    assert {m.name for m in archive.getmembers()} == {row['path'] for row in source_files}
    for row in source_files:
        raw = archive.extractfile(row['path']).read()
        assert raw == (FORMAT / 'postimages' / row['path']).read_bytes()
        assert len(raw) == row['output_bytes'] and sha(raw) == row['output_sha256'] and blob(raw) == row['output_git_blob']
with tarfile.open(NATIVE / 'records/changed-source-after.tar.xz', 'r:xz') as archive:
    assert archive.getmembers() == []
static = ROOT / 'readback/static'
sm = load(static / 'PACKAGE_MANIFEST.json')
assert {row['path'] for row in sm['files']} | {'PACKAGE_MANIFEST.json'} == {str(p.relative_to(static)) for p in static.rglob('*') if p.is_file()}
for row in sm['files']:
    raw = (static / row['path']).read_bytes()
    assert len(raw) == row['bytes'] and sha(raw) == row['sha256'] and blob(raw) == row['git_blob']
current = load(ROOT / 'CURRENT_SOURCES_G.json')
assert current['head'] == HEAD and current['tree'] == TREE and len(current['files']) == 38
assert blob((ROOT / 'CURRENT_SOURCES_G.json').read_bytes()) == '7117afdc5735c361eb0b441340cf8e24d131500e'
audit = {'schema':'hepta.mem8.g.root-independent-readback.v1','immutable_commit':'44bde0a4b5bed568032a3b0ba28022c731ffe621','source_sha':HEAD,'source_tree':TREE,'native_archive_members':67,'all_66_native_member_hashes':True,'phase_receipts':receipt_checks,'actual_passed':6,'actual_failed':0,'filtered_or_ignored_unselected':782,'selected_provider_case_executions':0,'nextest_uuid':'b58361b0-49b7-47f2-a15a-43ee34823b29','drain_markers':['commit','revoke','panic'],'formatter_members':43,'formatter_artifacts':34,'formatter_raw_logs':26,'four_native_source_files_equal_formatter_and_published_blobs':True,'source_and_binary_before_after_unchanged':True,'binary_sha256':binary['sha256'],'binary_bytes':binary['bytes'],'static_archive_members':12,'current_source_inventory_paths':38,'original_input_sha256':'207c3f7969198cb6564113aaf6fccdb1a5f028c34cdb90bd8e85866576aca9e2','new_native_execution':False,'model_calls':0,'real_memory_use_claimed':False,'unseen_successor_benefit_claimed':False,'passed':True}
(ROOT / 'ROOT_G_READBACK_AUDIT.json').write_text(json.dumps(audit,indent=2)+'\n')
print(json.dumps(audit,indent=2))
