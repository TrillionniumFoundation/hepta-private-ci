"""Source-root diversity ablation on a frozen, label-blind native retrieval pool.

This is NOT a new owner, a truth oracle, a trained selector, or production RAG.
The scorer consumes original native support annotations only after all candidate
identities have been persisted. Identical source roots are only one diversity
group; conflicting *different* roots are never silently collapsed.
"""

from collections import defaultdict

from sessions import source_id
from stem_audit_archive import require
from stem_frozen_retrieval_grid import PHASES, BASELINE, annotate, label_key


def root_distinct(ranked, limit):
    """Stable first-per-root, then stable duplicates to preserve the fixed K."""
    require(
        type(limit) is int
        and 1 <= limit <= 8
        and isinstance(ranked, list)
        and 1 <= len(ranked) <= 64
        and len({r["id"] for r in ranked}) == len(ranked)
        and all(
            isinstance(r, dict)
            and set(r) == {"id", "root"}
            and isinstance(r["id"], str)
            and bool(r["id"])
            and isinstance(r["root"], str)
            and bool(r["root"])
            for r in ranked
        ),
        "bounded original indexed source/root ranking required",
    )
    chosen, extras, roots = [], [], set()
    for row in ranked:
        if row["root"] in roots:
            extras.append(row["id"])
        else:
            roots.add(row["root"])
            chosen.append(row["id"])
    return (chosen + extras)[: min(limit, len(ranked))]


def validate_diverse_receipts(plan, original, receipts):
    """Reconstruct every source choice without labels, prompts, or model calls."""
    expected = {(phase, qid) for phase in PHASES for qid in plan["questions"][phase]}
    if len(receipts) != len(expected):
        raise ValueError("missing or duplicated distinct-root candidate census")
    observed = {}
    for row in receipts:
        key = (row["phase"], row["question_id"])
        if key not in expected or key in observed:
            raise ValueError("unregistered duplicate root-diverse candidate")
        baseline = original[(key[0], key[1], label_key(BASELINE))]
        ranked = row["ranked_original_source_roots"]
        if (
            row["source_family"] != baseline["source_family"]
            or row["original_as_of_index_sha256"]
            != baseline["original_as_of_index_sha256"]
            or row["original_baseline_source_ids"] != baseline["retrieved_source_ids"]
            or row["source_text_exported"] is not False
            or row["read_targets_for_retrieval"] is not False
            or row["pretrained_reader_calls"] != 0
            or not isinstance(ranked, list)
        ):
            raise ValueError("root-diverse sources changed the original input/cut")
        first_k = len(baseline["retrieved_source_ids"])
        if (
            len(ranked) < first_k
            or [source_id(v["id"]) for v in ranked[:first_k]]
            != baseline["retrieved_source_ids"]
        ):
            raise ValueError("original top-K changed before root deduplication")
        chosen = root_distinct(ranked, first_k)
        source_ids = [source_id(v) for v in chosen]
        if (
            source_ids != row["retrieved_source_ids"]
            or row["selected_original_identities"] != chosen
            or not isinstance(row["window_source_ids"], list)
            or not set(row["window_source_ids"]).issubset(source_ids)
            or len(set(row["window_source_ids"])) != len(row["window_source_ids"])
            or not isinstance(row["pool_sha256"], str)
            or len(row["pool_sha256"]) != 64
        ):
            raise ValueError("unbound rank, window or root-diverse receipt")
        observed[key] = row
    if set(observed) != expected:
        raise ValueError("incomplete original frozen native root-diversity census")
    return observed


def compare_diversity(plan, original, diverse, targets):
    """Retrospective weak-document support only; no selection from test labels."""
    expected = {q for p in PHASES for q in plan["questions"][p]}
    if set(targets) != expected or set(diverse) != {
        (p, q) for p in PHASES for q in plan["questions"][p]
    }:
        raise ValueError("root-diverse scoring requires full original census")
    totals, decisions = {}, []
    for phase in PHASES:
        counts = defaultdict(int)
        for qid in plan["questions"][phase]:
            baseline = original[(phase, qid, label_key(BASELINE))]
            alternative = diverse[(phase, qid)]
            before, after = (
                annotate(baseline, targets[qid]),
                annotate(alternative, targets[qid]),
            )
            if (before is None) != (after is None):
                raise ValueError("original target resolution changed")
            ranked = alternative["ranked_original_source_roots"]
            first_roots = [
                r["root"] for r in ranked[: len(baseline["retrieved_source_ids"])]
            ]
            repeated = len(first_roots) - len(set(first_roots))
            changed = (
                baseline["retrieved_source_ids"] != alternative["retrieved_source_ids"]
            )
            counts["planned"] += 1
            counts["original_topk_repeat_root_slots"] += repeated
            counts["changed_source_topk"] += int(changed)
            if before is None:
                counts["unscored_native_label"] += 1
            else:
                counts["scored_native_label"] += 1
                counts["original_document_hits"] += int(before[0])
                counts["alternative_document_hits"] += int(after[0])
                counts["original_window_hits"] += int(before[1])
                counts["alternative_window_hits"] += int(after[1])
                counts["document_rescues"] += int(not before[0] and after[0])
                counts["document_regressions"] += int(before[0] and not after[0])
                counts["window_rescues"] += int(not before[1] and after[1])
                counts["window_regressions"] += int(before[1] and not after[1])
            decisions.append(
                dict(
                    question_id=qid,
                    phase=phase,
                    source_family=baseline["source_family"],
                    rank_changed=changed,
                    duplicated_original_topk_roots=repeated,
                    original_document_hit=None if before is None else before[0],
                    diverse_document_hit=None if after is None else after[0],
                    original_window_hit=None if before is None else before[1],
                    diverse_window_hit=None if after is None else after[1],
                    independent_semantic_entailment_verified=False,
                )
            )
        totals[phase] = dict(counts)
    return dict(
        schema="hepta.stem-frozen-root-diversity.v1",
        comparator="original frozen RRF top8",
        same_frozen_retriever_encoder=True,
        original_index_and_asof_unchanged=True,
        same_maximum_eight_delivered_sources=True,
        no_new_reader_calls=True,
        weak_native_support_only=True,
        exploratory_after_prior_census_exposure=True,
        training_and_test_not_used_to_choose_algorithm=True,
        statistical_superiority_established=False,
        independent_semantic_citation_precision=None,
        production_accepted=False,
        results=totals,
        decisions=decisions,
    )
