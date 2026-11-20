"""Own the frozen matched-E1-to-E4 run and preserve the actual child exit."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import tarfile
import time

BASE = Path('/home/qian-qi/work/hepta-e4-matched-upstream-20261118-2e9b')
ROOT = BASE / 'candidate-41d273d'
SOURCE = ROOT / 'source'
ARTIFACT = Path('/dev/shm/hepta-cell-experiments-v3-20261116-0c078a')
RUNTIME = Path('/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a')
OWNED, OUTPUT = ROOT / 'owned-run-1', ROOT / 'run-1'
TRAINING_SOURCE = Path('/home/qian-qi/work/hepta-e1-matched-info-20261118-2e9b/source')
PRIOR = Path('/home/qian-qi/.local/state/hepta-runtime-mac-worker/jobs/1a1eee74a04-ffbe-36f')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open('xb') as stream:
        stream.write(json.dumps(value, sort_keys=True, allow_nan=False).encode() + b'\n')
        stream.flush()
        os.fsync(stream.fileno())


def main():
    ROOT.mkdir(exist_ok=False)
    SOURCE.mkdir()
    OWNED.mkdir()
    started = time.monotonic()
    initial_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
    for name in ('SOURCE.tar.gz', 'DEPLOYMENT.json'):
        shutil.copyfile(BASE / ('41d273d-' + name), ROOT / name)
    shutil.copyfile(Path(__file__), ROOT / 'RUN_SOURCE.py')
    deployment = json.loads((ROOT / 'DEPLOYMENT.json').read_text())
    assert deployment['source_commit'] == '41d273d06d0138ab4a747c5dc73bb2ee2a61e9ee'
    assert digest(ROOT / 'SOURCE.tar.gz') == deployment['archive_sha256'] == '6ac71e04c6fa790264e898d47578149f31f15941e6dc7763c696666ca506910a'
    with tarfile.open(ROOT / 'SOURCE.tar.gz') as archive:
        assert all(member.isfile() and not Path(member.name).is_absolute() and '..' not in Path(member.name).parts for member in archive)
        archive.extractall(SOURCE)
    assert len(deployment['files']) == 196
    for name, expected in deployment['files'].items():
        assert digest(SOURCE / name) == expected, name
    prior_hashes = {
        'exit.json': '4a96fc210540a0995a758cead94316e46720c0f22cf0bc8f220054e72b4d93df',
        'exit.witness.json': 'a216aa1b83828ef2b9a6e13e45faeb67511f2eb8d7fa89ec7b94b6395f45987e',
    }
    for name, expected in prior_hashes.items():
        assert digest(PRIOR / name) == expected
    prior = json.loads((PRIOR / 'exit.json').read_text())
    assert prior['exit_code'] == 0 and prior['timed_out'] is False and prior['cancelled'] is False
    assert prior['output_complete'] is True and prior['output_durable'] is True
    command = [str(RUNTIME / 'venv/bin/python'), '-I', '-B',
               str(SOURCE / 'scripts/cell_experiments/diagnostic_run_v4.py'),
               '--provider-python', str(RUNTIME / 'venv/bin/python'),
               '--provider-script', str(SOURCE / 'scripts/cell_experiments/diagnostic_provider_v4.py'),
               '--artifact-root', str(ARTIFACT),
               '--module-root', str(SOURCE / 'scripts/cell_experiments'),
               '--output', str(OUTPUT), '--study', 'repair_retrieval', '--panel', 'upstream',
               '--matched-training-source', str(TRAINING_SOURCE)]
    lock_path = ARTIFACT / 'research-round03-20261118-392934-b/WORKER.lock'
    assert lock_path.is_file() and not lock_path.is_symlink()
    with lock_path.open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        gpu = subprocess.run(['/usr/bin/nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits'], capture_output=True, text=True, check=True)
        assert int(gpu.stdout.splitlines()[0]) >= 4096
        write(OWNED / 'INTENT.json', {
            'schema': 'hepta.matched-upstream-owned-run.v1', 'command': command,
            'source_commit': deployment['source_commit'], 'source_tree': deployment['source_tree'],
            'wrapper_sha256': digest(Path(__file__)), 'deployment_sha256': digest(ROOT / 'DEPLOYMENT.json'),
            'prior_receipts': {name: {'path': str(PRIOR / name), 'sha256': expected} for name, expected in prior_hashes.items()},
            'lock': str(lock_path), 'gpu_free_mib_prefilter': int(gpu.stdout.splitlines()[0]),
            'actual_cuda_gate_unchanged': True, 'planned_primary_model_calls': 120,
            'planned_A_setup_model_calls': 4, 'planned_primary_verifier_calls': 120,
            'planned_A_setup_verifier_calls': 4, 'planned_A_reference_verifier_calls': 6,
            'no_E1_upstream_results_read': True, 'started_at_ns': time.time_ns(), 'automatic_retry': False,
        })
        env = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_DATASETS_OFFLINE='1', PYTHONDONTWRITEBYTECODE='1', TOKENIZERS_PARALLELISM='false', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
        timed_out = False
        with (OWNED / 'STDOUT.txt').open('xb') as stdout, (OWNED / 'STDERR.txt').open('xb') as stderr:
            child = subprocess.Popen(command, cwd=SOURCE, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
            write(OWNED / 'STARTED.json', {'pid': child.pid, 'process_group_id': child.pid, 'started_at_ns': time.time_ns(), 'intent_sha256': digest(OWNED / 'INTENT.json')})
            try:
                code = child.wait(timeout=1800)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    code = child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    code = child.wait(timeout=30)
        final_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
        receipt = {
            'pid': child.pid, 'wait_returncode': code, 'exit_source': 'subprocess.Popen.wait', 'timed_out': timed_out,
            'automatic_retry': False, 'wall_seconds': time.monotonic() - started,
            'observed_child_user_cpu_seconds': final_cpu.ru_utime - initial_cpu.ru_utime,
            'observed_child_system_cpu_seconds': final_cpu.ru_stime - initial_cpu.ru_stime,
            'cost_scope': 'owned child and waited descendants; model/verifier costs are nested and not additive',
            'full_system_cost_known': False, 'monetary_cost': None, 'energy_joules': None,
            'result_present': (OUTPUT / 'RESULT.json').is_file(), 'failure_present': (OUTPUT / 'FAILED.json').is_file(),
            'stdout_sha256': digest(OWNED / 'STDOUT.txt'), 'stderr_sha256': digest(OWNED / 'STDERR.txt'),
        }
        write(OWNED / 'EXIT.json', receipt)
        print(json.dumps(receipt), flush=True)
        raise SystemExit(code if code >= 0 else 1)


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        if not isinstance(error, SystemExit) and OWNED.is_dir():
            write(OWNED / 'WRAPPER_FAILED.json', {'error_type': type(error).__name__, 'error': str(error), 'automatic_retry': False, 'cost_complete': False})
        raise
