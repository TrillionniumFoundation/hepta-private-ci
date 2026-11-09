"""Retrospective effectiveness of retained tick-0 forecast votes, not new checks.

Calibration panels fit joint channels; original train labels fit only the prior.
Confirmation describes each original arm's observed horizon without transferring
labels across arms. Zero-cost VOI is an analytical gross-information diagnostic,
not a measured cost conversion, policy evaluation or authorization to accept.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from .checker_effects import CheckerSpec, EffectScope, PairedPanel, fit_checker_effects
from .check_voi import DecisionProblem, evaluate_check, select_check_voi
from .model_protocol import digest, finite_probability, public_view
from .shadow_replay import SOURCES as REPLAY_SOURCES, load, records, validate
from .shadow_schedule import observation_context


VERSION = "verify-checker-retained-replay-v1"
THRESHOLD = 0.5
ROSTER = (("qwen-neutral", "single", 0), ("qwen-auditor", "roles_two", 1),
          ("qwen-readout0", "readout_heads_two", 0),
          ("qwen-readout1", "readout_heads_two", 1),
          ("smol-neutral", "bases_two", 1), ("qwen-repeat", "repeat_two", 1))
SOURCES = tuple(sorted(set(REPLAY_SOURCES + ("checker_replay.py", "checker_effects.py",
                                           "check_voi.py", "contracts.py", "shadow_schedule.py"))))
LOSS_TABLE = ((0, 1), (1, 0))


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def effect_scope(snapshot):
    """Use the same observable-context identity as the composed shadow selector."""
    target = snapshot.target
    return EffectScope(target.domain, target.event, snapshot.observed_step, target.horizon_end,
                       target.continuation_policy_sha256, observation_context(snapshot))


def _observation(data, assessments, operations, positions, split, case_id, spec):
    checker, arm, index = spec
    key = split, case_id, arm
    assessment = assessments.get(key)
    if assessment is None:
        return None
    view, context = public_view([]), assessment["context"]
    _require(assessment["view"] == view and type(context["tick"]) is int
             and context["tick"] == 0 and assessment["evidence_sha256"] == digest(view),
             "checker evidence is not the frozen empty-ACK context")
    member = assessment["members"][index]
    operation = operations[member["operation_id"]]
    aggregate = operations[assessment["assessment_id"]]
    _require(aggregate["kind"] == "score_aggregation" and aggregate["status"] == "completed"
             and all(aggregate[k] == v for k, v in assessment.items()), "aggregation binding mismatch")
    _require(operation["status"] == "completed" and all(operation["context"].get(k) == v
             for k, v in context.items()), "member operation scope mismatch")
    heads = arm == "readout_heads_two"
    _require(operation["kind"] == ("trained_readout" if heads else "model_score"), "wrong member kind")
    forward = operations[member["feature_operation_id"]] if heads else operation
    _require(forward["status"] == "completed" and forward["kind"] == ("model_features" if heads else "model_score")
             and forward["model"] == ("smol" if checker == "smol-neutral" else "qwen")
             and forward["role"] == ("auditor" if checker == "qwen-auditor" else "neutral")
             and digest(forward["decoder"]) == digest(data["plan"]["decoder"])
             and forward["view"] == view and forward["prompt_sha256"] == digest(forward["prompt"])
             and all(forward[k] == member[k] for k in ("base_sha256", "prompt_sha256", "evidence_sha256")),
             "forward does not match the declared checker")
    if heads:
        _require(operation["feature_operation_id"] == forward["operation_id"]
                 and forward["context"]["head_index"] == index
                 and all(forward["context"].get(k) == v for k, v in context.items())
                 and positions[forward["operation_id"]] < positions[operation["operation_id"]],
                 "readout feature binding mismatch")
    identity = {k: member[k] for k in ("base_sha256", "adapter_sha256", "prompt_sha256")}
    _require(all((k == "adapter_sha256" and value is None) or
                 (type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value))
                 for k, value in identity.items()), "malformed model identity")
    _require(all(operation[k] == member[k] for k in (*identity, "score", "evidence_sha256"))
             and member["evidence_sha256"] == digest(view), "member score or identity mismatch")
    _require(positions[operation["operation_id"]] < positions[aggregate["operation_id"]],
             "aggregation precedes its member")
    host = data["host_rows"][(split, case_id, arm if split == "confirmation"
                              else split + "/uninterrupted_panel")]
    if host["effects"]:
        _require(positions[aggregate["operation_id"]] < positions[host["effects"][0]["operation_id"]],
                 "tick-0 assessment follows an effect")
    score = finite_probability(member["score"])
    return {"checker_id": checker, "case_id": case_id, "arm": arm, "split": split,
            "source_group": data["cases"][split][case_id]["source_group"],
            "version_sha256": digest({**identity, "threshold": THRESHOLD,
                                      "decoder": data["plan"]["decoder"]}),
            "identity": identity, "score": score,
            "outcome": "fail" if score >= THRESHOLD else "pass",
            "assessment_id": assessment["assessment_id"], "operation_id": operation["operation_id"],
            "operation_sha256": digest(operation), "evidence_sha256": member["evidence_sha256"]}


def fit_diagnostic(panels, *, scope, checkers, training_groups, heldout_groups, prior_error):
    """Fit paired calibration counts and enumerate hypothetical decision value."""
    _require(tuple(c.checker_id for c in checkers) == tuple(row[0] for row in ROSTER), "unregistered checker roster")
    model = fit_checker_effects(panels, scope=scope, checkers=checkers,
                               training_groups=training_groups, heldout_groups=heldout_groups)
    conditional = model.condition(prior_error, scope=scope)
    _require(conditional.status == "supported", conditional.reason)
    problem = DecisionProblem(("correct", "error"), (1 - prior_error, prior_error),
                              ("accept", "reject"), LOSS_TABLE)
    values = [asdict(evaluate_check(problem, channel)) for channel in conditional.channels]
    repeats = []
    for outcome in sorted({panel.outcomes[0] for panel in panels}):
        updated = model.condition(prior_error, {"qwen-neutral": outcome}, scope=scope)
        item = {"history": {"qwen-neutral": outcome}, "status": updated.status,
                "reason": updated.reason}
        if updated.status == "supported":
            after = DecisionProblem(problem.states, (1 - updated.posterior_error,
                                    updated.posterior_error), problem.actions, problem.losses)
            repeat = next(channel for channel in updated.channels if channel.checker_id == "qwen-repeat")
            item["evaluation"] = asdict(evaluate_check(after, repeat))
        repeats.append(item)
    return model, {"scope": asdict(scope), "prior_error": prior_error,
                   "hypothetical_loss_table": {"states": problem.states, "actions": problem.actions,
                                               "losses": LOSS_TABLE},
                   "cost_assumption": "zero solely to isolate gross information; not measured free checking",
                   "evaluations": values, "repeat_after_neutral": repeats,
                   "selection": asdict(select_check_voi(problem, conditional.channels, 0)),
                   "all_gross_values_zero": all(item["gross_value"] == 0 for item in values),
                   "positive_cost_identity": "net_value = gross_value - supplied_cost",
                   "zero_gross_implication": "when gross value is zero, every positive supplied cost gives net_value = -cost",
                   "measured_net_utility": None, "operating_policy_evaluated": False}


def _heldout_report(rows):
    known = [row for row in rows if row["error"] is not None]
    scored = [row for row in known if row["score"] is not None]
    correct = [row for row in scored if row["error"] is False]
    errors = [row for row in scored if row["error"] is True]
    accepted = [row for row in rows if row["accepted"]]
    accepted_errors = sum(row["error"] is True for row in accepted)
    missing_accepted = sum(row["error"] is None for row in accepted)
    return {"planned": len(rows), "known_horizon_labels": len(known), "scored": len(scored),
            "missing_horizon_labels": len(rows) - len(known),
            "missing_forecasts": sum(row["score"] is None for row in rows),
            "sensitivity": {"detected": sum(row["outcome"] == "fail" for row in errors), "errors": len(errors)},
            "false_positives": {"flagged": sum(row["outcome"] == "fail" for row in correct), "correct": len(correct)},
            "raw_score_brier": sum((row["score"] - row["error"]) ** 2 for row in scored) / len(scored) if scored else None,
            "original_arm_acceptance_coverage": len(accepted) / len(rows) if rows else None,
            "accepted_error_missing_label_bounds": [accepted_errors / len(accepted),
                (accepted_errors + missing_accepted) / len(accepted)] if accepted else None,
            "bounds_are_confidence_intervals": False, "complete_case_estimates_only": True}


def diagnose(data):
    """Check original ledgers, fit calibration only, then describe held-out arms."""
    data = validate(data)
    target, collections = records(data)
    initial_snapshot = next(row for row in collections["calibration"]["panel"][0] if row.observed_step == 0)
    scope = effect_scope(initial_snapshot)
    operations = {op["operation_id"]: op for op in data["operations"]}
    positions = {op["operation_id"]: i for i, op in enumerate(data["operations"])}
    assessments = {}
    for row in data["assessments"]:
        context = row["context"]
        if context["tick"] == 0 and context["split"] in ("calibration", "confirmation"):
            key = context["split"], context["case_id"], context["arm"]
            _require(key not in assessments, "duplicate tick-0 assessment")
            assessments[key] = row
    train_labels = collections["train"]["panel"][1]
    _require(train_labels and all(row.error is not None for row in train_labels), "prior needs complete train labels")
    prior = {"count": len(train_labels), "errors": sum(row.error for row in train_labels),
             "smoothing": [1, 1], "source_groups": sorted({row.source_group for row in train_labels}),
             "label_sha256": digest([asdict(row) for row in train_labels])}
    prior["probability"] = (prior["errors"] + 1) / (prior["count"] + 2)
    labels = {row.trajectory_id: row for row in collections["calibration"]["panel"][1]}
    panels, observations, checkers, used = [], [], None, set()
    for case_id, case in sorted(data["cases"]["calibration"].items()):
        selected = [_observation(data, assessments, operations, positions, "calibration", case_id, spec) for spec in ROSTER]
        _require(all(row is not None for row in selected), "incomplete paired calibration checker roster")
        _require(not used.intersection(row["operation_id"] for row in selected), "reused member evidence")
        used.update(row["operation_id"] for row in selected)
        current = tuple(CheckerSpec(row["checker_id"], row["version_sha256"], 0) for row in selected)
        checkers = current if checkers is None else checkers
        _require(current == checkers, "checker version changes across paired panels")
        label = labels[f"calibration/{case_id}/calibration/uninterrupted_panel"]
        panels.append(PairedPanel("calibration/" + case_id, case["source_group"],
                      digest({"case_id": case_id, "goal": case["goal"], "view": public_view([])}), scope,
                      tuple(c.checker_id for c in checkers), tuple(c.version_sha256 for c in checkers),
                      tuple(row["outcome"] for row in selected), label.error, label.evidence_sha256,
                      tuple(row["operation_sha256"] for row in selected), label.missing_reason))
        observations.extend(selected)
    groups = sorted({panel.source_group for panel in panels})
    heldout_groups = sorted({case["source_group"] for case in data["cases"]["confirmation"].values()})
    model, voi = fit_diagnostic(panels, scope=scope, checkers=checkers,
                               training_groups=groups, heldout_groups=heldout_groups, prior_error=prior["probability"])
    heldout, summaries = [], {}
    original_rows = {(row["case_id"], row["arm"]): row for row in data["rows"]}
    for spec, checker in zip(ROSTER, checkers):
        checker_id, arm, _ = spec
        arm_labels = {row.trajectory_id: row for row in collections["confirmation"].get(arm, ([], []))[1]}
        rows = []
        for case_id in sorted(data["cases"]["confirmation"]):
            _require((case_id, arm) in original_rows, "missing planned checker arm")
            label = arm_labels[f"confirmation/{case_id}/{arm}"]
            observed = _observation(data, assessments, operations, positions, "confirmation", case_id, spec)
            if observed is not None:
                _require(observed["version_sha256"] == checker.version_sha256, "held-out checker version drift")
                _require(observed["operation_id"] not in used, "held-out member evidence reused")
                used.add(observed["operation_id"])
            rows.append({**(observed or {"checker_id": checker_id, "case_id": case_id, "arm": arm,
                                        "score": None, "outcome": None}),
                         "error": label.error, "label_evidence_sha256": label.evidence_sha256,
                         "missing_label_reason": label.missing_reason,
                         "accepted": original_rows[case_id, arm]["accepted"]})
        summaries[checker_id] = _heldout_report(rows)
        heldout.extend(rows)
    return {"prior": prior, "panels": [asdict(row) for row in panels], "observations": observations,
            "model": asdict(model), "diagnostics": model.diagnostics(), "voi": voi,
            "heldout_observations": heldout, "heldout": summaries,
            "gates": data["gates"], "status": "RETAINED_CHECKER_DIAGNOSTIC_COMPLETED",
            "new_model_inference": False, "new_original_effects": False, "prospective_shadow": False,
            "checker_outputs_are_thresholded_forecasts": True, "full_physical_cost_complete": False,
            "source_groups_establish_independence": False, "scientific_admission": "HOLD",
            "production_authority": "NONE", "scheduling_benefit_established": False,
            "interpretation": "Empirical initial-view channels only; held-out labels are arm-specific and censored; zero cells are not certified impossibilities."}


def run(directory, output):
    """Create-only freeze/result; changed input or source leaves a failure receipt."""
    directory, output = Path(directory).resolve(), Path(output).resolve()
    _require(directory != output and directory not in output.parents, "output must not modify original run")
    output.mkdir(parents=True, exist_ok=False)
    def write(name, value):
        with (output / name).open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")
    try:
        data = load(directory)
        sources = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in SOURCES}
        write("freeze.json", {"version": VERSION, "input_sha256": data["input_sha256"], "source_sha256": sources,
              "roster": ROSTER, "threshold": THRESHOLD, "effect_fit_split": "calibration",
              "prior_fit_split": "train", "heldout_split": "confirmation", "tick": 0,
              "cost": "analytical zero; physical cost unknown", "hypothetical_loss_table": LOSS_TABLE,
              "retrospective": True, "prospective_protocol": False})
        result = diagnose(data)
        _require(all(hashlib.sha256((directory / name).read_bytes()).hexdigest() == sha
                     for name, sha in data["input_sha256"].items()), "original inputs changed during replay")
        _require(all(hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() == sha
                     for name, sha in sources.items()), "replay source changed during scoring")
        for key in ("panels", "observations", "model", "diagnostics", "voi", "heldout_observations"):
            write(key + ".json", result[key])
        write("result.json", {key: value for key, value in result.items()
                              if key not in ("panels", "observations", "model", "heldout_observations")})
        return result
    except Exception as error:
        write("failure.json", {"type": type(error).__name__, "message": str(error)})
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run(args.input, args.output)
    print(json.dumps({"status": result["status"], "paired_panels": len(result["panels"]),
                      "all_gross_values_zero": result["voi"]["all_gross_values_zero"]}))


if __name__ == "__main__":
    main()
