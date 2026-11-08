"""Recompute declared decisions and budget transitions without executing a model.

This checks consistency with the retained plan, not its authenticity or the
quality of its risk forecasts. The v1 plan declares intervention step 2 and
budget 1 in an exact, versioned scope string. Those legacy semantics are not
inferred from observed decisions. A different schedule needs a new contract.
"""

import math

from .model_protocol import ARMS, VERSION, digest
from .model_readbacks import readback_bindings


def _number(value, maximum=None):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("invalid nonnegative decision quantity")
    if maximum is not None and value > maximum:
        raise ValueError("decision probability exceeds one")
    return value


def _key(record, tick=False):
    case, arm = record["case_id"], record["arm"]
    if any(type(value) is not str or not value for value in (case, arm)):
        raise ValueError("invalid decision identity")
    if not tick:
        return case, arm
    step = record["tick"]
    if type(step) is not int or step not in (1, 2, 3):
        raise ValueError("invalid decision frontier")
    return case, arm, step


def decision_bindings(plan, assessments, operations, trajectories, decisions):
    """Fail closed on a missing, altered or unplanned decision/check/budget.

    The complete trajectory roster comes from the plan; reached decision frontiers
    come from completed trajectories cross-checked against actual effect receipts.
    Inference identity and acceptance are separate gates in ``model_summary``.
    """
    try:
        if plan["version"] != VERSION or plan["intervention_scope"] != (
            "one confirmation source group, actual step2 policy override, "
            "budget1; model/evidence unchanged"
        ):
            return False
        if plan["optional_steps"] != [2, 3] or tuple(plan["arms"]) != ARMS:
            return False
        cost = _number(plan["optional_cost"])
        budget = _number(plan["optional_budget"])
        loss = _number(plan["error_loss"])
        settings = {}
        for setting in plan["interventions"]:
            if type(setting) is not dict or set(setting) != {"name", "risk", "cost"}:
                return False
            name = setting["name"]
            if type(name) is not str or not name or "intervention/" + name in settings:
                return False
            _number(setting["risk"], 1)
            _number(setting["cost"])
            settings["intervention/" + name] = setting
        cases = {
            case["goal"]["task_id"]: case for case in plan["cases"]["confirmation"]
        }
        if len(cases) != len(plan["cases"]["confirmation"]):
            return False
        planned = {_key(row) for row in plan["planned_trajectories"]}
        rows = {_key(row): row for row in trajectories}
        if not planned or len(planned) != len(plan["planned_trajectories"]):
            return False
        if len(rows) != len(trajectories) or set(rows) != planned:
            return False
        if any(
            case not in cases or arm not in (*ARMS, *settings) for case, arm in planned
        ):
            return False
        expected, effects = set(), set()
        for (case, arm), row in rows.items():
            reached = row["reached_step"]
            if row["status"] != "completed" or row["split"] != "confirmation":
                return False
            if type(reached) is not int or reached not in (2, 3):
                return False
            if type(row["interrupted"]) is not bool or (
                not row["interrupted"] and reached != 3
            ):
                return False
            if row["source_group"] != cases[case]["source_group"]:
                return False
            steps = [2] if arm in settings else plan["optional_steps"]
            expected.update((case, arm, step) for step in steps if step <= reached)
            effects.update((case, arm, step) for step in range(1, reached + 1))
        indexed = {_key(row, tick=True): row for row in decisions}
        if len(indexed) != len(decisions) or set(indexed) != expected:
            return False
        by_id = {row["assessment_id"]: row for row in assessments}
        if len(by_id) != len(assessments):
            return False
        actual_effects, actual_checks, operation_ids = set(), set(), set()
        for operation in operations:
            if operation["operation_id"] in operation_ids:
                return False
            operation_ids.add(operation["operation_id"])
            context = operation["context"]
            kind = operation["kind"]
            if kind == "optional_host_check" or (
                kind == "host_effect" and context.get("split") == "confirmation"
            ):
                if (
                    operation["status"] != "completed"
                    or context["split"] != "confirmation"
                ):
                    return False
                key = _key(context, tick=True)
                target = (
                    actual_checks if kind == "optional_host_check" else actual_effects
                )
                if key in target:
                    return False
                target.add(key)
        if actual_effects != effects:
            return False
        selected_checks = set()
        for case, arm in sorted(planned):
            setting = settings.get(arm)
            remaining = 1.0 if setting is not None else budget
            for step in [2] if setting is not None else plan["optional_steps"]:
                key = case, arm, step
                if key not in expected:
                    continue
                decision = indexed[key]
                assessment = by_id[decision["assessment_id"]]
                context = assessment["context"]
                if (
                    _key(context, tick=True) != key
                    or context["split"] != "confirmation"
                ):
                    return False
                if decision["split"] != "confirmation":
                    return False
                if assessment["arm"] != ("single" if setting is not None else arm):
                    return False
                score = _number(assessment["score"], 1)
                if _number(decision["raw_model_score"], 1) != score:
                    return False
                if assessment["evidence_sha256"] != digest(assessment["view"]):
                    return False
                if decision["evidence_sha256"] != assessment["evidence_sha256"]:
                    return False
                risk, price = (
                    (setting["risk"], setting["cost"])
                    if setting is not None
                    else (score, cost)
                )
                if _number(decision["policy_risk_input"], 1) != risk:
                    return False
                if _number(decision["declared_check_cost"]) != price:
                    return False
                if _number(decision["budget_before"]) != remaining:
                    return False
                # Canonical comparison also rejects bool-for-number substitution.
                if digest(decision["intervention"]) != digest(setting):
                    return False
                selected = price <= remaining and risk * loss >= price
                if arm == "fixed_check":
                    selected = step == 3 and price <= remaining
                if decision["selection"] != ("check" if selected else "defer"):
                    return False
                if selected:
                    selected_checks.add(key)
                    remaining = round(remaining - price, 10)
        return selected_checks == actual_checks and readback_bindings(
            cases, settings, operations, rows, indexed, by_id
        )
    except (KeyError, TypeError, ValueError, IndexError, OverflowError):
        return False
