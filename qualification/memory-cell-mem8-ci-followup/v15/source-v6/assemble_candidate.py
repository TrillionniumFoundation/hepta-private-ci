#!/usr/bin/env python3
"""Build a new reviewed overlay from original V5 formatted bytes and exact edits."""
import argparse
import base64
import hashlib
import json
import lzma
from pathlib import Path

WORK = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
ORIGINAL = WORK / 'mem8-source-ci-v5-original-run/records'
BASE = '2ae5215beaf8d7b7df111a090b82134beae2683d'
BASE_TREE = '12159640adcf073b51f3837e75575e11f5c20233'
PARENT = '9bd2f589debdba4a93baa363817c3669cb103721'
PARENT_TREE = 'c77785ecb368c44ea699769001a47402c9f50591'


def obj(kind, data):
    return hashlib.sha1(kind.encode() + b' ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def identity(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'git_blob': obj('blob', data)}


def listing(raw):
    result = {}
    for row in raw.split(b'\0'):
        if not row:
            continue
        header, name = row.split(b'\t', 1)
        mode, kind, sha = header.decode().split()
        assert kind == 'blob'
        path = name.decode()
        assert path not in result
        result[path] = {'mode': mode, 'type': kind, 'git_blob': sha}
    return result


def tree_hash(rows):
    root = {}
    for path, entry in rows.items():
        current = root
        parts = path.split('/')
        for name in parts[:-1]:
            current = current.setdefault(name, {})
        assert parts[-1] not in current
        current[parts[-1]] = (entry['mode'], entry['git_blob'])

    def visit(directory):
        data = b''
        for name, value in sorted(directory.items(), key=lambda pair: (pair[0] + ('/' if isinstance(pair[1], dict) else '')).encode()):
            mode, digest = ('40000', visit(value)) if isinstance(value, dict) else value
            data += mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(digest)
        return obj('tree', data)

    return visit(root)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--extra-edits', type=Path, help='Reviewed JSON rows with path/local/preimage/postimage/group')
    args = parser.parse_args()
    base = listing((ORIGINAL / 'BASE_TREE.ls-tree').read_bytes())
    parent = listing((ORIGINAL / 'CANDIDATE_TREE.ls-tree').read_bytes())
    assert tree_hash(base) == BASE_TREE
    assert tree_hash(parent) == PARENT_TREE
    old_input = json.loads((ORIGINAL / 'INPUT.json').read_text())
    old_rows = {row['path']: row for row in old_input['files']}
    formatted = json.loads((ORIGINAL / 'FORMATTED_CAPSULE.json').read_text())
    assert formatted['candidate_tree'] == PARENT_TREE and len(formatted['files']) == 103
    rows = {}
    reconstructed = dict(base)
    for entry in formatted['files']:
        path = entry['path']
        data = base64.b64decode(entry['content_base64'], validate=True)
        value = identity(data)
        assert value == {'bytes': entry['postimage_bytes'], 'sha256': entry['postimage_sha256'], 'git_blob': entry['postimage_git_blob']}
        assert parent[path]['git_blob'] == value['git_blob']
        assert base.get(path, {}).get('git_blob') == entry['preimage_git_blob']
        rows[path] = {'path': path, 'mode': entry['mode'], 'group': old_rows[path]['group'],
                      'preimage_git_blob': entry['preimage_git_blob'], 'input_git_blob': value['git_blob'],
                      'bytes': value['bytes'], 'sha256': value['sha256'], 'content': data.decode()}
        reconstructed[path] = parent[path]
    assert reconstructed == parent

    caller_root = WORK / 'mem-caller-performance-9bd2-readonly'
    caller = json.loads((caller_root / 'FINAL_CANDIDATE_MANIFEST.json').read_text())
    edits = []
    for row in caller['files']:
        edits.append({'path': row['path'], 'local': str(caller_root / 'final-candidate' / row['path']),
                      'preimage': row['preimage'], 'postimage': row['postimage'], 'group': 'caller-conservative-performance'})
    for folder, group in [
        ('mem-neuron-readback-9bd2-readonly/final', 'neuron-bounded-original-readback'),
        ('mem-hardlink-public-error-contract-9bd2', 'hardlink-public-error-contract'),
    ]:
        path = WORK / folder
        manifest = json.loads((path / 'CANDIDATE_MANIFEST.json').read_text())
        manifest = manifest.get('candidate', manifest)
        file_rows = manifest.get('files') or manifest.get('changed_paths') or ([manifest] if 'path' in manifest else None)
        assert file_rows
        for row in file_rows:
            edits.append({'path': row['path'], 'local': str(path / 'source' / row['path']),
                          'preimage': row.get('before') or row.get('preimage'),
                          'postimage': row.get('after') or row.get('postimage'), 'group': group})
    if args.extra_edits:
        edits.extend(json.loads(args.extra_edits.read_text()))
    assert len({row['path'] for row in edits}) == len(edits)
    candidate = dict(parent)
    changed = []
    for edit in edits:
        path = edit['path']
        preimage = edit['preimage']
        expected_pre = (preimage or {}).get('git_blob', (preimage or {}).get('gitBlob'))
        assert parent.get(path, {}).get('git_blob') == expected_pre, path
        data = Path(edit['local']).read_bytes()
        value = identity(data)
        expected = edit['postimage']
        assert value == {'bytes': expected['bytes'], 'sha256': expected['sha256'],
                         'git_blob': expected.get('git_blob', expected.get('gitBlob'))}, path
        assert value['git_blob'] != expected_pre
        rows[path] = {'path': path, 'mode': '100644', 'group': edit['group'],
                      'preimage_git_blob': base.get(path, {}).get('git_blob'),
                      'input_git_blob': value['git_blob'], 'bytes': value['bytes'],
                      'sha256': value['sha256'], 'content': data.decode()}
        candidate[path] = {'mode': '100644', 'type': 'blob', 'git_blob': value['git_blob']}
        changed.append({'path': path, 'mode': '100644', 'group': edit['group'],
                        'preimage_git_blob': expected_pre, **value, 'content': data.decode()})
    assert {path for path in base.keys() | candidate.keys() if base.get(path) != candidate.get(path)} == rows.keys()
    assert {path for path in parent.keys() | candidate.keys() if parent.get(path) != candidate.get(path)} == {row['path'] for row in edits}
    candidate_tree = tree_hash(candidate)
    golden = (ORIGINAL / 'caller-verify.raw.log').read_bytes()
    reference = json.loads(golden)
    assert reference['status'] == 'PASS_HEPTA_CALLER_CLOSED_SET' and reference['rustFilesScanned'] == 6200
    config = {
        'schema': 'hepta.mem8.source-gates-reviewed-input.v6', 'base_sha': BASE,
        'base_tree': BASE_TREE, 'source_gate_run_version': 6,
        'ready_to_execute': True, 'execution_scope': 'source-only-format-caller-and-full-tree-scan',
        'source_parent_commit': PARENT, 'source_parent_tree': PARENT_TREE,
        'expected_initial_tree': candidate_tree,
        'files': [rows[path] for path in sorted(rows)], 'case_renames': old_input['case_renames'],
        'reference_caller_receipt': {'original_run': 43015979473, 'original_job': 130507034042,
                                     'original_source_head': formatted['initial_commit'],
                                     'original_formatted_tree': PARENT_TREE, **identity(golden)},
        'new_reviewed_edits_vs_parent': [{key: value for key, value in row.items() if key != 'content'} for row in changed],
        'native_tests_executed': 0, 'model_requests_executed': 0,
        'source_refs_modified': False,
        'previous_unknown_operations': {'V3_source_process': 'UNKNOWN_NOT_REPLAYED', 'V4_upload_effects': 'UNKNOWN_ZERO_PROCESS_START_REQUESTS', 'original_provider_turn': 'UNKNOWN_NO_NEW_GENERATION'},
        'unresolved': ['New-source format and full caller qualification have not yet executed.',
                       'New-source Rust/native qualification has not yet executed; previous failures remain historical.',
                       'Original owner, provider, exposure, independent trust, successor benefit, effect recovery and complete cost gates remain open.'],
    }
    encoded = json.dumps(config, indent=2, sort_keys=True).encode() + b'\n'
    compressed = lzma.compress(encoded, preset=6)
    (HERE / 'INPUT_SOURCE_GATES.json').write_bytes(encoded)
    (HERE / 'INPUT_SOURCE_GATES.json.xz').write_bytes(compressed)
    (HERE / 'GOLDEN_CALLER_RECEIPT.json').write_bytes(golden)
    (HERE / 'SOURCE_CHANGES.json').write_text(json.dumps(changed, indent=2) + '\n')
    manifest = {'schema': 'hepta.mem8.source-v6.assembly.v1', 'base_commit': BASE, 'base_tree': BASE_TREE,
                'parent_commit': PARENT, 'parent_tree': PARENT_TREE, 'candidate_tree': candidate_tree,
                'full_parent_entries': len(parent), 'full_candidate_entries': len(candidate),
                'cumulative_paths': len(rows), 'changed_paths_vs_parent': len(changed),
                'original_formatted_103_paths_verified': True,
                'input': identity(compressed), 'golden_caller_receipt': identity(golden),
                'files': config['new_reviewed_edits_vs_parent'],
                'source_commit_created': False, 'source_ref_changed': False,
                'source_gate_executed': False, 'native_tests_executed': 0, 'model_requests_executed': 0,
                'assembly_is_new_work_not_recovery_of_a_lost_original': True}
    (HERE / 'ASSEMBLY.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({key: value for key, value in manifest.items() if key != 'files'}))


if __name__ == '__main__':
    main()
