"""Root offline verification from complete immutable Git envelope readbacks.

Never execute archive scripts, native tests, models, or CI jobs.
"""
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parent
READ = ROOT / 'root-readback'


def info(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def check(data, expected):
    assert info(data) == {key: expected[key] for key in ('bytes', 'sha256', 'git_blob')}


index_bytes = (READ / 'MEM_ARCHIVE_INDEX.json').read_bytes()
assert info(index_bytes)['git_blob'] == '7bd1c3b5ab6a2a2df882ae909326c3690a76295a'
index = json.loads(index_bytes)
parts = []
for row in index['parts']:
    encoded = (READ / f"mem-envelope-{row['index']}.json").read_bytes()
    check(encoded, {key: row['envelope_' + key] for key in ('bytes', 'sha256', 'git_blob')})
    part = json.loads(encoded)
    data = base64.b64decode(part['content'], validate=True)
    check(data, row)
    assert row['offset'] == sum(map(len, parts))
    parts.append(data)
archive = b''.join(parts)
check(archive, index['archive'])
with tarfile.open(fileobj=io.BytesIO(archive), mode='r:xz') as tar:
    members = tar.getmembers()
    assert len(members) == 23
    assert len({row.name for row in members}) == len(members)
    for row in members:
        path = PurePosixPath(row.name)
        assert row.isfile() and not path.is_absolute() and '..' not in path.parts
    files = {row.name: tar.extractfile(row).read() for row in members}
manifest = json.loads(files['EVIDENCE_MANIFEST.json'])
assert {row['path'] for row in manifest['files']} == set(files) - {'EVIDENCE_MANIFEST.json'}
for row in manifest['files']:
    check(files[row['path']], row)
audit = json.loads(files['ORIGINAL_ARTIFACT_AUDIT.json'])
assert audit['source_commit'] == '189711e3563ea13a5328d52e99a286f082045b98'
assert audit['source_tree'] == 'e253b99e0a5c3b3a680569da0d224fabff0781ba'
observed = []
receipt_count = member_count = 0
ansi = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
for artifact in audit['artifacts']:
    raw_zip = files[str(artifact['artifact_id']) + '.zip']
    check(raw_zip, artifact['zip'])
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as zip_file:
        entries = zip_file.infolist()
        assert len(entries) == len({entry.filename for entry in entries})
        payload = {}
        for entry in entries:
            path = PurePosixPath(entry.filename)
            assert not path.is_absolute() and '..' not in path.parts
            assert not entry.is_dir()
            payload[entry.filename] = zip_file.read(entry)
    assert set(payload) == {row['path'] for row in artifact['members']}
    for row in artifact['members']:
        check(payload[row['path']], row)
    member_count += len(payload)
    total = 0
    frameworks = {}
    for row in artifact['receipts']:
        receipt_count += 1
        check(payload[row['receipt']], row['receipt_identity'])
        check(payload[row['raw_log']], row['raw_identity'])
        receipt = json.loads(payload[row['receipt']])
        raw = payload[row['raw_log']]
        assert (receipt['log_bytes'], receipt['log_sha256']) == (len(raw), info(raw)['sha256'])
        assert Path(receipt['log_file']).name == row['raw_log']
        assert receipt['command'] == row['command']
        assert receipt['tested_sha'] == row['tested_sha']
        assert receipt['before'] == receipt['after']
        assert receipt['before']['dirty'] is False
        assert receipt['before']['tree'] == audit['source_tree']
        assert receipt['source_sha'] == audit['source_commit']
        assert receipt['status'] == 'passed' and receipt['exit_code'] == 0
        assert receipt['timed_out'] is False and receipt['output_limit_exceeded'] is False
        if artifact['role'] == 'architecture-base-merge':
            assert receipt['tested_sha'] == 'dc87587b1aa8edb94694fb8938cdabcb8ef4dec6'
        else:
            assert receipt['tested_sha'] == audit['source_commit']
        text = ansi.sub('', raw.decode())
        framework = row['actual']['framework']
        if framework == 'nextest':
            summaries = re.findall(r'^\s*Summary \[[^\]]+\]\s+(\d+) tests? run: (\d+) passed(?:, (\d+) failed)?', text, re.M)
            assert len(summaries) == 1
            count, passed, failed = (int(value or 0) for value in summaries[0])
            assert count == passed and failed == 0
        elif framework == 'cargo-libtest':
            summaries = re.findall(r'^test result: ok\. (\d+) passed; (\d+) failed;', text, re.M)
            assert summaries
            count = sum(int(passed) for passed, failed in summaries)
            assert all(int(failed) == 0 for passed, failed in summaries)
        elif framework == 'unittest':
            summaries = re.findall(r'^Ran (\d+) tests? in [^\n]+$', text, re.M)
            assert len(summaries) == 1
            assert re.search(r'^OK\s*$', text, re.M)
            count = int(summaries[0])
        elif framework == 'non-test-command':
            count = 0
        else:
            raise AssertionError('Unreviewed framework: ' + framework)
        assert count == row['actual']['executions'] == row['actual']['passed']
        assert row['actual']['failed'] == 0
        total += count
        frameworks[framework] = frameworks.get(framework, 0) + count
    assert total == artifact['actual_test_executions']
    assert artifact['failed_test_executions'] == 0
    observed.append({'artifact_id': artifact['artifact_id'], 'role': artifact['role'],
                     'members': len(payload), 'receipts': len(artifact['receipts']),
                     'actual_test_executions': total, 'framework_executions': frameworks})
assert member_count == 217 and receipt_count == 49
assert {row['role']: row['actual_test_executions'] for row in observed} == {
    'mem-native': 17, 'mem-python': 119, 'mem-integrity': 35,
    'architecture-base-merge': 136, 'architecture-source-head': 664,
}
result = {'schema': 'mem8.root.ci189.mem-architecture.readback.v1',
          'verified_at': datetime.now(timezone.utc).isoformat(),
          'status': 'PASS_OFFLINE_ORIGINAL_BYTE_AND_COUNT_AUDIT',
          'index': info(index_bytes), 'archive': info(archive),
          'full_git_envelopes': 5, 'outer_members': 23, 'zip_members': 217,
          'receipts_and_raw_logs': 49, 'artifacts': observed,
          'distinct_tests_across_lanes_not_claimed': True,
          'original_mem_feature_qualification_not_observed': True,
          'original_mem_protocol_and_fixes_skipped': True,
          'memory_benefit_actor_executions_added_by_audit': 0,
          'archived_code_executed': False, 'native_tests_executed_by_audit': 0,
          'model_requests_executed_by_audit': 0}
result['verifier_history'] = [{'attempt': 1, 'status': 'stopped_before_audit_output',
    'reason': 'Strict summary regex expected plural tests; original selector-role summary is 1 test run.'},
    {'attempt': 2, 'status': 'passed', 'change': 'Recognize original singular and plural grammar; counts and all byte gates unchanged.'}]
(ROOT / 'ROOT_MEM_ARCH_READBACK_AUDIT.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
