"""Check sealed state dictionaries and recompute scores from the recorded physical margins."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def check(directory, historical):
    with (directory / "weights.json").open() as source:
        seals = json.load(source)
    if len(seals) != 12:
        raise ValueError("Expected twelve sealed state dictionaries")
    for name, expected in seals.items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"State dictionary mismatch for {name}")
    fit = json.loads((directory / "fit.json").read_text())
    evaluated = json.loads((directory / "eval.json").read_text())
    prior = {str(r["seed"]): r for r in json.loads(historical.read_text())
             if r["mode"] == "eval" and r["method"] == "direct"}
    for seed, row in evaluated["seeds"].items():
        if seed not in prior or row["parent"] != prior[seed]["parent_sha256"] or row["parent"] != fit["seeds"][seed]["parent"]:
            raise ValueError(f"Parent mismatch for {seed}")
        spans = fit["seeds"][seed]["span"]["null_dimensions"]
        print(f"seed {seed}, admissible dimensions {spans}")
        for name in ("keep", "exact", "weak", "direct"):
            reports = []
            for split in ("dev", "test", "retain"):
                panel = row[name][split]
                margin = np.asarray(panel["margins"], dtype=np.float64)
                labels = np.asarray(panel["labels"])
                correct = int(np.sum((margin > 0) == labels))
                brier = np.mean((1 / (1 + np.exp(-margin)) - labels) ** 2)
                if correct != panel["correct"] or abs(brier - panel["brier"]) > 1e-6:
                    raise ValueError(f"Metrics mismatch for {seed}, {name}, {split}")
                original = np.asarray(row["keep"][split]["margins"])
                if abs(np.max(np.abs(margin-original)) - panel["max_abs_margin_shift"]) > 1e-6:
                    raise ValueError(f"Margin change mismatch for {seed}, {name}, {split}")
                if split in ("test", "retain") and name in ("keep", "direct"):
                    old = prior[seed][split]
                    if list(labels) != old["labels"] or panel["groups"] != old["groups"]:
                        raise ValueError(f"Different historical panel for {seed}, {name}, {split}")
                    field = "parent_margins" if name == "keep" else "margins"
                    if not np.allclose(margin, old[field], rtol=0, atol=2e-5):
                        raise ValueError(f"Historical physical output mismatch for {seed}, {name}, {split}")
                reports.append(f"{split} {correct}/{len(labels)}")
            print(name, ", ".join(reports))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("results", type=Path)
    p.add_argument("historical_readouts", type=Path)
    a = p.parse_args()
    check(a.results, a.historical_readouts)
