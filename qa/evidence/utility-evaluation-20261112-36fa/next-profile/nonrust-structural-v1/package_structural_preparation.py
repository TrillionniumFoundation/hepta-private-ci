from pathlib import Path
import ast
import base64
import difflib
import gzip
import hashlib
import json
import re
import tomllib


ROOT = Path('/tmp/hepta-36fa-evaluated-ordinary-nonrust-v1')
OUT = ROOT / 'review-structural-v1'
SOURCE_MAP = Path('/tmp/hepta-36fa-post-profile-increments-preformat-leaf-map.json')
RUST = Path('/tmp/hepta-36fa-evaluated-ordinary-candidate-v2/review-complete-profile-v1/postimages')
INCREMENTS = Path('/tmp/hepta-36fa-reviewed-post-profile-increments-v1')


def identity(data):
    return {
        'bytes': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
        'git_blob_sha': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(),
    }


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def save(name, data):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == data, f'create-only mismatch: {path}'
    else:
        path.write_bytes(data)
    return identity(data)


source_map_raw = SOURCE_MAP.read_bytes()
source_map = json.loads(source_map_raw)
assert source_map['tree'] == '02103ded93173dd17aef645ddfcaa5fc6f674042'
assert len(source_map['entries']) == 15188
leaves = {entry['path']: entry for entry in source_map['entries']}
plan = json.loads((ROOT / 'STRUCTURAL_REGISTRATION_PLAN.json').read_text())
scope = json.loads((ROOT / 'STRUCTURAL_SCOPE.json').read_text())
expected = json.loads((ROOT / 'EXPECTED_MEMBERSHIP_PREPARATION.json').read_text())
before_callers = (ROOT / 'baseline/CALLERS.toml').read_bytes()
after_callers = (ROOT / 'structural-candidate/CALLERS.toml').read_bytes()
old = tomllib.loads(before_callers.decode())
new = tomllib.loads(after_callers.decode())
assert len(old['boundary']) == 541 and len(new['boundary']) == 569
assert old['protected_file'] == new['protected_file'] and len(old['protected_file']) == 412
assert {k for k in set(old) | set(new) if old.get(k) != new.get(k)} == {'boundary', 'privileged_inventory'}
assert {k for k in old['privileged_inventory'] if old['privileged_inventory'][k] != new['privileged_inventory'][k]} == {'required_boundary_ids'}
assert new['privileged_inventory']['required_boundary_ids'] == old['privileged_inventory']['required_boundary_ids'] + [row['id'] for row in plan['new_boundaries']]
changed = []
for index, (a, b) in enumerate(zip(old['boundary'], new['boundary'][:541], strict=True)):
    if a != b:
        assert {k for k in set(a) | set(b) if a.get(k) != b.get(k)} == {'product_callers'}
        changed.append(index)
assert changed == [row['position'] for row in plan['changed_existing_boundaries']]
assert new['boundary'][541:] == plan['new_boundaries']
assert sum(len(row['add']) for row in plan['changed_existing_boundaries']) == 38
assert sum(len(row['remove']) for row in plan['changed_existing_boundaries']) == 8
assert len(changed) == 30

files = []
patches = []
paths = ['CALLERS.toml'] + [f['path'] for f in expected['files']]
assert len(paths) == 13 and len(set(paths)) == 13
for path in paths:
    before = (ROOT / 'baseline' / path).read_bytes()
    after = after_callers if path == 'CALLERS.toml' else (ROOT / 'candidate' / path).read_bytes()
    assert before != after
    assert identity(before)['git_blob_sha'] == leaves[path]['sha']
    if path.endswith('.py'):
        old_tree, new_tree = ast.parse(before), ast.parse(after)
        old_functions = [n for n in ast.walk(old_tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        new_functions = [n for n in ast.walk(new_tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        assert len(old_functions) == len(new_functions)
        for a, b in zip(old_functions, new_functions, strict=True):
            assert ast.dump(a, include_attributes=False) == ast.dump(b, include_attributes=False)
            assert ast.get_source_segment(before.decode(), a) == ast.get_source_segment(after.decode(), b)
        old_non_expected = [n for n in old_tree.body if not (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'EXPECTED' for t in n.targets))]
        new_non_expected = [n for n in new_tree.body if not (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'EXPECTED' for t in n.targets))]
        assert [ast.dump(n, include_attributes=False) for n in old_non_expected] == [ast.dump(n, include_attributes=False) for n in new_non_expected]
    save('postimages/' + path, after)
    files.append({'path': path, 'mode': leaves[path]['mode'], 'before': identity(before), 'after': identity(after), 'before_base64': base64.b64encode(before).decode(), 'postimage_base64': base64.b64encode(after).decode()})
    patches.append(''.join(difflib.unified_diff(before.decode().splitlines(keepends=True), after.decode().splitlines(keepends=True), fromfile='a/' + path, tofile='b/' + path)))

invariants = {
    'cell_q24_candidate_stage_retained.rs': [
        'Only the complete evaluated NoUpdate cut is admitted; legacy TrainingNoUpdate and Adopt do not acquire this route.',
        'Actual held Dataset/Training/Evaluation provenance, full pins, original windows and four/five/six-cut prefixes remain distinct.',
        'Initial Version, Selector, NextUse and readiness channels are consumed once from the existing common owner state; no reconnect or new signing authority.',
    ],
    'cell_q24_candidate_stage_retained_execute.rs': [
        'The Root effect gate is checked around real effects and original deadlines remain unchanged.',
        'A lane is fenced before awaiting effects; Version Prepare, Selector Execute and C attestation each use their original one-shot owner path.',
        'C requires actual completion readiness and actual published Version/current evidence; original bounded polling is retained.',
    ],
    'cell_q24_candidate_stage_retained_readback.rs': [
        'Four-cut evaluated evidence, five-cut Selector and six-cut C remain distinct and bind the same complete preceding observations.',
        'Published Version, T/E, S and C are read through their original owners; no new grant, reconnect, signature or fabricated readback.',
    ],
    'circuit_evaluated_selection_command.rs': [
        'The opaque evaluated profile uses a distinct purpose and verifies original training/evaluation identity, signature, scope and current windows.',
        'Recovered command construction attenuates to readback before binding; legacy constructors retain their original semantics.',
        'An evaluated receipt can be obtained only from the original authenticated completed command response.',
    ],
    'circuit_evaluated_selection_command_owner_adapter.rs': [
        'The original Selector owner is consumed by value, retaining the same opaque evaluation context.',
        'Command-response conversion preserves the authenticated original signed receipt and full evaluated prefix; it does not re-sign.',
    ],
    'circuit_evaluated_selection_command_service.rs': [
        'Legacy and evaluated predecessor branches retain their actual held clients; no metadata-only replacement.',
        'Actual original attest/readback calls remain behind the existing origin, one-shot, current and command authentication checks.',
    ],
    'circuit_evaluated_next_use_command.rs': [
        'The evaluated C purpose requires the same opaque original Selector and complete preceding evaluated cut.',
        'Recovery is readback-only and retains full scope, objective, original signatures and time windows.',
    ],
    'circuit_evaluated_next_use_command_service.rs': [
        'The same held actual Training, Evaluation and Selector clients are used for C predecessor reads.',
        'Legacy/evaluated dispatch calls the original C owner behind existing origin and one-shot restrictions.',
    ],
    'circuit_evaluated_next_use_remote.rs': [
        'The source profile and opaque Selector must agree with the complete evaluated predecessor.',
        'EvaluatedOwner location preserves the final actual Source/Cell observation after all awaited T/E/S predecessor reads.',
        'Recovered original attest requests remain readback-only; the original owner is consumed for the command-owner transfer.',
    ],
    'circuit_retained_version_prepared.rs': [
        'A private non-Clone enum consumes the original prepared publication by value and returns the same T/E custody.',
        'Explicit original Prepared type UFCS retains the original signed inputs, await, return values and effect ordering.',
    ],
}
new_scopes = []
for path in plan['pending_new_protected_paths']:
    source = INCREMENTS / path
    if not source.exists():
        source = ROOT / 'rust-overrides' / path
    if not source.exists():
        source = RUST / path
    content = source.read_bytes()
    assert identity(content)['git_blob_sha'] == leaves[path]['sha'], path
    new_scopes.append({'path': path, 'source': identity(content), 'functions_present': re.findall(r'\bfn\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:<[^\n]*>)?\s*\(', content.decode()), 'invariants_to_fence': invariants[Path(path).name], 'final_marker_status': 'pending_actual_native_rustfmt'})
protection = {
    'status': 'scope_plan_only_no_unformatted_literal_contracts_frozen',
    'source_tree_unformatted': source_map['tree'],
    'new_protected_scopes': new_scopes,
    'existing_rows_requiring_review': [{'index': row['index'], 'path': row['path'], 'source_blob': leaves[row['path']]['sha'], 'preserve_all_existing_forbidden_items': True} for row in scope['existing_affected_protected_rows']],
    'counts': {'current_original_protected_rows': 412, 'new_scopes_planned': 10, 'existing_affected_rows': 39, 'expected_final_rows': 422},
    'marker_rules': [
        'Wait for actual native formatting before freezing exact function-body, order and mutation strings.',
        'Keep every unchanged original row/constraint; moved original owner calls must be guarded in their actual new helper rather than deleted.',
        'Full stripped bodies do not protect literal contents. Preserve purpose and digest-domain literals with exact actual-code/function-span checks; comment or dead-code decoys are not sufficient.',
        'Use the original validator without changing required membership equality, source collection, receiver rules or Unknown behavior.',
        'The two Source/C profiles, three/four/five/six receipt counts, cold reader admission/invalidation and real Published outcome require separate negative mutations.',
        'Keep all original QA attacks and original 600/300/4800 second entrypoint budgets. Mechanism fixtures and local source mutation checks do not establish real A/B/C or an ordinary deployed loop.',
    ],
    'pending_qa': [
        'Rebase existing helper/body mutation strings after formatting without deleting attacks or changing assertions.',
        'Add focused mutations for complete evaluated route eligibility and original Root gates/one-shot channel custody.',
        'Add focused mutations for pre-held E, two complete cold recovery reads, recovered reader invalidation and Published-only service admission.',
        'Add focused mutations for distinct legacy/evaluated purposes, correct receipt positions and literal/comment-decoy rejection.',
        'Synchronize the exact final CALLERS SHA256 in the existing blob-size allowlist only after all markers are final.',
    ],
    'source_closure_run': False,
    'full_caller_run': False,
}
protection_identity = save('PROTECTION_PLAN.json', encoded(protection))
packet = {
    'format': 'hepta.utility.nonrust-structural-preparation.v1',
    'status': 'prepared_incomplete_not_for_gate_or_publication',
    'source_base_tree_unformatted': source_map['tree'],
    'source_leaf_count': 15188,
    'source_leaf_map': identity(source_map_raw),
    'files': files,
    'root33_workflow': {'status': 'already_satisfied_in_source_base_not_reapplied', 'path': '.github/workflows/hepta-daemon-learning-native.yml', 'git_blob_sha': leaves['.github/workflows/hepta-daemon-learning-native.yml']['sha']},
    'limits': ['No final source protected-marker/literal update has been applied.', 'No new QA methods have been added or run.', 'Original verifier scripts and source roots remain unchanged.', 'The recorded changed-file parser checks do not establish full-source membership or a gate PASS.'],
}
packet_raw = encoded(packet)
packet_identity = save('packet.json', packet_raw)
packet_b64 = base64.b64encode(gzip.compress(packet_raw, compresslevel=9, mtime=0)) + b'\n'
packet_b64_identity = save('packet.json.gz.b64', packet_b64)
patch_identity = save('delta.patch', ''.join(patches).encode())
references = {}
for name in ['STRUCTURAL_REGISTRATION_PLAN.json', 'EXPECTED_MEMBERSHIP_PREPARATION.json', 'STRUCTURAL_SCOPE.json', 'PROTECTED_LITERAL_PREPARATION_GAPS.json', 'QA_STRUCTURAL_SCOPE.json', 'CHANGED_CALL_SITE_ANALYSIS.json', 'NEW_BOUNDARY_CHANGED_FILE_ANALYSIS.json', 'prepare_structural_registration.py', 'prepare_expected_memberships.py']:
    raw = (ROOT / name).read_bytes()
    references[name] = save(name, raw)
summary = {
    'format': 'hepta.utility.nonrust-structural-review.v1',
    'status': 'prepared_incomplete_pending_fmt_protection_qa_and_full_gates',
    'source_base_tree_unformatted': source_map['tree'],
    'source_leaf_count': 15188,
    'source_leaf_map': identity(source_map_raw),
    'packet_json': packet_identity,
    'packet_gzip_base64_utf8_with_one_final_lf': packet_b64_identity,
    'delta_patch': patch_identity,
    'files': [{k: f[k] for k in ['path', 'mode', 'before', 'after']} for f in files],
    'counts': {'files_changed': 13, 'old_boundaries': 541, 'new_boundaries': 28, 'candidate_boundaries': 569, 'old_boundary_rows_changed': 30, 'actual_member_additions': 38, 'actual_member_removals_due_to_moved_calls': 8, 'old_protected_rows_preserved': 412, 'new_protected_rows_planned_not_added': 10, 'expected_final_protected_rows': 422, 'qa_files_changed_expected_only': 12, 'qa_expected_values_changed': sum(len(f['changed_expected_values']) for f in expected['files']), 'qa_functions_source_and_ast_unchanged': sum(f['function_count'] for f in expected['files'])},
    'checks': {'toml_parsed': True, 'only_approved_structural_toml_fields_changed': True, 'all_existing_protected_rows_equal': True, 'all_12_qa_functions_ast_and_source_equal': True, 'all_non_expected_qa_top_level_ast_equal': True, 'original_verifier_scripts_changed': False, 'source_files_changed': False, 'full_source_membership_verified': False, 'source_closure_run': False, 'full_caller_run': False, 'cargo_run': False, 'native_fmt_run': False},
    'root33_workflow': packet['root33_workflow'],
    'protection_plan': protection_identity,
    'references': references,
    'next_steps': protection['pending_qa'],
    'limitations': packet['limits'],
}
assert summary['counts']['qa_expected_values_changed'] == 44
assert summary['counts']['qa_functions_source_and_ast_unchanged'] == 140
manifest_identity = save('MANIFEST.json', encoded(summary))
readme = '''# Evaluated ordinary profile: structural registration preparation

This is an incomplete, isolated review checkpoint against the unpublished, unformatted source tree `02103ded93173dd17aef645ddfcaa5fc6f674042` (15,188 leaves). It does not modify the active c0f gate source or any source branch.

The packet contains exact before/after bytes for CALLERS and twelve existing QA files. It adds 28 boundaries to the original 541, updates 30 original caller sets with 38 real additions and 8 real call migrations, and retains all 412 original protected rows byte-for-byte at this stage. In twelve QA files, only 44 EXPECTED dictionary values change. All 140 contained function bodies remain identical in source text and AST. All other top-level QA AST nodes remain identical.

The Root-only workflow addition was already independently reviewed and included in the input source tree: the original 32 cases remain in their original order and the one real ignored Version late-B-loss case is appended. It is referenced, not applied again by this packet.

The packet is not ready for publication or a gate run. Ten new production source scopes and 39 affected original protected rows still need exact source/body/literal contracts after actual native formatting. Existing mutation strings must follow the actual moved helpers without deleting attacks or changing assertions. Purpose and digest-domain literal checks must reject comment decoys; stripped bodies alone cannot protect literal values. The final CALLERS allowlist hash is deliberately not updated yet.

The changed-file parser records are limited planning observations over the candidate production delta and the two reviewed explicit-type corrections. They are not a full Rust source collection, not proof of complete caller membership, and not a full caller PASS. No source-closure gate, full caller gate, Cargo command, new QA method, or native formatter was run for this checkpoint. The original validator, full-source collection and strict equality remain unchanged. Final gates retain their original 600/300/4800-second budgets and must run on the future published exact source.

`packet.json.gz.b64` is UTF-8 base64 with one final LF. Decode base64, then gzip-decompress to recover the complete JSON bytes identified in MANIFEST.json. Each entry contains before_base64 and postimage_base64 and independent length/SHA256/Git-blob identities. `delta.patch` describes the same 13-file edit. `PROTECTION_PLAN.json` records the remaining source scopes and invariants without freezing unformatted literal markers.

Synthetic mechanism fixtures and source mutations establish no real authorized A/B/C task, independent field evaluation, deployment adoption, full cost accounting or ordinary cold-recovery acceptance.
'''
readme_identity = save('README.md', readme.encode())
catalog = []
for path in sorted(OUT.iterdir()):
    if path.is_file() and path.name != 'packet.json':
        catalog.append({'id': path.name, 'path': str(path), **identity(path.read_bytes())})
save('UPLOAD_CATALOG.json', encoded(catalog))
print(json.dumps({'manifest': manifest_identity, 'packet': packet_b64_identity, 'patch': patch_identity, 'readme': readme_identity, 'counts': summary['counts'], 'out': str(OUT), 'catalog': catalog}, indent=2))
