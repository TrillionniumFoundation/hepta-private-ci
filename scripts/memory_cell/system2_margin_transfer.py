"""One-sided margin refit and independent frozen-stop diagnostic.

Existing native TRAIN features and StemHead only. Squared hinge does not punish
an already sufficient margin, but does NOT guarantee retention on other pairs.
Frozen-stop is a control, not a learned probability or NDU continuation value.
"""

import argparse
import hashlib
import math
import os
from pathlib import Path
import re
import time

import torch
from safetensors.torch import load_file, save_file

from stem_cell import StemHead
from system2_ablation import model_digest
from system2_content_replay import ARCHIVE, audit_content
from system2_linear_solver import (
    RIDGE,
    aggregate,
    design,
    family_split,
    fit_head,
    inspect_head,
    write,
)

METHODS = ("frozen", "ridge", "squared_hinge", "hinge_erased")
MODES = ("raw", "centered", "frozen_stop")
PROTOCOL = dict(
    schema="hepta.system2.one-sided-margin.v1",
    methods=METHODS,
    ridge=RIDGE,
    target_margin=1.0,
    capacity_cuts=[16, 32, 48],
    proposal_limit=4,
    qp_max_solves=256,
    qp_tolerance=1e-10,
    modes=MODES,
    hypothesis="equality loss may unnecessarily shrink sufficient frozen margins",
    validation="leave-one-family-out refits of previously exposed TRAIN data",
    no_hyperparameter_search=True,
    new_encoder_calls=0,
    new_reader_calls=0,
    calibrated_stop=False,
    calibrated_ndu_utility=False,
    production_accepted=False,
)


def solve_hinge(a, b, *, ridge=RIDGE, max_solves=256):
    """min ||relu(b-Aw)||^2 + ridge*||w||^2 via nonnegative dual QP.

    w=A.T@alpha; H=A@A.T+ridge*I. Dual KKT: alpha>=0, H@alpha-b>=0,
    alpha*(H@alpha-b)=0. Counts include failed factorization attempts.
    A fixed active-set budget rejects nonconvergence; no damping theorem claimed.
    """
    if (
        a.ndim != 2
        or not 1 <= len(a) <= 1024
        or not 1 <= a.shape[1] <= 1024
        or b.shape != (len(a),)
        or a.dtype != torch.float64
        or b.dtype != a.dtype
        or a.device.type != "cpu"
        or b.device.type != "cpu"
        or a.requires_grad
        or b.requires_grad
        or not torch.isfinite(a).all()
        or not torch.isfinite(b).all()
        or type(ridge) not in (int, float)
        or not math.isfinite(ridge)
        or ridge <= 0
        or type(max_solves) is not int
        or not 1 <= max_solves <= 1024
    ):
        raise ValueError("bounded finite detached CPU double design required")
    h = a @ a.T + ridge * torch.eye(len(a), dtype=a.dtype)
    if not torch.isfinite(h).all():
        raise ValueError("nonfinite dual matrix")
    alpha = torch.zeros_like(b)
    passive = torch.zeros(len(a), dtype=torch.bool)
    tolerance = PROTOCOL["qp_tolerance"] * (1 + float(b.norm()))
    solves, dimensions = 0, []
    while True:
        gradient = h @ alpha - b
        violations = (~passive) & (gradient < -tolerance)
        if not violations.any():
            break
        indices = torch.where(violations)[0]
        passive[indices[torch.argmin(gradient[indices])]] = True
        while True:
            if solves >= max_solves:
                raise RuntimeError(f"active-set budget exhausted after {solves} solves")
            indices = torch.where(passive)[0]
            trial = torch.zeros_like(alpha)
            solves += 1
            dimensions.append(len(indices))
            trial[indices] = torch.linalg.solve(h[indices][:, indices], b[indices])
            if not torch.isfinite(trial).all():
                raise ValueError("nonfinite active-set solve")
            if (trial[indices] > 0).all():
                alpha = trial
                break
            nonpositive = indices[trial[indices] <= 0]
            ratios = alpha[nonpositive] / (alpha[nonpositive] - trial[nonpositive])
            if not torch.isfinite(ratios).all():
                raise ValueError("degenerate active-set step")
            step = float(ratios.min())
            alpha += step * (trial - alpha)
            # Drop the limiting constraints, not every small positive coefficient.
            dropped = nonpositive[ratios <= step + 1e-14]
            alpha[dropped] = 0
            passive[dropped] = False
    w = a.T @ alpha
    gradient = h @ alpha - b
    stationarity = ridge * w - a.T @ torch.relu(b - a @ w)
    scale = 1 + float((a.T @ b).norm())
    kkt = max(
        float(torch.relu(-alpha).max()),
        float(torch.relu(-gradient).max()),
        float((alpha * gradient).abs().max()),
    )
    if (
        not torch.isfinite(w).all()
        or kkt > 1e-7 * (1 + float(b.norm()))
        or float(stationarity.norm()) > 1e-8 * scale
    ):
        raise RuntimeError("squared-hinge KKT/stationarity residual failed")
    return w, dict(
        direct_solves=solves,
        factorization_dimensions=dimensions,
        active_constraints=int((alpha > 0).sum()),
        dual_kkt_residual=kkt,
        stationarity_residual=float(stationarity.norm()),
        objective=float(
            torch.relu(b - a @ w).square().sum() + ridge * w.square().sum()
        ),
        frozen_already_sufficient_contrasts=int((b <= 0).sum()),
    )


def fit_margin(rows, cut, method, *, revoked=frozenset()):
    if method not in METHODS or torch.is_inference_mode_enabled():
        raise ValueError("unregistered margin condition")
    if method in ("frozen", "ridge"):
        return fit_head(rows, cut, method, revoked=revoked)
    started = time.perf_counter()
    a, b, identities = design(rows, cut, revoked=revoked)
    if method == "hinge_erased":
        a = torch.zeros_like(a)
    head = StemHead(a.shape[1], rows[0].features.encoder_identity, kind="linear")
    head.null.requires_grad_(False)
    head.readout.bias.requires_grad_(False)
    before = model_digest(head)
    try:
        w, receipt = solve_hinge(a, b)
        with torch.no_grad():
            head.readout.weight.copy_(w.float().reshape(1, -1))
        if not torch.isfinite(head.readout.weight).all():
            raise ValueError("nonfinite FP32 storage")
        stored = head.readout.weight.detach().double().flatten()
        receipt["stored_fp32_stationarity"] = float(
            (RIDGE * stored - a.T @ torch.relu(b - a @ stored)).norm()
        )
        head.roots = set().union(*(r.features.roots for r in rows))
    except Exception:
        head.quarantined = True
        raise
    receipt.update(
        method=method,
        before=before,
        after=model_digest(head),
        training_ids=[r.features.question_id for r in rows],
        design_rows=identities,
        trainable_parameters=sum(
            p.numel() for p in head.parameters() if p.requires_grad
        ),
        total_parameters=sum(p.numel() for p in head.parameters()),
        elapsed_seconds=time.perf_counter() - started,
        labels="weak-native-source-membership",
    )
    return head, receipt


def observe(head, rows, *, revoked=frozenset()):
    """Freeze before labels are evaluated; fixed stop depends only on native scores."""
    records = inspect_head(head, rows, revoked=revoked)
    for record, row in zip(records, rows, strict=True):
        f = row.features
        proposal, best = record["proposal"], record["best"]
        native_max = max((float(f.frozen_scores[i]) for i in proposal), default=None)
        empty = native_max is None or native_max <= 0
        record["frozen_stop"] = dict(
            empty=empty,
            selected=None if empty else best,
            hit=not empty and best in row.positive_indices,
            stop_score=native_max,
        )
        record["ranking_hit_ignoring_stop"] = (
            best in row.positive_indices if best is not None else False
        )
    return records


def summarize(records):
    summary = aggregate(records)
    families = sorted({r["family"] for r in records})
    summary["modes"]["frozen_stop"] = dict(
        hits=sum(r["frozen_stop"]["hit"] for r in records),
        empty=sum(r["frozen_stop"]["empty"] for r in records),
        family_macro_hit_rate=sum(
            sum(r["frozen_stop"]["hit"] for r in records if r["family"] == fam)
            / sum(r["family"] == fam for r in records)
            for fam in families
        )
        / len(families),
    )
    summary["ranking_hits_ignoring_stop"] = sum(
        r["ranking_hit_ignoring_stop"] for r in records
    )
    return summary


def paired_changes(baseline, candidate, mode):
    left = {r["question_id"]: r for r in baseline}
    right = {r["question_id"]: r for r in candidate}
    if (
        mode not in MODES
        or len(left) != len(baseline)
        or len(right) != len(candidate)
        or not left
        or set(left) != set(right)
    ):
        raise ValueError("paired census mismatch")
    wins, losses, changed, families = 0, 0, 0, {}
    for qid, old in left.items():
        new = right[qid]
        if (old["family"], old["feature_digest"]) != (
            new["family"],
            new["feature_digest"],
        ):
            raise ValueError("paired provenance mismatch")
        delta = int(new[mode]["hit"]) - int(old[mode]["hit"])
        wins += delta > 0
        losses += delta < 0
        changed += new[mode]["selected"] != old[mode]["selected"]
        families.setdefault(old["family"], []).append(delta)
    return dict(
        questions=len(left),
        wins=wins,
        losses=losses,
        changed_choices=changed,
        family_mean_deltas={f: sum(v) / len(v) for f, v in families.items()},
        observed_no_source_regression=losses == 0,
        independent_significance=False,
    )


def run(archive, output, *, source_commit, execution_context="full-repository-source"):
    if not re.fullmatch("[0-9a-f]{40}", source_commit or ""):
        raise ValueError("exact source or declared source-overlay parent required")
    output.mkdir(exist_ok=False)
    # Fixed before loading training labels or computing any candidate result.
    paths = [Path(__file__), Path(__file__).with_name("system2_linear_solver.py")]
    plan = PROTOCOL | dict(
        source_commit=source_commit,
        execution_context=execution_context,
        executing_files={
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths
        },
        archive_sha256=ARCHIVE,
        same_data_as_prior_exploration=True,
        primary_mode="frozen_stop",
        record_all_other_modes_without_posthoc_selection=True,
    )
    write(output / "plan.json", plan)
    datasets, audit = audit_content(archive)
    write(output / "content-audit.json", audit)
    rows, original = datasets[48]
    tasks = [
        (f"capacity-{k}", train, train, cut) for k, (train, cut) in datasets.items()
    ]
    for family in sorted({r.features.family for r in rows}):
        train, test, cut = family_split(rows, original, family)
        tasks.append(("fold-" + family.replace(":", "-"), train, test, cut))
    results = []
    for task, train, test, cut in tasks:
        stamps = {r.features.question_id: r.features.seal() for r in (*train, *test)}
        for method in METHODS:
            started = time.perf_counter()
            record = dict(
                task=task,
                method=method,
                train_ids=[r.features.question_id for r in train],
                evaluation_ids=[r.features.question_id for r in test],
            )
            try:
                head, receipt = fit_margin(train, cut, method)
                head.requires_grad_(False)
                saved = output / f"{task}-{method}.safetensors"
                save_file(
                    {k: v.detach().contiguous() for k, v in head.state_dict().items()},
                    str(saved),
                )
                clone = StemHead(head.dimension, head.encoder_identity, kind="linear")
                clone.load_state_dict(load_file(str(saved)), strict=True)
                if model_digest(head) != model_digest(clone):
                    raise ValueError("fitted tensor reload mismatch")
                observed = observe(head, test)
                record.update(
                    status="succeeded",
                    fit=receipt,
                    fitted_roots=sorted(head.roots),
                    model_digest=model_digest(head),
                    records=observed,
                    summary=summarize(observed),
                )
            except Exception as exc:
                record.update(
                    status="failed", error_type=type(exc).__name__, error=str(exc)[:512]
                )
            record["elapsed_seconds"] = time.perf_counter() - started
            if any(
                r.features.seal() != stamps[r.features.question_id]
                for r in (*train, *test)
            ):
                record.update(status="failed", error="mutated shared features")
            write(output / f"{task}-{method}.json", record)
            results.append(record)
    expected = {(t[0], m) for t in tasks for m in METHODS}
    if (
        len(results) != len(expected)
        or {(r["task"], r["method"]) for r in results} != expected
    ):
        raise ValueError("incomplete fit-condition census")
    folds = {
        m: [r for r in results if r["method"] == m and r["task"].startswith("fold-")]
        for m in METHODS
    }
    cross, contrasts = {}, {}
    for method, group in folds.items():
        cross[method] = (
            summarize([x for r in group for x in r["records"]])
            if all(r["status"] == "succeeded" for r in group)
            else None
        )
    for method in METHODS[1:]:
        if cross["frozen"] is not None and cross[method] is not None:
            contrasts[method] = {
                mode: paired_changes(
                    [x for r in folds["frozen"] for x in r["records"]],
                    [x for r in folds[method] for x in r["records"]],
                    mode,
                )
                for mode in MODES
            }
    primary = contrasts.get("squared_hinge", {}).get("frozen_stop")
    failed = sum(r["status"] == "failed" for r in results)
    gain = bool(
        not failed
        and primary
        and primary["wins"] > 0
        and primary["losses"] == 0
        and all(v >= 0 for v in primary["family_mean_deltas"].values())
    )
    report = plan | dict(
        planned=len(expected),
        recorded=len(results),
        failed=failed,
        cross_family=cross,
        contrasts=contrasts,
        candidate_disposition="fresh_confirmation_and_reader_controls_required"
        if gain
        else "stop_no_nonregressing_cross_family_gain",
        fit_seconds_including_failures=sum(r["elapsed_seconds"] for r in results),
        exact_compute_matched=False,
        summary_results=[
            {k: r[k] for k in ("task", "method", "status", "summary") if k in r}
            for r in results
        ],
        independent_confirmation=False,
        reader_adequacy_established=False,
        reasoning_superiority=False,
    )
    write(output / "summary.json", report)
    if failed:
        raise RuntimeError("failed fit conditions retained; no smaller success census")
    return report


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
