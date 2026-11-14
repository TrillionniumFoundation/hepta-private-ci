"""Run the immutable registered runtime protocol as an explicitly new measurement."""
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[3]
evidence = root / "research_evidence/hepta_stable_flow_20261029"
output = evidence / "inference_cost_replay_20261030"
logs = output / "replay_execution"
logs.mkdir(exist_ok=False)
command = [sys.executable, "-m", "experiments.call_put_stable_flow_appendix.runtime", "run", "--study", str(evidence / "formal_run001"), "--numerics", str(evidence / "trained_numerics_replay_20261030"), "--output", str(output), "--idle-cpu-attested"]
env = dict(os.environ, OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
start = {"schema": "hepta-runtime-replay-execution-v1", "command": command, "started_unix": time.time(), "purpose": "New clock measurements on identical frozen checkpoints; not recovery of missing original timing bytes", "is_original_execution": False, "other_task_scientific_compute_paused": True, "unrelated_host_activity_controlled": False, "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
(logs / "start.json").write_text(json.dumps(start, indent=2, sort_keys=True) + "\n")
tick = time.perf_counter()
before = resource.getrusage(resource.RUSAGE_CHILDREN)
with (logs / "stdout.log").open("xb") as out, (logs / "stderr.log").open("xb") as err:
    result = subprocess.run(command, cwd=root, env=env, stdout=out, stderr=err)
after = resource.getrusage(resource.RUSAGE_CHILDREN)
finish = {**start, "finished_unix": time.time(), "returncode": result.returncode, "wall_seconds": time.perf_counter() - tick, "child_total_cpu_seconds": (after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime), "peak_rss_bytes": after.ru_maxrss * 1024, "stdout_sha256": hashlib.sha256((logs / "stdout.log").read_bytes()).hexdigest(), "stderr_sha256": hashlib.sha256((logs / "stderr.log").read_bytes()).hexdigest()}
summary = output / "execution/summary.json"
if summary.is_file():
    finish["summary_sha256"] = hashlib.sha256(summary.read_bytes()).hexdigest()
(logs / "finish.json").write_text(json.dumps(finish, indent=2, sort_keys=True) + "\n")
print(json.dumps(finish))
raise SystemExit(result.returncode)
