"""Independent same-source four-arm TRAIN verifier x terminal-guard audit.

Every run first passes the existing complete stdlib public-answer, checkpoint,
trace, token, cost and source-identity replay. Here we check *between-run*
comparability and report descriptive paired rescues/harm, never a winner.
This reviewer does not authenticate pretrained execution or future task value.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from group_attention_campaign_review import COHORTS, review as review_single
from group_checkpoint_audit import strict_json_file


MATRIX = {
    "legacy_oracle": (False, "legacy_oracle_v1"),
    "legacy_no_verifier": (False, "no_verifier_v1"),
    "guarded_oracle": (True, "legacy_oracle_v1"),
    "guarded_no_verifier": (True, "no_verifier_v1"),
}
COMPARE_ARMS = ("attention", "attention_fixed", "attention_ndu")


def _sha(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _int_nonnegative(x):
    return type(x) is int and x >= 0


def review_factorial(roots):
    """Require four original independent single-run reviews, then pair cases."""
    if type(roots) is not dict or set(roots) != set(MATRIX):
        raise ValueError("four preregistered factorial arms required")
    if len({str(Path(x).resolve()) for x in roots.values()}) != 4:
        raise ValueError("each factorial arm needs its own immutable output directory")

    runs = {}
    for arm, root in roots.items():
        root = Path(root)
        # Check full original data/trace/checkpoint/sampler claims first.
        checked = review_single(root)
        if (checked.get("passed") is not True
                or checked.get("authority") != "DENY_ALL"
                or checked.get("future_task_efficacy_proved") is not False
                or checked.get("real_host_execution_independently_attested") is not False):
            raise ValueError("single campaign failed independent original replay")
        protocol = strict_json_file(root / "protocol.json")
        observations = strict_json_file(root / "observations.json")
        report = strict_json_file(root / "report.json")
        teacher = strict_json_file(root / "teacher.json")
        encoder = strict_json_file(root / "encoder.json")
        expected_guard, expected_feedback = MATRIX[arm]
        if (protocol.get("terminal_guard") is not expected_guard
                or protocol.get("training_feedback_policy") != expected_feedback
                or report.get("authority") != "DENY_ALL"
                or report.get("production_authorized") is not False
                or report.get("natural_future_win_established") is not False
                or report.get("equal_actual_training_work") is not False):
            raise ValueError("factorial arm policy, authority or scientific posture differs")
        if (type(report.get("actual_lifecycle_cpu_ns")) is not int
                or report["actual_lifecycle_cpu_ns"] <= 0):
            raise ValueError("full physical lifecycle CPU cost required")
        runs[arm] = dict(protocol=protocol, rows=observations, report=report,
                         teacher=teacher, encoder=encoder, checked=checked)

    control = runs["legacy_oracle"]
    immutable_protocol = {k: v for k, v in control["protocol"].items()
                          if k not in ("terminal_guard", "training_feedback_policy")}
    base_encoder = control["encoder"]
    base_teacher = control["teacher"]
    reference_rows = control["rows"]
    reference_case_features = {(r["cohort"], r["arm"], r["case_id"]):
                               (r["source_group"], r["feature_sha256"])
                               for r in reference_rows}
    required_keys = set(reference_case_features)
    initial_digest = control["report"]["initial_core_sha256"]
    sample_sha = {name: control["report"]["training"][name]["sample_and_depth_sha256"]
                  for name in ("static", "wide", "core", "attention")}
    for arm, run in runs.items():
        proto, report, teacher, encoder = (run["protocol"], run["report"],
                                           run["teacher"], run["encoder"])
        if ({k: v for k, v in proto.items()
             if k not in ("terminal_guard", "training_feedback_policy")}
                != immutable_protocol):
            raise ValueError("training source, optimizer, protocol or model code drift across arms")
        if (encoder["model_material"] != base_encoder["model_material"]
                or encoder["actual_forward_calls"] != base_encoder["actual_forward_calls"]
                or encoder["logical_requests"] != base_encoder["logical_requests"]
                or encoder["feature_cache_canonical_bytes"] !=
                   base_encoder["feature_cache_canonical_bytes"]):
            raise ValueError("shared frozen Encoder identity or materialization changed")
        if any(teacher.get(k) != base_teacher.get(k) for k in (
                "slot_assignments", "operation_mask_sha256",
                "feature_hashes_sha256", "token_id_retokenized_sha256",
                "token_id_forward_witness_sha256", "source_groups_sha256")):
            raise ValueError("TRAIN operation evidence/token identity drift")
        if (report["initial_core_sha256"] != initial_digest
                or any(report["training"][k]["sample_and_depth_sha256"] != sample_sha[k]
                       for k in sample_sha)):
            raise ValueError("initial model or frozen minibatch-depth sampling drift")
        current_features = {(r["cohort"], r["arm"], r["case_id"]):
                            (r["source_group"], r["feature_sha256"])
                            for r in run["rows"]}
        if set(current_features) != required_keys or current_features != reference_case_features:
            raise ValueError("paired heldout source/feature identity drift")
        for name in ("core", "attention"):
            trained = report["training"][name]
            if (trained.get("training_feedback_policy") != MATRIX[arm][1]
                    or trained.get("training_verifier_oracle_enabled") is not
                       (MATRIX[arm][1] == "legacy_oracle_v1")
                    or not _int_nonnegative(trained.get("training_feedback_calls"))):
                raise ValueError("measured TRAIN oracle policy contradicts factorial arm")
        if report.get("genuine_pretrained_encoder_executed") is not True:
            raise ValueError("a declared actual pretrained run is required, not source-only checks")

    # Underlying single-run reviewer has already independently re-scored every
    # prediction from the registered public task. Re-pair raw case identities.
    paired = {}
    for cohort in COHORTS:
        paired[cohort] = {}
        for model_arm in COMPARE_ARMS:
            cases = {}
            for cell in MATRIX:
                rows = {r["case_id"]: r for r in runs[cell]["rows"]
                        if r["cohort"] == cohort and r["arm"] == model_arm}
                cases[cell] = rows
            origin = cases["legacy_oracle"]
            if not origin or any(set(rows) != set(origin) for rows in cases.values()):
                raise ValueError("incomplete heldout factorial case pairing")
            paired[cohort][model_arm] = {}
            for cell in MATRIX:
                rows = cases[cell]
                paired[cohort][model_arm][cell] = dict(
                    cases=len(origin), correct=sum(v["success"] for v in rows.values()),
                    rescued=sum(rows[k]["success"] and not v["success"] for k, v in origin.items()),
                    harmed=sum(v["success"] and not rows[k]["success"] for k, v in origin.items()),
                    online_cpu_ns=sum(v["cpu_ns"] for v in rows.values()),
                    measured_steps=sum(v["steps"] for v in rows.values()),
                    verifier_calls=sum(v["verifier_calls"] for v in rows.values()),
                )
    costs = {}
    for arm, run in runs.items():
        receipt = run["report"]
        training = receipt["training"]
        costs[arm] = dict(actual_lifecycle_cpu_ns=receipt["actual_lifecycle_cpu_ns"],
            encoder_cpu_ns=run["encoder"]["cpu_ns"],
            teacher_cpu_ns=run["teacher"]["cpu_ns"],
            critic_cpu_ns=receipt["critic_cost"]["cpu_ns"],
            train_cpu_ns=sum(training[x]["cpu_ns"] for x in training),
            terminal_supervised_steps=training["attention"].get("terminal_eligible_step_examples", 0),
            terminal_withheld_steps=training["attention"].get("terminal_suppressed_step_examples", 0),
            oracle_feedback_calls=sum(training[x]["training_feedback_calls"]
                                      for x in ("core", "attention")),
            training_optimizer=training["attention"]["optimizer"],
            run_observation_sha256=_sha(run["rows"]))
    return dict(schema="hepta.group.feedback-factorial-independent.v1",
                passed=True, authority="DENY_ALL", production_promotion_permitted=False,
                source_consistent_not_independently_attested=True,
                causal_quality_or_10t_equivalence_proven=False,
                independently_future_tested=False, equal_total_compute_demonstrated=False,
                shared_stem_weight_counted_once_per_run_not_free_compute=True,
                reference="legacy_oracle", protocol_seed=control["protocol"]["seed"],
                training_profile=control["protocol"]["training_profile"],
                arm_protocol_sha256={k:_sha(v["protocol"]) for k,v in runs.items()},
                costs=costs, descriptive_paired=paired)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for arm in MATRIX:
        ap.add_argument("--" + arm.replace("_", "-"), required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    roots = {arm: getattr(args, arm) for arm in MATRIX}
    output = review_factorial(roots)
    with Path(args.output).open("x") as f:
        json.dump(output, f, sort_keys=True, allow_nan=False)


if __name__ == "__main__":
    main()
