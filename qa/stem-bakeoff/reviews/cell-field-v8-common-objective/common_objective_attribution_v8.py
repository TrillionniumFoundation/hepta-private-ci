"""Read-only supplemental arithmetic from already audited J32 outputs."""

import argparse
import hashlib
import json
from pathlib import Path
import time
import numpy as np


def compute(workspace, output):
    root, output = Path(workspace), Path(output)
    if output.exists():
        raise ValueError("new attribution output required")
    started = time.process_time_ns()
    audit_path = root / "pft-development-v8/common-objective-audit.json"
    audit = json.loads(audit_path.read_bytes())
    if audit["status"] != "PASS":
        raise ValueError("complete independent replay must pass first")
    fits = {}
    for row in audit["rows"]:
        fits.setdefault(row["fit"], {})[row["branch"]] = row
    parity, classifications, exceptions = [], [], []
    for fit, rows in fits.items():
        directory = root / "pft-common-objective-v8" / fit
        with np.load(directory / "full32_eight_actions/trajectory.npz", allow_pickle=False) as full, \
             np.load(directory / "field32_eight_actions/trajectory.npz", allow_pickle=False) as field, \
             np.load(directory / "reference.npz", allow_pickle=False) as reference:
            parity.append({"fit": fit, "full_field_state_max_abs": float(np.max(np.abs(full["states"]-field["states"]))),
                "full_field_loss_max_abs": float(np.max(np.abs(full["losses"]-field["losses"]))),
                "field_initial_max_abs": float(np.max(np.abs(reference["field_initial"])))})
        zero, one, eight = [rows[name]["J32"] for name in ("zero32", "full32_one_action", "full32_eight_actions")]
        if eight > zero+1e-12 or eight > one+1e-12:
            exceptions.append({"fit": fit, "full8_minus_zero": eight-zero, "full8_minus_full1": eight-one})
    for branch in list(next(iter(fits.values())))[1:]:
        pairs = [(variants[branch], variants["zero32"]) for variants in fits.values()]
        for model in ("full", "loss2"):
            truth = [int(a["J32"] < z["J32"]-1e-12) for a, z in pairs]
            predicted = [int(a["forecasts"][model]["predicted_J32"] < z["J32"]-1e-12) for a, z in pairs]
            classifications.append({"branch": branch, "model": model, "actual_improve": sum(truth),
                "predicted_improve": sum(predicted), "agreement": sum(a == b for a, b in zip(truth, predicted)),
                "comparisons": 24})
    result = {"schema": "hepta.common-terminal-attribution-supplement.v8",
        "audit_sha256": hashlib.sha256(audit_path.read_bytes()).hexdigest(), "parity": parity,
        "direction_classifications": classifications, "full8_true_objective_exceptions": exceptions,
        "new_optimizer_steps": 0, "selection_labels_accessed": False, "cpu_ns": time.process_time_ns()-started,
        "scope": "Read-only arithmetic on already audited trajectories; no new predictions or optimizations."}
    output.write_text(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output", required=True)
    compute(**vars(parser.parse_args()))
