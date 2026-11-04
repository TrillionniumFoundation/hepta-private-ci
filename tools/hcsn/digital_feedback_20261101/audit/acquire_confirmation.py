"""Acquire immutable published #4578 archives and verify every recorded byte.
No training, model editing, fresh world generation, or parameter selection.
"""
import argparse, base64, concurrent.futures, gzip, hashlib, io, json, os, tarfile, time, urllib.request
from pathlib import Path, PurePosixPath
SOURCE = '903946f15dd79bc53a39a479230e366df04a371f'
ROOT = 'https://raw.githubusercontent.com/TrillionniumFoundation/hepta-private-ci/' + SOURCE + '/tools/hcsn/digital_feedback_20261101/'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def fetch(url, destination):
    if destination.exists():
        return destination.read_bytes()
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=45) as response:
                raw = response.read()
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(destination.suffix + '.partial')
            temporary.write_bytes(raw)
            temporary.replace(destination)
            return raw
        except Exception as exc:
            last = exc
            if attempt < 3:
                time.sleep(0.4 * (attempt + 1))
    raise last

def acquire(name, out):
    base = out / 'archives' / name
    raw_manifest = fetch(ROOT + 'archives/' + name + '/MANIFEST.json', base / 'MANIFEST.json')
    manifest = json.loads(raw_manifest)
    chunks = []
    for part in manifest['parts']:
        encoded = fetch(ROOT + 'archives/' + name + '/' + part['path'], base / part['path'])
        assert sha(encoded) == part['stored_sha256'], (name, part['path'], 'stored')
        raw = base64.b64decode(encoded.strip(), validate=True)
        assert sha(raw) == part['decoded_sha256'] and len(raw) == part['decoded_bytes'], (name, part['path'], 'decoded')
        chunks.append(raw)
    packed = b''.join(chunks)
    assert sha(packed) == manifest['archive_sha256'] and len(packed) == manifest['archive_bytes'], (name, 'archive')
    expected = {x['path']: x for x in manifest['files']}
    assert len(expected) == len(manifest['files']), (name, 'duplicate manifest')
    dest = out / 'restored' / name
    selected = []
    inventory = []
    all_bytes = 0
    with tarfile.open(fileobj=io.BytesIO(packed), mode='r:gz') as archive:
        members = archive.getmembers()
        assert len(members) == len(expected) and {m.name for m in members} == set(expected), (name, 'inventory')
        for member in members:
            p = PurePosixPath(member.name)
            assert member.isfile() and (not p.is_absolute()) and ('..' not in p.parts), (name, 'unsafe')
            raw = archive.extractfile(member).read()
            e = expected[member.name]
            assert len(raw) == e['bytes'] and sha(raw) == e['sha256'], (name, member.name, 'member')
            all_bytes += len(raw)
            if member.name.endswith(('.json', '.json.gz')) and (not member.name.startswith('worlds/')):
                target = dest / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                selected.append(member.name)
            inventory.append({'path': member.name, 'bytes': len(raw), 'sha256': e['sha256']})
    receipt = {'source': SOURCE, 'archive': name, 'manifest_sha256': sha(raw_manifest), 'archive_sha256': sha(packed), 'archive_bytes': len(packed), 'files_verified': len(inventory), 'uncompressed_bytes_verified': all_bytes, 'selected_members': selected}
    (base / 'ACQUISITION.json').write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'archive': name, 'files': len(inventory), 'bytes': len(packed), 'verified': True}), flush=True)
    return receipt

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--workers', type=int, default=2)
    p.add_argument('--fits', type=int, nargs='*')
    a = p.parse_args()
    out = a.output
    out.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    names = ['confirmation_001_control', 'training_002_control', 'development_001_control', 'development_002_control', 'training_001_control'] + ['confirmation_001_fit_' + str(f) for f in a.fits or range(6003, 6066, 2)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as ex:
        receipts = list(ex.map(lambda n: acquire(n, out), names))
    for name in ['protocol.json', 'statistics.py', 'quality.py', 'SOURCE_FREEZE.json', 'SEALED_MODELS.json', 'evidence/COST_DEV002.json', 'evidence/COST_FORMAL001.json', 'evidence/FIT_PLANNING_DEV002.json', 'evidence/DEVELOPMENT_FAILURE_LEDGER.json', 'audit/independent.py', 'evidence/MODELS_REMOTE.json', 'evidence/FINAL_PROTOCOL_SOURCE_AUDIT_V2.json', 'evidence/TRAINING_RECORDS_AUDIT.json']:
        fetch(ROOT + name, out / 'frozen' / name)
    result = {'source': SOURCE, 'receipts': receipts, 'archive_count': len(receipts), 'files_verified': sum((x['files_verified'] for x in receipts)), 'archive_bytes': sum((x['archive_bytes'] for x in receipts)), 'acquisition_wall_seconds': time.monotonic() - start, 'scope': 'Immutable published archive bytes verified; recorded summaries and raw records restored. No numerical validity claim from hash verification alone.'}
    (out / 'ACQUISITION.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'receipts'}), flush=True)
if __name__ == '__main__':
    main()
