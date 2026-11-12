from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parent
BASE = '57b27c81d0d5321b873ee751fd0e58e1d905b988'
A = 'codex-rs/hepta-agentd/src/'
QA = 'qa/b4-no-bypass/test_original_panel_training_transaction_source_closure.py'
OLD_QA = 'qa/b4-no-bypass/test_original_evaluation_host_source_closure.py'


def meta(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def ref(path, marker, area='postimages'):
    source = (ROOT / area / path).read_text()
    assert marker in source, (path, marker)
    return {'path': path, 'line': source[:source.index(marker)].count('\n') + 1,
            'marker': marker, **meta(source.encode())}


manifest = json.loads((ROOT / 'manifest.json').read_text())
assert manifest['source_commit'] == BASE and manifest['returncode'] == 0
preserved = json.loads((ROOT / 'PRESERVED_FUNCTIONS.formatted.json').read_text())
assert len(preserved['unchanged_functions']) == 22
assert all(row['byte_identical'] for row in preserved['unchanged_functions'])
assert all(row['remaining_body_byte_identical'] for row in preserved['body_migrations'])
cases = [
    ('original_panel_training_proof_rejects_new_source_reentry_and_incomplete_slots', 5, 5,
     'A begun call cannot begin again or finish against another call. One panel is insufficient. A completed proof rejects a newly allocated Source even with the same call identity and same T bytes. An extra slot poisons the proof before another peer read.',
     'The actual private lifecycle helper runs while holding the original B mutex; partial panel uses 1 T, two complete-panel transactions use 2 T each. No B effect is dispatched and all upstream/B files stay identical.',
     'Individual fallback fails the same-call lifecycle expectations or performs original 8N reads, rather than the exact total 5; a canned fixture would leave actual-T trace at zero.'),
    ('original_panel_same_call_training_keeps_four_execute_and_three_readback_frames', 11, 11,
     'Known Missing performs one actual first read and does not renew a partial proof. The same finite channel then performs Execute4, Readback3 and Readback3; both reads return the identical original opaque B receipt.',
     'Trace milestones are 1, 5, 8, 11. Only the first actual Execute changes the B journal; later readbacks and all upstream files remain unchanged.',
     'N=2 Individual fallback costs 18/17 per Execute/Readback, so it cannot satisfy 4/3; old member peers cannot satisfy actual-T trace counts.'),
    ('original_panel_last_actual_training_failure_never_returns_or_resigns_b', 4, 3,
     'At actual readonly T request4, truncate only the same fixture native-training artifact before calling the original T handler. This is the final panel T slot, after the original receipt owner completed its two T checks and durable B effect.',
     'B Execute returns an error, B journal differs from before, a new Execute is ReadbackRequired, later Readback is CommitUncertain, the journal does not change again, and no fifth T request occurs.',
     'Trace4 plus three original Completed replies proves the failure was not the first panel read or either receipt-owner T read. The test deliberately permits an uncertain durable B signature and forbids return/re-sign.'),
    ('original_panel_last_training_slot_keeps_the_actual_cohort_tail', 4, 4,
     'Pause actual readonly T request4, withdraw the actual retention cohort target, then release the same request. The original T handler must still succeed and the later non-T physical tail must refuse the B response.',
     'Four actual requests and four original Completed responses exclude T transport failure as the reason. B is already durable; later readback remains fenced without more T requests or journal writes.',
     'If the last panel or its post-T cohort/Cell/qualification tail were omitted, this negative case would return B. The exact fourth-slot admission and 4/4 completed count distinguish it from an early failure.'),
    ('original_panel_cancel_keeps_the_held_lane_and_consumed_channel', 7, 7,
     'Pause first actual T, cancel only the async B waiter, observe Busy from a separate B consumer while the same original mutex remains held, then release. The original blocking exchange completes naturally on the taken channel.',
     'The canceled client stays Unavailable; the original work consumes 4 actual T. A fresh Execute is ReadbackRequired, and an allowed readback consumes 3 more for total7 while preserving the durable B journal.',
     'The fixture does not kill a Rust process or release the original owner lane. Actual Busy, consumed client, dispatch-once flag and 4 then7 frame counts detect cancellation reuse/fallback.'),
]
test_path = A + 'circuit_original_evaluation_training_read_tests.rs'
prefix = 'runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::evaluation_host::fixture::training_read_support::tests::'
mapping = {
    'status': 'STATIC_MAPPING_NATIVE_UNRUN', 'base_source': BASE,
    'native_budgets_to_preserve': {'nextest_test_seconds': 60, 'rust_min_stack_bytes': 8388608,
                                  'test_threads': 2, 'retries': 0,
                                  'readonly_request_limit': 128, 'readonly_request_millis': 500},
    'names_note': 'Expected fully qualified names derive from the historical original panel test prefix and the unchanged/added module mounts. A fresh native listing/JUnit must confirm them; no compiled listing or native result exists for this cohort.',
    'fixture_chain': [
        ref(A + 'circuit_original_evaluation_training_read_support_tests.rs', 'PanelFixture::completed_for_publication('),
        ref(A + 'circuit_original_evaluation_training_read_support_tests.rs', 'Trainer::recover_original_stage('),
        ref(A + 'circuit_original_evaluation_training_read_support_tests.rs', 'let training = client.readback().await?'),
        ref(A + 'circuit_original_evaluation_training_read_support_tests.rs', 'training_ports::readonly_channel('),
        ref(A + 'circuit_original_evaluation_training_read_support_tests.rs', 'TrainingComposition::Original {'),
        ref(A + 'circuit_original_evaluation_host_support_tests.rs', 'into_host_from_original_training_readback('),
        ref(A + 'neuron_cell_evaluation_host_training_readback.rs', 'OriginalPanelTrainingSourceV1::from_original_training_readback('),
        ref(A + 'cell_q24_training_panel_read_peer_tests.rs', 'original_training_readback_response(bytes, request_id)'),
    ],
    'frame_scope': 'Counts apply to one actual T readonly channel after fixture setup. The initial D and T command reads are separate closed setup peers. These tests do not establish the aggregate Root/Version/S/C 128-frame budget.',
    'fixture_limits': 'Same-process fixed-purpose transport fixture, real SourceBound T handler and original owner/journal reads. Role credentials, Product declarations and B clock remain explicit fixtures. This bridge does not itself prove production four-connection admission or ordinary deployment.',
    'cases': [],
    'independent_review': {'reviewer': 'candidate_audit', 'type': 'static code review only',
                           'finding': 'Confirmed actual consuming factory, Bound pin, real T replies, expected 5/11/4/4/7 requests and 5/11/3/4/7 Completed replies; no legacy/canned fallback found.',
                           'native_or_latency_proven': False},
}
for name, requests, completed, behavior, assertions, fallback in cases:
    mapping['cases'].append({'name': name, 'expected_native_name': prefix + name,
                             'source': ref(test_path, 'async fn ' + name + '('),
                             'expected_actual_t_requests': requests,
                             'expected_actual_t_completed_replies': completed,
                             'behavior': behavior, 'assertions': assertions,
                             'why_legacy_or_wrong_slot_cannot_pass': fallback,
                             'native_status': 'UNRUN'})
(ROOT / 'NATIVE-PROOF-MAPPING.json').write_text(json.dumps(mapping, indent=2) + '\n')

files = []
for row in manifest['files']:
    content = (ROOT / 'postimages' / row['path']).read_bytes()
    assert meta(content) == row['after']
    files.append({'path': row['path'], 'local_area': 'postimages',
                  'base_commit': BASE, 'base': None if row['origin']['base_absent'] else row['base'],
                  'after': row['after'], 'kind': row['origin']['kind'], 'actual_rustfmt': True})
files.append({'path': QA, 'local_area': 'work', 'base_commit': BASE, 'base': None,
              'after': meta((ROOT / 'work' / QA).read_bytes()), 'kind': 'new_source_guard', 'actual_rustfmt': False})
old_qa = json.loads((ROOT / 'legacy-host-qa-scoped-v1/result.json').read_text())
assert old_qa['returncode'] == 0
files.append({'path': OLD_QA, 'local_area': 'legacy-qa-review/postimages',
              'base_commit': old_qa['base_sha'], 'base': old_qa['before'], 'after': old_qa['after'],
              'kind': 'existing_source_guard_two_marker_migration', 'actual_rustfmt': False})
guard = json.loads((ROOT / 'guard-final-actual-v1/result.json').read_text())
replay = json.loads((ROOT / 'strict-replay-v1/result.json').read_text())
assert guard['returncode'] == 0 and replay['status'] == 'PASS'
artifact_names = ['manifest.json', 'complete-postimages.json.gz', 'collector.stdout.raw.log',
                  'panel-training-formatted.patch', 'panel-training-57b-corrected.patch',
                  'format-only.patch', 'CALLERS-DELTA.actual.json', 'FORMAT-MARKER-ADAPTATIONS.json',
                  'NATIVE-PROOF-MAPPING.json', 'PRESERVED_FUNCTIONS.formatted.json',
                  'guard-final-actual-v1/result.json', 'guard-final-actual-v1/source-guard.raw.log',
                  'guard-final-actual-v1/inputs.json', 'guard-attempt-1/result.json', 'guard-attempt-1/raw.log',
                  'strict-replay-v1/result.json', 'legacy-qa-review/host-marker-migration.patch',
                  'legacy-host-qa-scoped-v1/result.json', 'legacy-host-qa-scoped-v1/raw.log']
delivery = {
    'status': 'ACTUAL_FORMAT_VERIFIED_SCOPED_GUARDS_PASSED_NATIVE_UNRUN',
    'base_commit': BASE, 'base_tree': manifest['source_tree'],
    'rust_product_files': 8, 'rust_test_files': 6, 'python_source_guards': 2,
    'files': files,
    'validation': {'actual_formatter_returncode': 0, 'formatted_rust_files': 14,
                   'formatted_files_changed': len(manifest['format_changed']),
                   'new_guard_tests_passed': 6, 'one_legacy_security_test_passed': 1,
                   'guard_scope': 'Local partial mirrors with proposed CALLERS. No full source/caller gate for B has run.',
                   'strict_touched_path_replays_passed': 3, 'replay_offsets_or_fuzz': False,
                   'original_formatter_patch_real_absence_check_returncode': replay['original_formatter_patch_check_returncode'],
                   'unchanged_original_functions': 22, 'body_migrations_preserving_remaining_bytes': 4,
                   'compile_run': False, 'native_tests_run': False},
    'global_inventory_merge': {'delta_base': 'sha256:abd68af6b993cb2b363c1909581b628e6f94bab0696eff2e55120d5cf9d2f4b9',
                              'current_registry_to_preserve': 'sha256:a7db9c047ed16b33a889fd95934e64b2268ff1c1b8d4225dc4b558968fddf757',
                              'never_overwrite_with_old_full_manifest': True,
                              'already_fixed_callers_not_repeated_in_delta': ['learning_original_owner_command_channel', 'learning_original_evaluation_host_profile', 'learning_original_evaluation_host_constructor']},
    'qualification': {'ordinary_adopt': 0, 'ordinary_no_update': 0, 'daemon_root_cold_recovery': 0},
    'open_risks': [
        'The 14 Rust files and five mechanism tests have not been compiled or executed; private visibility, lifetime, clippy and runtime issues may remain.',
        'The original 500ms readonly exchange and 60s per-test budgets are unchanged; the new real-owner fixtures must prove they finish within them.',
        'Three/four actual T reads close only the B Host panel transaction. Model-material export retains its original read path; aggregate Root/Version/S/C 128-frame and four-session closure remains separate.',
        'Only the new six guards and one affected legacy Host security case were executed locally. A full exact-head source gate and full caller verifier are required after central union.',
        'The exact d397 legacy Host QA migration preserves its added factory caller tuple. Other unseen legacy QA in the full repository still require the complete gate.',
    ],
    'artifacts': [{'path': name, **meta((ROOT / name).read_bytes())} for name in artifact_names],
    'main_pr_modified_by_this_delivery': False,
}
(ROOT / 'VERIFIED_MANIFEST.json').write_text(json.dumps(delivery, indent=2) + '\n')
print(json.dumps({'files': len(files), 'rust': 14, 'qa': 2,
                  'mapping': meta((ROOT / 'NATIVE-PROOF-MAPPING.json').read_bytes()),
                  'verified_manifest': meta((ROOT / 'VERIFIED_MANIFEST.json').read_bytes())}))
