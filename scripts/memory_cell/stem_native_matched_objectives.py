"""Budget-matched CE versus pairwise source Head SHADOW on frozen Features.

Separate read-only research arm: identical initialized Head bytes, admitted
TRAIN-only positive+negative pairs, same update steps, LR and static Encoder.
All 384 source choices are made before ANY held-out native target is read.
Original six policies, Reader cache, and model weights are not modified.
"""

import time
from pathlib import Path

import torch

from native import digest
from stem_cell import StemHead, sha256
from stem_pairwise_shadow import fit_pairwise_shadow

STAGES = (16, 32, 48)
PHASES = ("select", "retention", "test", "transfer")
CELLS = ("general", "temporal")
KINDS = ("linear", "gated")
OBJECTIVES = ("multi_positive_ce", "positive_vs_weak_negative")
STEPS = 128
LR = 0.03
MARGIN = 1.0


def _top1(values, names):
    if len(values) != len(names):
        raise ValueError("matched-objective Head candidate dimensions changed")
    return min(range(len(names)), key=lambda i: (-values[i], names[i])) if names else None


def matched_objective_shadow(
    questions, training_rows, features, cut, routes, output,
):
    """Fit 24 persistent Heads and seal 384 label-blind candidate selections."""
    train = tuple(q.identity for q in questions["train"])
    test = {
        p: tuple(q.identity for q in questions[p]) for p in PHASES
    }
    ids = train + tuple(q for phase in PHASES for q in test[phase])
    if (
        set(questions) != {"train", *PHASES}
        or len(train) != 48 or len(set(train)) != 48
        or any(len(test[p]) != 8 for p in PHASES)
        or len(ids) != len(set(ids)) or len(ids) != 80
        or set(routes) != set(features) or set(routes) != set(ids)
        or any(routes[q] not in CELLS for q in ids)
        or set(cut.question_ids) != set(train)
        or not isinstance(output, Path) or not output.is_dir()
    ):
        raise ValueError("unregistered source-only matched-objective cohort")
    dimensions = {features[q].paired.shape[1] for q in ids}
    identities = {features[q].encoder_identity for q in ids}
    if len(dimensions) != 1 or len(identities) != 1:
        raise ValueError("frozen Encoder differs across objective arms")
    d, encoder_id = next(iter(dimensions)), next(iter(identities))
    for q in ids:
        f = features[q]
        f.validate(d)
        if f.question_id != q:
            raise ValueError("feature/question identity detached")
    admissible = {}
    for row in training_rows:
        f = row.features
        n = len(f.candidate_ids)
        if (
            f.question_id not in train or f.question_id in admissible
            or f.seal() != features[f.question_id].seal()
            or f.family not in cut.families
        ):
            raise ValueError("held-out or reencoded training observation")
        if 0 < len(row.positive_indices) < n:
            admissible[f.question_id] = row
    if not admissible:
        raise ValueError("no originally admitted positive/negative pair")

    heads, seeds = {}, {}
    for kind in KINDS:
        for cell in CELLS:
            first = StemHead(d, encoder_id, kind=kind)
            seed = first.export()
            source_sha = sha256(seed)
            for objective in OBJECTIVES:
                copy = StemHead.restore(
                    seed, expected_sha256=source_sha,
                    encoder_identity=encoder_id,
                    allowed_roots=set(cut.allowed_roots), revoked=set(),
                )
                if copy.export() != seed:
                    raise ValueError("matched-objective initial Head bytes differ")
                heads[(kind, objective, cell)] = copy
            seeds[(kind, cell)] = source_sha

    fitted, choices = [], []
    for stage in STAGES:
        for kind in KINDS:
            for cell in CELLS:
                eligible = tuple(
                    admissible[q] for q in train[:stage]
                    if q in admissible and routes[q] == cell
                )
                train_ids = tuple(x.features.question_id for x in eligible)
                for objective in OBJECTIVES:
                    head = heads[kind, objective, cell]
                    row = dict(
                        stage=stage, kind=kind, objective=objective,
                        cell=cell, status="failed",
                        shared_initial_head_sha256=seeds[kind, cell],
                        previous_head_sha256=sha256(head.export()),
                        admitted_same_positive_negative_questions=len(eligible),
                        train_question_ids_sha256=digest(train_ids),
                        role="separate-nonqualifying-no-Reader-objective-ablation",
                    )
                    started = time.perf_counter()
                    try:
                        if objective == "multi_positive_ce":
                            receipt = head.fit(
                                eligible, cut, revoked=set(), steps=STEPS, lr=LR,
                            )
                        else:
                            receipt = fit_pairwise_shadow(
                                head, eligible, cut, revoked=set(),
                                steps=STEPS, lr=LR, margin=MARGIN,
                            )
                        if receipt["consumed_steps"] != STEPS:
                            raise ValueError("objective used fewer than matched steps")
                        payload = head.export()
                        path = output / (
                            f"matched-{kind}-{objective}-{cell}-{stage}.json"
                        )
                        with path.open("xb") as stream:
                            stream.write(payload)
                        restored = StemHead.restore(
                            payload, expected_sha256=sha256(payload),
                            encoder_identity=encoder_id,
                            allowed_roots=set(cut.allowed_roots), revoked=set(),
                        )
                        if restored.export() != payload:
                            raise ValueError("objective Head reload parity failed")
                        heads[kind, objective, cell] = restored
                        row.update(
                            status="succeeded",
                            receipt=receipt,
                            post_head_sha256=sha256(payload),
                            model_file_name=path.name,
                            model_bytes=len(payload),
                            reload_parity=True,
                            no_original_head_or_reader_mutation=True,
                        )
                    except Exception as exc:
                        row.update(
                            error_type=type(exc).__name__, error=str(exc)[:1024],
                        )
                    row["inclusive_fit_seconds"] = time.perf_counter() - started
                    fitted.append(row)
        failures = {
            (f["kind"], f["objective"], f["cell"]): f["error_type"]
            for f in fitted if f["stage"] == stage and f["status"] == "failed"
        }
        for phase in PHASES:
            for qid in test[phase]:
                f, cell = features[qid], routes[qid]
                for kind in KINDS:
                    for objective in OBJECTIVES:
                        row = dict(
                            stage=stage, phase=phase, question_id=qid,
                            kind=kind, objective=objective, cell=cell,
                            family=f.family,
                            status="failed",
                            pool_sha256=f.pool_digest,
                            feature_sha256=f.seal(),
                            ordered_candidate_ids_sha256=digest(f.candidate_ids),
                            candidate_count=len(f.candidate_ids),
                            registered_train_only_labels=True,
                            heldout_annotations_read_before_choices=False,
                            incremental_encoder_calls=0,
                            incremental_reader_calls=0,
                            shared_initial_head_sha256=seeds[kind, cell],
                        )
                        try:
                            if (kind, objective, cell) in failures:
                                raise ValueError(failures[kind, objective, cell])
                            head = heads[kind, objective, cell]
                            with torch.no_grad():
                                scores = head(f).tolist()
                            n = len(f.candidate_ids)
                            if len(scores) != n + 1:
                                raise ValueError("Head null/candidate shape changed")
                            row.update(
                                status="succeeded",
                                selected=_top1(scores[:n], f.candidate_ids),
                                original_frozen_selected=_top1(
                                    f.frozen_scores.tolist(), f.candidate_ids
                                ),
                                matched_head_sha256=sha256(head.export()),
                                score_vector_sha256=digest(scores),
                            )
                        except Exception as exc:
                            row.update(
                                error_type=type(exc).__name__,
                                error=str(exc)[:1024],
                            )
                        choices.append(row)
    if len(fitted) != 24 or len(choices) != 384:
        raise ValueError("matched source-objective experiment was incomplete")
    return fitted, choices


def review_objectives(questions, fitted, choices, pools, targets, *,
                      support_indices):
    """Review weak native document support after the choices are frozen."""
    index = {}
    for row in choices:
        key = (row["stage"], row["phase"], row["question_id"],
               row["kind"], row["objective"])
        if key in index:
            raise ValueError("duplicate pairwise-vs-CE decision")
        index[key] = row
    expected = {
        (stage, phase, q.identity, kind, objective)
        for stage in STAGES for phase in PHASES
        for q in questions[phase] for kind in KINDS
        for objective in OBJECTIVES
    }
    if set(index) != expected or len(index) != len(choices) != 384:
        raise ValueError("missing original 384 label-blind Shadow choices")
    by_fit = {}
    original_seed = {}
    for row in fitted:
        key = (row["stage"], row["kind"], row["objective"], row["cell"])
        if (
            key in by_fit or row["stage"] not in STAGES
            or row["kind"] not in KINDS or row["objective"] not in OBJECTIVES
            or row["cell"] not in CELLS
            or row["status"] not in ("succeeded", "failed")
            or row["role"] != "separate-nonqualifying-no-Reader-objective-ablation"
        ):
            raise ValueError("duplicate, forged or unmatched objective fit")
        seed = (row["kind"], row["cell"])
        if seed in original_seed and (
            row["shared_initial_head_sha256"] != original_seed[seed]
        ):
            raise ValueError("CE versus pairwise objective initial weights differ")
        original_seed[seed] = row["shared_initial_head_sha256"]
        if row["status"] == "succeeded" and (
            row["receipt"]["consumed_steps"] != STEPS
            or row["admitted_same_positive_negative_questions"] < 1
            or row["reload_parity"] is not True
            or row["no_original_head_or_reader_mutation"] is not True
            or row["receipt"]["production_accepted"] is not False
            or (row["objective"] == "positive_vs_weak_negative"
                and row["receipt"]["null_weights_unchanged"] is not True)
        ):
            raise ValueError("fit objectives did not use matched budget/unchanged Reader")
        by_fit[key] = row
    expected_fit = {
        (stage, kind, obj, cell)
        for stage in STAGES for kind in KINDS
        for obj in OBJECTIVES for cell in CELLS
    }
    if set(by_fit) != expected_fit or len(fitted) != 24:
        raise ValueError("incomplete 24 fit/checkpoint objective census")
    for stage in STAGES:
        for kind in KINDS:
            for cell in CELLS:
                a, b = (
                    by_fit[stage, kind, OBJECTIVES[0], cell],
                    by_fit[stage, kind, OBJECTIVES[1], cell],
                )
                if (
                    a["shared_initial_head_sha256"]
                    != b["shared_initial_head_sha256"]
                    or a["train_question_ids_sha256"] != b["train_question_ids_sha256"]
                    or a["admitted_same_positive_negative_questions"]
                    != b["admitted_same_positive_negative_questions"]
                ):
                    raise ValueError("objective training data or initialization differs")
    results = {}
    for stage in STAGES:
        for phase in PHASES:
            for kind in KINDS:
                changed = scored = pairwise_wins = ce_wins = uncertain = 0
                for q in questions[phase]:
                    qid = q.identity
                    ce = index[stage, phase, qid, kind, OBJECTIVES[0]]
                    pair = index[stage, phase, qid, kind, OBJECTIVES[1]]
                    if (
                        ce["shared_initial_head_sha256"]
                        != pair["shared_initial_head_sha256"]
                        or ce["pool_sha256"] != pair["pool_sha256"]
                        or ce["feature_sha256"] != pair["feature_sha256"]
                        or ce["ordered_candidate_ids_sha256"]
                        != pair["ordered_candidate_ids_sha256"]
                        or ce["family"] != pair["family"]
                        or ce["cell"] != pair["cell"]
                    ):
                        raise ValueError("objective matched initialization or sources drift")
                    for row in (ce, pair):
                        if row["status"] == "succeeded":
                            fit = by_fit[
                                row["stage"], row["kind"],
                                row["objective"], row["cell"]
                            ]
                            if (
                                fit["status"] != "succeeded"
                                or row.get("matched_head_sha256")
                                != fit.get("post_head_sha256")
                            ):
                                raise ValueError(
                                    "shadow score not from persisted matched Head"
                                )
                    if ce["status"] != "succeeded" or pair["status"] != "succeeded":
                        uncertain += 1
                        continue
                    changed += ce["selected"] != pair["selected"]
                    target = targets[qid]
                    if target.unanswerable or target.unresolved_evidence or not target.evidence:
                        uncertain += 1
                        continue
                    pool = pools.get(qid)
                    if pool is None or pool.seal() != ce["pool_sha256"]:
                        raise ValueError("altered original candidate pool in review")
                    support = set(support_indices(pool, target))
                    scored += 1
                    before = ce["selected"] in support
                    after = pair["selected"] in support
                    pairwise_wins += after and not before
                    ce_wins += before and not after
                if scored + uncertain != 8:
                    raise ValueError("shadow objective review denominator mismatch")
                results[f"{stage}/{phase}/{kind}"] = dict(
                    attempted=8,
                    matched_label_blind_selection_changes=changed,
                    native_weak_source_scored=scored,
                    unscored_or_failed=uncertain,
                    pairwise_over_ce_weak_source_gains=pairwise_wins,
                    ce_over_pairwise_weak_source_gains=ce_wins,
                    native_weak_document_labels_not_entailment=True,
                    original_reader_calls=0,
                )
    return dict(
        schema="hepta.stem-identical-initialization-objective-shadow.v1",
        fitted_objective_checkpoints=len(fitted),
        label_blind_shadow_decisions=len(choices),
        fixed_frozen_encoder_inputs=True,
        training_questions_same_for_both_objectives=True,
        initial_head_weights_identical=True,
        training_budget_updates_matched=STEPS,
        independent_semantic_source_judgment=False,
        by_stage_phase_kind=results,
        heldout_reader_answers_not_measured=True,
        no_original_policy_or_reader_mutation=True,
        production_accepted=False,
    )
