"""Selection-controlled split, merge and rank allocation for actual factor cells.

The writer sees the matrix it was asked to store. Selection addresses control
topology and retention; hidden read addresses are never accepted by this API.
Every fitted basis, even one later rejected, is charged and retained by digest.
No zero-cost retraining, random-noise compression or unconditional win is assumed.
"""

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .factor_cell import FactorBank, FactorBlock, MAX_RANK, canonical_matrix


DEFAULTS = {
    "max_cells": 4,
    "split_rounds": 2,
    "minimum_gain": 0.05,
    "retention_relative": 0.02,
    "retention_absolute_mse": 0.25,
    "near_lossless_mse": 0.25,
    "power_iterations": 8,
    "signal_floor": 0.15,
    "signal_dimension_multiplier": 4.0,
    "kmeans_iterations": 12,
    "training_price": 0.02,
    "retention_price": 0.02,
}


def artifact_size(shape, routes, ranks, has_missing=False):
    n, d = shape
    k = len(ranks)
    return (
        20
        + (n * (k - 1).bit_length() + 7) // 8
        + ((n * d + 7) // 8 if has_missing else 0)
        + k * (8 + 4 * d)
        + 2
        * sum(
            int(rank) * (int(np.count_nonzero(routes == index)) + d)
            for index, rank in enumerate(ranks)
        )
    )


def maximum_single_rank(shape, budget, has_missing=False):
    routes = np.zeros(shape[0], dtype=np.uint8)
    ranks = [
        rank
        for rank in range(min(*shape, MAX_RANK) + 1)
        if artifact_size(shape, routes, [rank], has_missing) <= budget
    ]
    if not ranks:
        raise ValueError("budget cannot hold a single cell's center and schema")
    return max(ranks)


def read_metrics(bank, matrix, addresses, domains=None):
    rows, columns = np.nonzero(addresses)
    if not len(rows):
        raise ValueError("evaluation address set is empty")
    predictions = bank.read(rows, columns)
    if any(value is None for value in predictions):
        raise ValueError("an evaluation address is unavailable in this memory")
    error = np.asarray(predictions, dtype=np.float64) - matrix[rows, columns]
    result = {
        "count": len(error),
        "mse": float(np.mean(error**2)),
        "mae": float(np.mean(np.abs(error))),
        "exact": float(np.mean(error == 0)),
        "read_factor_multiplications": int(
            sum(bank.blocks[int(bank.routes[row])].rank for row in rows)
        ),
    }
    if domains is not None:
        result["domain_mse"] = {
            str(int(domain)): float(np.mean(error[domains[rows] == domain] ** 2))
            for domain in np.unique(domains[rows])
        }
    return result


@dataclass
class WorkLedger:
    directory: Path
    records: list = field(default_factory=list)
    retained: dict = field(default_factory=dict)
    svd_work: int = 0
    fit_reconstruction_work: int = 0
    diagnostic_work: int = 0
    fit_calls: int = 0
    svd_calls: int = 0
    fit_seconds: float = 0.0
    temporary_factor_peak_bytes: int = 0
    audit_bytes: int = 0
    audit_snapshots: int = 0

    def __post_init__(self):
        self.directory = Path(self.directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def retain(self, bank):
        payload, identity = bank.to_bytes(), bank.digest
        if identity not in self.retained:
            target = self.directory / f"{identity}.factor"
            if target.exists():
                if target.read_bytes() != payload:
                    raise ValueError(
                        "existing forensic artifact does not match its identity"
                    )
            else:
                target.write_bytes(payload)
            self.retained[identity] = len(payload)
        return identity

    def fit(self, matrix, routes, ranks, mask, label, seed):
        bank, receipt = FactorBank.fit(
            matrix, routes=routes, ranks=ranks, mask=mask, seed=seed
        )
        self.fit_calls += 1
        self.svd_calls += receipt["svd_calls"]
        self.svd_work += receipt["svd_work_proxy"]
        reconstruction = sum(
            (block["svd_calls"] + 1) * block["rows"] * block["columns"] * block["rank"]
            for block in receipt["blocks"]
        )
        self.fit_reconstruction_work += reconstruction
        receipt["post_svd_reconstruction_mac_proxy"] = reconstruction
        self.fit_seconds += receipt["fit_wall_seconds"]
        self.temporary_factor_peak_bytes = max(
            self.temporary_factor_peak_bytes, len(bank.to_bytes())
        )
        self.retain(bank)
        self.records.append({"label": label, "fit": receipt})
        return bank

    @property
    def total_work(self):
        return self.svd_work + self.fit_reconstruction_work + self.diagnostic_work

    def metrics(self, bank, matrix, addresses, domains=None):
        result = read_metrics(bank, matrix, addresses, domains)
        self.diagnostic_work += result["read_factor_multiplications"]
        return result

    def summary(self):
        metadata = (
            json.dumps(self.records, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        audit = self.directory / f"ledger-{self.audit_snapshots}.json"
        with audit.open("xb") as stream:
            stream.write(metadata)
        self.audit_snapshots += 1
        self.audit_bytes += len(metadata)
        return {
            "fit_calls": self.fit_calls,
            "svd_calls": self.svd_calls,
            "svd_work_proxy": self.svd_work,
            "diagnostic_multiply_work_proxy": self.diagnostic_work,
            "post_svd_reconstruction_mac_proxy": self.fit_reconstruction_work,
            "total_work_proxy": self.total_work,
            "fit_wall_seconds": self.fit_seconds,
            "retained_artifact_bytes": sum(self.retained.values()),
            "retained_audit_metadata_bytes": self.audit_bytes,
            "unique_artifacts_written": len(self.retained),
            "temporary_factor_peak_bytes": self.temporary_factor_peak_bytes,
            "retained_by_sha256": dict(self.retained),
            "records": self.records,
        }


def _truncate(basis, ranks):
    return FactorBank(
        basis.routes,
        basis.mask,
        tuple(
            FactorBlock(
                block.center,
                block.record_factors[:, :rank],
                block.decoder[:rank],
                block.shift,
            )
            for block, rank in zip(basis.blocks, ranks, strict=True)
        ),
    )


def _rank_curves(basis, matrix, selection, domains, ledger):
    curves = []
    for index, block in enumerate(basis.blocks):
        row_ids = np.flatnonzero(basis.routes == index)
        selected = selection[row_ids]
        row, column = np.nonzero(selected)
        products = np.zeros(len(row), dtype=np.int64)
        target = matrix[row_ids[row], column]
        values = []
        for rank in range(block.rank + 1):
            if rank:
                products += block.record_factors[row, rank - 1].astype(
                    np.int64
                ) * block.decoder[rank - 1, column].astype(np.int64)
                ledger.diagnostic_work += len(row)
            prediction = products.copy()
            if block.shift > 0:
                prediction = (prediction + (1 << (block.shift - 1))) // (
                    1 << block.shift
                )
            elif block.shift < 0:
                prediction = prediction * (1 << -block.shift)
            error = (prediction + block.center[column] - target).astype(np.float64) ** 2
            values.append(
                {
                    "sse": float(error.sum()),
                    "domain_mse": {
                        str(int(domain)): float(
                            np.mean(error[domains[row_ids[row]] == domain])
                        )
                        for domain in np.unique(domains[row_ids[row]])
                    },
                }
            )
        curves.append(values)
    return curves


def fit_partition(
    matrix,
    mask,
    routes,
    budget,
    selection,
    domains,
    ledger,
    *,
    label,
    seed,
    floors=None,
    compact=False,
    basis=None,
):
    """Fit each proposed subspace, then allocate integer ranks under real bytes.

    Per-partition/domain minima are a sufficient retention constraint, stronger
    than a global mean. Full fitted bases are temporary training state and are
    separately charged, never presented as an in-budget deployed model.
    """
    routes = np.asarray(routes, dtype=np.uint8)
    k, d = len(np.unique(routes)), matrix.shape[1]
    maxima = [
        min(int(np.count_nonzero(routes == index)), d, MAX_RANK) for index in range(k)
    ]
    if artifact_size(matrix.shape, routes, [0] * k, not mask.all()) > budget:
        return None, {"reason": "schema_and_centers_exceed_budget", "label": label}
    if basis is None:
        basis = ledger.fit(matrix, routes, maxima, mask, label, seed)
    elif (
        basis.shape != matrix.shape
        or not np.array_equal(basis.routes, routes)
        or not np.array_equal(basis.mask, mask)
        or basis.digest not in ledger.retained
    ):
        raise ValueError(
            "reused basis must be an already charged fit from this owner and source"
        )
    else:
        ledger.records.append(
            {"reused_fit": {"label": label, "artifact_sha256": basis.digest}}
        )
    curves = _rank_curves(basis, matrix, selection, domains, ledger)
    ranks = []
    for curve in curves:
        admissible = [
            rank
            for rank, point in enumerate(curve)
            if floors is None
            or all(
                value <= floors[domain] for domain, value in point["domain_mse"].items()
            )
        ]
        if not admissible:
            return None, {"reason": "no_rank_meets_retention_floor", "label": label}
        ranks.append(min(admissible))
    size = artifact_size(matrix.shape, routes, ranks, not mask.all())
    if size > budget:
        return None, {
            "reason": "retention_minimum_exceeds_budget",
            "minimum_bytes": size,
            "label": label,
        }
    if not compact:
        while True:
            choices = []
            for index, curve in enumerate(curves):
                per_rank = 2 * (int(np.count_nonzero(routes == index)) + d)
                for rank in range(ranks[index] + 1, len(curve)):
                    cost = (rank - ranks[index]) * per_rank
                    benefit = curve[ranks[index]]["sse"] - curve[rank]["sse"]
                    if size + cost <= budget and benefit > 0:
                        choices.append((benefit / cost, benefit, -index, rank, cost))
            if not choices:
                break
            _, _, negative_index, rank, cost = max(choices)
            ranks[-negative_index] = rank
            size += cost
    bank = _truncate(basis, ranks)
    if len(bank.to_bytes()) != size or size > budget:
        raise AssertionError("rank allocation violated the serialized byte budget")
    ledger.retain(bank)
    receipt = {
        "label": label,
        "ranks": ranks,
        "artifact_bytes": size,
        "temporary_basis_sha256": basis.digest,
        "deployed_sha256": bank.digest,
        "retention_minimum_enforced": floors is not None,
        "compact": compact,
    }
    ledger.records.append({"allocation": receipt})
    return bank, receipt


def _bisect(features, seed, iterations, ledger):
    rng = np.random.default_rng(seed)
    n, d = features.shape
    first = int(rng.integers(n))
    second = int(np.argmax(np.sum((features - features[first]) ** 2, axis=1)))
    centers = features[[first, second]].copy()
    route = np.zeros(n, dtype=np.uint8)
    for _ in range(iterations):
        distance = np.sum((features[:, None, :] - centers[None, :, :]) ** 2, axis=2)
        ledger.diagnostic_work += n * d * 2
        proposed = np.argmin(distance, axis=1).astype(np.uint8)
        if min(np.bincount(proposed, minlength=2)) < 2:
            # Deterministic balanced projection split, based on written values.
            projection = features @ (centers[1] - centers[0])
            order = np.argsort(projection, kind="stable")
            proposed[order[: n // 2]], proposed[order[n // 2 :]] = 0, 1
            ledger.diagnostic_work += n * d
        if np.array_equal(route, proposed) and _:
            break
        route = proposed
        centers = np.stack(
            [features[route == index].mean(axis=0) for index in range(2)]
        )
    return route


def learned_routes(matrix, k, *, seed, ledger, energy=False, iterations=12):
    routes = np.zeros(len(matrix), dtype=np.uint8)
    values = matrix.astype(np.float64)
    values -= values.mean(axis=0)
    if energy:
        values = values**2
        values /= np.maximum(values.sum(axis=1, keepdims=True), 1.0)
        ledger.diagnostic_work += values.size
    while len(np.unique(routes)) < k:
        eligible = [
            index
            for index in np.unique(routes)
            if np.count_nonzero(routes == index) >= 4
        ]
        if not eligible:
            raise ValueError("too few rows for learned partition")
        chosen = max(
            eligible,
            key=lambda index: (
                float(np.var(values[routes == index], axis=0).sum())
                * np.count_nonzero(routes == index)
            ),
        )
        rows = np.flatnonzero(routes == chosen)
        local = _bisect(
            values[rows],
            seed + int(chosen) + len(np.unique(routes)) * 101,
            iterations,
            ledger,
        )
        routes[rows[local == 1]] = len(np.unique(routes))
    return routes


def split_route(matrix, current, selection, seed, ledger, energy, iterations):
    error = (current.reconstruct() - matrix).astype(np.float64) ** 2
    ledger.diagnostic_work += matrix.shape[1] * sum(
        len(block.record_factors) * block.rank for block in current.blocks
    )
    candidates = [
        index
        for index in range(len(current.blocks))
        if np.count_nonzero(current.routes == index) >= 4
    ]
    if not candidates:
        return None
    chosen = max(
        candidates,
        key=lambda index: float(
            error[(current.routes == index)[:, None] & selection].sum()
        ),
    )
    rows = np.flatnonzero(current.routes == chosen)
    values = matrix[rows].astype(np.float64)
    values -= values.mean(axis=0)
    if energy:
        values = values**2
        values /= np.maximum(values.sum(axis=1, keepdims=True), 1.0)
        ledger.diagnostic_work += values.size
    local = _bisect(values, seed, iterations, ledger)
    routes = current.routes.copy()
    routes[rows[local == 1]] = len(current.blocks)
    return routes


def split_signal(matrix, current, mask, ledger, settings):
    residual = np.where(mask, matrix - current.reconstruct(), 0).astype(np.float64)
    ledger.diagnostic_work += matrix.shape[1] * sum(
        len(block.record_factors) * block.rank for block in current.blocks
    )
    energy = float(np.sum(residual**2))
    ledger.diagnostic_work += matrix.size
    if energy == 0:
        return 0.0
    vector = np.arange(1, matrix.shape[1] + 1, dtype=np.float64)
    vector /= np.linalg.norm(vector)
    for _ in range(settings["power_iterations"]):
        vector = residual.T @ (residual @ vector)
        ledger.diagnostic_work += 2 * matrix.size
        norm = np.linalg.norm(vector)
        if not norm:
            return 0.0
        vector /= norm
    projected = residual @ vector
    ledger.diagnostic_work += matrix.size
    return float(np.sum(projected**2) / energy)


def fit_adaptive(
    matrix,
    *,
    budget,
    selection,
    domains,
    directory,
    seed,
    mask=None,
    initial_routes=None,
    settings=None,
):
    settings = {**DEFAULTS, **(settings or {})}
    matrix, mask = canonical_matrix(matrix, mask)
    selection, domains = np.asarray(selection), np.asarray(domains)
    if (
        selection.shape != matrix.shape
        or selection.dtype != np.dtype(bool)
        or (selection & ~mask).any()
    ):
        raise ValueError("selection addresses must be available coordinates")
    if domains.shape != (len(matrix),) or any(
        not selection[domains == domain].any() for domain in np.unique(domains)
    ):
        raise ValueError("every retention domain needs selection addresses")
    if initial_routes is not None:
        initial_routes = np.asarray(initial_routes)
        if (
            initial_routes.shape != (len(matrix),)
            or initial_routes.dtype.kind not in "iu"
        ):
            raise ValueError(
                "initial routes must assign an integer cell identity to every row"
            )
        labels = np.unique(initial_routes)
        if not 1 <= len(labels) <= settings["max_cells"] or not np.array_equal(
            labels, np.arange(len(labels))
        ):
            raise ValueError(
                "initial cell identities must be contiguous and within the cell-count limit"
            )
        initial_routes = initial_routes.astype(np.uint8, copy=False)
    started = time.perf_counter()
    ledger = WorkLedger(directory)
    rank = maximum_single_rank(matrix.shape, budget, not mask.all())
    single = ledger.fit(
        matrix,
        np.zeros(len(matrix), dtype=np.uint8),
        [rank],
        mask,
        "global_optimal_svd",
        seed,
    )
    initial_metrics = ledger.metrics(single, matrix, selection, domains)
    current = single
    events = []
    if initial_routes is not None and len(np.unique(initial_routes)) > 1:
        active, receipt = fit_partition(
            matrix,
            mask,
            initial_routes,
            budget,
            selection,
            domains,
            ledger,
            label="refresh_previous_partition",
            seed=seed,
        )
        if active is not None:
            current = active
            events.append({"action": "refresh", "accepted": True, **receipt})

    def metrics(bank):
        return ledger.metrics(bank, matrix, selection, domains)

    def floors():
        now = metrics(current)["domain_mse"]
        return {
            key: min(value, initial_metrics["domain_mse"][key])
            * (1 + settings["retention_relative"])
            + settings["retention_absolute_mse"]
            for key, value in now.items()
        }

    # A real fresh global fit can consolidate a previous topology after its
    # domains converge. The selected global fit above is charged to this owner.
    if len(current.blocks) > 1:
        candidate, receipt = fit_partition(
            matrix,
            mask,
            np.zeros(len(matrix), dtype=np.uint8),
            budget,
            selection,
            domains,
            ledger,
            label="consolidate",
            seed=seed,
            floors=floors(),
            compact=True,
            basis=single,
        )
        accepted = candidate is not None and (
            metrics(candidate)["mse"]
            <= metrics(current)["mse"] * (1 - settings["minimum_gain"])
            or len(candidate.to_bytes()) < len(current.to_bytes()) * 0.9
        )
        if accepted:
            current = candidate
        events.append({"action": "consolidate", "accepted": bool(accepted), **receipt})
    for round_index in range(settings["split_rounds"]):
        before = metrics(current)
        if (
            len(current.blocks) >= settings["max_cells"]
            or before["mse"] <= settings["near_lossless_mse"]
        ):
            events.append(
                {
                    "action": "trigger",
                    "search": False,
                    "reason": "capacity_or_near_lossless",
                }
            )
            break
        signal = split_signal(matrix, current, mask, ledger, settings)
        threshold = max(
            settings["signal_floor"],
            settings["signal_dimension_multiplier"] / matrix.shape[1],
        )
        if signal < threshold:
            events.append(
                {
                    "action": "trigger",
                    "search": False,
                    "reason": "diffuse_residual",
                    "signal": signal,
                    "threshold": threshold,
                }
            )
            break
        best, best_metric = None, before["mse"]
        for energy in (False, True):
            routes = split_route(
                matrix,
                current,
                selection,
                seed + round_index * 211,
                ledger,
                energy,
                settings["kmeans_iterations"],
            )
            if routes is None:
                continue
            candidate, receipt = fit_partition(
                matrix,
                mask,
                routes,
                budget,
                selection,
                domains,
                ledger,
                label=f"split_{round_index}_{'energy' if energy else 'raw'}",
                seed=seed,
                floors=floors(),
            )
            value = metrics(candidate)["mse"] if candidate is not None else None
            events.append(
                {"action": "split_candidate", "selection_mse": value, **receipt}
            )
            if candidate is not None and value < best_metric:
                best, best_metric = candidate, value
        accepted = best is not None and best_metric <= before["mse"] * (
            1 - settings["minimum_gain"]
        )
        events.append(
            {
                "action": "split",
                "accepted": bool(accepted),
                "before_mse": before["mse"],
                "after_mse": best_metric,
            }
        )
        if not accepted:
            break
        current = best
    if len(current.blocks) > 1:
        centers = np.stack([block.center for block in current.blocks]).astype(
            np.float64
        )
        pairs = [
            (float(np.sum((centers[a] - centers[b]) ** 2)), a, b)
            for a in range(len(centers))
            for b in range(a + 1, len(centers))
        ]
        _, left, right = min(pairs)
        merged = current.routes.copy()
        merged[merged == right] = left
        _, merged = np.unique(merged, return_inverse=True)
        merge_floors = floors()
        if len(current.blocks) == 2 and any(
            value > merge_floors[domain]
            for domain, value in initial_metrics["domain_mse"].items()
        ):
            candidate, receipt = (
                None,
                {
                    "reason": "already_fitted_global_cannot_meet_retention",
                    "search": False,
                },
            )
        else:
            candidate, receipt = fit_partition(
                matrix,
                mask,
                merged.astype(np.uint8),
                budget,
                selection,
                domains,
                ledger,
                label="merge",
                seed=seed,
                floors=merge_floors,
                compact=True,
                basis=single if len(current.blocks) == 2 else None,
            )
        accepted = (
            candidate is not None
            and len(candidate.to_bytes()) < len(current.to_bytes()) * 0.9
        )
        if accepted:
            current = candidate
        events.append({"action": "merge", "accepted": bool(accepted), **receipt})
    ledger.retain(current)
    report = {
        "schema": "hepta.memory.structure-owner.v3",
        "settings": settings,
        "budget_bytes": budget,
        "selection_sha256": hashlib.sha256(
            np.packbits(selection.ravel(), bitorder="little").tobytes()
        ).hexdigest(),
        "source_sha256": hashlib.sha256(matrix.tobytes()).hexdigest(),
        "hidden_queries_used_for_selection": False,
        "selection": metrics(current),
        "single_selection": initial_metrics,
        "deployed_bytes": len(current.to_bytes()),
        "cells": len(current.blocks),
        "ranks": [block.rank for block in current.blocks],
        "events": events,
        "work": ledger.summary(),
        "owner_wall_seconds": time.perf_counter() - started,
    }
    return current, report
