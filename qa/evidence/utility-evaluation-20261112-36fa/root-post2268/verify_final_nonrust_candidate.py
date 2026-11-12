import ast
import base64
import gzip
import hashlib
import json
from pathlib import Path


OUT = Path('/tmp/hepta-36fa-after2268-20261112')
CANDIDATE = Path('/tmp/hepta-36fa-reviewed-final-nonrust-v1')
CAPTURE = Path('/tmp/hepta-36fa-postformat-capture-launch-v1/ACTUAL_73_FILES.json')
INVENTORY = Path('/tmp/hepta-36fa-postformat-inventory-recovery-v1/final.inventory.recovered.json')
EXTRACTOR = Path('/tmp/hepta-36fa-extractor-launch-v2')
RECOVERED = Path('/tmp/hepta-36fa-postformat-proposal-exact-recovery-v2')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def source_bytes(row):
    keys = [key for key in row if key.endswith('base64')]
    assert len(keys) == 1, keys
    return base64.b64decode(row[keys[0]], validate=True)


def merkle(leaves):
    root = {}
    for path, (mode, sha) in leaves.items():
        parts = path.split('/')
        assert all(part and part not in ('.', '..') for part in parts)
        current = root
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        assert parts[-1] not in current
        current[parts[-1]] = (mode, sha)
    trees = {}

    def walk(node, prefix):
        entries = []
        for name, value in node.items():
            if isinstance(value, dict):
                mode, sha = '40000', walk(value, prefix + name + '/')
                order = name.encode() + b'/'
            else:
                mode, sha = value
                order = name.encode()
            entries.append((order, mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(sha)))
        body = b''.join(body for _, body in sorted(entries))
        sha = hashlib.sha1(b'tree ' + str(len(body)).encode() + b'\0' + body).hexdigest()
        trees[prefix.rstrip('/')] = sha
        return sha

    return walk(root, ''), trees


def methods(raw):
    text = raw.decode()
    lines = text.splitlines(keepends=True)
    result = {}
    for cls in ast.parse(text).body:
        if not isinstance(cls, ast.ClassDef):
            continue
        for node in cls.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test_'):
                start = min([node.lineno] + [item.lineno for item in node.decorator_list])
                key = (cls.name, node.name)
                assert key not in result
                result[key] = (''.join(lines[start - 1:node.end_lineno]), ast.dump(node, include_attributes=False))
    return result


def main():
    native_result_raw = (EXTRACTOR / 'RESULT.json').read_bytes()
    native_result = json.loads(native_result_raw)
    native_normal_raw = (EXTRACTOR / 'STATUS_01.original.json').read_bytes()
    wrapper = json.loads(native_normal_raw)
    assert not wrapper.get('isError')
    normal = json.loads(wrapper['content'][0]['text'])
    assert normal['job_id'] == '1a1d1a2125c-2564-1c69'
    assert normal['state'] == 'succeeded' and normal['exit_code'] == 0
    assert normal['output_complete'] and normal['output_durable'] and not normal['timed_out']
    assert not any(normal['log_truncated'].values())
    assert native_result['source_mutated'] is False and native_result['proposals_are_qualification'] is False
    proposal_raw = (RECOVERED / 'PROPOSALS.exact-recovered.json').read_bytes()
    proposal_pin = pin(proposal_raw)
    assert proposal_pin == {**{k: native_result['proposal'][k] for k in ('bytes', 'sha256')},
                            'git_blob': native_result['proposal']['git_blob_sha']}
    encoded = (RECOVERED / 'PROPOSALS.exact-recovered.json.gz.b64').read_bytes()
    assert encoded.endswith(b'\n')
    compressed = base64.b64decode(encoded[:-1], validate=True)
    assert compressed == (RECOVERED / 'PROPOSALS.exact-recovered.json.gz').read_bytes()
    assert gzip.decompress(compressed) == proposal_raw

    inventory_raw = INVENTORY.read_bytes()
    inventory = json.loads(inventory_raw)
    capture = json.loads(CAPTURE.read_bytes())
    captured = {row['path']: row for row in capture['files']}
    assert len(captured) == 73
    indexed = {row['path']: row for row in inventory['files']}
    assert len(indexed) == len(inventory['files']) == 15188
    manifest_raw = (CANDIDATE / 'MANIFEST.json').read_bytes()
    manifest = json.loads(manifest_raw)
    packet_raw = (CANDIDATE / 'NONRUST_PACKET.json').read_bytes()
    packet = json.loads(packet_raw)
    assert pin(packet_raw) == manifest['packet']
    assert packet['format'] == 'hepta-reviewed-nonrust-source-apply-v1'
    assert packet['base_inventory'] == pin(inventory_raw) == manifest['base_inventory']
    assert inventory['source'] == capture['source_identity'] == packet['source_identity'] == manifest['base_source_identity']
    assert pin(inventory_raw)['sha256'] == native_result['source_after']['sha256']
    compressed_parts = []
    offset = 0
    for part in manifest['packet_parts']:
        raw = (CANDIDATE / part['path']).read_bytes()
        assert pin(raw) == part['encoded'] and raw.endswith(b'\n')
        decoded = base64.b64decode(raw[:-1], validate=True)
        assert pin(decoded) == part['decoded'] and part['gzip_offset'] == offset
        compressed_parts.append(decoded)
        offset += len(decoded)
    compressed_packet = b''.join(compressed_parts)
    assert pin(compressed_packet) == manifest['packet_gzip']
    assert gzip.decompress(compressed_packet) == packet_raw

    leaves = {}
    for path, row in indexed.items():
        assert row['stable']
        mode = '120000' if row['kind'] == 'symlink' else ('100755' if row['permissions'] & 0o111 else '100644')
        assert row['kind'] in ('file', 'symlink')
        leaves[path] = (mode, row['working_blob'])
    before_tree, _ = merkle(leaves)
    assert before_tree == packet['base_physical_tree'] == manifest['base_physical_tree'] == '65b898bad23cd58c7f6fd53fafe618f9cf9562dc'
    changed = [row['path'] for row in packet['changes']]
    assert changed == sorted(set(changed)) and len(changed) == 11
    assert set(changed) == set(manifest['changed_paths'])
    for row in packet['changes']:
        path = row['path']
        assert path in captured and path in indexed and not path.endswith('.rs')
        assert path in ('.github/blob-size-allowlist.txt', 'CALLERS.toml') or (path.startswith('qa/b4-no-bypass/') and path.endswith('.py'))
        before = source_bytes(captured[path])
        after = base64.b64decode(row['after_base64'], validate=True)
        assert (CANDIDATE / 'before' / path).read_bytes() == before
        assert (CANDIDATE / 'after' / path).read_bytes() == after
        assert pin(before) == row['before'] == manifest['changed_paths'][path]['before']
        assert pin(after) == row['after'] == manifest['changed_paths'][path]['after']
        assert indexed[path]['working_blob'] == row['before']['git_blob']
        assert indexed[path]['sha256'] == row['before']['sha256'] and indexed[path]['bytes'] == row['before']['bytes']
        assert row['mode'] == '100644' and indexed[path]['permissions'] == 0o644
        assert before != after
        leaves[path] = (row['mode'], row['after']['git_blob'])
    after_tree, after_trees = merkle(leaves)
    assert len(leaves) == packet['expected_after_leaf_count'] == manifest['expected_after_leaf_count'] == 15188
    assert after_tree == packet['expected_after_physical_tree'] == manifest['expected_after_physical_tree'] == '74a2fe12be39aba5ab55d537124cd9462673fd9e'
    old_allowlist = (CANDIDATE / 'before/.github/blob-size-allowlist.txt').read_bytes()
    new_allowlist = (CANDIDATE / 'after/.github/blob-size-allowlist.txt').read_bytes()
    assert new_allowlist.startswith(old_allowlist)
    addition = new_allowlist[len(old_allowlist):].decode()
    assert [line for line in addition.splitlines() if line and not line.startswith('#')] == [
        'sha256:' + manifest['changed_paths']['CALLERS.toml']['after']['sha256'] + ' CALLERS.toml']

    old_count = unchanged_count = changed_count = new_count = 0
    all_method_rows = []
    qa_paths = sorted(path for path in captured if path.startswith('qa/') and path.endswith('.py'))
    assert len(qa_paths) == 21
    for path in qa_paths:
        before = source_bytes(captured[path])
        after_path = CANDIDATE / 'after' / path
        after = after_path.read_bytes() if after_path.exists() else before
        before_methods, after_methods = methods(before), methods(after)
        assert not set(before_methods) - set(after_methods)
        old_count += len(before_methods)
        new_count += len(set(after_methods) - set(before_methods))
        for name, old_value in before_methods.items():
            equal = old_value == after_methods[name]
            unchanged_count += int(equal)
            changed_count += int(not equal)
            all_method_rows.append({'path': path, 'class': name[0], 'method': name[1], 'source_and_ast_unchanged': equal})
    assert (old_count, unchanged_count, changed_count, new_count) == (184, 167, 17, 18)
    rust_rows = [json.loads(line) for line in Path('/tmp/hepta-36fa-final-source-preparation-v1/ACTUAL_V5_RUST_BLOBS.PUBLISHED.jsonl').read_text().splitlines()]
    assert len({row['path'] for row in rust_rows}) == len(rust_rows) == 43
    assert all(row['full_readback_equal'] and indexed[row['path']]['working_blob'] == row['sha'] for row in rust_rows)
    report = {
        'format': 'hepta-root-final-nonrust-candidate-review-v1',
        'status': 'exact_unapplied_candidate_verified_pending_peer_and_native',
        'manifest': pin(manifest_raw), 'packet': pin(packet_raw),
        'actual_extractor_job': normal['job_id'], 'actual_extractor_result': pin(native_result_raw),
        'actual_extractor_normal_sdk': pin(native_normal_raw), 'exact_recovered_original_proposal': proposal_pin,
        'recovery_scope': 'Independent raw identity match to actual successful native RESULT, plus complete companion decoding; not a second native full-output read.',
        'baseline_inventory': pin(inventory_raw), 'before_physical_tree': before_tree,
        'after_candidate_physical_tree': after_tree, 'complete_leaf_count': len(leaves),
        'complete_tree_node_count': len(after_trees), 'changed_existing_nonrust_paths': changed,
        'actual_prior_rust_postimages_github_full_readback': len(rust_rows),
        'old_qa': {'files': len(qa_paths), 'methods': old_count, 'source_and_ast_unchanged': unchanged_count,
                   'explicitly_changed': changed_count, 'new': new_count, 'removed': 0},
        'allowlist': 'All original bytes retained; one exact final CALLERS SHA256 appended.',
        'peer_semantic_review': 'pending', 'native_application': 'not_started', 'final_fmt': 'not_started',
        'full_source_gate': 'not_run', 'rust_tests': 'not_run', 'real_authorized_ABC': 'not_established',
        'qualification': False,
    }
    (OUT / 'ROOT_FINAL_NONRUST_CANDIDATE_REVIEW.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    (OUT / 'ROOT_FINAL_NONRUST_CANDIDATE_METHODS.json').write_text(json.dumps(all_method_rows, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
