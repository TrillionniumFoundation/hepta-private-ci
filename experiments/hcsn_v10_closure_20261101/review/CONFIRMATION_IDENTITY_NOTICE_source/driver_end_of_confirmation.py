"""Independent v10 raw evidence checks; imports no candidate implementation.

Run each formal audit through the economics stage meter. Development-only
scope is retained even when the numerical reconstruction succeeds.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rows(path):
    with Path(path).open() as stream:
        return [json.loads(line) for line in stream]


def close(a, b, tolerance=1e-10):
    if not np.allclose(a, b, atol=tolerance, rtol=tolerance):
        raise AssertionError(f"Independent numerical mismatch: {a!r}, {b!r}")


def risk(base):
    plan = read(base / "PLAN.json")
    for path, digest in plan["source_sha256"].items():
        assert sha(REPO / path) == digest
    worlds = {w["id"]: w for w in plan["logical_worlds"]}
    run_rows = rows(base / "runs.jsonl")
    stress_rows = rows(base / "stress.jsonl")
    costs = plan["costs"]
    indexed, metrics = {}, {}
    for row in run_rows + stress_rows:
        receipt = row["receipt"]
        world = worlds[row["world_id"]]
        hard = receipt["deadline_seconds"]
        flush = receipt["output_elapsed_seconds"]
        output_miss = flush > hard
        assert receipt["timely_output"] == (not output_miss)
        close(receipt["deadline_penalty"], costs["deadline_miss"] * output_miss)
        close(receipt["observation_fee"], costs["observation"] * receipt["requested_observations"])
        close(receipt["latency_fee"], costs["elapsed_second"] * flush)
        assert row["flushed_output"] == receipt["output"]
        close(row["net_utility"], row["correct"] - receipt["observation_fee"] - receipt["latency_fee"] - receipt["deadline_penalty"])
        accepted_ids = receipt["output"]["accepted_event_ids"]
        likelihood = np.ones(2)
        for name in ("audio", "video"):
            if "READ:" + name + ":1" in accepted_ids:
                accuracy = plan["head_accuracy"][name]
                likelihood *= [accuracy if label == world[name] else 1-accuracy for label in (0, 1)]
        probability = likelihood / likelihood.sum()
        close(probability, receipt["output"]["probabilities"])
        predicted = int(np.argmax(probability))
        assert receipt["output"]["predicted_class"] == predicted
        assert row["correct"] == int(predicted == world["target"])
        timeout = any(event["status"] == "timed_out" for event in receipt["events"])
        if timeout:
            assert "READ:video:1" not in accepted_ids
            assert receipt["late_drains"]
            assert all(drain["start"] >= flush for drain in receipt["late_drains"])
        if row["contract"] == "reserve":
            final = receipt["finalization"]
            close(receipt["service_deadline_seconds"], hard-final["reserve_seconds"])
            close(final["head_seconds"], final["head_completed_at"]-final["started_at"])
            close(final["serialization_seconds"], final["serialized_at"]-final["head_completed_at"])
            close(final["sink_seconds"], final["sink_completed_at"]-final["serialized_at"])
            budget = final["budget"]
            expected = (final["head_seconds"] <= budget["head_seconds"] and
                        final["serialization_seconds"] <= budget["serialization_seconds"] and
                        final["sink_seconds"] <= budget["sink_seconds"] and
                        final["started_at"] <= receipt["service_deadline_seconds"] + budget["guard_seconds"])
            assert expected == final["budget_satisfied"]
        for forecast in row["public_risk_forecasts"]:
            close(forecast["service_timeout_probability"], .5)
            close(forecast["output_deadline_miss_probability_before_intervention"], .5 if row["contract"] == "old" else 0.)
        for decision in receipt["decisions"]:
            if decision.get("mode") == "fixed":
                continue
            for candidate in decision["plans"]:
                expected_score = (candidate["correctness"] - costs["observation"] * candidate["expected_requested_reads"]
                                  - costs["elapsed_second"] * candidate["expected_seconds"]
                                  - costs["deadline_miss"] * candidate["deadline_miss_probability"])
                close(expected_score, candidate["score"])
        if "probe" not in row:
            key = row["clock_mode"], row["world_id"], row["arm"]
            assert key not in indexed
            indexed[key] = row
    for mode in ("logical", "real"):
        ids = [key for key in worlds if (mode, key, "reserve_full") in indexed]
        means = {}
        for arm in plan["arms"]:
            means[arm] = sum((worlds[key]["weight"] if mode == "logical" else 1/len(ids)) *
                              indexed[mode, key, arm]["net_utility"] for key in ids)
        for key in ids:
            full = indexed[mode, key, "reserve_full"]["receipt"]
            zero = indexed[mode, key, "reserve_zero"]["receipt"]
            assert full["output"]["probabilities"] == zero["output"]["probabilities"]
            assert full["requested_observations"] == zero["requested_observations"]
            fixed = indexed[mode, key, "reserve_fixed_old_zero"]["receipt"]
            old = indexed[mode, key, "old_zero"]["receipt"]
            assert fixed["output"]["probabilities"] == old["output"]["probabilities"]
            assert fixed["requested_observations"] == old["requested_observations"]
            close(fixed["observation_fee"], old["observation_fee"])
        metrics[mode] = {"worlds": len(ids), "mean_net_utility": means,
                         "reserve_full_minus_zero": means["reserve_full"]-means["reserve_zero"],
                         "reserve_minus_old_zero": means["reserve_full"]-means["old_zero"],
                         "fixed_action_reservation_minus_old_zero": means["reserve_fixed_old_zero"]-means["old_zero"],
                         "service_timeouts": sum(any(e["status"] == "timed_out" for e in indexed[mode,key,arm]["receipt"]["events"])
                                                 for key in ids for arm in plan["arms"]),
                         "reserve_output_misses": sum(not indexed[mode,key,arm]["receipt"]["timely_output"]
                                                       for key in ids for arm in plan["arms"] if arm.startswith("reserve"))}
    return {"scope": "Synthetic bounded-service fixture; timeout and output miss separately reconstructed",
            "runs_recomputed": len(run_rows), "stress_rows_recomputed": len(stress_rows), "modes": metrics,
            "raw_sha256": {"runs.jsonl": sha(base/"runs.jsonl"), "stress.jsonl": sha(base/"stress.jsonl")}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("study", choices=("risk", "joint_retrain", "persistent_renewal", "av_analytic", "frontend", "constant", "confirmation", "ci"))
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshot = args.output.with_name(args.output.stem+"_source")
    snapshot.mkdir(exist_ok=False)
    audit_sources = {}
    for path in sorted(Path(__file__).parent.glob("*.py")):
        (snapshot/path.name).write_bytes(path.read_bytes())
        audit_sources[path.name] = sha(path)
    if args.study == "joint_retrain":
        from .joint_reconstruction import audit
        result = audit(args.input)
    elif args.study == "persistent_renewal":
        from .renewal_reconstruction import audit
        result = audit(args.input)
    elif args.study == "av_analytic":
        from .av_reconstruction import audit
        result = audit(args.input)
    elif args.study == "frontend":
        from .frontend_reconstruction import audit
        result = audit(args.input)
    elif args.study == "constant":
        from .constant_reconstruction import audit
        result = audit(args.input)
    elif args.study == "confirmation":
        from .confirmation_reconstruction import audit
        result = audit(args.input)
    elif args.study == "ci":
        from .ci_reconstruction import audit
        result = audit(args.input)
    else:
        result = risk(args.input)
    report = {"schema": "hcsn-v10-independent-review.v1", "candidate_implementations_imported": False,
              "audit_source_sha256": sha(Path(__file__)), "audit_sources_snapshot": audit_sources,
              args.study: result,
              "scientific_adoption_asserted": False}
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
