"""Audit retained workflow artifacts without executing their contents or tests."""
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parent
SOURCE = '2d7506108fd1b7813d5afbe2bbb0aaf5d9460c6d'
TREE = '80562dbe724b082f388828b32fb305d036e8dff7'
BASE = '3a81000aae08c658276958d678874aca4db5eedd'
MERGE = '21ceefde202d58ef60e937d637f725727a9fe086'
EXPECTED = {
    'dispatcher': {'authbus_dispatch::tests::' + n for n in (
        'lost_queue_reply_recovers_from_sqlite_using_lookup_only_and_exact_receipt',
        'abandoned_first_claim_without_admission_is_quarantined_after_lookup_missing',
        'revocation_during_queue_request_prevents_success_ack',
        'ready_generation_and_owner_private_trust_are_required_before_admission',
        'matching_receipt_metadata_with_different_queue_input_never_acknowledges',
        'pq::pq_text_producer_recovers_through_existing_dispatch_and_rejects_wire_and_config_downgrade',
        'pq::pq_text_owner_resumes_after_revocation_rotation_and_rejected_config_rollback',
        'lease_delay::trust_refresh_sqlite_wait_cannot_authorize_transport_with_an_expired_lease',
        'policy_rollback::pq_removed_thread_cannot_return_through_owner_file_rollback_after_reopen',
        'policy_rollback::pq_owner_requires_explicit_nonzero_policy_revision_and_accepts_set_ordering',
        'policy_rollback::pq_bound_policy_refuses_renewal_without_policy_snapshot',
        'policy_rollback::pq_policy_change_fences_stale_renewal_and_current_policy_restores_dispatch',
        'checkpoint_sync::concurrent_checkpoint_syncs_share_owner_lock_and_preserve_rollback_rejection',
        'checkpoint_sync::cancelled_checkpoint_sync_waiter_and_owner_release_exclusive_admission',
    )},
    'product': {
        'signed_text_crosses_real_queue_once_and_current_trust_rejects_invalid_ingress',
        'pq_signed_text_crosses_real_queue_after_rejection_without_downgrade',
        'real_agentd_without_explicit_trust_rejects_signed_text',
    },
}
COMMANDS = {
    'dependencies': ['cargo', 'fetch', '--locked', '--manifest-path', 'codex-rs/Cargo.toml'],
    'dispatcher': ['just', 'test', '--locked', '-p', 'codex-hepta-agentd', '--lib', '-E', 'test(authbus_dispatch::tests::)', '--no-capture', '--retries', '0', '--test-threads=1'],
    'product': ['just', 'test', '--locked', '-p', 'codex-hepta-agentd', '--test', 'authbus_text_product', '--no-capture', '--retries', '0', '--test-threads=1'],
    'fix': ['just', 'fix', '--locked', '-p', 'codex-hepta-evidence', '-p', 'codex-hepta-agentd'],
    'format': ['just', 'fmt', '--base', BASE],
}
EXPECTED_ARTIFACTS = {
    f'pq-policy-renewal-{runner}-{lane}-41609576436-1'
    for runner in ('ubuntu-24.04', 'ubuntu-24.04-arm')
    for lane in ('source-head', 'base-merge')
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


lanes = []
for archive in sorted(ROOT.glob('*.zip')):
    meta = json.loads(archive.with_name(archive.stem + '-metadata.json').read_text())
    raw_archive = archive.read_bytes()
    assert sha(raw_archive) == meta['digest'].removeprefix('sha256:')
    assert len(raw_archive) == meta['size_in_bytes']
    assert meta['workflow_run']['head_sha'] == SOURCE and meta['workflow_run']['id'] == 41609576436
    assert meta['name'] in EXPECTED_ARTIFACTS
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        assert len(names) == len(set(names))
        assert all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in names)
        candidate = json.loads(z.read('candidate.json'))
        after = json.loads(z.read('candidate-after.json'))
        assert candidate == after
        assert candidate['source_sha'] == SOURCE and candidate['source_tree'] == TREE
        assert candidate['base_sha'] == BASE and candidate['tested_tree'] == TREE
        tested = SOURCE if candidate['lane'] == 'source-head' else MERGE
        assert candidate['tested_sha'] == tested
        commands, identities = {}, []
        for name, argv in COMMANDS.items():
            receipt_raw = z.read(name + '.json')
            r = json.loads(receipt_raw)
            log = z.read(r['log_file'])
            assert sha(log) == r['log_sha256'] and len(log) == r['log_bytes']
            assert r['source_sha'] == SOURCE and r['tested_sha'] == tested and r['base_sha'] == BASE
            assert r['lane'] == candidate['lane'] and r['run_id'] == '41609576436' and r['run_attempt'] == '1'
            assert r['command'] == argv and r['before'] == r['after']
            assert r['before']['dirty'] is False and r['before']['tree'] == TREE and r['before']['commit'] == tested
            identities.append(r['before'])
            result = {'original_receipt': r, 'receipt_sha256': sha(receipt_raw), 'log_hash_and_length_verified': True}
            if name in EXPECTED:
                text = re.sub(r'\x1b\[[0-9;]*m', '', log.decode())
                cases = re.findall(r'^test ([A-Za-z0-9_:]+) \.\.\. (ok|ignored|FAILED)\s*$', text, re.M)
                passed = [n for n, status in cases if status == 'ok']
                required = EXPECTED[name]
                result.update({'cases': cases, 'required_case_set': sorted(required), 'all_required_cases_ran_once_and_passed': (
                    len(cases) == len(required) and len(passed) == len(required) and set(passed) == required
                    and r['minimum_tests'] == len(required) and r['observed_passed_tests'] == len(required)
                    and r['observed_failed_tests'] == 0)})
            result['passed'] = (r['status'] == 'passed' and r['command_exit_code'] == 0 and r['exit_code'] == 0
                and r['timed_out'] is False and r['output_limit_exceeded'] is False
                and result.get('all_required_cases_ran_once_and_passed', True))
            commands[name] = result
        assert all(identity == identities[0] for identity in identities)
        selected = json.loads(z.read('selected-tests.json'))
        assert all(selected[n]['passed'] is True and set(selected[n]['expected']) == required for n, required in EXPECTED.items())
        assert all(selected[n]['observed'] == [list(case) for case in commands[n]['cases']] for n in EXPECTED)
        lanes.append({
            'artifact_id': meta['id'], 'artifact_name': meta['name'], 'archive_file': archive.name,
            'archive_sha256': sha(raw_archive), 'archive_size': len(raw_archive), 'github_digest_verified': True,
            'candidate_before': candidate, 'candidate_after': after, 'all_command_identities_equal_and_clean': True,
            'commands': commands,
            'original_member_inventory': [{'name': n, 'bytes': len(z.read(n)), 'sha256': sha(z.read(n))} for n in names],
            'selected_controls_and_original_postchecks_passed': all(r['passed'] for r in commands.values()),
        })
assert len({lane['artifact_name'] for lane in lanes}) == len(lanes)
document = {
    'schema': 'hepta-renewal-retained-original-artifact-review-v1', 'run_id': 41609576436, 'run_attempt': 1,
    'source_commit': SOURCE, 'source_tree': TREE, 'base_commit': BASE, 'prospective_merge_commit': MERGE,
    'reviewed_archive_count': len(lanes), 'all_four_lanes_present': {lane['artifact_name'] for lane in lanes} == EXPECTED_ARTIFACTS,
    'lanes': lanes, 'commands_or_tests_executed_by_this_review': False, 'archive_contents_modified': False,
    'runtime_scope': 'Only the original 14 dispatcher and 3 process controls at this source; the added cancellation case pauses the active owner before DB mutation.',
    'budget_source': '.github/workflows/hepta-pq-policy-renewal.yml at the reviewed source tree',
    'budget_source_sha256': '28ed20a7b499fb9044588d6f6048d1eec8bd02d8e7062626e0f54281fcc6902b',
    'original_budgets_seconds': {'job': 5400, 'dependencies': 600, 'dispatcher': 3600, 'product': 1800, 'fix': 1200, 'format': 300},
    'whole_chain_pq_qualification': False, 'full_hepta_native_or_deployment_qualification': False, 'other_workflow_failures_waived': False,
}
out = ROOT / ('review-' + str(len(lanes)) + '-lanes.json')
assert not out.exists(), 'Preserve prior observation records'
out.write_text(json.dumps(document, indent=2) + '\n')
print(json.dumps({'review': str(out), 'sha256': sha(out.read_bytes()), 'reviewed_lanes': len(lanes), 'results': [
    {'artifact_id': lane['artifact_id'], 'name': lane['artifact_name'], 'passed': lane['selected_controls_and_original_postchecks_passed'],
     'dispatcher_cases': len(lane['commands']['dispatcher']['cases']), 'product_cases': len(lane['commands']['product']['cases'])} for lane in lanes]}))
