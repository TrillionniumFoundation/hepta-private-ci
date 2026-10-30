import hashlib, io, json, shutil, stat, sys, tarfile
from pathlib import Path
from experiments.analytic_event_neuron.round6 import artifact_bundle as ab
source, out = map(Path, sys.argv[1:])
member_path = source / 'DEVELOPMENT_EVIDENCE_001_MANIFEST.json'
ab.require(ab.sha(member_path) == '31f50587439ffbb75385297860824d1f9e8fafb5cdd232c48e662caada61bbab', 'Member manifest changed')
manifest = json.loads(member_path.read_text(), object_pairs_hook=ab.unique)
complete = source / 'ROUND6_DEVELOPMENT_EVIDENCE_001.tar.gz'
if complete.exists():
    data = complete.read_bytes()
else:
    parts = json.loads((source / 'ROUND6_DEVELOPMENT_EVIDENCE_001_PARTS.json').read_text(), object_pairs_hook=ab.unique)
    ab.require(parts['schema'] == 'hepta.round6.binary-parts.v1' and len(parts['chunks']) == 6, 'Unknown development parts')
    chunks = []
    for i, part in enumerate(parts['chunks']):
        name = f'ROUND6_DEVELOPMENT_EVIDENCE_001.part{i:04d}'
        ab.require(Path(ab.safe(part['path'])).name == name, 'Unexpected part path')
        payload = (source / name).read_bytes()
        actual = ab.part_identity(name, payload)
        ab.require(len(payload) == part['bytes'] and actual['sha256'] == part['sha256']
                   and actual['git_blob_sha1'] == part['git_sha'], 'Part identity mismatch')
        chunks.append(payload)
    data = b''.join(chunks)
ab.require(len(data) == 3984039 and hashlib.sha256(data).hexdigest() ==
           '6be4c5bfc0d2ae329ca735f04d909f78459e43cdd627ba1c8235e1a719b1ea47', 'Development archive changed')
expected = {name: dict(entry, kind='file') for name, entry in manifest['files'].items()}
for name, entry in manifest['directories'].items():
    ab.require(name not in expected, 'Duplicate manifest member')
    expected[name] = dict(entry, kind='dir', bytes=0, sha256=None)
ab.check_tar(io.BytesIO(data), expected)  # All paths/types/modes/hashes checked first.
out.mkdir()  # Existing paths, including symlinks, are refused; parent must exist.
with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
    for item in archive:
        target = out / ab.safe(item.name)
        if item.isdir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(item) as incoming, target.open('xb') as saved:
                shutil.copyfileobj(incoming, saved)
            target.chmod(item.mode)
for name, entry in sorted(manifest['directories'].items(), reverse=True):
    (out / name).chmod(entry['mode'])
for name, entry in expected.items():
    target = out / name
    ab.require(stat.S_IMODE(target.stat().st_mode) == entry['mode'], 'Restored mode mismatch')
    if entry['kind'] == 'file':
        ab.require(target.stat().st_size == entry['bytes'] and ab.sha(target) == entry['sha256'], 'Restored bytes mismatch')
print('Verified development evidence:', out)
