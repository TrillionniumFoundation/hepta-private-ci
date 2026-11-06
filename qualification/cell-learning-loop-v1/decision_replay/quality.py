"""Strict engineering eligibility from actual states and typed execution.

This predicate grants no publication authority. The caller freezes provenance,
verifies complete checkpoints and supplies real shared-encoder features.
"""

import hashlib
import json


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def assess(receipt, cases, features, models, paths, bindings, score):
    """Reexecute both real heads and the fixed executor; reject forged receipts."""
    exit_code = receipt.get("parent_observed", {}).get("returncode")
    require(receipt.get("status") == "completed" and receipt.get("phase") == "evaluate"
            and type(exit_code) is int and exit_code == 0,
            "evaluation did not complete")
    evidence = receipt["result"]
    require(evidence.get("engineering_passed") is True, "evaluation did not qualify")
    historical = bindings["historical_cases"]
    require(type(historical) is int and 0 < historical < len(cases)
            and len(features) == len(cases), "invalid case partition")
    require(all(type(row.get("id")) is str and row["id"] for row in cases)
            and len({row["id"] for row in cases}) == len(cases), "invalid or duplicate golden case")
    require(type(evidence.get("historical_cases")) is int
            and evidence["historical_cases"] == historical
            and type(evidence.get("authored_held_cases")) is int
            and evidence["authored_held_cases"] == len(cases) - historical,
            "case inventory differs from frozen goldens")
    require(set(evidence["results"]) == {"parent", "candidate"}, "unexpected arm roster")
    counts, outputs, verified = {}, {}, {}
    for arm in ("parent", "candidate"):
        model, expected, path = models[arm], bindings[arm], paths[arm]
        state = model.state_hash()
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected["checkpoint_sha256"]
                and hashlib.sha256((path.parent / "manifest.json").read_bytes()).hexdigest() == expected["artifact"]
                and state == expected["state_sha256"]
                and model.encoder_hash == expected["encoder_sha256"]
                and model.source_version == expected["source_version"], "actual artifact/state binding changed: " + arm)
        recorded = evidence["results"][arm]
        require(set(recorded) == {"historical_correct", "correction_correct", "state_sha256", "outputs"}
                and recorded["state_sha256"] == state, "evaluation state binding changed: " + arm)
        fresh = [{"id": row["id"], "expected": row["expected"], **score(row, int(choice))}
                 for row, choice in zip(cases, model.predict(features), strict=True)]
        require(canonical(recorded["outputs"]) == canonical(fresh),
                "typed outputs, case roster or predictions changed: " + arm)
        counts[arm] = {"historical_correct": sum(row["correct"] for row in fresh[:historical]),
                       "correction_correct": sum(row["correct"] for row in fresh[historical:])}
        for key, actual in counts[arm].items():
            require(type(recorded[key]) is int and recorded[key] == actual,
                    "reported metric differs from real outputs: " + arm + ":" + key)
        require(model.state_hash() == state, "quality inference mutated state")
        outputs[arm], verified[arm] = fresh, dict(expected)
    retention_delta = counts["candidate"]["historical_correct"] - counts["parent"]["historical_correct"]
    correction_delta = counts["candidate"]["correction_correct"] - counts["parent"]["correction_correct"]
    reasons = (["corrected_task_not_improved"] if correction_delta <= 0 else [])
    if retention_delta < 0:
        reasons.append("historical_retention_loss")
    return {"quality_eligible": not reasons, "quality_vetoes": reasons, "counts": counts,
            "historical_delta": retention_delta, "correction_delta": correction_delta,
            "historical_regression_ids": [a["id"] for a, b in zip(outputs["parent"][:historical],
                outputs["candidate"][:historical], strict=True) if a["correct"] and not b["correct"]],
            "verified_content_bindings": verified, "fresh_outputs": outputs,
            "authority_granted": False, "scope": "post-run engineering eligibility; no prospective benefit claim"}


def publication_decision(quality):
    """No caller flag can turn this replay into a formal adoption authority."""
    formal, cost = "HOLD_NO_REGISTERED_NINE_ARM_ROUND", "HOLD_COMPLETE_COST_UNKNOWN"
    return {"passed": quality["quality_eligible"] and formal == "AUTHORIZED" and cost == "QUALIFIED",
            "quality": quality, "formal_authority": formal, "complete_cost": cost,
            "retention_veto_is_additional_not_sole_refusal": True,
            "formal_future_adoption_gate_invoked": False}
