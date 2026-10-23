"""Evaluator-only support retrieval and answerability diagnostics.

No answer generation, semantic entailment or procedure execution is scored.
Question categories and exact gold references are consumed only in this module.
"""

from collections import defaultdict
import math
import random
import statistics


def mean(values):
    return statistics.fmean(values) if values else None


def score_query(query, gold, selected_ids, *, accepted=True):
    valid = gold.category != 5 and bool(gold.evidence) and not gold.unresolved
    expected = set(gold.evidence)
    chosen = set(selected_ids) if accepted else set()
    hits = len(expected & chosen)
    return {
        "query_id": query.query_id, "group": query.group, "category": gold.category,
        "annotation_status": ("adversarial" if gold.category == 5 else
            "unresolved" if gold.unresolved else "missing" if not expected else "scorable"),
        "evidence_has_image": gold.evidence_has_image,
        "gold_evidence_count": len(expected), "unresolved_evidence": list(gold.unresolved),
        "support_recall": hits / len(expected) if valid else None,
        "all_support_recalled": int(expected <= chosen) if valid else None,
        "any_support_recalled": int(bool(expected & chosen)) if valid else None,
        "accepted": accepted,
        "answerability_screen_correct": int(accepted == (gold.category != 5)),
    }


def summarize(rows):
    scored = [r for r in rows if r["support_recall"] is not None]
    groups = defaultdict(list)
    for row in scored:
        groups[row["group"]].append(row)
    answerable = [r for r in rows if r["category"] != 5]
    adversarial = [r for r in rows if r["category"] == 5]
    tpr = mean([float(r["accepted"]) for r in answerable])
    tnr = mean([float(not r["accepted"]) for r in adversarial])
    return {
        "planned_questions": len(rows), "scorable_support_questions": len(scored),
        "adversarial_questions": len(adversarial),
        "unresolved_or_missing_questions": sum(r["annotation_status"] in ("unresolved", "missing") for r in rows),
        "support_recall": mean([r["support_recall"] for r in scored]),
        "all_support_recalled": mean([r["all_support_recalled"] for r in scored]),
        "any_support_recalled": mean([r["any_support_recalled"] for r in scored]),
        "group_macro_support_recall": mean([mean([r["support_recall"] for r in values]) for values in groups.values()]),
        "group_macro_all_support": mean([mean([r["all_support_recalled"] for r in values]) for values in groups.values()]),
        "acceptance_rate": mean([float(r["accepted"]) for r in rows]),
        "answerability_balanced_accuracy": (tpr + tnr) / 2 if tpr is not None and tnr is not None else None,
    }


def select_configuration(scores):
    """Caller passes development-only aggregate results, never test outcomes."""
    return max(scores, key=lambda key: (
        scores[key]["group_macro_all_support"], scores[key]["group_macro_support_recall"],
        -float(key)))


def calibrate_threshold(rows_by_threshold):
    """Calibration-only answerability screen; it never provides factual text.

    Ties prefer higher answerable coverage, then the lower threshold. This is a
    lexical abstention screen, not calibrated probability of factual correctness.
    """
    return max(rows_by_threshold, key=lambda threshold: (
        summarize(rows_by_threshold[threshold])["answerability_balanced_accuracy"],
        summarize(rows_by_threshold[threshold])["acceptance_rate"], -threshold))


def paired_group_interval(left, right, *, seed=20261022, samples=4000):
    """Descriptive bootstrap of whole conversations, not question bootstrap."""
    if type(samples) is not int or not 1 <= samples <= 10000:
        raise ValueError("bounded positive bootstrap samples required")
    if len(left) != len(right):
        raise ValueError("paired question census differs")
    # Denominator parity alone is insufficient: a mismatched source family or
    # gold annotation would silently contaminate the conversation bootstrap.
    immutable = ("query_id", "group", "category", "annotation_status",
                 "evidence_has_image", "gold_evidence_count", "unresolved_evidence")
    seen_ids = set()
    for a, b in zip(left, right):
        if any(a[key] != b[key] for key in immutable):
            raise ValueError("paired evidence/source identity differs")
        qid = a["query_id"]
        if type(qid) is not str or qid in seen_ids:
            raise ValueError("invalid or duplicate paired query identity")
        seen_ids.add(qid)
        if (a["support_recall"] is None) != (b["support_recall"] is None):
            raise ValueError("paired score denominator differs")
    grouped = defaultdict(list)
    for a, b in zip(left, right):
        if a["support_recall"] is not None:
            grouped[a["group"]].append(a["all_support_recalled"] - b["all_support_recalled"])
    means = [mean(values) for _, values in sorted(grouped.items())]
    if not means:
        return {"groups": 0, "interval": None}
    rng = random.Random(seed)
    draws = sorted(mean(rng.choices(means, k=len(means))) for _ in range(samples))
    return {"groups": len(means), "group_macro_difference": mean(means),
            "percentile_95_interval": [draws[math.floor(samples * 0.025)],
                                       draws[math.ceil(samples * 0.975) - 1]],
            "resamples": samples, "multiple_comparison_adjusted": False,
            "population_independence_authenticated": False,
            "low_power": True, "superiority_established": False}
