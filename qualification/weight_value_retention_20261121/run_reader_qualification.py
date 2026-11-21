"""One additional synthetic reader qualification; no real-data execution."""
from pathlib import Path
import hashlib
import json
import os
import resource
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'synthetic_reader_attempt001'
OUT.mkdir(exist_ok=False)
NAMES = ['test_reader_controls.py', 'run_reader_qualification.py', 'verify_records.py',
         'evaluation_io.py', 'data_contract.py', 'value_graph.py', 'run_confirmation.py']


def identities():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in NAMES}


def restrict():
    os.setsid()
    os.sched_setaffinity(0, {7})
    resource.setrlimit(resource.RLIMIT_CPU, (17, 17))
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))


prior = json.loads((ROOT / 'synthetic_phase_attempt001/RESULT.json').read_text())
prior_cpu = prior['cumulative_recorded_CPU_seconds']
assert prior_cpu < 3.0, 'remaining cumulative qualification cap is not 17 CPU seconds'
env = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
    NUMEXPR_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1')
env['PYTHONPATH'] = str(ROOT.parents[1] / 'recovery_20261121/python_packages')
before = identities()
usage = resource.getrusage(resource.RUSAGE_CHILDREN)
wall, cpu = time.monotonic(), time.process_time()
timeout = False
with (OUT / 'stdout.txt').open('xb') as stdout, (OUT / 'stderr.txt').open('xb') as stderr:
    process = subprocess.Popen([sys.executable, '-m', 'unittest', '-v', 'test_reader_controls'],
        cwd=ROOT, env=env, preexec_fn=restrict, stdout=stdout, stderr=stderr)
    try:
        code = process.wait(timeout=32)
    except subprocess.TimeoutExpired:
        timeout = True
        os.killpg(process.pid, signal.SIGKILL)
        code = process.wait()
end = resource.getrusage(resource.RUSAGE_CHILDREN)
after = identities()
child_cpu = end.ru_utime + end.ru_stime - usage.ru_utime - usage.ru_stime
self_cpu = time.process_time() - cpu
report = dict(schema='hepta-value-synthetic-reader-qualification-v1',
    status='COMPLETED' if code == 0 and before == after and not timeout else 'FAILED',
    exit_code=code, wall_timeout=timeout, synthetic_tests_declared=4,
    real_checkpoint_or_teacher_reads=0, real_forwards=0, real_solver_calls=0,
    source_before=before, source_after=after, source_unchanged=before == after,
    prior_synthetic_CPU=prior_cpu, child_CPU_seconds=child_cpu,
    supervisor_CPU_until_receipt=self_cpu,
    cumulative_recorded_CPU_seconds=prior_cpu + child_cpu + self_cpu,
    cumulative_CPU_hard_cap=20, child_CPU_hard_cap=17, child_wall_hard_cap=32,
    wall_seconds=time.monotonic() - wall, no_automatic_retry=True,
    receipt_tail_CPU_not_metered=True)
with (OUT / 'RESULT.json').open('x') as stream:
    json.dump(report, stream, indent=2, allow_nan=False)
    stream.write('\n')
print(json.dumps({k: v for k, v in report.items() if not k.startswith('source_')}, indent=2))
sys.exit(0 if report['status'] == 'COMPLETED' else 1)
