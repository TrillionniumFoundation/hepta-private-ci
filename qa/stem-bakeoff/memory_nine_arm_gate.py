"""Source-first, prospective A-I Hepta memory qualification gate (research-only).

This module does not execute or authenticate neural models. It independently
recounts complete, externally produced ORIGINAL observations and blind judgments,
rejects changed source/model/budget identities, and never promotes production.
No labels, gold support or judgments are accepted in the frozen input plan.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from math import isfinite, sqrt
import os
from pathlib import Path
import re
from statistics import NormalDist, fmean, stdev

PROFILE = "hepta.memory.a-i.prospective-qualification.v1"
ARMS = {
    "A": "bm25",
    "B": "dense_bm25_reranker",
    "C": "graph_rag",
    "D": "typed_frozen",
    "E": "shared_single_trained_head",
    "F": "shared_typed_trained_heads",
    "G": "learned_sparse_router",
    "H": "learned_meta_graph",
    "I": "budget_matched_split_merge",
}
# Eight primary effects govern the descriptive quality gate. Three additional
# fixed baseline/typed controls are reported and included in multiplicity,
# but a weak baseline does not have to beat BM25 for I to be evaluated.
PRIMARY_CONTRASTS = {
    "typed_vs_hybrid": ("D", "B"),
    "training_vs_frozen": ("E", "D"),
    "specialization_vs_pooled": ("F", "E"),
    "learned_router": ("G", "F"),
    "learned_graph": ("H", "G"),
    "split_merge": ("I", "H"),
    "candidate_vs_hybrid": ("I", "B"),
    "candidate_vs_graph_rag": ("I", "C"),
}
DIAGNOSTIC_CONTRASTS = {
    "hybrid_vs_bm25": ("B", "A"),
    "graph_vs_bm25": ("C", "A"),
    "typed_vs_graph": ("D", "C"),
}
CONTRASTS = {**PRIMARY_CONTRASTS, **DIAGNOSTIC_CONTRASTS}
WINDOWS = ("development", "calibration", "future_a", "future_b", "retention")
CATEGORIES = ("multi_hop", "temporal", "single_hop", "procedural", "semantic",
              "adversarial", "other")
MAX_FILE = 64 * 1024 * 1024
MAX_CASES = 10_000
SHA = re.compile(r"[0-9a-f]{64}\Z")
CITATION = re.compile(r"\[E([^\]\r\n]*)\]")
SAFE_ID = re.compile(r"[A-Za-z0-9_.:-]{1,160}\Z")


class Refused(ValueError):
    """A missing, forged, ambiguous or incompatible audit input."""


def require(condition, why):
    if not condition:
        raise Refused(why)


def keys(value, fields, where):
    require(type(value) is dict and set(value) == set(fields), where)


def integer(value, why, *, minimum=0, maximum=10**18):
    require(type(value) is int and minimum <= value <= maximum, why)


def token(value, why):
    require(type(value) is str and SAFE_ID.fullmatch(value) is not None, why)


def digest(value, why):
    require(type(value) is str and SHA.fullmatch(value) is not None
            and value != "0" * 64, why)


def sha(data):
    return sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def distinct_strings(items, why, limit=4096):
    require(type(items) is list and len(items) <= limit, why)
    for item in items:
        token(item, why)
    require(len(items) == len(set(items)), why)


def read_json(path):
    raw = Path(path).read_bytes()
    require(0 < len(raw) <= MAX_FILE, "missing/oversized input")
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise Refused("invalid input JSON") from exc


def validate_plan(plan):
    keys(plan, ("schema", "common", "cases", "arms", "policy"), "plan keys")
    require(plan["schema"] == PROFILE, "plan schema")
    common = plan["common"]
    keys(common, ("reader_sha256", "tokenizer_sha256", "prompt_sha256",
                  "encoder_sha256", "source_frontier_sha256",
                  "forget_frontier_sha256", "max_context_tokens",
                  "max_generated_tokens", "max_evidence_slots",
                  "training_roots", "calibration_roots"), "common identity")
    for field in ("reader_sha256", "tokenizer_sha256", "prompt_sha256",
                  "encoder_sha256", "source_frontier_sha256",
                  "forget_frontier_sha256"):
        digest(common[field], field)
    for field, bound in (("max_context_tokens", 32768),
                         ("max_generated_tokens", 2048),
                         ("max_evidence_slots", 64)):
        integer(common[field], field, minimum=1, maximum=bound)
    distinct_strings(common["training_roots"], "training roots")
    distinct_strings(common["calibration_roots"], "calibration roots")
    require(common["training_roots"] and common["calibration_roots"],
            "training/calibration source closure required")
    require(not set(common["training_roots"]) & set(common["calibration_roots"]),
            "training/calibration source overlap")

    policy = plan["policy"]
    keys(policy, ("alpha", "min_independent_future_groups",
                  "min_independent_groups_per_future_window",
                  "max_candidate_cpu_ratio", "max_candidate_rss_ratio"),
         "frozen policy")
    require(type(policy["alpha"]) is float and .0001 <= policy["alpha"] <= .05,
            "invalid fixed alpha")
    for field in ("min_independent_future_groups",
                  "min_independent_groups_per_future_window"):
        integer(policy[field], field, minimum=2, maximum=10000)
    for field in ("max_candidate_cpu_ratio", "max_candidate_rss_ratio"):
        v = policy[field]
        require(type(v) in (float, int) and isfinite(v) and 1 <= v <= 100,
                "invalid fixed resource threshold")

    require(type(plan["arms"]) is dict and set(plan["arms"]) == set(ARMS),
            "all nine precommitted arms required")
    for arm, profile in ARMS.items():
        bank = plan["arms"][arm]
        keys(bank, ("profile", "artifact_sha256", "training_receipt_sha256",
                    "trained_heads", "head_parameters", "head_optimizer_steps",
                    "head_optimizer_examples", "total_training_budget_units",
                    "max_head_calls", "resident_budget_bytes"), "arm bank")
        require(bank["profile"] == profile, "wrong architecture arm")
        digest(bank["artifact_sha256"], "artifact identity")
        digest(bank["training_receipt_sha256"], "training receipt identity")
        for field in ("trained_heads", "head_parameters", "head_optimizer_steps",
                      "head_optimizer_examples", "total_training_budget_units",
                      "max_head_calls", "resident_budget_bytes"):
            integer(bank[field], field, maximum=10**12)
        require(bank["resident_budget_bytes"] > 0, "zero resident budget")
        if arm in "ABCD":
            require(all(bank[f] == 0 for f in ("trained_heads", "head_parameters",
                    "head_optimizer_steps", "head_optimizer_examples",
                    "total_training_budget_units", "max_head_calls")),
                    "baseline cannot masquerade as a trained Head")
        else:
            require(bank["trained_heads"] == (1 if arm == "E" else 2),
                    "pooled / specialist Head population must be fixed")
            require(all(bank[f] > 0 for f in ("head_parameters",
                    "head_optimizer_steps", "head_optimizer_examples",
                    "total_training_budget_units", "max_head_calls")),
                    "missing trained Head work")
            require(bank["max_head_calls"] == (2 if arm == "F" else 1),
                    "only F may invoke both type Heads per case")

    # E-I share the total trainable Head capacity, learning examples and
    # allocator ceiling; Router/Graph/Evolution work must fit the SAME total
    # training budget rather than receiving free additional optimization.
    trained = [plan["arms"][a] for a in "EFGHI"]
    for field in ("head_parameters", "head_optimizer_examples",
                  "total_training_budget_units", "resident_budget_bytes"):
        require(len({b[field] for b in trained}) == 1, "unmatched " + field)
    require(plan["arms"]["I"]["head_optimizer_steps"]
            == plan["arms"]["H"]["head_optimizer_steps"],
            "split and static continuation must have matched Head steps")

    cases = plan["cases"]
    require(type(cases) is list and 1 <= len(cases) <= MAX_CASES,
            "invalid case census")
    seen, splits, family_window = set(), set(), {}
    known_train = set(common["training_roots"]) | set(common["calibration_roots"])
    root_window, source_id_window, query_window = {}, {}, {}
    for case in cases:
        keys(case, ("id", "family_id", "window", "question_sha256",
                    "snapshot_sha256", "source_roots", "eligible_source_ids"),
             "source-first case has missing/extra labels")
        token(case["id"], "case ID")
        token(case["family_id"], "family ID")
        require(case["id"] not in seen, "duplicate case")
        seen.add(case["id"])
        require(case["window"] in WINDOWS, "invalid cohort window")
        splits.add(case["window"])
        digest(case["question_sha256"], "question hash")
        digest(case["snapshot_sha256"], "snapshot hash")
        distinct_strings(case["source_roots"], "source roots")
        distinct_strings(case["eligible_source_ids"], "eligible sources")
        require(case["source_roots"] and case["eligible_source_ids"],
                "empty original source inventory")
        require(not known_train.intersection(case["source_roots"]),
                "training/calibration ancestor leaks into evaluation")
        old = family_window.setdefault(case["family_id"], case["window"])
        require(old == case["window"], "family reused across windows")
        for root in case["source_roots"]:
            previous = root_window.setdefault(root, case["window"])
            require(previous == case["window"], "source-root cross-window leak")
        # Disjoint root labels alone do not prove disjoint evidence or queries.
        for source_id in case["eligible_source_ids"]:
            previous = source_id_window.setdefault(source_id, case["window"])
            require(previous == case["window"], "source ID cross-window reuse")
        previous = query_window.setdefault(case["question_sha256"], case["window"])
        require(previous == case["window"], "identical question cross-window reuse")
    require({"future_a", "future_b"} <= splits, "two named future windows absent")
    return {case["id"]: case for case in cases}


def citations(answer, sources):
    # Citation IDs refer to the exact ordered Reader evidence slots, not
    # arbitrary source values supplied by the producing worker.
    result = []
    for match in CITATION.finditer(answer):
        raw = match.group(1)
        require(raw.isascii() and raw.isdigit() and raw[0] != "0",
                "malformed original Reader citation")
        pos = int(raw)
        require(1 <= pos <= len(sources), "orphan Reader citation")
        result.append(sources[pos - 1])
    require(answer.count("[E") == len(CITATION.findall(answer)),
            "unparsed Reader citation marker")
    return result


def audit_rows(plan, observations, judgments):
    cases = validate_plan(plan)
    expected = {(case_id, arm) for case_id in cases for arm in ARMS}
    require(type(observations) is list and len(observations) == len(expected),
            "original observation census incomplete")
    require(type(judgments) is list and len(judgments) == len(expected),
            "independent judgment census incomplete")
    common = plan["common"]
    orig, scored = {}, {}
    for obs in observations:
        keys(obs, ("case_id", "arm", "status", "question_sha256",
                   "snapshot_sha256", "source_frontier_sha256",
                   "forget_frontier_sha256", "reader_sha256",
                   "tokenizer_sha256", "prompt_sha256", "encoder_sha256",
                   "artifact_sha256", "selected_source_ids",
                   "context_sha256", "context_tokens", "generated_tokens",
                   "answer", "answer_sha256", "worker_receipt_sha256",
                   "reader_calls", "encoder_forwards", "dense_forwards",
                   "reranker_forwards", "graph_traversals", "typed_lookups",
                   "router_forwards", "head_calls", "latency_ns", "cpu_ns",
                   "peak_rss_bytes"), "original observation keys")
        key = (obs["case_id"], obs["arm"])
        require(key in expected and key not in orig, "duplicate/unknown original call")
        case, bank = cases[key[0]], plan["arms"][key[1]]
        require(obs["status"] in ("answered", "abstained", "unavailable"),
                "unknown original Reader outcome")
        require(obs["question_sha256"] == case["question_sha256"]
                and obs["snapshot_sha256"] == case["snapshot_sha256"],
                "question/source snapshot drift")
        for field in ("source_frontier_sha256", "forget_frontier_sha256",
                      "reader_sha256", "tokenizer_sha256", "prompt_sha256",
                      "encoder_sha256"):
            require(obs[field] == common[field], field + " drift")
        require(obs["artifact_sha256"] == bank["artifact_sha256"],
                "wrong physical arm artifact")
        for field in ("context_sha256", "worker_receipt_sha256"):
            digest(obs[field], field)
        require(type(obs["answer"]) is str
                and len(obs["answer"].encode("utf-8")) <= 65536,
                "invalid original answer bytes")
        require(obs["answer_sha256"] == sha(obs["answer"].encode("utf-8")),
                "original answer modified")
        distinct_strings(obs["selected_source_ids"], "delivered original source IDs", 64)
        require(len(obs["selected_source_ids"]) <= common["max_evidence_slots"]
                and set(obs["selected_source_ids"]) <= set(case["eligible_source_ids"]),
                "unsupported/or withdrawn evidence used")
        for field in ("context_tokens", "generated_tokens", "reader_calls",
                      "encoder_forwards", "dense_forwards", "reranker_forwards",
                      "graph_traversals", "typed_lookups", "router_forwards",
                      "head_calls", "latency_ns", "cpu_ns", "peak_rss_bytes"):
            integer(obs[field], field, maximum=10**16)
        require(obs["context_tokens"] <= common["max_context_tokens"]
                and obs["generated_tokens"] <= common["max_generated_tokens"],
                "original Reader token budget exceeded")
        require(obs["head_calls"] <= bank["max_head_calls"],
                "unbudgeted private Head invocation")
        require(obs["latency_ns"] > 0 and obs["cpu_ns"] > 0
                and obs["peak_rss_bytes"] > 0
                and obs["peak_rss_bytes"] <= bank["resident_budget_bytes"],
                "missing/overbudget measured resource")
        if obs["status"] == "unavailable":
            require(obs["reader_calls"] == 0 and obs["answer"] == "",
                    "unavailable call forged as Reader success")
        else:
            require(obs["reader_calls"] == 1, "no physical Reader forward")
            if obs["status"] == "answered":
                require(obs["answer"].strip() and obs["generated_tokens"] > 0,
                        "empty success-shaped original generation")
                # A valid model digest does not prove the intended retrieval
                # architecture actually ran on this case. Never allow one
                # expensive call to stand in for other accepted observations.
                mechanisms = {
                    "A": (),
                    "B": ("dense_forwards", "reranker_forwards"),
                    "C": ("graph_traversals",),
                    "D": ("typed_lookups",),
                    "E": ("encoder_forwards", "head_calls"),
                    "F": ("encoder_forwards", "typed_lookups", "head_calls"),
                    "G": ("encoder_forwards", "router_forwards", "head_calls"),
                    "H": ("encoder_forwards", "router_forwards",
                          "graph_traversals", "head_calls"),
                    "I": ("encoder_forwards", "router_forwards",
                          "graph_traversals", "head_calls"),
                }
                require(all(obs[field] > 0 for field in mechanisms[key[1]]),
                        "accepted original answer bypassed its A-I mechanism")
                if key[1] == "A":
                    require(all(obs[field] == 0 for field in (
                        "encoder_forwards", "dense_forwards", "reranker_forwards",
                        "graph_traversals", "typed_lookups", "router_forwards",
                        "head_calls")), "BM25 baseline used unregistered neural work")
        citations(obs["answer"], obs["selected_source_ids"])
        orig[key] = obs

    gold_per_case = {}
    judge_ids = set()
    for judge in judgments:
        keys(judge, ("case_id", "arm", "answer_sha256",
                     "judge_receipt_sha256", "judge_id", "gold_status",
                     "gold_support_ids", "category", "correct", "grounded",
                     "semantic_citation_entailment", "proper_abstention",
                     "unsafe"), "separate blind judgment keys")
        key = (judge["case_id"], judge["arm"])
        require(key in expected and key not in scored, "duplicate/unknown judgment")
        obs, case = orig[key], cases[key[0]]
        digest(judge["judge_receipt_sha256"], "independent review receipt")
        token(judge["judge_id"], "reviewer ID")
        judge_ids.add(judge["judge_id"])
        require(judge["answer_sha256"] == obs["answer_sha256"],
                "judge assessed a different original answer")
        require(judge["gold_status"] in ("scorable", "adversarial",
                                         "missing", "unresolved"), "gold status")
        require(judge["category"] in CATEGORIES, "independent category")
        distinct_strings(judge["gold_support_ids"], "original support IDs")
        require(set(judge["gold_support_ids"]) <= set(case["eligible_source_ids"]),
                "reviewer support outside source snapshot")
        if judge["gold_status"] == "scorable":
            require(judge["gold_support_ids"], "positive question without source support")
        if judge["gold_status"] == "adversarial":
            require(not judge["gold_support_ids"], "adversarial with positive support")
        for field in ("correct", "grounded", "semantic_citation_entailment",
                      "proper_abstention", "unsafe"):
            require(type(judge[field]) is bool, "forged or nullable judgment " + field)
        previous = gold_per_case.setdefault(key[0],
                        (judge["gold_status"], set(judge["gold_support_ids"]),
                         judge["category"]))
        require(previous == (judge["gold_status"], set(judge["gold_support_ids"]),
                             judge["category"]),
                "gold changed by memory arm")
        cited = citations(obs["answer"], obs["selected_source_ids"])
        if judge["grounded"] and obs["status"] == "answered":
            require(cited, "unsupported claim of citation grounding")
        if judge["proper_abstention"]:
            require(obs["status"] == "abstained", "abstention status invented")
        # An adverse outcome or missing source stays in the original denominator.
        effective = int(
            (judge["gold_status"] == "scorable" and obs["status"] == "answered"
             and judge["correct"] and judge["grounded"]
             and judge["semantic_citation_entailment"] and not judge["unsafe"])
            or (judge["gold_status"] == "adversarial" and obs["status"] == "abstained"
                and judge["proper_abstention"] and not judge["unsafe"]))
        scored[key] = {
            "utility": effective, "unsafe": judge["unsafe"],
            "full_gold_support": (set(judge["gold_support_ids"])
                                  <= set(obs["selected_source_ids"])
                                  if judge["gold_status"] == "scorable" else None),
            "unavailable": obs["status"] == "unavailable",
            "gold_status": judge["gold_status"], "category": judge["category"],
            "cpu_ns": obs["cpu_ns"], "rss": obs["peak_rss_bytes"],
        }
    require(set(orig) == expected and set(scored) == expected,
            "paired original/gold census not closed")
    return cases, scored, len(judge_ids)


def independent_components(cases, window):
    """Union transitive common source-root ancestors; never count query rows as N."""
    subset = [c for c in cases.values() if c["window"] == window]
    parent = {c["id"]: c["id"] for c in subset}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    # Both explicit source ancestry and source-family identity create
    # dependence. Separate source-root labels do not make two tasks from
    # one family statistically independent.
    ancestor_owner = {}
    for case in subset:
        ancestors = ([("source", root) for root in case["source_roots"]]
                     + [("family", case["family_id"])])
        for ancestor in ancestors:
            if ancestor in ancestor_owner:
                parent[find(case["id"])] = find(ancestor_owner[ancestor])
            else:
                ancestor_owner[ancestor] = case["id"]
    groups = defaultdict(list)
    for case in subset:
        groups[find(case["id"])].append(case["id"])
    return list(groups.values())


def effect(groups, scores, left, right, alpha):
    paired = [fmean(scores[(case, left)]["utility"]
                    - scores[(case, right)]["utility"] for case in group)
              for group in groups]
    n = len(paired)
    mean = fmean(paired) if paired else 0.0
    # Simultaneous, approximate Gaussian family-cluster interval.
    # This is NOT an authenticated independent-source or causal proof.
    multiplicity = len(CONTRASTS) + 4
    z = NormalDist().inv_cdf(1 - alpha / (2 * multiplicity))
    radius = z * stdev(paired) / sqrt(n) if n > 1 else 1.0
    if n < 30:
        radius = 1.0  # explicit low-power refusal
    return {"independent_components": n, "delta": mean,
            "lower": max(-1.0, mean - radius),
            "upper": min(1.0, mean + radius),
            "interval_kind": "descriptive_bonferroni_gaussian_cluster"}


def audit(plan, observations, judgments, expected_plan_sha256,
          training_receipts=None):
    digest(expected_plan_sha256, "externally pinned plan")
    require(sha(canonical(plan)) == expected_plan_sha256,
            "plan changed after external freeze")
    cases, scores, judge_count = audit_rows(plan, observations, judgments)
    # The old A-I contract matched *declared* learning budgets but did not
    # reconcile actual E-I optimizer/graph/evolution journals. A missing
    # training receipt now blocks external qualification, not the old synthetic
    # contract tests. Even a matching receipt is not an authenticated host.
    training_audit = None
    if training_receipts is not None:
        from memory_nine_arm_training_cost import verify_training_receipts
        training_audit = verify_training_receipts(plan, training_receipts)
    training_cost_gate = training_audit is not None
    groups = (independent_components(cases, "future_a")
              + independent_components(cases, "future_b"))
    alpha = plan["policy"]["alpha"]
    contrasts = {name: effect(groups, scores, a, b, alpha)
                 for name, (a, b) in CONTRASTS.items()}
    by_window = {
        window: {
            pair: effect(independent_components(cases, window), scores,
                         left, right, alpha)
            for pair, (left, right) in {
                "I_minus_B": ("I", "B"), "I_minus_C": ("I", "C")
            }.items()
        } for window in ("future_a", "future_b")
    }
    future = [c["id"] for c in cases.values()
              if c["window"] in ("future_a", "future_b")]
    per_arm = {}
    for arm in ARMS:
        rows = [scores[(case, arm)] for case in future]
        per_arm[arm] = {
            "task_utility_mean": fmean(r["utility"] for r in rows),
            "total_cpu_ns": sum(r["cpu_ns"] for r in rows),
            "peak_rss_bytes": max(r["rss"] for r in rows),
            "unsafe_count": sum(r["unsafe"] for r in rows),
            "unavailable_count": sum(r["unavailable"] for r in rows),
            "missing_or_unresolved": sum(r["gold_status"] in ("missing", "unresolved")
                                          for r in rows),
            "by_category": {
                category: {"cases": sum(r["category"] == category for r in rows),
                           "task_utility_mean": fmean(r["utility"] for r in rows
                              if r["category"] == category)}
                for category in CATEGORIES if any(r["category"] == category for r in rows)
            },
            "full_gold_support_rate": (
                fmean(float(r["full_gold_support"]) for r in rows
                      if r["full_gold_support"] is not None)
                if any(r["full_gold_support"] is not None for r in rows) else None),
        }
    p = plan["policy"]
    win_counts = {name: len(independent_components(cases, name))
                  for name in ("future_a", "future_b")}
    future_n = sum(win_counts.values())
    quality = (future_n >= p["min_independent_future_groups"]
               and all(n >= p["min_independent_groups_per_future_window"]
                       for n in win_counts.values())
               and all(contrasts[name]["lower"] > 0 for name in PRIMARY_CONTRASTS)
               and all(item["lower"] > 0 for window in by_window.values()
                       for item in window.values()))
    cpu_ratio = (per_arm["I"]["total_cpu_ns"]
                 / per_arm["B"]["total_cpu_ns"])
    rss_ratio = (per_arm["I"]["peak_rss_bytes"]
                 / per_arm["B"]["peak_rss_bytes"])
    safety = all(v["unsafe_count"] == 0 and v["unavailable_count"] == 0
                 and v["missing_or_unresolved"] == 0 for v in per_arm.values())
    costs = (cpu_ratio <= p["max_candidate_cpu_ratio"]
             and rss_ratio <= p["max_candidate_rss_ratio"])
    blockers = []
    if not quality:
        blockers.append("paired independent-family / two-future-window uplift not established")
    if not safety:
        blockers.append("unsafe/unavailable/unscorable original outcomes remain")
    if not costs:
        blockers.append("CPU/RSS candidate ceiling failed")
    if not training_cost_gate:
        blockers.append("E-I actual optimizer/router/graph/evolution work budget and source lineage not reconciled")
    blockers.extend((
        "original model/source and independent reviewer signatures not authenticated",
        "actual training FLOPs, full lifecycle cost, deletion and recovery not verified",
        "production authority and multi-host qualification not granted",
    ))
    return {
        "schema": PROFILE + ".report",
        "plan_sha256": expected_plan_sha256,
        "observations_sha256": sha(canonical(observations)),
        "judgments_sha256": sha(canonical(judgments)),
        "planned_cases": len(cases),
        "original_Reader_attempts": len(observations),
        "blind_judgments": len(judgments),
        "reviewer_id_count_unverified": judge_count,
        "effective_future_source_components": future_n,
        "components_by_window": win_counts,
        "contrasts": contrasts,
        "future_window_contrasts": by_window,
        "per_arm": per_arm,
        "candidate_to_hybrid_cpu_ratio": cpu_ratio,
        "candidate_to_hybrid_peak_rss_ratio": rss_ratio,
        "descriptive_quality_gate": quality,
        "measured_task_cost_gate": costs,
        "task_safety_gate": safety,
        "physical_e_i_training_cost_gate": training_cost_gate,
        "physical_e_i_training_audit": training_audit,
        "eligible_for_external_authenticity_review": bool(
            quality and costs and safety and training_cost_gate),
        "production_accepted": False,
        "superiority_established": False,
        "authority": "DENY_ALL",
        "status": "HOLD_NO_GO",
        "blockers": blockers,
    }


def create_only(path, value):
    raw = canonical(value) + b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--judgments", type=Path, required=True)
    parser.add_argument("--training-receipts", type=Path,
                        help="source-sealed E-I physical training events; absence is HOLD_NO_GO")
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    training_receipts = (read_json(args.training_receipts)
                         if args.training_receipts is not None else None)
    result = audit(read_json(args.plan), read_json(args.observations),
                   read_json(args.judgments), args.expected_plan_sha256,
                   training_receipts=training_receipts)
    create_only(args.report, result)
    print(json.dumps({"status": result["status"], "report": str(args.report),
                      "blockers": result["blockers"]}, sort_keys=True))


if __name__ == "__main__":
    main()
