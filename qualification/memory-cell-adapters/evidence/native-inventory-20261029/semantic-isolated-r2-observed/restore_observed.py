"""Verify the received-observations archive; only then extract to a new directory."""
from pathlib import Path
import base64, hashlib, io, json, sys, tarfile
root = Path(__file__).resolve().parent
record = json.loads((root/'ARCHIVE.json').read_bytes())
raw = base64.b64decode((root/record['encoded_path']).read_text().strip(),validate=True)
assert len(raw) == record['archive_bytes'] and hashlib.sha256(raw).hexdigest() == record['archive_sha256']
destination = Path(sys.argv[1])
assert not destination.exists()
with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
    members = archive.getmembers()
    assert len({member.name for member in members}) == len(members)
    for member in members:
        assert member.isfile() and not member.name.startswith('/') and '..' not in Path(member.name).parts
    manifest_raw = archive.extractfile('MANIFEST.json').read()
    assert hashlib.sha256(manifest_raw).hexdigest() == record['manifest_sha256']
    manifest = json.loads(manifest_raw)
    expected = {row['path']:row for row in manifest['files']}
    assert set(expected) == {member.name for member in members}-{'MANIFEST.json'}
    payload = {}
    for name,row in expected.items():
        data = archive.extractfile(name).read()
        assert len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256']
        payload[name] = data
destination.mkdir()
(destination/'MANIFEST.json').write_bytes(manifest_raw)
for name,data in payload.items():
    target = destination/name; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(data)
print(json.dumps({'state':'verified','files':len(payload),'full_remote_raw_archive_received':False}))
