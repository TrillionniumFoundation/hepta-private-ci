"""Reconcile original source gates and actual readonly record observations.

This reads local evidence only. It neither launches native work nor grants any
runtime authority. Large byte reconstruction is identified separately from
the native full-file observations and is never called a second transfer.
"""
import ast
import base64
import datetime
import gzip
import hashlib
import json
import re
import stat
from pathlib import Path

OUT = Path('/tmp/hepta-36fa-cc57-final-source-root-review-v1')
SRC = Path('/tmp/hepta-36fa-source-qualification-cc57-launch-v2')
OBS = Path('/tmp/hepta-36fa-cc57-source-inventory-readonly-capture-v1')
CLOSURE = Path('/tmp/hepta-36fa-cc57-closure-log-readonly-capture-v1')
CFG = Path('/tmp/hepta-36fa-cc57-admission-successor-v2/QUALIFICATION_INPUT.cc57-v2.HOLD.json')
PLAN = Path('/tmp/hepta-36fa-exact-source-qualification-plan-v2/PLAN.json')
ORIGIN = Path('/tmp/hepta-36fa-source-repair-canonical-packet-v1/CANONICAL_CLEAN_INVENTORY.expected.json')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def read(path):
    return json.loads(path.read_bytes())


def sdk(path):
    value = read(path)
    assert value['isError'] is False and len(value['content']) == 1
    assert value['content'][0]['type'] == 'text'
    return json.loads(value['content'][0]['text'])


def normal(path, job_id):
    value = sdk(path)
    assert value['job_id'] == job_id and value['state'] == 'succeeded' and value['exit_code'] == 0
    assert all(value[k] is False for k in ('timed_out', 'cancelled', 'automatic_retry'))
    assert all(value[k] is True for k in ('output_complete', 'output_durable', 'terminal_publication_confirmed'))
    assert not any(value['log_truncated'].values())
    return value


cfg, plan = read(CFG), read(PLAN)
head, tree = cfg['source'], cfg['tree']
assert head == 'cc57c7198db6293ccca562253c42fffbe2a04633'
assert tree == 'b7b357c07b5539769a068c6b9b009629f5612d1e'
terminal = normal(SRC / 'STATUS_05.original.json', '1a1d23c92f3-2564-1cb4')
assert terminal['log_bytes']['stdout'] == {'seen': 6169, 'stored': 6169}
assert terminal['log_bytes']['stderr'] == {'seen': 0, 'stored': 0}
assert len((SRC / 'STDOUT.complete.log').read_bytes()) == 6169
handoff, run = read(SRC / 'SOURCE_HANDOFF_RESULT.json'), read(SRC / 'ORIGINAL_RUN_RESULT.json')
assert handoff['source'] == run['source_sha'] == head
assert handoff['tree'] == run['source_tree'] == tree
assert handoff['status'] == handoff['original_run_status'] == run['status'] == 'passed'
assert handoff['driver_main_entered'] is True and handoff['driver_returncode'] == 0
assert handoff['qualification'] is False and run['actual_A_B_C_qualification'] is False
assert run['attempted'] == run['entrypoints_started'] == ['source-closure', 'self-test', 'verify']
assert run['not_run'] == []

obs_normal = normal(OBS / 'STATUS_01.original.json', '1a1d25d4534-2564-1cd2')
observed_sdk = sdk(OBS / 'STDOUT_READ_01.original.json')
assert observed_sdk['job_id'] == obs_normal['job_id']
stream = observed_sdk['stdout']
observed_raw = bytes.fromhex(stream['bytes_hex'])
assert observed_raw.decode() == stream['text']
assert stream['offset'] == 0 and stream['next_offset'] == stream['size'] == len(observed_raw) == 7518
assert stream['eof'] is True and observed_sdk['stderr']['size'] == 0
assert obs_normal['log_bytes']['stdout'] == {'seen': 7518, 'stored': 7518}
assert (OBS / 'STDOUT.complete.log').read_bytes() == observed_raw
observation = json.loads(observed_raw)
assert observation['source_job_id'] == terminal['job_id'] and observation['source_sha'] == head
assert observation['format'] == 'hepta-source-original-inventory-readonly-capture-v1'
assert all(observation[k] is False for k in ('qualification', 'record_or_source_writes', 'gate_or_cargo_commands_executed', 'full_original_contents_retransmitted'))
observer_plan = read(OBS / 'PLAN.HOLD.json')
assert len(observation['observations']) == len(observer_plan['items']) == 9
origin_raw = ORIGIN.read_bytes()
clone_raw = (OUT / 'CLONE_INVENTORY.expected_projection.json').read_bytes()
assert observation['origin_decoded_raw_identity'] == pin(origin_raw) == cfg['full_physical_inventory']
assert observation['clone_raw_identity'] == pin(clone_raw)
assert pin(origin_raw)['sha256'] != pin(clone_raw)['sha256'] != cfg['expected_inventory_sha256']
origin_gzip = gzip.compress(origin_raw, compresslevel=9, mtime=0)
clone_gzip = gzip.compress(clone_raw, compresslevel=9, mtime=0)
assert observation['clone_gzip_identity'] == pin(clone_gzip)
parts = [clone_gzip[i:i + 262144] for i in range(0, len(clone_gzip), 262144)]
assert observation['clone_original_retained_part_identities'] == [pin(p) for p in parts]
for row, expected in zip(observation['observations'], observer_plan['items']):
    assert row['path'] == expected['path'] and row['label'] == expected['label'] and row['kind'] == expected['kind']
    assert row['actual_identity'] == expected['expected']
    assert row['full_bounded_read'] is True
    info = row['stable_stat']
    assert stat.S_ISREG(info['mode']) and stat.S_IMODE(info['mode']) == expected['mode']
    assert info['uid'] == 1000 and info['nlink'] == 1 and info['size'] == expected['expected']['bytes']
    if row['kind'] == 'clone_raw':
        assert row['actual_identity'] == pin(clone_raw) and row['equal_first_clone_original'] is True
    else:
        assert row['actual_identity'] == pin(origin_gzip)
        assert row['decoded_raw_identity'] == pin(origin_raw) and row['equal_first_origin_gzip_original'] is True
assert len({r['stable_stat']['inode'] for r in observation['observations']}) == 9
origin, clone = json.loads(origin_raw), json.loads(clone_raw)
assert origin['source'] == clone['source'] == {'head': head, 'tree': tree, 'status': ''}
assert origin['tracked_entries'] == origin['filesystem_entries'] == clone['tracked_entries'] == clone['filesystem_entries'] == 15188
assert len(origin['files']) == len(clone['files']) == 15188
for before, frozen in zip(origin['files'], clone['files']):
    expected = dict(before)
    if expected['kind'] == 'file':
        expected['permissions'] = 0o500 if before['permissions'] & 0o111 else 0o400
    assert expected == frozen and before['matches_index'] is True and frozen['matches_index'] is True

stage_reviews = []
manifest_inventory_copies = 0
for gate in run['gates']:
    name = gate['gate']
    local = SRC / 'stage-originals' / name
    assert read(local / 'gate-final.json') == gate
    assert gate['status'] == 'passed' and gate['source_changed'] is False and gate['source_sha'] == head
    assert gate['lifecycle'] == {'attempted': True, 'entrypoint_started': True, 'package': 'completed', 'terminal_observed': True}
    assert all(gate[k] is None for k in ('execution_error', 'after_inventory_error', 'record_read_error'))
    assert gate['before_inventory_sha256'] == gate['after_inventory_sha256'] == pin(clone_raw)['sha256']
    receipt_raw = (local / (name + '.json')).read_bytes()
    receipt = json.loads(receipt_raw)
    assert gate['original_record'] == {'bytes': len(receipt_raw), 'path': name + '.json', 'sha256': pin(receipt_raw)['sha256']}
    assert gate['original_record_retained_unchanged'] is True
    assert receipt['returncode'] == 0 and receipt['source_sha'] == head
    assert receipt['timed_out'] is False and receipt['output_limit_exceeded'] is False
    raw_path = {'source-closure': CLOSURE / 'source-closure.original.log', 'self-test': local / 'self-test.log', 'verify': local / 'verify.original.log'}[name]
    raw = raw_path.read_bytes()
    assert receipt['log_bytes'] == len(raw) and receipt['log_sha256'] == pin(raw)['sha256']
    manifest_raw = (local / 'retained-manifest.json').read_bytes()
    pack = next(p for p in run['gate_packages'] if p['path'].endswith('/' + name + '/retained-manifest.json'))
    assert pack['bytes'] == len(manifest_raw) and pack['sha256'] == pin(manifest_raw)['sha256'] and pack['git_blob_sha'] == pin(manifest_raw)['git_blob']
    stage_reviews.append({'gate': name, 'status': gate['status'], 'elapsed_seconds': gate['elapsed_seconds'], 'receipt': pin(receipt_raw), 'raw': pin(raw), 'manifest': pin(manifest_raw)})
for manifest_path in [SRC / 'stage-originals/run-retained-manifest.json'] + [SRC / 'stage-originals' / n / 'retained-manifest.json' for n in run['attempted']]:
    for row in read(manifest_path)['files']:
        if row['original_path'].endswith('.inventory.json'):
            assert row['encoding'] == 'gzip' and row['original_bytes'] == len(clone_raw) and row['original_sha256'] == pin(clone_raw)['sha256']
            assert len(row['parts']) == len(parts) == 5
            for saved, part in zip(row['parts'], parts):
                p = pin(part)
                assert (saved['bytes'], saved['sha256'], saved['git_blob_sha']) == (p['bytes'], p['sha256'], p['git_blob'])
            manifest_inventory_copies += 1
assert manifest_inventory_copies == 7
closure_text = (CLOSURE / 'source-closure.original.log').read_text()
assert sum(bool(re.match(r'^test[^\n]+ \.\.\. ok$', line)) for line in closure_text.splitlines()) == 492
assert closure_text.endswith('Ran 492 tests in 384.885s\n\nOK\n')
assert 'PASS_HEPTA_CALLER_PROOF_SELF_TEST' in (SRC / 'stage-originals/self-test/self-test.log').read_text()
caller = read(SRC / 'stage-originals/verify/verify.original.log')
assert caller['status'] == 'PASS_HEPTA_CALLER_CLOSED_SET' and caller['authorityGranted'] is False
assert len(caller['boundaries']) == len(caller['privilegedInventory']) == 569
assert len(caller['protectedFiles']) == 422 and caller['rustFilesScanned'] == 6619

small = SRC / 'origin-and-clone-originals'
before_git, after_git = (small / 'GIT_STATE.before.json').read_bytes(), (small / 'GIT_STATE.after.json').read_bytes()
assert before_git == after_git
canonical = read(Path('/tmp/hepta-36fa-source-repair-canonical-alignment-launch-v1/RESULT.json'))
assert json.loads(before_git) == canonical['after']['git_state']
assert read(small / 'FULL_PHYSICAL_COMPARISON.json')['additional_physical_entries'] == []
assert all(read(small / 'FULL_PHYSICAL_COMPARISON.json')[k] is True for k in ('full_bytes_equal', 'original_rows_identical'))
assert handoff['actual_origin_full_physical_observation'] == {'extra_physical_entries': 0, 'full_physical_bytes_equal': True, 'original_source_rows_unchanged': True}
freeze = read(small / 'source-freeze.json')
assert freeze['source'] == clone['source'] and freeze['inventory_sha256'] == pin(clone_raw)['sha256'] and freeze['frozen_files'] == 15209
assert read(small / 'clone.json')['returncode'] == read(small / 'checkout.json')['returncode'] == 0
commands = read(small / 'READONLY_COMMANDS.json')
assert len(commands) == 13 and all(r['returncode'] == 0 and r['purpose'] == 'read-only preflight/evidence' for r in commands)

expected_inputs = {cfg['repo'] + '/' + x['path']: {k: x[k] for k in ('bytes', 'sha256', 'git_blob')} for x in plan['unchanged_original_controls']['reviewed_source_pins']['files']}
constants = {}
for node in ast.parse(Path('/tmp/hepta-36fa-cc57-admission-successor-v2/qualification-admission.cc57.HOLD.py').read_bytes()).body:
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
        try:
            constants[node.targets[0].id] = ast.literal_eval(node.value)
        except (ValueError, TypeError):
            pass
for path_key, value in [('maintenance_guard_path', constants['V5_PIN']), ('inventory_driver_path', constants['INVENTORY_PIN']), ('native_driver_path', cfg['native_driver_pin']), ('plan_path', cfg['plan_pin']), ('source_gates_config_path', cfg['source_gates_config_pin'])]:
    expected_inputs[cfg[path_key]] = value
for group in [cfg['final_format'], cfg['canonical_alignment'], cfg['runtime_guard']['runtime_restoration']]:
    for key in ('result', 'supervisor', 'environment'):
        if key in group:
            expected_inputs[group[key + '_path']] = group[key]
expected_inputs['/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/MAINTENANCE_STARTED.original.json'] = {'bytes': 1154, 'git_blob': '69a3d38ff1cf800813f1fbf1f30bca224157f223', 'sha256': 'f9372b818186526929ae25be698d108a4fee17d6612a18f36b8e950172c02ce1'}
assert len(expected_inputs) == 25 and read(small / 'INPUTS.final.json') == expected_inputs

result = {
    'format': 'hepta-root-complete-actual-source-review-v1',
    'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'status': 'SOURCE_GATES_PASSED_AND_ORIGINALS_REVIEWED',
    'source': head, 'tree': tree, 'source_job_id': terminal['job_id'],
    'source_normal': pin((SRC / 'STATUS_05.original.json').read_bytes()),
    'source_handoff': pin((SRC / 'SOURCE_HANDOFF_RESULT.json').read_bytes()),
    'original_run_result': pin((SRC / 'ORIGINAL_RUN_RESULT.json').read_bytes()),
    'gates': stage_reviews, 'source_closure_explicit_passed_methods': 492,
    'source_closure_failed_methods': 0, 'caller_boundaries': 569,
    'protected_rows': 422, 'rust_files_scanned': 6619,
    'caller_authority_granted': False,
    'inventory_observer_job': obs_normal['job_id'],
    'inventory_observer_normal': pin((OBS / 'STATUS_01.original.json').read_bytes()),
    'inventory_observer_original_stdout': pin(observed_raw),
    'separately_full_read_original_clone_records': 7,
    'separately_full_read_original_origin_gzip_records': 2,
    'clone_inventory': pin(clone_raw), 'origin_inventory': pin(origin_raw),
    'original_retained_inventory_parts_verified': 35,
    'complete_inventory_file_rows_each': 15188,
    'raw_inventory_transfer_scope': 'Full original files were read on native host with stable-stat and complete byte identities. Full material is exactly reconstructed from already obtained canonical bytes plus original freeze semantics; all original gzip and part identities match. Large full contents were not retransmitted. This is not a second native run.',
    'origin_git_before_after_and_canonical_equal': True,
    'all_25_original_input_pins_match': True,
    'all_13_original_readonly_commands_returned_zero': True,
    'extra_origin_physical_entries': 0,
    'original_source_budgets_seconds': {'source-closure': 600, 'self-test': 300, 'verify': 4800, 'outer': 7200},
    'source_gate_reexecution_for_recovery': False,
    'native_main_approved_by_this_report': False,
    'native_qualification_completed': False,
    'real_qualified_task_chain_outcomes': 0,
    'prior_failed_or_unknown_attempts_preserved': True,
}
(OUT / 'ROOT_COMPLETE_SOURCE_REVIEW.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
print(json.dumps({'status': result['status'], 'source_job_id': terminal['job_id'], 'observer_job_id': obs_normal['job_id'], 'gate_count': len(stage_reviews), 'input_count': 25, 'inventory_copies': 9, 'result_pin': pin((OUT / 'ROOT_COMPLETE_SOURCE_REVIEW.json').read_bytes())}))
