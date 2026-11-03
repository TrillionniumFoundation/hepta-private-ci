"""Actual candidate fitting and selection-only byte-budget allocation."""

import time

import numpy as np

from .factor_cell import (
    BLOCK_HEADER,
    HEADER,
    FactorBank,
    canonical_matrix,
    packed_routes,
)


def coordinate_split(shape, seed, fraction=0.2):
    if not 0 < fraction < 1 or np.prod(shape) < 2:
        raise ValueError("selection/hidden split requires two nonempty sets")
    order = np.random.default_rng(seed).permutation(int(np.prod(shape)))
    count = min(len(order) - 1, max(1, int(len(order) * fraction)))
    selection = np.zeros(shape, dtype=bool)
    selection.flat[order[:count]] = True
    return selection, ~selection


def kmeans_routes(matrix, cells, seed, iterations=20):
    """Seeded k-means++ plus Lloyd fitting; no hidden evaluation input."""
    started = time.perf_counter()
    values, _ = canonical_matrix(matrix)
    x = values.astype(np.float64)
    n, d = x.shape
    if not 1 <= cells <= min(n, 256) or not 1 <= iterations <= 100:
        raise ValueError("invalid codebook fitting budget")
    rng = np.random.default_rng(seed)
    centers = [x[int(rng.integers(n))].copy()]
    nearest = np.square(x - centers[0]).sum(axis=1)
    initialization_terms = n * d
    for _ in range(1, cells):
        index = (
            int(rng.choice(n, p=nearest / nearest.sum()))
            if nearest.sum()
            else int(rng.integers(n))
        )
        centers.append(x[index].copy())
        nearest = np.minimum(nearest, np.square(x - centers[-1]).sum(axis=1))
        initialization_terms += n * d
    centers = np.asarray(centers)
    previous, executed = None, 0
    for _ in range(iterations):
        distances = np.maximum(
            0.0,
            np.square(x).sum(axis=1)[:, None]
            + np.square(centers).sum(axis=1)[None, :]
            - 2 * x @ centers.T,
        )
        routes = np.argmin(distances, axis=1)
        counts = np.bincount(routes, minlength=cells)
        for empty in np.flatnonzero(counts == 0):
            errors = distances[np.arange(n), routes].copy()
            errors[counts[routes] <= 1] = -np.inf
            chosen = int(np.argmax(errors))
            counts[routes[chosen]] -= 1
            routes[chosen] = empty
            counts[empty] += 1
        centers = np.stack([x[routes == group].mean(axis=0) for group in range(cells)])
        executed += 1
        if previous is not None and np.array_equal(previous, routes):
            break
        previous = routes.copy()
    return routes.astype(np.uint8), {
        "algorithm": "kmeans++ and Lloyd; empty cells reassigned deterministically",
        "cells": cells,
        "seed": int(seed),
        "iterations": executed,
        "distance_component_terms": initialization_terms + executed * n * cells * d,
        "distance_terms_definition": "coordinate components contributing to initialization and Lloyd distances, not FLOPs",
        "fit_wall_seconds": time.perf_counter() - started,
    }


def fit_partition(matrix, routes, selection, *, seed=0, rank_limit=None):
    values, observed = canonical_matrix(matrix)
    route = np.asarray(routes)
    if selection.shape != values.shape or selection.dtype != np.dtype(bool):
        raise ValueError("selection coordinates do not match written source")
    if route.shape != (len(values),) or set(route.tolist()) != set(
        range(int(route.max()) + 1)
    ):
        raise ValueError("partition identities must be contiguous and nonempty")
    candidates, receipts = [], []
    for group in range(int(route.max()) + 1):
        rows = route == group
        local = values[rows]
        maximum = (
            min(local.shape)
            if rank_limit is None
            else min(min(local.shape), rank_limit)
        )
        choices = []
        for rank in range(maximum + 1):
            fitted, receipt = FactorBank.fit(local, ranks=[rank], seed=seed)
            errors = fitted.reconstruct()[selection[rows]] - local[
                selection[rows]
            ].astype(np.int64)
            choices.append(
                {
                    "block": fitted.blocks[0],
                    "rank": rank,
                    "selection_squared_error": float(
                        np.square(errors.astype(np.float64)).sum()
                    ),
                    "cost": 2 * rank * (len(local) + values.shape[1]),
                }
            )
            receipts.append(receipt | {"partition_cell": group, "candidate_rank": rank})
        candidates.append(choices)
    return {
        "routes": route.copy(),
        "mask": observed,
        "candidates": candidates,
        "receipts": receipts,
        "cached_parameter_bytes": sum(
            choice["block"].center.nbytes
            + choice["block"].record_factors.nbytes
            + choice["block"].decoder.nbytes
            for choices in candidates
            for choice in choices
        ),
    }


def allocate_partition(fitted, budget):
    """Exact multiple-choice knapsack over selection error; hidden never enters."""
    route, mask, candidates = fitted["routes"], fitted["mask"], fitted["candidates"]
    groups, d = len(candidates), mask.shape[1]
    base = (
        HEADER.size
        + len(packed_routes(route, (groups - 1).bit_length()))
        + groups * (BLOCK_HEADER.size + 4 * d)
    )
    if not mask.all():
        base += (mask.size + 7) // 8
    if type(budget) is not int or budget < base:
        return None
    units = (budget - base) // 2
    possible = sum(max(c["cost"] for c in group) // 2 for group in candidates)
    units = min(units, possible)
    previous = np.full(units + 1, np.inf)
    previous[0] = 0.0
    traces = []
    for group in candidates:
        following = np.full_like(previous, np.inf)
        trace = np.full(units + 1, -1, dtype=np.int16)
        for choice in group:
            cost = choice["cost"] // 2
            if cost > units:
                continue
            proposal = previous[: units + 1 - cost] + choice["selection_squared_error"]
            current = following[cost:]
            better = proposal < current
            current[better] = proposal[better]
            trace[cost:][better] = choice["rank"]
        previous = following
        traces.append(trace)
    spent = int(np.argmin(previous))
    error = float(previous[spent])
    if not np.isfinite(error):
        return None
    ranks = []
    for group, trace in reversed(list(zip(candidates, traces, strict=True))):
        rank = int(trace[spent])
        if rank < 0:
            raise RuntimeError("invalid allocation traceback")
        ranks.append(rank)
        spent -= group[rank]["cost"] // 2
    ranks.reverse()
    bank = FactorBank(
        route,
        mask,
        tuple(
            group[rank]["block"] for group, rank in zip(candidates, ranks, strict=True)
        ),
    )
    if len(bank.to_bytes()) > budget:
        raise RuntimeError("serialized model exceeded selected byte budget")
    return bank, {
        "ranks": ranks,
        "selection_squared_error": error,
        "budget_bytes": budget,
        "artifact_bytes": len(bank.to_bytes()),
        "unused_budget_bytes": budget - len(bank.to_bytes()),
        "selection_rule": "minimum selection-coordinate squared error under exact serialized-byte budget; ties prefer fewer bytes",
    }


def fit_work(receipts, route_receipts=()):
    return {
        "candidate_fits": len(receipts),
        "svd_calls": sum(r["svd_calls"] for r in receipts),
        "svd_work_proxy": sum(r["svd_work_proxy"] for r in receipts),
        "fit_wall_seconds": sum(r["fit_wall_seconds"] for r in receipts)
        + sum(r["fit_wall_seconds"] for r in route_receipts),
        "kmeans_distance_component_terms": sum(
            r.get("distance_component_terms", 0) for r in route_receipts
        ),
        "kmeans_iterations": sum(r.get("iterations", 0) for r in route_receipts),
    }


def equal_work_control(matrix, bank, base_work, target_work, max_repeats=256):
    """Execute additional global fits to meet both reported work and time floors."""
    receipts = []
    svd_work, seconds = base_work["svd_work_proxy"], base_work["fit_wall_seconds"]
    while (
        svd_work < target_work["svd_work_proxy"]
        or seconds < target_work["fit_wall_seconds"]
    ) and len(receipts) < max_repeats:
        repeated, receipt = FactorBank.fit(matrix, ranks=[bank.blocks[0].rank])
        if repeated.digest != bank.digest:
            raise RuntimeError("deterministic full-SVD control changed fitted model")
        receipts.append(receipt)
        svd_work += receipt["svd_work_proxy"]
        seconds += receipt["fit_wall_seconds"]
    return {
        "extra_fits": len(receipts),
        "actual_total_svd_work_proxy": svd_work,
        "actual_fit_wall_seconds": seconds,
        "target_svd_work_proxy": target_work["svd_work_proxy"],
        "target_fit_wall_seconds": target_work["fit_wall_seconds"],
        "work_floor_met": svd_work >= target_work["svd_work_proxy"]
        and seconds >= target_work["fit_wall_seconds"],
        "maximum_extra_fits": max_repeats,
        "same_artifact_sha256": bank.digest,
        "interpretation": "Repeated exact global SVD fitting cannot improve this fixed-rank least-squares solution; measured work is charged, not relabeled as learning progress.",
        "receipts": receipts,
    }
