"""Independent source-first QUERY-level typed MemoryCell retrieval evaluation.

Consumes previously sealed original trained-Head predictions, original frozen
source shortlist and separately held publisher-weak support. Never trains,
selects, invokes Reader, claims human entailment or promotes a model. Every
original question (including no-support/no-hit) remains in the denominator.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
from math import isfinite

PROFILE = "hepta.amcn.typed-question-weak-support.shadow.v1"
SOURCE_FIRST = "hepta.amcn.source-first-candidates.v1"
PUBLIC = "hepta.amcn.actual-archived-encoder-evidence.v1.public.v2"
WITHHELD = "hepta.amcn.actual-archived-encoder-evidence.v1.withheld.v2"
TRAIN_PROFILE = "hepta.amcn.typed-equal-budget.shadow.v1"
ARMS = ("lexical_top1", "frozen", "single_shared", "untyped_equal_budget",
        "typed_equal_budget", "typed_swapped_negative")
HELDOUT = ("select", "future_a", "future_b", "retention")
MAX_QUESTIONS = 4096
MAX_ROWS = 65536


class Refused(ValueError):
    """Invalid experiment input: no partial or success-shaped result."""


def require(value, error):
    if not value:
        raise Refused(error)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return sha256(canonical(value)).hexdigest()


def is_sha(value):
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def _row_input_digest(row, scope):
    """Reproduce original amcn_native.build_inputs / Case.input_digest bytes."""
    ev = row["evidence"]
    require(isinstance(ev, dict) and set(ev) == {
        "evidence_id", "source_root", "scope", "revision", "text",
        "content_sha256", "generation", "revoked"}, "source envelope")
    require(isinstance(ev["text"], str) and ev["text"]
            and sha256(ev["text"].encode("utf-8")).hexdigest() == ev["content_sha256"]
            and type(ev["revision"]) is int and ev["revision"] >= 1
            and ev["revoked"] is False and ev["scope"] == scope,
            "source bytes/revision/scope invalid")
    require(all(isinstance(ev[k], str) and ev[k] for k in
                ("evidence_id", "source_root", "generation")), "source identity")
    full = {"question": row["question"], "source_id": ev["evidence_id"],
            "source_revision": ev["revision"],
            "source_content_sha256": ev["content_sha256"], "evidence": ev["text"]}
    # amcn_core.canonical uses no newline for the source-first input string.
    text = canonical(full).decode("utf-8")
    # experiments.shared_stem_cell.execution.Case.input_digest uses a newline.
    return sha256(canonical([scope, text]) + b"\n").hexdigest()


def score_query_support(public, withheld, predictions, train_receipt, type_by_row, *,
                        expected_public_sha256, expected_withheld_sha256,
                        expected_predictions_sha256, expected_type_sha256):
    """Score original source-first query recall from ORIGINAL prediction bytes.

    External digests provide exact byte identity, not independently authenticated
    issuer trust. Call only AFTER prediction publication and label separation.
    """
    require(all(is_sha(x) for x in (expected_public_sha256,
            expected_withheld_sha256, expected_predictions_sha256,
            expected_type_sha256)), "missing original precommitted material pins")
    require(isinstance(public, dict) and digest(public) == expected_public_sha256
            and public.get("schema") == PUBLIC, "original source-first public input drift")
    require(isinstance(withheld, dict) and digest(withheld) == expected_withheld_sha256
            and set(withheld) == {"schema", "row_labels", "publisher_support",
                                  "source_first_plan_sha256"}
            and withheld["schema"] == WITHHELD, "untrusted withheld material")
    require(isinstance(train_receipt, dict)
            and train_receipt.get("production_accepted") is False,
            "original candidate is not nonauthorizing")
    metrics = train_receipt.get("metrics")
    require(isinstance(metrics, dict) and metrics.get("profile") == TRAIN_PROFILE
            and metrics.get("prediction_sha256") == expected_predictions_sha256
            and metrics.get("precommitted_type_inventory_sha256") == expected_type_sha256,
            "training receipt / prediction / type binding drift")
    require(isinstance(predictions, list) and digest(predictions) == expected_predictions_sha256,
            "original physical predictions changed after training")
    rows = public.get("rows")
    plans = public.get("source_first_shortlists")
    scope, generation = public.get("scope"), public.get("generation")
    require(isinstance(scope, str) and scope and isinstance(generation, str)
            and generation and isinstance(rows, list) and 1 <= len(rows) <= MAX_ROWS
            and isinstance(plans, dict) and 1 <= len(plans) <= MAX_QUESTIONS,
            "unbounded or missing source-first input")
    require(digest(plans) == withheld["source_first_plan_sha256"],
            "heldout support is not bound to the original plans")
    require(isinstance(type_by_row, dict)
            and set(type_by_row) == {r.get("row_id") for r in rows},
            "missing or extraneous predeclared Cell types")
    types = sorted(set(type_by_row.values()))
    require(len(types) == 2 and all(type(t) is str for t in types),
            "two predeclared functional memory types required")
    computed_type = digest({"profile": TRAIN_PROFILE,
        "features": metrics.get("frozen_feature_sha256"),
        "types": [(r["row_id"], type_by_row[r["row_id"]]) for r in rows]})
    require(computed_type == expected_type_sha256,
            "memory types changed since frozen physical feature training")
    require(isinstance(withheld["row_labels"], dict)
            and isinstance(withheld["publisher_support"], dict),
            "invalid withheld label schema")

    groups, indexed_rows = defaultdict(list), {}
    for row in rows:
        require(isinstance(row, dict) and set(row) == {
            "row_id", "question_id", "question", "family", "split", "evidence"},
            "public row schema")
        rid, split = row["row_id"], row["split"]
        # Validate TRAIN source bytes too; a mutated training source must not
        # become invisible merely because the scorer predicts HELDOUT rows.
        require(isinstance(row["evidence"], dict), "invalid source envelope")
        _row_input_digest(row, scope)
        require(isinstance(rid, str) and rid and rid not in indexed_rows
                and isinstance(row["question_id"], str) and row["question_id"]
                and isinstance(row["question"], str) and row["question"]
                and isinstance(row["family"], str) and row["family"]
                and split in ("train", *HELDOUT)
                and row["evidence"]["generation"] == generation,
                "stale, foreign or duplicate original question/source")
        indexed_rows[rid] = row
        if split != "train":
            groups[row["question_id"]].append(row)
    require(set(groups) == set(plans) == set(withheld["publisher_support"]),
            "missing zero-hit question or added lookahead query")
    heldout_rows = {rid for rid, r in indexed_rows.items() if r["split"] != "train"}
    require(set(withheld["row_labels"]) == heldout_rows and
            len(predictions) == len(heldout_rows),
            "hidden label/prediction census excludes original failures")

    seen, predicted = set(), {}
    for row in predictions:
        require(isinstance(row, dict) and set(row) == {
            "row_id", "family", "split", "input_sha256", "memory_type", "probabilities"},
            "unexpected model prediction schema")
        rid = row["row_id"]
        origin = indexed_rows.get(rid)
        require(origin is not None and rid in heldout_rows and rid not in seen,
                "unknown, TRAIN, or duplicate original prediction")
        seen.add(rid)
        require((row["family"], row["split"], row["memory_type"],
                 row["input_sha256"]) ==
                (origin["family"], origin["split"], type_by_row[rid],
                 _row_input_digest(origin, scope)),
                "physical candidate/source/type/input identity mismatch")
        probs = row["probabilities"]
        require(isinstance(probs, dict) and set(probs) == set(ARMS) - {"lexical_top1"}
                and all(type(p) in (float, int) and isfinite(p) and 0 <= p <= 1
                        for p in probs.values()), "missing, forged or nonfinite Head output")
        predicted[rid] = probs
    require(seen == heldout_rows, "missing original predicted candidate")

    score_rows = []
    for qid, candidates in sorted(groups.items()):
        question, split, family = (candidates[0][k] for k in
                                    ("question", "split", "family"))
        kind = type_by_row[candidates[0]["row_id"]]
        require(all((r["question"], r["split"], r["family"],
                     type_by_row[r["row_id"]]) == (question, split, family, kind)
                    for r in candidates), "question candidates mix families/splits/types")
        plan = plans[qid]
        require(isinstance(plan, dict) and plan.get("schema") == SOURCE_FIRST
                and plan.get("source_scope") == scope
                and plan.get("source_generation") == generation
                and plan.get("labels_accessed") is False
                and plan.get("independent_semantic_support_verified") is False
                and plan.get("question_sha256") == digest(question),
                "original source-first plan spoofed")
        sources = plan.get("ranked_source_ids")
        scores = plan.get("ranked_scores")
        require(isinstance(sources, list) and 1 <= len(sources) <= 16
                and isinstance(scores, list) and len(sources) == len(scores)
                and type(plan.get("shortlist_size")) is int
                and plan["shortlist_size"] == len(sources)
                and len(set(sources)) == len(sources)
                and all(type(s) is str and s for s in sources)
                and all(type(s) in (int, float) and isfinite(s) and s >= 0
                        for s in scores)
                and all(scores[i] >= scores[i+1] for i in range(len(scores)-1)),
                "original lexical shortlist invalid")
        by_src = {}
        for row in candidates:
            sid = row["evidence"]["evidence_id"]
            require(sid not in by_src, "duplicated candidate source in one question")
            by_src[sid] = row
        require(list(by_src) == sources,
                "source-first candidate order/coverage edited after sealing")
        gold = withheld["publisher_support"][qid]
        require(isinstance(gold, list) and len(gold) <= 8192
                and all(type(s) is str and s for s in gold)
                and len(gold) == len(set(gold)), "invalid publisher support inventory")
        supported = set(gold)
        for row in candidates:
            rid, sid = row["row_id"], row["evidence"]["evidence_id"]
            weak = withheld["row_labels"][rid]
            require(type(weak) is int and weak == int(sid in supported),
                    "weak label contradicts original publisher support")
        hits = {arm: None for arm in ARMS}
        for arm in ARMS:
            ranked = sources if arm == "lexical_top1" else sorted(sources,
                key=lambda sid: (-predicted[by_src[sid]["row_id"]][arm],
                                 sources.index(sid)))
            hit_positions = [j+1 for j, sid in enumerate(ranked) if sid in supported]
            hits[arm] = {"hit1": int(bool(hit_positions and hit_positions[0] == 1)),
                         "mrr": (1.0 / hit_positions[0] if hit_positions else 0.0),
                         "hitk": int(bool(hit_positions))}
        score_rows.append({"question_sha256": digest(qid), "family": family,
            "split": split, "memory_type": kind, "weak_support_count": len(supported),
            "weak_support_in_shortlist": sum(s in supported for s in sources),
            "measures": hits})

    summaries = []
    for split in HELDOUT:
        for kind in types:
            chosen = [x for x in score_rows if x["split"] == split
                      and x["memory_type"] == kind]
            if not chosen:
                continue
            for arm in ARMS:
                summaries.append({"split": split, "memory_type": kind,
                    "arm": arm, "questions": len(chosen),
                    "top1_hits": sum(x["measures"][arm]["hit1"] for x in chosen),
                    "topk_hits": sum(x["measures"][arm]["hitk"] for x in chosen),
                    "mrr_at_k": sum(x["measures"][arm]["mrr"] for x in chosen) / len(chosen),
                    "no_shortlist_support": sum(x["weak_support_in_shortlist"] == 0
                                                for x in chosen)})
    family_means = defaultdict(list)
    for row in score_rows:
        if row["split"] in ("future_a", "future_b"):
            family_means[(row["split"], row["family"])].append(
                row["measures"]["typed_equal_budget"]["hit1"] -
                row["measures"]["untyped_equal_budget"]["hit1"])
    ledger = {"win": 0, "loss": 0, "tie": 0}
    for values in family_means.values():
        mean = sum(values) / len(values)
        ledger["win" if mean > 0 else "loss" if mean < 0 else "tie"] += 1
    return {"schema": PROFILE, "production_accepted": False,
        "source_provenance": "publisher-weak annotations, not human entailment",
        "independent_issuer_verified": False, "true_future_calendar_windows": 0,
        "natural_reader_answers": 0, "strong_hybrid_rag_evaluated": False,
        "physical_weights_verified_by_scorer": False,
        "public_sha256": expected_public_sha256,
        "withheld_sha256": expected_withheld_sha256,
        "predictions_sha256": expected_predictions_sha256,
        "memory_type_inventory_sha256": expected_type_sha256,
        "total_heldout_queries": len(score_rows),
        "total_heldout_candidates": len(heldout_rows),
        "zero_support_or_zero_shortlist_questions": sum(
            row["weak_support_in_shortlist"] == 0 for row in score_rows),
        "future_source_family_count_upper_bound": len(family_means),
        "future_typed_minus_untyped_family_wins": ledger,
        "by_split_type_arm": summaries}
