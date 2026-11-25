"""Summarize the complete immutable train/dev pilot, including censored rows."""
import argparse
import json
from pathlib import Path
from statistics import mean
import hashlib


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(root, out):
    root, out = Path(root), Path(out)
    if out.exists():
        raise FileExistsError("Pilot summary already exists")
    protocol = json.loads((root / "PILOT_PROTOCOL.json").read_text())
    terminals = json.loads((root / "pilot_v1/TRAINING_TERMINALS.json").read_text())
    rows = []
    for bound in terminals["rows"]:
        path = root / "pilot_v1" / bound["case"]
        if sha(path / "RESULT.json") != bound["result_sha256"]:
            raise ValueError("Pilot terminal changed")
        row = json.loads((path / "RESULT.json").read_text())
        history = json.loads((path / "HISTORY.json").read_text())
        if sha(path / "HISTORY.json") != row["history_sha256"]:
            raise ValueError("Pilot history changed")
        rows.append({"case": row["case"], "status": row["status"], "updates": row["updates"],
                     "selected_step": row["selected_step"], "initial_dev": row["baseline_heads"]["standardized"]["dev"],
                     "selected_dev": row["selected_dev"], "cost": row["cost"],
                     "curves": history, "result_sha256": sha(path / "RESULT.json")})
    scores = {lr: mean(row["selected_dev"]["cross_entropy"] for row in rows
                       if row["case"]["physical_lr"] == lr) for lr in (1e-5, 1e-4)}
    result = {"scope": "train/dev-only global learning-rate and budget decision",
              "protocol_sha256": sha(root / "PILOT_PROTOCOL.json"), "rows": rows,
              "mean_selected_dev_CE_by_learning_rate": scores,
              "chosen_physical_lr": min(scores, key=scores.get),
              "max_selected_step": max(row["selected_step"] for row in rows),
              "completed_updates_rows": sum(row["status"] == "COMPLETED_MAX_UPDATES" for row in rows),
              "censored_rows": sum(row["status"] == "CENSORED_BUDGET" for row in rows),
              "formal_budget_decision": "96 updates retained; increase CPU/wall caps so N64 can complete; every tested optimum at or before step64",
              "test_created": False, "source_sha256": sha(__file__)}
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: result[key] for key in ("chosen_physical_lr", "max_selected_step",
                                                  "completed_updates_rows", "censored_rows")}, sort_keys=True))
    print(json.dumps({"path": str(out), "sha256": sha(out)}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    main(args.root, args.out)
