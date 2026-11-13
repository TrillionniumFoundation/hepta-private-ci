"""Lossless metadata packaging only. Does not create source Git objects."""
from pathlib import Path
import base64
import gzip
import hashlib
import json

ROOT = Path('/tmp/hepta-36fa-full-candidate-graph-v1')
CHUNK = 196608


def pin(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


records = []
for name in ('CANDIDATE_FILE_GRAPH.json', 'TREE_IDENTITIES.json'):
    raw = (ROOT / name).read_bytes()
    compressed = gzip.compress(raw, compresslevel=9, mtime=0)
    assert gzip.decompress(compressed) == raw
    gzip_name = name + '.gz'
    assert not (ROOT / gzip_name).exists()
    (ROOT / gzip_name).write_bytes(compressed)
    parts = []
    for index, offset in enumerate(range(0, len(compressed), CHUNK), 1):
        chunk = compressed[offset:offset + CHUNK]
        encoded = base64.b64encode(chunk) + b'\n'
        part_name = f'{gzip_name}.part-{index:03}.b64'
        assert not (ROOT / part_name).exists()
        (ROOT / part_name).write_bytes(encoded)
        parts.append({'name': part_name, **pin(encoded), 'decoded_offset': offset,
                      'decoded_bytes': len(chunk), 'decoded_sha256': hashlib.sha256(chunk).hexdigest()})
    rebuilt = b''.join(base64.b64decode((ROOT / part['name']).read_bytes(), validate=False) for part in parts)
    assert rebuilt == compressed and gzip.decompress(rebuilt) == raw
    records.append({'name': name, 'raw': pin(raw), 'gzip_name': gzip_name,
                    'gzip': pin(compressed), 'parts': parts,
                    'raw_or_gzip_blob_directly_uploaded': False,
                    'storage': 'Lossless encoded parts, not a claim that the computed raw/gzip blob is stored as a standalone Git object'})

manifest = {'format': 'hepta-mode-aware-source-graph-lossless-encoding-v1',
            'qualification': False, 'gzip_mtime': 0, 'decoded_part_max_bytes': CHUNK,
            'all_local_reconstructions_equal': True, 'artifacts': records,
            'canonical_inventory_reused': {'raw_git_blob': '7f94788b70546a8b8030dfd2b9182a7d9287c537',
                                         'storage': 'Existing five published original parts, referenced in INPUT_RECOVERY_PROOF.json; not uploaded again'},
            'base_file_graph': {'local': 'BASE_FILE_GRAPH.json', **pin((ROOT / 'BASE_FILE_GRAPH.json').read_bytes()),
                               'storage': 'Deterministic projection from the retained canonical inventory and derive_graph.py; no duplicate large base graph upload'}}
(ROOT / 'ENCODING_MANIFEST.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
print(json.dumps({'manifest': pin((ROOT / 'ENCODING_MANIFEST.json').read_bytes()),
                  'artifacts': [{'name': item['name'], 'raw': item['raw'], 'gzip': item['gzip'],
                                 'parts': len(item['parts'])} for item in records]}, indent=2))
