"""Original-question retrieval scoring for typed MemoryCell SHADOW experiments.

Read-only, no model invocation. All candidate predictions, source-first plans,
and question outcomes are supplied under three explicit independent byte pins.
Scores publisher-weak evidence coverage, NOT Reader completion or entailment.
"""
from __future__ import annotations

from collections import defaultdict
from math import isfinite

from amcn_core import digest, is_sha, require, shadow_disposition

PROFILE = "hepta.amcn.typed-question-recall.shadow.v1"
ARMS = ("lexical_top1", "frozen", "single_shared", "untyped_equal_budget",
        "typed_equal_budget", "typed_swapped_negative")
PREDICTED = frozenset(ARMS) - {"lexical_top1"}
SPLITS = ("select", "future_a", "future_b", "retention")
MAX_CANDIDATES = 65536
MAX_QUESTIONS = 4096
MAX_K = 16


def score_question_recall(plan, predictions, publisher_support, *,
                          expected_plan_sha256, expected_predictions_sha256,
                          expected_support_sha256):
    """Open publisher weak-support only after original question/ranking is pinned.

    Plan is a label-blind array of whole original questions, each with a
    source-first top-K of exact original source revisions. Each candidate has
    one physically produced probability per model arm. Pinned hashes certify
    byte identity only; external issuer and training lineage are not proven.
    """
    require(all(is_sha(x) for x in (expected_plan_sha256,
            expected_predictions_sha256, expected_support_sha256)),
            "complete out-of-band exact byte pins required")
    require(isinstance(plan, dict) and set(plan) == {"schema", "questions"}
            and plan["schema"] == PROFILE + ".plan"
            and digest(plan) == expected_plan_sha256,
            "original source-first question plan changed")
    questions = plan["questions"]
    require(isinstance(questions, list) and
            1 <= len(questions) <= MAX_QUESTIONS,
            "empty/oversized source-first question census")
    require(isinstance(predictions, list) and
            1 <= len(predictions) <= MAX_CANDIDATES and
            digest(predictions) == expected_predictions_sha256,
            "original model prediction census changed")
    require(isinstance(publisher_support, dict) and
            digest(publisher_support) == expected_support_sha256,
            "independent publisher-weak labels changed")
    by_prediction = {}
    for prediction in predictions:
        require(isinstance(prediction, dict) and set(prediction) == {
            "row_id", "family", "split", "input_sha256", "memory_type",
            "probabilities"}, "unexpected original physical prediction fields")
        row_id, probs = prediction["row_id"], prediction["probabilities"]
        require(isinstance(row_id, str) and row_id and row_id not in by_prediction
                and is_sha(prediction["input_sha256"])
                and isinstance(probs, dict) and set(probs) == PREDICTED
                and all(type(p) in (int, float) and isfinite(p) and 0 <= p <= 1
                        for p in probs.values()), "duplicate/corrupt original inference")
        by_prediction[row_id] = prediction
    seen_queries, seen_candidates, summaries = set(), set(), []
    for question in questions:
        require(isinstance(question, dict) and set(question) == {
            "question_id", "family", "split", "memory_type",
            "scope", "generation", "candidate_rows", "label_blind"},
            "unknown source-first plan fields")
        qid, family, split, kind = (question[k] for k in
                                    ("question_id", "family", "split", "memory_type"))
        require(all(isinstance(x, str) and x for x in
                    (qid, family, split, kind, question["scope"], question["generation"]))
                and split in SPLITS and qid not in seen_queries
                and question["label_blind"] is True,
                "duplicate/invalid/unsealed question identity")
        seen_queries.add(qid)
        candidates = question["candidate_rows"]
        require(isinstance(candidates, list) and 1 <= len(candidates) <= MAX_K,
                "missing/bloated source-first shortlist")
        source_ids, selected, support = set(), [], publisher_support.get(qid)
        require(isinstance(support, list) and len(support) <= 8192
                and all(isinstance(s, str) and s for s in support)
                and len(support) == len(set(support)),
                "missing or invalid original publisher support question")
        for cand in candidates:
            require(isinstance(cand, dict) and set(cand) == {
                "row_id", "source_id", "source_sha256", "source_revision",
                "input_sha256"}, "invalid source-first candidate identity")
            rid, sid = cand["row_id"], cand["source_id"]
            require(isinstance(rid, str) and rid and rid not in seen_candidates
                    and isinstance(sid, str) and sid and sid not in source_ids
                    and is_sha(cand["source_sha256"])
                    and is_sha(cand["input_sha256"])
                    and type(cand["source_revision"]) is int
                    and cand["source_revision"] >= 1,
                    "duplicate/revised/unsigned candidate content")
            seen_candidates.add(rid)
            source_ids.add(sid)
            original = by_prediction.get(rid)
            require(original is not None and
                    (original["family"], original["split"],
                     original["memory_type"], original["input_sha256"]) ==
                    (family, split, kind, cand["input_sha256"]),
                    "source/type/family/model request drift")
            selected.append((sid, original["probabilities"]))
        supported = set(support)
        measures = {}
        for arm in ARMS:
            ranked = selected if arm == "lexical_top1" else sorted(
                selected, key=lambda rec: (-rec[1][arm],
                                            next(i for i, item in enumerate(selected)
                                                 if item[0] == rec[0])))
            hits = [i + 1 for i, (sid, _) in enumerate(ranked) if sid in supported]
            measures[arm] = {"hit1": int(bool(hits and hits[0] == 1)),
                             "hitk": int(bool(hits)),
                             "mrr": 1.0 / hits[0] if hits else 0.0}
        summaries.append({"question_id_sha256": digest(qid), "family": family,
                          "split": split, "memory_type": kind,
                          "support_in_shortlist": sum(s in supported for s, _ in selected),
                          "weak_support_count": len(supported),
                          "measures": measures})
    require(set(publisher_support) == seen_queries and
            seen_candidates == set(by_prediction),
            "unpaired query, hidden zero-hit, or omitted prediction")
    require({"future_a", "future_b"} <= {r["split"] for r in summaries},
            "both diagnostic future partitions required")
    require(len({(q["scope"], q["generation"]) for q in questions}) == 1,
            "mixed scope/epoch cannot be one physical trial")
    groups = defaultdict(list)
    for row in summaries:
        groups[(row["split"], row["memory_type"])].append(row)
    totals = []
    for (split, kind), rows in sorted(groups.items()):
        for arm in ARMS:
            totals.append({"split": split, "memory_type": kind, "arm": arm,
                           "questions": len(rows),
                           "hit1": sum(r["measures"][arm]["hit1"] for r in rows),
                           "hitk": sum(r["measures"][arm]["hitk"] for r in rows),
                           "mrr_at_k": sum(r["measures"][arm]["mrr"]
                                       for r in rows) / len(rows),
                           "no_support_shortlist": sum(r["support_in_shortlist"] == 0
                                                       for r in rows)})
    family_deltas = defaultdict(list)
    for row in summaries:
        if row["split"] in ("future_a", "future_b"):
            family_deltas[(row["split"], row["family"])].append(
                row["measures"]["typed_equal_budget"]["hit1"] -
                row["measures"]["untyped_equal_budget"]["hit1"])
    wins = {"win": 0, "loss": 0, "tie": 0}
    for values in family_deltas.values():
        mean = sum(values) / len(values)
        wins["win" if mean > 0 else "loss" if mean < 0 else "tie"] += 1
    return shadow_disposition(
        profile=PROFILE, plan_sha256=expected_plan_sha256,
        original_predictions_sha256=expected_predictions_sha256,
        publisher_support_sha256=expected_support_sha256,
        complete_question_count=len(questions),
        complete_candidate_count=len(seen_candidates),
        zero_support_or_zero_hit_questions=sum(r["support_in_shortlist"] == 0
                                           for r in summaries),
        future_family_pairs=len(family_deltas),
        family_wins=wins, source_first_weak_support=totals,
        original_reader_answers=None, strong_hybrid_rag_comparison=None,
        pretrained_feature_origin_independently_authenticated=False,
        independent_future_calendar_windows=0,
        publisher_annotations_independent_entailment=False,
        physical_head_bank_independently_replayed=False,
        source_owner_and_external_issuers_verified=False)
