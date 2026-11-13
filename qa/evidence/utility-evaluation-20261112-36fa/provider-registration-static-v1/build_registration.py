#!/usr/bin/env python3
"""Build an external, unexecuted structural proposal from exact retained bytes."""

import ast
import base64
import difflib
import hashlib
import json
from pathlib import Path
import re
import tomllib


OUT = Path(__file__).parent
V1 = Path('/tmp/hepta-36fa-root-resident-provider-proposal-v1')
IDLE = Path('/tmp/hepta-36fa-root-resident-provider-proposal-v2/review-idle-transport-v1')
AGENT = 'codex-rs/hepta-agentd/src/'
WORKFLOW = '.github/workflows/hepta-daemon-learning-native.yml'
ROOT_QA = 'qa/b4-no-bypass/test_resident_root_source_closure.py'
BASE_COMMIT = 'cc57c7198db6293ccca562253c42fffbe2a04633'
BASE_TREE = 'b7b357c07b5539769a068c6b9b009629f5612d1e'
inputs = []


def identity(raw):
    return {
        'bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
        'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(),
    }


def read(path, expected_git=None):
    raw = path.read_bytes()
    got = identity(raw)
    if expected_git is not None:
        assert got['git_blob'] == expected_git, (path, got, expected_git)
    inputs.append({'local_path': str(path), **got})
    return raw


def write(name, raw):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)
    return {'path': name, **identity(raw)}


def jwrite(name, value):
    return write(name, (json.dumps(value, sort_keys=True, indent=2) + '\n').encode())


v1_manifest = json.loads(read(V1 / 'MANIFEST.json', '7cd37e6a6cc391bda9275b938acd7e08263d23a1'))
plan = json.loads(read(V1 / 'STRUCTURAL_REGISTRATION_PLAN.json', '2f17d2b74ca4a5d5c6a821debdd9d7cc91007547'))
idle_manifest = json.loads(read(IDLE / 'MANIFEST.json', '5cdbb64b2d3f4a984867327e739dcabad6c48e5b'))
assert plan['source'] == {'head': BASE_COMMIT, 'tree': BASE_TREE, 'status': ''}
assert idle_manifest['base_commit'] == BASE_COMMIT and idle_manifest['base_tree'] == BASE_TREE
assert idle_manifest['requires_provider_v1_manifest'] == identity((V1 / 'MANIFEST.json').read_bytes())['git_blob']

v1_sources = {}
idle_sources = {}
for manifest, directory, mapping in ((v1_manifest, V1, v1_sources), (idle_manifest, IDLE, idle_sources)):
    rows = manifest.get('source_changes', manifest.get('changes'))
    for row in rows:
        raw = read(directory / 'after' / row['path'], row['after']['git_blob'])
        assert identity(raw) == row['after']
        mapping[row['path']] = raw

baseline_raw = read(Path('/tmp/hepta-36fa-source-repair-canonical-packet-v1/CANONICAL_CLEAN_INVENTORY.expected.json'),
                    '7f94788b70546a8b8030dfd2b9182a7d9287c537')
assert identity(baseline_raw)['sha256'] == '13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9'
baseline = json.loads(baseline_raw)
base_rows = {row['path']: row for row in baseline['files']}
assert len(base_rows) == 15188

workflow_raw = read(Path('/tmp/hepta-36fa-cc57-native-history-scope-review-v1/08ffc5c603a4c950cca285ed2b1e479508d8b5ed.original.source.txt'),
                    '08ffc5c603a4c950cca285ed2b1e479508d8b5ed')
assert base_rows[WORKFLOW]['index_blob'] == identity(workflow_raw)['git_blob']
workflow = workflow_raw.decode()
parent_match = re.search(r'parents = (\[[\s\S]*?\n          \])', workflow)
assert parent_match is not None
original_parents = ast.literal_eval(parent_match.group(1))
assert len(original_parents) == len(set(original_parents)) == 33

transport_path = AGENT + 'authority_host_learning_resident_provider_transport_tests.rs'
lifecycle_path = AGENT + 'authority_host_learning_resident_provider_lifecycle_tests.rs'
child_path = AGENT + 'authority_host_learning_resident_provider_process_tests.rs'
root_path = AGENT + 'authority_host_learning_resident_root_tests.rs'
authority_path = AGENT + 'authority_host_learning_resident_authority.rs'
authority_raw = read(V1 / 'before' / authority_path, base_rows[authority_path]['index_blob'])
root_before = read(IDLE / 'before' / root_path, base_rows[root_path]['index_blob'])
assert idle_sources[root_path] == root_before + b'\n#[path = "authority_host_learning_resident_provider_transport_tests.rs"]\nmod provider_transport;\n'
module_edges = [
    (authority_path, authority_raw, '#[path = "authority_host_learning_resident_root_tests.rs"]\nmod tests;'),
    (root_path, idle_sources[root_path], '#[path = "authority_host_learning_resident_provider_transport_tests.rs"]\nmod provider_transport;'),
    (transport_path, idle_sources[transport_path], '#[path = "authority_host_learning_resident_provider_lifecycle_tests.rs"]\nmod lifecycle;'),
    (transport_path, idle_sources[transport_path], '#[path = "authority_host_learning_resident_provider_process_tests.rs"]\nmod process;'),
]
module_records = []
for path, raw, link in module_edges:
    assert raw.decode().count(link) == 1
    module_records.append({'path': path, 'source': identity(raw), 'observed_module_link': link})

prefix = 'authority_host_service::resident::authority::tests::provider_transport::'
expected_new = [
    prefix + 'resident_role_handoff_elapsed_real_time_cannot_renew_any_original_deadline',
    prefix + 'resident_role_admission_rejects_actual_uid_pidfd_and_process_start_mismatch',
    prefix + 'resident_role_receiver_refuses_another_real_recipient_or_registered_profile',
    prefix + 'lifecycle::resident_idle_original_a_eof_does_not_cancel_fresh_or_readonly_root',
    prefix + 'lifecycle::resident_idle_root_cancel_closes_live_a_and_joins_original_work',
    prefix + 'lifecycle::resident_idle_delivery_delay_keeps_original_service_expiry_and_joins',
]
new_cases = []
for path, module in ((transport_path, prefix), (lifecycle_path, prefix + 'lifecycle::')):
    source = idle_sources[path].decode()
    matches = list(re.finditer(r'(#\[tokio::test\(flavor = "multi_thread", worker_threads = 2\)\]\n'
                              r'#\[ignore = "explicit actual Root and pre-existing protected bind qualification"\]\n)'
                              r'async fn (\w+)\s*\(', source))
    assert len(matches) == 3
    for match in matches:
        new_cases.append({'fqn': module + match.group(2), 'path': path,
                          'definition_line': source[:match.start()].count('\n') + 3,
                          'source': identity(idle_sources[path]),
                          'attributes': match.group(1).strip().splitlines(),
                          'execution': 'not_run',
                          'scope': 'Root transport admission or idle lifetime; no complete ten-owner NoUpdate assertion'})
assert [row['fqn'] for row in new_cases] == expected_new
assert set(expected_new).isdisjoint(original_parents)
child = prefix + 'process::resident_role_peer_process_child'
child_source = idle_sources[child_path].decode()
assert f'const CHILD: &str = "{child}";' in child_source
assert '#[test]\n#[ignore = "only the explicit Root provider parent supplies the inherited control descriptor"]\nfn resident_role_peer_process_child(' in child_source
assert '.args(["--exact", CHILD, "--ignored", "--nocapture", "--test-threads=1"])' in child_source
assert child not in original_parents + expected_new

closing_offset = parent_match.end(1) - len('          ]')
added_text = ''.join('              ' + json.dumps(name) + ',\n' for name in expected_new)
workflow_after = workflow[:closing_offset] + added_text + workflow[closing_offset:]
after_match = re.search(r'parents = (\[[\s\S]*?\n          \])', workflow_after)
candidate_parents = ast.literal_eval(after_match.group(1))
assert candidate_parents == original_parents + expected_new
assert len(set(candidate_parents)) == 39
assert workflow_after[:closing_offset] == workflow[:closing_offset]
assert workflow_after[closing_offset + len(added_text):] == workflow[closing_offset:]

native_driver_raw = read(Path('/tmp/hepta-36fa-final-qualification-hold-v1/native-driver.original.py'),
                         'b92ddded4fce78aeb076d022471c62bf81ce2e4f')
native_driver = native_driver_raw.decode()
for marker in ["name in ('parents', 'packages')", "parents, packages = original_constants['parents'], original_constants['packages']",
               "if sorted(observed) != sorted(parents):", "'--run-ignored', 'only'", "'test(=' + name + ')' for name in parents"]:
    assert marker in native_driver

repair_packet_raw = read(Path('/tmp/hepta-36fa-source-closure-246d-diagnosis-v1/NONRUST_APPLY_PACKET.json'),
                        '35debe83e69774f855ed198d35edaa762ae09573')
repair_packet = json.loads(repair_packet_raw)
selected = {}
for row in repair_packet['changes']:
    if row['path'] in ('CALLERS.toml', ROOT_QA):
        raw = base64.b64decode(row['after_base64'], validate=True)
        assert identity(raw)['git_blob'] == base_rows[row['path']]['index_blob']
        selected[row['path']] = raw
callers = tomllib.loads(selected['CALLERS.toml'].decode())
assert len(callers['boundary']) == 569 and len(callers['protected_file']) == 422
assert identity(selected['CALLERS.toml']) == plan['callers_original']
service_path = AGENT + 'authority_host_learning_candidate_service.rs'
service = v1_sources[service_path].decode()
expected_edge_calls = {
    'root_resident_coordinator_run': 'RootResidentLearningRuntimeV3::run(',
    'root_resident_original_stream_serve': 'RootResidentLearningHandleV3::serve_original_stream(',
    'learning_original_candidate_stage_create': 'OriginalCellQ24CandidateStageOwnersV1::from_original_streams(',
    'learning_original_candidate_stage_recover': 'OriginalCellQ24CandidateStageOwnersV1::recover_original_streams(',
    'root_resident_candidate_runtime_consume': 'RootResidentLearningRegistrationV3::into_candidate_runtime(',
}
existing_edges = []
for edge in plan['existing_edges']:
    before = callers['boundary'][edge['zero_based_position']]
    assert before == edge['original_complete_row']
    call = expected_edge_calls[before['id']]
    assert service.count(call) == 1
    after = dict(before)
    after['product_callers'] = [*before['product_callers'], service_path]
    existing_edges.append({'position': edge['zero_based_position'], 'before': before,
                           'candidate_after_fields': after,
                           'observed_call': {'path': service_path, 'source': identity(v1_sources[service_path]),
                                             'line': service[:service.index(call)].count('\n') + 1,
                                             'form': 'explicit UFCS'},
                           'literal_marker_finalization': 'pending actual formatter and complete collector'})

new_specs = [
    ('root_candidate_handoff_send', 'send_root_candidate_stage_handoff', 'root_candidate_stage_handoff.rs', None, 'pub fn send_root_candidate_stage_handoff(', [], None),
    ('root_candidate_handoff_receive', 'receive_root_candidate_stage_handoff', 'root_candidate_stage_handoff.rs', None, 'pub fn receive_root_candidate_stage_handoff(', [], None),
    ('root_candidate_handoff_consume_original_streams', 'RootCandidateStageHandoffV1::into_original_streams', 'root_candidate_stage_handoff.rs', 'RootCandidateStageHandoffV1', 'pub(crate) fn into_original_streams(', [service_path], 'handoff.into_original_streams('),
    ('learning_original_candidate_handoff_deadline_restrict', 'OriginalCellQ24CandidateStageOwnersV1::restrict_original_handoff_deadline', 'cell_q24_candidate_stage_owners.rs', 'OriginalCellQ24CandidateStageOwnersV1', 'pub(crate) fn restrict_original_handoff_deadline(', [service_path], 'OriginalCellQ24CandidateStageOwnersV1::restrict_original_handoff_deadline('),
    ('root_resident_candidate_service_consume_registration', 'RootResidentLearningRegistrationV3::into_candidate_service', 'authority_host_learning_candidate_service.rs', 'RootResidentLearningRegistrationV3', 'pub fn into_candidate_service(', [], None),
    ('root_resident_candidate_service_run', 'RootResidentCandidateServiceV1::run', 'authority_host_learning_candidate_service.rs', 'RootResidentCandidateServiceV1', 'pub async fn run(', [], None),
]
existing_ids = {row['id'] for row in callers['boundary']}
existing_symbols = {row['symbol'] for row in callers['boundary']}
new_boundaries = []
for suggested_id, symbol, name, receiver, definition, observed_callers, call in new_specs:
    assert suggested_id not in existing_ids and symbol not in existing_symbols
    path = AGENT + name
    source = v1_sources[path].decode()
    assert source.count(definition) == 1
    observed_call = None
    if call is not None:
        assert service.count(call) == 1
        observed_call = {'path': service_path, 'line': service[:service.index(call)].count('\n') + 1,
                         'source': identity(v1_sources[service_path]),
                         'form': 'typed parameter method call' if call.startswith('handoff.') else 'explicit UFCS'}
    new_boundaries.append({'suggested_id': suggested_id, 'symbol': symbol, 'definition_path': path,
                           'receiver_type': receiver, 'definition_source': identity(v1_sources[path]),
                           'definition_line': source[:source.index(definition)].count('\n') + 1,
                           'visibility': 'pub(crate)' if definition.startswith('pub(crate)') else 'pub',
                           'observed_product_callers_in_fixed_v1_overlay': observed_callers,
                           'observed_call': observed_call,
                           'final_product_callers': None, 'definition_markers': None, 'caller_markers': None,
                           'complete_source_collection_required': True,
                           'absence_claim_scope': 'No global caller absence is claimed; fixed V1 overlay observations only.'})
assert [row['symbol'] for row in new_boundaries] == plan['new_entries_requiring_fences']

qa = selected[ROOT_QA].decode()
qa_tree = ast.parse(qa)
qa_constants = {}
for node in qa_tree.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        if node.targets[0].id in ('ROOT_CASES', 'ROOT_ISSUER_CASES'):
            qa_constants[node.targets[0].id] = ast.literal_eval(node.value)
assert len(qa_constants['ROOT_CASES']) == 19 and len(qa_constants['ROOT_ISSUER_CASES']) == 7
assert set(qa_constants['ROOT_CASES'] + qa_constants['ROOT_ISSUER_CASES']).issubset(original_parents)
assert len(original_parents) == 7 + len(qa_constants['ROOT_CASES']) + len(qa_constants['ROOT_ISSUER_CASES'])
assert 'self.assertEqual(len(parents), 7 + len(ROOT_CASES) + len(ROOT_ISSUER_CASES))' in qa

artifacts = []
artifacts.append(write('ROOT_WORKFLOW.candidate.yml', workflow_after.encode()))
artifacts.append(write('ROOT_WORKFLOW.diff', ''.join(difflib.unified_diff(workflow.splitlines(True), workflow_after.splitlines(True),
                                                       fromfile='a/' + WORKFLOW, tofile='b/' + WORKFLOW)).encode()))
artifacts.append(jwrite('ROOT_INVENTORY_PROPOSAL.json', {
    'format': 'hepta-provider-root-parent-registration-proposal-v1',
    'status': 'STATIC_HOLD_NO_SOURCE_WRITE_OR_EXECUTION',
    'source': {'commit': BASE_COMMIT, 'tree': BASE_TREE, 'status': ''},
    'workflow_path': WORKFLOW, 'before': identity(workflow_raw), 'candidate_after': identity(workflow_after.encode()),
    'original_parents': original_parents, 'new_parents': new_cases, 'candidate_parents': candidate_parents,
    'old_count': 33, 'new_count': 39, 'old_order_and_bytes_preserved': True,
    'only_source_change_proposed': 'Six append-only string entries in the existing workflow parents array.',
    'module_edges': module_records,
    'excluded_child': {'fqn': child, 'path': child_path, 'source': identity(idle_sources[child_path]),
                       'reason': 'Only its original explicit Root parent starts this exact ignored child with its inherited descriptor; not an independent Root case.'},
    'native_driver': {'identity': identity(native_driver_raw), 'changed': False,
                       'selection': 'Original AST extraction of parents; exact equality of retained Root JUnit names.',
                       'original_root_test_seconds': 7200, 'original_test_threads': 1, 'original_run_ignored': 'only'},
    'not_included': ['still-floating Fresh T/B/Root provider integration', 'new production launcher', 'complete ten-owner NoUpdate claim'],
    'h_calls': 0, 'tests_run': 0, 'real_utility_tasks': 0,
}))
artifacts.append(jwrite('BOUNDARY_REGISTRATION_PROPOSAL.json', {
    'format': 'hepta-provider-call-boundary-structure-proposal-v1',
    'status': 'STRUCTURE_ONLY_PENDING_ACTUAL_FORMAT_AND_COMPLETE_COLLECTOR',
    'callers_path': 'CALLERS.toml', 'baseline': identity(selected['CALLERS.toml']),
    'baseline_boundary_count': 569, 'baseline_protected_count': 422,
    'existing_edge_changes': existing_edges, 'new_boundary_candidates': new_boundaries,
    'candidate_boundary_count_if_exact_six_added': 575,
    'new_protected_rows': None, 'new_protected_count': None,
    'required_semantic_protection': plan['required_new_protection'],
    'final_body_markers_frozen': False, 'callers_file_written': False, 'full_collector_run': False,
    'scope_note': 'Definition ownership and directly observed V1 product edges only. Test callers and reexports are not counted as product callers; later source additions need fresh complete collection.',
}))
artifacts.append(jwrite('QA_INTEGRATION_OBLIGATIONS.json', {
    'format': 'hepta-provider-root-registration-qa-obligations-v1',
    'status': 'INSTRUCTIONS_FOR_ORDINARY_SINGLE_WRITER_NOT_APPLIED',
    'path': ROOT_QA, 'baseline': identity(selected[ROOT_QA]),
    'method': 'test_existing_ci_really_selects_root_cases_neuron_and_full_caller_proof',
    'root_cases_before': qa_constants['ROOT_CASES'],
    'root_cases_append': expected_new, 'root_issuer_cases_unchanged': qa_constants['ROOT_ISSUER_CASES'],
    'counts': {'root_cases_before': 19, 'root_cases_after': 25, 'issuer_cases': 7, 'other_original_parents': 7,
               'workflow_before': 33, 'workflow_after': 39},
    'preserve': ['unique parents assertion', 'both existing subset assertions',
                 'len(parents) == 7 + len(ROOT_CASES) + len(ROOT_ISSUER_CASES)',
                 'all original case names and original module checks', 'all caller-proof and package markers'],
    'necessary_source_mapping': [
        {'fqn_contains': '::provider_transport::lifecycle::', 'path': lifecycle_path, 'precedence': 'before generic provider_transport'},
        {'fqn_contains': '::provider_transport::', 'path': transport_path},
    ],
    'necessary_module_links': module_records[1:3],
    'ignored_parent_count_add_sources': [transport_path, lifecycle_path],
    'child_excluded_from_root_cases_and_parent_ignore_count': {'fqn': child, 'path': child_path},
    'required_postformat_work': ['Refresh affected exact body/literal fences only from actual formatted bytes.',
                               'Update exact allowlist and run original source/caller/native gates on the final source.',
                               'Do not call idle EOF/lifetime checks a full ten-owner NoUpdate or real utility result.'],
    'qa_file_written': False, 'test_execution': False,
}))
artifacts.append(jwrite('STATIC_REVIEW.json', {
    'format': 'hepta-provider-registration-static-byte-review-v1',
    'checks': {
        'all_fixed_v1_and_idle_postimages_full_hash_equal': True,
        'baseline_workflow_callers_and_qa_match_complete_cc57_inventory': True,
        'root_module_old_bytes_preserved_plus_exact_module_append': True,
        'six_exact_ignored_tokio_parent_definitions_and_module_links': True,
        'one_exact_exec_child_explicitly_excluded': True,
        'workflow_only_six_lines_added': True,
        'old_33_order_and_full_remaining_workflow_bytes_equal': True,
        'candidate_39_names_unique': True,
        'original_b92_dynamic_selection_and_exact_junit_comparison_unmodified': True,
        'five_existing_boundary_rows_equal_to_original_plan': True,
        'five_explicit_ufcs_caller_sites_found': True,
        'six_distinct_new_ids_and_symbols_do_not_collide_with_baseline': True,
        'two_new_internal_calls_observed_with_receiver_type': True,
        'original_qa_19_plus_7_plus_7_formula_preserved_as_obligation': True,
    },
    'scope': 'Local complete-byte comparisons and Python AST/data parsing only; no Rust compilation, source QA, full caller collection, or native process.',
    'source_writes': False, 'h_calls': 0, 'cargo_commands': 0, 'test_commands': 0,
    'not_a_qualification_result': True,
}))
artifacts.append(jwrite('INPUTS.json', {'format': 'hepta-provider-registration-static-inputs-v1', 'files': inputs,
                                     'baseline_embedded_files': {path: identity(raw) for path, raw in selected.items()}}))
artifacts.append(write('README.md', (
    '# Frozen provider registration proposal\n\n'
    'This external proposal uses the fixed V1 production handoff/service source and the separately frozen idle transport/lifetime test unit. It does not modify an active checkout.\n\n'
    'The workflow candidate preserves all 33 existing Root parent names and all other workflow bytes, then appends the six existing ignored parent definitions from the frozen unit. The one ignored exec child stays parent-launched and is not selected as an independent Root case. The unchanged native driver obtains the parent list dynamically and retains its exact JUnit coverage check and original 7200-second Root budget.\n\n'
    'The boundary draft identifies five existing product-call edges and six new boundary definitions. All proposed new receiver types are explicit. Empty observed caller lists refer only to this fixed overlay; complete caller collection remains pending. No final CALLERS, QA, allowlist, or body marker is written.\n\n'
    'The QA obligations preserve the original 7 + ROOT_CASES + ROOT_ISSUER_CASES formula: 19 + 7 + 7 = 33 becomes 25 + 7 + 7 = 39. The two new parent source modules must join the exact mapping and ignored-parent count; the child module must not. Ordinary remains the final QA/CALLERS writer.\n\n'
    'The floating Fresh T/B and Root provider integration is excluded. These idle tests do not establish ten-owner evaluated NoUpdate, an A→B→C task chain, or useful-task results. No source, format, Cargo, test, Root, or H command was run by this proposal. Actual formatting, exact fences, complete collection, and original gates remain future work.\n'
).encode()))
artifacts.append({'path': 'build_registration.py', **identity(Path(__file__).read_bytes())})
manifest = {'format': 'hepta-provider-registration-proposal-manifest-v1',
            'status': 'STATIC_HOLD_NOT_APPLIED_NOT_EXECUTED',
            'source': {'commit': BASE_COMMIT, 'tree': BASE_TREE},
            'requires_v1_manifest': '7cd37e6a6cc391bda9275b938acd7e08263d23a1',
            'requires_frozen_idle_manifest': '5cdbb64b2d3f4a984867327e739dcabad6c48e5b',
            'artifacts': artifacts, 'root_parents_before': 33, 'root_parents_candidate': 39,
            'existing_call_edges': 5, 'new_boundary_definitions': 6,
            'cargo_or_tests_executed': 0, 'h_requests': 0, 'active_source_writes': 0}
mpin = jwrite('MANIFEST.json', manifest)
print(json.dumps({'manifest': mpin, 'artifacts': len(artifacts), 'output': str(OUT)}, sort_keys=True))
