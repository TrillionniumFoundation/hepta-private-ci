import ast
import base64
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

OUT = Path('/tmp/hepta-36fa-after2268-20261112')
V1 = Path('/tmp/hepta-36fa-reviewed-final-nonrust-v1')
V2 = Path('/tmp/hepta-36fa-reviewed-final-nonrust-v2')
QA = 'qa/b4-no-bypass/test_evaluated_published_read_source_closure.py'
BASE_REVIEW = OUT / 'ROOT_FINAL_NONRUST_CANDIDATE_REVIEW.json'
PEER_V1 = Path('/tmp/hepta-36fa-final-nonrust-peer-review-v1/REVIEW.json')
PEER_V2 = Path('/tmp/hepta-36fa-final-nonrust-peer-review-v2/REVIEW.json')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def main():
    base_review_raw = BASE_REVIEW.read_bytes()
    assert pin(base_review_raw)['git_blob'] == 'b3422802e86e9383aca4ed503a0923d6475c6d86'
    helper_file = OUT / 'verify_final_nonrust_candidate.py'
    assert pin(helper_file.read_bytes())['git_blob'] == '5e40e592ca7f2791251ca86af190cb3968e7c4de'
    spec = importlib.util.spec_from_file_location('root_v1_helpers_only', helper_file)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    m1, m2 = [json.loads((root / 'MANIFEST.json').read_bytes()) for root in (V1, V2)]
    assert pin((V1 / 'MANIFEST.json').read_bytes())['git_blob'] == '10dffe87464c5a94cbf7c02f6b6ae1958697cd22'
    assert pin((V2 / 'MANIFEST.json').read_bytes())['git_blob'] == '66e013b04b2f67392ba9c3e14a627becf29739a9'
    packet1 = json.loads((V1 / 'NONRUST_PACKET.json').read_bytes())
    packet_raw = (V2 / 'NONRUST_PACKET.json').read_bytes()
    packet2 = json.loads(packet_raw)
    assert pin(packet_raw) == m2['packet']
    assert packet1.keys() == packet2.keys()
    for key in packet1:
        if key not in ('changes', 'expected_after_physical_tree'):
            assert packet1[key] == packet2[key], key
    assert len(packet1['changes']) == len(packet2['changes']) == 11
    changed = []
    for old, new in zip(packet1['changes'], packet2['changes']):
        assert old.keys() == new.keys()
        assert old['path'] == new['path'] and old['before'] == new['before'] and old['mode'] == new['mode']
        if old != new:
            changed.append(new['path'])
        for root, row in ((V1, old), (V2, new)):
            assert (root / 'after' / row['path']).read_bytes() == base64.b64decode(row['after_base64'], validate=True)
            assert pin((root / 'after' / row['path']).read_bytes()) == row['after']
            assert pin((root / 'before' / row['path']).read_bytes()) == row['before']
    assert changed == [QA]
    old_raw, new_raw = [(root / 'after' / QA).read_bytes() for root in (V1, V2)]
    addition = b'        for path in ORDINARY_SCOPE_GUARDS:\n            with self.subTest(actual_root_scopes=path):\n                self.actual_scopes(path, (ROOT / path).read_text())\n'
    assert new_raw.count(addition) == 1 and new_raw.replace(addition, b'', 1) == old_raw
    old_ast, new_ast = ast.parse(old_raw), ast.parse(new_raw)
    cls = next(node for node in new_ast.body if isinstance(node, ast.ClassDef) and node.name == 'EvaluatedOrdinaryRetainedClosureTests')
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'test_new_typed_edges_and_old_boundary_inventory_are_exact')
    loop = method.body.pop()
    assert isinstance(loop, ast.For) and ast.unparse(loop.iter) == 'ORDINARY_SCOPE_GUARDS'
    assert ast.dump(new_ast, include_attributes=False) == ast.dump(old_ast, include_attributes=False)
    assert m2['counts'] == m1['counts']
    gzip_parts = []
    offset = 0
    for part in m2['packet_parts']:
        encoded = (V2 / part['path']).read_bytes()
        assert pin(encoded) == part['encoded'] and encoded.endswith(b'\n')
        raw = base64.b64decode(encoded[:-1], validate=True)
        assert pin(raw) == part['decoded'] and part['gzip_offset'] == offset
        gzip_parts.append(raw)
        offset += len(raw)
    compressed = b''.join(gzip_parts)
    assert pin(compressed) == m2['packet_gzip']
    assert gzip.decompress(compressed) == packet_raw
    inventory_raw = helper.INVENTORY.read_bytes()
    assert pin(inventory_raw) == packet2['base_inventory']
    inventory = json.loads(inventory_raw)
    leaves = {row['path']: ('120000' if row['kind'] == 'symlink' else ('100755' if row['permissions'] & 0o111 else '100644'), row['working_blob']) for row in inventory['files']}
    for row in packet2['changes']:
        leaves[row['path']] = (row['mode'], row['after']['git_blob'])
    tree, nodes = helper.merkle(leaves)
    assert tree == packet2['expected_after_physical_tree'] == m2['expected_after_physical_tree'] == 'd5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087'
    assert len(leaves) == packet2['expected_after_leaf_count'] == 15188
    peer1_raw, peer2_raw = PEER_V1.read_bytes(), PEER_V2.read_bytes()
    assert pin(peer1_raw)['git_blob'] == 'a595a8c817529cd1b6a49467d0c42aa4292794a2'
    assert pin(peer2_raw)['git_blob'] == '19ee2480b741a7866f1a348a81aeaf136d1397a6'
    diagnostic_raw = (V2 / 'diagnostic-new18/RESULT.json').read_bytes()
    diagnostic = json.loads(diagnostic_raw)
    log = (V2 / 'diagnostic-new18/new18.raw.log').read_bytes()
    assert diagnostic['returncode'] == 0 and not diagnostic['timed_out'] and diagnostic['inputs_unchanged']
    assert pin(log) == {**{key: diagnostic['raw'][key] for key in ('bytes', 'sha256')}, 'git_blob': diagnostic['raw']['git_blob_sha']}
    assert b'Ran 18 tests in ' in log and log.rstrip().endswith(b'OK')
    before = (V2 / 'diagnostic-new18/INPUT_INVENTORY.json').read_bytes()
    assert before == (V2 / 'diagnostic-new18/AFTER_INVENTORY.json').read_bytes()
    coverage_raw = (V2 / 'diagnostic-new18/ACTUAL_SCOPE_COVERAGE.json').read_bytes()
    coverage = json.loads(coverage_raw)
    assert coverage['tests_run'] == 18 and coverage['test_result_successful'] and coverage['class_restored_to_original_function']
    assert coverage['expected_paths'] == 20 and coverage['expected_scope_count'] == coverage['observed_complete_actual_scope_count'] == 34
    assert coverage['all_actual_scopes_observed'] and not coverage['missing_actual_scopes'] and not coverage['unexpected_scopes']
    report = {
        'format': 'hepta-root-final-nonrust-v2-input-approval-v1',
        'status': 'APPROVED_FOR_ONE_FINAL_NONRUST_APPLY_AND_ORIGINAL_FMT_PENDING_EXACT_LAUNCH',
        'v1_root_complete_material_review': pin(base_review_raw),
        'v1_peer_blocker_preserved': pin(peer1_raw), 'v2_peer_resolution': pin(peer2_raw),
        'v2_manifest': pin((V2 / 'MANIFEST.json').read_bytes()), 'v2_packet': pin(packet_raw),
        'baseline_inventory': pin(inventory_raw), 'candidate_physical_tree': tree,
        'complete_leaf_count': len(leaves), 'tree_nodes': len(nodes),
        'changed_paths_from_actual_source': 11, 'changed_paths_from_v1_proposal': changed,
        'delta': 'Exactly three appended lines in one existing new test; removing them restores the entire V1 file bytes and AST. Other ten after-images are identical.',
        'scope_coverage': {'actual_paths': 20, 'actual_scopes': 34, 'observed_calls': len(coverage['calls']),
                           'missing': [], 'qualification': False},
        'scoped_actual_diagnostic': pin(diagnostic_raw), 'scoped_actual_raw_log': pin(log),
        'scoped_coverage_observation': pin(coverage_raw),
        'driver': {'bytes': 22679, 'sha256': 'dd5c81cdbfd7f53346304d0d36164b5d7ac753daa854c6dbff0d7e554788dccc', 'git_blob': '080753bf6fa5070c0f71096ace0cf199762ee42c'},
        'authorized_scope': 'Apply exact existing eleven non-Rust paths under original EX lock, then one original just fmt --base c0f78493f815780f68b9bf5e390a21314d79311f, 900 seconds, unchanged complete source/Git/input audits.',
        'outer_seconds': 2100, 'fix_authorized': False, 'rust_tests_authorized_in_this_action': False,
        'ref_updates_authorized_in_this_action': False, 'automatic_retry': False,
        'actual_native_application': 'not_started', 'actual_final_fmt': 'not_started',
        'full_gates': 'not_run', 'real_authorized_task_chain_results': 0, 'qualification': False,
    }
    (OUT / 'ROOT_FINAL_NONRUST_V2_INPUT_APPROVAL.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
