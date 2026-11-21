"""One owned child, one attempt directory, full parent-qualified verification outcome."""
import argparse
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time

from stage_contract import (FITS, LIMITS, check_contract, load_json, pin, require,
                            save_new, utc, verify_pin)

THREAD_KEYS = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
               'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS')


def child_result_check(root, contract, contract_pin):
    result_pin = pin(root / 'output' / 'STAGE_RESULTS.json')
    result = load_json(result_pin['path'])
    require(result['schema'] == 'hepta-verification-only-child-results-v1' and
            result['status'] == 'VERIFIED_PENDING_PARENT' and
            result['stage_contract_pin'] == contract_pin, 'new-stage child identity/status')
    require(result['source_pins'] == contract['source_pins'] and
            result['original_failed_reader'] == contract['original']['prior_failure'],
            'new source and preserved prior failure')
    require(result['full_PASS_requires_parent_process_COMPLETED'] is True and
            result['original_raw_result_alone_is_not_new_stage_acceptance'] is True and
            result['production_admission'] is False, 'stage acceptance scope')
    require(all(result[name] is True for name in ('mathematical_thresholds_unchanged',
            'bindings_reuse_checked', 'original_global_source_phase_entropy_exclusion_primary_checks_completed')),
            'all unchanged checks must complete')
    require(all(result[name] == 0 for name in ('new_candidates', 'new_publics', 'new_quality_comparisons')),
            'verification-only scope')
    require(len(result['fit_receipts']) == len(FITS), 'exactly five fit receipts')
    directory = root / 'output' / 'fits'
    require({p.name for p in directory.iterdir()} == {'fit_' + str(fit) + '.json' for fit in FITS},
            'complete and exclusive fit inventory')
    for fit, expected in zip(FITS, result['fit_receipts'], strict=True):
        require(Path(expected['path']) == directory / ('fit_' + str(fit) + '.json'), 'fit receipt destination')
        verify_pin(expected)
        item = load_json(expected['path'])
        require(item['schema'] == 'hepta-verification-fit-complete-v1' and
                item['status'] == 'FIT_COMPLETE' and item['fit'] == fit and
                item['stage_contract_pin'] == contract_pin and
                item['new_source_pins'] == contract['source_pins'] and
                item['original_CONF_tail_checks_completed'] is True, 'complete bound fit receipt')
    raw = result['raw_original_reader_results_pin']
    require(Path(raw['path']) == root / 'output' / 'READER_RESULTS.json', 'delegated result location')
    verify_pin(raw)
    record = load_json(raw['path'])
    require(record['status'] == 'PASS' and record['protocol_sha256'] == contract['original']['protocol']['sha256'] and
            record['counts'] == result['counts'], 'delegated original check result')
    require(result['counts']['own_graphs'] == 400 and result['counts']['original_recursive_worlds'] == 80,
            'whole fixed verification queue')
    require(not (root / 'STAGE_FAILED.json').exists() and not (root / 'output' / 'FAILED.json').exists(),
            'failed child cannot pass')
    return result, result_pin


def main(args):
    wall_start, self_start = time.monotonic(), time.process_time()
    contract, contract_pin = check_contract(args.contract)
    require(pin(__file__) == contract['source_pins']['supervise_verification.py'], 'actual supervisor source')
    entry = Path(__file__).with_name('run_verification.py').resolve()
    require(pin(entry) == contract['source_pins']['run_verification.py'], 'actual child entry source')
    require(pin(sys.executable) == contract['environment']['executable_pin'], 'actual parent interpreter')
    root = Path(contract['attempt_root'])
    root.mkdir(parents=True, exist_ok=False)
    environment = dict(os.environ, PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTHONHASHSEED='0')
    environment.update({key: '1' for key in THREAD_KEYS})
    environment['PYTHONPATH'] = contract['environment']['PYTHONPATH']
    environment['PYTHONPYCACHEPREFIX'] = str(root / 'unused_bytecode_cache')
    command = [sys.executable, str(entry),
               '--contract', str(args.contract.resolve()), '--output', str(root / 'output')]
    launch = dict(schema='hepta-verification-only-launch-v1', created_utc=utc(),
        stage_contract_pin=contract_pin, command=command, limits=LIMITS, source_pins=contract['source_pins'],
        original_failed_reader=contract['original']['prior_failure'], retry_permitted=False,
        actual_entry_pin=pin(entry), actual_supervisor_pin=pin(__file__), actual_interpreter_pin=pin(sys.executable),
        environment={key: environment[key] for key in (*THREAD_KEYS, 'PYTHONPATH', 'PYTHONNOUSERSITE',
                                                       'PYTHONDONTWRITEBYTECODE', 'PYTHONHASHSEED', 'PYTHONPYCACHEPREFIX')})
    save_new(root / 'LAUNCH.json', launch)

    def constrain():
        os.sched_setaffinity(0, {7})
        resource.setrlimit(resource.RLIMIT_AS, (LIMITS['address_space_bytes'],) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (LIMITS['CPU_soft'], LIMITS['CPU_hard']))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    process, timeout, error = None, False, None
    launched_at = time.monotonic()
    try:
        with (root / 'stdout.txt').open('xb') as stdout, (root / 'stderr.txt').open('xb') as stderr:
            remaining = LIMITS['wall_hard'] - (time.monotonic() - wall_start)
            require(remaining > 0, 'stage wall budget consumed by preflight')
            process = subprocess.Popen(command, env=environment, stdout=stdout, stderr=stderr,
                                       start_new_session=True, preexec_fn=constrain)
            try:
                remaining = LIMITS['wall_hard'] - (time.monotonic() - wall_start)
                process.wait(timeout=max(0.0, remaining))
            except subprocess.TimeoutExpired:
                timeout = True
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
    except BaseException as exc:
        error = dict(type=type(exc).__name__, message=str(exc))
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    child_wall = time.monotonic() - launched_at
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    child_user, child_system = after.ru_utime-usage.ru_utime, after.ru_stime-usage.ru_stime
    result, result_pin, unchanged = None, None, False
    returncode = process.returncode if process is not None else None
    try:
        check_contract(args.contract)
        require(pin(args.contract) == contract_pin, 'new contract changed')
        unchanged = True
        result, result_pin = child_result_check(root, contract, contract_pin)
    except BaseException as exc:
        error = error or dict(type=type(exc).__name__, message=str(exc))
    supervisor_wall = time.monotonic() - wall_start
    complete = (returncode == 0 and not timeout and error is None and unchanged and
                child_user+child_system <= LIMITS['CPU_hard'] and supervisor_wall <= LIMITS['wall_hard'])
    record = dict(launch, schema='hepta-verification-only-process-v1', completed_utc=utc(),
        status='COMPLETED' if complete else 'FAILED_OR_UNKNOWN', returncode=returncode,
        wall_timeout=timeout, error=error, source_and_input_closure_unchanged=unchanged,
        child_CPU_seconds=child_user+child_system, child_user_CPU_seconds=child_user,
        child_system_CPU_seconds=child_system, child_wall_seconds=child_wall,
        supervisor_CPU_seconds=time.process_time()-self_start,
        supervisor_wall_seconds=supervisor_wall,
        wall_budget_scope='Entire supervisor stage including preflight, child and final input/source checks; final receipt-write tail separately unmetered.',
        CPU_budget_scope='175/180 limits apply to child process; supervisor CPU separately included in recorded whole-stage cost.',
        result_pin=result_pin, child_maxrss_KiB=after.ru_maxrss, production_admission=False)
    process_pin = save_new(root / 'PROCESS.json', record)
    if complete:
        save_new(root / 'FINAL_VERIFICATION.json', dict(schema='hepta-verification-only-acceptance-v1',
            status='PASS', created_utc=utc(), stage_contract_pin=contract_pin,
            process_pin=process_pin, child_results_pin=result_pin, fit_receipts=result['fit_receipts'],
            original_failed_reader=contract['original']['prior_failure'],
            mathematical_check_scope='Exactly the original sealed candidate,80PUBLIC and four-contrast check set.',
            original_failure_rewritten=False, production_admission=False,
            existing_native_exporter_compatibility=False,
            NDU='KEEP_ORIGINAL_AND_STOP pending separate value, future-call and owner conditions.'))
    print('{"status":"' + ('PASS' if complete else 'FAILED_OR_UNKNOWN') +
          '","production_admission":false}', flush=True)
    return 0 if complete else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--contract', type=Path, required=True)
    sys.exit(main(parser.parse_args()))
