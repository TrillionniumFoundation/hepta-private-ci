#!/usr/bin/env python3
"""Make a small provided-object input and explicit artifact/hash semantics."""
import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def pin(b):
    return {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(), 'git_blob': hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()}

def write(name, b):
    with (ROOT / name).open('xb') as out:
        out.write(b)
    return {'path': name, **pin(b)}

def main():
    complete = json.loads((ROOT / 'BASE_OBJECT_PACKET.json').read_bytes())
    small = {'format': 'hepta-c0f-format-base-provided-objects-v1', 'status': 'PREPARED_NOT_APPROVED_FOR_EXECUTION', 'base': complete['base'], 'objects': complete['provided_objects'], 'complete_closure_identity_manifest': complete['complete_base_closure']['identity_manifest'], 'required_existing_count': 16011, 'provided_count': 83, 'native_execution': False, 'source_mutation': False}
    raw = (json.dumps(small, sort_keys=True, separators=(',', ':')) + '\n').encode()
    raw_pin = write('BASE_OBJECT_INPUT.json', raw)
    compressed = gzip.compress(raw, compresslevel=9, mtime=0)
    gzip_pin = write('BASE_OBJECT_INPUT.json.gz', compressed)
    parts = []
    for n, offset in enumerate(range(0, len(compressed), 196608)):
        decoded = compressed[offset:offset + 196608]
        encoded = base64.b64encode(decoded) + b'\n'
        parts.append({**write('BASE_OBJECT_INPUT.json.gz.part-%03d.b64' % (n + 1), encoded), 'decoded_bytes': len(decoded), 'decoded_offset': offset, 'decoded_sha256': hashlib.sha256(decoded).hexdigest()})
    manifest = {'schema': 'hepta-c0f-format-base-transport-input-manifest-v1', 'raw': raw_pin, 'gzip': gzip_pin, 'parts': parts, 'complete_proof_packet': pin((ROOT / 'BASE_OBJECT_PACKET.json').read_bytes()), 'meaning': 'All 83 original raw bodies in this small input are supplied. The full closure manifest is immutable separate evidence. Existing 16011 objects must still be verified from the approved source and the resulting complete base tree must be checked. This is not a runnable request or fresh availability observation.'}
    manifest_raw = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
    manifest_pin = write('TRANSPORT_INPUT_MANIFEST.json', manifest_raw)
    previous = (ROOT / 'FINAL_REVIEW.json').read_bytes()
    review = json.loads(previous)
    commit_raw = (ROOT / 'C0F_COMMIT.raw').read_bytes()
    original_field = review.pop('canonical_commit_raw_original')
    assert original_field['git_blob'] == complete['base']['commit']
    review['canonical_commit_raw_original'] = {'bytes': len(commit_raw), 'sha256': hashlib.sha256(commit_raw).hexdigest(), 'git_object_type': 'commit', 'git_object_sha': complete['base']['commit'], 'raw_file_git_blob': pin(commit_raw)['git_blob']}
    review['field_semantics_note'] = {'earlier_computed_review': pin(previous), 'reason': 'The earlier generic identity helper labels its typed Git hash field git_blob even when called with kind=commit. This v2 explicitly distinguishes the real commit OID from the Git blob used to retain its raw file. No body, object identity, inventory, object count or scope changed.', 'earlier_field_preserved': original_field}
    review['transport_input'] = {'manifest': manifest_pin, 'raw': raw_pin, 'gzip': gzip_pin}
    review_raw = (json.dumps(review, sort_keys=True, indent=2) + '\n').encode()
    review_pin = write('FINAL_REVIEW_v2.json', review_raw)
    print(json.dumps({'input': raw_pin, 'gzip': gzip_pin, 'parts': len(parts), 'manifest': manifest_pin, 'review': review_pin, 'commit_raw_file': pin(commit_raw)}, sort_keys=True))

if __name__ == '__main__':
    main()
