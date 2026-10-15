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

SCHEMA = "hepta.six-track-paired-observation.v1"
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


def number(v, *, positive=False):
    if type(v) not in (float, int) or not math.isfinite(v) or v < 0 or (positive and v == 0):
        raise Invalid("missing/negative/nonfinite physical measurement")
    return float(v)


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


def check_cases(raw):
    if type(raw) is not list or not 1 <= len(raw) <= 50000:
        raise Invalid("missing cohort rows")
    cases, groups, sources, observed = {}, defaultdict(set), defaultdict(set), defaultdict(list)
    reader_by_task = defaultdict(dict)
    for r in raw:
        if type(r) is not dict:
            raise Invalid("invalid case row")
        cid, task = ident(r.get("case_id")), ident(r.get("task_id"))
        split, modality, reader = r.get("split"), r.get("modality"), r.get("reader_condition")
        if cid in cases or split not in SPLITS or modality not in MODALITY or reader not in READER:
            raise Invalid("duplicate case or unsupported split/modality/Reader")
        group = ident(r.get("source_group"))
        src = digest(r.get("input_sha256"))
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
    present = [s for s in SPLITS[:-1] if observed[s]]
    if any(max(observed[a]) >= min(observed[b]) for a, b in zip(present, present[1:])):
        raise Invalid("train/future time boundary violated")
    for s in EVAL_SPLITS:
        if not observed[s]:
            raise Invalid("missing prospective/holdout evaluation partition")
    for (split, task), by_condition in reader_by_task.items():
        if split in EVAL_SPLITS:
            if set(by_condition) != set(READER):
                raise Invalid("missing Reader four-condition task intervention")
            if len({r["label"] for r in by_condition.values()}) != 1:
                raise Invalid("Reader intervention changed original task answer")
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
    if type(arm.get("trainable_parameters")) is not int or arm["trainable_parameters"] < 0:
        raise Invalid("missing parameter accounting")
    if type(arm.get("train_cases")) is not int or arm["train_cases"] < 0:
        raise Invalid("missing data-exposure accounting")
    if type(arm.get("physical_forward_claimed")) is not bool:
        raise Invalid("unreported physical-forward status")
    costs = arm.get("costs")
    if type(costs) is not dict or set(costs) != set(COSTS):
        raise Invalid("incomplete lifecycle/resource cost breakdown")
    for key in COSTS:
        number(costs[key], positive=(key == "peak_rss_bytes"))
    if stage == "P4":
        number(arm.get("compute_budget_ms"), positive=True)
        if costs["ndu_ms"] > arm["compute_budget_ms"] and name == "ndu_solver":
            raise Invalid("NDU consumed more than its declared compute budget")
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
        q = number(row.get("observed_utility"))
        latency = number(row.get("end_to_end_ms"), positive=True)
        if p > 1 or q > 1:
            raise Invalid("unbounded outcome/probability")
        if type(row.get("completed")) is not bool:
            raise Invalid("missing completed/failed result")
        if not row["completed"] and q != 0:
            raise Invalid("failed task assigned positive utility")
        if stage == "P3":
            digest(row.get("generated_artifact_sha256"))
        if stage == "P5":
            effect = row.get("observed_effect_sha256")
            if row["completed"] and effect != case["expected_effect_sha256"]:
                raise Invalid("different physical effect than paired control")
            if not row["completed"] and effect is not None:
                raise Invalid("unreconciled effect represented as clean failure")
            if row.get("recovery_status") not in ("not_needed", "reconciled", "blocked"):
                raise Invalid("missing recovery/unknown-effect disposition")
        seen.add(cid)
        per_case[cid] = row
        if case["split"] in EVAL_SPLITS:
            by_split[case["split"]].append((case, row))
    if seen != set(cases):
        raise Invalid("missing case receipt")
    metrics = {}
    for split in EVAL_SPLITS:
        data = by_split[split]
        if not data:
            raise Invalid("incomplete future partition")
        correct = sum(int((r["positive_probability"] >= .5) == bool(c["label"])) for c, r in data)
        metrics[split] = {
            "case_count": len(data),
            "source_family_count": len({c["source_group"] for c, _ in data}),
            "accuracy": correct / len(data),
            "brier": sum((r["positive_probability"] - c["label"]) ** 2 for c, r in data) / len(data),
            "mean_observed_utility": sum(r["observed_utility"] for _, r in data) / len(data),
            "completion_rate": sum(r["completed"] for _, r in data) / len(data),
            "p50_ms": nearest_rank([r["end_to_end_ms"] for _, r in data], .5),
            "p95_ms": nearest_rank([r["end_to_end_ms"] for _, r in data], .95),
            "p99_ms": nearest_rank([r["end_to_end_ms"] for _, r in data], .99),
        }
    # Explicit total-cost accounting. The measured end-to-end request time ALREADY
    # includes Encoder/Reader/Head/NDU/Tool. Only one-time training/load/compile/
    # evaluation/migration work is additionally amortized over actual completed rows.
    n = len(rows)
    amortized = sum(costs[k] for k in ONE_TIME) / n
    metrics["lifecycle"] = {
        "observed_evaluation_requests": n,
        "one_time_work_ms": sum(costs[k] for k in ONE_TIME),
        "amortized_one_time_ms_per_request": amortized,
        "mean_e2e_plus_amortized_ms": sum(row["end_to_end_ms"] for row in rows) / n + amortized,
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
        # The intentionally more-data P2 control is reported separately and never
        # treated as an equal-data pair. It must be strictly larger, not relabeled.
        if stage == "P2" and study["parent_more_data"]["train_cases"] <= study["split_children"]["train_cases"]:
            raise Invalid("more-data control lacks additional independent exposure")
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
        "schema": "hepta.six-track-descriptive-adjudication.v1",
        "source_sha256": doc["source_sha256"],
        "cases": len(cases), "track_count": 6,
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
