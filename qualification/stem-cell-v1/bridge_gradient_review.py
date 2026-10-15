"""Independent stdlib byte/ledger/retention review for original V7.1 candidates.

Runs in a separate interpreter from Torch trainer. This is NOT independent
model/host/label provenance or a weight-level numerical replay: it checks the
complete source-bound historical V6 receipt graph and redoes every recorded
scalar/label/paired-world calculation without importing campaign code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re

SEEDS = (41, 47, 53)
ARMS = ("joint", "protect_old", "protect_old_guarded")
OLD = "v6_binding_paired_world_warmup"
NEW = "natural_multirc_continuation"
HEX = re.compile(r"[0-9a-f]{64}\Z")
SCHEMA = "hepta.bridge.gradient-campaign.v7.1"


def _fail(reason):
    raise ValueError(reason)


def _require(condition, reason):
    if not condition:
        _fail(reason)


def _unique_pairs(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            _fail("duplicate JSON key")
        result[k] = v
    return result


def _finite_number(value, minimum=None):
    _require(type(value) in (int, float) and math.isfinite(value), "finite number required")
    if minimum is not None:
        _require(value >= minimum, "out of range number")
    return float(value)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                    allow_nan=False).encode()).hexdigest()


def _safe_file(path, *, max_bytes=32_000_000):
    path = Path(path)
    _require(not path.is_symlink() and path.is_file(), "regular non-symlink file required")
    _require(0 < path.stat().st_size <= max_bytes, "bounded nonempty file required")
    return path


def file_hash(path):
    return hashlib.sha256(_safe_file(path, max_bytes=50_000_000).read_bytes()).hexdigest()


def read(path):
    return json.loads(_safe_file(path).read_text(encoding="utf-8"),
                      object_pairs_hook=_unique_pairs,
                      parse_constant=lambda _: _fail("nonfinite JSON constant"))


def _sha(value):
    _require(isinstance(value, str) and HEX.fullmatch(value), "SHA256 required")
    return value


def _near(value, wanted, *, rel=2e-5, abs_tol=2e-6):
    _finite_number(value)
    _require(math.isclose(value, wanted, rel_tol=rel, abs_tol=abs_tol), "scalar replay mismatch")


def check_gradient_rows(receipt, plan, arm, *, steps=500):
    """Replay every projected dot/norm, step, source row and work counter."""
    _require(arm in ARMS and receipt["schema"] == "hepta.bridge.gradient-continuation.v7.1"
             and receipt["status"] == "completed" and receipt["arm"] == arm,
             "original admitted candidate receipt required")
    _require(receipt["old_task"] == OLD and receipt["new_task"] == NEW,
             "old V6 binding/new natural role reversal denied")
    _require(receipt["plan_sha256"] == plan["plan_sha256"] and
             receipt["source_scope"] == "original_train_only" and
             receipt["production_authorized"] is False,
             "plan/source/authority mismatch")
    rows = receipt["updates"]
    _require(len(rows) == steps == plan["updates"], "complete fixed update census required")
    work = dict(forwards=0, backwards=0, old_rows=0, new_rows=0,
                accepted=0, rejected=0, cpu_ns=0, wall_ns=0)
    for i, row in enumerate(rows):
        _require(row["logical_step"] == i+1 and row["arm"] == arm and
                 row["old_task"] == OLD and row["new_task"] == NEW,
                 "canonical step/role/arm mismatch")
        old_ids = [plan["binding_case_ids"][j] for j in plan["binding_batches"][i]]
        new_ids = [plan["natural_case_ids"][j] for j in plan["natural_batches"][i]]
        _require(row["old_case_ids"] == old_ids and row["new_case_ids"] == new_ids
                 and row["old_train_rows"] == len(old_ids)
                 and row["new_train_rows"] == len(new_ids),
                 "old binding/new natural sources or exposures mismatched")
        _require(row["actual_reader_forwards"] == 3 and row["actual_backward_calls"] == 2
                 and row["attempted_optimizer_steps"] == 1,
                 "physical callback census incomplete")
        _require(row["post_step_forward_observed"] is True
                 and row["first_order_only"] is True
                 and row["actual_retention_verified"] is False,
                 "training diagnostic misrepresented as retention")
        old2 = _finite_number(row["old_gradient_squared_l2"], 0)
        _finite_number(row["new_gradient_squared_l2"], 0)
        dot = _finite_number(row["dot_old_new"])
        projected = arm != "joint" and dot < 0 and old2 > 1e-24
        _require(row["projected"] is projected, "projection policy mismatch")
        expected_ratio = dot / old2 if projected else 0.
        _near(row["projection_coefficient"], expected_ratio)
        # Stored residual is accumulated after FP32 gradient materialization;
        # tolerate rounding vs FP64 analytic expected residual explicitly.
        _near(row["residual_new_dot_old"], dot - expected_ratio*old2,
              rel=1e-4, abs_tol=1e-4 * (abs(dot) + old2 + 1.))
        _near(row["old_loss_before"],
              _finite_number(row["old_ce"], 0) + .5*_finite_number(row["old_pair_loss"], 0))
        _finite_number(row["new_ce"], 0)
        _near(row["old_loss_proposal_delta"],
              _finite_number(row["old_loss_after_proposal"], 0) - row["old_loss_before"])
        guard = arm == "protect_old_guarded" and row["old_loss_proposal_delta"] > row["old_loss_guard_tolerance"]
        _require(row["old_loss_guard_reverted"] is guard
                 and row["optimizer_state_restored_if_rejected"] is guard
                 and row["rejected_optimizer_steps"] == int(guard)
                 and row["accepted_optimizer_steps"] == int(not guard),
                 "Adam poststep guard/rollback mismatch")
        _finite_number(row["adam_old_direction_dot"])
        _finite_number(row["preclip_combined_l2"], 0)
        _require(row["clip_limit"] == 1.0 and row["old_loss_guard_tolerance"] == 1e-6,
                 "unregistered gradient cap/guard tolerance")
        for count, field in (("forwards", "actual_reader_forwards"),
                             ("backwards", "actual_backward_calls"),
                             ("old_rows", "old_train_rows"),
                             ("new_rows", "new_train_rows"),
                             ("accepted", "accepted_optimizer_steps"),
                             ("rejected", "rejected_optimizer_steps")):
            work[count] += row[field]
        for unit in ("cpu_ns", "wall_ns"):
            cost = row[unit]
            _require(type(cost) is int and cost >= 0, "bounded physical step cost required")
            work[unit] += cost
    for key, counter in (("actual_reader_forwards", "forwards"),
                         ("actual_backward_calls", "backwards"),
                         ("old_train_rows", "old_rows"),
                         ("new_train_rows", "new_rows"),
                         ("accepted_optimizer_steps", "accepted"),
                         ("rejected_optimizer_steps", "rejected")):
        _require(receipt[key] == work[counter], "total physical work/cases drift")
    _require(receipt["attempted_optimizer_steps"] == steps
             and receipt["old_train_batches"] == steps
             and receipt["new_train_batches"] == steps,
             "fixed paired stream budgets incomplete")
    for unit in ("cpu_ns", "wall_ns"):
        _require(type(receipt[unit]) is int and receipt[unit] >= work[unit],
                 "step costs exceed enclosing candidate cost")
    _require(receipt["equal_backward_calls"] is True
             and receipt["actual_compute_equal"] is False
             and receipt["old_task_retention_verified"] is False
             and receipt["natural_task_generalization_verified"] is False,
             "unqualified advantage/retention claim")
    return work


def _retention(metrics, baseline):
    # Independent binary threshold and original 4-case paired-world aggregation.
    # TRAIN original fixed binding sources are ordered 4/group by the protocol.
    _require(baseline["accuracy"] == 1 and baseline["both_worlds_correct"] == 1,
             "unqualified original binding warmup")
    return (metrics["accuracy"] >= .95 - 1e-12
            and metrics["both_worlds_correct"] >= .95 - 1e-12
            and baseline["accuracy"] - metrics["accuracy"] <= .05+1e-12
            and baseline["both_worlds_correct"] - metrics["both_worlds_correct"] <= .05+1e-12)


def review(output, previous_v6):
    """Reopen original V6 receipts, every output byte and all 9 new arms."""
    output, previous_v6 = Path(output), Path(previous_v6)
    start, completed = read(output / "start.json"), read(output / "completed.json")
    _require(start["schema"] == completed["schema"] == SCHEMA and
             completed["complete"] is True and
             start["task_roles"] == completed["task_roles"] == {"old": OLD, "new": NEW},
             "incomplete/misidentified V7.1 campaign")
    _require(start["official_validation_unopened"] is True and
             completed["source_disjoint_future_windows"] == 0 and
             completed["production_authorized"] is False and
             completed["cell_split_authorized"] is False and
             completed["model_selected"] is False and
             completed["native_ndu_admitted"] is False,
             "research-only scope violated")
    _require(start["previous_v6_design_sha256"] == file_hash(previous_v6 / "design.json")
             and start["previous_warmup_sha256"] == file_hash(previous_v6 / "warmup-completion.json")
             and start["original_source_validation_scope"] ==
                "original_V6_checked_design_and_cached_features"
             and start["original_pretrained_snapshots_independently_authenticated"] is False,
             "original frozen V6 snapshot lineage drift")
    _require(set(completed["results"]) == {f"{seed}/{arm}" for seed in SEEDS for arm in ARMS},
             "all seed/arm cohorts required")
    original_warmup = read(previous_v6 / "warmup-completion.json")
    _require(original_warmup["primary_all_passed"] is True and
             original_warmup["fresh_scoring_authorized"] is False,
             "original V6 warmup gate missing or evaluation already authorized")
    all_records, all_work = {}, {}
    for seed in SEEDS:
        plan = read(output / f"seed-{seed}" / "plan.json")
        _require(plan["seed"] == seed and plan["schema"] ==
                 "hepta.binding.continuation-plan.v1", "wrong original schedule")
        _require(plan["plan_sha256"] == _digest({k:v for k,v in plan.items()
                    if k != "plan_sha256"}), "training plan bytes changed")
        _require(plan["updates"] == 500 and plan["batch_size"] == 16
                 and len(plan["binding_case_ids"]) == 128
                 and len(plan["binding_targets"]) == 128
                 and all(plan["binding_targets"][k:k+4] == [1, 0, 0, 1]
                         for k in range(0, 128, 4))
                 and len(plan["natural_case_ids"]) > 0,
                 "original source/group size not complete")
        _require(len(plan["binding_batches"]) == len(plan["natural_batches"]) == 500,
                 "missing original batches")
        frozen_plan = previous_v6 / f"seed-{seed}" / "bridge" / "continuation-plan.json"
        if frozen_plan.exists():
            _require(read(frozen_plan) == plan, "published V6 old/new training plan differs")
        old_folder = previous_v6 / f"seed-{seed}" / "bridge"
        old_model, original_scores = read(old_folder / "warmup-model.json"), read(old_folder / "warmup-binding-train.json")
        baseline = original_scores["metrics"]
        _require(original_warmup["gates"][str(seed)]["bridge"]["passed"] is True,
                 "original seed-specific V6 full binding training gate not passed")
        for arm in ARMS:
            folder = output / f"seed-{seed}" / arm
            attempt, model = read(folder / "attempt.json"), read(folder / "candidate-model.json")
            _require(attempt["original_warmup_sha256"] == file_hash(old_folder / "warmup-model.json")
                     and attempt["original_baseline_sha256"] == file_hash(old_folder / "warmup-binding-train.json")
                     and attempt["plan_sha256"] == plan["plan_sha256"]
                     and attempt["arm"] == arm and attempt["seed"] == seed,
                     "attempt/parent binding mismatch")
            _require(model["seed"] == seed and model["architecture"]["arm"] == "bridge"
                     and model["initial_execution_parameter_sha256"] == old_model["execution_parameter_sha256"]
                     and model["file"] == "candidate.pt"
                     and model["training_receipt_file"] == "candidate-training.json",
                     "candidate source/model identity altered")
            _require(file_hash(folder / "candidate.pt") == _sha(model["file_sha256"])
                     and file_hash(folder / "candidate-training.json") == _sha(model["training_receipt_sha256"]),
                     "candidate weights/receipts corrupted")
            receipt = read(folder / "candidate-training.json")
            _require(receipt["final_model_sha256"] == model["training_parameter_sha256"]
                     and receipt["initial_model_sha256"] == old_model["training_parameter_sha256"],
                     "candidate parameter digest chain differs")
            work = check_gradient_rows(receipt, plan, arm)
            old_panel = read(folder / "old-binding-train.json")
            _require(old_panel["case_ids"] == plan["binding_case_ids"],
                     "wrong original old-task scoring cohort")
            probabilities = old_panel["probabilities"]
            targets = plan["binding_targets"]
            _require(len(probabilities) == len(targets) == 128 and
                     all(t in (0,1) and type(t) is int for t in targets),
                     "paired-world complete binary training labels required")
            predictions = []
            for prob in probabilities:
                _require(0 <= _finite_number(prob) <= 1, "bounded old-task probabilities required")
                predictions.append(int(prob > .5))
            correct = sum(p == t for p,t in zip(predictions,targets))/128
            pairs_correct = sum(predictions[k]==targets[k] and predictions[k+2]==targets[k+2]
                                for k in range(0,128,4)) + sum(
                                predictions[k+1]==targets[k+1] and predictions[k+3]==targets[k+3]
                                for k in range(0,128,4))
            paired = pairs_correct/64
            _near(old_panel["metrics"]["accuracy"], correct, abs_tol=1e-12)
            _near(old_panel["metrics"]["both_worlds_correct"], paired, abs_tol=1e-12)
            described = read(folder / "descriptive.json")
            _require(described["old_training_retention"]["passed"] == _retention(old_panel["metrics"], baseline)
                     and described["arm"] == arm and described["seed"] == seed
                     and described["old_task_future_retention_verified"] is False
                     and described["independent_new_task_verified"] is False
                     and described["production_authorized"] is False,
                     "old-train retention/gates fabricated")
            _require((folder / "new-natural-internal-tune.json").is_file(),
                     "original natural internal diagnostic missing")
            result = completed["results"][f"{seed}/{arm}"]
            _require(result["model_sha256"] == receipt["final_model_sha256"]
                     and result["retained_train_only"] == described["old_training_retention"]["passed"]
                     and result["actual_cpu_ns"] == receipt["cpu_ns"]
                     and result["actual_wall_ns"] == receipt["wall_ns"]
                     and result["old_train_rows"] == work["old_rows"]
                     and result["new_train_rows"] == work["new_rows"]
                     and result["accepted_optimizer_steps"] == work["accepted"]
                     and result["rejected_optimizer_steps"] == work["rejected"],
                     "aggregate reports disagree with independently recalculated data")
            all_records[f"{seed}/{arm}"] = dict(old_binding_train_retained=result["retained_train_only"],
                attempted=500, accepted=work["accepted"], rejected=work["rejected"],
                correct_binding_old=round(correct*128), paired_correct=round(paired*64))
            all_work[f"{seed}/{arm}"] = work
    return dict(schema="hepta.bridge.gradient-independent-review.v7.1",
        disposition="DIAGNOSTIC_CONSISTENT_NOT_PRODUCTION_ADMITTED",
        source_provenance_independently_authenticated=False,
        trained_weight_numerical_replay_performed=False,
        future_task_quality_established=False, old_task_future_retention_verified=False,
        independent_future_windows=0, actual_equal_lifecycle_compute=False,
        model_selected=False, cell_split_authorized=False,
        production_authorized=False, arms=all_records,
        total_physical_reader_forwards=sum(row["forwards"] for row in all_work.values()),
        total_physical_backward_calls=sum(row["backwards"] for row in all_work.values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous-v6", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    args = parser.parse_args()
    result = review(args.output, args.previous_v6)
    if args.review.exists() or args.review.is_symlink():
        raise ValueError("independent review output must be create-only")
    with args.review.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"disposition": result["disposition"],
                      "arms_reviewed":len(result["arms"])},sort_keys=True))


if __name__ == "__main__":
    main()
