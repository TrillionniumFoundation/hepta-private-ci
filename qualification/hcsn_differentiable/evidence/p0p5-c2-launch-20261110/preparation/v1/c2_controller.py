"""Explicit, non-retrying six-fit C2 controller; validation-only unless later enabled."""
import os
import time

CONTROLLER_STARTED = time.monotonic()

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import resource
import signal
import subprocess
import threading
import traceback

from c2_boundary import require
from c2_io import exclusive_json, identity, runtime_identity, sha, verify_files
from c2_runner import bind_program, require_decision


def child_deadline(contract, outer, dispatched):
    spent = outer.get('whole_process_wall_seconds')
    ceiling = outer.get('hard_wall_seconds')
    require(isinstance(spent, (int, float)) and 0 < spent < 43200,
            'original outer active cost missing')
    require(isinstance(ceiling, (int, float)) and 0 < ceiling <= 14400,
            'original actual wall ceiling invalid')
    total = contract['cumulative_active_wall_seconds']
    require(ceiling <= total <= 43200 and total > spent, 'invalid new cumulative budget')
    return dispatched + total - spent


def wait_child(process, deadline, *, poll_seconds=0.1):
    """Collect this PID's actual exit rusage. Popen.poll/wait must not reap it first."""
    killed, kill_error = False, None
    while True:
        pid, status, usage = os.wait4(process.pid, os.WNOHANG)
        if pid:
            process.returncode = os.waitstatus_to_exitcode(status)
            return {'returncode': process.returncode, 'hard_timeout_sent': killed,
                    'kill_error': kill_error, 'child_terminal_unknown': False,
                    'child_cpu_seconds': usage.ru_utime + usage.ru_stime,
                    'child_user_cpu_seconds': usage.ru_utime, 'child_system_cpu_seconds': usage.ru_stime,
                    'child_peak_rss_bytes': int(usage.ru_maxrss) * 1024,
                    'child_cpu_scope': 'exact per-PID wait4 whole process including imports and finalization'}
        if time.monotonic() >= deadline and not killed:
            try:
                os.kill(process.pid, signal.SIGKILL)
                killed = True
            except ProcessLookupError:
                # The next wait4 still owns and accounts for the already exited child.
                killed = True
            except Exception:
                kill_error = traceback.format_exc()
                raise
        time.sleep(poll_seconds)


def harvest_futures(futures, snapshots, record):
    for future in as_completed(futures):
        name = futures[future]
        try:
            row = future.result()
            require(isinstance(row, dict) and row.get('name') == name, 'worker returned wrong terminal identity')
        except Exception:
            row = dict(snapshots.get(name, {'name': name}))
            row.update(status='worker_exception', worker_error=traceback.format_exc(),
                       terminal_accounting_incomplete=True)
            row.setdefault('process_started', None)
            row.setdefault('whole_process_wall_seconds', None)
            row.setdefault('attempt_wrapper_wall_seconds', None)
            row.setdefault('child_cpu_seconds', None)
            try:
                record(row)
            except Exception:
                row.setdefault('journal_errors', []).append(traceback.format_exc())
        yield row


def cost_totals(attempts, names):
    missing_terminal = sorted(set(names) - {r['name'] for r in attempts})
    incomplete = set(missing_terminal)
    unknown_launch = set(missing_terminal)
    for row in attempts:
        if row.get('process_started') is None:
            unknown_launch.add(row['name'])
        if (row.get('whole_process_wall_seconds') is None or row.get('attempt_wrapper_wall_seconds') is None
                or row.get('terminal_accounting_incomplete') or row.get('journal_errors')
                or row.get('child_terminal_unknown')
                or row.get('process_started') is True and row.get('child_cpu_seconds') is None):
            incomplete.add(row['name'])
    return {'missing_terminal_attempt_names': missing_terminal,
        'actual_continuations_started': sum(r.get('process_started') is True for r in attempts),
        'launch_status_unknown_names': sorted(unknown_launch),
        'actual_continuations_started_is_lower_bound': bool(unknown_launch),
        'sum_attempt_outer_wall_seconds': sum(r['whole_process_wall_seconds'] for r in attempts
                                              if r.get('whole_process_wall_seconds') is not None),
        'sum_attempt_wrapper_wall_seconds': sum(r['attempt_wrapper_wall_seconds'] for r in attempts
                                                if r.get('attempt_wrapper_wall_seconds') is not None),
        'sum_exact_per_child_cpu_seconds': sum(r['child_cpu_seconds'] for r in attempts
                                               if r.get('child_cpu_seconds') is not None),
        'attempt_cost_accounting_complete': not incomplete,
        'incomplete_attempt_accounting_names': sorted(incomplete),
        'attempt_sums_are_lower_bounds': bool(incomplete)}


def verify_roster(contract, campaign):
    require(campaign.get('status') == 'completed_attempt_roster' and campaign.get('source_unchanged') is True,
            'original 42 roster is not source-consistent terminal')
    require(len(campaign.get('attempts', [])) == 42, 'original roster is incomplete')
    original = [row for row in campaign['attempts'] if row['arm'] == 'hcsn']
    target = {(seed, lr) for seed in (101, 211, 307) for lr in (.001, .003)}
    require(len(original) == 6 and {(r['seed'], r['learning_rate']) for r in original} == target,
            'original HCSN opportunity roster differs')
    require(set(contract['fit_names']) == {r['name'] for r in original}
            and len(contract['fit_names']) == 6, 'C2 contract drops or adds a seed/LR opportunity')
    for row in original:
        require(row['status'] == 'failed' and row['fit_status'] == 'budget_exhausted'
                and row['returncode'] == 2, 'all candidates must have real soft-wall terminal reports')
    return sorted(original, key=lambda r: r['name'])


def run_controller(args):
    out = Path(args.output)
    out.mkdir(exist_ok=False)
    (out / 'attempts').mkdir()
    (out / 'parent-records').mkdir()
    (out / 'fits').mkdir()
    lock = threading.Lock()
    journal = (out / 'commands.jsonl').open('x')
    snapshots, names = {}, []
    program_inputs = {}
    report = {'schema': 'hcsn-c2-controller-v1', 'status': 'started', 'attempts': [],
        'confirmation_access': False, 'scientific_admission': 'HOLD', 'energy_joules': None,
        'started_utc': datetime.now(timezone.utc).isoformat(), 'formal_fits_started': 0,
        'execution_requested': args.execute, 'calendar_scope': 'separate phase; may extend calendar past original 15000s',
        'cpu_aggregation_scope': 'per-child wait4 exact and RUSAGE_CHILDREN aggregate are two views; do not add together',
        'controller_setup_scope': 'all imports, source/data admission and launch bookkeeping charged separately once'}

    def record(row):
        with lock:
            snapshots[row['name']] = dict(row)
            journal.write(json.dumps(row, allow_nan=False) + '\n')
            journal.flush()

    try:
        program_inputs = bind_program(args.program_manifest)
        require(str(Path(args.contract).resolve()) in program_inputs, 'controller contract not in frozen manifest')
        contract = json.loads(Path(args.contract).read_bytes())
        require(contract['execution_authorized'] is False, 'candidate contract must retain its original preparation status')
        require(contract['maximum_epochs'] == 200 and contract['cumulative_active_wall_seconds'] == 43200
                and contract['workers'] <= 6 and contract['threads'] == 1
                and contract['address_space_bytes'] == 8 * 1024**3
                and contract['peak_rss_bytes'] == 6 * 1024**3, 'C2 frozen resource policy changed')
        parent_result = Path(contract['parent_campaign']) / 'RESULT.json'
        require(sha(parent_result) == contract['parent_campaign_result_sha256'], 'original roster hash differs')
        program_inputs[str(parent_result)] = identity(parent_result)
        parent_plan = Path(contract['parent_campaign_plan'])
        require(sha(parent_plan) == contract['parent_campaign_plan_sha256'], 'original campaign plan differs')
        program_inputs[str(parent_plan)] = identity(parent_plan)
        require(runtime_identity() == json.loads(Path(contract['runtime_identity_path']).read_bytes()),
                'controller runtime differs from original training')
        require(sha(contract['runtime_identity_path']) == contract['runtime_identity_sha256'], 'runtime receipt differs')
        program_inputs[contract['runtime_identity_path']] = identity(contract['runtime_identity_path'])
        parents = verify_roster(contract, json.loads(parent_result.read_bytes()))
        names = [p['name'] for p in parents]
        report['contract'] = identity(args.contract)
        report['candidate_names'] = names
        if not args.execute:
            report['status'] = 'validated_controller_inputs_no_process_started'
            return report
        require_decision(args.decision, args.decision_sha256, args.contract, args.program_manifest)
        program_inputs[str(Path(args.decision).resolve())] = identity(args.decision)
        report['execution_decision'] = identity(args.decision)

        def run_one(parent):
            dispatched = time.monotonic()
            row = {'name': parent['name'], 'status': 'preparing', 'process_started': False,
                'parent_full_outer_wall_seconds': parent['whole_process_wall_seconds'],
                'parent_actual_hard_wall_seconds': parent['hard_wall_seconds'],
                'cumulative_active_wall_cap_seconds': contract['cumulative_active_wall_seconds'],
                'dispatch_utc': datetime.now(timezone.utc).isoformat(),
                'whole_process_wall_seconds': None, 'attempt_wrapper_wall_seconds': None,
                'child_cpu_seconds': None}
            process = None
            attempt = out / 'attempts' / parent['name']
            try:
                record(row)
                attempt.mkdir(exist_ok=False)
                outer = out / 'parent-records' / (parent['name'] + '.json')
                row['parent_outer_record'] = exclusive_json(outer, parent)
                deadline = child_deadline(contract, parent, dispatched)
                row['remaining_at_dispatch_seconds'] = deadline - dispatched
                runner = Path(__file__).with_name('c2_runner.py')
                command = [contract['python'], '-B', str(runner), '--parent',
                    str(Path(contract['parent_campaign']) / parent['name']), '--outer', str(outer),
                    '--source', contract['source'], '--contract', str(args.contract),
                    '--program-manifest', str(args.program_manifest), '--policy', str(Path(__file__).with_name('POSTERIOR-POLICY.json')),
                    '--output', str(out / 'fits' / parent['name']), '--execute',
                    '--decision', str(args.decision), '--decision-sha256', args.decision_sha256]
                # Do not use preexec_fn from ThreadPoolExecutor threads. A clean
                # interpreter sets the limit, then execs the exact pinned Python.
                bootstrap = ('import os,resource,sys; '
                    f'resource.setrlimit(resource.RLIMIT_AS,({contract["address_space_bytes"]},{contract["address_space_bytes"]})); '
                    'os.execv(sys.argv[1],sys.argv[1:])')
                launch = [contract['python'], '-B', '-c', bootstrap, *command]
                env = os.environ.copy()
                env.update(HCSN_PROCESS_STARTED=str(dispatched), OMP_NUM_THREADS='1',
                    OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1',
                    PYTHONDONTWRITEBYTECODE='1', PYTHONHASHSEED='0')
                row['command'] = launch
                row['prelaunch_wall_seconds'] = time.monotonic() - dispatched
                require(deadline - time.monotonic() > contract['finalization_reserve_seconds'],
                        'no remaining allowance after charged prelaunch setup')
                with (attempt / 'stdout').open('xb') as stdout, (attempt / 'stderr').open('xb') as stderr:
                    row['spawn_attempted'] = True
                    process = subprocess.Popen(launch, cwd=str(Path(__file__).parent), env=env,
                        stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
                    row.update(process_started=True, pid=process.pid, status='running')
                    record(row)
                    row.update(wait_child(process, deadline))
                row['whole_process_wall_seconds'] = time.monotonic() - dispatched
                result_path = out / 'fits' / parent['name'] / 'result.json'
                if result_path.is_file():
                    row['result'] = identity(result_path)
                    result = json.loads(result_path.read_bytes())
                    row.update(fit_status=result['status'], adequate=result['training_adequacy_established'],
                        cumulative_epochs_completed=result['cumulative_epochs_completed'])
                row['status'] = ('timed_out' if row['hard_timeout_sent'] else
                    'completed' if row['returncode'] == 0 else 'failed')
            except Exception:
                row.update(status='controller_attempt_failure', error=traceback.format_exc())
                if process is None and row.get('spawn_attempted'):
                    row.update(process_started=None, terminal_accounting_incomplete=True,
                               launch_outcome='Popen raised; no per-PID identity returned')
                if process is not None and process.returncode is None:
                    try:
                        os.kill(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except Exception:
                        row['cleanup_kill_error'] = traceback.format_exc()
                    try:
                        row.update(wait_child(process, time.monotonic()))
                    except Exception:
                        row.update(child_terminal_unknown=True, terminal_accounting_incomplete=True,
                                   cleanup_wait_error=traceback.format_exc())
                row['whole_process_wall_seconds'] = time.monotonic() - dispatched
            finally:
                row['attempt_wrapper_wall_seconds'] = time.monotonic() - dispatched
                row['cumulative_parent_and_c2_active_wall_seconds'] = parent['whole_process_wall_seconds'] + row['attempt_wrapper_wall_seconds']
                row['child_cpu_seconds'] = row.get('child_cpu_seconds')
                for filename in ('stdout', 'stderr'):
                    try:
                        path = attempt / filename
                        row[filename] = identity(path) if path.is_file() else None
                    except Exception:
                        row.setdefault('artifact_errors', []).append(traceback.format_exc())
                try:
                    record(row)
                    exclusive_json(attempt / 'RESULT.json', row)
                except Exception:
                    row.setdefault('journal_errors', []).append(traceback.format_exc())
            return row

        with ThreadPoolExecutor(max_workers=contract['workers']) as pool:
            futures = {pool.submit(run_one, parent): parent['name'] for parent in parents}
            report['attempts'].extend(harvest_futures(futures, snapshots, record))
        report['status'] = 'completed_attempt_roster'
    except Exception:
        report.update(status='controller_failed', error=traceback.format_exc())
    finally:
        report.update(cost_totals(report['attempts'], names if args.execute else []))
        report['source_inputs_before'] = program_inputs
        try:
            verify_files(program_inputs)
            report['source_inputs_unchanged'] = True
        except Exception:
            report.update(status='controller_source_changed', source_inputs_unchanged=False,
                          source_check_error=traceback.format_exc())
        report.update(controller_full_wall_seconds=time.monotonic() - CONTROLLER_STARTED,
            controller_full_cpu_seconds=time.process_time(),
            children_cpu_seconds=resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime,
            controller_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)
        if report['missing_terminal_attempt_names']:
            report['status'] = 'controller_incomplete_attempt_roster'
        journal.close()
        report['commands'] = identity(out / 'commands.jsonl')
        exclusive_json(out / 'RESULT.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--program-manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--decision', type=Path)
    parser.add_argument('--decision-sha256')
    args = parser.parse_args()
    result = run_controller(args)
    return 0 if result['status'] in ('completed_attempt_roster', 'validated_controller_inputs_no_process_started') else 2


if __name__ == '__main__':
    raise SystemExit(main())
