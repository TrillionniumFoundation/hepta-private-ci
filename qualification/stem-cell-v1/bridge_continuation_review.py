"""Independent stdlib audit of V6 primary continuation and retention.

This auditor authenticates completed training records; it performs no neural
execution and never opens fresh or official-validation prediction outputs.
"""

from hashlib import sha256
import json
import math
from pathlib import Path

from binding_review import (audit_checkpoint, audit_continuation, audit_natural_panel,
                            audit_panel, audit_scores, audit_source_inventory, audit_warmup)
from bridge_review import audit_architecture, audit_initialization


SEEDS = (41, 47, 53)
ARMS = ("natural_only", "replay", "contrastive")


def _check(condition, message):
    if not condition:
        raise ValueError(message)


def _read(path):
    return json.loads(Path(path).read_text())


def _sha(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def _id(row):
    return json.dumps([row[key] for key in ("source_split", "paragraph_id", "question_id", "answer_id")], separators=(",", ":"))


def audit_retention(metrics, baseline):
    """Engineering retention rule, independently applied to saved probabilities."""
    _check(metrics["cases"] == baseline["cases"] == 128 and metrics["groups"] == baseline["groups"] == 32
           and metrics["paired_candidates"] == baseline["paired_candidates"] == 64, "complete train128 retention domain required")
    _check(baseline["accuracy"] == baseline["both_worlds_correct"] == baseline["all_four_correct"] == 1
           and baseline["probability_CE"] <= .10, "retention reference must pass the full warmup gate")
    reasons = []
    for key in ("accuracy", "both_worlds_correct"):
        value = metrics[key]
        _check(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1, "finite retention metrics required")
        if value + 1e-12 < .95:
            reasons.append(key + "_below_0.95")
        if baseline[key] - value > .05 + 1e-12:
            reasons.append(key + "_drop_above_0.05")
    return dict(passed=not reasons, reasons=reasons, qualification_scope="binding_train_retention_only",
                natural_internal_metrics_are_reported_not_a_gate=True, fresh_selection=False)


def audit_continuation_budget(receipt, plan):
    arm = receipt["arm"]
    _check(arm in ARMS and plan["updates"] == 500 and plan["batch_size"] == 16
           and plan["logical_update_order"] == ["natural", "binding"], "fixed 500-update continuation plan required")
    replay = 0 if arm == "natural_only" else 500
    _check(receipt["requested_natural_updates"] == receipt["completed_natural_updates"] == 500
           and receipt["requested_binding_updates"] == receipt["completed_binding_updates"] == replay
           and receipt["completed_steps"] == 500 and receipt["status"] == "completed",
           "incomplete or changed continuation update budget")
    _check(receipt["actual_natural_exposures"] == 8000 and receipt["actual_binding_exposures"] == replay * 16
           and receipt["actual_total_exposures"] == 8000 + replay * 16, "continuation exposure accounting mismatch")
    _check(receipt["optimizer"] == "Adam_foreach_false" and receipt["learning_rate"] == .001
           and receipt["depth"] == 3 and receipt["pair_weight"] == (.5 if arm == "contrastive" else 0.)
           and receipt["natural_case_identity_verified"] is True, "continuation optimizer, public row identity or loss changed")
    _check([item["logical_step"] for item in receipt["diagnostics"]] == list(range(0, 501, 100)),
           "scheduled continuation diagnostics missing")
    multiplier = 1 if arm == "natural_only" else 2
    _check(all(item["optimizer_steps"] == multiplier * item["logical_step"] for item in receipt["diagnostics"]),
           "diagnostic optimizer-step accounting mismatch")
    return dict(passed=True, natural_updates=500, binding_updates=replay,
                natural_exposures=8000, binding_exposures=replay * 16, fixed_budget_diagnostics_do_not_select=True)


def audit_natural_diagnostics(receipt, natural_train):
    keys = list(dict.fromkeys(tuple(row[key] for key in ("source_split", "paragraph_id", "question_id"))
                             for row in natural_train))[:8]
    cases = [row for row in natural_train if tuple(row[key] for key in ("source_split", "paragraph_id", "question_id")) in keys]
    targets, reports = [row["label"] for row in cases], []
    for item in receipt["diagnostics"]:
        diagnostic = item["natural"]
        probabilities = diagnostic["probabilities"]
        _check(diagnostic["n"] == len(cases) == len(probabilities)
               and all(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1 for p in probabilities),
               "training-source natural diagnostic rows differ from fixed first eight questions")
        predictions = [int(p > .5) for p in probabilities]
        accuracy = sum(pred == target for pred, target in zip(predictions, targets)) / len(targets)
        _check(diagnostic["predictions"] == predictions and diagnostic["accuracy"] == accuracy,
               "natural diagnostic predictions differ from strict raw probability decisions")
        reports.append(dict(logical_step=item["logical_step"], cases=len(cases), accuracy=accuracy))
    return dict(passed=True, scope="first_eight_natural_training_questions_not_internal_tune", diagnostics=reports)


def audit_global_retention(gates, reported):
    _check(set(gates) == {str(seed) for seed in SEEDS} and all(type(value) is bool for value in gates.values()),
           "all three independently derived primary retention seeds required")
    passed = all(gates.values())
    _check(reported is passed, "global contrastive gate contradicts independent metrics")
    return passed


def review_run(run, code, natural_cases):
    """Require actual continuation completion; support code alone never passes."""
    run, code, natural_cases = Path(run), Path(code), Path(natural_cases)
    _check((run / "continuation-completion.json").is_file(),
           "continuation not complete; support code exists but no continuation audit was performed")
    design = _read(run / "design.json")
    names = {"warmup.pt", "warmup-model.json", "warmup-training.json", "warmup-binding-train.json", "warmup-gate.json",
             "initialization.json", "initialization.bin", "continuation-plan.json", "retention-gates.json"}
    for arm in ARMS:
        names.update((arm + ".pt", arm + "-model.json", arm + "-training.json", arm + "-binding-train.json",
                      arm + "-binding-internal.json", arm + "-natural-internal.json"))
    guarded = {run / name for name in ("design.json", "all-cases.json", "warmup-completion.json",
                                      "continuation-start.json", "continuation-completion.json")}
    guarded.update(code / name for name in design["runtime_source_sha256"])
    guarded.update((Path(__file__), code / "binding_review.py", code / "bridge_review.py",
                    natural_cases, natural_cases.parent / "material-provenance.json"))
    guarded.update(run / f"seed-{seed}" / "bridge" / name for seed in SEEDS for name in names)
    previous = {Path(value["folder"]).parent for value in design["historical_baselines"].values()}
    _check(len(previous) == 1, "one authenticated previous V5 source required")
    previous_design_path = next(iter(previous)) / "design.json"
    guarded.add(previous_design_path)
    before = {str(path.resolve()): _sha(path) for path in guarded}
    previous_design, provenance = _read(previous_design_path), _read(natural_cases.parent / "material-provenance.json")
    _check(_sha(previous_design_path) == design["previous_v5_design_sha256"] == provenance["design_sha256"]
           and _sha(natural_cases) == provenance["natural_cases_file_sha256"]
           and provenance["official_train_sha256"] == previous_design["train_file_sha256"], "natural reference source byte binding changed")
    natural, parts = _read(natural_cases), _read(run / "all-cases.json")
    for role in ("train", "tune"):
        rows = natural[role]
        _check([_id(row) for row in rows] == design["natural_case_ids"][role]
               and sorted({row["source_hash"] for row in rows}) == previous_design["natural_sources"][role]
               and all(row["source_split"] == "train" for row in rows), "natural train/tune source membership changed")
    source = audit_source_inventory(code, design["runtime_source_sha256"])
    warmups = _read(run / "warmup-completion.json")
    start, completed = _read(run / "continuation-start.json"), _read(run / "continuation-completion.json")
    _check(warmups["completed_ns"] < start["started_ns"] < completed["completed_ns"], "continuation began before primary fitting completed")
    _check(warmups["primary_all_passed"] is True, "primary all-seed fitting gate was not opened")
    _check(warmups["runtime_source_sha256"] == completed["runtime_source_sha256"] == design["runtime_source_sha256"], "runtime changed across phases")
    _check(design["retention"] == dict(candidate_accuracy=.95, paired_world_accuracy=.95, maximum_drop=.05)
           and design["natural_internal_tune_is_hard_gate"] is False, "retention thresholds or natural internal scope changed")
    result = dict(schema="hepta.bridge.continuation-independent-review.v1", source=source, seeds=[],
                  fit_costs=dict(cpu_ns=0, wall_ns=0), physical_panel_costs=dict(cpu_ns=0, wall_ns=0), coverage=[])
    contrastive_gates, freeze_times = {}, []
    for seed in SEEDS:
        folder = run / f"seed-{seed}" / "bridge"
        initial = audit_initialization(folder / "initialization.json")
        for name in ("initialization.json", "initialization.bin"):
            _check(_sha(folder / name) == design["initialization_files_sha256"][f"seed-{seed}/bridge/{name}"],
                   "primary initialization bytes changed after design freezing")
        warm_receipt, warm_model = _read(folder / "warmup-training.json"), _read(folder / "warmup-model.json")
        warm_panel = audit_panel(parts["reader_train"], _read(folder / "warmup-binding-train.json"), warm_model)
        warm_audit = audit_warmup(warm_receipt, parts["reader_train"], warm_panel["metrics"])
        _check(warm_audit["qualified"] and _read(folder / "warmup-gate.json")["passed"] is True
               and warmups["gates"][str(seed)]["bridge"]["passed"] is True,
               "primary continuation opened without all three independently qualified warmups")
        audit_checkpoint(folder / "warmup.pt", warm_model, warm_receipt)
        audit_architecture(warm_model["architecture"], initial)
        _check(warm_model["frozen_ns"] <= warmups["completed_ns"]
               and warm_receipt["initial_model_sha256"] == initial["training_parameter_sha256"]
               and warm_model["initial_execution_parameter_sha256"] == initial["execution_parameter_sha256"],
               "primary reference warmup initialization or freeze chronology changed")
        plan, reported_gates = _read(folder / "continuation-plan.json"), _read(folder / "retention-gates.json")
        _check(plan["seed"] == seed and set(reported_gates) == set(ARMS), "primary seed plan or retention arm inventory changed")
        seed_report, sequences = dict(seed=seed, arms=[]), set()
        for arm in ARMS:
            receipt, model = _read(folder / (arm + "-training.json")), _read(folder / (arm + "-model.json"))
            _check(receipt["arm"] == arm and model["seed"] == seed, "model or receipt arm/seed differs from path")
            budget = audit_continuation_budget(receipt, plan)
            fit = audit_continuation(receipt, plan, natural["train"], parts["reader_train"], warm_receipt)
            audit_natural_diagnostics(receipt, natural["train"])
            audit_checkpoint(folder / (arm + ".pt"), model, receipt, warm_model)
            audit_architecture(model["architecture"], initial)
            _check(model["parameter_count"] == receipt["parameter_count"] == 42562
                   and start["started_ns"] <= model["frozen_ns"] <= completed["completed_ns"], "continued architecture or freeze chronology changed")
            train = audit_panel(parts["reader_train"], _read(folder / (arm + "-binding-train.json")), model)
            internal = audit_panel(parts["internal_tune"], _read(folder / (arm + "-binding-internal.json")), model)
            natural_internal = audit_natural_panel(natural["tune"], _read(folder / (arm + "-natural-internal.json")), model)
            retention = audit_retention(train["metrics"], warm_panel["metrics"])
            _check(reported_gates[arm]["passed"] is retention["passed"]
                   and completed["gates"][str(seed)][arm]["passed"] is retention["passed"], "reported retention gate differs from independent raw metrics")
            if arm == "contrastive":
                contrastive_gates[str(seed)] = retention["passed"]
            sequences.add(fit["natural_sequence_sha256"])
            freeze_times.append(model["frozen_ns"])
            seed_report["arms"].append(dict(arm=arm, budget=budget, fit=fit, retention=retention,
                training_panel=train, binding_internal_panel=internal, natural_internal_panel=natural_internal))
            for axis in ("cpu_ns", "wall_ns"):
                result["fit_costs"][axis] += receipt[axis]
                result["physical_panel_costs"][axis] += sum(panel["costs"][axis] for panel in (train, internal, natural_internal))
            result["coverage"].append(dict(seed=seed, arm=arm, model=str((folder / (arm + "-model.json")).resolve()),
                receipt=str((folder / (arm + "-training.json")).resolve()), scored_panels=[
                    arm + "-binding-train.json", arm + "-binding-internal.json", arm + "-natural-internal.json"]))
        _check(len(sequences) == 1, "natural sample identity/order differs between continuation arms")
        result["seeds"].append(seed_report)
    _check(freeze_times == sorted(freeze_times) and len(set(freeze_times)) == 9, "continuations were not frozen in the registered sequential order")
    all_passed = audit_global_retention(contrastive_gates, completed["contrastive_all_passed"])
    phase = completed["phase_cost"]
    _check(phase["cpu_ns"] >= result["fit_costs"]["cpu_ns"] + result["physical_panel_costs"]["cpu_ns"], "continuation phase CPU below disjoint fits/panels")
    if not all_passed:
        _check(not any((run / name).exists() for name in ("feedback-start.json", "all-models-frozen.json", "evaluation-start.json", "completion.json")),
               "failed primary retention opened feedback or fresh evaluation")
    after = {path: _sha(path) for path in before}
    _check(before == after, "continuation review input changed during read-only audit")
    result.update(passed=True, audit_completed=True, continuation_executed=True, models=9,
        binding_panels=18, natural_internal_panels=9, unchanged_input_files=len(after), input_sha256=after,
        independently_qualified_contrastive=contrastive_gates, all_contrastive_retained=all_passed,
        feedback_training_authorized_by_retention=all_passed, fresh_scoring_authorized_by_retention_alone=False,
        whole_phase_cost=phase, costs_are_nonadditive_scopes=True, prior_warmup_costs_not_recharged=True,
        feedback_and_fresh_reviewed=False, official_validation_read=False, neural_execution=False)
    return result


if __name__ == "__main__":
    import argparse
    import time

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--code", type=Path, required=True)
    parser.add_argument("--natural-cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    report = review_run(args.run, args.code, args.natural_cases)
    report["audit_cost"] = dict(cpu_ns=time.process_time_ns() - cpu, wall_ns=time.perf_counter_ns() - wall,
                                scope="complete_review_call_before_output_serialization")
    with args.output.open("x") as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
