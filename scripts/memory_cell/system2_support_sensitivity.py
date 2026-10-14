"""All bounded support subsets, not another selected-seed few-shot result.

Reuse the published Cell fits and compare question-macro expected source hits.
Each support snapshot is fitted ONCE and evaluated on every other local query.
No new Encoder, Reader, independent cohort, chronology or NDU value is supplied.
"""

import argparse
from dataclasses import replace
from fractions import Fraction
import hashlib
from itertools import combinations
import os
from pathlib import Path
import re
import time

import torch
from safetensors.torch import load_file, save_file

from system2_ablation import digest
from system2_content_replay import ARCHIVE, audit_content
from system2_fewshot_cells import (
    BUDGETS,
    METHODS as ORIGINAL_METHODS,
    delta_fit,
    journal,
    neighbor_bank,
    predict,
    support_cut,
)
from system2_learning_probe import prepare
from system2_linear_solver import family_split, write
from system2_margin_transfer import fit_margin

METHODS = ORIGINAL_METHODS + ("swapped_labels",)
CONTROLS = (
    "frozen",
    "shared",
    "local_only",
    "neighbor",
    "erased_update",
    "swapped_labels",
)
PROTOCOL = dict(
    schema="hepta.system2.all-support-subsets.v1",
    methods=METHODS,
    budgets=BUDGETS,
    primary_budget=2,
    support_selection="exhaustive; no label/score filtering",
    anchor="first subset in inherited sha256-question-id order",
    maximum_episodes=2048,
    maximum_snapshots=512,
    aggregation="uniform subsets WITHIN query; then equal query or family",
    controls=CONTROLS,
    progression="positive mean over every control AND no frozen losses on any subset",
    ranking_and_stop="unchanged prior/delta/neighbor fits; unchanged frozen-native stop",
    data_status="reused exposed TRAIN data; same-root question-disjoint personalization",
    swapped_labels="synthetic within-support reversal only; never a human/native verdict",
    new_encoder_calls=0,
    new_reader_calls=0,
    independent_confirmation=False,
    chronology_established=False,
    calibrated_ndu_utility=False,
    production_accepted=False,
)


def enumerate_episodes(features):
    if not 1 <= len(features) <= 32 or len({f.question_id for f in features}) != len(
        features
    ):
        raise ValueError("bounded unique feature cohort required")
    dim = features[0].paired.shape[1]
    for f in features:
        f.validate(dim)
    if len({f.encoder_identity for f in features}) != 1:
        raise ValueError("mixed shared encoder")
    result, snapshots = [], set()
    for f in sorted(features, key=lambda x: x.question_id):
        other = sorted(
            (
                x
                for x in features
                if x.family == f.family and x.question_id != f.question_id
            ),
            key=lambda x: (digest(x.question_id), x.question_id),
        )
        if len(other) < max(BUDGETS):
            raise ValueError("missing support; no smaller replacement cohort")
        for k in BUDGETS:
            for index, support in enumerate(combinations(other, k)):
                ids = [x.question_id for x in support]
                sid = digest((f.family, ids))
                row = dict(
                    query_id=f.question_id,
                    family=f.family,
                    budget=k,
                    support_ids=ids,
                    query_digest=f.seal(),
                    snapshot_id=sid,
                    anchor=index == 0,
                )
                row["episode_id"] = digest(row)
                result.append(row)
                snapshots.add(sid)
                if (
                    len(result) > PROTOCOL["maximum_episodes"]
                    or len(snapshots) > PROTOCOL["maximum_snapshots"]
                ):
                    raise ValueError("exhaustive study exceeds fixed resource bound")
    return result


def swapped_support(support, cut, dimension, *, revoked=frozenset()):
    """Reverse eligible support singleton labels only; no opportunity stays no-op."""
    items, _ = prepare(support, cut, dimension, revoked=revoked)
    changed = []
    for row, item in zip(support, items, strict=True):
        pos = tuple(p[0] for p in item.positive if len(p) == 1)
        neg = tuple(p[0] for p in item.negative if len(p) == 1)
        changed.append(replace(row, positive_indices=neg) if pos and neg else row)
    return tuple(changed)


def aggregate(records, planned):
    expected = {(e["episode_id"], m): e for e in planned for m in METHODS}
    actual = {(r["episode_id"], r["method"]): r for r in records}
    if (
        not expected
        or len(expected) != len(planned) * len(METHODS)
        or len(actual) != len(records)
        or set(actual) != set(expected)
    ):
        raise ValueError("missing/extra/duplicate support prediction")
    for key, record in actual.items():
        if any(record.get(k) != v for k, v in expected[key].items()):
            raise ValueError("episode/query/support binding drift")
        if record["status"] not in ("succeeded", "failed") or (
            record["status"] == "succeeded" and type(record.get("weak_hit")) is not bool
        ):
            raise ValueError("invalid outcome or source score")
    results, contrasts = {}, {}
    for k in BUDGETS:
        eps = [e for e in planned if e["budget"] == k]
        qids = sorted({e["query_id"] for e in eps})
        by_query = {q: [e for e in eps if e["query_id"] == q] for q in qids}
        families = {q: by_query[q][0]["family"] for q in qids}
        unique_families = sorted(set(families.values()))
        results[k], contrasts[k] = {}, {}
        for method in METHODS:
            per_query = []
            for q, group in by_query.items():
                rows = [actual[(e["episode_id"], method)] for e in group]
                hits = sum(
                    r.get("weak_hit", False) for r in rows if r["status"] == "succeeded"
                )
                failed = sum(r["status"] == "failed" for r in rows)
                bounds = [Fraction(hits, len(rows)), Fraction(hits + failed, len(rows))]
                per_query.append(
                    dict(
                        query_id=q,
                        family=families[q],
                        subsets=len(rows),
                        hits=hits,
                        failed=failed,
                        bounds=bounds,
                        selected_choices=len(
                            {
                                r["prediction"]["selected"]
                                for r in rows
                                if r["status"] == "succeeded"
                            }
                        ),
                        mixed_success=hits > 0 and hits + failed < len(rows),
                    )
                )
            macro = [sum(r["bounds"][i] for r in per_query) / len(qids) for i in (0, 1)]
            family_macro = [
                sum(
                    sum(r["bounds"][i] for r in per_query if r["family"] == f)
                    / sum(r["family"] == f for r in per_query)
                    for f in unique_families
                )
                / len(unique_families)
                for i in (0, 1)
            ]
            anchors = [actual[(e["episode_id"], method)] for e in eps if e["anchor"]]
            results[k][method] = dict(
                query_macro_bounds=list(map(float, macro)),
                family_macro_bounds=list(map(float, family_macro)),
                anchor_hits=sum(
                    r.get("weak_hit", False)
                    for r in anchors
                    if r["status"] == "succeeded"
                ),
                anchor_failures=sum(r["status"] == "failed" for r in anchors),
                mixed_hit_queries=sum(r["mixed_success"] for r in per_query),
                selection_sensitive_queries=sum(
                    r["selected_choices"] > 1 for r in per_query
                ),
                all_subset_hits=sum(r["hits"] for r in per_query),
                subset_predictions=len(eps),
                failed=sum(r["failed"] for r in per_query),
                per_query=[
                    r | {"bounds": list(map(float, r["bounds"]))} for r in per_query
                ],
            )
        for control in CONTROLS:
            rows = []
            for q, group in by_query.items():
                wins, losses, missing = 0, 0, 0
                for e in group:
                    cand, base = (
                        actual[(e["episode_id"], m)]
                        for m in ("differentiated", control)
                    )
                    if cand["status"] == base["status"] == "succeeded":
                        d = int(cand["weak_hit"]) - int(base["weak_hit"])
                        wins += d > 0
                        losses += d < 0
                    else:
                        missing += 1
                rows.append(
                    dict(
                        query_id=q,
                        subsets=len(group),
                        wins=wins,
                        losses=losses,
                        missing=missing,
                        effect=[
                            Fraction(wins - losses - missing, len(group)),
                            Fraction(wins - losses + missing, len(group)),
                        ],
                    )
                )
            means = [sum(r["effect"][i] for r in rows) / len(rows) for i in (0, 1)]
            contrasts[k][control] = dict(
                query_macro_effect_bounds=list(map(float, means)),
                subset_wins=sum(r["wins"] for r in rows),
                subset_losses=sum(r["losses"] for r in rows),
                missing=sum(r["missing"] for r in rows),
                queries_with_loss=sum(r["losses"] > 0 for r in rows),
                queries_with_win=sum(r["wins"] > 0 for r in rows),
                per_query=[r | {"effect": list(map(float, r["effect"]))} for r in rows],
            )
    failed = sum(r["status"] == "failed" for r in records)
    primary = contrasts[2]
    robust = (
        not failed
        and primary["frozen"]["subset_losses"] == 0
        and all(primary[m]["query_macro_effect_bounds"][0] > 0 for m in CONTROLS)
    )
    return dict(
        by_budget=results,
        differentiated_contrasts=contrasts,
        unique_queries=len({e["query_id"] for e in planned}),
        source_families=len({e["family"] for e in planned}),
        episodes=len(planned),
        recorded=len(records),
        failed=failed,
        support_robust_gain=bool(robust),
        independent_confirmation=False,
        production_accepted=False,
        candidate_disposition="fresh_confirmation_required"
        if robust
        else "stop_no_controlled_support_robust_gain",
        repeated_supports_are_not_independent=True,
    )


def run(
    archive,
    output,
    *,
    source_commit,
    execution_context="full-repository-source",
    revoked=frozenset(),
):
    if not re.fullmatch("[0-9a-f]{40}", source_commit or ""):
        raise ValueError("exact source or explicit overlay parent required")
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
    rows, original = datasets[48]
    prepare(rows, original, rows[0].features.paired.shape[1], revoked=revoked)
    planned = enumerate_episodes([r.features for r in rows])
    write(output / "episodes.json", planned)
    write(output / "content-audit.json", audit)
    by_id = {r.features.question_id: r for r in rows}
    stamps = {q: r.features.seal() for q, r in by_id.items()}
    priors = {}
    for family in sorted({r.features.family for r in rows}):
        train, _, cut = family_split(rows, original, family)
        try:
            head, fit = fit_margin(train, cut, "squared_hinge", revoked=revoked)
            prior = head.readout.weight.detach().flatten().clone()
            priors[family] = (prior, set(head.roots))
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
    # A fitted snapshot never includes any of its own evaluated query identities.
    specifications = {e["snapshot_id"]: e for e in planned}
    states = {}
    for sid, e in sorted(specifications.items()):
        query = by_id[e["query_id"]].features
        support = tuple(by_id[q] for q in e["support_ids"])
        cut = support_cut(support, query, original)
        zero = torch.zeros(query.paired.shape[1])
        for method in METHODS:
            stamp = time.perf_counter()
            key = (sid, method)
            meta = dict(
                snapshot_id=sid,
                method=method,
                family=e["family"],
                support_ids=e["support_ids"],
                status="started",
            )
            journal(output / "state-starts.jsonl", meta)
            try:
                shared = method in (
                    "shared",
                    "differentiated",
                    "erased_update",
                    "swapped_labels",
                )
                if shared and priors[query.family] is None:
                    raise ValueError("failed shared prior; no silent fallback")
                prior, roots = priors[query.family] if shared else (zero, set())
                delta, fit, bank = (
                    zero,
                    dict(status="no_adaptation", direct_solves=0),
                    None,
                )
                train_support = (
                    swapped_support(support, cut, len(zero), revoked=revoked)
                    if method == "swapped_labels"
                    else support
                )
                if method in (
                    "local_only",
                    "differentiated",
                    "erased_update",
                    "swapped_labels",
                ):
                    delta, fit = delta_fit(
                        train_support,
                        cut,
                        prior,
                        erased=method == "erased_update",
                        revoked=revoked,
                    )
                    roots = set(roots) | set(cut.allowed_roots)
                elif method == "neighbor":
                    bank = neighbor_bank(support, cut, len(zero), revoked=revoked)
                    roots = set(cut.allowed_roots)
                    fit = dict(
                        status="memory",
                        vector_bytes=sum(
                            t.numel() * t.element_size() for t in bank.values()
                        ),
                    )
                path = output / (digest(key) + ".safetensors")
                tensors = dict(prior=prior, delta=delta) | (
                    {} if bank is None else bank
                )
                save_file(
                    {k: t.clone().contiguous() for k, t in tensors.items()}, str(path)
                )
                restored = load_file(str(path))
                if set(restored) != set(tensors) or any(
                    not torch.equal(restored[k], t) for k, t in tensors.items()
                ):
                    raise ValueError("snapshot reload mismatch")
                meta.update(
                    status="succeeded",
                    fit=fit,
                    source_roots=sorted(roots),
                    state_file=path.name,
                    state_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    synthetic_supervision=method == "swapped_labels",
                    fitted_support_labels={
                        r.features.question_id: list(r.positive_indices)
                        for r in train_support
                    },
                )
                states[key] = (restored, meta)
            except Exception as exc:
                meta.update(
                    status="failed", error_type=type(exc).__name__, error=str(exc)[:512]
                )
                states[key] = (None, meta)
            meta["elapsed_seconds"] = time.perf_counter() - stamp
            journal(output / "states.jsonl", meta)
    predictions = []
    for e in planned:
        query = by_id[e["query_id"]].features
        for method in METHODS:
            stamp = time.perf_counter()
            record = e | dict(method=method, status="started")
            journal(output / "starts.jsonl", record)
            tensors, meta = states[(e["snapshot_id"], method)]
            try:
                if tensors is None:
                    raise ValueError("support snapshot unavailable")
                if e["query_id"] in meta["support_ids"]:
                    raise ValueError("query is in its own snapshot")
                bank = (
                    {k: tensors[k] for k in ("positive", "negative")}
                    if method == "neighbor"
                    else None
                )
                p = predict(
                    query,
                    tensors["prior"],
                    tensors["delta"],
                    query.encoder_identity,
                    meta["source_roots"],
                    bank=bank,
                    revoked=revoked,
                )
                record.update(
                    status="succeeded",
                    prediction=p,
                    state_sha256=meta["state_sha256"],
                    no_pair_support=meta["fit"]["status"] == "no_pair_opportunity",
                )
            except Exception as exc:
                record.update(
                    status="failed", error_type=type(exc).__name__, error=str(exc)[:512]
                )
            record["elapsed_seconds"] = time.perf_counter() - stamp
            predictions.append(record)
            journal(output / "predictions.jsonl", record)
    # Check persisted snapshots against the states actually used, before scoring.
    for tensors, meta in states.values():
        if tensors is not None:
            saved = load_file(str(output / meta["state_file"]))
            if set(saved) != set(tensors) or any(
                not torch.equal(saved[k], v) for k, v in tensors.items()
            ):
                raise ValueError("prediction mutated a frozen support snapshot")
    if any(by_id[q].features.seal() != value for q, value in stamps.items()):
        raise ValueError("prediction mutated shared features")
    sealed = hashlib.sha256((output / "predictions.jsonl").read_bytes()).hexdigest()
    write(
        output / "prediction-seal.json",
        dict(sha256=sealed, count=len(predictions), query_scoring_started=False),
    )
    for r in predictions:
        if r["status"] == "succeeded":
            r["weak_hit"] = (
                r["prediction"]["selected"] in by_id[r["query_id"]].positive_indices
            )
        journal(output / "scored.jsonl", r)
    if any(by_id[q].features.seal() != value for q, value in stamps.items()):
        raise ValueError("shared feature drift")
    if (
        hashlib.sha256((output / "predictions.jsonl").read_bytes()).hexdigest()
        != sealed
    ):
        raise ValueError("scoring changed raw predictions")
    result = aggregate(predictions, planned)
    states_failed = sum(m["status"] == "failed" for _, m in states.values())
    if states_failed or any(p is None for p in priors.values()):
        result.update(
            support_robust_gain=False,
            candidate_disposition="stop_incomplete_snapshot_census",
        )
    result.update(
        source_commit=source_commit,
        execution_context=execution_context,
        protocol=PROTOCOL,
        shared_prior_fit_attempts=len(priors),
        support_snapshots=len(specifications),
        state_conditions=len(states),
        state_failures=states_failed,
        prediction_sha256=sealed,
        state_fit_seconds_including_failures=sum(
            m["elapsed_seconds"] for _, m in states.values()
        ),
        elapsed_seconds=time.perf_counter() - started,
        new_encoder_calls=0,
        new_reader_calls=0,
        compute_matched=False,
        historical_encoding_cost_not_zero=True,
        reader_adequacy_established=False,
    )
    write(output / "summary.json", result)
    if result["failed"] or states_failed or any(p is None for p in priors.values()):
        raise RuntimeError("failed conditions retained in complete census")
    return result


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
