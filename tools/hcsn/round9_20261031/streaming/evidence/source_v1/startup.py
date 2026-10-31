"""Additive cold-process accounting; does not change the frozen quality gates."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def worker(implementation, arm):
    import numpy as np

    history = np.array([[[.1, .2, .5], [-.2, .3, .7]]])
    lengths = np.array([2])
    query = np.array([[1., .3, .8, .1, .4]])
    parameters = None
    if arm == "calibrated_analytic_17":
        path = HERE.parents[1] / "round8_20261031/state_task/evidence/models/analytic_filter_17.json"
        parameters = json.loads(path.read_text())["state"]
    if implementation == "r8_torch_history":
        import torch
        from tools.hcsn.round8_20261031.state_task.models import RiskModel, load_state

        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        model = (RiskModel("fixed_ordinary_filter").eval() if parameters is None
                 else load_state("analytic_filter", parameters))
        with torch.no_grad():
            risk = model(torch.tensor(history, dtype=torch.float32), torch.tensor(lengths),
                         torch.tensor(query, dtype=torch.float32)).numpy()
    else:
        from tools.hcsn.round9_20261031.streaming.filter import StreamingFilter

        state = StreamingFilter(1, parameters)
        state.update(history, lengths)
        risk = state.predict(query)
    print(json.dumps({"risk": risk.tolist(), "protect": (risk > query[:, 4]).tolist()}))


def measure():
    output = HERE / "evidence/startup.json"
    if output.exists():
        raise FileExistsError("refusing to overwrite startup evidence")
    registration = {"source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "written_before_measurement": True, "rounds": 3,
                    "scope": "Fresh process, warm filesystem caches; includes imports, model load, inference, JSON, process launch and exit. Shared host.",
                    "relationship": "Additive cost accounting after the original frozen implementation audit; no retuning or changed quality gate."}
    (HERE / "evidence/STARTUP_REGISTERED.json").write_text(json.dumps(registration, indent=2) + "\n")
    env = os.environ | {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    rows = []
    implementations = ["r8_torch_history", "r9_numpy_sufficient_state"]
    for arm in ("calibrated_analytic_17", "ordinary_exact"):
        for repeat in range(3):
            for implementation in implementations[::1 if repeat % 2 == 0 else -1]:
                before = resource.getrusage(resource.RUSAGE_CHILDREN)
                start = time.perf_counter()
                result = subprocess.run([sys.executable, "-m", "tools.hcsn.round9_20261031.streaming.startup",
                                         "--worker", implementation, "--arm", arm], cwd=ROOT, env=env,
                                        text=True, capture_output=True, check=True)
                wall = time.perf_counter() - start
                after = resource.getrusage(resource.RUSAGE_CHILDREN)
                rows.append({"arm": arm, "implementation": implementation, "round": repeat,
                             "wall_seconds": wall,
                             "child_cpu_seconds": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
                             "output": json.loads(result.stdout)})
    grouped = {}
    for row in rows:
        grouped.setdefault((row["arm"], row["implementation"]), []).append(row)
    summary = [{"arm": k[0], "implementation": k[1],
                "median_cpu_seconds": statistics.median(r["child_cpu_seconds"] for r in values),
                "median_wall_seconds": statistics.median(r["wall_seconds"] for r in values)}
               for k, values in grouped.items()]
    output.write_text(json.dumps({"registration": registration, "raw": rows, "summary": summary,
                                  "energy_joules": None}, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=["r8_torch_history", "r9_numpy_sufficient_state"])
    parser.add_argument("--arm", choices=["calibrated_analytic_17", "ordinary_exact"])
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.arm)
    else:
        measure()
