"""Independent scalar scoring of the saved real-V6 development predictions."""

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np


def audit(directory):
    result = json.loads((directory / "RESULTS.json").read_bytes())
    for name, expected in result["raw_file_sha256"].items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Recorded evidence changed: {name}")
    data = np.load(directory / "holdout_scoring.npz", allow_pickle=False)
    fit = np.load(directory / "fit_features.npz", allow_pickle=False)
    probabilities = np.load(directory / "sealed_predictions.npz", allow_pickle=False)
    if (len(data["targets"]) != 1000 or len(set(data["groups"])) != 500
            or len(set(fit["groups"])) != 2000 or set(data["groups"]) & set(fit["groups"])):
        raise ValueError("Actual source-group census or separation failed")
    errors, records = [], 0
    for view, view_name in enumerate(("clean", "shared_occlusion_public_sum")):
        rows = np.flatnonzero(data["views"] == view)
        if len(rows) != 500:
            raise ValueError("The registered complete view census was not retained")
        for name in probabilities.files:
            values, brier, correct = [], [], []
            bins = [[] for _ in range(10)]
            for i in rows:
                p, target = list(map(float, probabilities[name][i])), int(data["targets"][i])
                if len(p) != 100 or any(not math.isfinite(v) or v < 0 for v in p):
                    raise ValueError("Invalid recorded joint prediction")
                if not math.isclose(math.fsum(p), 1., rel_tol=0., abs_tol=1e-6) or p[target] <= 0:
                    raise ValueError("Invalid probability normalization or actual-target support")
                selected = max(range(100), key=lambda k: p[k])
                values.append(-math.log(p[target]))
                brier.append(math.fsum(v * v for v in p) - 2 * p[target] + 1)
                correct.append(float(selected == target))
                bins[min(9, int(p[selected] * 10))].append((p[selected], correct[-1]))
                if view:
                    public = int(data["features"][i, -11:-1].argmax())
                    if public != (target // 10 + target % 10) % 10:
                        raise ValueError("The declared public relation was not constructed correctly")
                    if name.endswith("_public_conditioned") and any(
                            p[t] != 0 for t in range(100) if (t // 10 + t % 10) % 10 != public):
                        raise ValueError("Strong baseline failed to enforce its public information")
            ece = math.fsum(abs(math.fsum(c - ok for c, ok in block)) for block in bins) / len(rows)
            computed = {"joint_nll": math.fsum(values) / len(rows),
                        "joint_brier": math.fsum(brier) / len(rows),
                        "joint_accuracy": math.fsum(correct) / len(rows), "selected_ECE_10bins": ece}
            errors.extend(abs(value - result["metrics"][view_name][name][metric]) for metric, value in computed.items())
            records += len(rows)
    if max(errors) > 1e-12:
        raise ValueError(f"Independent scalar scoring mismatch: {max(errors)}")
    return {"schema": "hepta.repair.real-v6-independent-scoring.v1", "status": "passed",
            "prediction_rows_reopened": records, "distinct_holdout_source_pairs": 500,
            "max_scalar_metric_difference": max(errors),
            "input_result_sha256": hashlib.sha256((directory / "RESULTS.json").read_bytes()).hexdigest(),
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "scope": "Saved-prediction scoring and byte/source-census audit, not new neural forwards or source qualification"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.run)
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2); stream.write("\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
