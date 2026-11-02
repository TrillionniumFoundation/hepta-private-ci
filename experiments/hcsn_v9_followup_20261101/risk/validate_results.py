"""Recompute risk results using only retained JSON and the standard library."""

import argparse
import hashlib
import json
import math
from pathlib import Path


def validate(output):
    plan = json.loads((output / "PLAN.json").read_text())
    summary = json.loads((output / "SUMMARY.json").read_text())
    raw = (output / "runs.jsonl").read_bytes()
    rows = [json.loads(line) for line in raw.splitlines()]
    assert hashlib.sha256(raw).hexdigest() == summary["raw_sha256"]
    checks = 1
    for mode in ("logical", "real"):
        worlds = [w for w in plan["logical_worlds"]
                  if mode == "logical" or w["id"] in plan["real_world_ids"]]
        indexed = {(r["world_id"], r["arm"]): r for r in rows if r["clock_mode"] == mode}
        assert len(indexed) == len(worlds) * len(plan["arms"])
        expected = {(w["id"], arm) for w in worlds for arm in plan["arms"]}
        assert set(indexed) == expected
        means = dict.fromkeys(plan["arms"], 0.)
        for world in worlds:
            weight = world["weight"] if mode == "logical" else 1 / len(worlds)
            for arm in plan["arms"]:
                row = indexed[world["id"], arm]
                receipt = row["receipt"]
                assert receipt["observation_fee"] == receipt["requested_observations"] * plan["costs"]["observation"]
                assert receipt["latency_fee"] == receipt["output_elapsed_seconds"] * plan["costs"]["elapsed_second"]
                penalty = plan["costs"]["deadline_miss"] * (receipt["output_elapsed_seconds"] > plan["deadline"])
                assert penalty == receipt["deadline_penalty"] == row["scored_deadline_penalty"]
                assert row["correct"] == int(receipt["output"]["predicted_class"] == world["target"])
                utility = row["correct"] - receipt["observation_fee"] - receipt["latency_fee"] - penalty
                assert math.isclose(utility, row["net_utility"], abs_tol=1e-12)
                assert row["flushed_output"] == receipt["output"]
                assert receipt["post_drain_elapsed_seconds"] >= receipt["output_elapsed_seconds"]
                if any(e["status"] == "timed_out" for e in receipt["events"]):
                    assert "READ:video:1" not in receipt["output"]["accepted_event_ids"]
                    assert row["drained_payloads"] == 1
                means[arm] += weight * utility
                checks += 10
            for a, b in (("full", "zero_on_full"), ("zero", "full_on_zero")):
                left, right = indexed[world["id"], a], indexed[world["id"], b]
                assert left["receipt"]["output"]["probabilities"] == right["receipt"]["output"]["probabilities"]
                assert left["receipt"]["requested_observations"] == right["receipt"]["requested_observations"]
                checks += 2
        for arm, mean in means.items():
            assert math.isclose(mean, summary["modes"][mode]["mean_net_utility"][arm], abs_tol=1e-12)
            checks += 1
        assert math.isclose(means["full"] - means["zero"], summary["modes"][mode]["full_minus_zero"], abs_tol=1e-12)
        checks += 1
    return {"schema": "hcsn-v9-risk-json-audit.v1", "checks": checks,
            "runs": len(rows), "passed": True, "scope": "retained JSON recomputation; no AV or architecture acceptance"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.output), indent=2))
