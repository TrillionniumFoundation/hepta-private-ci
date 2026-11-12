#!/usr/bin/env python3
"""One bounded timing diagnostic over the exact original c0f verifier.

This worker does not qualify a source head. Original functions are delegated to
with unchanged arguments, return values and exceptions. Timings are inclusive.
"""
import functools
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import time
import traceback


class DiagnosticWindowEnded(BaseException):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    raw = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())


def load_module(name, path, expected_sha256):
    if sha256(path.read_bytes()) != expected_sha256:
        raise RuntimeError('exact input digest differs: ' + str(path))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def event(kind, **values):
    print(json.dumps({'event': kind, **values}, sort_keys=True), flush=True)


def main():
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    cfg_raw = Path(sys.argv[1]).read_bytes()
    cfg = json.loads(cfg_raw)
    if cfg['state'] != 'READY_FOR_SINGLE_TIMING_DIAGNOSTIC':
        raise RuntimeError('timing diagnostic is not admitted')
    if cfg['hard_timeout_seconds'] != 240 or cfg['internal_stop_seconds'] != 220:
        raise RuntimeError('original approved diagnostic budgets differ')
    if set(cfg['prior_terminal_files']) != {'verify/execution-terminal.json', 'run-result.json'}:
        raise RuntimeError('both exact prior terminal records are required')
    records = Path(cfg['records'])
    if not records.is_dir():
        raise RuntimeError('outer driver must create the isolated records directory')
    source = Path(cfg['source_checkout'])
    if source.resolve() == records.resolve() or records.resolve().is_relative_to(source.resolve()):
        raise RuntimeError('diagnostic records must remain outside the source')
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.environ['GIT_OPTIONAL_LOCKS'] = '0'
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(source / 'scripts'))
    driver = load_module('frozen_source_inventory_driver', Path(cfg['inventory_driver_path']), cfg['inventory_driver_sha256'])
    before = after = None
    before_error = after_error = None
    phase = 'preparing'
    status = 'unknown_scoped_timing_diagnostic'
    original_exception = None
    original_result = None
    verify_started = verify_finished = None
    verify_cpu_started = verify_cpu_finished = None
    measured = {}
    boundaries = []
    input_index = None
    originals = []

    def stop(_signum, _frame):
        raise DiagnosticWindowEnded('220-second internal diagnostic window ended')

    def measured_function(container, name, label, boundary=False):
        original = getattr(container, name)
        metric = {'calls': 0, 'completed_calls': 0, 'wall_seconds_inclusive': 0.0,
                  'cpu_seconds_inclusive': 0.0, 'exception_counts': {}}
        measured[label] = metric

        @functools.wraps(original)
        def invoke(*args, **kwargs):
            nonlocal input_index
            identifier = None
            if boundary:
                identifier = args[1].identifier
                if input_index is None:
                    # Observe the original completed collector's index only.
                    # Never replace, filter, cache or mutate that index.
                    paths = sorted(args[2])
                    input_index = {'rust_source_count': len(paths),
                                   'source_path_list_sha256': sha256(('\n'.join(paths) + '\n').encode())}
                    write_json(records / 'original-source-index-paths.json', paths)
                    event('original_collector_completed', **input_index)
            metric['calls'] += 1
            wall = time.perf_counter()
            cpu = time.process_time()
            error_type = None
            completed = False
            try:
                result = original(*args, **kwargs)
                completed = True
                return result
            except BaseException as error:
                error_type = type(error).__name__
                metric['exception_counts'][error_type] = metric['exception_counts'].get(error_type, 0) + 1
                raise
            finally:
                elapsed_wall = time.perf_counter() - wall
                elapsed_cpu = time.process_time() - cpu
                metric['wall_seconds_inclusive'] += elapsed_wall
                metric['cpu_seconds_inclusive'] += elapsed_cpu
                metric['completed_calls'] += int(completed)
                if boundary:
                    row = {'position': len(boundaries), 'identifier': identifier,
                           'original_call_returned': completed, 'exception_type': error_type,
                           'wall_seconds_inclusive': elapsed_wall, 'cpu_seconds_inclusive': elapsed_cpu}
                    boundaries.append(row)
                    event('original_boundary_timing', **row)

        originals.append((container, name, original))
        setattr(container, name, invoke)

    signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, max(0.001, 220 - (time.perf_counter() - started_wall)))
    write_json(records / 'worker-start.json', {'status': 'started_scoped_timing_diagnostic',
               'input_sha256': sha256(cfg_raw), 'source_sha': cfg['source_sha'],
               'source_tree': cfg['source_tree'], 'internal_stop_seconds': 220,
               'full_gate_run': False})
    event('timing_diagnostic_started', source_sha=cfg['source_sha'], internal_stop_seconds=220)
    try:
        prior = Path(cfg['prior_gate_records'])
        for filename, expected in cfg['prior_terminal_files'].items():
            if sha256((prior / filename).read_bytes()) != expected:
                raise RuntimeError('actual prior terminal record differs: ' + filename)
        terminal = json.loads((prior / 'verify/execution-terminal.json').read_bytes())
        if not terminal.get('terminal', {}).get('known_terminal'):
            raise RuntimeError('original verify has no known terminal record')
        prior_run = json.loads((prior / 'run-result.json').read_bytes())
        if prior_run.get('status') not in ('passed', 'failed', 'unknown', 'rejected'):
            raise RuntimeError('original source-gates run has no final status')
        before = driver.inventory(source)
        driver.put(records / 'source-before.inventory.json', before)
        driver.require_inventory(before, cfg)
        if len(before) != cfg['expected_inventory_bytes'] or sha256(before) != cfg['expected_inventory_sha256']:
            raise RuntimeError('exact complete c0f source inventory differs')
        for path, expected in cfg['original_input_sha256'].items():
            if sha256((source / path).read_bytes()) != expected:
                raise RuntimeError('original verifier input differs: ' + path)
        phase = 'original_verify'
        proof = load_module('original_c0f_timing_verifier', source / 'scripts/verify_hepta_callers.py', cfg['original_input_sha256']['scripts/verify_hepta_callers.py'])
        helper_path = Path(proof.typed_callers.__file__).resolve()
        if helper_path != (source / 'scripts/hepta_typed_callers.py').resolve():
            raise RuntimeError('typed helper import came from another source')
        measured_function(proof.typed_callers, '_declared_aliases', '_declared_aliases')
        measured_function(proof.typed_callers, 'has_authority_call', 'has_authority_call')
        measured_function(proof, '_verify_boundary', '_verify_boundary', boundary=True)
        verify_started = time.perf_counter()
        verify_cpu_started = time.process_time()
        # Call the unchanged original verify implementation, including its own
        # full collector, source stripping, field index and strict membership.
        original_result = proof.verify(source, source / 'CALLERS.toml')
        status = 'completed_scoped_timing_diagnostic'
    except DiagnosticWindowEnded as error:
        status = 'stopped_scoped_timing_diagnostic'
        original_exception = {'type': type(error).__name__, 'message': str(error),
                              'phase': phase, 'traceback': traceback.format_exc()}
    except BaseException as error:
        original_exception = {'type': type(error).__name__, 'message': str(error),
                              'phase': phase, 'traceback': traceback.format_exc()}
        status = 'failed_original_verification_during_diagnostic' if type(error).__name__ == 'VerificationFailure' else 'unknown_scoped_timing_diagnostic'
        if before is None:
            before_error = original_exception
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        if verify_started is not None:
            verify_finished, verify_cpu_finished = time.perf_counter(), time.process_time()
        for container, name, original in reversed(originals):
            setattr(container, name, original)
        metrics = {'status': status, 'phase': phase, 'source_sha': cfg['source_sha'],
                   'input_index': input_index, 'metrics': measured, 'boundaries': boundaries,
                   'original_exception': original_exception,
                   'original_verify_returned': original_result is not None,
                   'original_verify_result': original_result,
                   'verify_call_wall_seconds': None if verify_started is None else verify_finished - verify_started,
                   'verify_call_cpu_seconds': None if verify_cpu_started is None else verify_cpu_finished - verify_cpu_started,
                   'worker_wall_seconds_before_after_inventory': time.perf_counter() - started_wall,
                   'worker_cpu_seconds_before_after_inventory': time.process_time() - started_cpu,
                   'timing_semantics': 'All wrapped timings are inclusive. Nested measurements overlap and must not be summed into a total or percentage.',
                   'full_gate_run': False, 'source_collection_reduced': False,
                   'boundary_set_reduced': False, 'verdict_cache_added': False}
        # Preserve actual measurements before the potentially slower final
        # full inventory. Outer hard timeout must not erase these records.
        write_json(records / 'timing-metrics.json', metrics)
        try:
            after = driver.inventory(source)
            driver.put(records / 'source-after.inventory.json', after)
            driver.require_inventory(after, cfg)
            if sha256(after) != cfg['expected_inventory_sha256']:
                raise RuntimeError('exact source differs after diagnostic')
        except BaseException as error:
            after_error = {'type': type(error).__name__, 'message': str(error),
                           'traceback': traceback.format_exc()}
        unchanged = before == after if before is not None and after is not None else None
        final_status = (
            'failed_source_changed_during_scoped_timing_diagnostic' if unchanged is False else
            status if unchanged is True and after_error is None else
            'unknown_source_check_after_scoped_timing_diagnostic'
        )
        result = {'status': final_status,
                  'source_sha': cfg['source_sha'], 'source_tree': cfg['source_tree'],
                  'source_unchanged': unchanged, 'before_error': before_error, 'after_error': after_error,
                  'source_before': None if before is None else {'bytes': len(before), 'sha256': sha256(before)},
                  'source_after': None if after is None else {'bytes': len(after), 'sha256': sha256(after)},
                  'measurements': 'timing-metrics.json', 'full_gate_run': False,
                  'wall_seconds': time.perf_counter() - started_wall, 'cpu_seconds': time.process_time() - started_cpu}
        write_json(records / 'diagnostic-result.json', result)
        event('timing_diagnostic_finished', **result)
    if result['source_unchanged'] is not True or result['after_error'] is not None:
        return 1
    return 0 if status == 'completed_scoped_timing_diagnostic' else 3 if status == 'stopped_scoped_timing_diagnostic' else 1


if __name__ == '__main__':
    raise SystemExit(main())
