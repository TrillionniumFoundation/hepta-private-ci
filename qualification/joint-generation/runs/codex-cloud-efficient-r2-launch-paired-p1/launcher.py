"""T8-style idle Python parent; only nested B samples, no NumPy import."""
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

base = Path(__file__).resolve().parent
root = base.parents[1]
sample = sys.argv[1]
if sample not in ("B1", "B2"):
    raise ValueError("nested fixed samples only")
env = os.environ.copy()
for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    env[key] = "1"
env["PYTHONDONTWRITEBYTECODE"] = "1"
command = ["python", str(base / "worker.py"), "execute", sample]
child = resource.getrusage(resource.RUSAGE_CHILDREN)
before = (time.process_time_ns(), time.perf_counter_ns(), child.ru_utime + child.ru_stime)
with (base / (sample + ".stdout-stderr.log")).open("x") as stream:
    result = subprocess.run(command, cwd=root, env=env, stdout=stream, stderr=subprocess.STDOUT)
child = resource.getrusage(resource.RUSAGE_CHILDREN)
receipt = {"command": command, "returncode": result.returncode, "parent_executable": sys.executable,
    "parent_environment": {key: os.environ.get(key) for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")},
    "parent_cpu_ns": time.process_time_ns() - before[0], "wall_ns": time.perf_counter_ns() - before[1],
    "children_cpu_ns": round((child.ru_utime + child.ru_stime - before[2]) * 1e9),
    "scope": "parent own CPU and waited child CPU separate; do not add child CPU again to worker totals"}
with (base / (sample + ".launcher.json")).open("x") as stream:
    json.dump(receipt, stream, indent=2, sort_keys=True); stream.write("\n")
print(json.dumps(receipt))
sys.exit(result.returncode)
