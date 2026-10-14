"""Train-only content-versus-cardinality intervention on existing Continuation.

Every fitted positive/negative pair has the SAME nonzero size and differs by
one candidate. A content-erased arm receives zero feature vectors of identical
shape, with the same labels, updates, and path order. It can learn cardinality
but cannot distinguish the members of a matched pair. No Reader, new Encoder,
FBSDE change, outcome authentication, or production admission is introduced.
"""

from collections import Counter
from dataclasses import dataclass
import math
from pathlib import Path
import json

import torch

from system2_ablation import Continuation, Limits, Meter, model_digest
from system2_learning_probe import prepare

METHODS = ("content", "content_erased")


@dataclass(frozen=True)
class ContentOpportunity:
    original: object
    pairs: tuple


def matched_opportunities(rows, cut, dimension, *, revoked=frozenset()):
    """All admission precedes labels, via existing prepare. Missing is not null."""
    items, _ = prepare(rows, cut, dimension, revoked=revoked)
    results, disposition = [], []
    for item in items:
        pairs = tuple(
            (p, n)
            for p in item.positive
            for n in item.negative
            if len(p) == len(n) and len(set(p) ^ set(n)) == 2
        )
        results.append(ContentOpportunity(item, pairs))
        disposition.append(
            dict(
                question_id=item.feature.question_id,
                family=item.feature.family,
                feature_digest=item.feature.seal(),
                matched_pairs=len(pairs),
                cardinalities=sorted({len(p) for p, _ in pairs}),
                eligible=bool(pairs),
                reason="same_size_one_replacement_weak_support_pair"
                if pairs
                else "no_same_size_hit_miss_pair_not_unanswerability",
            )
        )
    return tuple(results), disposition


def pair_at(pairs, visit):
    if not pairs or type(visit) is not int or visit < 0:
        raise ValueError("nonempty matched pairs and local visit required")
    sizes = sorted({len(p) for p, _ in pairs})
    size = sizes[visit % len(sizes)]
    group = [pair for pair in pairs if len(pair[0]) == size]
    return group[(visit // len(sizes)) % len(group)]


def _features(feature, path, method, meter):
    if method not in METHODS:
        raise ValueError("unregistered content intervention")
    meter.charge("critic_forward", 1)
    meter.charge("feature_pairs", len(path))
    x = feature.paired[list(path)]
    # No original values enter this intervention, at training OR inspection.
    return x if method == "content" else torch.zeros_like(x)


def _mean(values):
    return sum(values) / len(values) if values else None


@torch.no_grad()
def evaluate(model, opportunities, method, *, revoked=frozenset()):
    if model.quarantined or model.roots.intersection(revoked) or method not in METHODS:
        raise ValueError("unavailable content probe")
    before, meter, records = model_digest(model), Meter(Limits(seconds=300)), []
    for entry in opportunities:
        item, pairs = entry.original, entry.pairs
        f = item.feature
        f.validate(model.dimension)
        if f.roots.intersection(revoked) or model.encoder_identity not in (
            None,
            f.encoder_identity,
        ):
            raise ValueError("withdrawn or incompatible feature")
        scores = {}
        for path in item.paths:
            value = float(model(_features(f, path, method, meter)))
            if not math.isfinite(value):
                raise ValueError("nonfinite continuation score")
            scores[path] = value
        chosen = min(
            item.paths, key=lambda p: (-scores[p], tuple(f.candidate_ids[i] for i in p))
        )
        gaps = [scores[p] - scores[n] for p, n in pairs]
        frozen_gaps = [
            max(float(f.frozen_scores[i]) for i in p)
            - max(float(f.frozen_scores[i]) for i in n)
            for p, n in pairs
        ]

        def accuracy(values):
            return _mean([1.0 if v > 0 else 0.5 if v == 0 else 0.0 for v in values])

        records.append(
            dict(
                question_id=f.question_id,
                family=f.family,
                feature_digest=f.seal(),
                scores=[dict(path=list(p), value=v) for p, v in scores.items()],
                selected=list(chosen),
                empty=not chosen,
                weak_support_hit=chosen in item.positive,
                matched_pairs=len(pairs),
                matched_pair_accuracy=accuracy(gaps),
                frozen_max_score_accuracy=accuracy(frozen_gaps),
                mean_pair_margin=_mean(gaps),
                max_absolute_pair_margin=max(map(abs, gaps), default=None),
            )
        )
    if model_digest(model) != before:
        raise ValueError("inspection mutated continuation")
    eligible = [r for r in records if r["matched_pairs"]]
    families = sorted({r["family"] for r in eligible})
    return dict(
        records=records,
        model_digest=before,
        costs=meter.receipt(),
        planned_questions=len(records),
        eligible_questions=len(eligible),
        eligible_families=len(families),
        matched_pair_question_macro=_mean(
            [r["matched_pair_accuracy"] for r in eligible]
        ),
        frozen_max_score_question_macro=_mean(
            [r["frozen_max_score_accuracy"] for r in eligible]
        ),
        matched_pair_family_macro=_mean(
            [
                _mean(
                    [r["matched_pair_accuracy"] for r in eligible if r["family"] == fam]
                )
                for fam in families
            ]
        ),
        empty_choices=sum(r["empty"] for r in records),
        weak_support_hits=sum(r["weak_support_hit"] for r in records),
        ties_receive_half_credit=True,
        paired_comparisons_are_not_independent_samples=True,
        is_task_accuracy=False,
    )


@torch.enable_grad()
def fit(
    model,
    rows,
    cut,
    *,
    method="content",
    steps=96,
    operation_ceiling=100000,
    revoked=frozenset(),
):
    if (
        method not in METHODS
        or type(steps) is not int
        or not 1 <= steps <= 2048
        or torch.is_inference_mode_enabled()
        or model.quarantined
        or model.roots.intersection(cut.forbidden_roots | revoked)
    ):
        raise ValueError("invalid content session")
    all_items, disposition = matched_opportunities(
        rows, cut, model.dimension, revoked=revoked
    )
    if model.encoder_identity not in (None, rows[0].features.encoder_identity):
        raise ValueError("continuation lineage drift")
    eligible = tuple(e for e in all_items if e.pairs)
    if not eligible:
        return dict(
            status="unavailable",
            updates=0,
            disposition=disposition,
            reason="no_same_cardinality_contrast",
            costs=None,
            records=[],
        )
    before = model_digest(model)
    meter, visits, records = (
        Meter(Limits(operations=operation_ceiling, seconds=300)),
        Counter(),
        [],
    )
    optimizer = torch.optim.SGD(model.parameters(), lr=0.03)
    try:
        for step in range(steps):
            entry = eligible[step % len(eligible)]
            f = entry.original.feature
            positive, negative = pair_at(entry.pairs, visits[f.question_id])
            # Counterbalance pair presentation within each question.
            paths, targets = (positive, negative), (1.0, 0.0)
            if visits[f.question_id] % 2:
                paths, targets = paths[::-1], targets[::-1]
            event = dict(
                step=step,
                question_id=f.question_id,
                feature_digest=f.seal(),
                paths=[list(p) for p in paths],
                targets=list(targets),
                status="started",
            )
            records.append(event)
            predictions = [model(_features(f, p, method, meter)) for p in paths]
            loss = (
                sum(
                    torch.nn.functional.binary_cross_entropy(v, v.new_tensor(t))
                    for v, t in zip(predictions, targets, strict=True)
                )
                / 2
            )
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                model.parameters(), 1.0, error_if_nonfinite=True
            )
            meter.charge("optimizer_updates", 1)
            optimizer.step()
            if not all(torch.isfinite(p).all() for p in model.parameters()):
                raise ValueError("nonfinite updated parameter")
            visits[f.question_id] += 1
            event.update(
                status="completed",
                predictions=[float(v.detach()) for v in predictions],
                loss=float(loss.detach()),
            )
    except Exception as exc:
        model.quarantined = True
        model.last_content_failure = dict(
            records=records,
            costs=meter.receipt(),
            before=before,
            completed_updates=sum(r["status"] == "completed" for r in records),
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
        method=method,
        visits=dict(visits),
        records=records,
        costs=meter.receipt(),
        supervision="any_native_source_hit_not_joint_sufficiency",
    )


def gate(initial, results):
    """A training observation can request confirmation, never authorize deployment."""
    if any(results.get(m, {}).get("status") != "succeeded" for m in METHODS):
        return "stop_incomplete_or_no_matched_opportunity"
    content = results["content"]["after"]
    erased = results["content_erased"]["after"]
    value = content["matched_pair_question_macro"]
    refs = (
        initial["content"]["matched_pair_question_macro"],
        erased["matched_pair_question_macro"],
        content["frozen_max_score_question_macro"],
    )
    if (
        value is None
        or any(r is None for r in refs)
        or not all(value > r for r in refs)
    ):
        return "stop_no_content_gain_over_all_train_controls"
    if content["weak_support_hits"] <= initial["content"]["weak_support_hits"]:
        return "stop_no_free_choice_training_gain"
    return "fresh_confirmation_and_reader_controls_required"


def _write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(
            value, stream, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2
        )
        stream.write("\n")


def _save_model(model, path):
    from safetensors.torch import load_file, save_file

    tensors = {k: v.detach().cpu().contiguous() for k, v in model.state_dict().items()}
    save_file(tensors, str(path))
    restored = Continuation(model.dimension, hidden=model.hidden)
    restored.load_state_dict(load_file(str(path)), strict=True)
    if model_digest(restored) != model_digest(model):
        raise ValueError("saved model reload parity failed")
    return dict(
        model_digest=model_digest(model),
        encoder_identity=model.encoder_identity,
        roots=sorted(model.roots),
        hidden=model.hidden,
        dimension=model.dimension,
        reload_tensor_parity=True,
        production_accepted=False,
    )


def run_content_probe(
    rows, cut, dimension, *, steps=96, output=None, revoked=frozenset()
):
    """No new model selection on test annotations; artifacts enable exact replay."""
    opportunities, disposition = matched_opportunities(
        rows, cut, dimension, revoked=revoked
    )
    stamps = {r.features.question_id: r.features.seal() for r in rows}
    if output is not None:
        output = Path(output)
        output.mkdir(exist_ok=False)
        from safetensors.torch import load_file, save_file

        tensors, metadata = {}, []
        for index, row in enumerate(rows):
            f = row.features
            tensors[f"f{index}.paired"] = f.paired.detach().cpu().contiguous()
            tensors[f"f{index}.frozen_scores"] = (
                f.frozen_scores.detach().cpu().contiguous()
            )
            metadata.append(
                dict(
                    question_id=f.question_id,
                    family=f.family,
                    roots=sorted(f.roots),
                    encoder_identity=f.encoder_identity,
                    pool_digest=f.pool_digest,
                    candidate_ids=list(f.candidate_ids),
                    feature_digest=f.seal(),
                    positive_indices=list(row.positive_indices),
                    tensor_prefix=f"f{index}",
                )
            )
        save_file(tensors, str(output / "train-features.safetensors"))
        restored = load_file(str(output / "train-features.safetensors"))
        if set(restored) != set(tensors) or any(
            not torch.equal(restored[k], t) for k, t in tensors.items()
        ):
            raise ValueError("train feature export mismatch")
        _write(
            output / "train-inputs.json",
            dict(
                rows=metadata,
                dimension=dimension,
                admission_digest=cut.admission_digest,
                allowed_questions=sorted(cut.question_ids),
                allowed_families=sorted(cut.families),
                allowed_roots=sorted(cut.allowed_roots),
                forbidden_roots=sorted(cut.forbidden_roots),
                test_labels_present=False,
            ),
        )
    initial, results, snapshots = {}, {}, {}
    for method in METHODS:
        model = Continuation(dimension)
        initial[method] = evaluate(model, opportunities, method, revoked=revoked)
        try:
            training = fit(
                model, rows, cut, method=method, steps=steps, revoked=revoked
            )
            after = evaluate(model, opportunities, method, revoked=revoked)
            results[method] = dict(
                status=training["status"], training=training, after=after
            )
            if training["status"] == "succeeded" and output is not None:
                snapshots[method] = _save_model(model, output / f"{method}.safetensors")
        except Exception as exc:
            results[method] = dict(
                status="failed",
                error_type=type(exc).__name__,
                error=str(exc)[:512],
                partial_training=getattr(model, "last_content_failure", None),
            )
        if any(r.features.seal() != stamps[r.features.question_id] for r in rows):
            raise ValueError("content intervention mutated shared features")
    if initial["content"]["model_digest"] != initial["content_erased"]["model_digest"]:
        raise ValueError("initialization mismatch")
    complete = all(results[m]["status"] == "succeeded" for m in METHODS)
    if complete:
        a, b = [results[m]["training"] for m in METHODS]
        if a["costs"]["attempted_operations"] != b["costs"]["attempted_operations"] or [
            (r["question_id"], r["paths"], r["targets"]) for r in a["records"]
        ] != [(r["question_id"], r["paths"], r["targets"]) for r in b["records"]]:
            raise ValueError("paired content controls have unmatched work or labels")
        for r in results["content_erased"]["after"]["records"]:
            if r["matched_pairs"] and r["max_absolute_pair_margin"] != 0:
                raise ValueError("erased control acquired content information")
    report = dict(
        schema="hepta.system2.content-cardinality-probe.v1",
        disposition=disposition,
        rows=len(rows),
        initial=initial,
        methods=results,
        snapshots=snapshots,
        paired_shapes_calls_updates_matched=complete,
        measured_wall_time_matched=False,
        next_gate=gate(initial, results),
        train_only=True,
        actual_reader_calls=0,
        reader_adequacy_established=False,
        superiority_claim=False,
        production_accepted=False,
    )
    if output is not None:
        _write(output / "report.json", report)
    return report
