"""Fail-closed, source-family-paired A-I MemoryCell benchmark adjudicator.

This module NEVER performs inference, signs source evidence or promotes a model.
It consumes externally frozen task/arm manifests and *actual* per-arm outputs.
All scores are derived after joining the complete nine-arm prediction census to
separate evaluation gold; producer-claimed correctness is not trusted.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import random
import re
import statistics

ARMS = tuple("ABCDEFGHI")
COMPARISONS = (
    ("B", "A"), ("C", "B"), ("D", "B"), ("E", "D"), ("F", "E"),
    ("G", "F"), ("H", "G"), ("I", "H"), ("I", "B"), ("I", "C"),
)
ROLES = ("bm25", "hybrid_dense_rerank", "source_graph", "typed_static",
         "shared_one_head", "shared_typed_heads", "learned_router",
         "learned_meta_graph", "split_merge_evolution")
HEX64 = re.compile(r"^[a-f0-9]{64}$")
MEASURES = ("context_tokens", "reader_output_tokens", "reader_calls",
            "encoder_calls", "head_calls", "router_calls", "graph_hops",
            "wall_ns", "cpu_ns", "peak_rss_bytes", "io_bytes")


class ProtocolError(ValueError):
    """An incomplete, forged, or noncomparable experiment is not scorable."""


def need(ok, message):
    if not ok:
        raise ProtocolError(message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pinned(path: Path, expected: str):
    need(isinstance(expected, str) and HEX64.fullmatch(expected), "invalid SHA-256 pin")
    data = path.read_bytes()
    need(digest(data) == expected, f"changed or unsealed input: {path.name}")
    return json.loads(data)


def normalized_answer(value):
    need(isinstance(value, str) and len(value) <= 8192, "invalid answer text")
    return " ".join(value.casefold().split())


def sorted_unique(value, field, *, allow_empty=False):
    need(isinstance(value, list) and (allow_empty or bool(value)), f"invalid {field}")
    need(all(isinstance(s, str) and s and len(s) <= 256 for s in value), f"invalid {field} members")
    need(value == sorted(set(value)), f"{field} must be sorted, unique")
    return value


def nonnegative(value, field):
    need(type(value) is int and value >= 0, f"{field} must be a measured integer")
    return value


def sha(value, field):
    need(isinstance(value, str) and HEX64.fullmatch(value), f"invalid {field}")
    return value


def validate_plan(plan):
    need(isinstance(plan, dict) and plan.get("schema_version") == 1,
         "unknown A-I protocol version")
    need(plan.get("arms") == list(ARMS), "the nine A-I arms must be frozen in order")
    need(plan.get("comparisons") == [list(p) for p in COMPARISONS],
         "primary comparisons differ from the pre-registered matrix")
    need(plan.get("status") == "SHADOW_ONLY", "experimental authority must remain shadow-only")
    need(plan.get("evaluation_frozen_before_outputs") is True, "no prospective freeze witness")
    for key in ("source_snapshot_sha256", "reader_sha256", "encoder_sha256", "scorer_sha256"):
        sha(plan.get(key), key)
    limits = plan.get("limits")
    need(isinstance(limits, dict), "resource ceilings absent")
    for key in ("context_tokens", "reader_output_tokens", "reader_calls",
                "head_calls", "router_calls", "cpu_ns", "wall_ns",
                "peak_rss_bytes", "resident_bytes", "training_work_units"):
        need(nonnegative(limits.get(key), key) > 0, "nonpositive resource ceiling")
    policy = plan.get("acceptance")
    need(isinstance(policy, dict), "acceptance policy absent")
    need(type(policy.get("seed")) is int and policy["seed"] >= 0, "invalid bootstrap seed")
    need(type(policy.get("bootstrap_repetitions")) is int
         and 100 <= policy["bootstrap_repetitions"] <= 100000, "bootstrap repetitions outside bounds")
    need(type(policy.get("min_evaluation_families")) is int
         and policy["min_evaluation_families"] >= 30, "minimum family count too low")
    need(type(policy.get("min_future_windows")) is int
         and policy["min_future_windows"] >= 2, "independent future windows required")
    for key in ("min_effect", "max_cost_ratio", "max_slice_regression"):
        v = policy.get(key)
        need(type(v) in (int, float) and math.isfinite(v) and v >= 0, f"invalid {key}")
    need(policy["max_cost_ratio"] >= 1, "impossible cost ratio")
    arms = plan.get("arm_manifests")
    need(isinstance(arms, dict) and set(arms) == set(ARMS), "missing arm manifest")
    for i, arm in enumerate(ARMS):
        m = arms[arm]
        need(isinstance(m, dict) and m.get("method") == ROLES[i], f"wrong {arm} implementation")
        for key in ("artifact_sha256", "source_closure_sha256"):
            sha(m.get(key), f"{arm}.{key}")
        for key in ("resident_bytes", "training_work_units"):
            need(nonnegative(m.get(key), f"{arm}.{key}") <= limits[key],
                 f"{arm} resource limit")
        groups = sorted_unique(m.get("learned_from_families"), f"{arm}.learned_from_families", allow_empty=True)
        need((bool(groups) if arm in "EFGHI" else not bool(groups)), f"{arm} training provenance inconsistent")
        need(m.get("reader_sha256") == plan["reader_sha256"], f"{arm} reader differs")
        if arm in "EFGHI":
            need(m.get("encoder_sha256") == plan["encoder_sha256"], f"{arm} shared encoder differs")
        if arm in "GHI":
            need(m.get("route_before_head") is True, f"{arm} must route before Head calls")
        if arm in "CHI":
            sha(m.get("graph_artifact_sha256"), f"{arm}.graph_artifact_sha256")
        if arm in "GHI":
            sha(m.get("router_artifact_sha256"), f"{arm}.router_artifact_sha256")
        if arm == "I":
            need(m.get("evaluated_split_merge") is True, "I lacks actual structural operation")
            sha(m.get("topology_receipt_sha256"), "I.topology_receipt_sha256")
    need(arms["H"]["resident_bytes"] == arms["I"]["resident_bytes"] and
         arms["H"]["training_work_units"] == arms["I"]["training_work_units"],
         "evolution must match static Meta-Graph parameter and training budgets")
    tasks = plan.get("tasks")
    need(isinstance(tasks, list) and tasks, "no sealed task census")
    ids, family_split, eval_families, windows = set(), {}, set(), set()
    for t in tasks:
        need(isinstance(t, dict), "invalid task")
        tid, family, split = t.get("task_id"), t.get("family_id"), t.get("split")
        need(isinstance(tid, str) and tid and tid not in ids, "duplicate/invalid task id")
        need(isinstance(family, str) and family, "invalid family id")
        need(split in ("train", "calibration", "evaluation"), "invalid split")
        need(family_split.setdefault(family, split) == split, "source-family leakage across splits")
        sorted_unique(t.get("allowed_source_ids"), "allowed_source_ids")
        sha(t.get("source_snapshot_sha256"), "task source snapshot")
        need(t["source_snapshot_sha256"] == plan["source_snapshot_sha256"], "task source snapshot drift")
        need(isinstance(t.get("tags"), list) and
             all(v in ("multi_hop", "temporal", "ood", "adversarial", "procedural", "cross_modal") for v in t["tags"])
             and len(t["tags"]) == len(set(t["tags"])), "unknown or duplicate slice tags")
        if split == "evaluation":
            need(isinstance(t.get("future_window"), str) and t["future_window"], "future window absent")
            eval_families.add(family)
            windows.add(t["future_window"])
        else:
            need(t.get("future_window") is None, "non-evaluation task carries future window")
        ids.add(tid)
    need([t["task_id"] for t in tasks] == sorted(ids), "task census must be canonically sorted")
    train_families = {f for f, s in family_split.items() if s == "train"}
    for a, m in arms.items():
        need(set(m["learned_from_families"]) <= train_families,
             f"{a} trained from calibration/evaluation or unknown families")
    return {"task_map": {t["task_id"]: t for t in tasks},
            "eval_ids": {t["task_id"] for t in tasks if t["split"] == "evaluation"},
            "eval_families": eval_families, "windows": windows}


def validate_gold(gold, ctx):
    need(isinstance(gold, list), "gold must be a separately sealed array")
    need(len(gold) == len(ctx["eval_ids"]), "gold task census incomplete")
    result = {}
    for g in gold:
        need(isinstance(g, dict), "invalid gold row")
        tid = g.get("task_id")
        need(tid in ctx["eval_ids"] and tid not in result, "duplicate/unregistered gold")
        need(type(g.get("answerable")) is bool, "answerability not independently declared")
        answers = sorted_unique(g.get("accepted_answers"), "gold accepted_answers", allow_empty=not g["answerable"])
        refs = sorted_unique(g.get("required_support_ids"), "gold required_support_ids", allow_empty=not g["answerable"])
        need(bool(answers) == g["answerable"] and bool(refs) == g["answerable"],
             "answerable case must specify independently frozen answer and sources")
        need(set(refs) <= set(ctx["task_map"][tid]["allowed_source_ids"]), "gold outside owned source closure")
        if not g["answerable"]:
            need(not answers and not refs, "unanswerable gold leaked support")
        result[tid] = g
    need(set(result) == ctx["eval_ids"], "gold missing eval task")
    return result


def validate_predictions(plan, ctx, predictions):
    need(isinstance(predictions, list), "prediction journal must be an array")
    need(len(predictions) == len(ARMS) * len(ctx["eval_ids"]), "partial A-I census")
    result = {}
    lim = plan["limits"]
    for row in predictions:
        need(isinstance(row, dict), "invalid prediction row")
        a, tid = row.get("arm"), row.get("task_id")
        need(a in ARMS and tid in ctx["eval_ids"] and (a, tid) not in result,
             "duplicate, non-evaluation or unknown prediction")
        manifest = plan["arm_manifests"][a]
        for key in ("artifact_sha256", "source_closure_sha256"):
            need(row.get(key) == manifest[key], f"{a} artifact/lineage pin changed")
        need(row.get("source_snapshot_sha256") == plan["source_snapshot_sha256"],
             "row source frontier changed")
        need(row.get("reader_sha256") == plan["reader_sha256"], "Reader drift")
        need(type(row.get("abstained")) is bool, "invalid abstention")
        answer = normalized_answer(row.get("answer_text"))
        selected = sorted_unique(row.get("selected_source_ids"), "selected ids", allow_empty=True)
        cited = sorted_unique(row.get("cited_source_ids"), "cited ids", allow_empty=True)
        need(set(selected) <= set(ctx["task_map"][tid]["allowed_source_ids"]), "unauthorized retrieved source")
        need(set(cited) <= set(selected), "citation absent from delivered evidence")
        need((not answer and not cited) if row["abstained"] else bool(answer),
             "abstention/answer contradiction")
        need(type(row.get("confidence_ppm")) is int and 0 <= row["confidence_ppm"] <= 1_000_000,
             "invalid confidence")
        r = row.get("measured")
        need(isinstance(r, dict) and set(r) == set(MEASURES), "incomplete physical resource receipt")
        for key in MEASURES:
            nonnegative(r[key], f"{a}.{key}")
            if key in lim:
                need(r[key] <= lim[key], f"{a} exceeded {key} resource ceiling")
        need(r["reader_calls"] == 1, "different Reader call budget or missing Reader execution")
        need(len(selected) <= lim.get("selected_source_count", 1_000_000),
             "selected evidence count over ceiling")
        if a in "CHI":
            need(row.get("graph_artifact_sha256") == manifest["graph_artifact_sha256"],
                 "graph artifact identity changed")
        if a in "GHI":
            need(row.get("router_artifact_sha256") == manifest["router_artifact_sha256"],
                 "router artifact identity changed")
        if a in "ABCD":
            need(r["head_calls"] == 0 and r["router_calls"] == 0, "non-neural arm invoked learned Cells")
        else:
            need(r["encoder_calls"] == 1, "shared frozen Encoder forward not accounted")
        if a == "E":
            need(r["head_calls"] == 1 and r["router_calls"] == 0, "single-Head execution invalid")
        if a == "F":
            need(r["head_calls"] >= 1 and r["router_calls"] == 0, "multi-type Head accounting absent")
        if a in "GHI":
            need(r["router_calls"] >= 1 and 1 <= r["head_calls"] <= lim["head_calls"],
                 "sparse selected-only execution not observed")
        sha(row.get("invocation_receipt_sha256"), "physical invocation witness reference")
        result[(a, tid)] = row
    need(set(result) == {(a, tid) for a in ARMS for tid in ctx["eval_ids"]},
         "incomplete nine-arm prediction join")
    return result


def family_macro(values, eval_families):
    grouped = defaultdict(list)
    for family, value in values:
        grouped[family].append(value)
    need(set(grouped) == eval_families, "family denominator changed")
    return {f: statistics.mean(v) for f, v in grouped.items()}


def paired_interval(left, right, *, repetitions, seed, alpha):
    families = sorted(left)
    need(families == sorted(right), "comparison does not pair the same families")
    delta = [left[f] - right[f] for f in families]
    observed = statistics.mean(delta)
    rng = random.Random(seed)
    boot = sorted(statistics.mean(delta[rng.randrange(len(delta))] for _ in delta)
                  for _ in range(repetitions))
    # One-sided family-cluster lower bound. Bonferroni corrects all predeclared comparisons.
    index = max(0, math.floor(repetitions * alpha / len(COMPARISONS)) - 1)
    return observed, boot[index]


def adjudicate(plan, predictions, gold):
    ctx = validate_plan(plan)
    truth = validate_gold(gold, ctx)
    rows = validate_predictions(plan, ctx, predictions)
    scored, per_arm = {}, {}
    for a in ARMS:
        entries, by_family, by_slice = [], [], defaultdict(list)
        for tid in sorted(ctx["eval_ids"]):
            r, g, t = rows[(a, tid)], truth[tid], ctx["task_map"][tid]
            if g["answerable"]:
                correct = not r["abstained"] and normalized_answer(r["answer_text"]) in {
                    normalized_answer(ans) for ans in g["accepted_answers"]}
                supported = set(g["required_support_ids"]) <= set(r["cited_source_ids"])
                success = int(correct and supported)
            else:
                success = int(r["abstained"])
            entries.append(success)
            by_family.append((t["family_id"], success))
            for tag in t["tags"]:
                by_slice[tag].append(success)
            if not g["answerable"]:
                by_slice["negative"].append(success)
        groups = family_macro(by_family, ctx["eval_families"])
        scored[a] = groups
        per_arm[a] = {"macro_grounded_success": statistics.mean(groups.values()),
                      "micro_grounded_success": statistics.mean(entries),
                      "evaluated_tasks": len(entries),
                      "independent_families": len(groups),
                      "slice_success": {k: statistics.mean(v) for k, v in sorted(by_slice.items())},
                      "mean_cpu_ns": statistics.mean(rows[(a, tid)]["measured"]["cpu_ns"]
                                                for tid in ctx["eval_ids"]),
                      "mean_wall_ns": statistics.mean(rows[(a, tid)]["measured"]["wall_ns"]
                                                 for tid in ctx["eval_ids"])}
    for a in "CHI":
        need(any(rows[(a, tid)]["measured"]["graph_hops"] > 0
                 for tid in ctx["eval_ids"]), f"{a} graph never executed")
    policy = plan["acceptance"]
    eval_tasks = [ctx["task_map"][tid] for tid in ctx["eval_ids"]]
    critical_slices = ("multi_hop", "ood", "adversarial")
    covered_slices = all(any(tag in t["tags"] for t in eval_tasks)
                         for tag in critical_slices)
    window_families = defaultdict(set)
    for t in eval_tasks:
        window_families[t["future_window"]].add(t["family_id"])
    enough_window_families = all(len(v) >= max(1, policy["min_evaluation_families"] //
                                                     (2 * policy["min_future_windows"]))
                                 for v in window_families.values())
    eligible = (len(ctx["eval_families"]) >= policy["min_evaluation_families"] and
                len(ctx["windows"]) >= policy["min_future_windows"] and
                covered_slices and enough_window_families)
    contrasts, blockers = {}, []
    if not eligible:
        blockers.append("insufficient independent future source families/windows or critical slices")
    for k, (candidate, control) in enumerate(COMPARISONS):
        effect, lower = paired_interval(scored[candidate], scored[control],
                                        repetitions=policy["bootstrap_repetitions"],
                                        seed=policy["seed"] + k, alpha=0.05)
        ratio = per_arm[candidate]["mean_cpu_ns"] / max(1, per_arm[control]["mean_cpu_ns"])
        wall_ratio = per_arm[candidate]["mean_wall_ns"] / max(1, per_arm[control]["mean_wall_ns"])
        negative = []
        for tag in ("multi_hop", "ood", "negative"):
            x, y = per_arm[candidate]["slice_success"].get(tag), per_arm[control]["slice_success"].get(tag)
            if x is not None and y is not None and x - y < -policy["max_slice_regression"]:
                negative.append(tag)
        passed = (eligible and lower > policy["min_effect"] and
                  ratio <= policy["max_cost_ratio"] and
                  wall_ratio <= policy["max_cost_ratio"] and not negative)
        contrasts[f"{candidate}-{control}"] = {
            "paired_family_effect": effect, "multiplicity_adjusted_lower_bound": lower,
            "cpu_cost_ratio": ratio, "wall_cost_ratio": wall_ratio,
            "regressed_slices": negative, "passes": passed}
        if not passed:
            blockers.append(f"{candidate}-{control}: no independently qualified net gain")
    # A digest references content, not an independently authenticated signature.
    # Even a positive frozen experiment is a candidate, not verified serving evidence.
    blockers.extend(("independently authenticated source, evaluator and execution receipts missing",
                     "semantic Reader answer sufficiency and citation entailment not independently adjudicated",
                     "production withdrawal, recovery and final-use authority not qualified"))
    return {"schema_version": 1, "qualification": "HOLD_NO_GO",
            "production_activation_allowed": False,
            "independent_evaluator_authenticated": False,
            "scientific_matrix_candidate": eligible and all(v["passes"] for v in contrasts.values()),
            "arm_metrics": per_arm, "comparisons": contrasts, "blockers": blockers,
            "future_windows": sorted(ctx["windows"]),
            "notes": "Exact-string-plus-all-citations is a conservative diagnostic, not semantic answer adjudication. External evidence-owner, Reader, source and run receipt authentication are not supplied by this pure verifier."}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "predictions", "gold"):
        p.add_argument("--" + name, type=Path, required=True)
        p.add_argument("--" + name + "-sha256", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    need(not args.output.exists(), "output must be create-only")
    plan = pinned(args.plan, args.plan_sha256)
    predictions = pinned(args.predictions, args.predictions_sha256)
    gold = pinned(args.gold, args.gold_sha256)
    report = adjudicate(plan, predictions, gold)
    report["input_sha256"] = {"plan": args.plan_sha256,
                              "predictions": args.predictions_sha256,
                              "gold": args.gold_sha256}
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "qualification": report["qualification"],
                      "blockers": len(report["blockers"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
