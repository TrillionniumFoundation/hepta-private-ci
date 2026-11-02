"""Retained-action sensitivity to the explicit output deadline penalty.

This changes scoring only. It does not rerun workers, reserve flush time,
reoptimize policies, or estimate outcomes under different actions.
"""

import argparse
import hashlib
import json
from pathlib import Path


def analyze(output):
    plan = json.loads((output / "PLAN.json").read_text())
    raw = (output / "runs.jsonl").read_bytes()
    rows = [json.loads(line) for line in raw.splitlines()]
    result = {"schema": "hcsn-v9-risk-scoring-sensitivity.v1",
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "scope": "post-freeze sensitivity; retained realized actions, not retraining or reoptimization",
        "interpretation": "Positive risk effect under the frozen contract can arise from waiting to hard deadline then flushing late. It is not evidence of general content or analytic-core advantage.",
        "flush_reserve": {"executed": False,
            "reason": "Reserving flush time changes the execution protocol; it requires a separate registered actual run."},
        "modes": {}}
    for mode in ("logical", "real"):
        indexed = {(r["world_id"], r["arm"]): r for r in rows if r["clock_mode"] == mode}
        worlds = [w for w in plan["logical_worlds"] if (w["id"], "full") in indexed]
        grid = []
        for deadline_weight in (0., .25, .5, 1.):
            means = {}
            for arm in plan["arms"]:
                values = []
                for world in worlds:
                    row = indexed[world["id"], arm]
                    receipt = row["receipt"]
                    late = receipt["output_elapsed_seconds"] > plan["deadline"]
                    utility = row["correct"] - receipt["observation_fee"] - receipt["latency_fee"] - deadline_weight * late
                    weight = world["weight"] if mode == "logical" else 1 / len(worlds)
                    values.append(weight * utility)
                means[arm] = sum(values)
            grid.append({"deadline_penalty_per_miss": deadline_weight, "mean_net_utility": means,
                         "full_minus_zero": means["full"] - means["zero"]})
        result["modes"][mode] = {"worlds": len(worlds), "retained_actions_scoring_grid": grid}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = analyze(args.output)
    with (args.output / "SENSITIVITY.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result))
