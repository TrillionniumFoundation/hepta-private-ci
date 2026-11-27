"""New v2 preparation: compile source text only, preserving complete child cost."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

base = Path(__file__).resolve().parent
output = base / 'compile-check'
output.mkdir(exist_ok=False)
paths = [base / 'input_contract.py', base / 'render_c2_resources.py']


def identities():
    return {p.name: {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths}


before = identities()
code = 'import pathlib,sys\nfor arg in sys.argv[1:]:\n p=pathlib.Path(arg);compile(p.read_bytes(),str(p),"exec");print("Compiled text only:",p.name)\n'
argv = [sys.executable, '-B', '-c', code, *(str(p) for p in paths)]
with (output / 'stdout').open('xb') as stdout, (output / 'stderr').open('xb') as stderr:
    started = time.perf_counter()
    process = subprocess.Popen(argv, stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL)
    _, status, usage = os.wait4(process.pid, 0)
    elapsed = time.perf_counter() - started
    process.returncode = os.waitstatus_to_exitcode(status)
after = identities()
result = {'schema': 'c2-resource-renderer-v2-new-compile-check-v1', 'returncode': process.returncode,
          'source_before': before, 'source_after': after, 'source_unchanged': before == after,
          'whole_compile_child_wall_seconds': elapsed, 'wait4_compile_child_CPU_seconds': usage.ru_utime + usage.ru_stime,
          'wait4_peak_RSS_bytes': usage.ru_maxrss * 1024, 'argv': argv,
          'cost_scope': 'Complete new compile child Popen-to-wait4; outer script hashing/receipt/exit excluded.',
          'replaces_old_v1_receipt': False, 'behavioral_tests': 0, 'matplotlib_imports': 0,
          'actual_C2_inputs_read': False, 'model_calls': 0, 'E_access': False, 'render_calls': 0}
(output / 'RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
raise SystemExit(0 if process.returncode == 0 and before == after else 2)
