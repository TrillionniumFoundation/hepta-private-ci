"""Small analytic/synthetic controls, with calibration work explicitly counted."""

from collections import Counter
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
from reference import verify
from solver import fit


def main(target):
    started, cpu = time.monotonic(), time.process_time()
    counts, cases = Counter(), []

    def observe(event):
        counts[event["event"]] += 1

    def run(z, y):
        return fit(z, y, observe=observe)

    def check(z, y, value):
        return verify(z, y, value, observe=observe)

    def reject(name, operation):
        try:
            operation()
        except (ValueError, FloatingPointError) as error:
            cases.append({"case": name, "rejected": True, "error": str(error)})
        else:
            raise ValueError("negative control accepted: " + name)

    flat = np.tile(np.arange(10, dtype=np.float64)[:, None], (1, 11))
    labels = np.arange(10, dtype=np.int64)
    value = run(flat, labels); check(flat, labels, value)
    if value["beta"] != 1. or value["outcome"] != "FLAT":
        raise ValueError("flat objective rule")
    cases.append({"case": "exact_per_row_flat_exception", "passed": True})
    logits = np.zeros((10, 11), dtype=np.float64); logits[:, 0] = 1.
    good = np.zeros(10, dtype=np.int64)
    upper = run(logits, good); check(logits, good, upper)
    if upper["beta"] != 100.:
        raise ValueError("upper boundary")
    cases.append({"case": "upper_KKT_boundary", "passed": True})
    bad = np.ones(10, dtype=np.int64)
    lower = run(logits, bad); check(logits, bad, lower)
    if lower["beta"] != .01:
        raise ValueError("lower boundary")
    cases.append({"case": "lower_KKT_boundary", "passed": True})
    mixed = np.array([0] * 8 + [1] * 2, dtype=np.int64)
    interior = run(logits, mixed); check(logits, mixed, interior)
    if abs(interior["beta"] - math.log(40)) > 4e-12 or interior["outcome"] != "INTERIOR":
        raise ValueError("known analytic beta=log(40)")
    cases.append({"case": "interior_known_analytic_optimum", "passed": True})
    shifted = logits + np.arange(10, dtype=np.float64)[:, None] * 100.
    shifted_value = run(shifted, mixed); check(shifted, mixed, shifted_value)
    if shifted_value["beta"] != interior["beta"] or shifted_value["final"] != interior["final"]:
        raise ValueError("per-row additive centering invariance")
    cases.append({"case": "stable_per_row_shift_invariance", "passed": True})
    reject("nonfinite_logits", lambda: run(np.full((10, 11), np.nan), mixed))
    reject("empty_rows", lambda: run(logits[:0], mixed[:0]))
    reject("floating_labels", lambda: run(logits, mixed.astype(np.float64)))
    reject("boolean_labels", lambda: run(logits, mixed.astype(bool)))
    reject("out_of_range_labels", lambda: run(logits, np.full(10, 11, dtype=np.int64)))
    reject("wrong_class_count", lambda: run(logits[:, :10], mixed))
    changed = copy.deepcopy(interior); changed["beta"] += .01
    reject("modified_final_beta", lambda: check(logits, mixed, changed))
    changed_trace = copy.deepcopy(interior); changed_trace["trace"][0]["move"] = "lower"
    reject("modified_bisection_move", lambda: check(logits, mixed, changed_trace))
    changed_nll = copy.deepcopy(interior); changed_nll["final"]["nll"] += .001
    reject("modified_recorded_NLL", lambda: check(logits, mixed, changed_nll))
    root = Path(__file__).resolve().parent
    receipt = {"schema": "D-temperature-synthetic-controls-v1", "passed": len(cases), "cases": cases,
               "synthetic_work_counts": dict(counts), "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in [root / "solver.py", root / "reference.py", root / "controls.py"]},
               "body_wall_seconds": time.monotonic() - started, "body_cpu_seconds": time.process_time() - cpu,
               "cost_scope": "Synthetic control main body; imports and outer Python lifetime are not included.",
               "production_D_logits_read": False, "E_payload_or_labels_accessed": False,
               "neural_model_forward_backward_calls": 0, "neural_optimizer_operations": 0}
    with target.open("x") as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2, allow_nan=False); stream.write("\n")
    print(json.dumps({"passed": len(cases), "synthetic_work_counts": dict(counts)}))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
