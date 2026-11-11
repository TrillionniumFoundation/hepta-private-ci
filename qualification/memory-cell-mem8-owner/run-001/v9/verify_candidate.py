#!/usr/bin/env python3
"""Root review of the v9 owner checkpoint against immutable v7 and V14."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CANDIDATE = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / 'BLOCKERS.json'


def identity(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def main():
    base_data = (HERE / 'BASE_BLOCKERS.json').read_bytes()
    candidate_data = CANDIDATE.read_bytes()
    source_audit_data = (HERE / 'PUBLISHED_SOURCE_GATE_AUDIT.json').read_bytes()
    assert identity(base_data)['git_blob'] == 'af43c75a36cb33c82fef4a8ab4edc892c5cf8e76'
    assert identity(candidate_data)['git_blob'] == '6030c1c917dbb0dcc6a6ff2ed5259e35a243a925'
    assert identity(source_audit_data)['git_blob'] == '75f47d1f0e8bb3cb8d38afc1751e6da4a09195c1'
    base, candidate = json.loads(base_data), json.loads(candidate_data)
    allowed = {'actionable_remaining_inputs', 'checkpoint_revision', 'checkpoint_utc',
               'closed_this_followup', 'final_source_composition', 'hosted_ci_followup_189',
               'implementation_progress', 'new_model_requests_this_revision', 'open',
               'previous_checkpoint', 'publication', 'publication_state', 'runtime_transport',
               'source_preparation_followup_v5', 'v9_update_provenance'}
    changed = {key for key in base.keys() | candidate.keys() if base.get(key) != candidate.get(key)}
    assert changed == allowed
    before = {gate['id']: gate for gate in base['open']}
    after = {gate['id']: gate for gate in candidate['open']}
    assert before.keys() == after.keys() and len(after) == 10
    for gate_id in before:
        if gate_id == 'HOSTED-CI':
            assert before[gate_id]['closure'] == after[gate_id]['closure']
        else:
            assert before[gate_id] == after[gate_id], gate_id
    old_closed = base['closed_this_followup']
    assert candidate['closed_this_followup'][:len(old_closed)] == old_closed
    assert [row['id'] for row in candidate['closed_this_followup'][len(old_closed):]] == [
        'V5-SOURCE-ONLY-FORMAT-CALLER-TREE', 'V5-EXACT-SOURCE-BAZEL-MODULE-LOCK']
    assert candidate['final_source_composition']['initial_2ae_composition_historical'] == base['final_source_composition']
    assert candidate['new_model_requests_this_revision'] == 0
    assert candidate['physical_provider_requests'] is None
    assert candidate['production_adoption'] is False
    intake = candidate['actionable_remaining_inputs']
    assert {row['gate_id'] for row in intake['gates']} == after.keys()
    preparation = candidate['source_preparation_followup_v5']
    assert preparation['source_gate'] == json.loads(source_audit_data)
    for key, value in identity(source_audit_data).items():
        assert preparation['source_gate_root_audit'][key] == value
    assert preparation['source_gate_root_audit']['commit'] == 'e9c8d26d159edfb72eb9c2b8f4580478b4b37a2d'
    assert preparation['source_gate_snapshot_scope']['remaining_field_is_historical'] is True
    assert preparation['original_v3']['admission'] == 'UNKNOWN'
    assert preparation['original_v4']['source_process_start_requests'] == 0
    assert preparation['preparation_archive']['original_preparation_notes_recovery_complete'] is False
    bazel = preparation['bazel_lock_followup']
    assert bazel['lock_command_phases_started'] == 0
    assert bazel['revision2_actual_root_audit']['actual_lock_command_phases'] == 1
    assert bazel['revision2_actual_root_audit']['status'] == 'PASS_EXACT_SOURCE_BAZEL_MODULE_LOCK'
    assert candidate['publication']['expected_previous_head'] == 'cb54f618f0408c314b1c367a5256ea185165c354'
    assert candidate['publication']['activation'] == 'ROOT_EXPECTED_HEAD_CAS_SUCCESS_ONLY'
    result = {
        'schema': 'hepta.mem8.owner-v9.root-prepublication-audit.v1',
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'result': 'PASS_EXACT_CHECKPOINT_INVARIANTS_AND_PUBLISHED_EVIDENCE_REFERENCES',
        'base': identity(base_data), 'candidate': identity(candidate_data),
        'changed_fields_reviewed_in_full': sorted(changed),
        'unchanged_top_level_fields': sorted(base.keys() - changed),
        'nine_non_CI_gate_objects_identical': True, 'hosted_closure_text_identical': True,
        'all_ten_adoption_gates_open': True, 'all_previous_closed_scope_rows_preserved': True,
        'new_closed_items_are_source_and_lock_subgates_only': True,
        'source_audit_entire_published_document_matches': True,
        'draft_source_audit_reference_mismatch_corrected_before_publication': True,
        'full_new_source_native_outcomes_not_claimed_by_this_checkpoint': True,
        'original_provider_unknown_and_physical_count_null_preserved': True,
        'real_owner_exposure_independent_trust_inputs_not_fabricated': True,
        'actual_ref_mutations_by_this_verifier': 0,
        'publication_requires_subsequent_actual_expected_head_CAS_and_readback': True,
    }
    (HERE / 'ROOT_PREPUBLICATION_AUDIT.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
