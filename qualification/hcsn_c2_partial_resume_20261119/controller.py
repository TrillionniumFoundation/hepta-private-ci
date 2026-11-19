"""Standard-library controller for one separately identified C2 partial continuation."""

import atexit
import hashlib
import json
import os
from pathlib import Path
import queue
import resource
import shutil
import signal
import subprocess
import sys
import threading
import time

from resources import cgroup_chain, resource_rejections


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "RUN_OUTPUT"
THREAD_VARIABLES = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")


def write(path, value):
    temporary = path.with_suffix(".part.json")
    with temporary.open('w') as stream:
        json.dump(value, stream, allow_nan=False, sort_keys=True, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def verify_freeze(request):
    freeze = json.loads((HERE / "FREEZE.json").read_text())
    if freeze['identity'] != request['identity'] or not {
            'REQUEST.json', 'BINDINGS.json', 'runner.py', 'controller.py'} <= freeze['files'].keys():
        raise ValueError("complete new-identity source freeze required")
    actual = {}
    for name, expected in freeze['files'].items():
        relative = Path(name)
        path = HERE / relative
        if relative.is_absolute() or '..' in relative.parts or path.is_symlink() or not path.is_file():
            raise ValueError("regular relative frozen file required: "+name)
        actual[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual[name] != expected:
            raise ValueError("frozen source hash differs: "+name)
    return {'identity': freeze['identity'], 'files': actual,
            'freeze_sha256': hashlib.sha256((HERE/'FREEZE.json').read_bytes()).hexdigest()}


def host_resources(request):
    memory = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        name, value = line.split(':', 1)
        if name in ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'):
            memory[name] = int(value.split()[0])*1024
    affinity, cores = sorted(os.sched_getaffinity(0)), []
    selected, seen = [], set()
    cpuinfo = {}
    for block in Path('/proc/cpuinfo').read_text().split('\n\n'):
        fields = {key.strip(): value.strip() for line in block.splitlines()
                  for key, sep, value in [line.partition(':')] if sep}
        if {'processor', 'physical id', 'core id'} <= fields.keys():
            cpuinfo[int(fields['processor'])] = (int(fields['physical id']), int(fields['core id']))
    for cpu in affinity:
        base = Path(f'/sys/devices/system/cpu/cpu{cpu}/topology')
        try:
            package, core = (int((base/name).read_text()) for name in ('physical_package_id', 'core_id'))
            topology_source = 'sysfs'
        except FileNotFoundError:
            if cpu not in cpuinfo:
                cores.append({'cpu': cpu, 'topology_source': 'unavailable'})
                continue
            package, core = cpuinfo[cpu]
            topology_source = '/proc/cpuinfo'
        cores.append({'cpu': cpu, 'physical_package_id': package, 'core_id': core,
                      'topology_source': topology_source})
        if (package, core) not in seen:
            selected.append(cpu)
            seen.add((package, core))
    old_key = str(Path(request['original_root'])/'c2-native-execution-20261110-c385-v1')
    conflicts, unreadable = [], []
    for path in Path('/proc').iterdir():
        if not path.name.isdigit() or int(path.name) == os.getpid():
            continue
        try:
            arguments = path.joinpath('cmdline').read_bytes().decode(errors='replace').split('\0')
            old = any(Path(x).name in ('c2_runner.py', 'c2_controller.py') for x in arguments)
            old = old or any(old_key in x or request['original_c2_program'] in x for x in arguments)
            duplicate = any(str(HERE/'runner.py') == x or str(HERE/'controller.py') == x
                            or str(Path(request['previous_continuation_root'])/name) == x
                            for x in arguments for name in ('runner.py', 'controller.py'))
            if old or duplicate:
                conflicts.append({'pid': int(path.name), 'arguments': arguments})
        except FileNotFoundError:
            continue
        except PermissionError:
            unreadable.append(int(path.name))
    return {'observed_unix_time': time.time(), 'observed_monotonic': time.monotonic(),
            'memory_bytes': memory, 'disk_free_bytes': shutil.disk_usage(HERE).free,
            'affinity': affinity, 'physical_core_topology': cores, 'selected_cpus': selected[:1],
            'conflicting_processes': conflicts, 'unreadable_process_cmdlines': unreadable,
            'original_key_path': old_key, 'original_key_path_exists': Path(old_key).exists(),
            'original_artifacts_modified': False, 'cgroup_chain': cgroup_chain()}


def process_memory(pid):
    values = {}
    try:
        for line in Path(f'/proc/{pid}/status').read_text().splitlines():
            key, _, value = line.partition(':')
            if key in ('VmRSS', 'VmHWM', 'VmSize'):
                values[key+'_bytes'] = int(value.split()[0])*1024
    except (FileNotFoundError, ProcessLookupError):
        pass
    return values


def request_stop(item, reason, budget):
    if item.get('stop') is not None or item.get('reaped'):
        return
    now = time.monotonic()
    receipt = {'identity': item['identity'], 'reason': reason, 'monotonic': now,
               'dispatch_elapsed_seconds': now-item['start'], 'pid': item['process'].pid}
    item['stop'] = receipt
    item['kill_deadline'] = min(item['start']+budget['scientific_wall_seconds_per_fit']+
                                budget['cleanup_grace_seconds'], now+budget['cleanup_grace_seconds'])
    try:
        write(OUTPUT/(item['name']+'.STOP_REQUEST.json'), receipt)
        fit_directory = OUTPUT/item['name']
        if fit_directory.is_dir():
            write(fit_directory/'STOP_REQUEST.json', receipt)
    except OSError as error:
        item['stop_receipt_error'] = repr(error)
    try:
        os.killpg(item['process'].pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def wait_receipt(item, messages):
    pid, status, usage = os.wait4(item['process'].pid, 0)
    item['reaped'] = True
    messages.put((pid, status, usage, time.monotonic()))


def main():
    OUTPUT.mkdir(exist_ok=False)
    request = json.loads((HERE/'REQUEST.json').read_text())
    budget = request['budget']
    terminal = {'identity': request['identity'], 'schema': 'hcsn-c2-independent-controller-v1',
                'old_controller_terminal': 'UNKNOWN', 'full_six_fit_replay': False,
                'original_admission_reused': False, 'fits': {}, 'budget': budget}
    try:
        terminal['source_freeze'] = verify_freeze(request)
        observation = host_resources(request)
        write(OUTPUT/'RESOURCE.json', observation)
        reasons = resource_rejections(observation["cgroup_chain"], budget)
        if len(request['fits']) != 1 or budget['concurrency'] != 1 or budget['threads_per_fit'] != 1:
            reasons.append('exactly one one-thread fit required')
        if observation['memory_bytes']['MemAvailable'] < budget['minimum_available_memory_bytes']:
            reasons.append('insufficient MemAvailable')
        if observation['disk_free_bytes'] < budget['minimum_output_disk_free_bytes']:
            reasons.append('insufficient output disk space')
        if len(observation['selected_cpus']) < 1:
            reasons.append('one available physical core required')
        if observation['conflicting_processes']:
            reasons.append('old or duplicate C2 process remains alive')
        if reasons:
            raise ValueError('; '.join(reasons))
    except Exception as error:
        terminal.update(status='DENIED_NO_LAUNCH', reason=repr(error), subprocesses_started=0)
        write(OUTPUT/'TERMINAL.json', terminal)
        print(json.dumps(terminal, sort_keys=True), flush=True)
        return 2
    interrupted = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda number, frame: interrupted.append(number))
    active, messages = {}, queue.Queue()
    # Keep controller bookkeeping inside the same logical CPU as its fit.
    os.sched_setaffinity(0, set(observation['selected_cpus']))
    terminal['controller_affinity'] = sorted(os.sched_getaffinity(0))
    def emergency_cleanup():
        for item in active.values():
            if item.get('reaped'):
                continue
            try:
                os.killpg(item['process'].pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    atexit.register(emergency_cleanup)
    # All fork/preexec launches precede waiter threads; preexec never runs in a
    # multi-threaded parent. Waiters only block in wait4 and return exact rusage.
    for fit, cpu in zip(request['fits'], observation['selected_cpus']):
        name = fit['name']
        start = time.monotonic()
        env = {**os.environ, **{key: '1' for key in THREAD_VARIABLES},
               'HCSN_PHASE_START': repr(start), 'HCSN_ASSIGNED_CPU': str(cpu),
               'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'CUDA_VISIBLE_DEVICES': ''}
        def constrain(cpu=cpu):
            os.setsid()
            resource.setrlimit(resource.RLIMIT_AS, (budget['address_space_bytes_per_fit'],)*2)
            os.sched_setaffinity(0, {cpu})
        stdout, stderr = [(OUTPUT/(name+suffix)).open('xb') for suffix in ('.stdout', '.stderr')]
        try:
            process = subprocess.Popen([sys.executable, str(HERE/'runner.py'), '--fit', name],
                                       cwd=HERE, env=env, preexec_fn=constrain, stdout=stdout, stderr=stderr)
            item = {'name': name, 'identity': fit['new_identity'], 'process': process,
                    'start': start, 'assigned_cpu': cpu, 'stop': None, 'hard_killed': False,
                    'memory_high_water_observed_bytes': 0}
            active[process.pid] = item
        except Exception as error:
            terminal['fits'][name] = {'status': 'SPAWN_FAILED', 'error': repr(error),
                                      'dispatch_monotonic': start}
        finally:
            stdout.close(); stderr.close()
    terminal['subprocesses_started'] = len(active)
    for item in active.values():
        threading.Thread(target=wait_receipt, args=(item, messages), daemon=True).start()
    while active:
        try:
            pid, status, usage, exit_time = messages.get(timeout=.25)
        except queue.Empty:
            pid = None
        if pid is not None:
            item = active.pop(pid)
            item['process'].returncode = os.waitstatus_to_exitcode(status)
            wall = exit_time-item['start']
            result_path = OUTPUT/item['name']/'RESULT.json'
            result, result_error = None, None
            try:
                result = json.loads(result_path.read_text())
            except Exception as error:
                result_error = repr(error)
            receipt = {'identity': item['identity'], 'pid': pid, 'assigned_cpu': item['assigned_cpu'],
                       'dispatch_monotonic': item['start'], 'wait4_return_monotonic': exit_time,
                       'exit_code': item['process'].returncode, 'raw_wait_status': status,
                       'full_fresh_process_wall_seconds': wall,
                       'cpu_user_seconds': usage.ru_utime, 'cpu_system_seconds': usage.ru_stime,
                       'cpu_total_seconds': usage.ru_utime+usage.ru_stime, 'peak_rss_kib': usage.ru_maxrss,
                       'observed_memory_high_water_bytes': item['memory_high_water_observed_bytes'],
                       'scientific_wall_budget_seconds': budget['scientific_wall_seconds_per_fit'],
                       'wall_within_scientific_budget_seconds': min(wall, budget['scientific_wall_seconds_per_fit']),
                       'cleanup_budget_overrun_wall_seconds': max(0., wall-budget['scientific_wall_seconds_per_fit']),
                       'post_deadline_wall_scope': 'May include in-flight compute and finalization; no extra scientific budget or qualification credit.',
                       'post_external_stop_wall_seconds': None if item['stop'] is None else exit_time-item['stop']['monotonic'],
                       'external_stop': item['stop'], 'hard_killed': item['hard_killed'],
                       'stop_receipt_error': item.get('stop_receipt_error'),
                       'result_error': result_error, 'result_status': None if result is None else result.get('status'),
                       'result_sha256': None if result is None else hashlib.sha256(result_path.read_bytes()).hexdigest(),
                       'rss_limit_exceeded': usage.ru_maxrss*1024 > budget['peak_rss_stop_bytes_per_fit']}
            receipt['status'] = ('FAILED_TERMINAL' if item['hard_killed'] or result is None or
                                 item['process'].returncode != 0 else 'REVIEWABLE_TERMINAL')
            write(OUTPUT/(item['name']+'.COST.json'), receipt)
            if result_path.parent.is_dir():
                write(result_path.parent/'COST.json', receipt)
            terminal['fits'][item['name']] = receipt
            write(OUTPUT/'TERMINAL.json', {**terminal, 'status': 'RUNNING' if active else 'FINISHING'})
        for item in active.values():
            if item.get('reaped'):
                continue
            memory = process_memory(item['process'].pid)
            item['memory_high_water_observed_bytes'] = max(item['memory_high_water_observed_bytes'],
                                                          memory.get('VmHWM_bytes', 0), memory.get('VmRSS_bytes', 0))
            now = time.monotonic()
            reason = ('controller_signal' if interrupted else
                      'rss_limit' if item['memory_high_water_observed_bytes'] > budget['peak_rss_stop_bytes_per_fit'] else
                      'scientific_wall_limit' if now-item['start'] >= budget['scientific_wall_seconds_per_fit'] else None)
            if reason is not None:
                request_stop(item, reason, budget)
            if item['stop'] is not None and now >= item['kill_deadline'] and not item['hard_killed']:
                try:
                    os.killpg(item['process'].pid, signal.SIGKILL)
                    item['hard_killed'] = True
                except ProcessLookupError:
                    pass
    terminal['status'] = ('REVIEWABLE_TERMINALS' if all(x['status'] == 'REVIEWABLE_TERMINAL'
                                                       for x in terminal['fits'].values()) else 'INCOMPLETE_OR_FAILED')
    terminal['controller_signals'] = interrupted
    terminal['cgroup_chain_after'] = cgroup_chain()
    try:
        terminal['source_freeze_after'] = verify_freeze(request)
    except Exception as error:
        terminal.update(status='SOURCE_IDENTITY_FAILED', source_error=repr(error))
    write(OUTPUT/'TERMINAL.json', terminal)
    print(json.dumps({'status': terminal['status'], 'fits': list(terminal['fits'])}, sort_keys=True), flush=True)
    return 0 if terminal['status'] == 'REVIEWABLE_TERMINALS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
