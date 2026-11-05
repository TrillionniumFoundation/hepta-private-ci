#!/usr/bin/env python3
"""Static comparison of the frozen external H4 package; never launches it."""
from pathlib import Path
import ast
import base64
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
H4 = ROOT / 'model_storage/h4-capture-repair/native'
H3 = ROOT / 'model_storage/h3-preparation/native'
CLOUD = ROOT / 'model_storage/h4-capture-repair/cloud-utility-controls'


def load(path):
    return json.loads(path.read_bytes())


def describe(path):
    data = path.read_bytes()
    return {'path': str(path.relative_to(ROOT)), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def constant(module, name):
    matches = [node.value for node in module.body if isinstance(node, ast.Assign)
               and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
               and node.targets[0].id == name]
    assert len(matches) == 1
    return ast.literal_eval(matches[0])


def main():
    manifest_path = H4 / 'frozen-package-manifest.json'
    manifest = load(manifest_path)
    assert describe(manifest_path)['sha256'] == 'a977ddb4455e8b3c523924efa53d42f94515f29199c6f2ac51c081e84df2a44f'
    files = manifest['files'] + [manifest['request']]
    for item in files:
        actual = describe(H4 / item['path'])
        assert (actual['bytes'], actual['sha256']) == (item['bytes'], item['sha256'])

    launch = load(H4 / 'h4-exact-launch-plan.json')
    plan = load(H4 / 'h4-native-plan.json')
    old_plan = load(H3 / 'h3-native-plan.json')
    assert plan['source_frozen'] is True and plan['execution_configuration_frozen'] is True
    assert plan['source_commit'] == manifest['source_commit'] == launch['source_commit'] == '6db78eca53a5acdda0d96873d3f4cd65863426f0'
    assert plan['source_tree'] == manifest['source_tree'] == launch['source_tree'] == 'e91f5994017fc5d2cfe58d405a20ee6ad9376772'
    assert plan['steps'] == old_plan['steps'] and len(plan['steps']) == 13
    assert plan['selected_total'] == old_plan['selected_total'] == launch['selected_exact_cases'] == 74
    assert sum(len(step['expected_names']) for step in plan['steps']) == 74
    assert plan['original_job_timeout_seconds'] == old_plan['original_job_timeout_seconds'] == 5400
    assert (launch['expected_tracked_count'], launch['expected_tracked_bytes']) == (11840, 183410043)
    plan_changes = sorted(k for k in plan.keys() | old_plan.keys() if plan.get(k) != old_plan.get(k))
    assert plan_changes == ['execution_configuration_frozen', 'external_execution_revision', 'live_parent_correspondence']

    immutable = {
        'nextest_fd_runner.py': 'nextest_fd_runner.py',
        'fd_gate_evidence.py': 'fd_gate_evidence.py',
        'test_nextest_fd_runner.py': 'test_nextest_fd_runner.py',
        'test_fd_gate_targets.py': 'test_fd_gate_targets.py',
        'h4-selected-tests-guard.py': 'h3-selected-tests-guard.py',
        'h4-extra-controls.json': 'h3-extra-controls.json'}
    for current, prior in immutable.items():
        assert (H4 / current).read_bytes() == (H3 / prior).read_bytes()
    extra = load(H4 / 'h4-extra-controls.json')['full_evidence_library']
    assert extra['minimum'] == 22 and extra['expected_passed'] == 161 and len(extra['expected_names']) == 161
    assert len(extra['expected_ignored']) == 1

    budget = load(H4 / 'h4-budget-map.json')
    old_budget = load(H3 / 'h3-budget-map.json')
    assert budget['outer_seconds'] == old_budget['outer_seconds'] == launch['outer_timeout_seconds'] == 5400
    assert budget['per_test_seconds'] == old_budget['per_test_seconds'] == 60
    assert budget['retries'] == old_budget['retries'] == 0
    assert budget['test_threads'] == old_budget['test_threads'] == 1
    assert [gate for gate in budget['gates'] if gate['name'] != 'live-parent-correspondence-controls'] == old_budget['gates']
    new = [gate for gate in budget['gates'] if gate['name'] == 'live-parent-correspondence-controls']
    assert len(new) == 1 and new[0]['timeout_seconds'] == 20 and new[0]['actual_product_credit'] is False

    bundle = load(H4 / 'h4-native-bundle.json')
    expected = {item['path']: item['sha256'] for item in launch['files']}
    assert len(bundle) == len(expected) == 12 and set(bundle) == set(expected)
    for name, encoded in bundle.items():
        decoded = base64.b64decode(encoded, validate=True)
        assert decoded == (H4 / name).read_bytes()
        assert hashlib.sha256(decoded).hexdigest() == expected[name]
    bootstrap_text = (H4 / 'bootstrap_h4_native.py').read_text()
    bootstrap = ast.parse(bootstrap_text)
    assert constant(bootstrap, 'EXPECTED') == expected
    request_path = H4 / 'joint-h4-native-attempt-1/launch-request.json'
    request = load(request_path)
    assert request['host'] == launch['host'] == 'desktop'
    assert request['executable'] == launch['executable'] == '/usr/bin/python3'
    assert request['cwd'] == launch['cwd']
    assert request['timeout_seconds'] == launch['outer_timeout_seconds'] == 5400
    assert request['idempotency_key'] == launch['idempotency_key'] == 'ms-joint-h4-native-6db78-attempt1-93bfcf'
    assert request['args'] == ['-c', bootstrap_text, launch['source_commit'], launch['source_tree'], launch['evidence_name']]
    assert request['stdin'] == (H4 / 'h4-native-bundle.json').read_text()
    assert request['env'] == {'PYTHONDONTWRITEBYTECODE': '1', 'GIT_NO_LAZY_FETCH': '1', 'GIT_TERMINAL_PROMPT': '0'}

    coordinator = ast.parse((H4 / 'run_h4_native_pipeline.py').read_text())
    assert constant(coordinator, 'COLLECTOR_SHA') == describe(H4 / 'test_elf_capture.py')['sha256']
    assert constant(coordinator, 'FD_RUNNER_SHA') == describe(H4 / 'nextest_fd_runner.py')['sha256']
    verifier = ast.parse((H4 / 'live_fd_correspondence.py').read_text())
    assert constant(verifier, 'FINAL_USE_GATE') == 'final-use-profile-controls'
    assert constant(verifier, 'FINAL_USE_TARGET') == 'codex_hepta_contracts'
    assert constant(verifier, 'FINAL_USE_CHILD_CASE') == 'final_use::tests::killed_owner_releases_lock_but_keeps_claim'

    cloud_receipt = load(CLOUD / 'receipt.json')
    for item in cloud_receipt:
        log_path = Path(item['log'])
        assert hashlib.sha256(log_path.read_bytes()).hexdigest() == item['log_sha256']
    proc_receipt, synthetic_receipt = cloud_receipt
    assert proc_receipt['returncode'] == 1 and synthetic_receipt['returncode'] == 0
    assert 'FAILED (errors=3)' in Path(proc_receipt['log']).read_text()
    assert Path(proc_receipt['log']).read_text().count("RuntimeError: collector requires the process and /proc to share a PID namespace") == 3
    assert 'Ran 3 tests' in Path(synthetic_receipt['log']).read_text() and '\nOK\n' in Path(synthetic_receipt['log']).read_text()
    assert proc_receipt['sources']['test_executed_binary_capture.py'] != describe(H4 / 'test_executed_binary_capture.py')['sha256']
    assert synthetic_receipt['sources']['live_fd_correspondence.py'] == describe(H4 / 'live_fd_correspondence.py')['sha256']

    report = {
        'schema': 'h4-external-capture-independent-review-v1',
        'decision': 'No concrete blocker found in the frozen external package; actual desktop prerequisites and the full original native sequence remain required.',
        'source_commit': launch['source_commit'], 'source_tree': launch['source_tree'],
        'repository_source_unchanged': True,
        'frozen_manifest': describe(manifest_path), 'launch': describe(H4 / 'h4-exact-launch-plan.json'),
        'request': describe(request_path), 'bundle': describe(H4 / 'h4-native-bundle.json'),
        'bundle_members': 12, 'manifest_file_hashes_checked': len(files),
        'decoded_bundle_equals_files_and_bootstrap_hash_allowlist': True,
        'exact_request_bootstrap_and_stdin_match': True,
        'original_workflow_steps_equal': 13, 'selected_exact_names': 74,
        'unchanged_primary_files': [{'current': current, 'prior': prior, 'sha256': describe(H4 / current)['sha256']} for current, prior in immutable.items()],
        'full_evidence_original_wrapper_minimum': 22,
        'full_evidence_exact_name_guard_passed': 161, 'full_evidence_expected_ignored': extra['expected_ignored'],
        'budgets': {'outer_seconds': 5400, 'per_test_seconds': 60, 'retries': 0, 'test_threads': 1,
                    'original_gate_list_and_relative_order_equal': True,
                    'only_added_gate': new[0], 'added_gate_charged_inside_original_outer': True},
        'mechanism_review': [
            'Equal complete child and direct-parent identity/argv/image observations surround opening both actual executable FDs.',
            'Equal complete ancestor chains preserve real PPID links to the exact bound wrapper PID/start; both opened image metadata remain stable through retention.',
            'Parent need not remain alive after the bounded live observation interval; held FD bytes preserve the observed image without claiming end-of-copy liveness.',
            'Direct matches keep exact primary PID/start/source/hash/metadata/argv/case identity.',
            'The sole auxiliary role is fixed to FinalUse killed_owner, one same-image direct child of its unique actual outer FD, exact argv and source; no additional case credit.',
            'Unknown child, wrong/ambiguous parent, source/image/name/argv mismatch, missing relationship fields, chain drift, duplicate or additional helper cause correspondence errors.',
            'The coordinator preserves original outcomes and FD records and propagates original collector, primary verifier and new correspondence errors before qualification.',
            'Source/raw guards, exact counts, primary pending/exec-error rejection, original command deadlines, full-library ignored-name check and final configuration check remain active.'],
        'observed_utility_evidence': {
            'source': describe(CLOUD / 'receipt.json'),
            'synthetic_correspondence': {'cases': 3, 'returncode': 0, 'log': describe(Path(synthetic_receipt['log'])), 'native_product_credit': False},
            'interim_proc_controls': {'cases': 3, 'errors': 3, 'returncode': 1, 'reason': 'original PID namespace guard',
                'log': describe(Path(proc_receipt['log'])), 'executed_utility_sha256': proc_receipt['sources']['test_executed_binary_capture.py'],
                'final_utility_sha256': describe(H4 / 'test_executed_binary_capture.py')['sha256'],
                'scope': 'Interim control source failed before capture. Final strengthened source must execute in the original desktop prerequisite; it has no pass credit from this receipt.'}},
        'limits': [
            'Static review is not desktop native execution, complete runtime closure, or a hostile privileged-writer proof.',
            'Polling can miss short processes; no missing observation or old H3 parent relation is invented.',
            'H3 remains FAILED and no H1/H2/H3 result is requalified.',
            'Only the parent scheduler may launch after the exact archive owned-process release; bulk downloads remain paused.'],
        'native_runs_by_this_reviewer': 0, 'remote_reads_by_this_reviewer': 0,
        'review_execution_note': 'The first local static-comparison attempt incorrectly assumed the wrapper minimum was 161 and stopped on that reviewer assertion. The unchanged original wrapper minimum is 22; the coordinator separately requires all 161 exact selected names and one exact ignored name. The assertion was corrected to verify both original layers; no project gate or budget was changed.',
        'input_inventory': [describe(H4 / item['path']) for item in files] + [describe(manifest_path), describe(CLOUD / 'receipt.json')]
    }
    path = OUT / 'review.json'
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'review': describe(path), 'bundle_members': 12, 'original_workflow_steps': 13,
                      'original_selected_cases': 74, 'native_runs': 0, 'remote_reads': 0}))


if __name__ == '__main__':
    main()
