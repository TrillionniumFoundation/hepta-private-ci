#!/usr/bin/env python3
"""Package already fetched and hash-verified format-base bytes; no native access."""
import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def identity(raw, kind='blob'):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob': hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + '\n').encode('utf-8')

def write_new(name, raw):
    path = ROOT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as out:
        out.write(raw)
    return {'path': name, **identity(raw)}

def encode_parts(name, raw):
    compressed = gzip.compress(raw, compresslevel=9, mtime=0)
    gzip_pin = write_new(name + '.gz', compressed)
    parts = []
    for i, start in enumerate(range(0, len(compressed), 196608)):
        block = compressed[start:start + 196608]
        encoded = base64.b64encode(block) + b'\n'
        pin = write_new(name + '.gz.part-%03d.b64' % (i + 1), encoded)
        parts.append({**pin, 'decoded_offset': start, 'decoded_bytes': len(block), 'decoded_sha256': hashlib.sha256(block).hexdigest()})
    return {'raw': {'path': name, **identity(raw)}, 'gzip': gzip_pin, 'parts': parts, 'encoding': 'Each piece is an independent canonical base64 encoding of a contiguous gzip byte slice plus one LF. Strict-decode each; concatenate bytes; gunzip.'}

def main():
    delta = json.loads((ROOT / 'BASE_OBJECT_DELTA.HOLD.json').read_bytes())
    ledger_raw = (ROOT / 'BLOB_READBACK_LEDGER.json').read_bytes()
    ledger = json.loads(ledger_raw)
    rows = ledger['rows']
    assert len(rows) == 72 and all(r['status'] == 'complete_full_GET_equal' for r in rows)
    complete = {r['sha']: r for r in rows}
    objects = list(delta['provided_tree_and_commit_objects'])
    original_gets = []
    for expected in delta['missing_blob_bodies']:
        oid = expected['sha']
        body_wrapper = json.loads((ROOT / ('blob-reads/' + oid + '.body.json')).read_bytes())
        body = body_wrapper['content'].encode('utf-8')
        observed = identity(body)
        assert observed == {'bytes': expected['bytes'], 'sha256': expected['sha256'], 'git_blob': oid}
        actual = complete[oid]
        assert (actual['bytes'], actual['sha256'], actual['git_blob']) == (expected['bytes'], expected['sha256'], oid)
        sdk_path = 'blob-reads/' + oid + '.GITHUB_GET.original.json'
        sdk_raw = (ROOT / sdk_path).read_bytes()
        sdk = json.loads(sdk_raw)
        assert not sdk.get('isError') and sdk['structuredContent']['content'].encode('utf-8') == body
        write_new('blob-bodies/' + oid, body)
        objects.append({'type': 'blob', 'sha': oid, 'bytes': len(body), 'sha256': observed['sha256'], 'raw_base64': base64.b64encode(body).decode('ascii'), 'paths': expected['paths']})
        original_gets.append({'path': sdk_path, **identity(sdk_raw), 'complete_content_matches_blob': oid})
    assert len(objects) == 83
    for item in objects:
        body = base64.b64decode(item['raw_base64'], validate=True)
        obs = identity(body, item['type'])
        assert (obs['bytes'], obs['sha256'], obs['git_blob']) == (item['bytes'], item['sha256'], item['sha'])
    full_closure_raw = (ROOT / 'C0F_CLOSURE_IDENTITIES.json').read_bytes()
    closure = json.loads(full_closure_raw)
    all_ids = {x['sha']: x for x in closure['objects']}
    covered = {x['sha'] for x in objects} | {x['sha'] for x in delta['required_existing_objects']}
    assert len(all_ids) == len(covered) == 16094 and set(all_ids) == covered
    assert not ({x['sha'] for x in objects} & {x['sha'] for x in delta['required_existing_objects']})
    for obj in objects + delta['required_existing_objects']:
        match = all_ids[obj['sha']]
        assert (obj['type'], obj['bytes'], obj['sha256']) == (match['type'], match['bytes'], match['sha256'])
    packet = {
        'format': 'hepta-c0f-format-base-complete-closure-increment-v1',
        'status': 'PREPARED_ORIGINAL_BYTES_NOT_EXECUTION_APPROVAL',
        'base': {'commit': delta['base_commit'], 'tree': delta['base_tree'], 'parents': closure['parents'], 'leaves': 14851, 'inventory': identity((ROOT / 'C0F_INVENTORY.json').read_bytes())},
        'comparison_scope': {'existing_snapshot_commits': delta['compared_current_snapshot_commits'], 'declared_existing_objects': 16449, 'ancestry_complete': False, 'current_native_availability_observed_by_this_preparation': False},
        'complete_base_closure': {'object_count': 16094, 'commit_objects': 1, 'tree_objects': 1778, 'blob_objects': 14315, 'identity_manifest': identity(full_closure_raw)},
        'provided_objects': sorted(objects, key=lambda x: (x['type'], x['sha'])),
        'provided_counts': {'commit': 1, 'tree': 10, 'blob': 72, 'total': 83},
        'required_existing_objects': delta['required_existing_objects'],
        'required_existing_count': 16011,
        'expected_union_with_declared_existing_pack': 16532,
        'live_admission_requirements': ['Verify every supplied raw object length/SHA256/Git type+OID before import.', 'Read and fully verify every reused required object from the explicitly approved source; metadata alone does not establish live availability.', 'Re-read and Merkle-verify the complete c0f snapshot root after pack creation.', 'Keep original c0f formatter base and actual formatter arguments unchanged.', 'Keep old source, index, refs and object stores read-only; only a separately approved fresh target may be written.', 'Retain real parent references without claiming full ancestry; do not add shallow/grafts/alternates or run whole-history fsck.'],
        'native_execution': False,
        'source_mutation': False,
        'qualification': False,
    }
    packet_raw = json_bytes(packet)
    write_new('BASE_OBJECT_PACKET.json', packet_raw)
    encodings = [encode_parts('BASE_OBJECT_PACKET.json', packet_raw), encode_parts('C0F_CLOSURE_IDENTITIES.json', full_closure_raw)]
    sdk_paths = sorted(ROOT.glob('*.GITHUB_GET.original.json')) + sorted((ROOT / 'blob-reads').glob('*.GITHUB_GET.original.json'))
    sdk_items = []
    for path in sdk_paths:
        raw = path.read_bytes()
        sdk_items.append({'path': path.relative_to(ROOT).as_posix(), **identity(raw), 'raw_base64': base64.b64encode(raw).decode('ascii')})
    sdk_raw = json_bytes({'schema': 'hepta-static-format-base-original-git-get-bundle-v1', 'entries': sdk_items, 'native_execution': False})
    write_new('ORIGINAL_GIT_GETS.json', sdk_raw)
    encodings.append(encode_parts('ORIGINAL_GIT_GETS.json', sdk_raw))
    encoding_raw = json_bytes({'schema': 'hepta-lossless-encoded-originals-v1', 'bundles': encodings})
    write_new('ENCODING_MANIFEST.json', encoding_raw)
    review = {
        'schema': 'hepta-c0f-format-base-final-preparation-review-v1',
        'status': 'COMPLETE_FIXED_INCREMENT_PREPARED',
        'base_commit': delta['base_commit'], 'base_tree': delta['base_tree'],
        'source_inventory_original': identity((ROOT / 'C0F_INVENTORY.json').read_bytes()),
        'canonical_commit_raw_original': identity((ROOT / 'C0F_COMMIT.raw').read_bytes(), 'commit'),
        'original_tree_body_comparisons': 1778,
        'existing_snapshot_pack_recomputed': {'trees': 1832, 'blobs': 14615, 'commits': 2, 'total': 16449},
        'base_complete_closure': {'leaves': 14851, 'trees': 1778, 'blobs': 14315, 'commits': 1, 'total': 16094},
        'provided_increment': {'trees': 10, 'blobs': 72, 'commits': 1, 'total': 83, 'blob_bytes': 2216414},
        'required_existing': {'trees': 1768, 'blobs': 14243, 'total': 16011},
        'expected_union': 16532,
        'full_raw_blob_gets_verified': original_gets,
        'packet': identity(packet_raw), 'encoding_manifest': identity(encoding_raw),
        'reviewed_format_source': {'git_blob': 'd4eabe70b68605933240e9129245f7f4cccbde5d', 'scope': 'The fixed changed_paths resolves base^{commit}, diffs that exact base against the current worktree without merge-base, and configuration comparison may git show base:path. No formatter command executed.'},
        'why_increment_is_required': 'The declared isolated cc57+246d pack does not contain the c0f commit or the 82 other base-only objects. The complete c0f snapshot can be added with this fixed 83-object increment and the 16011 strictly verified shared objects.',
        'limits': ['The inventory/tree recovery is accepted solely after original complete byte identities match; it is not a new native read.', 'The existing-pack comparison is pure byte/Merkle analysis of previously approved preserved inputs, not a present availability probe.', 'This package retains c0f real parent OIDs; their ancestry is outside scope and is not silently fetched.', 'The final future overlay is not frozen by this work and must not inherit cc57 source/native PASS.', 'No H operation, old repository mutation, formatter, Rust test, source gate or native qualification occurred.'],
    }
    review_raw = json_bytes(review)
    write_new('FINAL_REVIEW.json', review_raw)
    print(json.dumps({'packet': identity(packet_raw), 'encoding_manifest': identity(encoding_raw), 'review': identity(review_raw), 'encoded_part_counts': [len(b['parts']) for b in encodings], 'sdk_files': len(sdk_items)}, sort_keys=True))

if __name__ == '__main__':
    main()
