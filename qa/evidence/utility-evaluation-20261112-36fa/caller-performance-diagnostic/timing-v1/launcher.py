#!/usr/bin/env python3
"""Durable bounded launcher for a separate, non-qualification diagnostic."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import traceback


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    with path.open('xb') as stream:
        stream.write((json.dumps(value, indent=2, sort_keys=True) + '\n').encode())
        stream.flush()
        os.fsync(stream.fileno())


def main():
    config_path = Path(sys.argv[1])
    config_bytes = config_path.read_bytes()
    cfg = json.loads(config_bytes)
    if cfg['state'] != 'READY_FOR_SINGLE_TIMING_DIAGNOSTIC':
        raise RuntimeError('still prepared; actual original-job terminal admission required')
    if cfg['hard_timeout_seconds'] != 240 or cfg['internal_stop_seconds'] != 220:
        raise RuntimeError('diagnostic timeout contract differs')
    if set(cfg['prior_terminal_files']) != {'verify/execution-terminal.json', 'run-result.json'} or cfg['prior_job_state_observed'] not in ('completed', 'failed', 'cancelled'):
        raise RuntimeError('actual prior job terminal observation is absent')
    if digest(Path(__file__).read_bytes()) != cfg['launcher_sha256']:
        raise RuntimeError('launcher identity differs')
    worker = Path(cfg['worker_path'])
    if digest(worker.read_bytes()) != cfg['worker_sha256']:
        raise RuntimeError('worker identity differs')
    source = Path(cfg['source_checkout'])
    records = Path(cfg['records'])
    if records.resolve().is_relative_to(source.resolve()):
        raise RuntimeError('records are not outside the source')
    records.mkdir(parents=True, exist_ok=False)
    save(records / 'INPUT.json', cfg)
    save(records / 'launcher-start.json', {'status': 'started', 'run_identity': cfg['run_identity'],
         'input_sha256': digest(config_bytes), 'full_gate_run': False})
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.environ['GIT_OPTIONAL_LOCKS'] = '0'
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(source / 'scripts'))
    command = [sys.executable, '-B', str(worker), str(config_path)]
    original = None
    error = None
    try:
        runner_path = source / 'scripts/hepta_ci_exec.py'
        if digest(runner_path.read_bytes()) != cfg['original_input_sha256']['scripts/hepta_ci_exec.py']:
            raise RuntimeError('original execute_logged source differs')
        spec = importlib.util.spec_from_file_location('original_c0f_ci_exec_for_timing', runner_path)
        runner = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = runner
        spec.loader.exec_module(runner)
        os.chdir(source)
        original = runner.execute_logged(command, records / 'diagnostic.log', timeout_seconds=240)
        save(records / 'original-execute-logged.json', {'command': command, **original})
    except BaseException as exc:
        error = {'type': type(exc).__name__, 'message': str(exc), 'traceback': traceback.format_exc()}
        save(records / 'launcher-error.json', error)
    result = None
    if (records / 'diagnostic-result.json').is_file():
        result = json.loads((records / 'diagnostic-result.json').read_bytes())
    save(records / 'launcher-final.json', {'status': 'finished_scoped_timing_diagnostic' if error is None and result is not None else 'unknown_scoped_timing_diagnostic',
         'original_execution': original, 'launcher_error': error, 'worker_result': result,
         'full_gate_run': False, 'original_source_gate_result_inherited': False})
    if error is not None or result is None or original is None or original.get('timed_out') or original.get('output_limit_exceeded'):
        return 1
    return original['returncode']


if __name__ == '__main__':
    raise SystemExit(main())
