"""Existing linear StemHead: isolate optimization, score origin and transfer.

Cached native TRAIN features only. This is an exploratory refit after inspecting
prior results, not untouched confirmation, calibrated utility or production.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time

import torch
from safetensors.torch import load_file, save_file

from selector_head import TrainingCut
from stem_cell import StemHead
from system2_ablation import digest, model_digest
from system2_content_replay import ARCHIVE, SOURCE, audit_content
from system2_learning_probe import prepare

METHODS = ("frozen", "sgd", "ridge", "ridge_erased")
RIDGE = 0.01
STEPS = 96
RATE = 0.03


def design(rows, cut, *, revoked=frozenset()):
    if not 1 <= len(rows) <= 256:
        raise ValueError("bounded nonempty training rows required")
    items, _ = prepare(rows, cut, rows[0].features.paired.shape[1], revoked=revoked)
    diffs, targets, weights, identities = [], [], [], []
    eligible = 0
    for item in items:
        f = item.feature
        pos = [p[0] for p in item.positive if len(p) == 1]
        neg = [p[0] for p in item.negative if len(p) == 1]
        pairs = [(i, j) for i in pos for j in neg]
        eligible += bool(pairs)
        for i, j in pairs:
            diffs.append((f.paired[i] - f.paired[j]).double())
            targets.append(1.0 - float(f.frozen_scores[i]) + float(f.frozen_scores[j]))
            weights.append(1.0 / len(pairs))
            identities.append([f.question_id, f.seal(), i, j])
    if not diffs:
        raise ValueError(
            "no singleton source-hit/miss opportunity; not unanswerability"
        )
    weight = torch.tensor(weights, dtype=torch.float64).div(eligible).sqrt()
    a = torch.stack(diffs) * weight[:, None]
    b = torch.tensor(targets, dtype=torch.float64) * weight
    if not torch.isfinite(a).all() or not torch.isfinite(b).all():
        raise ValueError("nonfinite contrast design")
    return a, b, identities


def fit_head(rows, cut, method, *, revoked=frozenset()):
    if method not in METHODS or torch.is_inference_mode_enabled():
        raise ValueError("unregistered solver or inference-mode training")
    started = time.perf_counter()
    a, b, identities = design(rows, cut, revoked=revoked)
    if method == "ridge_erased":
        a = torch.zeros_like(a)
    dimension = a.shape[1]
    head = StemHead(dimension, rows[0].features.encoder_identity, kind="linear")
    # Ranking pairs cannot identify a null threshold or common intercept.
    head.null.requires_grad_(False)
    head.readout.bias.requires_grad_(False)
    before = model_digest(head)
    w = torch.zeros(dimension, dtype=torch.float64)
    losses = []
    try:
        if method.startswith("ridge"):
            # Dual solve avoids factoring a d-by-d matrix when n << d.
            w = a.T @ torch.linalg.solve(
                a @ a.T + RIDGE * torch.eye(len(a), dtype=a.dtype), b
            )
        elif method == "sgd":
            for _ in range(STEPS):
                residual = a @ w - b
                losses.append(float(residual.square().sum() + RIDGE * w.square().sum()))
                w -= RATE * (2 * a.T @ residual + 2 * RIDGE * w)
        if not torch.isfinite(w).all():
            raise ValueError("nonfinite fitted readout")
        with torch.no_grad():
            head.readout.weight.copy_(w.float().reshape(1, -1))
        if not torch.isfinite(head.readout.weight).all():
            raise ValueError("fitted readout exceeds storage precision")
        head.roots = (
            set().union(*(r.features.roots for r in rows))
            if method != "frozen"
            else set()
        )
        after = head.readout.weight.detach().double().flatten()
        normal = a.T @ (a @ w - b) + RIDGE * w
        if method.startswith("ridge") and float(normal.norm()) > 1e-8 * (
            1 + float((a.T @ b).norm())
        ):
            raise ValueError("ridge normal-equation residual")
    except Exception:
        head.quarantined = True
        raise
    return head, dict(
        method=method,
        before=before,
        after=model_digest(head),
        parameters_total=sum(p.numel() for p in head.parameters()),
        adaptable_parameters=dimension,
        parameters_changed=model_digest(head) != before,
        training_questions=len(rows),
        contrast_rows=len(a),
        design_digest=digest(identities),
        actual_sgd_updates=STEPS if method == "sgd" else 0,
        direct_solves=int(method.startswith("ridge")),
        factored_dimension=len(a) if method.startswith("ridge") else 0,
        objective=float((a @ w - b).square().sum() + RIDGE * w.square().sum()),
        normal_equation_residual=float(normal.norm()),
        stored_fp32_objective=float(
            (a @ after - b).square().sum() + RIDGE * after.square().sum()
        ),
        losses=losses,
        elapsed_seconds=time.perf_counter() - started,
        frozen_null_and_bias=True,
        is_calibrated_utility=False,
    )


@torch.no_grad()
def inspect_head(head, rows, *, revoked=frozenset()):
    """Raw vs centered use SAME weights/ranking; no labels choose an origin."""
    if head.quarantined or head.roots.intersection(revoked):
        raise ValueError("withdrawn fitted head")
    before = model_digest(head)
    records = []
    for row in rows:
        f = row.features
        f.validate(head.dimension)
        if f.roots.intersection(revoked):
            raise ValueError("withdrawn inference features")
        proposal = sorted(
            range(len(f.candidate_ids)),
            key=lambda i: (-float(f.frozen_scores[i]), f.candidate_ids[i]),
        )[:4]
        logits = head(f)[:-1].double()
        if not torch.isfinite(logits).all():
            raise ValueError("nonfinite readout logits")
        # Center ONLY the learned residual, not the native evidence logits.
        residual = logits - f.frozen_scores.double()
        offset = float(residual[proposal].mean()) if proposal else 0.0
        centered = logits - offset
        best = (
            min(proposal, key=lambda i: (-float(logits[i]), f.candidate_ids[i]))
            if proposal
            else None
        )
        if (
            proposal
            and min(proposal, key=lambda i: (-float(centered[i]), f.candidate_ids[i]))
            != best
        ):
            raise ValueError("origin convention changed ranking")
        pos = [i for i in proposal if i in row.positive_indices]
        neg = [i for i in proposal if i not in row.positive_indices]
        gaps = [float(logits[i] - logits[j]) for i in pos for j in neg]
        hits = sum(1.0 if gap > 0 else 0.5 if gap == 0 else 0.0 for gap in gaps)
        item = dict(
            question_id=f.question_id,
            family=f.family,
            feature_digest=f.seal(),
            proposal=proposal,
            best=best,
            residual_mean=offset,
            singleton_pairs=len(gaps),
            pair_accuracy=hits / len(gaps) if gaps else None,
        )
        for mode, scores in (("raw", logits), ("centered", centered)):
            empty = best is None or float(scores[best]) <= 0
            item[mode] = dict(
                empty=empty,
                selected=None if empty else best,
                hit=not empty and best in row.positive_indices,
                best_score=None if best is None else float(scores[best]),
            )
        records.append(item)
    if before != model_digest(head):
        raise ValueError("evaluation mutated head")
    return records


def aggregate(records):
    if not records or len({r["question_id"] for r in records}) != len(records):
        raise ValueError("incomplete or duplicated evaluation question census")
    eligible = [r for r in records if r["pair_accuracy"] is not None]
    families = sorted({r["family"] for r in records})
    mean = lambda xs: sum(xs) / len(xs) if xs else None
    return dict(
        questions=len(records),
        families=len(families),
        eligible_questions=len(eligible),
        singleton_pair_question_macro=mean([r["pair_accuracy"] for r in eligible]),
        singleton_pair_family_macro=mean(
            [
                mean([r["pair_accuracy"] for r in eligible if r["family"] == fam])
                for fam in families
                if any(r["family"] == fam for r in eligible)
            ]
        ),
        modes={
            mode: dict(
                hits=sum(r[mode]["hit"] for r in records),
                empty=sum(r[mode]["empty"] for r in records),
                family_macro_hit_rate=mean(
                    [
                        mean(
                            [int(r[mode]["hit"]) for r in records if r["family"] == fam]
                        )
                        for fam in families
                    ]
                ),
            )
            for mode in ("raw", "centered")
        },
        no_opportunity_questions=len(records) - len(eligible),
        is_reader_accuracy=False,
    )


def family_split(rows, original, family):
    train = tuple(r for r in rows if r.features.family != family)
    test = tuple(r for r in rows if r.features.family == family)
    if not train or not test:
        raise ValueError("empty family partition")
    train_roots = frozenset(root for r in train for root in r.features.roots)
    test_roots = frozenset(root for r in test for root in r.features.roots)
    if train_roots & test_roots:
        raise ValueError("family names hide shared training/evaluation roots")
    cut = TrainingCut(
        frozenset(r.features.question_id for r in train),
        frozenset(r.features.family for r in train),
        train_roots,
        original.forbidden_roots | test_roots,
        digest((original.admission_digest, "leave-family-out", family)),
    )
    return train, test, cut


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def run(archive, output, *, source_commit, execution_context="full-repository-source"):
    if not re.fullmatch("[0-9a-f]{40}", source_commit or ""):
        raise ValueError("exact executing source required")
    output.mkdir(exist_ok=False)
    source_files = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__), Path(__file__).with_name("system2_content_replay.py"))
    }
    write(
        output / "plan.json",
        dict(
            source_commit=source_commit,
            archived_source=SOURCE,
            execution_context=execution_context,
            executing_source_files=source_files,
            artifact_sha256=ARCHIVE,
            methods=METHODS,
            ridge=RIDGE,
            rate=RATE,
            steps=STEPS,
            target_margin=1.0,
            proposal_limit=4,
            capacity_cuts=[16, 32, 48],
            validation="leave-one-source-family-out on previously exposed TRAIN data",
            origin_interventions=["raw", "per-query-zero-mean-learned-residual"],
            null_threshold=0.0,
            null_calibrated=False,
            no_hyperparameter_search=True,
            new_encoder_calls=0,
            new_reader_calls=0,
            production_accepted=False,
        ),
    )
    datasets, audit = audit_content(archive)
    write(output / "original-content-audit.json", audit)
    rows, original = datasets[48]
    tasks = [
        ("capacity-" + str(k), data, data, cut) for k, (data, cut) in datasets.items()
    ]
    for family in sorted({r.features.family for r in rows}):
        train, test, cut = family_split(rows, original, family)
        tasks.append(("fold-" + family.replace(":", "-"), train, test, cut))
    results, failed = [], False
    for name, train, test, cut in tasks:
        stamps = {r.features.question_id: r.features.seal() for r in (*train, *test)}
        for method in METHODS:
            record = dict(
                task=name,
                method=method,
                train_ids=[r.features.question_id for r in train],
                evaluation_ids=[r.features.question_id for r in test],
            )
            started = time.perf_counter()
            try:
                model, receipt = fit_head(train, cut, method)
                # Freeze the fitted weights BEFORE evaluation source labels are consumed.
                saved = output / f"{name}-{method}.safetensors"
                save_file(
                    {k: v.detach().contiguous() for k, v in model.state_dict().items()},
                    str(saved),
                )
                clone = StemHead(model.dimension, model.encoder_identity, kind="linear")
                clone.load_state_dict(load_file(str(saved)), strict=True)
                if model_digest(clone) != model_digest(model):
                    raise ValueError("parameter-only reload mismatch")
                record.update(
                    status="succeeded", fit=receipt, records=inspect_head(model, test)
                )
                record["summary"] = aggregate(record["records"])
                record["fitted_roots"] = sorted(model.roots)
            except Exception as exc:
                failed = True
                record.update(
                    status="failed", error_type=type(exc).__name__, error=str(exc)[:512]
                )
            record["elapsed_seconds"] = time.perf_counter() - started
            if any(
                r.features.seal() != stamps[r.features.question_id]
                for r in (*train, *test)
            ):
                raise ValueError("shared features were mutated")
            write(output / f"{name}-{method}.json", record)
            results.append(record)
    cross = {}
    for method in METHODS:
        group = [
            r
            for r in results
            if r["task"].startswith("fold-") and r["method"] == method
        ]
        cross[method] = (
            aggregate([p for r in group for p in r["records"]])
            if all(r["status"] == "succeeded" for r in group)
            else None
        )
    frozen, candidate = cross["frozen"], cross["ridge"]
    gain = (
        frozen is not None
        and candidate is not None
        and candidate["modes"]["centered"]["hits"] > frozen["modes"]["centered"]["hits"]
        and candidate["modes"]["centered"]["family_macro_hit_rate"]
        > frozen["modes"]["centered"]["family_macro_hit_rate"]
    )
    write(
        output / "summary.json",
        dict(
            source_commit=source_commit,
            execution_context=execution_context,
            executing_source_files=source_files,
            candidate_disposition="fresh_confirmation_and_reader_controls_required"
            if gain
            else "stop_no_cross_family_source_gain",
            raw_and_centered_use_identical_fitted_weights=True,
            origin_convention_is_exploratory_not_preregistered_confirmation=True,
            results=[
                {k: r[k] for k in ("task", "method", "status", "summary") if k in r}
                for r in results
            ],
            planned_fit_conditions=len(tasks) * len(METHODS),
            recorded=len(results),
            failed=failed,
            cross_family_exploratory=cross,
            independent_confirmation=False,
            ranking_objective_is_not_null_calibration=True,
            lineage_acceptance_not_authenticated_here=True,
            new_encoder_calls=0,
            new_reader_calls=0,
            reasoning_superiority=False,
            production_accepted=False,
        ),
    )
    if failed:
        raise RuntimeError(
            "failed fit conditions retained; not a reduced success census"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(
        args.archive,
        args.output,
        source_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", ""),
    )
