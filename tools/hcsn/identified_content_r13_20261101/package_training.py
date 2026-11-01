"""Deterministic, independently verifiable archives of every fit and source datum."""

import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parent


def archive(name, members):
    target = ROOT/name
    if target.exists():
        raise FileExistsError(target)
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w') as tar:
        for path in sorted(members):
            data = path.read_bytes()
            info = tarfile.TarInfo(str(path.relative_to(ROOT)))
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            tar.addfile(info, io.BytesIO(data))
    target.write_bytes(gzip.compress(raw.getvalue(), mtime=0))
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(members)}
    with tarfile.open(target, 'r:gz') as tar:
        check = {m.name: hashlib.sha256(tar.extractfile(m).read()).hexdigest() for m in tar.getmembers()}
    if check != hashes:
        raise AssertionError('Archive round-trip identity mismatch')
    return {'file': name, 'bytes': target.stat().st_size,
            'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'members': hashes}


if __name__ == '__main__':
    protocol = json.loads((ROOT/'PROTOCOL.json').read_text())
    records = []
    for i in range(0, len(protocol['seeds']), 2):
        members = []
        for seed in protocol['seeds'][i:i+2]:
            for core in protocol['cores']:
                stem = f'{seed}_{core}'
                members += [ROOT/'evidence/fits'/f'{stem}.json',
                            ROOT/'evidence/receipts'/f'{stem}.json',
                            ROOT/'evidence/logs'/f'{stem}.txt']
        records.append(archive(f'TRAINING_{i//2+1:02d}.tar.gz', members))
    records.append(archive('DATA_AND_FRONTEND.tar.gz', [ROOT/'data/sms_spam_collection.zip',
        ROOT/'evidence/frontend.json', ROOT/'evidence/frontend_receipt.json',
        ROOT/'evidence/frontend_log.txt', ROOT/'evidence/FRONTEND_RECEIPT_SCOPE.json']))
    (ROOT/'TRAINING_ARCHIVES.json').write_text(json.dumps({'archives':records}, indent=2)+'\n')
    print(json.dumps([{k:v for k,v in r.items() if k!='members'} for r in records], indent=2))
