"""Hash every historical archive member; copy only declared inputs, no model calls."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

root = Path(__file__).resolve().parent
manifest = json.loads((root / 'archive/MANIFEST.json').read_text())
records = {item['path']: item for item in manifest['files']}
wanted = {'data/pendigits.tra'} | {
    f'campaign/fits/{arm}-s{seed}/{name}'
    for arm in ('flow', 'flow_fixed') for seed in (101, 211, 307)
    for name in ('selected.pt', 'RESULT.json', 'REQUEST.json')
}
seen = set()
copied = []
with tarfile.open(root / 'archive/originals.tar.xz', 'r:xz') as archive:
    for member in archive.getmembers():
        if not member.isfile() or member.name in seen:
            raise ValueError('invalid or duplicate archive member')
        seen.add(member.name)
        if member.name == 'MANIFEST.json':
            continue
        info = records[member.name]
        data = archive.extractfile(member).read()
        if len(data) != info['bytes'] or hashlib.sha256(data).hexdigest() != info['sha256']:
            raise ValueError(('hash mismatch', member.name))
        if member.name in wanted:
            rel = PurePosixPath(member.name)
            if rel.is_absolute() or '..' in rel.parts:
                raise ValueError('unsafe member')
            target = root / 'originals' / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as handle:
                handle.write(data)
            copied.append(info)
if seen != set(records) | {'MANIFEST.json'}:
    raise ValueError('member set')
(root / 'ORIGINAL_READBACK.json').write_text(json.dumps({
    'verified_members':len(records), 'copied':copied, 'model_calls':0,
    'optimizer_calls':0, 'archive_source_commit':manifest['source_commit'],
}, indent=2)+'\n')
print(json.dumps({'verified_members':len(records),'copied':len(copied)}))
