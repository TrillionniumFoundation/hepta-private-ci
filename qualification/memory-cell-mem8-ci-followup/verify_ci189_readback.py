"""Root offline verification of the immutable original CI archive."""
import base64
import hashlib
import io
import json
import lzma
import re
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent

def sha(data):
    return hashlib.sha256(data).hexdigest()

def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()

objects = []
for index in range(3):
    item = json.loads((ROOT / 'readback' / f'CI189_READBACK_{index}.json').read_text())
    response = item['response']
    assert response['encoding'] == 'base64'
    data = base64.b64decode(''.join(response['content'].split()), validate=True)
    assert blob(data) == response['sha'] == item['expected']['sha']
    assert data == (ROOT / 'readback' / f'CI189_OBJECT_{index}').read_bytes()
    objects.append(data)
assert (len(objects[0]), sha(objects[0])) == (344748, '2f8d10568b3d4faf6bdb1927615b08f5497c159f6720d240a88b6516f9296873')
files = {}
with tarfile.open(fileobj=io.BytesIO(objects[0]), mode='r:xz') as archive:
    members = archive.getmembers()
    assert len(members) == 35 and sum(item.size for item in members) < 1024 * 1024
    for item in members:
        path = PurePosixPath(item.name)
        assert not path.is_absolute() and '..' not in path.parts
        assert item.isfile() and not item.issym() and not item.islnk()
        assert item.name not in files and item.size <= 200000
        files[item.name] = archive.extractfile(item).read()
        assert len(files[item.name]) == item.size
assert files['MANIFEST.json'] == objects[1] and files['INDEX.json'] == objects[2]
manifest = json.loads(objects[1])
index = json.loads(objects[2])
assert len(manifest['files']) == 34
assert {row['path'] for row in manifest['files']} == set(files) - {'MANIFEST.json'}
for row in manifest['files']:
    data = files[row['path']]
    assert (len(data), sha(data), blob(data)) == (row['bytes'], row['sha256'], row['git_blob'])
logs = {}
assert len(index['raw_logs']) == 6
for row in index['raw_logs']:
    stored = files[row['path']]
    assert len(stored) == row['stored_bytes'] and sha(stored) == row['stored_sha256']
    if row['encoding'] == 'xz':
        decoder = lzma.LZMADecompressor()
        raw = decoder.decompress(stored, max_length=row['raw_bytes'] + 1)
        assert decoder.eof and not decoder.unused_data
    else:
        assert row['encoding'] == 'utf-8'
        raw = stored
    assert len(raw) == row['raw_bytes'] and sha(raw) == row['raw_sha256']
    logs[str(row['job_id'])] = raw.decode('utf-8').splitlines()

observations = json.loads(files['derived/FAILURE_BLOCKS.json'])
counts = {}
for group in ('model', 'infer', 'neuron', 'hardlink', 'remote_control'):
    rows_by_job = observations[group]
    if isinstance(rows_by_job, list):
        job = '130461514744' if group == 'hardlink' else '130461514980'
        rows_by_job = {job: rows_by_job}
    for job, rows in rows_by_job.items():
        for row in rows:
            lines = logs[job][row['line_start'] - 1:row['line_end']]
            assert lines[-1] == row['summary']
            clean = [re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '',
                            re.sub(r'^\d{4}-\d\d-\d\dT\S+Z ', '', line)) for line in lines]
            data = ('\n'.join(clean) + '\n').encode()
            assert (len(data), sha(data)) == (row['bytes'], row['sha256'])
        counts[f'{group}:{job}'] = {'printed': len(rows), 'unique_normalized_payloads': len({row['sha256'] for row in rows})}
assert [row['sha256'] for row in observations['model']['130461514712']] == [row['sha256'] for row in observations['model']['130461514922']]
assert counts['hardlink:130461514744'] == {'printed': 4, 'unique_normalized_payloads': 3}
assert counts['infer:130461514980'] == counts['neuron:130461514980'] == {'printed': 2, 'unique_normalized_payloads': 1}

receipt = json.loads(files['derived/SIGNED_CREDIT_RECEIPT_FROM_RAW.json'])
for state in ('before', 'after'):
    assert receipt[state]['commit'] == index['source_head'] == '189711e3563ea13a5328d52e99a286f082045b98'
    assert receipt[state]['tree'] == index['source_tree'] == 'e253b99e0a5c3b3a680569da0d224fabff0781ba'
    assert not receipt[state]['dirty']
assert receipt['command_exit_code'] == receipt['exit_code'] == receipt['observed_failed_tests'] == 0
assert receipt['observed_passed_tests'] == receipt['named_pass_rows'] == 1
assert receipt['command'][-2:] == ['--retries', '0']
merge = json.loads(files['records/CI_MERGE_COMMIT.json'])
assert merge['sha'] == index['tested_pr_merge'] == '83b67d85bc8ba58ca1f4e758efdc32dbe5f11c58'
assert merge['tree']['sha'] == index['source_tree']
assert index['source_head'] in {parent['sha'] for parent in merge['parents']}
audit = {
    'schema': 'hepta.mem8.root-ci189-readback.v13',
    'verified_at': datetime.now(timezone.utc).isoformat(),
    'immutable_commit': 'ecbbd495009d78ab995225cb437f6f98575e4bf7',
    'archive': {'bytes': len(objects[0]), 'sha256': sha(objects[0]), 'git_blob': blob(objects[0])},
    'members_verified': 35, 'manifest_rows_verified': 34, 'complete_original_logs_verified': 6,
    'normalized_failure_observations_verified': counts,
    'original_action_merge_commit': merge['sha'],
    'source_commit': index['source_head'], 'shared_tree': index['source_tree'],
    'original_commit_identities_kept_distinct': True,
    'windows_private_signed_credit': {'passed': 1, 'failed': 0, 'retries': 0, 'scope': 'Exact 189711 receipt printed in complete original job log; separate workflow artifact not downloaded by this verifier.'},
    'overall_ci_pass': False,
    'archived_programs_executed': 0, 'native_tests_executed': 0, 'model_requests_executed': 0,
}
(ROOT / 'ROOT_CI189_READBACK_AUDIT.json').write_text(json.dumps(audit, indent=2) + '\n')
print(json.dumps(audit, indent=2))
