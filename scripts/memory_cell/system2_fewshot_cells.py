"""Cached-native episodic Cell differentiation, not independent confirmation.

Prior: all OTHER source families. Local delta: exactly K label-free-selected
support questions in the target family. The final query shares a source root
with local support by design; old root-disjoint experiments remain unchanged.
Only source-membership targets exist, not task/stop/FBSDE-utility supervision.
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
from system2_content_replay import ARCHIVE, audit_content
from system2_learning_probe import prepare
from system2_linear_solver import RIDGE, design, family_split, write
from system2_margin_transfer import fit_margin, solve_hinge

METHODS = (
    "frozen",
    "shared",
    "local_only",
    "differentiated",
    "erased_update",
    "neighbor",
)
BUDGETS = (1, 2)
PROTOCOL = dict(
    schema="hepta.system2.fewshot-local-delta.v1",
    methods=METHODS,
    support_budgets=BUDGETS,
    primary_budget=2,
    ridge=RIDGE,
    margin=1.0,
    proposal=4,
    support_order="sha256-canonical-question-id; never filtered by support labels",
    stop="frozen-native-max>0; not calibrated",
    shared_root_personalization=True,
    evaluation="same exposed TRAIN cohort; question-disjoint local adaptation, NOT root-disjoint",
    independent_confirmation=False,
    new_encoder_calls=0,
    new_reader_calls=0,
    reader_adequacy_established=False,
    calibrated_ndu_utility=False,
    production_accepted=False,
)


def episodes(features):
    """Features only: no Supervision or target access at split selection."""
    if not 1 <= len(features) <= 256 or len({f.question_id for f in features}) != len(
        features
    ):
        raise ValueError("bounded unique query census required")
    result = []
    for f in sorted(features, key=lambda x: x.question_id):
        others = sorted(
            (
                x
                for x in features
                if x.family == f.family and x.question_id != f.question_id
            ),
            key=lambda x: (digest(x.question_id), x.question_id),
        )
        if len(others) < max(BUDGETS):
            raise ValueError("insufficient same-family support; no replacement cohort")
        for k in BUDGETS:
            result.append(
                dict(
                    query_id=f.question_id,
                    family=f.family,
                    budget=k,
                    support_ids=[x.question_id for x in others[:k]],
                    query_digest=f.seal(),
                )
            )
    return result


def support_cut(support, query, original):
    """Allow declared local-root overlap, never remove an original forbidden root."""
    ids = frozenset(r.features.question_id for r in support)
    roots = frozenset(root for r in support for root in r.features.roots)
    if (
        not support
        or len(ids) != len(support)
        or query.question_id in ids
        or not ids <= original.question_ids
        or query.question_id not in original.question_ids
        or {r.features.family for r in support} != {query.family}
        or query.family not in original.families
        or not roots <= original.allowed_roots
        or roots.intersection(original.forbidden_roots)
    ):
        raise ValueError("unadmitted local support/query or original forbidden source")
    return TrainingCut(
        ids,
        frozenset({query.family}),
        roots,
        original.forbidden_roots,
        digest((original.admission_digest, "local-personalization", sorted(ids))),
    )


def delta_fit(support, cut, prior, *, erased=False, revoked=frozenset()):
    """Fit only local delta; prior and input tensors must remain immutable."""
    if (
        type(erased) is not bool
        or torch.is_inference_mode_enabled()
        or prior.ndim != 1
        or prior.dtype != torch.float32
        or prior.device.type != "cpu"
        or prior.requires_grad
        or not torch.isfinite(prior).all()
    ):
        raise ValueError("frozen finite CPU prior required")
    items, disposition = prepare(support, cut, len(prior), revoked=revoked)
    eligible = sum(
        any(p for p in x.positive if len(p) == 1)
        and any(p for p in x.negative if len(p) == 1)
        for x in items
    )
    if not eligible:
        return torch.zeros_like(prior), dict(
            status="no_pair_opportunity",
            direct_solves=0,
            training_ids=sorted(cut.question_ids),
            disposition=disposition,
            updates=0,
        )
    a, b, identities = design(support, cut, revoked=revoked)
    shifted = b - a @ prior.double()
    # Erase ONLY the new delta's inputs; do not erase the already fixed prior.
    local_a = torch.zeros_like(a) if erased else a
    delta, receipt = solve_hinge(local_a, shifted)
    stored = delta.float()
    if not torch.isfinite(stored).all():
        raise ValueError("nonfinite stored local delta")
    receipt.update(
        status="fitted",
        training_ids=sorted(cut.question_ids),
        contrasts=identities,
        delta_weight_bytes=stored.numel() * stored.element_size(),
        erased=erased,
        stored_objective=float(
            torch.relu(shifted - local_a @ stored.double()).square().sum()
            + RIDGE * stored.double().square().sum()
        ),
    )
    return stored, receipt


def neighbor_bank(support, cut, dimension, *, revoked=frozenset()):
    """A parameter-free support-memory comparator with explicit abstention fallback."""
    items, _ = prepare(support, cut, dimension, revoked=revoked)
    bank = {"positive": [], "negative": []}
    for item in items:
        # Match learned support availability; no positive is NOT a no-answer label.
        if not any(len(p) == 1 for p in item.positive) or not any(
            len(p) == 1 for p in item.negative
        ):
            continue
        for label, paths in (("positive", item.positive), ("negative", item.negative)):
            bank[label].extend(
                item.feature.paired[p[0]].clone() for p in paths if len(p) == 1
            )
    return {
        k: torch.stack(v) if v else torch.empty(0, dimension) for k, v in bank.items()
    }


@torch.no_grad()
def predict(
    feature, prior, delta, encoder_identity, roots, *, bank=None, revoked=frozenset()
):
    """No target argument. Ranking changes cannot change the common frozen stop."""
    feature.validate(prior.numel())
    if (
        feature.encoder_identity != encoder_identity
        or feature.roots.intersection(revoked)
        or set(roots).intersection(revoked)
        or prior.shape != delta.shape
        or any(
            t.dtype != torch.float32
            or t.device.type != "cpu"
            or t.requires_grad
            or not torch.isfinite(t).all()
            for t in (prior, delta)
        )
    ):
        raise ValueError("withdrawn, unbound or invalid Cell")
    head = StemHead(prior.numel(), encoder_identity, kind="linear")
    with torch.no_grad():
        head.readout.weight.copy_((prior + delta).reshape(1, -1))
    head.requires_grad_(False)
    head.roots = set(roots)
    scores = head(feature)[:-1]
    fallback = False
    if bank is not None:
        fallback = any(not len(bank[k]) for k in ("positive", "negative"))
        if not fallback:
            x = torch.nn.functional.normalize(feature.paired, dim=-1)
            scores = sum(
                sign
                * (x @ torch.nn.functional.normalize(bank[k], dim=-1).T).max(1).values
                for k, sign in (("positive", 1), ("negative", -1))
            )
    proposal = sorted(
        range(len(feature.candidate_ids)),
        key=lambda i: (-float(feature.frozen_scores[i]), feature.candidate_ids[i]),
    )[:4]
    if not torch.isfinite(scores).all():
        raise ValueError("nonfinite prediction")
    best = (
        min(proposal, key=lambda i: (-float(scores[i]), feature.candidate_ids[i]))
        if proposal
        else None
    )
    empty = not proposal or float(feature.frozen_scores[proposal[0]]) <= 0
    return dict(
        selected=None if empty else best,
        empty=empty,
        proposal=proposal,
        candidate_scores=[float(scores[i]) for i in proposal],
        neighbor_fallback=fallback,
        model_digest=model_digest(head),
        source_roots=sorted(roots),
    )


def summarize(records, expected):
    keys = [(r["query_id"], r["budget"], r["method"]) for r in records]
    if len(keys) != len(set(keys)) or set(keys) != set(expected):
        raise ValueError("missing/duplicate/extra planned prediction")
    if any(r["status"] not in ("succeeded", "failed") for r in records):
        raise ValueError("unregistered outcome")
    results, contrasts = {}, {}
    for k in BUDGETS:
        results[k], contrasts[k] = {}, {}
        for m in METHODS:
            group = [r for r in records if r["budget"] == k and r["method"] == m]
            families = sorted({r["family"] for r in group})
            if not group:
                raise ValueError("empty registered condition")
            hits = sum(r.get("weak_hit", False) for r in group)
            failed = sum(r["status"] == "failed" for r in group)
            results[k][m] = dict(
                questions=len(group),
                hits=hits,
                failed=failed,
                hit_bounds=[hits / len(group), (hits + failed) / len(group)],
                family_macro=None
                if failed
                else sum(
                    sum(r["weak_hit"] for r in group if r["family"] == f)
                    / sum(r["family"] == f for r in group)
                    for f in families
                )
                / len(families),
                no_pair_support=sum(r.get("no_pair_support", False) for r in group),
            )
        cand = {
            r["query_id"]: r
            for r in records
            if r["budget"] == k and r["method"] == "differentiated"
        }
        for m in ("frozen", "shared", "neighbor", "local_only"):
            base = {
                r["query_id"]: r
                for r in records
                if r["budget"] == k and r["method"] == m
            }
            if set(cand) != set(base):
                raise ValueError("unmatched contrast")
            if any(
                (cand[q]["family"], cand[q]["query_digest"])
                != (base[q]["family"], base[q]["query_digest"])
                for q in cand
            ):
                raise ValueError("contrast source drift")
            delta = [
                int(cand[q]["weak_hit"]) - int(base[q]["weak_hit"])
                for q in cand
                if cand[q]["status"] == base[q]["status"] == "succeeded"
            ]
            contrasts[k][m] = dict(
                wins=sum(d > 0 for d in delta),
                losses=sum(d < 0 for d in delta),
                missing=len(cand) - len(delta),
            )
    gain = all(
        contrasts[2][m]["wins"] > 0
        and contrasts[2][m]["losses"] == 0
        and contrasts[2][m]["missing"] == 0
        for m in ("frozen", "shared", "neighbor", "local_only")
    )
    return dict(
        by_budget=results,
        differentiated_contrasts=contrasts,
        candidate_disposition="fresh_confirmation_required"
        if gain
        else "stop_no_controlled_fewshot_gain",
        production_accepted=False,
        reader_adequacy_established=False,
        recorded=len(records),
        failed=sum(r["status"] == "failed" for r in records),
        unique_queries=len({r["query_id"] for r in records}),
        source_families=len({r["family"] for r in records}),
        independent_confirmation=False,
    )


def journal(path, value):
    with path.open("a", encoding="utf-8") as out:
        out.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
        out.flush()
        os.fsync(out.fileno())


def run(archive, output, *, source_commit, execution_context="full-repository-source"):
    if not re.fullmatch("[0-9a-f]{40}", source_commit or ""):
        raise ValueError("exact source or explicitly declared overlay parent required")
    output.mkdir(exist_ok=False)
    started = time.perf_counter()
    write(
        output / "protocol.json",
        PROTOCOL
        | dict(
            source_commit=source_commit,
            execution_context=execution_context,
            archive_sha256=ARCHIVE,
            executing_file_sha256=hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
        ),
    )
    datasets, audit = audit_content(archive)
    write(output / "content-audit.json", audit)
    rows, original = datasets[48]
    planned = episodes([r.features for r in rows])
    write(output / "episodes.json", planned)
    by_id = {r.features.question_id: r for r in rows}
    stamps = {qid: r.features.seal() for qid, r in by_id.items()}
    priors = {}
    for family in sorted({e["family"] for e in planned}):
        train, _, cut = family_split(rows, original, family)
        try:
            head, fit = fit_margin(train, cut, "squared_hinge")
            prior = head.readout.weight.detach().flatten().clone()
            priors[family] = (prior, head.encoder_identity, head.roots)
            save_file(
                {"prior": prior}, str(output / (digest(family) + "-prior.safetensors"))
            )
            journal(
                output / "prior-fits.jsonl",
                dict(
                    family=family, status="succeeded", fit=fit, roots=sorted(head.roots)
                ),
            )
        except Exception as exc:
            priors[family] = None
            journal(
                output / "prior-fits.jsonl",
                dict(family=family, status="failed", error=str(exc)[:512]),
            )
    predictions = []
    for episode in planned:
        query = by_id[episode["query_id"]].features
        support = tuple(by_id[qid] for qid in episode["support_ids"])
        cut = support_cut(support, query, original)
        zero = torch.zeros(query.paired.shape[1])
        for method in METHODS:
            record = episode | dict(method=method, status="started")
            journal(output / "starts.jsonl", record)
            stamp = time.perf_counter()
            try:
                shared = method in ("shared", "differentiated", "erased_update")
                if shared and priors[query.family] is None:
                    raise ValueError("shared prior failed; no fallback relabeling")
                prior, identity, roots = (
                    priors[query.family]
                    if shared
                    else (zero, query.encoder_identity, set())
                )
                delta, fit, bank = (
                    zero,
                    dict(status="no_adaptation", direct_solves=0),
                    None,
                )
                if method in ("local_only", "differentiated", "erased_update"):
                    delta, fit = delta_fit(
                        support, cut, prior, erased=method == "erased_update"
                    )
                    roots = set(roots) | set(cut.allowed_roots)
                elif method == "neighbor":
                    bank = neighbor_bank(support, cut, len(zero))
                    roots = set(cut.allowed_roots)
                    fit = dict(
                        status="memory",
                        vector_bytes=sum(
                            x.numel() * x.element_size() for x in bank.values()
                        ),
                    )
                path = output / (digest((episode, method)) + ".safetensors")
                save_file({"delta": delta, **({} if bank is None else bank)}, str(path))
                restored = load_file(str(path))
                if not torch.equal(restored["delta"], delta):
                    raise ValueError("local delta reload mismatch")
                p = predict(
                    query,
                    prior,
                    restored["delta"],
                    identity,
                    roots,
                    bank=None if bank is None else {k: restored[k] for k in bank},
                )
                record.update(
                    status="succeeded",
                    prediction=p,
                    fit=fit,
                    no_pair_support=fit["status"] == "no_pair_opportunity",
                    prior_digest=digest(prior.tolist()),
                    delta_digest=digest(delta.tolist()),
                    state_file=path.name,
                    state_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    shared_local_root_overlap=sorted(query.roots & cut.allowed_roots),
                )
            except Exception as exc:
                record.update(
                    status="failed", error_type=type(exc).__name__, error=str(exc)[:512]
                )
            record["elapsed_seconds"] = time.perf_counter() - stamp
            predictions.append(record)
            journal(output / "predictions.jsonl", record)
    # All predictions are durable BEFORE any final query's label is read for evaluation.
    sealed = hashlib.sha256((output / "predictions.jsonl").read_bytes()).hexdigest()
    write(
        output / "prediction-seal.json",
        dict(sha256=sealed, count=len(predictions), query_scoring_started=False),
    )
    for record in predictions:
        if record["status"] == "succeeded":
            r = by_id[record["query_id"]]
            record["weak_hit"] = record["prediction"]["selected"] in r.positive_indices
            record["query_positive_in_proposal"] = bool(
                set(record["prediction"]["proposal"]) & set(r.positive_indices)
            )
        journal(output / "scored.jsonl", record)
    if any(r.features.seal() != stamps[qid] for qid, r in by_id.items()):
        raise ValueError("shared input feature mutation")
    expected = {(e["query_id"], e["budget"], m) for e in planned for m in METHODS}
    report = summarize(predictions, expected) | dict(
        source_commit=source_commit,
        execution_context=execution_context,
        prediction_sha256=sealed,
        new_encoder_calls=0,
        new_reader_calls=0,
        elapsed_seconds=time.perf_counter() - started,
        prior_fits=len(priors),
        planned=len(expected),
        candidate_delta_bytes=zero.numel() * zero.element_size(),
        lineage_authentication_and_current_revocation_are_external=True,
    )
    write(output / "summary.json", report)
    if report["failed"]:
        raise RuntimeError("failed predictions retained; no smaller success census")
    return report


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("archive", type=Path)
    cli.add_argument("output", type=Path)
    args = cli.parse_args()
    run(
        args.archive,
        args.output,
        source_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", ""),
    )
