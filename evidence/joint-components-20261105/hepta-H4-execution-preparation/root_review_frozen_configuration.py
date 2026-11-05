#!/usr/bin/env python3
"""Verify the exact H4 external package without launching or rewriting it."""
from pathlib import Path
import ast
import base64
import hashlib
import json
import shutil

WORK = Path('/workspace/scratch/93bfcfe29fc8')
H4 = WORK / 'model_storage/h4-capture-repair/native'
H3 = WORK / 'model_storage/h3-preparation/native'
OUT = Path(__file__).resolve().parent
PQ = WORK / 'pq_recovery/h4-configuration-review'
CLOUD = WORK / 'model_storage/h4-capture-repair/cloud-utility-controls'


def read(p):
    return json.loads(p.read_bytes())


def digest(p):
    b = p.read_bytes()
    return {'path': str(p.relative_to(WORK)), 'bytes': len(b),
            'sha256': hashlib.sha256(b).hexdigest()}


def constant(p, name):
    found = [n.value for n in ast.parse(p.read_text()).body
             if isinstance(n, ast.Assign) and len(n.targets) == 1
             and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name]
    assert len(found) == 1, name
    return ast.literal_eval(found[0])


def copy_exact(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        assert dst.read_bytes() == src.read_bytes(), str(dst)
    else:
        shutil.copyfile(src, dst)
    assert dst.read_bytes() == src.read_bytes()


def main():
    manifest_path = H4 / 'frozen-package-manifest.json'
    assert digest(manifest_path)['sha256'] == 'a977ddb4455e8b3c523924efa53d42f94515f29199c6f2ac51c081e84df2a44f'
    manifest = read(manifest_path)
    members = manifest['files'] + [manifest['request']]
    assert len(members) == 18
    for row in members:
        actual = digest(H4 / row['path'])
        assert (actual['bytes'], actual['sha256']) == (row['bytes'], row['sha256']), row['path']
    launch = read(H4 / 'h4-exact-launch-plan.json')
    plan = read(H4 / 'h4-native-plan.json')
    previous = read(H3 / 'h3-native-plan.json')
    request = read(H4 / manifest['request']['path'])
    assert launch['source_commit'] == manifest['source_commit'] == plan['source_commit'] == previous['source_commit'] == '6db78eca53a5acdda0d96873d3f4cd65863426f0'
    assert launch['source_tree'] == manifest['source_tree'] == plan['source_tree'] == previous['source_tree'] == 'e91f5994017fc5d2cfe58d405a20ee6ad9376772'
    assert launch['chain_commit'] == '8df4b21d893906570d48f5beafabb3b31e0aefbc'
    assert plan['steps'] == previous['steps'] and len(plan['steps']) == 13
    assert sum(len(step['expected_names']) for step in plan['steps']) == plan['selected_total'] == 74
    assert (launch['expected_tracked_count'], launch['expected_tracked_bytes']) == (11840, 183410043)
    expected = {r['path']: r['sha256'] for r in launch['files']}
    bundle = read(H4 / 'h4-native-bundle.json')
    assert set(bundle) == set(expected) and len(bundle) == 12
    assert constant(H4 / 'bootstrap_h4_native.py', 'EXPECTED') == expected
    for name, encoded in bundle.items():
        raw = base64.b64decode(encoded, validate=True)
        assert raw == (H4 / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected[name]
    assert request['host'] == launch['host'] == 'desktop'
    assert request['executable'] == launch['executable'] == '/usr/bin/python3'
    assert request['cwd'] == launch['cwd'] == '/home/qian-qi/work/hepta-pq-effect-v4-20261105-93bfcf'
    assert request['args'] == ['-c', (H4 / 'bootstrap_h4_native.py').read_text(), launch['source_commit'], launch['source_tree'], 'joint-h4-native-attempt-1']
    assert request['stdin'] == (H4 / 'h4-native-bundle.json').read_text()
    assert request['idempotency_key'] == launch['idempotency_key'] == 'ms-joint-h4-native-6db78-attempt1-93bfcf'
    assert request['env'] == {'PYTHONDONTWRITEBYTECODE': '1', 'GIT_NO_LAZY_FETCH': '1', 'GIT_TERMINAL_PROMPT': '0'}
    budget = read(H4 / 'h4-budget-map.json')
    old_budget = read(H3 / 'h3-budget-map.json')
    assert request['timeout_seconds'] == launch['outer_timeout_seconds'] == budget['outer_seconds'] == old_budget['outer_seconds'] == 5400
    assert budget['per_test_seconds'] == old_budget['per_test_seconds'] == 60
    assert budget['retries'] == old_budget['retries'] == 0
    assert budget['test_threads'] == old_budget['test_threads'] == 1
    added = [x for x in budget['gates'] if x['name'] == 'live-parent-correspondence-controls']
    assert len(added) == 1 and added[0]['timeout_seconds'] == 20 and added[0]['actual_product_credit'] is False
    assert [x for x in budget['gates'] if x not in added] == old_budget['gates']
    unchanged = {'nextest_fd_runner.py': 'nextest_fd_runner.py',
                 'fd_gate_evidence.py': 'fd_gate_evidence.py',
                 'test_nextest_fd_runner.py': 'test_nextest_fd_runner.py',
                 'test_fd_gate_targets.py': 'test_fd_gate_targets.py',
                 'h4-selected-tests-guard.py': 'h3-selected-tests-guard.py',
                 'h4-extra-controls.json': 'h3-extra-controls.json'}
    for now, prior in unchanged.items():
        assert (H4 / now).read_bytes() == (H3 / prior).read_bytes()
    full = read(H4 / 'h4-extra-controls.json')['full_evidence_library']
    assert full['minimum'] == 22 and full['expected_passed'] == len(full['expected_names']) == 161
    assert full['expected_ignored'] == ['authbus_outbox_tests::crash_delivery_child']
    cloud = read(CLOUD / 'receipt.json')
    for receipt in cloud:
        assert digest(Path(receipt['log']))['sha256'] == receipt['log_sha256']
    refused, synthetic = cloud
    assert refused['returncode'] == 1 and synthetic['returncode'] == 0
    refusal_log = Path(refused['log']).read_text()
    assert refusal_log.count('RuntimeError: collector requires the process and /proc to share a PID namespace') == 3
    assert refused['sources']['test_executed_binary_capture.py'] != expected['test_executed_binary_capture.py']
    for name in ['live_fd_correspondence.py', 'test_live_fd_correspondence.py', 'test_elf_capture.py', 'run_h4_native_pipeline.py']:
        assert synthetic['sources'][name] == expected[name]
    assert 'Ran 3 tests' in Path(synthetic['log']).read_text() and '\nOK\n' in Path(synthetic['log']).read_text()
    pq_manifest = read(PQ / 'delivery-manifest.json')
    assert digest(PQ / 'delivery-manifest.json')['sha256'] == '33a80221327d2514b3425240fff7cd71d69de57e2df71661d4b71ae0628ac009'
    assert pq_manifest['reviewed_package_manifest_sha256'] == digest(manifest_path)['sha256']
    for row in pq_manifest['files']:
        actual = digest(PQ / row['path'])
        assert (actual['bytes'], actual['sha256']) == (row['bytes'], row['sha256'])
        copy_exact(PQ / row['path'], OUT / 'independent-review' / row['path'])
    copy_exact(PQ / 'delivery-manifest.json', OUT / 'independent-review/delivery-manifest.json')
    for row in members:
        copy_exact(H4 / row['path'], OUT / 'frozen-package' / row['path'])
    copy_exact(manifest_path, OUT / 'frozen-package/frozen-package-manifest.json')
    for path in CLOUD.iterdir():
        if path.is_file():
            copy_exact(path, OUT / 'cloud-utility-controls' / path.name)
    report = {
        'schema': 'root-h4-frozen-execution-package-review-v1',
        'decision': 'Exact package accepted for one full original attempt after the separately verified H3 archive and index job release; this is not native pass credit.',
        'source_commit': launch['source_commit'], 'source_tree': launch['source_tree'],
        'chain_commit': launch['chain_commit'],
        'manifest': digest(manifest_path), 'request': digest(H4 / manifest['request']['path']),
        'bundle': digest(H4 / 'h4-native-bundle.json'),
        'exact_file_hashes_verified': 18, 'decoded_bundle_members': 12,
        'bootstrap_request_stdin_environment_bound': True,
        'original_steps_unchanged': 13, 'original_selected_outcomes': 74,
        'original_full_active': 161, 'original_full_ignored': full['expected_ignored'],
        'original_wrapper_minimum': 22, 'outer_seconds': 5400,
        'per_case_seconds': 60, 'retries': 0, 'test_threads': 1,
        'original_budgets_and_relative_order_unchanged': True,
        'only_added_gate': added[0],
        'unchanged_primary_files': unchanged,
        'synthetic_controls': {'cases': 3, 'returncode': 0, 'sources_equal_final': True, 'desktop_credit': False},
        'interim_proc_controls': {'cases': 3, 'errors': 3, 'namespace_guard_preserved': True, 'final_source_pending_desktop': True},
        'mechanism_review': [
            'The source review binds actual child and direct-parent executable FDs to two equal complete live observations and the exact wrapper chain.',
            'Only the one fixed FinalUse case can have one direct auxiliary child; full argv, parent PID/start, image metadata and digest, source and unique primary FD must match.',
            'Auxiliary observations add no outcome credit and cannot fill a missing primary FD. Original primary FD verifier remains byte-identical.',
            'Held-FD metadata is checked through retention; parent liveness is only asserted during the recorded two-sample interval.',
            'H3 remains failed. No retrospective parent assignment or source/native result transfer is permitted.'
        ],
        'independent_review': digest(PQ / 'review.json'),
        'native_launch_by_this_review': False,
        'remaining_prerequisites': ['Exact archive/index owned-job release verified separately', 'All desktop utility prerequisites and full native gates in this same attempt'],
        'learning_trial_created': False, 'repository_or_workflow_edited': False,
        'limits': ['Static package validation is not a native result.', 'Polling may miss short processes.', 'No hostile privileged-writer or full import-closure claim.'],
        'inputs': [digest(H4 / row['path']) for row in members]
    }
    target = OUT / 'root-review.json'
    target.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'result': 'PASS exact frozen package review', 'report': digest(target), 'copied_package_files': 19, 'native_launched': False}))


if __name__ == '__main__':
    main()
