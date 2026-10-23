"""Independent, fail-closed A--I MemoryCell experiment ledger auditor.

This module neither calls the models nor reads training labels in a serving path.
It reconstructs exact-answer, annotated support and group-paired diagnostics
from sealed predictions and reviewer-only gold. It NEVER grants production use.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import re
import statistics
import unicodedata

SCHEMA = "hepta.memory.ablation-matrix.v1"
ARMS = {
    "A": "bm25",
    "B": "dense_bm25_reranker",
    "C": "graph_rag",
    "D": "typed_untrained",
    "E": "shared_encoder_single_head",
    "F": "shared_encoder_typed_heads",
    "G": "learned_router",
    "H": "learned_meta_graph",
    "I": "split_merge_evolution",
}
ROLES = ("train", "calibration", "evaluation", "future_1", "future_2", "ood")
EVALUATION_ROLES = ROLES[2:]
# Fixed before inspecting evaluation results. A/B/C are independently required.
CONTRASTS = (("D", "B"), ("E", "D"), ("F", "E"),
             ("G", "F"), ("H", "G"), ("I", "H"),
             ("I", "B"), ("I", "C"))
SHA = re.compile(r"[0-9a-f]{64}\Z")
QUESTION_KEYS = frozenset(("query_id", "group_id", "split", "question", "available_source_ids",
                           "source_snapshot_sha256"))
PREDICTION_KEYS = frozenset(("arm", "query_id", "plan_sha256", "source_snapshot_sha256",
                             "source_frontier_sha256", "forget_frontier_sha256", "reader_sha256",
                             "selected_source_ids", "abstained", "answer", "resources"))
RESOURCE_KEYS = frozenset(("wall_ms", "peak_rss_bytes", "resident_bytes", "context_bytes",
                           "input_tokens", "output_tokens", "head_calls", "router_calls",
                           "encoder_calls", "graph_calls", "energy_joules"))
BUDGET_KEYS = frozenset(("top_k", "max_context_bytes", "max_output_tokens", "max_wall_ms",
                         "max_peak_rss_bytes", "max_resident_bytes", "max_head_calls",
                         "max_router_calls", "max_encoder_calls", "max_graph_calls"))


def require(cond, reason):
    if not cond:
        raise ValueError(reason)


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def digest_ok(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def uniq_strings(values, *, nonempty=True):
    return (type(values) is list and (bool(values) or not nonempty)
            and all(type(x) is str and bool(x) and len(x) <= 256 for x in values)
            and len(values) == len(set(values)))


def strict_int(value, minimum=0):
    return type(value) is int and value >= minimum


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def load_json(path):
    return json.loads(Path(path).read_bytes())


def load_jsonl(path):
    result = []
    for idx, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        require(line.strip(), f"blank JSONL row {idx}")
        result.append(json.loads(line))
    return result


def norm_answer(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _keys(obj, required, description):
    require(type(obj) is dict and set(obj) == set(required), f"{description}: strict fields")


def validate_plan(plan, questions_raw, gold_raw):
    _keys(plan, ("schema", "suite_id", "source_sha256", "query_sha256", "gold_sha256",
                 "reader_sha256", "source_frontier_sha256", "forget_frontier_sha256",
                 "splits", "arms", "budget", "minimum_independent_groups",
                 "minimum_gain", "seed", "comparisons"), "plan")
    require(plan["schema"] == SCHEMA, "schema mismatch")
    require(type(plan["suite_id"]) is str and 1 <= len(plan["suite_id"]) <= 128,
            "invalid suite id")
    for field in ("source_sha256", "query_sha256", "gold_sha256", "reader_sha256",
                  "source_frontier_sha256", "forget_frontier_sha256"):
        require(digest_ok(plan[field]), f"invalid {field}")
    require(plan["query_sha256"] == digest(questions_raw), "query bytes do not match frozen plan")
    require(plan["gold_sha256"] == digest(gold_raw), "reviewer gold bytes do not match frozen plan")
    splits = plan["splits"]
    _keys(splits, ROLES, "source-group splits")
    for role in ROLES:
        require(uniq_strings(splits[role], nonempty=role in ROLES[:3]), f"invalid {role} groups")
    all_groups = list(itertools.chain.from_iterable(splits.values()))
    require(len(all_groups) == len(set(all_groups)), "source group crosses train/calibration/holdout")
    require(type(plan["arms"]) is dict and plan["arms"] == ARMS,
            "all nine frozen arm definitions are required")
    require(plan["comparisons"] == [list(pair) for pair in CONTRASTS],
            "comparisons must be frozen before evaluating")
    _keys(plan["budget"], BUDGET_KEYS, "budget")
    for key, val in plan["budget"].items():
        require(strict_int(val, 1), f"invalid {key} budget")
    require(strict_int(plan["minimum_independent_groups"], 2), "minimum groups must be >=2")
    require(type(plan["minimum_gain"]) in (int, float)
            and math.isfinite(plan["minimum_gain"]) and 0 < plan["minimum_gain"] <= 1,
            "invalid predeclared improvement floor")
    require(strict_int(plan["seed"]), "invalid seed")
    questions = json.loads(questions_raw)
    gold = json.loads(gold_raw)
    require(type(questions) is list and bool(questions), "empty questions")
    require(type(gold) is list and bool(gold), "empty reviewer gold")
    seen_q = set()
    role_groups = {g: role for role, groups in splits.items() for g in groups}
    for q in questions:
        _keys(q, QUESTION_KEYS, "question (gold/answers must be reviewer-only)")
        qid, group, split = q["query_id"], q["group_id"], q["split"]
        require(type(qid) is str and qid and qid not in seen_q, "duplicate or invalid query")
        seen_q.add(qid)
        require(split in EVALUATION_ROLES and role_groups.get(group) == split,
                "query split/group mismatch or training contamination")
        require(type(q["question"]) is str and q["question"], "invalid query text")
        require(uniq_strings(q["available_source_ids"], nonempty=False), "invalid available source list")
        require(digest_ok(q["source_snapshot_sha256"]), "invalid immutable query snapshot")
    seen_gold = set()
    for item in gold:
        _keys(item, ("query_id", "answerable", "acceptable_answers", "required_support_ids",
                     "slice"), "protected gold")
        qid = item["query_id"]
        require(type(qid) is str and qid in seen_q and qid not in seen_gold,
                "missing/duplicate protected gold query")
        seen_gold.add(qid)
        require(type(item["answerable"]) is bool, "answerability must be Boolean")
        require(uniq_strings(item["acceptable_answers"], nonempty=item["answerable"]),
                "invalid answer references")
        require(uniq_strings(item["required_support_ids"], nonempty=item["answerable"]),
                "invalid annotated gold support")
        require(item["answerable"] or not item["acceptable_answers"] and not item["required_support_ids"],
                "unanswerable case must not contain affirmative answers")
        require(item["slice"] in ("ordinary", "multi_hop", "temporal", "adversarial", "ood"),
                "unknown evaluation slice")
    require(seen_q == seen_gold, "reviewer gold census differs from serving query census")
    return questions, {row["query_id"]: row for row in gold}


def validate_resource(row, budget):
    _keys(row, RESOURCE_KEYS, "actual resource receipt")
    require(all(number(v) for v in row.values()), "nonfinite/negative or Boolean resource")
    for key in ("context_bytes", "input_tokens", "output_tokens", "head_calls",
                "router_calls", "encoder_calls", "graph_calls", "peak_rss_bytes", "resident_bytes"):
        require(type(row[key]) is int, f"{key} must be an integer")
    bounds = (("context_bytes", "max_context_bytes"), ("output_tokens", "max_output_tokens"),
              ("wall_ms", "max_wall_ms"), ("peak_rss_bytes", "max_peak_rss_bytes"),
              ("resident_bytes", "max_resident_bytes"), ("head_calls", "max_head_calls"),
              ("router_calls", "max_router_calls"), ("encoder_calls", "max_encoder_calls"),
              ("graph_calls", "max_graph_calls"))
    require(all(row[k] <= budget[b] for k, b in bounds), "observed resource budget overrun")


def score(questions, gold, predictions, plan, plan_sha):
    q_by_id = {q["query_id"]: q for q in questions}
    expected = {(arm, qid) for arm in ARMS for qid in q_by_id}
    seen = {}
    for row in predictions:
        _keys(row, PREDICTION_KEYS, "prediction")
        arm, qid = row["arm"], row["query_id"]
        key = arm, qid
        require(key in expected and key not in seen, "unexpected or duplicated prediction")
        q = q_by_id[qid]
        for name, value in (("plan_sha256", plan_sha),
                            ("source_snapshot_sha256", q["source_snapshot_sha256"]),
                            ("source_frontier_sha256", plan["source_frontier_sha256"]),
                            ("forget_frontier_sha256", plan["forget_frontier_sha256"]),
                            ("reader_sha256", plan["reader_sha256"])):
            require(row[name] == value, f"prediction stale or wrong {name}")
        require(type(row["abstained"]) is bool, "abstention is not Boolean")
        require(type(row["answer"]) is str and (not row["answer"] if row["abstained"]
                                                  else bool(row["answer"].strip())),
                "answer / abstention inconsistency")
        sources = row["selected_source_ids"]
        require(uniq_strings(sources, nonempty=False), "duplicate/invalid selected evidence")
        require(len(sources) <= plan["budget"]["top_k"], "evidence slot budget overrun")
        require(set(sources) <= set(q["available_source_ids"]), "invented evidence/source authority")
        validate_resource(row["resources"], plan["budget"])
        seen[key] = row
    require(set(seen) == expected, "incomplete A-I by-query paired prediction census")
    results = []
    for arm, qid in sorted(expected):
        q = q_by_id[qid]
        g = gold[qid]
        p = seen[arm, qid]
        support = (set(g["required_support_ids"]) <= set(p["selected_source_ids"])
                   if g["answerable"] else None)
        exact = (norm_answer(p["answer"]) in {norm_answer(a) for a in g["acceptable_answers"]}
                 if not p["abstained"] and g["answerable"] else False)
        success = (p["abstained"] if not g["answerable"] else
                   (not p["abstained"] and exact and support))
        results.append({"arm": arm, "query_id": qid, "group_id": q["group_id"],
                        "split": q["split"], "slice": g["slice"],
                        "answerable": g["answerable"], "abstained": p["abstained"],
                        "exact_answer": bool(exact), "annotated_support_complete": support,
                        "strict_task_success": bool(success),
                        "resources": p["resources"]})
    return results


def group_means(results, arm, split):
    by_group = defaultdict(list)
    for row in results:
        if row["arm"] == arm and row["split"] == split:
            by_group[row["group_id"]].append(int(row["strict_task_success"]))
    return {k: statistics.fmean(v) for k, v in sorted(by_group.items())}


def paired_stats(results, candidate, control, split, seed, reps=4000):
    left = group_means(results, candidate, split)
    right = group_means(results, control, split)
    require(left and left.keys() == right.keys(), "unpaired source-group evaluation")
    differences = [left[k] - right[k] for k in left]
    delta = statistics.fmean(differences)
    rng = random.Random(seed)
    size = len(differences)
    bootstrap = sorted(statistics.fmean(rng.choices(differences, k=size)) for _ in range(reps))
    # One-sided sign-flip randomization, never interpret each query as independent.
    if size <= 16:
        null = [statistics.fmean(s * d for s, d in zip(signs, differences))
                for signs in itertools.product((-1, 1), repeat=size)]
    else:
        null = [statistics.fmean((1 if rng.getrandbits(1) else -1) * d
                                 for d in differences) for _ in range(reps)]
    p = (1 + sum(x >= delta - 1e-12 for x in null)) / (len(null) + 1)
    return {"candidate": candidate, "control": control, "split": split,
            "groups": size, "delta": delta,
            "descriptive_interval_95": [bootstrap[int(.025 * reps)], bootstrap[int(.975 * reps)]],
            "one_sided_signflip_p": min(1.0, p)}


def holm_adjust(comparisons):
    """Family-wise Holm adjusted p values, maintaining original contrast order."""
    order = sorted(range(len(comparisons)), key=lambda i: comparisons[i]["one_sided_signflip_p"])
    adjusted, previous = [0.0] * len(order), 0.0
    for rank, idx in enumerate(order):
        previous = min(1.0, max(previous, (len(order) - rank) * comparisons[idx]["one_sided_signflip_p"]))
        adjusted[idx] = previous
    return [dict(row, holm_p=adjusted[i]) for i, row in enumerate(comparisons)]


def audit(plan_path, questions_path, gold_path, predictions_directory):
    plan_raw = Path(plan_path).read_bytes()
    query_raw = Path(questions_path).read_bytes()
    gold_raw = Path(gold_path).read_bytes()
    plan = json.loads(plan_raw)
    questions, gold = validate_plan(plan, query_raw, gold_raw)
    plan_sha = digest(plan_raw)
    root = Path(predictions_directory)
    predictions, inventory = [], {}
    for arm in ARMS:
        path = root / f"{arm}.jsonl"
        raw = path.read_bytes()  # Missing arm is fatal, not silent partial success.
        inventory[arm] = {"sha256": digest(raw), "bytes": len(raw)}
        predictions.extend(load_jsonl(path))
    results = score(questions, gold, predictions, plan, plan_sha)
    comparisons = holm_adjust([paired_stats(results, a, b, "evaluation", plan["seed"] + i)
                               for i, (a, b) in enumerate(CONTRASTS)])
    group_counts = {split: len({q["group_id"] for q in questions if q["split"] == split})
                    for split in EVALUATION_ROLES}
    by_arm = {}
    resource_metrics = ("wall_ms", "peak_rss_bytes", "resident_bytes", "context_bytes",
                        "input_tokens", "output_tokens", "head_calls", "router_calls",
                        "encoder_calls", "graph_calls", "energy_joules")
    for arm in ARMS:
        arm_rows = [r for r in results if r["arm"] == arm]
        by_arm[arm] = {"resource_observations": {
                           key: {"mean": statistics.fmean(float(r["resources"][key]) for r in arm_rows),
                                 "maximum": max(float(r["resources"][key]) for r in arm_rows)}
                           for key in resource_metrics},
                       "strict_task_success": statistics.fmean(int(r["strict_task_success"])
                                                                 for r in arm_rows),
                       "group_macro_success_by_window": {
                           split: (statistics.fmean(group_means(results, arm, split).values())
                                   if group_counts[split] else None) for split in EVALUATION_ROLES},
                       "abstention_on_unanswerable": (
                           statistics.fmean(int(r["abstained"]) for r in arm_rows if not r["answerable"])
                           if any(not r["answerable"] for r in arm_rows) else None),
                       "multi_hop_success": (
                           statistics.fmean(int(r["strict_task_success"]) for r in arm_rows
                                            if r["slice"] == "multi_hop")
                           if any(r["slice"] == "multi_hop" for r in arm_rows) else None)}
    enough_groups = group_counts["evaluation"] >= plan["minimum_independent_groups"]
    has_two_future_windows = (group_counts["future_1"] >= plan["minimum_independent_groups"]
                              and group_counts["future_2"] >= plan["minimum_independent_groups"])
    # These are untrusted reports until independently validated model/evaluator,
    # evidence membership, real resource cost, future observations and deletion.
    meets_diagnostic_gate = (enough_groups and has_two_future_windows and
                             all(c["holm_p"] < .05 and c["delta"] >= plan["minimum_gain"]
                                 for c in comparisons))
    return {"schema": SCHEMA, "plan_sha256": plan_sha,
            "query_sha256": digest(query_raw), "gold_sha256": digest(gold_raw),
            "prediction_inventory": inventory, "rows": len(results), "group_counts": group_counts,
            "arm_metrics": by_arm, "predeclared_comparisons": comparisons,
            "diagnostic_statistical_gate": meets_diagnostic_gate,
            "production_activation_allowed": False, "scientific_superiority_established": False,
            "missing_external_admission": ["authenticated_source_membership",
                                           "independent_blind_semantic_or_program_judge",
                                           "full_training_and_inference_cost_parity",
                                           "genuinely_future_independent_sources",
                                           "deletion_and_negative_transfer",
                                           "model_and_evaluator_attestation",
                                           "terminal_exact_head_ci"],
            "qualification": "SHADOW_ONLY / DENY_ALL / HOLD_NO_GO"}


def create_only(path, content):
    with Path(path).open("xb") as stream:
        stream.write(content)


def freeze_plan(draft_path, questions_path, reviewer_gold_path, destination):
    """Create-only exact-byte plan seal. Publish SHA externally before any run."""
    draft = load_json(draft_path)
    query_raw = Path(questions_path).read_bytes()
    gold_raw = Path(reviewer_gold_path).read_bytes()
    validate_plan(draft, query_raw, gold_raw)
    sealed = canonical(draft) + b"\n"
    create_only(destination, sealed)
    return digest(sealed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze", help="create-only plan seal; do this before running producers")
    freeze.add_argument("--draft", required=True)
    freeze.add_argument("--queries", required=True)
    freeze.add_argument("--reviewer-gold", required=True)
    freeze.add_argument("--plan", required=True)
    check = sub.add_parser("audit", help="strict nine-arm independent reviewer")
    check.add_argument("--plan", required=True)
    check.add_argument("--queries", required=True)
    check.add_argument("--reviewer-gold", required=True)
    check.add_argument("--predictions", required=True)
    check.add_argument("--report", required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        print(json.dumps({"sealed_plan_sha256": freeze_plan(
            args.draft, args.queries, args.reviewer_gold, args.plan)}))
        return
    result = audit(args.plan, args.queries, args.reviewer_gold, args.predictions)
    create_only(args.report, canonical(result) + b"\n")
    print(json.dumps({"plan_sha256": result["plan_sha256"],
                      "rows": result["rows"], "status": result["qualification"]}))


if __name__ == "__main__":
    main()
