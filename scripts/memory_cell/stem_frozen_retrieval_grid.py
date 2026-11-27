"""Frozen native retriever RRF ablation. TRAIN-only grid selection, no Reader.

All candidate windows are generated label-blind on immutable strict-as-of
indexes with the ORIGINAL frozen MiniLM Encoder and original window budget.
The public native-document labels are consulted strictly after every candidate
receipt is retained. Labels are weak source support, not passage entailment.
"""

from collections import defaultdict
import math
import re

from native import digest
from sessions import source_id


PHASES = ("train", "select", "retention", "test", "transfer")
WEIGHTS = (0.0, 0.25, 0.5, 0.75, 1.0)
CHANNELS = (64, 128)
GRID = tuple((k, w) for k in CHANNELS for w in WEIGHTS)
BASELINE = (64, 0.5)


def label_key(policy):
    k, weight = policy
    if (
        type(k) is not int
        or k not in CHANNELS
        or type(weight) is not float
        or weight not in WEIGHTS
    ):
        raise ValueError("policy not in preregistered frozen retrieval grid")
    return f"k{k}/lex{weight:.2f}"


def validate_unlabelled(plan, records):
    cohorts = plan["questions"]
    if (
        set(cohorts) != set(PHASES)
        or len(cohorts["train"]) != 48
        or any(len(cohorts[p]) != 8 for p in PHASES[1:])
        or len({q for p in PHASES for q in cohorts[p]}) != 80
        or set(plan["question_families"]) != {q for p in PHASES for q in cohorts[p]}
        or plan["source_visibility_policy"]
        != "strict-as-of-before-index-and-every-Encoder-v1"
    ):
        raise ValueError("nonoriginal candidate plan or source admission")
    expected = {
        (p, q, label_key(config)) for p in PHASES for q in cohorts[p] for config in GRID
    }
    observed = {}
    for row in records:
        key = (row["phase"], row["question_id"], row["policy"])
        ids, windows = row["retrieved_source_ids"], row["window_source_ids"]
        if (
            key not in expected
            or key in observed
            or row["source_family"] != plan["question_families"][key[1]]
            or not isinstance(ids, list)
            or not 1 <= len(ids) <= 8
            or len(set(ids)) != len(ids)
            or not isinstance(windows, list)
            or len(set(windows)) != len(windows)
            or not set(windows).issubset(ids)
            or not isinstance(row["original_as_of_index_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", row["original_as_of_index_sha256"]) is None
            or not isinstance(row["pool_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", row["pool_sha256"]) is None
            or (
                row.get("replayed_original_pool_sha256") is not True
                if key[2] == label_key(BASELINE)
                else row.get("replayed_original_pool_sha256") is not None
            )
            or row.get("source_text_exported") is not False
            or row.get("read_targets_for_retrieval") is not False
        ):
            raise ValueError("unregistered, duplicated or unbound retrieval receipt")
        observed[key] = row
    if set(observed) != expected:
        raise ValueError("missing frozen retrieval/grid/question receipt")
    for phase in PHASES:
        for qid in cohorts[phase]:
            family = plan["question_families"][qid]
            original = observed[(phase, qid, label_key(BASELINE))]
            if original.get("replayed_original_pool_sha256") is not True:
                raise ValueError("original frozen pool identity not reproduced")
            pins = {
                (
                    observed[(phase, qid, label_key(config))][
                        "original_as_of_index_sha256"
                    ],
                    observed[(phase, qid, label_key(config))]["source_family"],
                )
                for config in GRID
            }
            if pins != {(original["original_as_of_index_sha256"], family)}:
                raise ValueError("retrieval weight sweep changed source/index boundary")
    return observed


def annotate(record, target):
    if target.unanswerable or target.unresolved_evidence or not target.evidence:
        return None
    native_sources = {source_id(s) for s in target.evidence}
    retrieved = set(record["retrieved_source_ids"])
    windowed = set(record["window_source_ids"])
    return (
        bool(native_sources & retrieved),
        bool(native_sources & windowed),
    )


def select_from_train(plan, unlabelled, targets):
    """TRAIN ONLY; caller must never pass held-out targets to this function."""
    train_ids = plan["questions"]["train"]
    if not isinstance(targets, dict) or set(targets) != set(train_ids):
        raise ValueError("frozen retriever calibration requires TRAIN-only labels")
    bests = []
    for config in GRID:
        family = defaultdict(list)
        unscored = 0
        for qid in train_ids:
            item = unlabelled[("train", qid, label_key(config))]
            labels = annotate(item, targets[qid])
            if labels is None:
                unscored += 1
            else:
                family[item["source_family"]].append(float(labels[1]))
        if not family:
            raise ValueError("no admitted native-source TRAIN examples")
        macro = math.fsum(
            math.fsum(values) / len(values) for values in family.values()
        ) / len(family)
        bests.append(
            dict(
                id=label_key(config),
                channel_k=config[0],
                lexical_weight=config[1],
                family_macro_window_recall=macro,
                training_families=len(family),
                scored=sum(map(len, family.values())),
                unscored=unscored,
            )
        )
    selected = min(
        bests,
        key=lambda x: (
            -round(x["family_macro_window_recall"], 12),
            x["channel_k"],
            abs(x["lexical_weight"] - BASELINE[1]),
            x["lexical_weight"],
        ),
    )
    return dict(
        schema="hepta.stem-frozen-retrieval-train-grid.v1",
        train_question_count=48,
        eligible_policy_ids=[label_key(c) for c in GRID],
        selected_policy=selected["id"],
        selected_channel_k=selected["channel_k"],
        selected_lexical_weight=selected["lexical_weight"],
        baseline_policy=label_key(BASELINE),
        train_cohort_sha256=digest(train_ids),
        train_only=True,
        evaluation_labels_were_not_read_to_select=True,
        shadow_no_policy_reader_or_head_changes=True,
        evaluated_after_original_answers_persisted=True,
        no_independent_semantic_entailment=True,
        production_accepted=False,
        all_candidates=bests,
    )


def verify_train_selection(plan, selection):
    """Reject a rewritten winner/selection receipt before held-out labels enter.

    This checks the complete frozen 10-policy TRAIN scorecard. It cannot
    authenticate the native labels independently and is not a success gate.
    """
    expected = [label_key(policy) for policy in GRID]
    if (
        not isinstance(selection, dict)
        or selection.get("schema") != "hepta.stem-frozen-retrieval-train-grid.v1"
        or selection.get("train_only") is not True
        or selection.get("evaluation_labels_were_not_read_to_select") is not True
        or selection.get("production_accepted") is not False
        or selection.get("train_question_count") != 48
        or selection.get("train_cohort_sha256") != digest(plan["questions"]["train"])
        or selection.get("baseline_policy") != label_key(BASELINE)
        or selection.get("eligible_policy_ids") != expected
        or not isinstance(selection.get("all_candidates"), list)
        or len(selection["all_candidates"]) != len(GRID)
    ):
        raise ValueError("unbound or post-hoc retriever TRAIN policy selection")
    valid = []
    for (k, weight), entry in zip(GRID, selection["all_candidates"], strict=True):
        if (
            not isinstance(entry, dict)
            or entry.get("id") != label_key((k, weight))
            or entry.get("channel_k") != k
            or entry.get("lexical_weight") != weight
            or type(entry.get("training_families")) is not int
            or entry["training_families"] < 1
            or type(entry.get("scored")) is not int
            or type(entry.get("unscored")) is not int
            or entry["scored"] < 1
            or entry["unscored"] < 0
            or entry["scored"] + entry["unscored"] != 48
            or type(entry.get("family_macro_window_recall")) not in (float, int)
            or not math.isfinite(entry["family_macro_window_recall"])
            or not 0 <= entry["family_macro_window_recall"] <= 1
        ):
            raise ValueError("frozen TRAIN grid scorecard changed or nonfinite")
        valid.append(entry)
    chosen = min(
        valid,
        key=lambda x: (
            -round(x["family_macro_window_recall"], 12),
            x["channel_k"],
            abs(x["lexical_weight"] - BASELINE[1]),
            x["lexical_weight"],
        ),
    )
    if (
        selection.get("selected_policy") != chosen["id"]
        or selection.get("selected_channel_k") != chosen["channel_k"]
        or selection.get("selected_lexical_weight") != chosen["lexical_weight"]
    ):
        raise ValueError("TRAIN-only winner does not match recorded frozen scorecard")
    return chosen


def evaluate_fixed(plan, unlabelled, targets, selection):
    """Held-out labels only after the TRAIN-only choice is immutable."""
    verify_train_selection(plan, selection)
    eval_ids = [q for p in PHASES[1:] for q in plan["questions"][p]]
    if set(targets) != set(eval_ids) or len(eval_ids) != 32 or len(set(eval_ids)) != 32:
        raise ValueError("evaluation targets changed calibration selection")
    out, decisions = {}, []
    for phase in PHASES[1:]:
        counts = defaultdict(int)
        for qid in plan["questions"][phase]:
            a = unlabelled[(phase, qid, label_key(BASELINE))]
            b = unlabelled[(phase, qid, selection["selected_policy"])]
            if (
                a["source_family"] != b["source_family"]
                or a["source_family"] != plan["question_families"][qid]
                or a["original_as_of_index_sha256"] != b["original_as_of_index_sha256"]
            ):
                raise ValueError(
                    "retrieval evaluation changed native family or as-of index"
                )
            original, proposed = annotate(a, targets[qid]), annotate(b, targets[qid])
            counts["planned"] += 1
            row = dict(
                phase=phase,
                question_id=qid,
                source_family=a["source_family"],
                native_support_resolved=original is not None,
                original_document_hit=original[0] if original is not None else None,
                selected_document_hit=proposed[0] if proposed is not None else None,
                original_window_hit=original[1] if original is not None else None,
                selected_window_hit=proposed[1] if proposed is not None else None,
                registered_source_sha256=a["original_as_of_index_sha256"],
                independent_semantic_support_verified=False,
            )
            if (original is None) != (proposed is None):
                raise ValueError("target scoring differed across policies")
            if original is None:
                counts["unscored_original_question"] += 1
            else:
                counts["scored_original_question"] += 1
                counts["original_document_hits"] += int(original[0])
                counts["selected_document_hits"] += int(proposed[0])
                counts["original_window_hits"] += int(original[1])
                counts["selected_window_hits"] += int(proposed[1])
                counts["retrieval_rescues"] += int(not original[0] and proposed[0])
                counts["retrieval_regressions"] += int(original[0] and not proposed[0])
                counts["window_rescues"] += int(not original[1] and proposed[1])
                counts["window_regressions"] += int(original[1] and not proposed[1])
                counts["source_retrieved_but_not_windowed"] += int(
                    proposed[0] and not proposed[1]
                )
            decisions.append(row)
        all_rows = [row for row in decisions if row["phase"] == phase]
        counts["original_planned_family_count"] = len(
            {row["source_family"] for row in all_rows}
        )
        counts["native_scored_family_count"] = len(
            {row["source_family"] for row in all_rows if row["native_support_resolved"]}
        )
        out[phase] = dict(counts)
    return dict(
        schema="hepta.stem-frozen-retrieval-grid-eval.v2",
        source_only_ablation=True,
        same_original_frozen_encoder=True,
        same_query_and_source_time_pins=True,
        same_reader_calls=0,
        same_candidate_window_budget=True,
        selected_policy=selection["selected_policy"],
        matched_question_count=32,
        distinct_heldout_question_source_families=len(
            {row["source_family"] for row in decisions}
        ),
        independent_family_effect_not_verified=True,
        train_policy_revalidated_against_original_scorecard=True,
        results=out,
        decisions=decisions,
        independent_native_document_entailment_verified=False,
        no_claim_of_original_Reader_QA_gain=True,
        independent_new_source_family_validation=False,
        production_accepted=False,
    )


def posthoc_all_registered_grid_ceiling(plan, unlabelled, targets, selection):
    """Hindsight *upper bound* across the already fixed 10-grid observations.

    Held-out document-support labels are consulted ONLY after both the
    candidate receipts and TRAIN-selected policy have been finalized.
    This is NOT a deployable oracle, hyperparameter search, or Reader score.
    No ID of a hindsight-winning eval policy is selected or returned.
    """
    verify_train_selection(plan, selection)
    eval_ids = [q for p in PHASES[1:] for q in plan["questions"][p]]
    if (
        set(targets) != set(eval_ids)
        or len(eval_ids) != 32
        or len(set(eval_ids)) != 32
        or selection["train_only"] is not True
        or selection["evaluation_labels_were_not_read_to_select"] is not True
        or selection["selected_policy"] not in {label_key(g) for g in GRID}
        or selection["baseline_policy"] != label_key(BASELINE)
        or selection["train_cohort_sha256"] != digest(plan["questions"]["train"])
        or selection["train_question_count"] != len(plan["questions"]["train"])
    ):
        raise ValueError("posthoc grid ceiling cannot change fixed TRAIN selection")
    phases, decisions = {}, []
    for phase in PHASES[1:]:
        counts = defaultdict(int)
        for qid in plan["questions"][phase]:
            variants = [unlabelled[(phase, qid, label_key(config))] for config in GRID]
            if any(
                row["source_family"] != plan["question_families"][qid]
                or row["read_targets_for_retrieval"] is not False
                for row in variants
            ):
                raise ValueError("hindsight labels were available during retrieval")
            support = [annotate(row, targets[qid]) for row in variants]
            if any((s is None) != (support[0] is None) for s in support):
                raise ValueError("inconsistent native support across original grid")
            baseline = support[GRID.index(BASELINE)]
            selected = support[
                [label_key(c) for c in GRID].index(selection["selected_policy"])
            ]
            counts["planned"] += 1
            item = dict(
                phase=phase,
                question_id=qid,
                source_family=plan["question_families"][qid],
                native_document_support_resolved=baseline is not None,
                original_document_hit=baseline[0] if baseline else None,
                original_window_hit=baseline[1] if baseline else None,
                train_selected_window_hit=selected[1] if selected else None,
                any_fixed_grid_document_hit=(
                    any(hit[0] for hit in support) if baseline else None
                ),
                any_fixed_grid_window_hit=(
                    any(hit[1] for hit in support) if baseline else None
                ),
                label_exposed_only_after_all_800_candidate_receipts=True,
                hindsight_config_used_for_policy=False,
                independent_passage_entailment_reviewed=False,
            )
            if baseline is None:
                counts["unscored_native_support"] += 1
            else:
                counts["scored_native_support"] += 1
                counts["baseline_document_hits"] += int(baseline[0])
                counts["baseline_window_hits"] += int(baseline[1])
                counts["train_selected_window_hits"] += int(selected[1])
                counts["any_registered_grid_document_hits"] += int(
                    item["any_fixed_grid_document_hit"]
                )
                counts["any_registered_grid_window_hits"] += int(
                    item["any_fixed_grid_window_hit"]
                )
                counts["hindsight_grid_could_rescue_missing_document"] += int(
                    not baseline[0] and item["any_fixed_grid_document_hit"]
                )
                counts["hindsight_grid_could_rescue_missing_window"] += int(
                    not baseline[1] and item["any_fixed_grid_window_hit"]
                )
                counts["retrieved_but_no_window_under_any_grid"] += int(
                    item["any_fixed_grid_document_hit"]
                    and not item["any_fixed_grid_window_hit"]
                )
            decisions.append(item)
        if counts["planned"] != 8:
            raise ValueError("fixed eight-question evaluation phase changed")
        phases[phase] = dict(counts)
    return dict(
        schema="hepta.stem-frozen-retrieval-grid-hindsight-ceiling.v1",
        fixed_grid_policy_count=len(GRID),
        fixed_train_selected_policy=selection["selected_policy"],
        original_baseline_policy=label_key(BASELINE),
        planned_evaluation_questions=32,
        trained_or_tuned_on_evaluation_labels=False,
        upper_bound_requires_forbidden_per_question_oracle=True,
        actual_frozen_reader_calls=0,
        independent_source_window_entailment_reviewed=False,
        task_answer_gain_proven=False,
        by_phase=phases,
        decisions=decisions,
        production_accepted=False,
    )
