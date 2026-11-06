#!/usr/bin/env python3
"""Read retained H3 evidence only; no runner, Cargo, network, or mutation of inputs."""
from collections import Counter
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
NATIVE = ROOT / 'model_storage/h3-preparation/native'
EVIDENCE = NATIVE / 'joint-h3-native-attempt-1'
FORMATTED = ROOT / 'model_storage/h3-preparation/formatted-candidate'
SOURCE = '6db78eca53a5acdda0d96873d3f4cd65863426f0'
TREE = 'e91f5994017fc5d2cfe58d405a20ee6ad9376772'
KILLED = 'final_use::tests::killed_owner_releases_lock_but_keeps_claim'


def load(path):
    return json.loads(path.read_bytes())


def identity(path):
    data = path.read_bytes()
    return {'path': str(path.relative_to(ROOT)), 'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def parse_receipt(name):
    receipt_path = EVIDENCE / (name + '.json')
    receipt = load(receipt_path)
    raw_path = EVIDENCE / receipt['log_file']
    raw = raw_path.read_bytes()
    assert len(raw) == receipt['log_bytes']
    assert hashlib.sha256(raw).hexdigest() == receipt['log_sha256']
    assert all(receipt[side]['commit'] == SOURCE and receipt[side]['tree'] == TREE
               and receipt[side]['dirty'] is False for side in ('before', 'after'))
    clean = re.sub(r'\x1b\[[0-9;]*m', '', raw.decode())
    cases = re.findall(r'^test ([A-Za-z0-9_:]+) \.\.\. (ok|ignored|FAILED)\s*$', clean, re.M)
    assert sum(result == 'ok' for _, result in cases) == receipt['observed_passed_tests']
    assert sum(result == 'FAILED' for _, result in cases) == receipt['observed_failed_tests']
    return receipt, cases, [receipt_path, raw_path]


def main():
    pipeline = load(EVIDENCE / 'pipeline-status.json')
    assert pipeline['status'] == 'failed'
    assert pipeline['source_before'] == pipeline['source_after']
    assert pipeline['configuration_unchanged'] is True
    assert not any(name in pipeline['gates'] for name in ('full-evidence-library', 'fix', 'fmt'))

    product, product_cases, files = parse_receipt('effect-pq-product')
    assert product['status'] == 'passed' and product['command_exit_code'] == 0
    assert product['timed_out'] is False and len(product_cases) == 2
    product_fd_path = EVIDENCE / 'effect-pq-product.fd-executed-binaries.json'
    product_fd = load(product_fd_path)
    assert not product_fd['errors'] and product_fd['per_case_bijection_verified'] is True
    assert Counter(record['exact_test'] for record in product_fd['records']) == Counter(name for name, _ in product_cases)

    proof_path = EVIDENCE / 'effect-pq-product-process/1032265-1793915885381498081/completed.json'
    proof = load(proof_path)
    verify_path = EVIDENCE / 'effect-pq-product-daemon-verification.json'
    verification = load(verify_path)
    assert verification['verified'] is True
    assert verification['sha256'] == identity(proof_path)['sha256']
    assert proof['source']['commit'] == SOURCE and proof['source']['tree'] == TREE
    first, second = proof['first_process'], proof['second_process']
    assert first['source'] == second['source'] == proof['source']
    assert first['capture_method'] == 'first-live-fd-hash-copy'
    assert first['full_hash_and_copy_this_capture'] is True
    assert first['same_held_file_object_verified'] is False
    assert second['capture_method'] == 'same-held-file-object-reuse'
    assert second['full_hash_and_copy_this_capture'] is False
    assert second['same_held_file_object_verified'] is True
    assert (first['pid'], first['start_ticks']) != (second['pid'], second['start_ticks'])
    assert (first['spawn_generation'], second['spawn_generation']) == (1, 5)
    for key in ('actual_executable', 'cargo_resolved_binary', 'retained_copy', 'sha256', 'bytes', 'device', 'inode'):
        assert first[key] == second[key]
    for image in (first, second):
        assert image['opened_fd_and_process_identity_verified'] and image['owner_and_generation_verified']
        assert image['origin_capture_pid'] == first['pid'] and image['origin_capture_start_ticks'] == first['start_ticks']
    assert proof['post_count'] == proof['physical_apply_count'] == proof['used_nonces'] == 1
    assert proof['lookup_count'] == 2
    assert proof['provider_ack']['key'] == proof['provider_record']['effect_key']
    for key in ('payload_sha256', 'provider_operation_id_sha256'):
        assert proof['provider_ack'][key] == proof['provider_record'][key]
    assert proof['terminal']['observation'] == 'succeeded'
    assert proof['cleanup_exit']['exact_lease_removed'] is True
    assert proof['cleanup_exit']['supervisor_pre_fenced_draining'] is True

    finaluse, cases, finaluse_files = parse_receipt('final-use-profile-controls')
    files += finaluse_files
    fd_path = EVIDENCE / 'final-use-profile-controls.fd-executed-binaries.json'
    live_path = EVIDENCE / 'final-use-profile-controls.live-polled-binaries.json'
    fd, live = load(fd_path), load(live_path)
    assert finaluse['status'] == 'passed' and finaluse['command_exit_code'] == 0
    assert finaluse['timed_out'] is False
    assert len(cases) == len(fd['records']) == 50 and all(result == 'ok' for _, result in cases)
    assert fd['per_case_bijection_verified'] is True
    assert Counter(record['exact_test'] for record in fd['records']) == Counter(name for name, _ in cases)
    assert len({(record['pid'], record['start_ticks']) for record in fd['records']}) == 50
    assert fd['errors'] == ['live process capture differs from exact fd-exec record']
    assert not live['errors'] and len(live['records']) == 50
    fd_by_id = {(record['pid'], record['start_ticks']): record for record in fd['records']}
    live_by_id = {(record['pid'], record['start_ticks']): record for record in live['records']}
    common = set(fd_by_id) & set(live_by_id)
    extra = [record for key, record in live_by_id.items() if key not in fd_by_id]
    missed = [record for key, record in fd_by_id.items() if key not in live_by_id]
    assert len(common) == 49 and len(extra) == len(missed) == 1
    assert all(fd_by_id[key]['sha256'] == live_by_id[key]['sha256'] for key in common)
    outer = [record for record in fd['records'] if record['exact_test'] == KILLED]
    assert len(outer) == 1
    assert extra[0]['observed_selected_tests'] == [KILLED]
    assert extra[0]['sha256'] == outer[0]['sha256']
    assert not any(key in extra[0] for key in ('argv', 'parent_pid', 'parent_start_ticks', 'ancestor_chain', 'ancestor_chain_before', 'ancestor_chain_after'))

    contract_source = OUT / 'source/codex-rs/hepta-contracts/src/final_use_tests.rs'
    assert identity(contract_source)['git_blob'] == '76ea4ef5aab6c25c806fcbfe6a0f24329b60dc69'
    product_source = FORMATTED / 'codex-rs/hepta-agentd/tests/automation_effect_pq_product.rs'
    helper_source = FORMATTED / 'codex-rs/hepta-agentd/tests/support/automation_effect_binary.rs'
    files += [EVIDENCE / 'pipeline-status.json', product_fd_path, proof_path, verify_path, fd_path, live_path,
              EVIDENCE / 'final-use-profile-controls.fd-capture-config.json', contract_source,
              OUT / 'final-use-tests-exact.raw.json', product_source, helper_source,
              NATIVE / 'test_elf_capture.py', NATIVE / 'run_h3_native_pipeline.py',
              NATIVE / 'fd_gate_evidence.py', NATIVE / 'nextest_fd_runner.py']

    report = {
        'schema': 'h3-independent-process-and-finaluse-review-v1',
        'method': 'Independent local raw/receipt/source reads and deterministic reconciliation; no native rerun, production change, remote read, or qualification override.',
        'source': {'commit': SOURCE, 'tree': TREE},
        'overall': {'status': 'FAILED', 'scope': pipeline['scope'], 'original_error': pipeline['error'],
                    'elapsed_seconds': pipeline['timed_coordinator_elapsed_seconds'],
                    'source_before_after_equal': True, 'configuration_unchanged': True,
                    'unexecuted_after_stop': ['full-evidence-library (161 selected plus 1 ignored)', 'fix', 'fmt']},
        'ordinary_process': {
            'test_outcomes': product_cases, 'wrapper_elapsed_seconds': product['elapsed_seconds'],
            'completed_sha256': identity(proof_path)['sha256'],
            'daemon_verification_receipt_sha256': identity(verify_path)['sha256'],
            'first_process': first, 'second_process': second,
            'post_count': 1, 'physical_apply_count': 1, 'lookup_count': 2, 'used_nonces': 1,
            'provider_ack_matches_original_key_payload_operation': True, 'terminal': proof['terminal'],
            'reached_assertions': [
                'provider fsync completed and acknowledgement not delivered before the controlled kill',
                'new daemon process and newer owner generation; same held actual file object',
                'old client and old generation grant refused without a second POST',
                'temporary lookup absence remains Indeterminate with no effect receipt',
                'subsequent lookup recovers the original operation and durable succeeded terminal',
                'third local read returns the same terminal without an additional provider lookup',
                'POST 1, physical application 1, provider lookups 2, FinalUse nonce 1',
                'original recovery frontier/trust bytes and claimed external frontier remain unchanged',
                'store reopen confirms original operation digest and identical durable terminal receipt',
                'second owned process cleanup and exact lease removal'],
            'limits': [
                'controlled local operator/provider fixtures and supervisor pre-fenced SIGKILL, not unannounced power loss',
                'same-host process restart, not full-host database restore or independently administered frontier custody',
                'opened held-file metadata stability, not a privileged-writer resistance proof',
                'local review verifies receipt/proof/raw bytes; daemon ELF itself is retained remotely and has not been independently downloaded or rehashed by this review',
                'no H1/H2 retrospective credit and no overall H3 PASS']},
        'finaluse': {
            'actual_raw_outcomes': cases, 'wrapper_elapsed_seconds': finaluse['elapsed_seconds'],
            'raw_50_ok_and_fd_50_exact_case_bijection': True,
            'primary_fd_unique_images': fd['unique_actual_elf_sha256'],
            'poll_records': 50, 'matching_outer_records': 49,
            'extra_poll_record': extra[0], 'outer_fd_for_same_case': outer[0],
            'fd_case_missed_by_poll': missed[0],
            'self_spawn_source': {'path': str(contract_source.relative_to(ROOT)),
                'git_blob': identity(contract_source)['git_blob'], 'lines': [708, 752],
                'mechanism': 'The exact killed_owner test directly spawns current_exe with --exact, its own test name, --nocapture and CHILD_STATE; the child persists a claim then parks until the outer test kills it. Child output is suppressed.'},
            'finding': 'The coordinator requires every observed selected-image process to have its own fd-runner record; a direct self-spawn bypasses the nextest target runner. This is a concrete over-strict capture-composition assumption.',
            'historical_attribution_limit': 'The extra record is consistent with the self-spawn source, image and time, but old polling records omit full argv and contemporaneous immediate parent/ancestor identities. Its exact parent is not retrospectively proven; do not delete, relabel, or fill the missing short outer capture.',
            'h3_original_gate_status_preserved': 'FAILED'},
        'h4_minimal_acceptance_boundary': [
            'Keep exact original outcome-to-fd-record bijection and unique identity checks unchanged; auxiliary children never count as tests or replace missing fd records.',
            'Allow only the fixed FinalUse gate, contracts image, killed_owner exact name and exact expected argv for the known direct helper role.',
            'Save full child argv and stable before/after child PID/start, opened executable identity and ancestry chain to the exact bound wrapper PID/start.',
            'Require immediate parent PID/start to match the unique exact killed_owner outer fd record, plus contemporaneous stable parent argv and actual executable identity. Same wrapper ancestry, source, image or name alone is insufficient.',
            'Reject ambiguous, wrong-parent, reparented, changed-exec, wrong-image/name/source or incomplete observed helper attribution. Parent disappearance cannot be repaired with a later process listing.',
            'Record auxiliary attribution separately, preserving every original live observation and the original raw/FD record sets.',
            'Use the same frozen source, original commands, 60-second per-test limits, wrapper budgets and 5400-second outer budget; external config revision and utility tests must be explicit.',
            'H4 evidence can only qualify a new run; H3 missing parent evidence and failed overall status remain unchanged.'],
        'recommended_focused_controls': [
            'Actual direct-child positive case tied to the intended outer PID/start/image/argv, using a controlled small executable rather than claiming a Rust gate pass.',
            'Same wrapper/image/name but different immediate parent, stale parent start, or missing parent chain must not be accepted as the known helper.',
            'Changed parent/child image or argv and ancestry instability must not pass; primary case-to-fd bijection must still fail on missing or duplicate records.'],
        'input_inventory': [identity(path) for path in dict.fromkeys(files)]}
    output = OUT / 'review.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'review': identity(output), 'input_files': len(report['input_inventory']),
                      'ordinary_process_raw_passes': len(product_cases), 'finaluse_raw_passes': len(cases),
                      'fd_outer_poll_matches': len(common), 'extra_poll': len(extra), 'poll_missing_outer': len(missed),
                      'native_reruns': 0, 'remote_reads': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
