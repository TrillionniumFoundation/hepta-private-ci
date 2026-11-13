"""HOLD handoff to the exact original 5118 source-gates main; no gate logic changes."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import signal
import sys
import types

sys.dont_write_bytecode = True
if INPUT.get('state') != 'READY_FOR_FINAL_SOURCE_QUALIFICATION' or INPUT.get('root_execution_approved') is not True:
    raise RuntimeError('final-source qualification input remains HOLD')
out = Path(INPUT['source_gates_handoff_records'])
if not out.is_absolute() or out.is_relative_to(Path(INPUT['repo'])) or Path(INPUT['repo']).is_relative_to(out):
    raise RuntimeError('fresh external source-gate admission records required')
out.mkdir(parents=True, exist_ok=False)
result = {'format': 'hepta-final-source-gates-handoff-v1', 'status': 'unknown',
          'source': INPUT['source'], 'tree': INPUT['tree'], 'qualification': False,
          'driver_main_entered': False, 'driver_returncode': None,
          'started_at': datetime.now(timezone.utc).isoformat()}
guard = None


def save(name, value):
    raw = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
    with (out / name).open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


try:
    path = Path(INPUT['admission_path'])
    raw = path.read_bytes()
    observed = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}
    if observed != INPUT['admission_pin']:
        raise RuntimeError('exact shared admission module differs')
    module = types.ModuleType('final_source_gates_admission')
    module.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    guard = module.Admission(INPUT, out / 'admission', True)
    signal.signal(signal.SIGALRM, guard.m.alarm_handler)
    guard.m.set_alarm(600)
    try:
        guard.acquire_and_validate()
        config_path = Path(INPUT['source_gates_config_path'])
        config_raw = guard.m.read_input(config_path, INPUT['source_gates_config_pin'])
        cfg = guard.m.parse(config_raw)
        module.check(cfg['schema'] == 'hepta.utility.desktop-source-gates.v1'
                     and cfg['state'] == 'READY_FOR_EXACT_SOURCE_RUN'
                     and cfg['source_sha'] == INPUT['source'] and cfg['source_tree'] == INPUT['tree']
                     and cfg['object_repository'] == INPUT['repo']
                     and cfg['driver_sha256'] == module.INVENTORY_PIN['sha256']
                     and cfg['hepta_ci_exec_sha256'] == '9b2bfaa563fff018df4e4f10944f6fbc63d307fa4c4a7e167c392288edb5a5c1'
                     and cfg['budgets_seconds'] == {'source-closure': 600, 'self-test': 300, 'verify': 4800},
                     'unaltered original exact-source gate inputs')
        guard.m.write('SOURCE_GATES_INPUT.original.json', config_raw)
        guard.before_native_stage('source-gates')
    finally:
        signal.alarm(0)
    # The original main exclusively owns clone creation, freeze, complete source
    # inventories, all three gates, their original recorders and failure policy.
    os.environ['CODEX_REPO_ROOT'] = cfg['source_checkout']
    save('EXECUTION_START.json', {'at': datetime.now(timezone.utc).isoformat(),
         'driver': module.INVENTORY_PIN, 'config': INPUT['source_gates_config_pin'],
         'original_argv': ['python3', INPUT['inventory_driver_path'], '--config', str(config_path)]})
    result['driver_main_entered'] = True
    previous_argv = sys.argv
    try:
        sys.argv = [INPUT['inventory_driver_path'], '--config', str(config_path)]
        result['driver_returncode'] = guard.inventory.main()
    finally:
        sys.argv = previous_argv
    original = Path(cfg['records']) / 'run-result.json'
    original_raw = original.read_bytes()
    payload = json.loads(original_raw)
    with (out / 'ORIGINAL_RUN_RESULT.json').open('xb') as stream:
        stream.write(original_raw); stream.flush(); os.fsync(stream.fileno())
    result['original_run_status'] = payload['status']
    result['original_records'] = cfg['records']
    if payload['status'] == 'passed':
        if result['driver_returncode'] == 0:
            result['status'] = 'passed'
        else:
            result['status'] = 'unknown' if result['driver_returncode'] is None else 'failed'
            result['inconsistent_original_terminal'] = {
                'driver_returncode': result['driver_returncode'], 'original_run_status': payload['status']}
    else:
        result['status'] = payload['status']
except BaseException as error:
    result['error'] = type(error).__name__ + ': ' + str(error)
    if result.get('driver_returncode') not in (None, 0):
        result['status'] = 'failed'
finally:
    signal.alarm(0)
    if guard is not None:
        try:
            signal.signal(signal.SIGALRM, guard.m.alarm_handler); guard.m.set_alarm(300)
            result['actual_origin_full_physical_observation'] = guard.finish()
        except BaseException as error:
            result['final_evidence_error'] = type(error).__name__ + ': ' + str(error)
            if isinstance(error, module.SourceChanged):
                result['status'] = 'failed'
            elif result['status'] == 'passed':
                result['status'] = 'unknown'
        finally:
            signal.alarm(0); guard.close()
    result['finished_at'] = datetime.now(timezone.utc).isoformat()
    save('RESULT.json', result)
    print(json.dumps(result, sort_keys=True), flush=True)
raise SystemExit(0 if result['status'] == 'passed' else 1)
