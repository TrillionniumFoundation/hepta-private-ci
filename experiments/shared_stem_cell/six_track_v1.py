#!/usr/bin/env python3
"""Source-locked P0-P5 paired research scorer; never a model or effect authorizer.

No generated fixture, claimed digest, or passed unit test establishes real-model
execution, independent outcome provenance, physical cost, or production readiness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

SCHEMA = "hepta.six-track-paired-observation.v3"
SHA_KEYS = ("source_sha256", "plan_sha256", "dataset_sha256", "evaluator_sha256")
SPLITS = ("train", "calibration", "test", "future1", "future2", "future3", "ood")
EVAL_SPLITS = ("test", "future1", "future2", "future3", "ood")
READER = ("none", "retrieved", "sufficient", "premise_removed")
MODALITY = ("text", "image", "audio", "video")
ARMS = {
    "P0": ("granite_frozen", "granite_learned", "mmbert_frozen", "mmbert_learned",
           "gemma_frozen", "gemma_learned", "laya_frozen", "laya_learned"),
    "P1": ("shared_frozen", "shared_learned", "replicated_frozen", "replicated_learned"),
    "P2": ("parent_unsplit", "split_children", "matched_unsplit", "parent_more_data"),
    "P3": ("text_only", "image_text", "audio_text", "temporal_video",
           "scrambled_media", "multimodal_generator"),
    "P4": ("no_search", "bellman", "critic", "tree_search", "standard_optimizer", "ndu_solver"),
    "P5": ("typed", "mcp_steps", "mcp_batch", "native_cpu", "native_gpu"),
}
PAIRS = {
    "P0": (("granite_learned", "granite_frozen"), ("mmbert_learned", "mmbert_frozen"),
           ("gemma_learned", "gemma_frozen"), ("laya_learned", "laya_frozen")),
    "P1": (("shared_learned", "shared_frozen"), ("shared_learned", "replicated_learned")),
    "P2": (("split_children", "parent_unsplit"), ("split_children", "matched_unsplit")),
    "P3": (("multimodal_generator", "text_only"), ("temporal_video", "scrambled_media")),
    "P4": (("ndu_solver", "bellman"), ("ndu_solver", "critic"),
           ("ndu_solver", "tree_search"), ("ndu_solver", "standard_optimizer")),
    "P5": (("native_cpu", "typed"), ("native_cpu", "mcp_batch"),
           ("native_gpu", "typed"), ("native_gpu", "mcp_batch")),
}
# Exactly these mutually named observables are required. CPU/GPU are work times,
# not added to wall time. End-to-end times already include inference/effect work.
COSTS = ("load_ms", "encode_ms", "reader_ms", "head_ms", "decoder_ms",
         "routing_ms", "ndu_ms", "jit_ms", "effect_ms", "checkpoint_ms",
         "retry_ms", "training_ms", "evaluation_ms", "migration_ms",
         "cpu_ms", "gpu_ms", "peak_rss_bytes", "peak_gpu_bytes", "energy_joules")
ONE_TIME = ("load_ms", "training_ms", "jit_ms", "evaluation_ms", "migration_ms")


class Invalid(ValueError):
    """Unusable comparison; never replace missing work with zero."""


def digest(s):
    if type(s) is not str or len(s) != 64 or s == "0" * 64 or any(c not in "0123456789abcdef" for c in s):
        raise Invalid("missing or malformed SHA256 identity")
    return s


def ident(s):
    if type(s) is not str or not 1 <= len(s) <= 128 or not all(
        c.isascii() and (c.isalnum() or c in "._:-") for c in s
    ):
        raise Invalid("malformed bounded identity")
    return s


# A single claimed physical scalar bigger than 10^18 cannot represent a
# credible observed per-request time/byte/energy measurement in this study.
# Bound it before accumulation, independent of the JSON parser's int limits.
MAX_SCALAR = 10**18


def number(v, *, positive=False):
    if type(v) not in (float, int) or v < 0 or (positive and v == 0):
        raise Invalid("missing/negative/nonfinite physical measurement")
    try:
        value = float(v)
    except (OverflowError, ValueError) as exc:
        raise Invalid("missing/negative/nonfinite physical measurement") from exc
    if not math.isfinite(value) or value > MAX_SCALAR:
        raise Invalid("missing/negative/nonfinite physical measurement")
    return value


def signed_utility(v):
    """An observed result may have negative net utility or a failure penalty."""
    if type(v) not in (float, int):
        raise Invalid("missing/nonfinite/out-of-bound signed utility")
    try:
        value = float(v)
    except (OverflowError, ValueError) as exc:
        raise Invalid("missing/nonfinite/out-of-bound signed utility") from exc
    if not math.isfinite(value) or not -1 <= value <= 1:
        raise Invalid("missing/nonfinite/out-of-bound signed utility")
    return value


def _pairs(items):
    d = {}
    for k, v in items:
        if k in d:
            raise Invalid("duplicate JSON key")
        d[k] = v
    return d


def load_json(path):
    raw = Path(path).read_bytes()
    if not 2 <= len(raw) <= 16 * 1024 * 1024:
        raise Invalid("observation absent or oversized")
    return json.loads(raw, object_pairs_hook=_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(Invalid("nonfinite JSON"))), hashlib.sha256(raw).hexdigest()


def nearest_rank(values, p):
    if not values:
        raise Invalid("empty latency samples")
    return sorted(values)[max(0, math.ceil(p * len(values)) - 1)]


def supported_nearest_rank(values, p, minimum):
    """Do not publish a tail percentile on an inadequate request sample."""
    return nearest_rank(values, p) if len(values) >= minimum else None


def check_cases(raw):
    if type(raw) is not list or not 1 <= len(raw) <= 50000:
        raise Invalid("missing cohort rows")
    cases, groups, sources, observed = {}, defaultdict(set), defaultdict(set), defaultdict(list)
    # A declared independent source family cannot recycle identical input bytes
    # under another family name to inflate paired bootstrap/source counts.
    source_owner_by_input = {}
    # This is a task-INSTANCE identifier, not a reusable task type. Its
    # presence in a second split leaks prior task identity across windows even
    # if the surrounding context and source-group strings have changed.
    task_split_owner = {}
    reader_by_task = defaultdict(dict)
    for r in raw:
        if type(r) is not dict:
            raise Invalid("invalid case row")
        cid, task = ident(r.get("case_id")), ident(r.get("task_id"))
        split, modality, reader = r.get("split"), r.get("modality"), r.get("reader_condition")
        if cid in cases or split not in SPLITS or modality not in MODALITY or reader not in READER:
            raise Invalid("duplicate case or unsupported split/modality/Reader")
        previous_split = task_split_owner.setdefault(task, split)
        if previous_split != split:
            raise Invalid("task instance identity reused across temporal cohorts")
        group = ident(r.get("source_group"))
        src = digest(r.get("input_sha256"))
        original_owner = source_owner_by_input.setdefault(src, (split, group))
        if original_owner != (split, group):
            raise Invalid("identical input reused across distinct source families")
        number(r.get("observed_at"), positive=True)
        if type(r.get("label")) is not int or r["label"] not in (0, 1):
            raise Invalid("binary externally supplied label missing")
        digest(r.get("expected_effect_sha256"))
        rk = (split, task)
        if reader in reader_by_task[rk]:
            raise Invalid("repeated Reader condition in task")
        reader_by_task[rk][reader] = r
        groups[split].add(group)
        sources[split].add(src)
        observed[split].append(r["observed_at"])
        cases[cid] = r
    for i, a in enumerate(SPLITS):
        for b in SPLITS[i+1:]:
            if groups[a] & groups[b] or sources[a] & sources[b]:
                raise Invalid("source/input leakage between evaluation cohorts")
    if not observed["train"] or not observed["calibration"]:
        raise Invalid("missing train/calibration partition")
    present = [s for s in SPLITS[:-1] if observed[s]]
    if any(max(observed[a]) >= min(observed[b]) for a, b in zip(present, present[1:])):
        raise Invalid("train/future time boundary violated")
    for s in EVAL_SPLITS:
        if not observed[s]:
            raise Invalid("missing prospective/holdout evaluation partition")
    if min(observed["ood"]) <= max(max(observed["train"]), max(observed["calibration"])):
        raise Invalid("OOD examples must occur after train/calibration freeze")
    for (split, task), by_condition in reader_by_task.items():
        if split in EVAL_SPLITS:
            if set(by_condition) != set(READER):
                raise Invalid("missing Reader four-condition task intervention")
            if len({r["label"] for r in by_condition.values()}) != 1:
                raise Invalid("Reader intervention changed original task answer")
            if (by_condition["sufficient"]["input_sha256"]
                    == by_condition["premise_removed"]["input_sha256"]):
                raise Invalid("Reader sufficient/premise-removed intervention has identical input bytes")
            for key in ("modality", "source_group", "expected_effect_sha256"):
                if len({r[key] for r in by_condition.values()}) != 1:
                    raise Invalid("Reader intervention changed original task media/source/effect")
    if not {r["modality"] for r in cases.values()} >= set(MODALITY):
        raise Invalid("not all real media modes declared")
    return cases, groups


def check_arm(stage, name, arm, cases):
    if type(arm) is not dict or arm.get("name") != name:
        raise Invalid("arm name/source misbinding")
    if arm.get("authority") != "DENY_ALL" or arm.get("production_promotion_permitted") is not False:
        raise Invalid("fabricated execution authority")
    for k in ("model_sha256", "initial_head_sha256", "final_head_sha256", "train_data_sha256", "optimizer_sha256"):
        digest(arm.get(k))
    if type(arm.get("train_steps")) is not int or arm["train_steps"] < 0:
        raise Invalid("missing training step census")
    if stage in ("P0", "P1"):
        if name.endswith("_frozen"):
            if arm["train_steps"] != 0:
                raise Invalid("frozen Head cannot report optimizer steps")
            if arm["initial_head_sha256"] != arm["final_head_sha256"]:
                raise Invalid("frozen Head changed weights without training")
        if name.endswith("_learned"):
            if arm["train_steps"] == 0:
                raise Invalid("learned Head has no optimizer steps")
            if arm["initial_head_sha256"] == arm["final_head_sha256"]:
                raise Invalid("learned Head weights did not change")
    if type(arm.get("trainable_parameters")) is not int or arm["trainable_parameters"] < 0:
        raise Invalid("missing parameter accounting")
    if stage in ("P0", "P1") and name.endswith("_learned") and not arm["trainable_parameters"]:
        raise Invalid("learned Head has zero trainable parameters")
    if type(arm.get("train_cases")) is not int or arm["train_cases"] < 0:
        raise Invalid("missing data-exposure accounting")
    if type(arm.get("physical_forward_claimed")) is not bool:
        raise Invalid("unreported physical-forward status")
    if "e2e_includes_one_time" in arm:
        raise Invalid("obsolete all-or-nothing one-time cost flag")
    one_time_in_e2e = arm.get("one_time_in_e2e")
    if (type(one_time_in_e2e) is not dict or set(one_time_in_e2e) != set(ONE_TIME)
            or any(type(included) is not bool for included in one_time_in_e2e.values())):
        raise Invalid("missing per-component one-time cost inclusion evidence")
    costs = arm.get("costs")
    if type(costs) is not dict or set(costs) != set(COSTS):
        raise Invalid("incomplete lifecycle/resource cost breakdown")
    for key in COSTS:
        number(costs[key], positive=(key == "peak_rss_bytes"))
    if stage == "P4":
        # The registered compute ceiling is PER CASE. Do not compare total
        # arm-level NDU milliseconds to one request's solver budget.
        number(arm.get("compute_budget_ms"), positive=True)
    rows = arm.get("results")
    if type(rows) is not list or len(rows) != len(cases):
        raise Invalid("missing/extra paired case results")
    seen, by_split, per_case = set(), defaultdict(list), {}
    for row in rows:
        if type(row) is not dict:
            raise Invalid("malformed result")
        cid = ident(row.get("case_id"))
        if cid in seen or cid not in cases:
            raise Invalid("duplicate/foreign case prediction")
        case = cases[cid]
        if row.get("input_sha256") != case["input_sha256"]:
            raise Invalid("incorrect or swapped input identity")
        if row.get("prelabel_sealed") is not True:
            raise Invalid("outcome-dependent/unsealed prediction")
        digest(row.get("trace_sha256"))
        p = number(row.get("positive_probability"))
        q = signed_utility(row.get("observed_utility"))
        latency = number(row.get("end_to_end_ms"), positive=True)
        if p > 1:
            raise Invalid("unbounded probability")
        if type(row.get("completed")) is not bool:
            raise Invalid("missing completed/failed result")
        if not row["completed"] and q > 0:
            raise Invalid("failed task assigned positive utility")
        if stage == "P3":
            digest(row.get("generated_artifact_sha256"))
        if stage == "P4":
            solver_ms = number(row.get("measured_solver_ms"))
            if solver_ms > arm["compute_budget_ms"]:
                raise Invalid("actual P4 compute exceeded matched budget")
        if stage == "P5":
            effect = row.get("observed_effect_sha256")
            if row["completed"] and effect != case["expected_effect_sha256"]:
                raise Invalid("different physical effect than paired control")
            if not row["completed"] and effect is not None:
                raise Invalid("unreconciled effect represented as clean failure")
            if row.get("recovery_status") not in ("not_needed", "reconciled", "blocked"):
                raise Invalid("missing recovery/unknown-effect disposition")
            if row["completed"] and row["recovery_status"] == "blocked":
                raise Invalid("blocked effect cannot be reported completed")
        seen.add(cid)
        per_case[cid] = row
        if case["split"] in EVAL_SPLITS:
            by_split[case["split"]].append((case, row))
    if seen != set(cases):
        raise Invalid("missing case receipt")
    if stage == "P4" and name == "ndu_solver":
        actual_total_solver_ms = sum(
            result["measured_solver_ms"] for result in per_case.values()
        )
        if costs["ndu_ms"] + 1e-6 < actual_total_solver_ms:
            raise Invalid("NDU aggregate cost underreports measured per-case solver work")
    metrics = {}
    for split in EVAL_SPLITS:
        data = by_split[split]
        if not data:
            raise Invalid("incomplete future partition")
        correct = sum(int((r["positive_probability"] >= .5) == bool(c["label"])) for c, r in data)
        completed_and_correct = sum(
            int(r["completed"] and (r["positive_probability"] >= .5) == bool(c["label"]))
            for c, r in data
        )
        latencies = [r["end_to_end_ms"] for _, r in data]
        metrics[split] = {
            "case_count": len(data),
            "source_family_count": len({c["source_group"] for c, _ in data}),
            "distinct_task_count": len({c["task_id"] for c, _ in data}),
            "accuracy": correct / len(data),
            "accuracy_counts_predictions_even_if_execution_failed": True,
            "completed_and_correct_fraction": completed_and_correct / len(data),
            "brier": sum((r["positive_probability"] - c["label"]) ** 2 for c, r in data) / len(data),
            "mean_observed_utility": sum(r["observed_utility"] for _, r in data) / len(data),
            "negative_utility_count": sum(r["observed_utility"] < 0 for _, r in data),
            "completion_rate": sum(r["completed"] for _, r in data) / len(data),
            "p50_ms": supported_nearest_rank(latencies, .5, 3),
            "p95_ms": supported_nearest_rank(latencies, .95, 20),
            "p99_ms": supported_nearest_rank(latencies, .99, 100),
            "tail_percentiles_are_request_samples_not_independent_families": True,
        }
    # End-to-end request latency includes request execution, but different
    # one-off costs may or may not appear in the measured request stream. Charge
    # EACH missing component once: an all-or-nothing flag can silently erase
    # e.g. model training cost because model load happened inside one request.
    # Train/calibration case forwards cannot silently inflate the effective
    # number of measured holdout/future/OOD serving requests. The experiment
    # horizon is exactly its observed EVAL_SPLITS; no invented lifetime reuse.
    n = sum(len(by_split[split]) for split in EVAL_SPLITS)
    if n == 0:
        raise Invalid("no evaluation requests for lifecycle cost")
    not_in_e2e = sum(costs[k] for k in ONE_TIME if not one_time_in_e2e[k])
    amortized = not_in_e2e / n
    measured_e2e = sum(
        row["end_to_end_ms"] for split in EVAL_SPLITS for _, row in by_split[split]
    )
    metrics["lifecycle"] = {
        "observed_all_split_requests": len(rows),
        "observed_evaluation_requests": n,
        "excluded_training_calibration_requests": len(rows) - n,
        "one_time_work_ms": sum(costs[k] for k in ONE_TIME),
        "one_time_not_in_e2e_ms": not_in_e2e,
        "one_time_included_in_e2e": dict(one_time_in_e2e),
        "amortized_one_time_ms_per_request": amortized,
        "mean_e2e_plus_amortized_ms": measured_e2e / n + amortized,
        "reported_peak_rss_bytes": costs["peak_rss_bytes"],
        "reported_peak_gpu_bytes": costs["peak_gpu_bytes"],
        "reported_energy_joules": costs["energy_joules"],
        "costs_are_self_reported_not_independently_attested": True,
    }
    return metrics, per_case


def audit(doc):
    if type(doc) is not dict or doc.get("schema") != SCHEMA or doc.get("authority") != "DENY_ALL" or doc.get("production_promotion_permitted") is not False:
        raise Invalid("non-authorizing six-track schema required")
    for k in SHA_KEYS:
        digest(doc.get(k))
    cases, groups = check_cases(doc.get("cases"))
    stage_data = doc.get("tracks")
    if type(stage_data) is not dict or set(stage_data) != set(ARMS):
        raise Invalid("incomplete P0-P5 experiment tracks")
    out = {}
    for stage, names in ARMS.items():
        study = stage_data[stage]
        if type(study) is not dict or set(study) != set(names):
            raise Invalid("missing/duplicated strong baseline arm")
        metrics, original_rows = {}, {}
        for name in names:
            metrics[name], original_rows[name] = check_arm(stage, name, study[name], cases)
        # Local, actually-trained family comparisons must not smuggle extra
        # examples, steps, params, or altered frozen initial weights into a gain.
        for left, right in PAIRS[stage]:
            a, b = study[left], study[right]
            if a["train_data_sha256"] != b["train_data_sha256"] or a["train_cases"] != b["train_cases"]:
                raise Invalid("unmatched source/example exposure between paired candidates")
            if a["model_sha256"] != b["model_sha256"]:
                raise Invalid("base model changed inside purported same-Stem comparison")
            if stage in ("P1", "P2") and a["optimizer_sha256"] != b["optimizer_sha256"]:
                raise Invalid("optimizer changed inside purported same-learning comparison")
            if stage in ("P1", "P2", "P4") and a["train_steps"] != b["train_steps"]:
                raise Invalid("unmatched learning effort in causal comparison")
            if stage == "P2" and a["trainable_parameters"] != b["trainable_parameters"]:
                raise Invalid("split not matched to unsplit parameter count")
            if stage == "P4" and a["compute_budget_ms"] != b["compute_budget_ms"]:
                raise Invalid("different NDU and cheap-control compute budgets")
            if stage in ("P0", "P1") and left.endswith("learned") and right.endswith("frozen"):
                if a["initial_head_sha256"] != b["initial_head_sha256"]:
                    raise Invalid("frozen and trainable Head start differently")
                if a["final_head_sha256"] == a["initial_head_sha256"]:
                    raise Invalid("Head learning claimed but physical parameter identity unchanged")
                if b["final_head_sha256"] != b["initial_head_sha256"]:
                    raise Invalid("frozen baseline weight mutated")
        # Reject aliased P0 model identities and nonmatched training schedules.
        if stage == "P0":
            learned = [study[family + "_learned"] for family in ("granite", "mmbert", "gemma", "laya")]
            if len({arm["model_sha256"] for arm in learned}) != 4:
                raise Invalid("P0 model families alias one physical model identity")
            for field in ("train_data_sha256", "train_cases", "train_steps", "optimizer_sha256"):
                if len({arm[field] for arm in learned}) != 1:
                    raise Invalid("P0 encoder comparison changed common training budget")
        if stage == "P1":
            a, b = study["shared_learned"], study["replicated_learned"]
            if a["initial_head_sha256"] != b["initial_head_sha256"]:
                raise Invalid("P1 shared/replicated Head initialization differs")
            if a["trainable_parameters"] != b["trainable_parameters"]:
                raise Invalid("P1 shared/replicated private Head parameter budget differs")
        # Larger-data control cannot reuse the identical smaller dataset identity;
        # different hashes alone never authenticate independent real observations.
        if stage == "P2":
            if study["parent_more_data"]["train_cases"] <= study["split_children"]["train_cases"]:
                raise Invalid("more-data control lacks additional independent exposure")
            if study["parent_more_data"]["train_data_sha256"] == study["split_children"]["train_data_sha256"]:
                raise Invalid("more-data control reused identical training dataset identity")
        deltas = {}
        for left, right in PAIRS[stage]:
            left_data, right_data = original_rows[left], original_rows[right]
            per_split = {}
            for split in EVAL_SPLITS:
                family_deltas = defaultdict(list)
                for cid, case in cases.items():
                    if case["split"] == split:
                        family_deltas[case["source_group"]].append(
                            left_data[cid]["observed_utility"] - right_data[cid]["observed_utility"]
                        )
                family_means = [sum(vals) / len(vals) for vals in family_deltas.values()]
                n = len(family_means)
                per_split[split] = {
                    "family_count": n,
                    "mean_paired_utility_difference": sum(family_means) / n,
                    "positive_families": sum(x > 0 for x in family_means),
                    "negative_families": sum(x < 0 for x in family_means),
                    "ties": sum(x == 0 for x in family_means),
                    "insufficient_independent_families_for_efficacy": n < 30,
                }
            deltas[f"{left}__vs__{right}"] = per_split
        out[stage] = {"arms": metrics, "paired_family_differences": deltas,
                      "full_six_track_production_acceptance": False}
    # Even a complete locally supplied corpus does not authenticate independently
    # observed real labels, weights, exact CPU/GPU execution or FinalUse.
    return {
        "schema": "hepta.six-track-descriptive-adjudication.v3",
        "task_instance_ids_cross_split_rejected": True,
        "task_identity_provenance_independently_verified": False,
        "source_sha256": doc["source_sha256"],
        "cases": len(cases),
        "distinct_input_sha256_count": len({case["input_sha256"] for case in cases.values()}),
        "independent_source_groups_not_cryptographically_attested": True,
        "track_count": 6,
        "tracks": out,
        "independent_outcome_provenance_verified": False,
        "prelabel_seals_independently_verified": False,
        "physical_host_cost_authenticated": False,
        "true_generation_quality_verified": False,
        "future_ndu_superiority_established": False,
        "jit_mcp_end_to_end_superiority_established": False,
        "statistical_model_winner_selected": False,
        "production_promotion_permitted": False,
        "authority": "DENY_ALL",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    doc, raw_digest = load_json(args.observations)
    result = audit(doc)
    result["observation_bytes_sha256"] = raw_digest
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(result, out, sort_keys=True, indent=2, allow_nan=False)
        out.write("\n")


if __name__ == "__main__":
    main()
