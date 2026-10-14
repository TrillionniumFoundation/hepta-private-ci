"""Single-Cell, train-only continuation opportunity diagnostic.

Uses the existing Continuation/Features/TrainingCut; no Reader or new runtime.
Native source membership remains weak supervision, NOT joint sufficiency. The
legacy sampler is retained unchanged as a comparator. Pairing changes training
exposure and costs; equal updates are not equal compute or a task-effect claim.
"""

from collections import Counter
from dataclasses import dataclass
import itertools
import math
import time

import torch

from system2_ablation import (
    Continuation,
    Limits,
    Meter,
    digest,
    model_digest,
    train_continuation,
)


@dataclass(frozen=True)
class Opportunity:
    feature: object
    paths: tuple
    positive: tuple
    negative: tuple


def prepare(rows, cut, dimension, *, revoked=frozenset()):
    """Validate the ENTIRE cut before inspecting any source-support label."""
    if not 1 <= len(rows) <= 256 or not cut.admission_digest:
        raise ValueError("bounded admitted train cut required")
    seen, encoders = set(), set()
    for row in rows:
        f = row.features
        f.validate(dimension)
        if (
            f.question_id not in cut.question_ids
            or f.question_id in seen
            or f.family not in cut.families
            or not f.roots.issubset(cut.allowed_roots)
            or f.roots.intersection(cut.forbidden_roots | revoked)
            or not f.encoder_identity
            or not f.pool_digest
        ):
            raise ValueError("unadmitted, duplicate or withdrawn training input")
        seen.add(f.question_id)
        encoders.add(f.encoder_identity)
    if len(encoders) != 1:
        raise ValueError("mixed encoder lineage")
    result, disposition = [], []
    for row in rows:
        f = row.features
        positive = row.positive_indices
        if len(set(positive)) != len(positive) or any(
            type(i) is not int or not 0 <= i < len(f.candidate_ids) for i in positive
        ):
            raise ValueError("invalid native support indices")
        proposal = sorted(
            range(len(f.candidate_ids)),
            key=lambda i: (-float(f.frozen_scores[i]), f.candidate_ids[i]),
        )[:4]
        paths = ((),) + tuple(
            p
            for d in range(1, min(len(proposal), 3) + 1)
            for p in itertools.combinations(proposal, d)
        )
        pos = tuple(p for p in paths if set(p).intersection(positive))
        neg = tuple(p for p in paths if not set(p).intersection(positive))
        result.append(Opportunity(f, paths, pos, neg))
        disposition.append(
            dict(
                question_id=f.question_id,
                feature_digest=f.seal(),
                proposal_candidate_ids=[f.candidate_ids[i] for i in proposal],
                positive_paths=len(pos),
                negative_paths=len(neg),
                eligible=bool(pos and neg),
                reason="paired_weak_support_available"
                if pos and neg
                else "no_positive_in_proposal_not_null_supervision",
            )
        )
    return tuple(result), disposition


def cycle_path(paths, visit):
    """Cycle cardinalities PER QUESTION, not by its global position in the cut."""
    sizes = sorted({len(p) for p in paths})
    size = sizes[visit % len(sizes)]
    group = [p for p in paths if len(p) == size]
    return group[(visit // len(sizes)) % len(group)]


@torch.no_grad()
def inspect(model, opportunities, *, revoked=frozenset()):
    """Free argmax over the unchanged top-four path pool, INCLUDING empty."""
    if model.quarantined or model.roots.intersection(revoked):
        raise ValueError("unavailable continuation")
    before = model_digest(model)
    meter = Meter(Limits(seconds=300))
    records = []
    for item in opportunities:
        f = item.feature
        f.validate(model.dimension)
        if f.roots.intersection(revoked) or model.encoder_identity not in (
            None,
            f.encoder_identity,
        ):
            raise ValueError("withdrawn or incompatible probe")
        scores = []
        for path in item.paths:
            meter.charge("critic_forward", 1)
            meter.charge("feature_pairs", len(path))
            value = float(model(f.paired[list(path)]))
            if not math.isfinite(value):
                raise ValueError("nonfinite continuation score")
            scores.append((value, path))
        value, chosen = min(
            scores, key=lambda s: (-s[0], tuple(f.candidate_ids[i] for i in s[1]))
        )
        best_positive = max((v for v, p in scores if p in item.positive), default=None)
        best_negative = max(v for v, p in scores if p in item.negative)
        records.append(
            dict(
                question_id=f.question_id,
                feature_digest=f.seal(),
                selected_candidate_ids=[f.candidate_ids[i] for i in chosen],
                empty=not chosen,
                weak_support_hit=chosen in item.positive,
                opportunity=bool(item.positive),
                value=value,
                positive_negative_margin=None
                if best_positive is None
                else best_positive - best_negative,
            )
        )
    if model_digest(model) != before:
        raise ValueError("probe mutated model")
    return dict(
        records=records,
        costs=meter.receipt(),
        model_digest=before,
        weak_support_hits=sum(r["weak_support_hit"] for r in records),
        empty_choices=sum(r["empty"] for r in records),
        no_positive_opportunity=sum(not r["opportunity"] for r in records),
        is_task_accuracy=False,
    )


@torch.enable_grad()
def fit_paired(
    model,
    rows,
    cut,
    *,
    steps=96,
    operation_ceiling=100000,
    revoked=frozenset(),
    sampling="paired",
):
    """One hit/miss pair from the SAME question for each optimizer update.

    shape_matched_random uses the identical per-question cardinality schedule,
    but samples subsets uniformly within the SAME top-four proposal. It matches
    neural forward counts and transition lengths, not guaranteed wall latency.

    Missing support is never converted to an unanswerable question. Pair labels
    only concern the recorded source-membership objective. Failures quarantine
    partial weights and retain attempted work, including pre-update failures.
    """
    if (
        sampling not in ("paired", "shape_matched_random")
        or type(steps) is not int
        or not 1 <= steps <= 2048
        or torch.is_inference_mode_enabled()
        or model.quarantined
        or model.roots.intersection(cut.forbidden_roots | revoked)
    ):
        raise ValueError("invalid paired session")
    all_items, disposition = prepare(rows, cut, model.dimension, revoked=revoked)
    eligible = tuple(i for i in all_items if i.positive and i.negative)
    if model.encoder_identity not in (None, rows[0].features.encoder_identity):
        raise ValueError("continuation lineage drift")
    if not eligible:
        return dict(
            status="unavailable",
            updates=0,
            disposition=disposition,
            reason="no_paired_training_opportunity",
            costs=None,
        )
    before = model_digest(model)
    meter = Meter(Limits(operations=operation_ceiling, seconds=300))
    optimizer = torch.optim.SGD(model.parameters(), lr=0.03)
    visits = Counter()
    records = []
    random = torch.Generator().manual_seed(719)
    try:
        for step in range(steps):
            item = eligible[step % len(eligible)]
            f = item.feature
            pos = cycle_path(item.positive, visits[f.question_id])
            neg = cycle_path(item.negative, visits[f.question_id])
            paths, targets = (pos, neg), (1.0, 0.0)
            if sampling == "shape_matched_random":
                proposal = [p[0] for p in item.paths if len(p) == 1]
                sampled = []
                for path in paths:
                    chosen = {
                        proposal[i]
                        for i in torch.randperm(len(proposal), generator=random)[
                            : len(path)
                        ].tolist()
                    }
                    sampled.append(tuple(i for i in proposal if i in chosen))
                paths = tuple(sampled)
                targets = tuple(float(p in item.positive) for p in paths)
            event = dict(
                step=step,
                question_id=f.question_id,
                feature_digest=f.seal(),
                sampling=sampling,
                paths=[list(p) for p in paths],
                targets=list(targets),
                status="started",
            )
            if sampling == "paired":
                event.update(positive_indices=list(pos), negative_indices=list(neg))
            records.append(event)
            predictions = []
            for path in paths:
                meter.charge("critic_forward", 1)
                meter.charge("feature_pairs", len(path))
                predictions.append(model(f.paired[list(path)]))
            loss = (
                torch.nn.functional.binary_cross_entropy(
                    predictions[0], predictions[0].new_tensor(targets[0])
                )
                + torch.nn.functional.binary_cross_entropy(
                    predictions[1], predictions[1].new_tensor(targets[1])
                )
            ) / 2
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                model.parameters(), 1.0, error_if_nonfinite=True
            )
            meter.charge("optimizer_updates", 1)
            optimizer.step()
            if not all(torch.isfinite(p).all() for p in model.parameters()):
                raise ValueError("nonfinite update")
            visits[f.question_id] += 1
            event.update(
                status="completed",
                loss=float(loss.detach()),
                first_prediction_before=float(predictions[0].detach()),
                second_prediction_before=float(predictions[1].detach()),
            )
    except Exception as exc:
        model.quarantined = True
        model.last_probe_failure = dict(
            before=before,
            costs=meter.receipt(),
            records=records,
            completed_updates=sum(e["status"] == "completed" for e in records),
            error_type=type(exc).__name__,
            error=str(exc)[:512],
        )
        raise
    model.encoder_identity = rows[0].features.encoder_identity
    model.roots = model.roots.union(root for row in rows for root in row.features.roots)
    return dict(
        status="succeeded",
        before=before,
        after=model_digest(model),
        updates=len(records),
        disposition=disposition,
        records=records,
        visits=dict(visits),
        costs=meter.receipt(),
        sampling=sampling,
        objective="native-source-hit-miss-not-joint-sufficiency",
        no_forced_evidence_at_evaluation=True,
    )


def run_probe(rows, cut, dimension, *, steps=96, revoked=frozenset()):
    """Fresh equal-initialization three-way comparison on ONE supplied Cell.

    The comparison is made on training questions, not held-out Reader accuracy.
    No labels or fields from the Reader controls enter either optimizer.
    """
    started = time.perf_counter()
    opportunities, disposition = prepare(rows, cut, dimension, revoked=revoked)
    stamps = {r.features.question_id: r.features.seal() for r in rows}
    snapshot = Continuation(dimension)
    initial = inspect(snapshot, opportunities, revoked=revoked)
    results = {}
    for method in ("legacy", "shape_matched_random", "paired"):
        model = Continuation(dimension)
        if model_digest(model) != initial["model_digest"]:
            raise ValueError("unequal initialization")
        try:
            if method == "legacy":
                training = train_continuation(model, rows, cut, steps=steps)
            else:
                training = fit_paired(
                    model, rows, cut, steps=steps, revoked=revoked, sampling=method
                )
            after = inspect(model, opportunities, revoked=revoked)
            results[method] = dict(status="succeeded", training=training, after=after)
        except Exception as exc:
            results[method] = dict(
                status="failed",
                error_type=type(exc).__name__,
                error=str(exc)[:512],
                partial_training=getattr(model, "last_probe_failure", None),
                legacy_failure_cost_may_be_unavailable=method == "legacy",
            )
        if any(r.features.seal() != stamps[r.features.question_id] for r in rows):
            raise ValueError("training mutated shared features")
    paired = results["paired"]
    trained = (
        paired["status"] == "succeeded" and paired["training"]["status"] == "succeeded"
    )
    gain = (
        trained and paired["after"]["weak_support_hits"] > initial["weak_support_hits"]
    )
    random_control = results["shape_matched_random"]
    comparable = (
        trained
        and random_control["status"] == "succeeded"
        and random_control["training"]["status"] == "succeeded"
    )
    matched_work = (
        comparable
        and paired["training"]["costs"]["attempted_operations"]
        == random_control["training"]["costs"]["attempted_operations"]
    )
    if comparable and not matched_work:
        raise ValueError("paired/random neural-work census differs")
    paired_over_random = (
        comparable
        and paired["after"]["weak_support_hits"]
        > random_control["after"]["weak_support_hits"]
    )
    return dict(
        schema="hepta.system2.single-cell.train-opportunity.v1",
        rows=len(rows),
        cut_admission_digest=cut.admission_digest,
        disposition=disposition,
        disposition_digest=digest(disposition),
        initial=initial,
        methods=results,
        elapsed_seconds=time.perf_counter() - started,
        observed_training_decision_gain=bool(gain),
        next_gate=(
            "reader_controls_and_fresh_confirmation"
            if gain and paired_over_random and matched_work
            else "stop_no_gain_over_matched_random"
            if gain
            else "stop_no_train_decision_gain"
        ),
        same_update_ceiling=True,
        legacy_compute_matched=False,
        paired_random_neural_shapes_and_calls_matched=bool(matched_work),
        paired_over_random_training_decision_gain=bool(paired_over_random),
        matched_training_compute=False,
        matched_wall_time=False,
        evaluation="train-only diagnostic; not held-out policy selection",
        planned_reader_calls=0,
        actual_reader_calls=0,
        reader_adequacy_established=False,
        production_accepted=False,
        superiority_claim=False,
    )
