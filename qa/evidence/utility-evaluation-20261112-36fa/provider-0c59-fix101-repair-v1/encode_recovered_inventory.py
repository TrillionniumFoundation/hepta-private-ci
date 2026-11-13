#!/usr/bin/env python3
"""Encode the exact recovered actual inventory; compare every producer identity."""
from pathlib import Path
import base64
import gzip
import hashlib
import json

root = Path('/tmp/hepta-36fa-provider-0c59-fix101-repair-v1')
def pin(b):
    return {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()}
def save(name, raw):
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        assert p.read_bytes() == raw
    else:
        p.write_bytes(raw)

artifacts = json.loads((root / 'actual_inputs/ARTIFACTS.json').read_bytes())
observed = next(r for r in artifacts['files'] if r['name'] == 'final.inventory.json.gz')
raw = (root / 'ACTUAL_FINAL_INVENTORY.exact_recovered.json').read_bytes()
assert pin(raw) == {'bytes': observed['raw_bytes'], 'sha256': observed['raw_sha256'], 'git_blob': observed['raw_git_blob']}
compressed = gzip.compress(raw, mtime=0)
assert gzip.decompress(compressed) == raw
assert pin(compressed) == {k: observed[k] for k in ('bytes', 'sha256', 'git_blob')}
save('recovered-inventory/final.inventory.json.gz', compressed)
rows = []
for r in observed['parts']:
    off, size = r['decoded_offset'], r['decoded_bytes']
    payload = compressed[off:off + size]
    assert len(payload) == size and hashlib.sha256(payload).hexdigest() == r['decoded_sha256']
    part = base64.b64encode(payload) + b'\n'
    assert pin(part) == {k: r[k] for k in ('bytes', 'sha256', 'git_blob')}
    name = 'recovered-inventory/' + r['name']
    save(name, part)
    rows.append({'name': name, 'path': str(root / name), 'chars': len(part.decode()), **pin(part),
                 'decoded_offset': off, 'decoded_bytes': size, 'decoded_sha256': r['decoded_sha256']})
assert b''.join(base64.b64decode((root / r['name']).read_bytes(), validate=False) for r in rows) == compressed
review = {'format': 'hepta-recovered-actual-inventory-lossless-encoding-v1',
    'classification': 'Exact recovery from retained base and actual postimage, not a second native read.',
    'raw': pin(raw), 'gzip': pin(compressed), 'parts': rows,
    'matches_actual_artifacts_raw_gzip_and_every_part': True,
    'original_gzip_operation': 'gzip.compress(raw, mtime=0)',
    'original_split_bytes': 262144,
    'git_leaf_limit': 512000}
save('RECOVERED_INVENTORY_ENCODING.json', (json.dumps(review, indent=2, sort_keys=True) + '\n').encode())
print(json.dumps(review, indent=2))
