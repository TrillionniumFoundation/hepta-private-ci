"""One bounded synthetic test launch; never launches a real-data experiment."""
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
OUT = ROOT / 'synthetic_math_attempt001'
OUT.mkdir(exist_ok=False)
SOURCE_NAMES = ['test_math_controls.py', 'head_candidates.py', 'value_graph.py',
                'data_contract.py', 'run_math_qualification.py']


def identities():
    result = {}
    for name in SOURCE_NAMES:
        raw = (ROOT / name).read_bytes()
        result[name] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    return result


def restrict():
    os.setsid()
    os.sched_setaffinity(0, {7})
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))


before = identities()
env = os.environ.copy()
env.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
           VECLIB_MAXIMUM_THREADS='1', NUMEXPR_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1')
env['PYTHONPATH'] = str(ROOT.parents[1] / 'recovery_20261121/python_packages')
usage = resource.getrusage(resource.RUSAGE_CHILDREN)
wall, cpu = time.monotonic(), time.process_time()
status = 'COMPLETED'
with (OUT / 'stdout.txt').open('xb') as stdout, (OUT / 'stderr.txt').open('xb') as stderr:
    process = subprocess.Popen([sys.executable, '-m', 'unittest', '-v', 'test_math_controls'],
                               cwd=ROOT, env=env, preexec_fn=restrict,
                               stdout=stdout, stderr=stderr)
    try:
        code = process.wait(timeout=40)
    except subprocess.TimeoutExpired:
        status = 'WALL_LIMIT'
        os.killpg(process.pid, signal.SIGKILL)
        code = process.wait()
end = resource.getrusage(resource.RUSAGE_CHILDREN)
after = identities()
report = {'schema': 'hepta.value-synthetic-math-qualification.v1', 'status': status,
          'exit_code': code, 'synthetic_tests_declared': 6,
          'synthetic_conic_calls_declared': 1,
          'real_checkpoint_or_teacher_reads': 0, 'real_forwards': 0,
          'source_before': before, 'source_after': after, 'source_unchanged': before == after,
          'CPU_hard_cap': 20, 'wall_hard_cap': 40, 'CPU_affinity': [7],
          'child_CPU_seconds': end.ru_utime + end.ru_stime - usage.ru_utime - usage.ru_stime,
          'supervisor_CPU_until_receipt': time.process_time() - cpu,
          'wall_seconds': time.monotonic() - wall,
          'receipt_tail_CPU_not_metered': True, 'no_automatic_retry': True}
with (OUT / 'RESULT.json').open('x') as handle:
    json.dump(report, handle, indent=2, allow_nan=False)
    handle.write('\n')
print(json.dumps({k: v for k, v in report.items() if not k.startswith('source_')}, indent=2))
raise SystemExit(0 if code == 0 and before == after else 1)
