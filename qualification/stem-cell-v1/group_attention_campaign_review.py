"""Independent stdlib-only replay of Group evidence-attention campaign records.

Recomputes symbolic labels from public text; never imports model, Torch,
teacher, fitting code, or checkpoint. Artifact identities are NOT signatures,
and untrusted self-reported execution timing is not hardware attestation.
"""
from __future__ import annotations

import argparse
from collections import defaultdict, Counter
import hashlib
import json
from pathlib import Path

from group_campaign_review import _parse

ARMS = ("static", "wide", "core", "attention",
        "core_fixed", "attention_fixed", "core_ndu", "attention_ndu")
DIRECT = ("static", "wide", "core", "attention")
SYSTEM2 = ("core_fixed", "attention_fixed", "core_ndu", "attention_ndu")
MODELS = {"static": "static", "wide": "wide", "core": "core",
          "attention": "attention", "core_fixed": "core",
          "attention_fixed": "attention", "core_ndu": "core",
          "attention_ndu": "attention"}
MODES = {"static": "direct", "wide": "direct", "core": "direct",
         "attention": "direct", "core_fixed": "fixed",
         "attention_fixed": "fixed", "core_ndu": "ndu",
         "attention_ndu": "ndu"}
INVALID_STATUSES = {"budget_exhausted", "callback_failed",
                    "resource_budget_stop", "ndu_stop:expired_policy",
                    "ndu_stop:continuation_support_violated"}
COHORTS = ("test", "long", "deleted", "composition")
REQUIRED_SOURCES = (
    "group_core.py", "group_training.py", "group_attention_curriculum.py",
    "group_step_supervision.py", "group_attention_campaign.py",
    "group_attention_campaign_review.py", "group_campaign_review.py",
    "group_tasks.py", "group_encoder.py", "group_features.py",
    "hf_encoder_kernel.py", "execution_meter.py", "aten_work.py",
    "group_campaign.py", "group_loop.py", "group_critic.py",
    "system2_execution.py", "ndu_continuation.py",
    "paired_execution.py", "transformer_work.py", "next_round_matrix.py",
)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _summarize(rows):
    times = sorted(x["wall_ns"] for x in rows)
    return dict(n=len(rows), correct=sum(x["success"] for x in rows),
                unsupported_attempts=sum(x["unsupported_attempt"] for x in rows),
                steps=sum(x["steps"] for x in rows),
                verifier_calls=sum(x["verifier_calls"] for x in rows),
                execution_statuses=dict(Counter(x["execution_status"] for x in rows)),
                cpu_ns=sum(x["cpu_ns"] for x in rows), wall_ns=sum(times),
                p50_ns=times[len(times) // 2],
                p95_ns=times[min(len(times) - 1, int(.95 * len(times)))])


def review(root):
    root = Path(root)
    protocol = json.loads((root / "protocol.json").read_text())
    rows = json.loads((root / "observations.json").read_text())
    report = json.loads((root / "report.json").read_text())
    teacher = json.loads((root / "teacher.json").read_text())
    encoder = json.loads((root / "encoder.json").read_text())
    if (protocol["schema"] != "hepta.group.paired-step-campaign.v1"
            or report["schema"] != "hepta.group.paired-step-observation.v1"
            or report["protocol_sha256"] != _digest(protocol)
            or tuple(protocol["frozen_candidate_arms"]) != ARMS
            or protocol["evaluation_cohorts"] != list(COHORTS)
            or report["authority"] != "DENY_ALL" or report["production_authorized"]
            or report["natural_future_win_established"]
            or report["equal_actual_training_work"]):
        raise ValueError("unregistered protocol, authority or unsupported efficacy assertion")
    hashes = protocol.get("source_sha256")
    if type(hashes) is not dict or set(hashes) != set(REQUIRED_SOURCES):
        raise ValueError("complete exact-source inventory required")
    for filename in REQUIRED_SOURCES:
        expected_sha = hashlib.sha256(
            (Path(__file__).parent / filename).read_bytes()).hexdigest()
        if hashes[filename] != expected_sha:
            raise ValueError("campaign or independent reviewer source SHA differs")
    public, seen_groups, replay_labels = protocol["public_cases"], {}, {}
    if set(public) != {"train", "validation", *COHORTS}:
        raise ValueError("complete training and heldout cohorts required")
    for cohort, cases in public.items():
        identifiers = set()
        seen_groups[cohort] = set()
        replay_labels[cohort] = {}
        for case in cases:
            cid, source = case["case_id"], case["source_group"]
            if cid in identifiers or source in seen_groups[cohort]:
                raise ValueError("duplicate public case or source group")
            identifiers.add(cid)
            seen_groups[cohort].add(source)
            answer, _, _ = _parse(case, missing=cohort == "deleted")
            replay_labels[cohort][cid] = answer
        if not cases:
            raise ValueError("empty heldout cohort")
    if not (seen_groups["train"] == set(protocol["train_source_groups"])):
        raise ValueError("training source membership drift")
    if any(seen_groups[a] & seen_groups[b] for a, b in
           (("train", "validation"), ("train", "test"), ("train", "long"),
            ("validation", "test"), ("validation", "long"), ("test", "long"))):
        raise ValueError("leaked train/test/long source groups")
    if (seen_groups["test"] != seen_groups["deleted"]
            or set(replay_labels["test"]) != set(replay_labels["deleted"])):
        raise ValueError("deleted cohort does not preserve original cases")
    if (protocol.get("critic_fit_splits") != ["validation_fit", "validation_calibration"]
            or protocol.get("live_system2_modes") != ["fixed", "ndu"]
            or not report.get("real_system2_callbacks_executed")
            or not report.get("same_model_critic_frozen_on_validation_only")):
        raise ValueError("live System2 and disjoint frozen-critic protocol required")
    critic = report.get("critic_cost")
    if (type(critic) is not dict or type(critic.get("cpu_ns")) is not int
            or critic["cpu_ns"] <= 0 or type(critic.get("wall_ns")) is not int
            or critic["wall_ns"] <= 0 or set(critic.get("receipts", {})) != {"core", "attention"}
            or not critic.get("separate_fits_charged")
            or critic.get("source_group_independence_claimed")):
        raise ValueError("measured frozen critics required")
    mid = len(public["validation"]) // 2
    for model_owner in ("core", "attention"):
        receipt = critic["receipts"][model_owner]
        metadata = receipt["metadata"]
        if (metadata["source_groups"]["fit"] != sorted(
                    c["source_group"] for c in public["validation"][:mid])
                or metadata["source_groups"]["calibration"] != sorted(
                    c["source_group"] for c in public["validation"][mid:])
                or receipt["parameters_sha256"] in ("", "0" * 64)
                or receipt["fit_rows"] != mid * 3
                or receipt["calibration_rows"] != (len(public["validation"]) - mid) * 3
                or metadata["future_support_guaranteed"]
                or metadata["confidence_bound_established"]):
            raise ValueError("critic source-bound validation provenance mismatch")
    if (teacher["source_groups_sha256"] != _digest(sorted(seen_groups["train"]))
            or teacher["authority"] != "DENY_ALL" or not teacher["train_only"]
            or teacher["supervised_steps"] < len(public["train"])
            or teacher["tokenizer_calls"] != len(public["train"])
            or report["teacher"] != teacher or report["encoder_cost"] != encoder
            or type(encoder["actual_forward_calls"]) is not int
            or encoder["actual_forward_calls"] <= 0):
        raise ValueError("teacher or physical Encoder receipt mismatch")
    training = report["training"]
    if (set(training) != set(DIRECT)
            or training["core"]["sample_and_depth_sha256"] !=
               training["attention"]["sample_and_depth_sha256"]
            or training["core"]["parameter_count"] != training["attention"]["parameter_count"]
            or not training["attention"]["attention_supervision_enabled"]
            or training["core"]["attention_supervision_enabled"]
            or training["attention"]["attention_target_sha256"] !=
               teacher["teacher_tensor_sha256"]):
        raise ValueError("paired training schedule or teacher digest mismatch")
    for name in DIRECT:
        receipt = training[name]
        if (receipt["status"] != "completed" or
                receipt["completed_steps"] != protocol["steps"] or
                receipt["seed"] != protocol["seed"] or
                receipt["cpu_ns"] <= 0 or receipt["wall_ns"] <= 0 or
                receipt["parameter_count"] <= 0):
            raise ValueError("partial or unmeasured training")
    expected = {(cohort, arm, case["case_id"]) for cohort in COHORTS
                for arm in ARMS for case in public[cohort]}
    cases = {cohort: {r["case_id"]: r for r in public[cohort]} for cohort in COHORTS}
    seen, by_arm, model_hashes, feature_hashes = set(), defaultdict(list), defaultdict(set), defaultdict(set)
    for row in rows:
        key = row["cohort"], row["arm"], row["case_id"]
        if key not in expected or key in seen:
            raise ValueError("unexpected, duplicate or out-of-cohort observation")
        seen.add(key)
        cohort, arm, cid = key
        case = cases[cohort][cid]
        label = replay_labels[cohort][cid]
        mode = MODES[arm]
        if (type(row["prediction"]) is not int
                or not -1 <= row["prediction"] <= 7
                or type(row["success"]) is not bool
                or type(row["valid_execution"]) is not bool
                or type(row["evidence_supported"]) is not bool
                or type(row["unsupported_attempt"]) is not bool
                or type(row["execution_status"]) is not str
                or row["execution_mode"] != mode
                or row["source_group"] != case["source_group"]
                or row["evidence_supported"] != (label is not None)
                or row["unsupported_attempt"] != (label is None)
                or row["valid_execution"] !=
                   (row["execution_status"] not in INVALID_STATUSES)
                or row["success"] != (label is not None
                                     and row["valid_execution"]
                                     and row["prediction"] == label)):
            raise ValueError("independently replayed evidence outcome differs")
        if (type(row["steps"]) is not int or not 1 <= row["steps"] <= 4
                or type(row["verifier_calls"]) is not int
                or not 0 <= row["verifier_calls"] <= 4):
            raise ValueError("bounded physical System2 steps and verifier calls required")
        if mode == "direct":
            if (row["execution_status"] != "direct_forward"
                    or row["steps"] != (1 if arm in ("static", "wide") else 4)
                    or row["verifier_calls"] != 0
                    or row["search_formula_work"] is not None
                    or row["prediction"] == -1):
                raise ValueError("direct control contains fabricated System2 work")
        else:
            if (row["execution_status"] == "direct_forward"
                    or row["verifier_calls"] != row["steps"]
                    or type(row["search_formula_work"]) is not int
                    or row["search_formula_work"] <= 0
                    or mode == "fixed" and row["steps"] != 4
                    or (row["execution_status"] == "verifier_accepted_not_independent_eval")
                        != row["success"]):
                raise ValueError("missing or inconsistent actual System2 verifier/compute evidence")
        if any(type(row[name]) is not int or row[name] <= 0
               for name in ("wall_ns", "cpu_ns")):
            raise ValueError("missing physical observation")
        for field in ("feature_sha256", "model_sha256"):
            value = row[field]
            if (type(value) is not str or len(value) != 64
                    or any(c not in "0123456789abcdef" for c in value)):
                raise ValueError("unbound digest")
        feature_hashes[(cohort, cid)].add(row["feature_sha256"])
        model_hashes[arm].add(row["model_sha256"])
        by_arm[f"{cohort}.{arm}"].append(row)
    if seen != expected or any(len(v) != 1 for v in
                               (*feature_hashes.values(), *model_hashes.values())):
        raise ValueError("incomplete pairs, drifting frozen models or feature mismatch")
    for arm, owner in MODELS.items():
        if model_hashes[arm] != model_hashes[owner]:
            raise ValueError("loop execution changed the frozen model artifact")
    for cid in replay_labels["test"]:
        if feature_hashes[("deleted", cid)] == feature_hashes[("test", cid)]:
            raise ValueError("deleted and original evidence cannot reuse a snapshot")
    summaries = {k: _summarize(values) for k, values in by_arm.items()}
    if report["summaries"] != summaries:
        raise ValueError("reported scores/timing disagree with complete raw observations")
    # Paired deltas are descriptive evidence, not a causal model or matched
    # total-compute acceptance test. Recompute directly from raw observations.
    paired = {}
    for cohort in COHORTS:
        core_rows = {r["case_id"]: r for r in by_arm[f"{cohort}.core"]}
        candidate_rows = {r["case_id"]: r for r in by_arm[f"{cohort}.attention"]}
        if core_rows.keys() != candidate_rows.keys():
            raise ValueError("attention/core pairs do not match")
        rescued = sum(candidate_rows[k]["success"] and not v["success"]
                      for k, v in core_rows.items())
        harmed = sum(v["success"] and not candidate_rows[k]["success"]
                     for k, v in core_rows.items())
        paired[cohort] = dict(n=len(core_rows), rescued=rescued, harmed=harmed,
            correct_delta=rescued-harmed,
            core_online_cpu_ns=sum(v["cpu_ns"] for v in core_rows.values()),
            attention_online_cpu_ns=sum(v["cpu_ns"] for v in candidate_rows.values()),
            core_training_cpu_ns=training["core"]["cpu_ns"],
            attention_training_cpu_ns=training["attention"]["cpu_ns"],
            equal_total_compute_demonstrated=False,
            independent_future_samples_established=False)
    loop_comparisons = {}
    for cohort in COHORTS:
        loop_comparisons[cohort] = {}
        for mode in ("fixed", "ndu"):
            left = {r["case_id"]: r for r in by_arm[f"{cohort}.core_{mode}"]}
            right = {r["case_id"]: r for r in by_arm[f"{cohort}.attention_{mode}"]}
            if left.keys() != right.keys():
                raise ValueError("missing paired System2 episode")
            loop_comparisons[cohort][mode] = dict(
                n=len(left),
                rescued=sum(right[k]["success"] and not v["success"] for k,v in left.items()),
                harmed=sum(v["success"] and not right[k]["success"] for k,v in left.items()),
                baseline_verifier_calls=sum(v["verifier_calls"] for v in left.values()),
                candidate_verifier_calls=sum(v["verifier_calls"] for v in right.values()),
                baseline_cpu_ns=sum(v["cpu_ns"] for v in left.values()),
                candidate_cpu_ns=sum(v["cpu_ns"] for v in right.values()),
                equal_total_compute_demonstrated=False,
                model_execution_independently_attested=False)
    return dict(schema="hepta.group.paired-attention-independent-review.v1",
                passed=True, authority="DENY_ALL",
                complete_group_replay=True,
                public_evidence_labels_independently_recomputed=True,
                teacher_bound_to_train_sources=True,
                same_initial_core_claim_still_unattested=True,
                equal_compute_claim_allowed=False,
                real_host_execution_independently_attested=False,
                future_task_efficacy_proved=False,
                descriptive_paired=paired,
                real_system2_descriptive_paired=loop_comparisons,
                observation_sha256=_digest(rows),
                protocol_sha256=_digest(protocol),
                paired_summaries=summaries)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    with Path(args.output).open("x") as stream:
        json.dump(review(args.root), stream, sort_keys=True, allow_nan=False)


if __name__ == "__main__":
    main()
