"""Bound one metadata-only test child; preserve complete wait4 and raw logs."""
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source'
LIMIT, MEMORY = 30., 256 * 1024**2
before = json.loads((ROOT / 'SOURCE-BEFORE.json').read_bytes())['files']
for path in SOURCE.rglob('*.py'):
    compile(path.read_bytes(), str(path), 'exec')  # Syntax only; never import the renderer or supervisor.
def restrict():
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY, MEMORY))
command = [sys.executable, '-B', '-m', 'unittest', 'test_native155', '-v']
start = time.monotonic()
with (ROOT / 'stdout').open('xb') as out, (ROOT / 'stderr').open('xb') as err:
    child = subprocess.Popen(command, cwd=SOURCE, stdout=out, stderr=err, start_new_session=True,
                             preexec_fn=restrict, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    timed_out = False
    while True:
        pid, status, usage = os.wait4(child.pid, os.WNOHANG)
        if pid:
            break
        if time.monotonic() - start >= LIMIT:
            timed_out = True
            os.killpg(child.pid, signal.SIGKILL)
            pid, status, usage = os.wait4(child.pid, 0)
            break
        time.sleep(.005)
end = time.monotonic()
child.returncode = os.waitstatus_to_exitcode(status)
after = {str(p.relative_to(SOURCE)): {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
         for p in sorted(SOURCE.rglob('*')) if p.is_file()}
receipt = {'schema': 'renderer-native155-software-validation-v1', 'argv': command,
           'returncode': child.returncode, 'timed_out': timed_out, 'complete_child_wall_seconds': end-start,
           'complete_wait4_child_CPU_seconds': usage.ru_utime+usage.ru_stime, 'complete_wait4_peak_RSS_bytes': usage.ru_maxrss*1024,
           'source_before': before, 'source_after': after, 'source_unchanged': before == after,
           'limits': {'whole_child_wall_seconds': LIMIT, 'address_space_bytes': MEMORY, 'worker': 1, 'retry': False},
           'compile_only_preflight': True, 'renderer_imported': False, 'actual_model_or_C2_or_E_access': False,
           'gate_test_scope': 'Six native-only synthetic JSON tests with nine rejection variants and two positive cases; full renderer/archive pipeline not exercised.',
           'supervisor_setup_compile_packaging_and_exit_cost': 'Not included in complete child account; not separately metered.'}
(ROOT / 'RESULT.json').write_text(json.dumps(receipt, indent=2)+'\n')
print(json.dumps({k:receipt[k] for k in ('returncode','complete_child_wall_seconds','complete_wait4_child_CPU_seconds','complete_wait4_peak_RSS_bytes','source_unchanged')}))
raise SystemExit(0 if child.returncode==0 and not timed_out and before==after and end-start<=LIMIT and usage.ru_maxrss*1024<=MEMORY else 2)
