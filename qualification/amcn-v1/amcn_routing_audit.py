"""Blinded read-only fixed-Reader graph vs strong hybrid RAG comparison.

Actual strong-RAG scores and model outputs are supplied by existing Hepta
owners, never approximated by this file's simple BM25 reference. This is a
strict pairing/accounting contract, NOT a new production evaluator or signer.
"""
from __future__ import annotations

from collections import defaultdict
from math import sqrt, log, isfinite

from amcn_core import digest, is_sha, require, shadow_disposition

ARMS = ("cell_independent", "cell_fixed_graph", "cell_learned_route", "strong_hybrid_rag")
METRIC = "external_independent_task_success_v1"


def compare_routing(original_runs, independent_judgments, *, scorer_pin, alpha=0.05):
    """Do not open judgments until all exact Reader/graph outputs are sealed."""
    require(is_sha(scorer_pin) and alpha == 0.05, "independent evaluation plan pin")
    require(isinstance(original_runs, list) and original_runs
            and len(original_runs) <= 65536, "original runs required")
    shape = {"case_id", "family", "split", "arm", "question_sha256",
             "source_frontier_sha256", "reader_sha256", "prompt_sha256",
             "evidence_ids", "raw_answer_sha256", "status",
             "original_inference_receipt_sha256", "input_tokens",
             "output_tokens", "measured_wall_ms"}
    cases, original = defaultdict(dict), {}
    for record in original_runs:
        require(isinstance(record, dict) and set(record) == shape, "routing outcome shape")
        key = record["case_id"], record["arm"]
        require(record["arm"] in ARMS and key not in original, "unknown/duplicate route")
        require(record["split"] in ("future_a", "future_b", "retention"),
                "no TRAIN/SELECT outcomes in final evaluation")
        require(all(is_sha(record[k]) for k in ("question_sha256",
                "source_frontier_sha256", "reader_sha256", "prompt_sha256",
                "original_inference_receipt_sha256")), "unsealed identity")
        require(record["status"] in ("ok", "failed")
                and (is_sha(record["raw_answer_sha256"]) if record["status"] == "ok"
                     else record["raw_answer_sha256"] is None), "invalid model outcome")
        require(isinstance(record["evidence_ids"], list)
                and len(record["evidence_ids"]) <= 16
                and all(isinstance(x, str) and x for x in record["evidence_ids"]),
                "exact selected evidence IDs")
        require(all(type(record[k]) is int and record[k] >= 0 for k in
                    ("input_tokens", "output_tokens", "measured_wall_ms")),
                "actual resource meters")
        original[key] = record
        cases[record["case_id"]][record["arm"]] = record
    require(all(set(arms) == set(ARMS) for arms in cases.values()), "four matched graph/RAG arms")
    for case_id, arms in cases.items():
        pivot = arms[ARMS[0]]
        for arm in ARMS[1:]:
            comp = arms[arm]
            for field in ("family", "split", "question_sha256",
                          "source_frontier_sha256", "reader_sha256", "prompt_sha256"):
                require(comp[field] == pivot[field], "reader/task/source drift across routes")
    require(isinstance(independent_judgments, list) and
            len(independent_judgments) == len(original), "complete independently scored census")
    scores, families = {}, defaultdict(lambda: defaultdict(list))
    for entry in independent_judgments:
        require(isinstance(entry, dict) and set(entry) == {"case_id", "arm",
                "raw_answer_sha256", "score", "metric", "judgment_sha256"},
                "immutable scored answer envelope")
        key = entry["case_id"], entry["arm"]
        require(key in original and key not in scores
                and entry["metric"] == METRIC and is_sha(entry["judgment_sha256"])
                and entry["raw_answer_sha256"] == original[key]["raw_answer_sha256"],
                "scorer/answer mismatch")
        score = entry["score"]
        require(type(score) in (int, float) and isfinite(score)
                and 0 <= score <= 1, "bounded success metric")
        if original[key]["status"] != "ok":
            require(score == 0, "failed model response cannot be rated successful")
        scores[key] = float(score)
        fam = original[key]["family"]
        families[fam][entry["arm"]].append(float(score))
    require(set(scores) == set(original), "missing independent outcomes")
    costs = {}
    for arm in ARMS:
        group = [x for x in original.values() if x["arm"] == arm]
        costs[arm] = {
            "input_tokens": sum(x["input_tokens"] for x in group),
            "output_tokens": sum(x["output_tokens"] for x in group),
            "observed_wall_ms_sum": sum(x["measured_wall_ms"] for x in group),
            "failed": sum(x["status"] == "failed" for x in group)
        }
    family_count = len(families)
    comparisons = {}
    for candidate in ARMS[:-1]:
        diffs = []
        for group in families.values():
            require(set(group) == set(ARMS), "incomplete source-family coverage")
            mean = lambda a: sum(group[a]) / len(group[a])
            diffs.append(mean(candidate) - mean("strong_hybrid_rag"))
        delta = sum(diffs) / family_count
        radius = 2 * sqrt(log(2 * 3 / alpha) / (2 * family_count))
        comparisons[candidate] = {
            "mean_success_gain_vs_strong_rag": delta,
            "descriptive_simultaneous_95pct_interval":
                [max(-1., delta - radius), min(1., delta + radius)],
            "source_family_count_upper_bound": family_count,
            "independent_family_provenance_verified_here": False,
        }
    return shadow_disposition(
        profile="hepta.amcn.strong-rag-routes.v1",
        original_outcomes_sha256=digest(original_runs),
        external_judgments_sha256=digest(independent_judgments),
        scorer_pin=scorer_pin, source_families_upper_bound=family_count,
        comparisons=comparisons, cost=costs,
        semantic_citation_precision=None,
        strong_hybrid_rag_really_executed_here=False,
        reader_unchanged_admission_claim=False,
        independent_evaluator_accepted=False)
