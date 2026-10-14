"""Source-bound, model-free four-arm Reader diagnostic accounting.

Consumes ORIGINAL externally generated answer receipts and a later separately
sealed score table. This module cannot execute models, rewrite answers, judge
citation entailment or independently authenticate external human reviewers.
"""
from __future__ import annotations

from collections import defaultdict
from math import log, sqrt, isfinite

from amcn_core import ARMS, Refused, digest, is_sha, require, freeze_reader_quartets, shadow_disposition

PROTOCOL = "hepta.amcn.reader-score.v1"
CONTRASTS = (("human_sufficient", "ordinary_retrieval"),
             ("human_sufficient", "critical_premise_removed"),
             ("ordinary_retrieval", "no_evidence"))


def score_reader_quartets(request_rows, answers, independent_scores,
                          *, evaluator_receipt_sha256, failure_score=0.0):
    """Compute DESCRIPTIVE matched family deltas; never claim external signoff.

    Original answers and source identities must be complete before externally
    scored judgments are opened. Integrity and role independence are separate.
    """
    plan = freeze_reader_quartets(request_rows)
    require(is_sha(evaluator_receipt_sha256), "missing separately supplied evaluator pin")
    require(type(failure_score) is float and failure_score == 0.0,
            "undeclared failure imputation policy")
    expected = {(r["case_id"], r["arm"]): r for r in request_rows}
    require(isinstance(answers, list) and len(answers) == len(expected), "complete raw answer census")
    needed = {"case_id", "arm", "family", "response_sha256", "status",
              "emitted_evidence_ids", "input_tokens", "output_tokens",
              "observed_wall_ms", "source_frontier_sha256"}
    originals = {}
    for raw in answers:
        require(isinstance(raw, dict) and set(raw) == needed, "raw execution shape")
        key = (raw["case_id"], raw["arm"])
        require(key in expected and key not in originals, "duplicate/unmatched answer")
        req = expected[key]
        require(raw["family"] == req["family"] and
                raw["source_frontier_sha256"] == req["source_frontier_sha256"],
                "answer source identity drift")
        require(raw["status"] in ("success", "failed"), "unknown original execution outcome")
        require(raw["status"] == "failed" and raw["response_sha256"] is None or
                raw["status"] == "success" and is_sha(raw["response_sha256"]),
                "missing/forged response digest")
        require(isinstance(raw["emitted_evidence_ids"], list) and
                all(isinstance(x, str) and x for x in raw["emitted_evidence_ids"]),
                "citation structure")
        require(all(type(raw[t]) is int and raw[t] >= 0 for t in
                    ("input_tokens", "output_tokens", "observed_wall_ms")),
                "actual usage receipt")
        originals[key] = raw
    require(set(originals) == set(expected), "incomplete original model answer census")
    require(isinstance(independent_scores, list)
            and len(independent_scores) == len(expected), "complete blind scoring census")
    scores = {}
    for entry in independent_scores:
        require(isinstance(entry, dict) and set(entry) ==
                {"case_id", "arm", "response_sha256", "score", "metric", "score_receipt_sha256"},
                "score input schema")
        key = (entry["case_id"], entry["arm"])
        require(key in expected and key not in scores, "duplicate/unmatched judgment")
        require(entry["response_sha256"] == originals[key]["response_sha256"],
                "post-generation response text alteration")
        require(entry["metric"] == "externally_scored_binary_success_v1"
                and is_sha(entry["score_receipt_sha256"]), "incompatible metric")
        require(type(entry["score"]) in (int, float) and isfinite(entry["score"])
                and 0 <= entry["score"] <= 1, "bounded descriptive outcome")
        if originals[key]["status"] == "failed":
            require(entry["score"] == failure_score, "failed call relabelled successful")
        scores[key] = float(entry["score"])
    require(set(scores) == set(expected), "missing original score")
    cases = defaultdict(dict)
    families = defaultdict(lambda: defaultdict(list))
    citation_invalid = defaultdict(int)
    tokens = defaultdict(lambda: {"input": 0, "output": 0, "wall_ms": 0, "failed": 0})
    for key, raw in originals.items():
        case_id, arm = key
        request = expected[key]
        families[request["family"]][arm].append(scores[key])
        require(arm not in cases[case_id], "duplicate per-case arm")
        cases[case_id][arm] = scores[key]
        delivered = set(request["evidence_ids"])
        citation_invalid[arm] += sum(e not in delivered for e in raw["emitted_evidence_ids"])
        tokens[arm]["input"] += raw["input_tokens"]
        tokens[arm]["output"] += raw["output_tokens"]
        tokens[arm]["wall_ms"] += raw["observed_wall_ms"]
        tokens[arm]["failed"] += (raw["status"] == "failed")
    require(all(set(group) == set(ARMS) for group in cases.values()), "four-arm score mismatch")
    for family, arms in families.items():
        require(set(arms) == set(ARMS), "incomplete family comparison")
    summary = {}
    n = len(families)
    alpha = 0.05 / len(CONTRASTS)
    # Conservative family-wise Hoeffding bound for differences in [-1,1];
    # not a proof of true independent families. No significance from repeats.
    radius = 2.0 * sqrt(log(2.0 / alpha) / (2.0 * n))
    for lhs, rhs in CONTRASTS:
        diffs = []
        for fam, arms in sorted(families.items()):
            left = sum(arms[lhs]) / len(arms[lhs])
            right = sum(arms[rhs]) / len(arms[rhs])
            diffs.append(left - right)
        delta = sum(diffs) / n
        summary[f"{lhs}-minus-{rhs}"] = {
            "mean_delta": delta, "95pct_family_interval": [
                max(-1.0, delta - radius), min(1.0, delta + radius)],
            "effective_family_upper_bound": n,
            "independence_authenticated": False,
        }
    return shadow_disposition(
        profile=PROTOCOL, request_plan_sha256=plan["request_sha256"],
        original_answer_receipt_sha256=digest(answers),
        external_judgment_receipt_sha256=evaluator_receipt_sha256,
        original_scored_answer_binding_sha256=digest(independent_scores),
        executed_answers=len(answers), families_upper_bound=n,
        alpha_familywise=0.05, comparisons=summary,
        observed_costs=dict(tokens), undelivered_citation_labels=dict(citation_invalid),
        semantic_citation_precision=None, independent_reviewer_authenticated=False,
        strong_hybrid_rag_compared=False, production_accepted=False,
    )
