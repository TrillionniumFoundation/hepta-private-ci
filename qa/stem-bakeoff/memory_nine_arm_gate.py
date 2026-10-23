"""Fail-closed, independent A-I MemoryCell comparison census and scientific gate.

This module never runs a model, trains a Head, certifies remote signatures,
authorizes a memory writer, or accepts self-scored model success. Synthetic
unit fixtures test the gate, never count as research observations.

The original source/corpus and evaluator-only gold must be provided separately
from the generation worker. Scores are reconstructed from source frames, not
from a generator's claimed retrieval score.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import random
import statistics

ARMS = {
    "A": "bm25",
    "B": "dense_bm25_reranker",
    "C": "source_grounded_graph_rag",
    "D": "typed_untrained",
    "E": "shared_encoder_single_trained_head",
    "F": "shared_encoder_multi_typed_heads",
    "G": "learned_sparse_router",
    "H": "learned_meta_graph",
    "I": "split_merge_evolution",
}
COMPARISONS = (
    ("B", "A"), ("C", "B"), ("D", "C"), ("E", "D"),
    ("F", "E"), ("G", "F"), ("H", "G"), ("I", "H"),
    ("I", "B"), ("I", "C"),
)
SPLITS = ("train", "calibration", "future_1", "future_2",
          "ood", "adversarial", "deletion")
PRIMARY = ("future_1", "future_2", "ood")
HEX = set("0123456789abcdef")
SCHEMA = "hepta.memory.nine-arm.v1"
POLICY = {
    "schema": SCHEMA,
    "arms": ARMS,
    "comparisons": COMPARISONS,
    "primary_splits": PRIMARY,
    "max_sources": 8,
    "max_context_utf8_bytes": 4096,
    "max_reader_input_tokens": 1024,
    "max_reader_output_tokens": 64,
    "min_independent_groups_per_primary_split": 200,
    "min_absolute_quality_delta": 0.02,
    "alpha_familywise": 0.05,
    "bootstrap_samples": 2000,
    "bootstrap_seed": 20261023,
    "max_cost_ratio_to_strong_baseline": 1.10,
    "required_negative_controls": [
        "wrong_edge", "swapped_head", "missing_support",
        "withdrawn_ancestor", "static_topology",
    ],
    "requested_authority": "DENY_ALL",
    "production_activation_allowed": False,
}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _digest(value):
    return (type(value) is str and len(value) == 64
            and all(char in HEX for char in value))


def _nonnegative_int(value):
    return type(value) is int and value >= 0


def _strict_pairs(pairs):
    result = {}
    for name, value in pairs:
        _require(name not in result, "duplicate JSON key")
        result[name] = value
    return result


def _reject_constant(value):
    raise ValueError("nonfinite JSON constant: " + value)


def read_json(path, *, max_bytes=64 * 1024 * 1024):
    raw = Path(path).read_bytes()
    _require(0 < len(raw) <= max_bytes, "JSON input missing or unbounded")
    return json.loads(raw, object_pairs_hook=_strict_pairs,
                      parse_constant=_reject_constant)


def read_jsonl(path):
    raw = Path(path).read_bytes()
    _require(len(raw) <= 256 * 1024 * 1024, "observation file exceeds bound")
    if not raw:
        return []
    _require(raw.endswith(b"\n"), "observation JSONL must end with newline")
    return [json.loads(line, object_pairs_hook=_strict_pairs,
                       parse_constant=_reject_constant)
            for line in raw.splitlines()]


def _source_index(cohort):
    _require(type(cohort) is dict and cohort.get("schema") == SCHEMA,
             "invalid cohort schema")
    sources, questions = cohort.get("sources"), cohort.get("questions")
    _require(type(sources) is list and type(questions) is list
             and sources and questions, "empty source/question census")
    by_source, by_question, roots = {}, {}, {}
    for item in sources:
        _require(type(item) is dict and type(item.get("source_id")) is str
                 and type(item.get("group")) is str
                 and type(item.get("frame")) is str
                 and item["source_id"] and item["group"], "invalid source")
        key = (item["group"], item["source_id"])
        _require(key not in by_source, "duplicate source/root")
        by_source[key] = item["frame"]
    for item in questions:
        _require(type(item) is dict and type(item.get("query_id")) is str
                 and type(item.get("group")) is str
                 and item.get("split") in SPLITS
                 and type(item.get("gold_support_ids")) is list
                 and type(item.get("answerable")) is bool
                 and _digest(item.get("question_sha256")),
                 "invalid evaluator-only question")
        qid, group, split = item["query_id"], item["group"], item["split"]
        _require(qid not in by_question and qid and group, "duplicate query")
        _require(roots.setdefault(group, split) == split,
                 "same source family crosses cohort splits")
        expected = item["gold_support_ids"]
        _require(all(type(x) is str for x in expected)
                 and len(set(expected)) == len(expected), "duplicate gold refs")
        # Missing annotated evidence is reported, never silently repaired.
        _require(any(root == group for root, _ in by_source),
                 "question has no source family")
        by_question[qid] = item
    return by_source, by_question, roots


def _read_plan(plan, cohort_bytes):
    _require(type(plan) is dict and plan.get("schema") == SCHEMA
             and plan.get("policy_sha256") == sha(canonical(POLICY))
             and plan.get("cohort_sha256") == sha(cohort_bytes),
             "plan/policy/source pin mismatch")
    _require(_digest(plan.get("reader_sha256"))
             and _digest(plan.get("source_frontier_sha256"))
             and _digest(plan.get("forget_frontier_sha256")),
             "missing shared Reader or evidence owner frontier identity")
    specs = plan.get("arm_specs")
    _require(type(specs) is dict and set(specs) == set(ARMS),
             "A-I arm manifest is incomplete")
    for arm, name in ARMS.items():
        spec = specs[arm]
        _require(type(spec) is dict and spec.get("kind") == name
                 and _digest(spec.get("artifact_sha256"))
                 and type(spec.get("trained_group_ids")) is list
                 and all(type(g) is str for g in spec["trained_group_ids"])
                 and len(set(spec["trained_group_ids"])) == len(spec["trained_group_ids"]),
                 "arm mechanism/artifact/source closure is not pinned: " + arm)
    return specs


def freeze(cohort_path, metadata_path, output_path):
    """Write a new, exclusive plan; caller must commit it before running arms.

    Metadata contains reader/source/forget digests and all nine mechanism specs.
    These hashes are integrity references; they are not source-owner signatures.
    """
    raw = Path(cohort_path).read_bytes()
    _source_index(read_json(cohort_path))
    metadata = read_json(metadata_path)
    plan = {**metadata, "schema": SCHEMA,
            "policy_sha256": sha(canonical(POLICY)), "cohort_sha256": sha(raw)}
    _read_plan(plan, raw)
    with Path(output_path).open("xb") as stream:
        stream.write(canonical(plan) + b"\n")
    return sha(Path(output_path).read_bytes())


def _resources(row):
    values = row.get("resources")
    fields = ("wall_ns", "reader_forwards", "encoder_forwards",
              "head_forwards", "peak_rss_bytes", "resident_artifact_bytes",
              "input_tokens", "output_tokens")
    _require(type(values) is dict and all(
        _nonnegative_int(values.get(name)) for name in fields),
        "missing or negative physical resource counters")
    _require(values["input_tokens"] <= POLICY["max_reader_input_tokens"]
             and values["output_tokens"] <= POLICY["max_reader_output_tokens"],
             "Reader token limit exceeded")
    return values


def _check_row(row, arm, question, sources, plan, specs, roots):
    qid, group = question["query_id"], question["group"]
    _require(type(row) is dict and row.get("query_id") == qid
             and row.get("arm") == arm and row.get("group") == group
             and row.get("split") == question["split"],
             "altered query/arm/source identity")
    selected = row.get("selected_source_ids")
    _require(type(selected) is list and len(selected) <= POLICY["max_sources"]
             and all(type(s) is str for s in selected)
             and len(set(selected)) == len(selected),
             "duplicate or over-budget selected sources")
    _require(all((group, ref) in sources for ref in selected),
             "cross-group or invented source reference")
    delivered = "".join(sources[group, ref] for ref in selected).encode()
    _require(row.get("context_sha256") == sha(delivered)
             and type(row.get("context_utf8_bytes")) is int
             and row["context_utf8_bytes"] == len(delivered)
             and len(delivered) <= POLICY["max_context_utf8_bytes"],
             "source-frame context changed or exceeds budget")
    _require(row.get("reader_sha256") == plan["reader_sha256"]
             and row.get("source_frontier_sha256") == plan["source_frontier_sha256"]
             and row.get("forget_frontier_sha256") == plan["forget_frontier_sha256"],
             "Reader or live source/forget frontier drift")
    _require(row.get("artifact_sha256") == specs[arm]["artifact_sha256"],
             "unregistered model/graph artifact")
    _require(row.get("execution_kind") == "original_model_execution",
             "mock/replay/digest-only execution may not enter the real census")
    answer = row.get("answer")
    _require(type(answer) is str and row.get("answer_sha256") == sha(answer.encode()),
             "missing or forged answer bytes")
    _require(type(row.get("accepted")) is bool,
             "accepted is not a strict Boolean")
    _require(row["accepted"] or not answer,
             "abstention must not deliver a nonempty answer")
    if row["accepted"]:
        _require(bool(selected), "accepted answer without source")
    resources = _resources(row)
    _require(resources["reader_forwards"] > 0 if row["accepted"] else True,
             "accepted answer without physical Reader call")
    ancestry = specs[arm]["trained_group_ids"]
    _require(all(root in roots and roots[root] in ("train", "calibration")
                 for root in ancestry), "trained on holdout/OOD/source-deleted family")
    # An artifact's supplied closure must not be trusted as full training proof.
    _require(type(row.get("generation_receipt_sha256")) is str
             and _digest(row["generation_receipt_sha256"]),
             "missing model execution receipt identity")
    gold = set(question["gold_support_ids"])
    unresolved = sorted(ref for ref in gold if (group, ref) not in sources)
    scorable = bool(gold) and not unresolved and question["answerable"]
    hit = len(set(selected) & gold)
    return {
        "support_all": (int(gold <= set(selected)) if scorable else None),
        "support_fraction": (hit / len(gold) if scorable else None),
        "unresolved_gold": unresolved, "answerable": question["answerable"],
        "accepted": row["accepted"], "resources": resources,
        "answer_sha256": row["answer_sha256"], "group": group,
        "split": question["split"], "arm": arm, "query_id": qid,
    }


def _bootstrap_group_differences(scores, arm_a, arm_b, split, *, draws):
    paired = defaultdict(list)
    for key, entries in scores.items():
        if key[0] != split or arm_a not in entries or arm_b not in entries:
            continue
        a, b = entries[arm_a], entries[arm_b]
        if a["correct"] is not None and b["correct"] is not None:
            paired[a["group"]].append(float(a["correct"]) - float(b["correct"]))
    diffs = [statistics.fmean(values) for _, values in sorted(paired.items())]
    if not diffs:
        return {"groups": 0, "difference": None, "interval": None}
    seed = POLICY["bootstrap_seed"] + sum(map(ord, arm_a + arm_b + split))
    rng = random.Random(seed)
    distribution = sorted(
        statistics.fmean(rng.choices(diffs, k=len(diffs))) for _ in range(draws)
    )
    alpha = POLICY["alpha_familywise"] / len(COMPARISONS)
    lo = distribution[math.floor(draws * alpha / 2)]
    hi = distribution[min(draws - 1, math.ceil(draws * (1 - alpha / 2)) - 1)]
    return {"groups": len(diffs), "difference": statistics.fmean(diffs),
            "bonferroni_interval": [lo, hi],
            "interval": [lo, hi], "cluster_unit": "source_family",
            "independence_authenticated": False}


def audit(plan_path, cohort_path, prediction_path, judgment_path=None):
    """Recompute all row/cost/quality scores; never return production approval."""
    raw = Path(cohort_path).read_bytes()
    cohort = read_json(cohort_path)
    sources, questions, roots = _source_index(cohort)
    plan = read_json(plan_path)
    specs = _read_plan(plan, raw)
    result = {"schema": SCHEMA, "authority": "DENY_ALL", "mode": "SHADOW_ONLY",
              "production_activation_allowed": False,
              "scientific_superiority_certified": False,
              "plan_sha256": sha(Path(plan_path).read_bytes()),
              "cohort_sha256": sha(raw),
              "policy_sha256": sha(canonical(POLICY)),
              "complete": False, "blockers": [], "metrics": {},
              "comparisons": {}, "coverage": {}}
    for arm in ARMS:
        if arm in ("E", "F", "G", "H", "I") and not specs[arm]["trained_group_ids"]:
            result["blockers"].append("arm " + arm + " lacks actual learning ancestors")
    observations, rows = {}, read_jsonl(prediction_path)
    for row in rows:
        _require(type(row) is dict, "observation is not an object")
        arm, qid = row.get("arm"), row.get("query_id")
        _require(arm in ARMS and qid in questions, "extra or unregistered result row")
        key = (qid, arm)
        _require(key not in observations, "duplicate query/arm execution")
        observations[key] = _check_row(row, arm, questions[qid], sources,
                                       plan, specs, roots)
    expected = {(qid, arm) for qid in questions for arm in ARMS}
    missing = expected - observations.keys()
    result["coverage"] = {
        "expected": len(expected), "observed": len(observations),
        "missing": len(missing), "unregistered": 0,
        "arms": {arm: sum(a == arm for _, a in observations) for arm in ARMS},
    }
    if missing:
        result["blockers"].append("missing " + str(len(missing)) +
                                  " original A-I executions")
    judgments = {}
    if judgment_path is not None:
        for item in read_jsonl(judgment_path):
            _require(type(item) is dict, "invalid judgment")
            key = (item.get("query_id"), item.get("arm"))
            _require(key in observations and key not in judgments,
                     "extra, duplicate or unpaired independent judgment")
            _require(item.get("answer_sha256") == observations[key]["answer_sha256"]
                     and type(item.get("correct")) is bool
                     and type(item.get("supported")) is bool
                     and type(item.get("judge_id")) is str
                     and bool(item["judge_id"]), "unbound or fake judgment")
            judgments[key] = item
    if set(judgments) != set(observations):
        result["blockers"].append("missing sealed independent answer judgments")
    # The mere existence of a judge_id or digest is not an authenticated witness.
    result["blockers"].append(
        "independently authenticated source, Reader, model and judge attestations absent")
    for split in SPLITS:
        section = {}
        for arm in ARMS:
            records = [v for v in observations.values()
                       if v["arm"] == arm and v["split"] == split]
            if not records:
                continue
            checked = [v for v in records if v["support_all"] is not None]
            judged = [judgments[(v["query_id"], arm)] for v in records
                      if (v["query_id"], arm) in judgments]
            section[arm] = {
                "n": len(records), "source_groups": len({r["group"] for r in records}),
                "gold_scorable": len(checked),
                "source_all_support": (statistics.fmean(v["support_all"] for v in checked)
                                       if checked else None),
                "source_partial_support": (statistics.fmean(v["support_fraction"]
                                         for v in checked) if checked else None),
                "answer_correct": (statistics.fmean(j["correct"] for j in judged)
                                   if len(judged) == len(records) else None),
                "citation_supported": (statistics.fmean(j["supported"] for j in judged)
                                       if len(judged) == len(records) else None),
                "answer_coverage": statistics.fmean(v["accepted"] for v in records),
                "total_wall_ns": sum(v["resources"]["wall_ns"] for v in records),
                "total_head_forwards": sum(v["resources"]["head_forwards"] for v in records),
                "max_peak_rss_bytes": max(v["resources"]["peak_rss_bytes"] for v in records),
                "total_encoder_forwards": sum(v["resources"]["encoder_forwards"]
                                              for v in records),
            }
        result["metrics"][split] = section
    scored = defaultdict(dict)
    for (qid, arm), value in observations.items():
        split = value["split"]
        scored[(split, qid)][arm] = {
            **value, "correct": judgments[(qid, arm)]["correct"]
            if (qid, arm) in judgments else None}
    adequate = True
    for split in PRIMARY:
        members = {q["group"] for q in questions.values() if q["split"] == split}
        if len(members) < POLICY["min_independent_groups_per_primary_split"]:
            adequate = False
            result["blockers"].append(
                split + " has " + str(len(members)) +
                " independent source families (needs at least 200)")
        section = {}
        for left, right in COMPARISONS:
            name = left + "_minus_" + right
            effect = _bootstrap_group_differences(
                scored, left, right, split, draws=POLICY["bootstrap_samples"])
            section[name] = effect
            interval = effect["interval"]
            if interval is None or interval[0] <= POLICY["min_absolute_quality_delta"]:
                adequate = False
                result["blockers"].append(split + " " + name +
                                          " fails preregistered effect threshold")
        result["comparisons"][split] = section
        if all(arm in result["metrics"][split] for arm in ("B", "I")):
            b = result["metrics"][split]["B"]
            i = result["metrics"][split]["I"]
            if b["total_wall_ns"] <= 0 or (
                i["total_wall_ns"] > b["total_wall_ns"] *
                    POLICY["max_cost_ratio_to_strong_baseline"]
            ):
                adequate = False
                result["blockers"].append(split + " I/B wall-clock budget is unmatched")
        else:
            adequate = False
            result["blockers"].append(split + " missing strong-baseline cost pairs")
    # With no original negative-control data and signed verification this is not a GO.
    for control in POLICY["required_negative_controls"]:
        result["blockers"].append("unverified causal control: " + control)
    if not any(q["split"] == "adversarial" for q in questions.values()):
        result["blockers"].append("no adversarial abstention cohort")
    if not any(q["split"] == "deletion" for q in questions.values()):
        result["blockers"].append("no post-forget reconstruction cohort")
    result["complete"] = not missing and len(judgments) == len(expected)
    result["candidate_effect_thresholds_met"] = adequate and result["complete"]
    result["blockers"] = sorted(set(result["blockers"]))
    result["disposition"] = "HOLD_NO_GO"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pre = commands.add_parser("freeze", help="atomically freeze cohort/spec SHA pins")
    pre.add_argument("--cohort", required=True)
    pre.add_argument("--metadata", required=True)
    pre.add_argument("--output", required=True)
    inspect = commands.add_parser("audit", help="independent nine-arm observation audit")
    inspect.add_argument("--plan", required=True)
    inspect.add_argument("--cohort", required=True)
    inspect.add_argument("--predictions", required=True)
    inspect.add_argument("--judgments")
    inspect.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        print(freeze(args.cohort, args.metadata, args.output))
    else:
        result = audit(args.plan, args.cohort, args.predictions, args.judgments)
        with Path(args.output).open("xb") as stream:
            stream.write(canonical(result) + b"\n")
        print(json.dumps({"disposition": result["disposition"],
                          "blockers": len(result["blockers"]),
                          "coverage": result["coverage"]}, indent=2))


if __name__ == "__main__":
    main()
