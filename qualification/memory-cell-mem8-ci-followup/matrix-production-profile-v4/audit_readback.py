"""Audit original Matrix evidence; never runs the native suite."""
import base64
import hashlib
import io
import json
import re
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HEAD = 'f1fd544b3e12ed6aca83872cdeda8114a1e058c0'
TREE = 'fff40d06312d4f6a185772cd8a62a618d55f31cf'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()

publication = json.loads((ROOT.parent / 'mem8-matrix-diagnosis/PRODUCTION_V4_ARCHIVE_PUBLICATION.json').read_text())
archive_checks = []
for index, key in enumerate(('native', 'source')):
    result = json.loads((ROOT / f'READBACK_{index}.json').read_text())['structuredContent']
    raw = base64.b64decode(''.join(result['content'].split()), validate=True)
    expected = publication[key]
    assert len(raw) == expected['bytes']
    assert sha(raw) == expected['sha256']
    assert blob(raw) == result['sha'] == expected['git_blob']
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:xz') as archive:
        members = archive.getmembers()
        assert len(members) == expected['members']
        assert len({m.name for m in members}) == len(members)
        assert all(m.isfile() and not Path(m.name).is_absolute() and '..' not in Path(m.name).parts for m in members)
        data = {m.name: archive.extractfile(m).read() for m in members}
    manifest = json.loads(data['FILE_MANIFEST.json'])
    assert manifest['source']['head'] == HEAD and manifest['source']['tree'] == TREE
    assert manifest['source']['dirty'] is False
    assert {f['path'] for f in manifest['files']} | {'FILE_MANIFEST.json'} == set(data)
    for entry in manifest['files']:
        content = data[entry['path']]
        assert len(content) == entry['bytes']
        assert sha(content) == entry['sha256'] and blob(content) == entry['git_blob']
    archive_checks.append({'kind': key, 'archive_bytes': len(raw), 'archive_sha256': sha(raw), 'git_blob': blob(raw), 'complete_members': len(members), 'member_hashes_verified': len(manifest['files'])})

native = ROOT / 'readback/native'
source = ROOT / 'readback/source'
records = native / 'records'
result = json.loads((records / 'RESULT.json').read_text())
assert result['status'] == 'passed' and result['matrix_passed'] == 30
assert result['matrix_failed'] == result['matrix_selected_skipped'] == 0
assert result['source']['head'] == HEAD and result['source']['tree'] == TREE
assert result['scoped_fix_clean'] and result['model_calls'] == 0
receipts = []
for phase in ('matrix-consumers', 'matrix-scoped-fix'):
    receipt = json.loads((records / f'{phase}.json').read_text())
    raw = (records / receipt['log_file']).read_bytes()
    assert len(raw) == receipt['log_bytes'] and sha(raw) == receipt['log_sha256']
    assert receipt['exit_code'] == receipt['command_exit_code'] == receipt['returncode'] == 0
    assert receipt['status'] == 'passed' and receipt['timed_out'] is False
    assert receipt['output_limit_exceeded'] is False
    assert receipt['before'] == receipt['after']
    assert receipt['before']['commit'] == HEAD and receipt['before']['tree'] == TREE
    assert receipt['before']['dirty'] is False
    assert (records / f'{phase}.source-after.patch').read_bytes() == b''
    receipts.append({'phase': phase, 'bytes': len(raw), 'sha256': sha(raw), 'command': receipt['command'], 'started_at': receipt['started_at'], 'finished_at': receipt['finished_at']})

receipt = json.loads((records / 'matrix-consumers.json').read_text())
assert receipt['command'] == ['just','test','--locked','-p','codex-hepta-matrix-sdk','--test-threads','2','--no-tests','fail','--retries','0']
raw = (records / receipt['log_file']).read_text()
raw = re.sub(r'\x1b\[[0-9;]*m', '', raw)
passes = re.findall(r'^\s*PASS\s+\[[^\]]+\]\s+(?:\(\s*\d+/\d+\)\s+)?(\S+)\s+(\S+)\s*$', raw, re.M)
assert len(passes) == len(set(passes)) == 30
assert not re.search(r'^\s*(?:FAIL|RETRY|TRY\s+\d+|LEAK|ABORT)\b', raw, re.M)
assert re.search(r'Summary\s+\[[^\]]+\]\s+30 tests run: 30 passed, 2 skipped', raw)
junit_bytes = (records / 'matrix-consumers.junit.xml').read_bytes()
junit = ET.fromstring(junit_bytes)
cases = junit.findall('.//testcase')
assert len(cases) == 30
assert not junit.findall('.//failure') and not junit.findall('.//error') and not junit.findall('.//skipped')
ids = [(c.attrib['classname'], c.attrib['name']) for c in cases]
expected = [tuple(c) for c in json.loads((records / 'EXPECTED_CASES.json').read_text())]
assert sorted(passes) == sorted(ids) == sorted(expected)
assert len(set(expected)) == 30
uuid = '0b047180-e052-4017-b937-d88ca1387275'
assert junit.attrib['uuid'] == result['nextest_uuid'] == uuid
assert re.findall(r'Nextest run ID ([0-9a-f-]+)', raw) == [uuid]
assert sha(junit_bytes) != sha((records / 'matrix-consumers.preexisting-junit.xml').read_bytes())
assert (native / 'driver/run_production_profile_v4.py').read_bytes() == (ROOT.parent / 'mem8-matrix-diagnosis/run_production_profile_v4.py').read_bytes()

source_index = json.loads((source / 'SOURCE_INDEX.json').read_text())
assert source_index['base'] == '96038ccf0660154fac143ba6cbe4be81e00813e8'
assert source_index['parent'] == 'dc96a441312e239c165c1642880084dfeccc2c71'
assert len(source_index['files']) == 65
for entry in source_index['files']:
    data = (source / entry['path']).read_bytes()
    assert len(data) == entry['bytes'] and sha(data) == entry['sha256'] and blob(data) == entry['git_blob']
paths = {f['path'] for f in source_index['files']}
assert 'codex-rs/hepta-matrix-sdk/src/sdk.rs' not in paths
assert 'codex-rs/hepta-matrix-sdk/tests/store_version_migration.rs' not in paths
assert sha((source / 'codex-rs/Cargo.lock').read_bytes()) == result['source']['cargo_lock_sha256']
assert sha((source / 'MODULE.bazel.lock').read_bytes()) == result['source']['bazel_lock_sha256']

audit = {'schema':'hepta.mem8.matrix.root-readback-audit.v1','immutable_evidence_commit':'beed73b97df9797b1475deed6e460d5e551fa12f','source':result['source'],'archives':archive_checks,'native_receipts':receipts,'raw_case_ids_equal_junit_and_original_expected':True,'nextest_uuid':uuid,'actual_passed':30,'actual_failed':0,'actual_selected_skipped':0,'filtered_or_ignored_unselected':2,'retries_observed':0,'preexisting_junit_credited':False,'complete_changed_source_postimages_verified':65,'source_git_modes_not_reconstructed_from_archive':True,'scoped_fix_clean':True,'model_calls':0,'new_native_execution':False,'whole_repository_ci_qualified':False,'cross_version_migration_qualified':False,'passed':True}
(ROOT / 'ROOT_READBACK_AUDIT.json').write_text(json.dumps(audit,indent=2)+'\n')
print(json.dumps(audit,indent=2))
