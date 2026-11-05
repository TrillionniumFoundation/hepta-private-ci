"""Bound trusted evaluation arms in fresh POSIX Python processes.

Cloudpickle is used ONLY for host-owned callbacks, never for client checkpoints or
wire requests. This provides separate Python heaps and temporary working directories;
it is not a security sandbox or a reset of shared databases/services/absolute paths.
Such external state must be independently snapshotted by the trusted experiment.
RLIMIT_AS bounds virtual address space, not RSS. RSS is measured after execution.
"""

import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import tempfile
import time
import threading

import cloudpickle


ROOT = Path(__file__).resolve()
MAX_INPUT = 64 * 1024 * 1024
SERIALIZATION_LOCK = threading.RLock()


def _worker(snapshot, cpu_seconds, address_space_bytes, output_limit, deadline):
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_AS, (address_space_bytes, address_space_bytes))
    resource.setrlimit(resource.RLIMIT_FSIZE, (output_limit, output_limit))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.setitimer(signal.ITIMER_REAL, max(1., deadline))
    cases_wire, predictor, executor_factory = cloudpickle.loads(Path(snapshot).read_bytes())
    executor = executor_factory()
    signal.setitimer(signal.ITIMER_REAL, 0.)
    for raw in json.loads(cases_wire):
        began = time.perf_counter()
        signal.setitimer(signal.ITIMER_REAL, deadline)
        try:
            # A private decoded case and executor state are kept within this arm.
            choice = predictor(raw['query'])
            correct = executor(choice, raw['payload']) == raw['expected']
            error = None
        except Exception as exc:
            correct, error = False, type(exc).__name__
        elapsed = time.perf_counter() - began
        signal.setitimer(signal.ITIMER_REAL, 0.)
        if elapsed > deadline:
            correct, error = False, 'deadline'
        row = dict(id=raw['key'], cluster=raw['cluster'], stratum=raw['stratum'],
                   correct=bool(correct), error=error, seconds=elapsed)
        print(json.dumps(row, allow_nan=False, separators=(',', ':')), flush=True)
    print(json.dumps({'terminal': True, 'completed': len(json.loads(cases_wire))}), flush=True)


def run_arm(cases_wire, model, executor_factory, deadline_seconds, *, cpu_seconds=30,
            wall_seconds=60., address_space_bytes=1024 * 1024 * 1024):
    """Return every registered row plus measured costs, including failed arms.

    The worker PID remains unreaped until its original process group is signalled,
    preventing a recycled PID from being mistaken for this worker during cleanup.
    Detached descendants and external services are outside this trusted-runner scope.
    """
    if (os.name != 'posix' or not hasattr(os, 'wait4') or not hasattr(os, 'WNOWAIT')):
        raise ValueError('bounded evaluation requires POSIX waitid/wait4')
    if (type(cpu_seconds) is not int or cpu_seconds < 1
            or type(address_space_bytes) is not int or address_space_bytes < 16 * 1024 * 1024
            or type(wall_seconds) not in (int, float) or not math.isfinite(wall_seconds)
            or wall_seconds <= 0 or not math.isfinite(deadline_seconds) or deadline_seconds <= 0):
        raise ValueError('invalid external worker budgets')
    cases = json.loads(cases_wire)
    began = time.perf_counter()
    receipt = dict(status='serialization_error', wall_seconds=None, cpu_seconds=None,
                   peak_rss_bytes=None, output_bytes=0, worker_pid=None, input_sha256=None,
                   runner_sha256=hashlib.sha256(ROOT.read_bytes()).hexdigest(),
                   isolation='fresh-interpreter-private-cwd', cloudpickle=cloudpickle.__version__,
                   external_state_isolated=False, cpu_limit_seconds=cpu_seconds,
                   address_space_limit_bytes=address_space_bytes, wall_limit_seconds=wall_seconds,
                   limit_scope='CPU/AS hard limits are per process; joined CPU is checked after wait4',
                   snapshot_scope='Callback defining modules by value; other imports use the pinned runtime',
                   cost_scope='One worker and children it reaped; excludes setup, parent serialization, '
                              'network, energy and external services. Not a complete deployment bill.')
    rows, reason = [], 'serialization_error'
    try:
        # Serialize the same unchanged host state separately for each arm. Neither
        # predictor nor factory is called in the parent or after the other arm.
        modules = {inspect.getmodule(callback) or inspect.getmodule(type(callback))
                   for callback in (model.predict, executor_factory)}
        modules = {module for module in modules if module is not None and module.__name__ != 'builtins'}
        with SERIALIZATION_LOCK:
            prior = cloudpickle.list_registry_pickle_by_value()
            added = [module for module in modules if module.__name__ not in prior]
            try:
                for module in added:
                    cloudpickle.register_pickle_by_value(module)
                snapshot = cloudpickle.dumps((cases_wire, model.predict, executor_factory), protocol=5)
            finally:
                for module in added:
                    cloudpickle.unregister_pickle_by_value(module)
        receipt['callback_modules_by_value'] = sorted(module.__name__ for module in modules)
        if len(snapshot) > MAX_INPUT:
            raise ValueError('host callback snapshot exceeds input cap')
    except Exception as exc:
        receipt['failure_type'] = type(exc).__name__
    else:
        receipt['input_sha256'] = hashlib.sha256(snapshot).hexdigest()
        output_limit = min(32 * 1024 * 1024, max(8192, len(cases) * 2048 + 4096))
        try:
            with tempfile.TemporaryDirectory(prefix='memory-eval-') as temporary:
                work = Path(temporary)
                payload = work / 'host-snapshot.bin'
                payload.write_bytes(snapshot)
                with (work / 'stdout').open('wb') as stdout, (work / 'stderr').open('wb') as stderr:
                    process = None
                    try:
                        process = subprocess.Popen([sys.executable, str(ROOT), '--worker', str(payload),
                            str(cpu_seconds), str(address_space_bytes), str(output_limit), str(deadline_seconds)],
                            cwd=work, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                            start_new_session=True, close_fds=True)
                        receipt['worker_pid'] = process.pid
                        wait_began = time.perf_counter()
                        reason = 'worker_exit'
                        while True:
                            state = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                            if state is not None:
                                break
                            if time.perf_counter() - wait_began >= wall_seconds:
                                reason = 'deadline'
                                break
                            time.sleep(.005)
                    finally:
                        if process is not None:
                            # The leader has not been reaped and its PID cannot be reused.
                            try:
                                os.killpg(process.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            _, status, usage = os.wait4(process.pid, 0)
                            process.returncode = os.waitstatus_to_exitcode(status)
                    receipt.update(exit_code=process.returncode, worker_wall_seconds=time.perf_counter()-wait_began,
                                   cpu_seconds=usage.ru_utime + usage.ru_stime,
                                   peak_rss_bytes=int(usage.ru_maxrss * (1024 if sys.platform.startswith('linux') else 1)))
                raw = (work / 'stdout').read_bytes()
                receipt['output_bytes'] = len(raw)
                receipt['stderr_bytes'] = (work / 'stderr').stat().st_size
                receipt['output_sha256'] = hashlib.sha256(raw).hexdigest()
                terminal = False
                try:
                    for line in raw.splitlines():
                        if len(line) > 2048 or terminal:
                            raise ValueError('invalid worker output framing')
                        row = json.loads(line)
                        if row == {'terminal': True, 'completed': len(cases)}:
                            terminal = True
                            continue
                        if len(rows) >= len(cases):
                            raise ValueError('excess worker rows')
                        case = cases[len(rows)]
                        if (set(row) != {'id', 'cluster', 'stratum', 'correct', 'error', 'seconds'}
                                or (row['id'], row['cluster'], row['stratum']) !=
                                   (case['key'], case['cluster'], case['stratum'])
                                or type(row['correct']) is not bool
                                or not (row['error'] is None or isinstance(row['error'], str))
                                or type(row['seconds']) not in (int, float)
                                or not math.isfinite(row['seconds']) or row['seconds'] < 0):
                            raise ValueError('invalid worker row identity/value')
                        rows.append(row)
                    if process.returncode == 0 and terminal and len(rows) == len(cases):
                        reason = 'completed'
                    elif process.returncode in (-signal.SIGALRM, -signal.SIGXCPU):
                        reason = 'deadline'
                except (ValueError, TypeError, KeyError, UnicodeError):
                    rows, reason = [], 'protocol_error'
        except OSError as exc:
            reason = 'launch_or_io_error'
            receipt['failure_type'] = type(exc).__name__
        if receipt['cpu_seconds'] is not None and receipt['cpu_seconds'] > cpu_seconds:
            reason = 'cpu_budget_exceeded'
    # Failed or unstarted cases remain in the registered denominator.
    for case in cases[len(rows):]:
        rows.append(dict(id=case['key'], cluster=case['cluster'], stratum=case['stratum'],
                         correct=False, error=reason, seconds=0., not_completed=True))
    receipt.update(status=reason, wall_seconds=time.perf_counter()-began)
    return rows, receipt


if __name__ == '__main__':
    if len(sys.argv) != 7 or sys.argv[1] != '--worker':
        raise SystemExit('only the trusted parent may invoke this worker')
    _worker(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), float(sys.argv[6]))
