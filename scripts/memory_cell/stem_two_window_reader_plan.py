"""Label-blind SECOND window for a fixed frozen-Reader capacity ablation.

No new retrieval, Encoder tuning, learned Head, test label or source mutation.
Keep original frozen top-1 E1 byte-identical; choose the highest frozen-scored
different-session/root E2 from the *same exact candidate pool*. Research only.
"""

import math

from native import digest
from selector_answering import selected_window, choose


def prepare_second_window(
    query, pool, features, original_selected, original_sources, session_by_source_id,
):
    """Never use published answers or source labels to select E2."""
    pool.revalidate(query, set())
    if (
        features.question_id != query.identity
        or features.pool_digest != pool.seal()
        or features.candidate_ids != tuple(w.identity() for w in pool.windows)
        or features.roots != frozenset(s["root"] for s in pool.inspected)
        or not isinstance(original_sources, list)
        or len(original_sources) != 1
        or not isinstance(session_by_source_id, dict)
        or not {w.source_id for w in pool.windows}.issubset(session_by_source_id)
        or any(
            not isinstance(session_by_source_id[w.source_id], str)
            or not session_by_source_id[w.source_id]
            for w in pool.windows
        )
        or type(original_selected) is not int
        or not 0 <= original_selected < len(pool.windows)
    ):
        raise ValueError("original strict frozen question/source binding")
    scores = features.frozen_scores.tolist()
    if len(scores) != len(pool.windows) or any(
        type(v) not in (int, float) or not math.isfinite(v) for v in scores
    ):
        raise ValueError("invalid pinned frozen pair-Encoder logits")
    selected = choose(scores + [0.0], features.candidate_ids, allow_null=False)
    if selected != original_selected:
        raise ValueError("frozen ranker top-1 differs from original archived policy")
    first = selected_window(query, pool, features, selected, set())
    if list(first) != original_sources:
        raise ValueError("original frozen Reader E1 excerpt/offset changed")
    reference = pool.windows[selected]
    first_session = session_by_source_id[reference.source_id]
    alternatives = [
        i for i, w in enumerate(pool.windows)
        if i != selected and w.root != reference.root
        and w.source_id != reference.source_id
        and session_by_source_id[w.source_id] != first_session
    ]
    alternatives.sort(key=lambda i: (-scores[i], features.candidate_ids[i]))
    second_index = alternatives[0] if alternatives else None
    row = dict(
        schema="hepta.stem-frozen-top2-different-source.preregistered.v1",
        question_id=query.identity,
        question_sha256=digest((query.identity, query.content, query.observed_at)),
        candidate_pool_sha256=pool.seal(),
        encoder_identity=features.encoder_identity,
        candidate_ids_digest=digest(features.candidate_ids),
        original_top1_index=selected,
        selected_original_source_id=reference.source_id,
        selected_original_session_sha256=digest(first_session),
        selection_requires_distinct_native_sessions=True,
        different_source_candidates=len(alternatives),
        second_index=second_index,
        second_selection_uses_gold=False,
        frozen_score_top2_no_train_fit=True,
        both_windows_same_original_time_cut=True,
        decoded_answer_model_unchanged=True,
        original_reader_answers_rewritten=False,
        source_sufficiency_independently_reviewed=False,
        production_accepted=False,
    )
    if second_index is None:
        row["status"] = "unavailable"
        row["reason"] = "no-distinct-native-session-in-original-pool"
        return first, (), row
    second = selected_window(query, pool, features, second_index, set())
    second = (dict(second[0], label="E2"),)
    if (
        second[0]["root"] == first[0]["root"]
        or second[0]["original_id"] == first[0]["original_id"]
        or second[0]["scope"] != query.scope
        or second[0]["label"] != "E2"
    ):
        raise ValueError("second Reader passage is not source-distinct and bound")
    row["status"] = "prepared"
    row["second_source_id"] = second[0]["original_id"]
    row["second_session_sha256"] = digest(
        session_by_source_id[pool.windows[second_index].source_id]
    )
    row["second_window_sha256"] = digest(second)
    return first, first + second, row


def compare_capacity_rows(original, repeated, extended, *, diagnose, targets):
    """Score after both NEW Reader outcome journals were fully persisted."""
    if not callable(diagnose) or len(repeated) != 16 or len(extended) != 16:
        raise ValueError("exact original test/transfer sixteen-question census required")
    phases = ("test", "transfer")
    pairs = {}
    for src, tag in ((repeated, "same-host-one"), (extended, "two")):
        for row in src:
            key = row["phase"], row["question_id"]
            if row["phase"] not in phases or (key, tag) in pairs:
                raise ValueError("unregistered or duplicated Reader comparator")
            pairs[key, tag] = row
    expected = {
        (phase, x["question_id"]) for phase in phases for x in original
        if x["phase"] == phase
    }
    if len(expected) != 16 or set(targets) != {qid for _, qid in expected}:
        raise ValueError("incomplete published original test/transfer target census")
    if set(pairs) != {(key, tag) for key in expected for tag in ("same-host-one", "two")}:
        raise ValueError("incomplete new Reader control source census")
    result = {}
    for phase in phases:
        sums = []
        actual = 0
        all_rows = []
        for key in sorted(k for k in expected if k[0] == phase):
            one, two = pairs[key, "same-host-one"], pairs[key, "two"]
            eligible = two["status"] != "unavailable"
            comparable = one["status"] == two["status"] == "succeeded"
            diff = None
            if comparable:
                if (
                    one["reader_identity"] != two["reader_identity"]
                    or one["reader_profile"] != two["reader_profile"]
                    or one["original_E1"] != two["original_E1"]
                    or one["reader_prompt_budget"] != two["reader_prompt_budget"]
                    or len(one["delivered_sources"]) != 1
                    or len(two["delivered_sources"]) != 2
                    or one["delivered_sources"][0] != two["delivered_sources"][0]
                ):
                    raise ValueError("not identical frozen Reader/E1/matched budget")
                x = diagnose(one["answer"], targets[key[1]])
                y = diagnose(two["answer"], targets[key[1]])
                if x is not None and y is not None:
                    if any(type(v) not in (int, float) or not math.isfinite(v)
                           or not 0 <= v <= 1 for v in (x, y)):
                        raise ValueError("invalid original native diagnostic target F1")
                    diff = y - x
                    sums.append(diff)
                    actual += 1
            all_rows.append(dict(
                question_id=key[1], eligible_second_source=eligible,
                both_same_host_reader_calls_succeeded=comparable,
                observed_f1_delta_two_minus_one=diff,
                source_window_entailment_not_judged=True,
            ))
        n = len(all_rows)
        if n != 8:
            raise ValueError("changed original phase census")
        from math import fsum
        subtotal = fsum(sums)
        result[phase] = dict(
            attempted=n, reader_comparable_scored_pairs=actual,
            unscored_or_failed_pairs=n-actual,
            second_window_unavailable=sum(not x["eligible_second_source"] for x in all_rows),
            conditional_f1_delta_mean=subtotal/actual if actual else None,
            all_planned_f1_delta_bounds=[
                (subtotal-(n-actual))/n, (subtotal+(n-actual))/n,
            ],
            rows=all_rows,
            independently_certified_source_sufficiency=False,
        )
    return dict(
        schema="hepta.stem-top2-reader-capacity.v1",
        original_registered_questions=16,
        external_model_execution_must_be_proved_by_runner_receipts=True,
        pure_accounting_function_does_not_authenticate_model_execution=True,
        actual_source_count_only_ablation=True,
        same_host_and_frozen_weights_prompt_required=True,
        change_in_input_token_cost_must_be_reported=True,
        no_original_six_arm_mutation=True,
        semantic_citation_precision=None,
        production_accepted=False,
        by_phase=result,
    )
