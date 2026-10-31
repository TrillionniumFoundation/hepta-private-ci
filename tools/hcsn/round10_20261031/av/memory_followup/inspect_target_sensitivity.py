"""Describe target removal sensitivity without conflating accuracy with information."""
import hashlib
import json
from pathlib import Path

import numpy as np


def main():
    root = Path(__file__).resolve().parent
    protocol = json.loads((root / "PROTOCOL.json").read_text())
    rows = []
    for model in protocol["models"]:
        changed, maximum, absolute, source = 0, 0.0, [], {}
        for seed in protocol["seeds"]:
            path = root / "results" / f"{model}_{seed}" / "predictions.npz"
            source[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
            with np.load(path, allow_pickle=False) as arrays:
                original = arrays["delay96"]
                target_zero = arrays["delay96_target_zero"]
                difference = np.abs(original - target_zero)
                changed += int(np.sum(original.argmax(1) != target_zero.argmax(1)))
                maximum = max(maximum, float(difference.max()))
                absolute.append(float(difference.mean()))
        rows.append({"model": model, "changed_class_predictions_out_of_576": changed,
                     "maximum_absolute_logit_difference": maximum,
                     "mean_absolute_logit_difference": float(np.mean(absolute)),
                     "predictions_sha256": source})
    output = {
        "analysis_status": "Posthoc descriptive examination of already saved predictions; no training, reselection or gate changes",
        "reason": "Equal top-1 accuracy can hide prediction or logit changes, so it cannot prove exactly zero retained information",
        "conditions": ["delay96", "delay96_target_zero"],
        "interpretation": "Measure response to removing target information; no positive semantic retention claim and no impossibility theorem",
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "rows": rows,
    }
    (root / "TARGET_SENSITIVITY.json").write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"models": len(rows), "analytic_changed_predictions": rows[2]["changed_class_predictions_out_of_576"]}))


if __name__ == "__main__":
    main()
