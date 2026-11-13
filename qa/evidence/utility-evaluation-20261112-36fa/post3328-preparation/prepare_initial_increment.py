#!/usr/bin/env python3
"""Freeze explicitly handed-off evidence only; no H, Git refs, or source writes."""
from pathlib import Path
import base64
import gzip
import hashlib
import json

OUT = Path('/tmp/hepta-36fa-post3328-evidence-preparation-v1')
PUBLICATION = Path('/tmp/hepta-36fa-cc57-evidence-publication-v1')
SOURCE = Path('/tmp/hepta-36fa-source-qualification-cc57-launch-v2')
PEER = Path('/tmp/hepta-36fa-native-after-cc57-source-peer-v1')
EVIDENCE_PREFIX = 'qa/evidence/utility-evaluation-20261112-36fa/'
BASE_PLAN = {'bytes': 519233, 'sha256': '9066e5e9f7d66e09f6084b688457af6652f95a32ce2111b4f5abaa2737c5d995', 'git_blob': '7900aa83b40b152f69ca2a1925c819ec46bba72e'}
PUBLICATION_FILES = [
    'PUBLISHED_3328_ANCHORS.json', 'REF_AFTER.original.json',
    'REF_UPDATE.original.json', 'REF_UPDATE_REQUEST.json',
    'ROOT_COMMIT_READBACK_REVIEW.json', 'COMMIT_READ.original.json',
    'COMMIT_CREATE.original.json', 'REF_BEFORE.original.json',
    'COMMIT_REQUEST.json', 'ROOT_COMPLETE_TREE_READBACK_REVIEW.json',
    'verify_actual_trees.py', 'parent-root.READ.response.json',
    'leaf.READ.response.json', 'parent-qa.READ.response.json',
    'parent-evidence.READ.response.json', 'parent-root.CREATE.original.json',
    'parent-qa.CREATE.original.json', 'parent-evidence.CREATE.original.json',
    'leaf.CREATE.original.json', 'README_FULL_READBACK.json',
    'PUBLISH_PLAN.json', 'README.PUBLISH.md',
    'ROOT_VERIFIED_INCREMENTAL_ENTRIES.json', 'LOCAL_TRANSFER_FIRST_ERROR.json',
    'POST3251_METADATA_FIRST_404.original.json', 'ROOT_PUBLICATION_SELECTION_FINAL.json',
    'README_PUBLICATION_REVIEW.json', 'OBSERVED_STATE_THROUGH_VERIFY_START.json',
    'README.TEMPLATE.md', 'ROOT_PUBLICATION_SELECTION.json', 'OBSERVED_STATE.json',
    'README.BASE_TEMPLATE.md', 'ROOT_SELECTION_BEFORE_PEER.json',
    'FROZEN_INPUT_FILEMAP.json', 'prepare_checkpoint.HOLD.py',
    'PR_READBACK_REVIEW.json', 'PR_AFTER.original.json', 'PR_UPDATE.original.json',
    'PR_BODY_GITHUB_FULL_READBACK.original.json', 'PR_BEFORE.original.json',
    'PR.PUBLISHED_3328.md',
]


def pins(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def read_stable(path):
    a = path.stat()
    raw = path.read_bytes()
    b = path.stat()
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    if any(getattr(a, k) != getattr(b, k) for k in fields):
        raise ValueError(f'input changed while reading: {path}')
    return raw


def write_new(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as f:
        f.write(raw)


def jbytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode()


def normalized(path):
    if path.startswith(EVIDENCE_PREFIX):
        path = path[len(EVIDENCE_PREFIX):]
    p = Path(path)
    if p.is_absolute() or '..' in p.parts or '\\' in path:
        raise ValueError(f'unsafe evidence path {path}')
    return path


def main():
    raw_plan = read_stable(PUBLICATION / 'PUBLISH_PLAN.json')
    assert pins(raw_plan) == BASE_PLAN
    plan = json.loads(raw_plan)
    base = plan['files']
    assert len(base) == 3328 and plan['leaf_sha'] == 'cbc9999071443c4e969830ca2fc198f3dad7ca96'
    anchors = json.loads(read_stable(PUBLICATION / 'PUBLISHED_3328_ANCHORS.json'))
    assert anchors['evidence_head'] == '15673f01e5248efdecd00fcb06a58ae3dd45d2c0'
    assert anchors['actual_tree_commit_and_ref_readback'] is True
    assert anchors['evidence_root_tree'] == plan['root_tree']
    write_new(OUT / 'BASE_3328_FILEMAP.json', jbytes(base))
    write_new(OUT / 'BASE_3328_PLAN.original.json', raw_plan)
    rows, duplicate_base, duplicate_selected, transport = [], [], [], []
    selected = {}

    def store_bytes(evidence_path, raw, origin, kind, known_remote=False):
        evidence_path = normalized(evidence_path)
        identity = pins(raw)
        if evidence_path in base:
            assert base[evidence_path] == identity['git_blob'], ('base overwrite', evidence_path)
            duplicate_base.append({'path': evidence_path, 'local': str(origin), **identity})
            return
        if evidence_path in selected:
            assert selected[evidence_path]['git_blob'] == identity['git_blob']
            duplicate_selected.append({'path': evidence_path, 'local': str(origin), **identity})
            return
        if len(raw) >= 500000:
            raise ValueError('large raw files require lossless transport')
        raw.decode('utf-8')
        frozen = OUT / 'frozen' / evidence_path
        write_new(frozen, raw)
        row = {'path': evidence_path, 'local': str(origin), 'frozen_local': str(frozen),
               **identity, 'kind': kind, 'known_remote': known_remote or identity['git_blob'] in base.values(),
               'full_readback_equal': None}
        rows.append(row)
        selected[evidence_path] = row

    def add(path, evidence_path, kind, expected=None, known_remote=False):
        raw = read_stable(path)
        identity = pins(raw)
        if expected is not None:
            assert identity == expected, (str(path), identity, expected)
        if len(raw) < 500000:
            return store_bytes(evidence_path, raw, path, kind, known_remote)
        compressed = gzip.compress(raw, compresslevel=9, mtime=0)
        assert gzip.decompress(compressed) == raw
        parts = []
        assembled = b''
        for i, offset in enumerate(range(0, len(compressed), 262144), 1):
            chunk = compressed[offset:offset + 262144]
            encoded = base64.b64encode(chunk) + b'\n'
            assert base64.b64decode(encoded.strip(), validate=True) == chunk
            assembled += chunk
            part_path = normalized(evidence_path) + f'.part-{i:03d}.gz.b64'
            store_bytes(part_path, encoded, path, 'lossless_transport_part')
            parts.append({'path': part_path, 'offset': offset, 'decoded': pins(chunk), 'encoded': pins(encoded)})
        assert gzip.decompress(assembled) == raw
        manifest = {'format': 'hepta-lossless-original-evidence-transport-v1',
                    'original_local_path': str(path), 'raw': identity,
                    'gzip': pins(compressed), 'parts': parts,
                    'encoding': 'base64 of contiguous gzip bytes, each ASCII file has one terminal LF',
                    'recovery': 'Strip only terminal whitespace, strict base64-decode parts in order, concatenate, then gzip-decompress. Verify all raw and transport identities.',
                    'compression_created_locally_for_transport': True,
                    'not_a_new_native_read': True,
                    'original_observation_preserved_in_raw': True}
        manifest_path = normalized(evidence_path) + '.transport-manifest.json'
        store_bytes(manifest_path, jbytes(manifest), path, 'lossless_transport_manifest')
        transport.append(manifest)

    for name in PUBLICATION_FILES:
        add(PUBLICATION / name, 'checkpoint-3328-publication/' + name, 'frozen_publication_original')

    peer_path = PEER / 'PLACEMENT.json'
    peer = json.loads(read_stable(peer_path))
    for entry in peer['entries']:
        assert entry['full_github_readback_equal'] is True
        add(Path(entry['local_path']), entry['path'], 'native_hold_static_peer',
            {'bytes': entry['bytes'], 'sha256': entry['sha256'], 'git_blob': entry['sha']}, True)
    add(peer_path, 'native-after-cc57-source-peer-v1/PLACEMENT.json', 'native_hold_static_peer_placement', known_remote=True)

    handoff_path = SOURCE / 'EVALUATION_FIXED_24_HANDOFF.json'
    handoff = json.loads(read_stable(handoff_path))
    assert len(handoff['files']) == 24
    existing_progress = {
        'STATUS_02.original.json', 'STATUS_03.original.json',
        'STDOUT_READ_02.original.json', 'STDOUT_READ_03.original.json',
        'STDOUT.part-0000000444-0000003600.log',
    }
    for entry in handoff['files']:
        rel = entry['relative_path']
        prefix = 'progress-through-verify-start/' if rel in existing_progress else 'completed-originals/'
        add(Path(entry['path']), 'source-qualification-cc57-v2/' + prefix + rel,
            'source_original_or_transport_observation',
            {'bytes': entry['bytes'], 'sha256': entry['sha256'], 'git_blob': entry['git_blob_sha']})
    add(handoff_path, 'source-qualification-cc57-v2/completed-originals/EVALUATION_FIXED_24_HANDOFF.json', 'frozen_handoff_index')

    first_path = SOURCE / 'FIRST_TWO_GATE_ORIGINALS_READBACK.json'
    first = json.loads(read_stable(first_path))
    assert len(first['files']) == 6
    for entry in first['files']:
        original = Path(entry['path'])
        rel = str(original.relative_to(SOURCE))
        add(original, 'source-qualification-cc57-v2/completed-originals/' + rel,
            'original_first_two_gate_receipt',
            {'bytes': entry['bytes'], 'sha256': entry['sha256'], 'git_blob': entry['git_blob']}, True)
        sdk = Path(entry['sdk'])
        add(sdk, 'source-qualification-cc57-v2/completed-originals/' + sdk.name,
            'original_first_two_gate_read_sdk')
    add(first_path, 'source-qualification-cc57-v2/completed-originals/FIRST_TWO_GATE_ORIGINALS_READBACK.json', 'original_first_two_gate_readback_index', known_remote=True)

    report = {'format': 'hepta-post3328-initial-selection-v1',
              'base': {'evidence_head': anchors['evidence_head'], 'leaf': plan['leaf_sha'], 'root': plan['root_tree'],
                       'file_count': len(base), 'plan': BASE_PLAN},
              'status': 'selected_frozen_inputs_pending_complete_git_readback',
              'selected_new_paths': len(rows), 'base_duplicates': duplicate_base,
              'selected_duplicates': duplicate_selected, 'transport_originals': len(transport),
              'all_new_payloads_below_500000_bytes': all(r['bytes'] < 500000 for r in rows),
              'base_paths_mutated': [], 'old_readme_modified': False,
              'future_source_capture_not_selected': True,
              'native_five_core_pending_separate_full_readback_handoff': True,
              'real_qualified_task_chain_outcomes': 0,
              'H_calls': 0, 'tests': 0, 'source_writes': 0, 'refs_updated': False}
    write_new(OUT / 'SELECTED_ROWS_INITIAL.json', jbytes(rows))
    write_new(OUT / 'INITIAL_SELECTION_REVIEW.json', jbytes(report))
    print(json.dumps({'new_paths': len(rows), 'base_duplicates': len(duplicate_base),
                      'transports': len(transport), 'selected_bytes': sum(r['bytes'] for r in rows),
                      'maximum_new_file': max(r['bytes'] for r in rows)}))


if __name__ == '__main__':
    main()
