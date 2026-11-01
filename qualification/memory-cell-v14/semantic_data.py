"""New authored holdout for skill-language reuse; V13 train/calibration only.

The fixed executor is deliberately shared. This tests selecting and composing
known skills, not learning their algorithms or discovering an unsegmented plan.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
V13 = HERE.parent / "memory-cell-v13"
spec = importlib.util.spec_from_file_location("semantic_shared_tasks", V13 / "tasks.py")
TASKS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TASKS)
SKILLS = TASKS.SKILLS
SEEDS = [17, 29, 43]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def training_data():
    root = V13 / "evidence" / "inputs"
    return {split: json.loads((root / f"{split}_rows.json").read_text()) for split in ("train", "calibration")}


def new_holdout():
    return json.loads((HERE / "semantic_holdout.json").read_text())


def manifest():
    original = training_data()
    held = new_holdout()
    return {"train_sha256": sha(original["train"]), "calibration_sha256": sha(original["calibration"]),
            "holdout_sha256": sha(held), "shared_executor_file_sha256": hashlib.sha256((V13 / "tasks.py").read_bytes()).hexdigest(),
            "train_rows": len(original["train"]), "calibration_rows": len(original["calibration"]),
            "holdout_rows": len(held["rows"]), "compositions": len(held["compositions"])}


def evaluate(rows, predictions):
    outcomes = [TASKS.score_prediction(row, int(label)) for row, label in zip(rows, predictions)]
    return {"task_success": sum(x["correct"] for x in outcomes) / len(rows),
            "label_accuracy": sum(x["label_correct"] for x in outcomes) / len(rows),
            "count": len(rows), "outcomes": outcomes,
            "predictions": [int(x) for x in predictions]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    args.manifest.write_text(json.dumps(manifest(), indent=2) + "\n")
