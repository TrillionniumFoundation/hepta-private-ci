"""Standard-library replay of risk qualification and all reported contrasts."""

import argparse
import hashlib
import json
import math
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(output):
    plan = json.loads((output/"PLAN.json").read_text())
    complete = json.loads((output/"EXECUTION_COMPLETE.json").read_text())
    assert digest(output/"PLAN.json") == complete["plan_sha256"]
    assert digest(output/"runs.jsonl") == complete["runs_sha256"]
    assert digest(output/"stress.jsonl") == complete["stress_sha256"]
    rows = [json.loads(line) for line in (output/"runs.jsonl").read_text().splitlines()]
    stress = [json.loads(line) for line in (output/"stress.jsonl").read_text().splitlines()]
    checks, modes = 3, {}
    fixed_pairs = (("old_zero", "reserve_fixed_old_zero"),
                   ("reserve_full", "old_zero_fixed_reserve"), ("reserve_full", "reserve_zero"))
    for mode in ("logical", "real"):
        worlds = [w for w in plan["logical_worlds"] if mode == "logical" or w["id"] in plan["real_world_ids"]]
        selected = [r for r in rows if r["clock_mode"] == mode]
        indexed = {(r["world_id"], r["arm"]): r for r in selected}
        assert len(indexed) == len(selected) == len(worlds)*len(plan["arms"])
        assert set(indexed) == {(w["id"], arm) for w in worlds for arm in plan["arms"]}
        means = dict.fromkeys(plan["arms"], 0.)
        counts = {arm: {"runs": 0, "requests": 0, "service_timeouts": 0,
                       "output_deadline_misses": 0, "correct": 0, "budget_overruns": 0}
                  for arm in plan["arms"]}
        for world in worlds:
            weight = world["weight"] if mode == "logical" else 1/len(worlds)
            for arm in plan["arms"]:
                row = indexed[world["id"], arm]
                receipt = row["receipt"]
                late = receipt["output_elapsed_seconds"] > plan["hard_deadline"]
                assert receipt["timely_output"] == (not late)
                assert receipt["deadline_seconds"] == plan["hard_deadline"]
                assert receipt["deadline_penalty"] == plan["costs"]["deadline_miss"]*late
                assert receipt["observation_fee"] == plan["costs"]["observation"]*receipt["requested_observations"]
                assert receipt["latency_fee"] == plan["costs"]["elapsed_second"]*receipt["output_elapsed_seconds"]
                assert row["flushed_output"] == receipt["output"]
                correct = int(receipt["output"]["predicted_class"] == world["target"])
                assert correct == row["correct"]
                utility = correct-receipt["observation_fee"]-receipt["latency_fee"]-receipt["deadline_penalty"]
                assert math.isclose(utility, row["net_utility"], abs_tol=1e-12)
                assert receipt["post_drain_elapsed_seconds"] >= receipt["output_elapsed_seconds"]
                timed_out = any(e["status"] == "timed_out" for e in receipt["events"])
                if timed_out:
                    assert "READ:video:1" not in receipt["output"]["accepted_event_ids"]
                    assert row["drains"] == 1
                    assert receipt["late_drains"][0]["start"] >= receipt["output_elapsed_seconds"]
                if row["contract"] == "reserve":
                    reserve = sum(plan["finalization_budget"].values())
                    assert math.isclose(receipt["service_deadline_seconds"], plan["hard_deadline"]-reserve)
                    assert receipt["finalization"]["budget_satisfied"]
                    assert not late
                    for record in row["public_risk_forecasts"]:
                        assert record["service_timeout_probability"] == .5
                        assert record["output_deadline_miss_probability_before_intervention"] == 0.
                        assert record["output_deadline_miss_probability_used"] == 0.
                means[arm] += weight*utility
                counts[arm]["runs"] += 1
                counts[arm]["requests"] += receipt["requested_observations"]
                counts[arm]["service_timeouts"] += int(timed_out)
                counts[arm]["output_deadline_misses"] += int(late)
                counts[arm]["correct"] += correct
                counts[arm]["budget_overruns"] += int(not receipt.get("finalization", {}).get("budget_satisfied", True))
                checks += 15
            for left, right in fixed_pairs:
                a, b = indexed[world["id"], left]["receipt"], indexed[world["id"], right]["receipt"]
                assert a["output"]["probabilities"] == b["output"]["probabilities"]
                assert a["requested_observations"] == b["requested_observations"]
                assert a["observation_fee"] == b["observation_fee"]
                checks += 3
            a, b = indexed[world["id"], "reserve_full"]["receipt"], indexed[world["id"], "reserve_zero"]["receipt"]
            assert [e["action"] for e in a["events"]] == [e["action"] for e in b["events"]]
            checks += 1
        modes[mode] = {"worlds": len(worlds), "runs": len(selected), "mean_net_utility": means,
            "counts": counts, "reserve_full_minus_reserve_zero": means["reserve_full"]-means["reserve_zero"],
            "reserve_fixed_old_zero_minus_old_zero": means["reserve_fixed_old_zero"]-means["old_zero"],
            "reserve_full_minus_old_full": means["reserve_full"]-means["old_full"],
            "fixed_content_requests_and_observation_fees_equal": True}
    assert len(stress) == len(plan["stress_probes"])
    for row in stress:
        receipt = row["receipt"]
        assert not receipt["finalization"]["budget_satisfied"]
        assert not receipt["timely_output"]
        assert receipt["deadline_penalty"] == plan["costs"]["deadline_miss"]
        assert "READ:video:1" not in receipt["output"]["accepted_event_ids"]
        assert row["drains"] == 1
        checks += 5
    normal_reserve = [r for r in rows if r["clock_mode"] == "real" and r["contract"] == "reserve"]
    return {"schema": "hcsn-v10-risk-audit.v1", "checks": checks, "passed": True,
        "source_plan_sha256": digest(output/"PLAN.json"), "raw_sha256": digest(output/"runs.jsonl"),
        "modes": modes, "stress_outside_budget": [{"probe": r["probe"],
            "timely": r["receipt"]["timely_output"], "budget_satisfied": r["receipt"]["finalization"]["budget_satisfied"]}
            for r in stress],
        "qualification": {"registered_normal_actual_reserve_runs": len(normal_reserve),
            "registered_normal_actual_reserve_timely": all(r["receipt"]["timely_output"] for r in normal_reserve),
            "registered_normal_actual_finalization_budgets_met": all(r["receipt"]["finalization"]["budget_satisfied"] for r in normal_reserve),
            "scope": plan["scope"], "unbounded_head_sink_guarantee": False,
            "service_timeout_equals_output_miss": False, "real_AV_confirmation": False,
            "analytic_core_advantage": False}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = audit(args.output)
    with (args.output/"AUDIT_SUMMARY.json").open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps(result))
