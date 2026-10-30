"""Exploratory write/address diagnosis on already declared long-sequence data."""
import json
from pathlib import Path
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from third.memory.reference import closed_write
from third.memory.execution import atomic_json
from task_flow_20261030.memory.data import make_suite
from task_flow_20261030.memory.freeze import verify, sha


def main():
    verify()
    result = json.loads((HERE / "results.json").read_text())
    plan = json.loads((HERE / "diagnostic_plan.json").read_text())
    if not result["complete"]:
        raise RuntimeError("Diagnose only after complete matrix; never alter selection")
    start, cpu = time.perf_counter(), time.process_time()
    rows = []
    for row in result["runs"]:
        _, suite, _ = make_suite(row["task"], row["seed"], result["protocol"])
        data = suite["test512"]
        x, dt = data["x"][:64], data["dt"][:64]
        p = dict(np.load(HERE / row["checkpoint"]))
        u = np.concatenate([x, np.log1p(dt)[..., None]], axis=-1)
        keys = np.tanh(u @ p["key"] + p["key_bias"]) / np.float32(4.)
        query = keys[:, -1]
        write = closed_write(u @ p["write"] + p["write_bias"])[..., 0]
        # Generator markers are used for analysis only, never for model routing.
        markers = (4, 5) if row["task"] == "memory" else (12, 13)
        filler = ~np.any(x[:, :, list(markers)] != 0, axis=2)
        dot = np.einsum("btk,bk->bt", keys, query)
        norms = np.linalg.norm(keys, axis=2) * np.linalg.norm(query, axis=1)[:, None]
        cosines = dot / np.maximum(norms, 1e-12)
        exposure = write * dot ** 2 / (1e-4 + np.sum(keys ** 2, axis=2))
        rows.append(dict(run_id=row["run_id"], subset_size=64, split="test512",
            filler_write_mean=float(write[filler].mean()),
            filler_write_maximum=float(write[filler].max()),
            exact_zero_filler_write_fraction=float((write[filler] == 0).mean()),
            examples_all_filler_writes_zero=int(np.all((write == 0) | ~filler, axis=1).sum()),
            mean_absolute_query_filler_cosine=float(np.abs(cosines[filler]).mean()),
            cumulative_write_query_exposure_mean=float((exposure * filler).sum(1).mean()),
            test512_accuracy=row["metrics"]["test512"]["accuracy"]))
    output = dict(exploratory=True, plan=plan, rows=rows,
                  source_sha256=sha(__file__), results_sha256=sha(HERE / "results.json"),
                  cpu_seconds=time.process_time() - cpu, wall_seconds=time.perf_counter() - start,
                  limits="Exposed task/seed data. Exposure is an address/write diagnostic, not an exact error bound or proof of a unique failure cause. No model, gate, checkpoint or protocol changes.")
    atomic_json(HERE / "diagnosis.json", output)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
