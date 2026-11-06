"""TRAIN-label placebo for native persistent Stem Heads; no Reader or test gold.

This ablation isolates weak source-label information from optimizer movement.
Both real and placebo fit the exact same frozen Features and admitted TRAIN
question IDs, with the same seed, head architecture, steps and candidate count.
A placebo is an explicitly *unlabelled* candidate, NOT a verified false fact.
"""

from hashlib import sha256
from pathlib import Path
import math

import torch

from native import digest
from selector_head import Supervision
from stem_cell import StemHead, sha256 as file_sha256
from stem_pairwise_shadow import fit_pairwise_shadow

STAGES = (16, 32, 48)
PHASES = ("select", "retention", "test", "transfer")
CELLS = ("general", "temporal")
KINDS = ("linear", "gated")
LABELS = ("weak_source", "nonpositive_placebo")
STEPS = 128
LR = 0.03
MARGIN = 1.0


def placebo_labels(row):
    """A deterministic disjoint weak label with the same positive cardinality."""
    f = row.features
    positives = tuple(row.positive_indices)
    n = len(f.candidate_ids)
    if (
        type(n) is not int
        or not 0 < len(positives) <= n // 2
        or len(set(positives)) != len(positives)
        or any(type(i) is not int or not 0 <= i < n for i in positives)
    ):
        raise ValueError("no balanced, distinct weak-source label alternatives")
    eligible = (i for i in range(n) if i not in positives)
    ranked = sorted(
        eligible,
        key=lambda i: (
            sha256(
                digest(
                    (
                        f.question_id,
                        f.family,
                        f.pool_digest,
                        f.candidate_ids[i],
                        "fixed-negative-label-placebo-v1",
                    )
                ).encode()
            ).hexdigest(),
            f.candidate_ids[i],
        ),
    )
    result = tuple(sorted(ranked[: len(positives)]))
    if len(result) != len(positives) or set(result) & set(positives):
        raise ValueError("placebo source label not disjoint")
    return Supervision(f, result, row.negative_kinds)


def _top1(scores, candidate_ids):
    if len(scores) != len(candidate_ids):
        raise ValueError("source scores differ from frozen candidate census")
    if not candidate_ids:
        return None
    if any(type(s) not in (int, float) or not math.isfinite(s) for s in scores):
        raise ValueError("nonfinite source-selection scores")
    return min(range(len(candidate_ids)), key=lambda i: (-scores[i], candidate_ids[i]))


def label_placebo_shadow(questions, training_rows, features, cut, routes, output):
    """24 source-only fits and 384 answer-blind choices at fixed checkpoints."""
    if (
        set(questions) != {"train", *PHASES}
        or len(questions["train"]) != 48
        or any(len(questions[p]) != 8 for p in PHASES)
        or not isinstance(output, Path)
        or not output.is_dir()
        or output.is_symlink()
    ):
        raise ValueError("unregistered label-placebo question cohort")
    train = tuple(q.identity for q in questions["train"])
    heldout = {p: tuple(q.identity for q in questions[p]) for p in PHASES}
    all_ids = train + tuple(q for p in PHASES for q in heldout[p])
    if (
        len(all_ids) != len(set(all_ids))
        or len(all_ids) != 80
        or set(routes) != set(features)
        or set(routes) != set(all_ids)
        or set(cut.question_ids) != set(train)
        or any(routes[q] not in CELLS for q in all_ids)
    ):
        raise ValueError("train/heldout, route or feature identity drift")
    dims = {features[q].paired.shape[1] for q in all_ids}
    encoders = {features[q].encoder_identity for q in all_ids}
    if len(dims) != 1 or len(encoders) != 1:
        raise ValueError("frozen shared Encoder is not identical")
    dim, encoder = next(iter(dims)), next(iter(encoders))
    for qid in all_ids:
        f = features[qid]
        f.validate(dim)
        if f.question_id != qid:
            raise ValueError("frozen question and Feature are detached")

    admitted = {}
    for row in training_rows:
        f = row.features
        f.validate(dim)
        if (
            f.question_id not in train
            or f.question_id in admitted
            or f.seal() != features[f.question_id].seal()
            or f.family not in cut.families
            or not f.roots.issubset(cut.allowed_roots)
            or f.roots.intersection(cut.forbidden_roots)
        ):
            raise ValueError("unadmitted, overlapping or reencoded TRAIN row")
        positives = tuple(row.positive_indices)
        if len(set(positives)) != len(positives) or any(
            type(i) is not int or not 0 <= i < len(f.candidate_ids) for i in positives
        ):
            raise ValueError("invalid native TRAIN supervision")
        if 0 < len(positives) <= len(f.candidate_ids) // 2:
            admitted[f.question_id] = row
    if not admitted or {routes[q] for q in admitted} != set(CELLS):
        raise ValueError("no usable paired TRAIN label in both Cells")

    heads, seeds = {}, {}
    for kind in KINDS:
        for cell in CELLS:
            seed = StemHead(dim, encoder, kind=kind).export()
            seed_sha = file_sha256(seed)
            seeds[kind, cell] = seed_sha
            for condition in LABELS:
                head = StemHead.restore(
                    seed,
                    expected_sha256=seed_sha,
                    encoder_identity=encoder,
                    allowed_roots=set(cut.allowed_roots),
                    revoked=set(),
                )
                if head.export() != seed:
                    raise ValueError("placebo and real initial Head bytes differ")
                heads[kind, cell, condition] = head

    fits, choices = [], []
    for stage in STAGES:
        for kind in KINDS:
            for cell in CELLS:
                rows = tuple(
                    admitted[q]
                    for q in train[:stage]
                    if q in admitted and routes[q] == cell
                )
                ids_sha = digest(tuple(r.features.question_id for r in rows))
                if not rows:
                    raise ValueError("a registered checkpoint Cell lacks TRAIN data")
                for condition in LABELS:
                    head = heads[kind, cell, condition]
                    entry = dict(
                        stage=stage,
                        kind=kind,
                        cell=cell,
                        condition=condition,
                        status="failed",
                        initial_seed_sha256=seeds[kind, cell],
                        prior_head_sha256=file_sha256(head.export()),
                        training_question_ids_sha256=ids_sha,
                        training_question_count=len(rows),
                        updates_requested=STEPS,
                        original_six_arms_unchanged=True,
                    )
                    try:
                        actual = (
                            rows
                            if condition == "weak_source"
                            else tuple(placebo_labels(row) for row in rows)
                        )
                        receipt = fit_pairwise_shadow(
                            head,
                            actual,
                            cut,
                            revoked=set(),
                            steps=STEPS,
                            lr=LR,
                            margin=MARGIN,
                        )
                        if (
                            receipt["consumed_steps"] != STEPS
                            or receipt["null_weights_unchanged"] is not True
                            or receipt["observed_original_reader_calls"] != 0
                        ):
                            raise ValueError(
                                "control and placebo training budgets drift"
                            )
                        payload = head.export()
                        name = f"label-control-{kind}-{cell}-{condition}-{stage}.json"
                        with (output / name).open("xb") as handle:
                            handle.write(payload)
                        restored = StemHead.restore(
                            payload,
                            expected_sha256=file_sha256(payload),
                            encoder_identity=encoder,
                            allowed_roots=set(cut.allowed_roots),
                            revoked=set(),
                        )
                        if restored.export() != payload:
                            raise ValueError("label control reload changed Head bytes")
                        heads[kind, cell, condition] = restored
                        entry.update(
                            status="succeeded",
                            model_file=name,
                            model_bytes=len(payload),
                            post_head_sha256=file_sha256(payload),
                            supervision_sha256=digest(
                                tuple(
                                    (r.features.question_id, tuple(r.positive_indices))
                                    for r in actual
                                )
                            ),
                            receipt=receipt,
                        )
                    except Exception as exc:
                        entry.update(
                            error_type=type(exc).__name__, error=str(exc)[:1024]
                        )
                    fits.append(entry)
        for phase in PHASES:
            for q in questions[phase]:
                f = features[q.identity]
                cell = routes[q.identity]
                with torch.no_grad():
                    original = _top1(f.frozen_scores.tolist(), f.candidate_ids)
                for kind in KINDS:
                    for condition in LABELS:
                        head = heads[kind, cell, condition]
                        entry = dict(
                            stage=stage,
                            phase=phase,
                            question_id=q.identity,
                            family=f.family,
                            cell=cell,
                            kind=kind,
                            condition=condition,
                            status="failed",
                            initial_seed_sha256=seeds[kind, cell],
                            pool_sha256=f.pool_digest,
                            feature_sha256=f.seal(),
                            candidate_ids_sha256=digest(f.candidate_ids),
                            candidate_count=len(f.candidate_ids),
                            original_frozen_selected=original,
                            original_reader_calls=0,
                            heldout_labels_read=False,
                        )
                        try:
                            if head.quarantined:
                                raise ValueError("label-control Head quarantined")
                            with torch.no_grad():
                                scores = head(f).tolist()[:-1]
                            entry.update(
                                status="succeeded",
                                selected=_top1(scores, f.candidate_ids),
                                head_sha256=file_sha256(head.export()),
                            )
                        except Exception as exc:
                            entry.update(
                                error_type=type(exc).__name__, error=str(exc)[:1024]
                            )
                        choices.append(entry)
    if len(fits) != 24 or len(choices) != 384:
        raise ValueError("lost an original label-control task or fit")
    return fits, choices


def review_placebo(questions, fits, choices, pools, targets, *, support_indices):
    """Weak document-source review only, after all choices have been sealed."""
    if len(fits) != 24 or len(choices) != 384 or not callable(support_indices):
        raise ValueError("missing complete placebo census or scorer")
    by_fit = {}
    for row in fits:
        key = row["stage"], row["kind"], row["cell"], row["condition"]
        if (
            key in by_fit
            or row["stage"] not in STAGES
            or row["kind"] not in KINDS
            or row["cell"] not in CELLS
            or row["condition"] not in LABELS
        ):
            raise ValueError("duplicate or nonregistered placebo fit")
        by_fit[key] = row
    index = {}
    for row in choices:
        key = (
            row["stage"],
            row["phase"],
            row["question_id"],
            row["kind"],
            row["condition"],
        )
        if (
            key in index
            or row["stage"] not in STAGES
            or row["phase"] not in PHASES
            or row["kind"] not in KINDS
            or row["condition"] not in LABELS
            or row["status"] not in ("succeeded", "failed")
            or row["original_reader_calls"] != 0
            or row["heldout_labels_read"] is not False
        ):
            raise ValueError("invalid, repeated or answer-conditioned placebo choice")
        fit = by_fit[row["stage"], row["kind"], row["cell"], row["condition"]]
        if (
            row["initial_seed_sha256"] != fit["initial_seed_sha256"]
            or row["status"] == "succeeded"
            and (
                fit["status"] != "succeeded"
                or row["head_sha256"] != fit["post_head_sha256"]
            )
        ):
            raise ValueError("placebo decision not from its saved Head")
        index[key] = row
    expected = {
        (stage, phase, q.identity, kind, condition)
        for stage in STAGES
        for phase in PHASES
        for q in questions[phase]
        for kind in KINDS
        for condition in LABELS
    }
    if set(index) != expected or len(by_fit) != 24:
        raise ValueError("label-control choices or fits missing from denominator")
    cohort = {}
    for stage in STAGES:
        for phase in PHASES:
            for kind in KINDS:
                wins = losses = changes = scored = missing = 0
                learned_vs_frozen = placebo_vs_frozen = 0
                for q in questions[phase]:
                    a = index[stage, phase, q.identity, kind, LABELS[0]]
                    b = index[stage, phase, q.identity, kind, LABELS[1]]
                    if (
                        a["family"] != b["family"]
                        or a["pool_sha256"] != b["pool_sha256"]
                        or a["feature_sha256"] != b["feature_sha256"]
                        or a["candidate_ids_sha256"] != b["candidate_ids_sha256"]
                        or a["original_frozen_selected"]
                        != b["original_frozen_selected"]
                        or a["cell"] != b["cell"]
                        or a["initial_seed_sha256"] != b["initial_seed_sha256"]
                    ):
                        raise ValueError(
                            "placebo changed frozen Encoder or candidate pool"
                        )
                    pool = pools.get(q.identity)
                    if (
                        pool is None
                        or pool.seal() != a["pool_sha256"]
                        or any(
                            c["status"] == "succeeded"
                            and (
                                type(c["selected"]) is not int
                                or not 0 <= c["selected"] < c["candidate_count"]
                            )
                            for c in (a, b)
                        )
                    ):
                        raise ValueError("unbound placebo selection or changed pool")
                    if a["status"] != "succeeded" or b["status"] != "succeeded":
                        missing += 1
                        continue
                    changes += a["selected"] != b["selected"]
                    target = targets[q.identity]
                    if (
                        target.unanswerable
                        or target.unresolved_evidence
                        or not target.evidence
                    ):
                        missing += 1
                        continue
                    support = set(support_indices(pool, target))
                    aa, bb = a["selected"] in support, b["selected"] in support
                    wins += aa and not bb
                    losses += bb and not aa
                    learned_vs_frozen += (
                        aa and a["original_frozen_selected"] not in support
                    )
                    placebo_vs_frozen += (
                        bb and b["original_frozen_selected"] not in support
                    )
                    scored += 1
                if scored + missing != 8:
                    raise ValueError("placebo review changed original cohort size")
                cohort[f"{stage}/{phase}/{kind}"] = dict(
                    attempted=8,
                    weak_source_scored=scored,
                    failed_or_unresolved=missing,
                    label_placebo_selection_changes=changes,
                    real_label_over_placebo_weak_source_wins=wins,
                    placebo_over_real_label_weak_source_wins=losses,
                    real_label_over_frozen_weak_source_gains=learned_vs_frozen,
                    placebo_over_frozen_weak_source_gains=placebo_vs_frozen,
                    all_planned_real_minus_placebo_weak_bounds=[
                        (wins - losses - missing) / 8,
                        (wins - losses + missing) / 8,
                    ],
                    independent_semantic_support_verified=False,
                )
    return dict(
        schema="hepta.stem-weak-source-label-placebo.v1",
        original_native_reader_calls=0,
        original_six_arms_unchanged=True,
        trained_heads=len(fits),
        sealed_choices=len(choices),
        exact_candidate_and_initial_head_pairing=True,
        weak_unlabelled_is_not_a_verified_negative=True,
        no_new_reader_answer_quality_measured=True,
        independent_semantic_citation_precision=None,
        no_prospective_independent_family_claim=True,
        production_accepted=False,
        by_stage_phase_kind=cohort,
    )
