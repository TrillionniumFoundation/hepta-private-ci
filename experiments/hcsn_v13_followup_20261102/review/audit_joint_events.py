"""Bound and summarize recorded training reset/admission events; no eval data."""

import argparse
import json
from pathlib import Path


def audit(run):
    plan = json.loads((run/"PLAN.json").read_text())
    roster = json.loads((run/"CANDIDATES.json").read_text())["models"]
    checks, failures, rows = 0, [], []
    bound = plan["protocol"]["batch_size"] * 6 * 8
    for item in roster:
        records = json.loads((run/item["directory"]/"TRAIN.json").read_text())["training"]
        total = {"reset_cell_events": 0, "restoration_cell_events": 0}
        for row in records:
            for name in total:
                value = row[name]
                checks += 1
                if type(value) is not int or not 0 <= value <= bound:
                    failures.append("noninteger or out-of-bounds event count: " + item["directory"])
                if item["family"] in ("gru", "ssm", "history"):
                    checks += 1
                    if value != 0:
                        failures.append("ordinary non-reset family reports financial reset events")
                total[name] += value
        rows.append({"task": item["task"], "family": item["family"], "seed": item["seed"], **total})
    return {"checks": checks, "all_checks_passed": not failures, "failed_examples": failures,
            "fits": len(rows), "rows": rows,
            "scope": "Actual recorded source-tick reset/restoration counts, not independently re-executed events, continuous first passage or proof of benefit"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.run)
    with args.out.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}))
    raise SystemExit(0 if result["all_checks_passed"] else 1)
