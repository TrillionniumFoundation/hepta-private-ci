"""Single-attempt supervisor. No download, install, environment switching or retry."""
import argparse
import datetime
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import signal
import subprocess
import sys
import time
from runtime_integrity import verify as verify_runtime
from common import ROOT, read_json, sha256, summarize, validate_fixtures, verify_assets, verify_seal


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')


def proc_highwater(pid):
    try:
        text = Path(f'/proc/{pid}/status').read_text()
        return max(int(line.split()[1]) * 1024 for line in text.splitlines() if line.startswith(('VmRSS:', 'VmHWM:')))
    except (FileNotFoundError, ProcessLookupError, ValueError):
        return 0


def host_metadata(cpu):
    info = {}
    blocks = Path('/proc/cpuinfo').read_text().split('\n\n')
    block = next(b for b in blocks if any(line.partition(':')[0].strip() == 'processor' and line.partition(':')[2].strip() == str(cpu) for line in b.splitlines()))
    for line in block.splitlines():
        key, _, value = line.partition(':')
        if key.strip() in ('vendor_id', 'model name', 'cpu family', 'model', 'stepping', 'flags'):
            info[key.strip()] = value.strip()
    quotas = {}
    for name in ('cpu.max', 'memory.max', 'cpuset.cpus.effective'):
        path = Path('/sys/fs/cgroup') / name
        quotas[name] = path.read_text().strip() if path.exists() else None
    return {'cpu': info, 'selected_cpu_id': cpu, 'affinity': sorted(os.sched_getaffinity(0)),
            'cgroup': quotas, 'python_version': platform.python_version(),
            'python_build': platform.python_build(), 'python_compiler': platform.python_compiler(),
            'kernel_release': platform.release(), 'machine': platform.machine()}


def stop(proc):
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGKILL)
    proc.wait()


def main():
    assert not sys.flags.optimize, 'Optimized Python prohibited'
    parser = argparse.ArgumentParser()
    parser.add_argument('--assets', required=True)
    parser.add_argument('--admission', required=True)
    parser.add_argument('--approval', required=True)
    args = parser.parse_args()
    start = time.perf_counter()
    protocol = read_json(ROOT / 'protocol.json')
    seal_hash = verify_seal()
    approval = read_json(args.approval)
    assert approval['decision'] == 'GO' and approval['seal_sha256'] == seal_hash
    assert approval['admission_sha256'] == sha256(args.admission)
    assert approval['independent_review'] == 'GO' and approval['primary_run_authorized'] is True
    admission = read_json(args.admission)
    verify_assets(args.assets, admission, protocol)
    validate_fixtures(read_json(ROOT / 'fixtures.json'))
    versions = {name: importlib.metadata.version(name) for name in protocol['runtime_versions']}
    assert versions == protocol['runtime_versions']
    assert platform.system() == 'Linux' and platform.machine() == 'x86_64'
    assert tuple(sys.version_info[:2]) == (3, 12)
    assert admission['full_runtime_distributions'] == dict(sorted((d.metadata['Name'], d.version) for d in importlib.metadata.distributions())), 'Runtime changed after admission'
    runtime_hash = verify_runtime(admission['runtime_integrity'])
    # Exclusive file creation is the global no-rerun latch. Never delete it to retry.
    attempt = {'protocol_id': protocol['protocol_id'], 'seal_sha256': seal_hash,
               'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'state': 'STARTED', 'attempt': 1, 'supervisor_pid': os.getpid()}
    with (ROOT / 'PRIMARY_ATTEMPT.json').open('x') as f:
        json.dump(attempt, f, indent=2)
    output = ROOT / 'private_run'
    output.mkdir(exist_ok=False)
    cpu = min(os.sched_getaffinity(0))
    os.sched_setaffinity(0, {cpu})
    env = os.environ.copy()
    env.update({'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1',
                'NUMEXPR_NUM_THREADS': '1', 'TOKENIZERS_PARALLELISM': 'false',
                'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1',
                'DO_NOT_TRACK': '1', 'CUDA_VISIBLE_DEVICES': '', 'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': '1'})
    sessions = []
    proc = None
    peak_combined = 0
    observation = {'session_index': None, 'arm': None, 'violated_bounds': []}
    try:
        for index, arm in enumerate(protocol['order']):
            assert time.perf_counter() - start < protocol['budget']['wall_seconds']
            result_path = output / f'session_{index + 1:02d}_{arm}.json'
            command = [sys.executable, str(ROOT / 'worker.py'), '--arm', arm, '--assets', str(Path(args.assets).resolve()),
                       '--admission', str(Path(args.admission).resolve()), '--approval', str(Path(args.approval).resolve()),
                       '--output', str(result_path), '--cpu', str(cpu)]
            launch = time.perf_counter()
            peak_session = 0
            observation = {'session_index': index + 1, 'arm': arm, 'worker_elapsed_seconds': 0,
                           'primary_elapsed_seconds': time.perf_counter() - start, 'parent_vmhwm_bytes': proc_highwater(os.getpid()),
                           'worker_vmhwm_bytes': None, 'combined_vmhwm_sum_bytes': None,
                           'session_peak_combined_bytes': 0, 'violated_bounds': [], 'exit_status': None}
            with (output / f'session_{index + 1:02d}.log').open('w') as log:
                proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
                while proc.poll() is None:
                    now = time.perf_counter()
                    parent_hwm = proc_highwater(os.getpid())
                    worker_hwm = proc_highwater(proc.pid)
                    combined = parent_hwm + worker_hwm
                    peak_session = max(peak_session, combined)
                    peak_combined = max(peak_combined, combined)
                    violations = []
                    if now - start > protocol['budget']['wall_seconds']: violations.append('primary_wall_seconds')
                    if now - launch > protocol['budget']['worker_seconds']: violations.append('worker_wall_seconds')
                    if combined > protocol['budget']['rss_bytes']: violations.append('combined_vmhwm_bytes')
                    observation.update({'worker_elapsed_seconds': now - launch, 'primary_elapsed_seconds': now - start,
                                        'parent_vmhwm_bytes': parent_hwm, 'worker_vmhwm_bytes': worker_hwm,
                                        'combined_vmhwm_sum_bytes': combined, 'session_peak_combined_bytes': peak_session,
                                        'violated_bounds': violations, 'limits': protocol['budget']})
                    if violations:
                        stop(proc)
                        observation['exit_status'] = proc.returncode
                        raise RuntimeError('Resource budget exceeded; primary attempt aborted without retry')
                    time.sleep(protocol['budget']['poll_seconds'])
                observation['exit_status'] = proc.returncode
                observation['worker_elapsed_seconds'] = time.perf_counter() - launch
                assert proc.returncode == 0, f'Worker {index + 1} failed with exit {proc.returncode}; inspect private log'
            result = read_json(result_path)
            # Includes usable JSON read/parse: imports/load/conversion/warmup/measurement/serialization/exit.
            usable = time.perf_counter()
            result['first_query_from_launch_ms'] = (result['first_at'] - launch) * 1000
            result['ready_from_launch_ms'] = (result['ready_at'] - launch) * 1000
            result['full_session_from_launch_ms'] = (usable - launch) * 1000
            result['combined_parent_worker_highwater_sum_bytes'] = peak_session
            assert result['worker_peak_rss_bytes'] + proc_highwater(os.getpid()) <= protocol['budget']['rss_bytes']
            if sessions:
                assert result['token_fingerprints'] == sessions[0]['token_fingerprints']
                assert result['untruncated_token_lengths'] == sessions[0]['untruncated_token_lengths']
            sessions.append(result)
            write_json(result_path, result)
        assert verify_runtime(admission['runtime_integrity']) == runtime_hash
        summary = summarize(sessions, protocol)
        summary.update({'protocol_id': protocol['protocol_id'], 'seal_sha256': seal_hash,
                        'model_revision': protocol['model_revision'], 'runtime_versions': versions,
                        'host_metadata': host_metadata(cpu), 'runtime_integrity_sha256': runtime_hash,
                        'timing_label': 'process-cold; OS page-cache uncontrolled; preflight hash reads warm page cache',
                        'independent_paired_sessions': 6, 'fresh_worker_processes': 12,
                        'primary_wall_seconds': time.perf_counter() - start,
                        'combined_parent_worker_highwater_sum_peak_bytes': peak_combined,
                        'sessions': sessions,
                        'source_weight_file_bytes': (Path(args.assets) / 'model.safetensors').stat().st_size,
                        'source_asset_bytes_total': sum(p.stat().st_size for p in Path(args.assets).iterdir()),
                        'setup_costs': admission['setup_costs'],
                        'setup_cost_scope': 'Shared runtime/model acquisition recorded separately; excluded from local process startup'})
        assert summary['primary_wall_seconds'] <= protocol['budget']['wall_seconds']
        write_json(output / 'aggregate.json', summary)
        attempt['state'] = 'COMPLETED'
        attempt['decision'] = summary['decision']
    except BaseException as exc:
        if proc is not None and proc.poll() is None:
            stop(proc)
        attempt['state'] = 'INCONCLUSIVE_ABORTED_NO_RETRY'
        attempt['error_type'] = type(exc).__name__
        attempt['error'] = str(exc)
        write_json(output / 'failure.json', {'attempt': attempt, 'completed_sessions': len(sessions),
                                           'elapsed_seconds': time.perf_counter() - start, 'partial_results_preserved': True,
                                           'last_worker_observation': observation,
                                           'combined_monitored_peak_bytes': peak_combined})
        raise
    finally:
        attempt['elapsed_seconds'] = time.perf_counter() - start
        write_json(ROOT / 'PRIMARY_ATTEMPT.json', attempt)
    print(json.dumps({'state': attempt['state'], 'decision': attempt.get('decision'), 'sessions': len(sessions)}))

if __name__ == '__main__':
    main()
