#!/usr/bin/env python3
"""Pure offline exact successor controls; never invokes a native entry point."""
import ast
import base64
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-coordinator-a489-maintenance-successor-v1')
OLD = Path('/tmp/hepta-36fa-provider-0c59-maintenance-successor-v1/execution-candidate-v1')
RUN = Path('/tmp/hepta-36fa-coordinator-a489-materializer-runtime-v1')
OUT = ROOT / 'execution-candidate-v1'
OLD_CONTROL = '/home/qian-qi/hepta-utility-36fa-evidence/provider-0c59-maintenance-v1'
CONTROL = '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1'
OLD_SOURCE = '/home/qian-qi/hepta-utility-36fa-provider-0c59-isolated-v1'
SOURCE = '/home/qian-qi/hepta-utility-36fa-provider-coordinator-a489-isolated-v1'
STAGE_KEY = 'hepta-utility-36fa-provider-coordinator-a489-maintenance-control-staging-v1'
MAIN_KEY = 'hepta-utility-36fa-provider-coordinator-a489-maintenance-v1'


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def checked(path, object_id):
    raw = path.read_bytes()
    assert pin(raw)['git_blob'] == object_id, (str(path), pin(raw))
    return raw


def jbytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()


def save(name, raw):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)
    assert path.read_bytes() == raw
    return {'name': name, **pin(raw)}


def literal_assignment(raw, name):
    tree = ast.parse(raw)
    hits = [node for node in tree.body if isinstance(node, ast.Assign)
            and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name]
    assert len(hits) == 1
    return ast.literal_eval(hits[0].value)


def line(raw, prefix):
    hits = [value for value in raw.splitlines(keepends=True) if value.startswith(prefix)]
    assert len(hits) == 1
    return hits[0]


def replace_exact(raw, before, after, changes):
    assert raw.count(before) == 1, before[:100]
    changes.append({'before': before.decode(), 'after': after.decode()})
    return raw.replace(before, after, 1)


def inverse(raw, changes):
    for item in reversed(changes):
        before, after = item['before'].encode(), item['after'].encode()
        assert raw.count(after) == 1
        raw = raw.replace(after, before, 1)
    return raw


def definitions(raw):
    text = raw.decode()
    return {node.name: ast.get_source_segment(text, node)
            for node in ast.parse(text).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}


def diff(before, after, before_name, after_name):
    return ''.join(difflib.unified_diff(before.decode().splitlines(True),
                                      after.decode().splitlines(True),
                                      fromfile=before_name, tofile=after_name)).encode()


def main():
    assert not OUT.exists(), 'Frozen candidate directory already exists; no overwrite'
    hold_raw = checked(ROOT / 'WAITING_CONFIG.ACTUAL_MATERIALIZATION.json',
                       'eb322791ff64a67389b4e37b341bc01c63f3d5cb')
    driver = checked(ROOT / 'driver-maintenance.HOLD.py',
                     '59461030d4160f7ad6a978df5a7b6aaeb33fb2a6')
    normal = checked(RUN / 'STATUS_04.original.json',
                     '2a11b4b9e2baa380c247b6a728f90edfbcdcd644')
    old_cfg_raw = checked(OLD / 'MAINTENANCE_CONFIG.execution-candidate.json',
                          'd27dd8ee763c75eb5a0f195bb034fc9ca32b727e')
    old_launcher = checked(OLD / 'LAUNCHER.execution-candidate.py',
                           '92be49535aed7505c81f9c18782e668406b2b186')
    old_bootstrap = checked(OLD / 'STAGING_BOOTSTRAP.execution-candidate.py',
                            'e0c52b055ffea90817c4dc8a6c16f1c0d64d3332')
    old_payload_raw = checked(OLD / 'STAGING_PAYLOAD.execution-candidate.json',
                              'ad31acb90619438625b877b51a6c6ce680ccd25a')
    old_stage_raw = checked(OLD / 'STAGING_REQUEST.execution-candidate.json',
                            'dd593f5d41f7ecc46072f2fe60eb1047579588a2')
    old_main_raw = checked(OLD / 'PROCESS_INPUT.execution-candidate.json',
                           'c6a5a907647a97204878b5b5371eab540b778403')
    hold = json.loads(hold_raw)
    assert hold['status'] == 'HOLD_ACTUAL_MATERIALIZATION_AND_ROOT_EXACT_REVIEW_REQUIRED'
    assert hold['root_execution_approved'] is False
    cfg = json.loads(hold_raw)
    cfg['status'] = 'ROOT_APPROVED_TO_EXECUTE'
    cfg['root_execution_approved'] = True
    cfg_raw = jbytes(cfg)
    reverted = json.loads(cfg_raw)
    reverted['status'] = hold['status']
    reverted['root_execution_approved'] = hold['root_execution_approved']
    assert jbytes(reverted) == hold_raw
    changes = [key for key in hold if hold[key] != cfg[key]]
    assert changes == ['status', 'root_execution_approved']
    assert cfg['formal_approved_config_created'] is False
    assert cfg['source_repo'] == SOURCE
    assert cfg['materialization']['supervisor_path'] == CONTROL + '/MATERIALIZATION_SUPERVISOR.original.json'
    assert cfg['archive_restoration']['supervisor_path'] == CONTROL + '/V8_RESTORATION_SUPERVISOR.original.json'

    old_payload = json.loads(old_payload_raw)
    assert set(old_payload) == {'format', 'files'}
    assert old_payload['format'] == 'hepta-original-maintenance-control-staging-v1'
    old_pins = literal_assignment(old_bootstrap, 'PINS')
    original_files = {name: base64.b64decode(value, validate=True)
                      for name, value in old_payload['files'].items()}
    assert len(original_files) == 6 and set(original_files) == set(old_pins)
    assert all(pin(body) == old_pins[name] for name, body in original_files.items())
    assert original_files['APPROVED_MAINTENANCE_CONFIG.json'] == old_cfg_raw
    files = dict(original_files)
    files['driver-maintenance.py'] = driver
    files['APPROVED_MAINTENANCE_CONFIG.json'] = cfg_raw
    files['MATERIALIZATION_SUPERVISOR.original.json'] = normal
    pins = {name: pin(body) for name, body in files.items()}
    assert pins['MATERIALIZATION_SUPERVISOR.original.json'] == cfg['materialization']['supervisor']
    assert pins['V8_RESTORATION_SUPERVISOR.original.json'] == cfg['archive_restoration']['supervisor']
    unchanged_inputs = [name for name in files if files[name] == original_files[name]]
    assert unchanged_inputs == ['inventory-driver.original.py', 'MAINTENANCE_STARTED.original.json',
                                'V8_RESTORATION_SUPERVISOR.original.json']

    bootstrap_changes = []
    bootstrap = replace_exact(old_bootstrap, line(old_bootstrap, b'BASE = '),
                              ('BASE = pathlib.Path(' + repr(CONTROL) + ')\n').encode(),
                              bootstrap_changes)
    bootstrap = replace_exact(bootstrap, line(old_bootstrap, b'PINS = '),
                              ('PINS = ' + repr(pins) + '\n').encode(), bootstrap_changes)
    assert inverse(bootstrap, bootstrap_changes) == old_bootstrap
    assert definitions(bootstrap) == definitions(old_bootstrap)
    assert len(definitions(bootstrap)) == 4
    assert b'os.exec' not in bootstrap and b'fcntl.flock' not in bootstrap
    ast.parse(bootstrap)
    compile(bootstrap, str(OUT / 'STAGING_BOOTSTRAP.execution-candidate.py'), 'exec')

    launcher_changes = []
    launcher = replace_exact(old_launcher, line(old_launcher, b'ROOT='),
                             ('ROOT=Path(' + json.dumps(CONTROL) + ')\n').encode(), launcher_changes)
    launcher_pins = {name: (pins[name]['bytes'], pins[name]['sha256'], pins[name]['git_blob'])
                     for name in ['driver-maintenance.py', 'APPROVED_MAINTENANCE_CONFIG.json']}
    launcher = replace_exact(launcher, line(old_launcher, b'PINS='),
                             ('PINS=' + repr(launcher_pins) + '\n').encode(), launcher_changes)
    launcher = replace_exact(launcher, OLD_SOURCE.encode(), SOURCE.encode(), launcher_changes)
    launcher = replace_exact(launcher, b'fixed_original_maintenance_0c59_launcher_verified',
                             b'fixed_original_maintenance_coordinator_a489_launcher_verified',
                             launcher_changes)
    assert inverse(launcher, launcher_changes) == old_launcher
    assert definitions(launcher) == definitions(old_launcher)
    assert len(definitions(launcher)) == 5
    assert launcher.count(b'fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)') == 1
    assert b'flock(' not in driver
    assert b'os.set_inheritable(lock_fd,True)' in launcher
    ast.parse(launcher)
    compile(launcher, str(OUT / 'LAUNCHER.execution-candidate.py'), 'exec')
    payload = {'format': old_payload['format'],
               'files': {name: base64.b64encode(body).decode() for name, body in files.items()}}
    payload_raw = jbytes(payload)

    stage_request = json.loads(old_stage_raw)
    assert list(stage_request) == ['host', 'executable', 'args', 'cwd', 'timeout_seconds', 'idempotency_key', 'stdin']
    stage_request['args'] = ['-B', '-c', bootstrap.decode()]
    stage_request['idempotency_key'] = STAGE_KEY
    stage_request['stdin'] = payload_raw.decode()
    stage_raw = jbytes(stage_request)
    main_request = json.loads(old_main_raw)
    assert list(main_request) == ['host', 'executable', 'args', 'cwd', 'idempotency_key', 'timeout_seconds']
    main_request['args'] = ['-B', '-c', launcher.decode()]
    main_request['idempotency_key'] = MAIN_KEY
    main_raw = jbytes(main_request)
    assert stage_request['timeout_seconds'] == 900 and main_request['timeout_seconds'] == 9300
    assert all(value['host'] == 'desktop' and value['executable'] == '/usr/bin/python3'
               and value['cwd'] == '/home/qian-qi' and 'env' not in value
               for value in [stage_request, main_request])
    assert len(stage_raw) < 1048576 and len(payload_raw) < 1048576
    reverted_stage = json.loads(stage_raw)
    original_stage = json.loads(old_stage_raw)
    for key in ['args', 'idempotency_key', 'stdin']:
        reverted_stage[key] = original_stage[key]
    assert jbytes(reverted_stage) == old_stage_raw
    reverted_main = json.loads(main_raw)
    original_main = json.loads(old_main_raw)
    for key in ['args', 'idempotency_key']:
        reverted_main[key] = original_main[key]
    assert jbytes(reverted_main) == old_main_raw

    OUT.mkdir()
    rows = []
    for name, body in files.items():
        rows.append(save('staged-files/' + name, body))
    bodies = {
        'MAINTENANCE_CONFIG.execution-candidate.json': cfg_raw,
        'LAUNCHER.execution-candidate.py': launcher,
        'PROCESS_INPUT.execution-candidate.json': main_raw,
        'STAGING_BOOTSTRAP.execution-candidate.py': bootstrap,
        'STAGING_PAYLOAD.execution-candidate.json': payload_raw,
        'STAGING_REQUEST.execution-candidate.json': stage_raw,
        'CONFIG_HOLD_TO_CANDIDATE.diff': diff(hold_raw, cfg_raw, 'WAITING_CONFIG.ACTUAL_MATERIALIZATION.json', 'MAINTENANCE_CONFIG.execution-candidate.json'),
        'LAUNCHER_FROM_92BE.diff': diff(old_launcher, launcher, 'original_92be4953_launcher.py', 'LAUNCHER.execution-candidate.py'),
        'STAGING_BOOTSTRAP_FROM_E0C5.diff': diff(old_bootstrap, bootstrap, 'original_e0c52b05_staging.py', 'STAGING_BOOTSTRAP.execution-candidate.py'),
    }
    rows += [save(name, body) for name, body in bodies.items()]
    review = {
        'format': 'hepta-coordinator-a489-exact-maintenance-candidate-review-v1',
        'status': 'PREPARED_PENDING_ROOT_EXACT_ENGINEERING_APPROVAL',
        'scope': 'Pure offline construction and byte/AST verification; no H call or native preflight/main invocation.',
        'approval_fields_are_candidate_bytes_only': True,
        'config_changed_keys': changes,
        'config_two_field_inverse_full_bytes_equal': True,
        'unchanged_formal_approved_config_created': False,
        'historical_HOLD_explanation_unchanged': True,
        'actual_materialization_job': cfg['materialization']['job_id'],
        'actual_materialization_result': cfg['materialization']['result'],
        'actual_materialization_supervisor': cfg['materialization']['supervisor'],
        'source_repo': SOURCE, 'control': CONTROL,
        'six_input_pins': pins, 'three_unchanged_input_names': unchanged_inputs,
        'bootstrap_exact_replacements': bootstrap_changes,
        'bootstrap_inverse_full_bytes_equal': True,
        'bootstrap_four_helpers_byte_equal': True,
        'bootstrap_has_no_exec_or_flock': True,
        'launcher_exact_replacements': launcher_changes,
        'launcher_inverse_full_bytes_equal': True,
        'launcher_five_helpers_byte_equal': True,
        'single_lock': 'Only the original EX launcher opens and holds the actual shared lock across exec. Driver contains no flock; stage holds no lock.',
        'stage_typed': {'keys': list(stage_request), 'idempotency_key': STAGE_KEY,
                        'timeout_seconds': 900, 'request': pin(stage_raw), 'stdin': pin(payload_raw),
                        'no_environment_override': True, 'inverse_original_full_bytes_equal': True},
        'main_typed': {'keys': list(main_request), 'idempotency_key': MAIN_KEY,
                       'timeout_seconds': 9300, 'request': pin(main_raw),
                       'no_environment_override': True, 'no_stdin': True,
                       'inverse_original_full_bytes_equal': True},
        'ordered_execution_condition': 'No H dispatch before Root exact approval. If authorized: unique create-only stage; same-job normal exit 0 and complete original staging record plus six input files and bootstrap/argv/payload readback; only then unique original EX main. Unknown results reconcile the original key/job and do not advance. Failures preserve all partial records.',
        'original_budget_seconds': {'preflight': 600, 'fix': 7200, 'fmt': 900, 'records': 300, 'main_outer': 9300, 'stage_outer': 900},
        'fix_argv': cfg['fix_argv'], 'fmt_argv': cfg['fmt_argv'],
        'target_creation': False, 'minimum_target_free_bytes': cfg['minimum_target_free_bytes'],
        'H_calls': 0, 'maintenance_dispatch_authorized': False,
        'tests_authorized': False, 'ref_updates_authorized': False,
        'historical_0c59_fix101_retained': True,
    }
    rows.append(save('EXACT_CANDIDATE_REVIEW.json', jbytes(review)))
    rows.append(save('PREPARATION_SCRIPT.py', Path(__file__).read_bytes()))
    index = {'format': 'hepta-exact-maintenance-candidate-file-index-v1',
             'status': review['status'], 'files': rows,
             'no_native_calls': True, 'not_an_execution_approval': True}
    index_row = save('FILE_INDEX.json', jbytes(index))
    print(json.dumps({'directory': str(OUT), 'files': rows + [index_row]}, indent=2))


if __name__ == '__main__':
    main()
