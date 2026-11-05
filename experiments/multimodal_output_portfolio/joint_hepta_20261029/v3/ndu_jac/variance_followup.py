"""Fresh-stream exploratory EB follow-up; never replaces original evidence."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .paid_audit import PaidAudit, Plan
from .paid_study import ETA, TASKS, draw, predict, stream
from .variance_audit import VarianceAudit


def run(lock_file, output):
    frozen = json.loads(lock_file.read_text())
    sources = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
               for name in ("variance_audit.py", "variance_followup.py", "paid_audit.py", "paid_study.py")}
    protocol = {"schema": "ndu-jac.variance-followup.v1", "parent_lock_sha256":
        hashlib.sha256(lock_file.read_bytes()).hexdigest(), "frozen_source_sha256": sources,
        "status": "exploratory_followup_after_observing_Hoeffding_failure",
        "fresh_stream_phases": [30, 31], "bounds": ["hoeffding", "empirical_bernstein"],
        "comparisons": 72, "delta": 0.05, "refitting": False,
        "allocation": "same_frozen_MSE_allocation; no_ci_driven_search",
        "cost": "Same declared counter tariff including full setup; full physical economics not certified"}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".protocol.json").write_text(json.dumps(protocol, sort_keys=True)+"\n")
    start = time.perf_counter(), time.process_time()
    cells = list(frozen["plans"])
    for task in range(len(TASKS)):
        for seed in frozen["protocol"]["seeds"]:
            cells.append({"task": task, "seed": seed, "method_index": 3, "model": None,
                "allocation": {"m": 1024, "n": 0, "beta": 0., "setup": 0., "prediction_tariff": 0.}})
    rows = []
    for cell in cells:
        task, seed, j, model, a = (cell[k] for k in ("task", "seed", "method_index", "model", "allocation"))
        pair = draw(stream(task, seed, 30, j), a["m"], task)
        h = predict(model, pair[0]) if a["beta"] else np.zeros(a["m"])
        reset = predict(model, draw(stream(task, seed, 31, j), a["n"])) if a["n"] else np.array([])
        bound = model["support_abs_bound"] if model else 0.
        target = hashlib.sha256(json.dumps([protocol, cell], sort_keys=True).encode()).hexdigest()
        plan = Plan(target, ETA, (0., 1.), (-bound, bound), beta=a["beta"], comparisons=72,
                    budget=0.01024, fit_cost=a["setup"]*1e-5,
                    fit_ids=("fit_bank", "allocation_pilot"))
        methods = {}
        price = a["prediction_tariff"] if a["beta"] else 0.
        for name, implementation in (("hoeffding", PaidAudit), ("empirical_bernstein", VarianceAudit)):
            audit = implementation(plan)
            for i in range(a["m"]):
                audit.pair(f"p{i}", target, float(pair[1][i]), float(pair[2][i]), float(h[i]), (1+price)*1e-5)
            for i, value in enumerate(reset):
                audit.reset(f"r{i}", target, float(value), (0.02+price)*1e-5)
            methods[name] = audit.decide()
        rows.append({"task": TASKS[task], "seed": seed, "model": model["method"] if model else "direct",
            "allocation": a, "methods": methods,
            "raw": {"candidate": pair[1].tolist(), "baseline": pair[2].tolist(),
                    "predictor": h.tolist(), "resets": reset.tolist()}})
    result = {"protocol": protocol, "rows": rows,
        "fresh_paid_pairs": sum(r["allocation"]["m"] for r in rows),
        "fresh_resets": sum(r["allocation"]["n"] for r in rows),
        "wall_seconds": time.perf_counter()-start[0], "cpu_seconds": time.process_time()-start[1],
        "physical_reuse": "The two fixed bound methods use the same draws; draws counted once. No new fit/pilot calls.",
        "limits": "One new validation draw per frozen cell; neither a repeated power study nor an efficiency theorem."}
    output.write_text(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n")
    print(json.dumps({"cells": len(rows), "adopt": {name: sum(r["methods"][name]["decision"] == "adopt" for r in rows)
                                                    for name in protocol["bounds"]}}))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.lock, args.output)
