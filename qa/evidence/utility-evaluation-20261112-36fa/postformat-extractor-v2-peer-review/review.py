"""Read-only peer review: exact v2 delta and pure scope location, no main/gate."""

import ast
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
OUT = Path('/tmp/hepta-36fa-extractor-v2-peer-review')
V1 = Path('/tmp/hepta-36fa-postformat-nonrust-v1')
V2 = Path('/tmp/hepta-36fa-postformat-extractor-v2-preparation')
CAPTURE = Path('/tmp/hepta-36fa-postformat-capture-launch-v1/ACTUAL_73_FILES.json')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def differences(a, b, path=''):
    if type(a) is not type(b):
        return [(path, a, b)]
    if isinstance(a, dict):
        assert set(a) == set(b), path
        return [v for key in a for v in differences(a[key], b[key], path + '/' + key)]
    if isinstance(a, list):
        assert len(a) == len(b), path
        return [v for i, (x, y) in enumerate(zip(a, b)) for v in differences(x, y, path + '/' + str(i))]
    return [] if a == b else [(path, a, b)]


old_plan_raw = (V1 / 'FENCE_MATRIX.original.json').read_bytes()
new_plan_raw = (V2 / 'FENCE_MATRIX_V2.json').read_bytes()
old_extractor_raw = (V1 / 'extractor.f868.py').read_bytes()
new_extractor_raw = (V2 / 'extractor-v2.py').read_bytes()
assert pin(old_plan_raw)['git_blob'] == 'ffaabdbd254bea8e3d45572c1e8e961625ee5119'
assert pin(new_plan_raw)['git_blob'] == '420daa1d2fb8397016b23a294e25a23ebe01e0d0'
assert pin(old_extractor_raw)['git_blob'] == 'f8686d5986f0f21404621d7e2d6a78634dc3f578'
assert pin(new_extractor_raw)['git_blob'] == '9f13a0e39e012982a5ac539aec1f1bb980e83fa7'
old_plan = json.loads(old_plan_raw)
new_plan = json.loads(new_plan_raw)
diff = differences(old_plan, new_plan)
assert len(diff) == 3
for index, (path, before, after) in zip((8, 9, 10), diff):
    assert path == '/critical_literals/' + str(index) + '/prefix_regex'
    assert after == before + r'\s*\{'
assert new_extractor_raw == old_extractor_raw.replace(pin(old_plan_raw)['sha256'].encode(), pin(new_plan_raw)['sha256'].encode()).replace(pin(old_plan_raw)['git_blob'].encode(), pin(new_plan_raw)['git_blob'].encode())
old_ast = ast.parse(old_extractor_raw)
new_ast = ast.parse(new_extractor_raw)
old_defs = {node.name: ast.get_source_segment(old_extractor_raw.decode(), node) for node in old_ast.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
new_defs = {node.name: ast.get_source_segment(new_extractor_raw.decode(), node) for node in new_ast.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
assert old_defs == new_defs and len(old_defs) == 21
compile(new_ast, str(V2 / 'extractor-v2.py'), 'exec')

capture_raw = CAPTURE.read_bytes()
capture = json.loads(capture_raw)
captured = {}
for row in capture['files']:
    raw = base64.b64decode(row['content_base64'], validate=True)
    expected = {'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': row['git_blob_sha']}
    assert pin(raw) == expected
    assert row['stable'] is True
    captured[row['path']] = raw
assert len(captured) == 73
assert capture['actual_physical_tree'] == '65b898bad23cd58c7f6fd53fafe618f9cf9562dc'
contract = json.loads(Path('/tmp/hepta-36fa-after2268-20261112/APPROVED_F868_CONTRACT.json').read_bytes())
paths = sorted({row['path'] for row in new_plan['rows']})
assert len(paths) == 46 and len(new_plan['rows']) == 49
assert set(paths) == set(contract['formatted_source_pins'])
for path in paths:
    expected = contract['formatted_source_pins'][path]
    assert pin(captured[path]) == {'bytes': expected['bytes'], 'sha256': expected['sha256'], 'git_blob': expected['git_blob_sha']}
modules = OUT / 'pinned_modules'
modules.mkdir(exist_ok=True)
for spec in (new_plan['original_verifier'], new_plan['typed_helper']):
    raw = captured[spec['path']]
    assert pin(raw) == {'bytes': spec['bytes'], 'sha256': spec['sha256'], 'git_blob': spec['git_blob_sha']}
    destination = modules / Path(spec['path']).name
    if destination.exists():
        assert destination.read_bytes() == raw
    else:
        destination.write_bytes(raw)
sys.path.insert(0, str(modules))
proof = load('hepta_actual_source_peer_proof', modules / 'verify_hepta_callers.py')
extractor = load('hepta_actual_source_peer_extractor_v2', V2 / 'extractor-v2.py')
assert Path(proof.typed_callers.__file__).resolve() == (modules / 'hepta_typed_callers.py').resolve()
sources = {path: captured[path].decode() for path in paths}
masked = {path: proof._strip_cfg_test_items(proof._strip_rust_non_code(raw)) for path, raw in sources.items()}
assert all(len(masked[path]) == len(sources[path]) for path in paths)
scopes = []
for row in new_plan['rows']:
    located = [extractor.select_scope(proof, masked[row['path']], selector) for selector in row['selectors']]
    scopes.append({'id': row['id'], 'path': row['path'], 'selector_count': len(located), 'actual_spans': located})
assert sum(row['selector_count'] for row in scopes) == 382
old_literals = []
for index, spec in enumerate(old_plan['critical_literals']):
    try:
        span = extractor.literal_span(proof, masked[spec['path']], sources[spec['path']], spec)
        old_literals.append({'index': index, 'status': 'located', 'span': span})
    except extractor.PreconditionRejected as error:
        old_literals.append({'index': index, 'status': 'rejected', 'error': repr(error)})
assert [r['index'] for r in old_literals if r['status'] == 'rejected'] == [8, 9, 10]
new_literals = []
for index, spec in enumerate(new_plan['critical_literals']):
    span = extractor.literal_span(proof, masked[spec['path']], sources[spec['path']], spec)
    new_literals.append({'index': index, 'path': spec['path'], 'actual_source': pin(captured[spec['path']]),
                         'span': span, 'actual_raw_prefix_and_literal': sources[spec['path']][span['prefix_start']:span['end']]})
assert len(new_literals) == 17
mounts = [extractor.mount_span(proof, masked[spec['parent']], sources[spec['parent']], spec) for spec in new_plan['module_mounts']]
assert len(mounts) == 10
review = {
    'format': 'hepta-extractor-v2-independent-static-peer-review-v1',
    'status': 'NO_BLOCKING_CHANGE_FOUND_IN_EXACT_FORMAT_PREFIX_SYNC',
    'inputs': {'actual_73_file_capture': pin(capture_raw), 'old_plan': pin(old_plan_raw), 'new_plan': pin(new_plan_raw), 'old_extractor': pin(old_extractor_raw), 'new_extractor': pin(new_extractor_raw)},
    'plan_changes_exact': diff,
    'extractor_change_exact': 'Only PLAN_SHA256 and PLAN_BLOB values; all 21 function/class definitions and all remaining bytes unchanged.',
    'formatted_source_verification': {'paths': 46, 'all_actual_bytes_match_original_approved_contract': True, 'source_physical_tree': capture['actual_physical_tree']},
    'pure_scope_locations': scopes,
    'original_literal_plan_on_actual_formatted_bytes': old_literals,
    'new_literal_plan_on_actual_formatted_bytes': new_literals,
    'actual_module_mounts': mounts,
    'counts': {'protected_rows': 49, 'scope_selectors': 382, 'literal_spans': 17, 'module_mounts': 10},
    'narrowing_review': 'Only three prefix patterns require the actual opening block brace after the same match arm. No optional brace/alternate scope is introduced. The exact literal, owner/function selector, original masking, nested-function exclusion, unique-match requirement, immediate-raw-literal check and real masked expression check are unchanged.',
    'actual_fmt_cross_reference': {'audit_report': '4be399c11ac6e3c8edc68f8f50637ee53f1de3a3', 'retained_version_after': 'e6f841ab40dbfe35f5763b726f391830a76c9b44', 'retained_version_context_after': '518aaa1a22b3320215813ae0aa2eaf9a7b15cb12', 'meaning': 'These are three of the 15 already reviewed single-tail-expression blocks in the actual 43-file formatting transition.'},
    'execution_scope': {'original_extractor_main_calls': 0, 'original_validator_gate_calls': 0, 'rust_tests': 0, 'native_or_H_calls': 0, 'source_or_ref_writes': False, 'analysis_only_calls': 'Original pure select_scope/literal_span/mount_span on actual captured bytes; no native-result inference.'},
    'limitations': ['This static peer review does not establish the original f868 native terminal.', 'New actual run requires its own Root-approved contract, fresh external records/key, exact launcher pins and native authorization.', 'No source closure, full caller, Rust test or ordinary-loop PASS is inferred.'],
}
(OUT / 'REVIEW.json').write_text(json.dumps(review, indent=2) + '\n')
print(json.dumps({'review': pin((OUT / 'REVIEW.json').read_bytes()), 'counts': review['counts'], 'v1_literal_rejections': [r['index'] for r in old_literals if r['status'] == 'rejected'], 'new_all_literal_spans_located': True, 'all_definitions_identical': len(old_defs), 'main_calls': 0}, indent=2))
