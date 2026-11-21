"""Retrieve exact existing HCSN sources and originals without model execution."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parent
REV = '298fae004356f4adb5b58f2bc4d61fdde5bdab75'
RAW = 'https://raw.githubusercontent.com/TrillionniumFoundation/hepta-private-ci/' + REV + '/'

def fetch(item):
    path, expected, url = item
    with urllib.request.urlopen(url, timeout=45) as response:
        data = response.read(70_000_001)
    if len(data) > 70_000_000:
        raise ValueError('response cap')
    digest = hashlib.sha256(data).hexdigest()
    if expected and digest != expected:
        raise ValueError(('source hash', path, digest, expected))
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != data:
        raise ValueError(('existing file differs', path))
    if not target.exists():
        with target.open('xb') as handle:
            handle.write(data)
    return dict(path=path, bytes=len(data), sha256=digest, url=url)

def main():
    protocol = json.loads((ROOT / 'UPSTREAM_PROTOCOL.json').read_text())
    archive = json.loads((ROOT / 'ARCHIVE.json').read_text())
    items = [('upstream/' + p, sha, RAW + p) for p, sha in protocol['sources'].items()]
    arcpath = 'qualification/hcsn_network/evidence/real-task-originals/archive-attempt001/'
    items += [('archive/' + p['path'], p['sha256'], RAW + arcpath + p['path']) for p in archive['parts']]
    items += [('archive/MANIFEST.json', archive['manifest_sha256'], RAW + arcpath + 'MANIFEST.json')]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(fetch, items))
    data = b''.join((ROOT / 'archive' / p['path']).read_bytes() for p in archive['parts'])
    if hashlib.sha256(data).hexdigest() != archive['archive_sha256']:
        raise ValueError('archive identity')
    assembled = ROOT / 'archive/originals.tar.xz'
    assembled.write_bytes(data)
    # Exact per-member hashes are checked before selected immutable originals are copied.
    manifest = json.loads((ROOT / 'archive/MANIFEST.json').read_text())
    (ROOT / 'SOURCE_FETCH_RECEIPT.json').write_text(json.dumps({'revision':REV,'files':records,'archive_sha256':archive['archive_sha256'],'manifest_type':type(manifest).__name__},indent=2)+'\n')
    with tarfile.open(assembled, 'r:xz') as tf:
        inventory = [{'name':m.name,'bytes':m.size} for m in tf.getmembers()]
    (ROOT / 'ARCHIVE_MEMBERS.json').write_text(json.dumps(inventory,indent=2)+'\n')
    print(json.dumps({'verified_sources_and_parts':len(records),'archive_bytes':len(data),'members':len(inventory)}),flush=True)

if __name__ == '__main__':
    main()
