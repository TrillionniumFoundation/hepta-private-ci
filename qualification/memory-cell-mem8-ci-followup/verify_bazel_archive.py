"""Verify complete immutable lock evidence without executing archived programs."""
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile

ROOT = Path(__file__).resolve().parent
REF = '8aa84a4f608d3ffdbb2eed9eeb051e4c11cea4ad'

def identity(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}

objects = {}
for index in range(10):
    receipt = json.loads((ROOT / 'readback' / f'READBACK_{index}.json').read_text())
    assert receipt['ref'] == REF and not receipt['response']['isError']
    response = receipt['response']['structuredContent']
    assert response['encoding'] == 'base64'
    data = base64.b64decode(''.join(response['content'].split()), validate=True)
    assert identity(data)['git_blob'] == receipt['expected']['sha'] == response['sha']
    objects[index] = data
assert identity(objects[0]) == {'bytes': 41032, 'sha256': '905df89d53f17415e66ded52c60320fab05125ade53080bc481bcc0963944ad1',
                                'git_blob': 'e3c98f1e7380ebb5e2ddd17ca2ef179e6fac7de8'}
members = {}
with tarfile.open(fileobj=io.BytesIO(objects[0]), mode='r:xz') as archive:
    entries = archive.getmembers()
    assert len(entries) == 43 and sum(x.size for x in entries) < 2_000_000
    for entry in entries:
        path = PurePosixPath(entry.name)
        assert entry.isfile() and not path.is_absolute() and '..' not in path.parts
        assert entry.name not in members and str(path) == entry.name
        members[entry.name] = archive.extractfile(entry).read()
        assert len(members[entry.name]) == entry.size
assert members['MANIFEST.json'] == objects[1]
assert members['QUALIFICATION_RESULT.json'] == objects[2]
assert members['INDEPENDENT_AUDIT.json'] == objects[3]
manifest = json.loads(objects[1])
assert len(manifest['files']) == 42
assert {x['path'] for x in manifest['files']} == set(members) - {'MANIFEST.json'}
for entry in manifest['files']:
    assert identity(members[entry['path']]) == {key: entry[key] for key in ('bytes', 'sha256', 'git_blob')}

def read(name):
    return json.loads(members['records/' + name + '.json'])

receipt = read('lock-generate')
result = read('RESULT')
assert receipt['status'] == 'passed' and not receipt['timed_out']
assert all(receipt[key] == 0 for key in ('command_exit_code', 'exit_code', 'returncode'))
assert receipt['before'] == receipt['after'] and not receipt['before']['dirty']
assert receipt['before']['commit'] == '65ff5d15075f9193664ab0b5f74e2264cfe0c24c'
assert receipt['before']['tree'] == 'e253b99e0a5c3b3a680569da0d224fabff0781ba'
assert receipt['before']['parents'] == ['2ae5215beaf8d7b7df111a090b82134beae2683d']
raw = members['records/' + receipt['log_file']]
assert len(raw) == receipt['log_bytes'] == 4987
assert hashlib.sha256(raw).hexdigest() == receipt['log_sha256'] == 'b9611548ac59c858b88b7bfee1819c2c2b7f2dc7b9e4fa4ca9e50caac34bd13c'
assert b'bazel mod deps --lockfile_mode=update' in raw
assert b'fb3e52dd-7d24-4cb9-91b3-67364a71fe08' in raw
assert read('BASE_CHECKOUT_IDENTITY') == {'commit': '2ae5215beaf8d7b7df111a090b82134beae2683d', 'tree': '12159640adcf073b51f3837e75575e11f5c20233', 'status': ''}
assert read('BASE_INDEX_TREE')['actual'] == read('BASE_INDEX_TREE')['expected'] == '12159640adcf073b51f3837e75575e11f5c20233'
assert read('DONOR_BEFORE') == read('DONOR_AFTER')
assert read('TOOLS_BEFORE') == read('TOOLS_AFTER')
assert result['status'] == 'passed_local_candidate_lock_gate'
assert result['phase_receipts'] == ['lock-generate.json']
assert result['native_tests_executed'] == result['model_requests'] == 0
assert not result['first_generation_had_lock_drift'] and not result['published_reference_updated']
assert result['post_lock'] == {'bytes': 1788299, 'sha256': '783b3ad329fa53bd4a0e48be6907d38259fa2880d61bd1994b863d7f78bbca57', 'git_blob': '1565448430312c7fb7537a48f97e9cd2da945df3'}
assert members['records/lock-generate.patch'] == b''
assert members['original-driver/driver.stderr'] == b''
publication = json.loads(objects[4])
assert publication['expected_source_files'] == publication['verified_source_files'] == len(publication['files']) == 69
assert not publication['failures'] and all(x['full_remote_readback'] for x in publication['files'])
assert publication['source_candidate_tree'] == receipt['before']['tree']

audit = {'schema': 'hepta.mem8.bazel-lock.root-readback.v2',
         'verified_at': datetime.now(timezone.utc).isoformat(), 'immutable_commit': REF,
         'full_git_objects': 10, 'archive': identity(objects[0]), 'verified_members': 43,
         'manifest_rows_verified': 42, 'lock_gate_status': receipt['status'],
         'local_qualification_commit': receipt['before']['commit'], 'tree': receipt['before']['tree'],
         'published_source_commit': '189711e3563ea13a5328d52e99a286f082045b98',
         'local_and_published_commit_are_distinct': True, 'native_results_transferred': False,
         'raw_log': identity(raw), 'donor_and_tools_unchanged': True,
         'original_lock_phases': 1, 'lock_drift': False, 'post_lock': result['post_lock'],
         'source_postimages_published_and_fully_read_back': 69,
         'archived_programs_executed': 0, 'native_tests_executed': 0, 'model_requests_executed': 0}
(ROOT / 'ROOT_BAZEL_READBACK_AUDIT.json').write_text(json.dumps(audit, indent=2) + '\n')
print(json.dumps(audit, indent=2))
