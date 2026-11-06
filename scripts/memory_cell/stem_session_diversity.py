"""Label-blind session diversification of a frozen native source ranking.

Provenance roots remain authoritative for withdrawal and family accounting;
only Document.session groups candidate diversity. This does not certify
semantic entailment or improve a Reader without a separately matched run.
"""

from collections import defaultdict

from sessions import source_id
from stem_audit_archive import require
from stem_frozen_retrieval_grid import BASELINE, PHASES, annotate, label_key


def session_distinct(ranked, limit):
    """Stable first-per-session, followed by remaining original ranked rows."""
    require(
        type(limit) is int
        and 1 <= limit <= 8
        and isinstance(ranked, list)
        and limit <= len(ranked) <= 64
        and all(
            isinstance(row, dict)
            and set(row) == {"id", "root", "session"}
            and all(
                isinstance(row[key], str) and bool(row[key])
                for key in ("id", "root", "session")
            )
            for row in ranked
        )
        and len({row["id"] for row in ranked}) == len(ranked),
        "bounded original source IDs, withdrawal roots and sessions required",
    )
    chosen, rest, seen = [], [], set()
    for row in ranked:
        if row["session"] in seen:
            rest.append(row["id"])
        else:
            seen.add(row["session"])
            chosen.append(row["id"])
    return (chosen + rest)[:limit]


def validate_session_receipts(plan, originals, receipts):
    """Require an unchanged top-K, original index and pre-answer source census."""
    expected = {
        (phase, question) for phase in PHASES for question in plan["questions"][phase]
    }
    require(
        isinstance(receipts, list) and len(receipts) == len(expected) == 80,
        "complete original 80-question session census required",
    )
    observed = {}
    for item in receipts:
        key = (item["phase"], item["question_id"])
        require(
            key in expected and key not in observed,
            "unknown or duplicated source/session question",
        )
        before = originals[(key[0], key[1], label_key(BASELINE))]
        ranked = item["ranked_original_source_sessions"]
        topk = before["retrieved_source_ids"]
        require(
            item["source_family"] == before["source_family"]
            and item["original_as_of_index_sha256"]
            == before["original_as_of_index_sha256"]
            and item["original_baseline_source_ids"] == topk
            and item["read_targets_for_retrieval"] is False
            and item["source_text_exported"] is False
            and item["pretrained_reader_calls"] == 0
            and isinstance(ranked, list)
            and len(ranked) >= len(topk)
            and [source_id(v["id"]) for v in ranked[: len(topk)]] == topk,
            "original candidate ranking, cutoff, family or admission changed",
        )
        chosen = session_distinct(ranked, len(topk))
        selected = [source_id(identity) for identity in chosen]
        windows = item["window_source_ids"]
        require(
            item["selected_original_identities"] == chosen
            and item["retrieved_source_ids"] == selected
            and len(set(selected)) == len(selected)
            and isinstance(windows, list)
            and len(set(windows)) == len(windows)
            and set(windows).issubset(selected)
            and isinstance(item["pool_sha256"], str)
            and len(item["pool_sha256"]) == 64,
            "session choice or original-window provenance differs",
        )
        observed[key] = item
    require(set(observed) == expected, "incomplete session ablation census")
    return observed


def compare_session_diversity(plan, originals, receipts, targets):
    """Score ONLY after all candidates are frozen; source labels are weak."""
    wanted = {q for phase in PHASES for q in plan["questions"][phase]}
    require(
        set(targets) == wanted
        and set(receipts)
        == {(phase, q) for phase in PHASES for q in plan["questions"][phase]},
        "complete, separately admitted post-generation target census required",
    )
    totals, decisions = {}, []
    for phase in PHASES:
        counts = defaultdict(int)
        for question in plan["questions"][phase]:
            before = originals[(phase, question, label_key(BASELINE))]
            after = receipts[(phase, question)]
            original = annotate(before, targets[question])
            candidate = annotate(after, targets[question])
            require(
                (original is None) == (candidate is None),
                "original task scorability changed",
            )
            ranked = after["ranked_original_source_sessions"]
            cutoff = len(before["retrieved_source_ids"])
            head = ranked[:cutoff]
            different = before["retrieved_source_ids"] != after["retrieved_source_ids"]
            counts["planned"] += 1
            counts["original_topk_duplicate_session_slots"] += len(head) - len(
                {row["session"] for row in head}
            )
            counts["distinct_sessions_available_at_depth"] += len(
                {row["session"] for row in ranked}
            )
            counts["changed_source_topk"] += int(different)
            if original is None:
                counts["unscored_native_label"] += 1
            else:
                counts["scored_native_label"] += 1
                counts["original_document_hits"] += int(original[0])
                counts["session_document_hits"] += int(candidate[0])
                counts["original_window_hits"] += int(original[1])
                counts["session_window_hits"] += int(candidate[1])
                counts["document_rescues"] += int(not original[0] and candidate[0])
                counts["document_regressions"] += int(original[0] and not candidate[0])
                counts["window_rescues"] += int(not original[1] and candidate[1])
                counts["window_regressions"] += int(original[1] and not candidate[1])
            decisions.append(
                dict(
                    phase=phase,
                    question_id=question,
                    source_family=before["source_family"],
                    changed_source_topk=different,
                    original_unique_topk_sessions=len({r["session"] for r in head}),
                    available_distinct_sessions=len({r["session"] for r in ranked}),
                    weak_original_document_hit=(
                        None if original is None else original[0]
                    ),
                    weak_session_document_hit=(
                        None if candidate is None else candidate[0]
                    ),
                    weak_original_window_hit=(
                        None if original is None else original[1]
                    ),
                    weak_session_window_hit=(
                        None if candidate is None else candidate[1]
                    ),
                )
            )
        totals[phase] = dict(counts)
    return dict(
        schema="hepta.stem-native-session-diversity.v1",
        original_frozen_rrf_top_k=8,
        original_source_order_verified=True,
        same_model_encoder_asof_index_budget=True,
        provenance_roots_unchanged=True,
        diversifies_document_session_not_withdrawal_root=True,
        actual_new_reader_calls=0,
        question_count=len(decisions),
        exploratory_development_after_prior_exposure=True,
        labels_not_used_in_source_ranking=True,
        native_document_membership_is_not_semantic_entailment=True,
        product_answer_gain_not_measured=True,
        independent_source_families_not_certified=True,
        semantic_citation_precision=None,
        production_accepted=False,
        results=totals,
        decisions=decisions,
    )
