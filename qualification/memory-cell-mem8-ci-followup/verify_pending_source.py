"""Verify preserved source-only request bytes. This does not execute the request."""
import base64
import hashlib
import io
import json
import lzma
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent

def sha(data):
    return hashlib.sha256(data).hexdigest()

def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()

response = json.loads((ROOT / 'readback/PENDING_SOURCE_V3_GIT_READBACK.json').read_text())
data = base64.b64decode(''.join(response['content'].split()), validate=True)
assert response['encoding'] == 'base64'
assert blob(data) == response['sha'] == '5390733b88f56dcfae78f434b241dae5024c206e'
assert (len(data), sha(data)) == (359020, '5ffdd4b903b3b9fc433449d81ea263050033d18c6929fa4d92a069e4dec72b72')
files = {}
with tarfile.open(fileobj=io.BytesIO(data), mode='r:xz') as archive:
    members = archive.getmembers()
    assert len(members) == 16 and sum(item.size for item in members) < 1024 * 1024
    for item in members:
        path = PurePosixPath(item.name)
        assert not path.is_absolute() and '..' not in path.parts
        assert item.isfile() and not item.issym() and not item.islnk()
        assert item.name not in files and item.size <= 445681
        files[item.name] = archive.extractfile(item).read()
        assert len(files[item.name]) == item.size
manifest = json.loads(files['MANIFEST.json'])
assert len(manifest['files']) == 15
assert {row['path'] for row in manifest['files']} == set(files) - {'MANIFEST.json'}
for row in manifest['files']:
    content = files[row['path']]
    assert (len(content), sha(content), blob(content)) == (row['bytes'], row['sha256'], row['git_blob'])
request = json.loads(files['ORIGINAL_REQUEST.json'])
assert request['host'] == 'ai395' and request['executable'] == '/usr/bin/python3'
assert request['idempotency_key'] == 'mem8-integrated-repair-source-ai395-ed353817-v3'
assert request['timeout_seconds'] == 660
stdin = json.loads(request['stdin'])
assert len(stdin['files']) == 2
packed = base64.b64decode(stdin['files'][0], validate=True)
driver = base64.b64decode(stdin['files'][1], validate=True)
assert (len(packed), sha(packed)) == (312660, '39777a1141d4c74edfef38d67e7577cd659287d6e6a7045415278683faddd408')
assert driver == files['run_source_gates.py']
assert (len(driver), sha(driver)) == (20555, 'e7a5cb8878465394cbd047fedd2133205b19cabe273320e298b1728625a1e522')
decoder = lzma.LZMADecompressor()
plain = decoder.decompress(packed, max_length=2423958)
assert decoder.eof and not decoder.unused_data
assert (len(plain), sha(plain)) == (2423957, '18143912ffb6f5d558a19e793d925d3abd4c469bb90c429e84ff751ab8029146')
config = json.loads(plain)
index = json.loads(files['SOURCE_GATE_INDEX.json'])
assert config['execution_scope'] == 'source-only-format-caller-and-full-tree-scan'
assert config['published_parent_commit'] == '189711e3563ea13a5328d52e99a286f082045b98'
assert config['base_sha'] == '2ae5215beaf8d7b7df111a090b82134beae2683d'
assert config['prior_formatted_tree'] == 'e253b99e0a5c3b3a680569da0d224fabff0781ba'
assert len(config['files']) == len(index['files']) == 92
assert len(config['incremental_paths_since_published_parent']) == 31
assert len({row['path'] for row in config['files']}) == 92
for row, expected in zip(config['files'], index['files']):
    content = row['content'].encode()
    assert {key: value for key, value in row.items() if key != 'content'} == expected
    assert (len(content), sha(content), blob(content)) == (row['bytes'], row['sha256'], row['input_git_blob'])
for name in ('ORIGINAL_START.json', 'RECONCILE_SAME_KEY_1.json'):
    result = json.loads(files[name])
    assert result['isError'] and 'MCP request timed out' in json.dumps(result)
assert 'membership changed' in files['REGISTRY_RECONCILIATION.json'].decode()
assert blob(files['REGISTRY_RECONCILIATION.json']) == '43c54a86295193122d1df08c1826f776ac52c190'
audit = {
    'schema': 'hepta.mem8.pending-source-v3.root-readback.v1',
    'verified_at': datetime.now(timezone.utc).isoformat(),
    'immutable_commit': 'fd00e7162e9bfa5485b78ff5cd4013054c4065ee',
    'archive_members_verified': 16, 'manifest_rows_verified': 15,
    'all_source_file_postimages_verified': 92, 'incremental_paths': 31,
    'full_original_request_input_and_driver_verified': True,
    'original_key': request['idempotency_key'],
    'job_identity': 'UNKNOWN', 'admission': 'UNKNOWN', 'execution_terminal': 'UNKNOWN',
    'same_key_reconciliation_retained': True,
    'new_key_replay': False,
    'archive_programs_executed': 0, 'native_tests_executed': 0, 'model_requests_executed': 0,
}
(ROOT / 'ROOT_PENDING_SOURCE_READBACK_AUDIT.json').write_text(json.dumps(audit, indent=2) + '\n')
print(json.dumps(audit, indent=2))
