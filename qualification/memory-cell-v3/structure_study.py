"""Execute fixed-work structural controls and retain failures without gate edits."""

import copy
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from v3.factor_cell import FactorBank, canonical_matrix
from v3.structure import (
    DEFAULTS,
    WorkLedger,
    fit_adaptive,
    fit_partition,
    learned_routes,
    maximum_single_rank,
    read_metrics,
)


def synthetic_flows(seed, rows=256, columns=32):
    if rows % 4 or columns % 4 or columns < 8:
        raise ValueError("synthetic structural protocol needs four nonempty subspaces")
    rng = np.random.default_rng(seed)
    domain = np.repeat(np.arange(4), rows // 4)
    heterogeneous = np.zeros((rows, columns))
    for index in range(4):
        basis = np.linalg.qr(rng.normal(size=(columns // 4, 2)))[0].T
        local = rng.normal(size=(rows // 4, 2)) * 100
        heterogeneous[
            index * rows // 4 : (index + 1) * rows // 4,
            index * columns // 4 : (index + 1) * columns // 4,
        ] = local @ basis
    common = np.linalg.qr(rng.normal(size=(columns, 6)))[0].T
    converged = rng.normal(size=(rows, 6)) @ common * (100 * np.sqrt(2 / 6))
    low_basis = np.linalg.qr(rng.normal(size=(columns, 2)))[0].T
    stable = rng.normal(size=(rows, 2)) @ low_basis * 100
    random = rng.integers(-80, 81, size=(rows, columns), dtype=np.int32)
    permutation = rng.permutation(rows)

    def convert(value):
        return np.floor(value[permutation] + 0.5).astype("<i4")

    return {
        "heterogeneous": [convert(heterogeneous)],
        "convergent": [convert(heterogeneous), convert(converged)],
        "stable_lowrank": [convert(stable)],
        "random": [random[permutation]],
    }, domain[permutation]


def addresses(shape, seed, available=None):
    rng = np.random.default_rng(seed)
    mask = np.ones(shape, dtype=bool) if available is None else available
    selection = (rng.random(shape) < 0.25) & mask
    # Each row participates in writer-side selection. The hidden set remains
    # disjoint and contains only previously written coordinate facts.
    for row in range(shape[0]):
        known = np.flatnonzero(mask[row])
        if known.size and not selection[row].any():
            selection[row, known[0]] = True
    hidden = mask & ~selection
    return selection, hidden


def _fixed(matrix, selection, domains, mask, budget, k, seed, directory, work_target):
    started = time.perf_counter()
    ledger = WorkLedger(directory)
    candidates = []
    if k == 1:
        rank = maximum_single_rank(matrix.shape, budget, not mask.all())
        bank = ledger.fit(
            matrix,
            np.zeros(len(matrix), dtype=np.uint8),
            [rank],
            mask,
            "fixed_global_full_svd",
            seed,
        )
        candidates.append(bank)
    else:
        for energy in (False, True):
            routes = learned_routes(
                matrix,
                k,
                seed=seed,
                ledger=ledger,
                energy=energy,
                iterations=DEFAULTS["kmeans_iterations"],
            )
            candidate, _ = fit_partition(
                matrix,
                mask,
                routes,
                budget,
                selection,
                domains,
                ledger,
                label=f"fixed_{k}_{'energy' if energy else 'raw'}",
                seed=seed,
            )
            if candidate is not None:
                candidates.append(candidate)
    if not candidates:
        raise ValueError("fixed structure cannot satisfy declared artifact budget")
    best = min(
        candidates, key=lambda bank: ledger.metrics(bank, matrix, selection)["mse"]
    )
    efficient = best
    natural = {
        "selection": ledger.metrics(best, matrix, selection, domains),
        "deployed_bytes": len(best.to_bytes()),
        "work": copy.deepcopy(ledger.summary()),
        "owner_wall_seconds": time.perf_counter() - started,
    }
    matched_fits = 0
    # Repeating a full SVD is a deliberately strong optimization-work control:
    # it cannot improve the same mathematical optimum. It still executes and
    # incurs its real time/work, rather than crediting imaginary extra steps.
    while ledger.total_work < work_target:
        repeat = ledger.fit(
            matrix,
            best.routes,
            [block.rank for block in best.blocks],
            mask,
            "matched_work_repeat",
            seed,
        )
        if (
            ledger.metrics(repeat, matrix, selection)["mse"]
            < ledger.metrics(best, matrix, selection)["mse"]
        ):
            best = repeat
        matched_fits += 1
        if not ledger.records[-1]["fit"]["svd_work_proxy"]:
            break
    return (
        best,
        {
            "k": k,
            "selection": ledger.metrics(best, matrix, selection, domains),
            "deployed_bytes": len(best.to_bytes()),
            "matched_work_repeat_fits": matched_fits,
            "work": ledger.summary(),
            "efficient_before_work_padding": natural,
            "owner_wall_seconds": time.perf_counter() - started,
            "fixed_structure_scope": "fixed cell count; learned row routing and selection-based rank allocation are allowed at every write",
        },
        efficient,
    )


def _totals(episodes, arm, efficient=False):
    models = [
        episode[arm]["efficient_before_work_padding"] if efficient else episode[arm]
        for episode in episodes
    ]
    return {
        "hidden_mse": float(np.mean([model["hidden"]["mse"] for model in models])),
        "selection_mse": float(
            np.mean([model["selection"]["mse"] for model in models])
        ),
        "hidden_mae": float(np.mean([model["hidden"]["mae"] for model in models])),
        "hidden_exact": float(np.mean([model["hidden"]["exact"] for model in models])),
        "work_proxy": sum(model["work"]["total_work_proxy"] for model in models),
        "retained_artifact_bytes": sum(
            model["work"]["retained_artifact_bytes"] for model in models
        ),
        "retained_audit_metadata_bytes": sum(
            model["work"]["retained_audit_metadata_bytes"] for model in models
        ),
        "common_replay_and_owner_bytes": sum(
            episode["shared_state"]["charged_bytes_per_arm"] for episode in episodes
        ),
        "fit_seconds": sum(model["work"]["fit_wall_seconds"] for model in models),
        "owner_wall_seconds": sum(model["owner_wall_seconds"] for model in models),
        "mean_deployed_bytes": float(
            np.mean([model["deployed_bytes"] for model in models])
        ),
        "query_factor_multiplications": sum(
            model["hidden"]["read_factor_multiplications"] for model in models
        ),
    }


def evaluate_flow(
    name, matrices, domains, *, seed, budget, directory, settings=None, available=None
):
    settings = {**DEFAULTS, **(settings or {})}
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    episodes, previous = [], None
    for index, values in enumerate(matrices):
        matrix, mask = canonical_matrix(values, available)
        selection, hidden = addresses(matrix.shape, seed + index * 31 + 90_001, mask)
        bank, adaptive = fit_adaptive(
            matrix,
            budget=budget,
            selection=selection,
            domains=domains,
            directory=directory / f"episode-{index}" / "adaptive",
            seed=seed,
            initial_routes=None if previous is None else previous.routes,
            mask=mask,
            settings=settings,
        )
        artifact_path = (
            directory / f"episode-{index}" / "adaptive" / f"{bank.digest}.factor"
        )
        reloaded = FactorBank.load(artifact_path, bank.digest)
        hidden_rows, hidden_columns = np.nonzero(hidden)
        parity = reloaded.read(hidden_rows, hidden_columns) == bank.read(
            hidden_rows, hidden_columns
        )
        if not parity:
            raise AssertionError(
                "route migration changed hidden-coordinate reads after serialization"
            )
        prior_routes = (
            np.zeros(len(matrix), dtype=np.uint8)
            if previous is None
            else previous.routes
        )
        adaptive["route_migration"] = {
            "parent_artifact_sha256": None if previous is None else previous.digest,
            "selected_artifact_sha256": reloaded.digest,
            "changed_row_routes": int(
                np.count_nonzero(prior_routes != reloaded.routes)
            ),
            "hidden_coordinate_read_parity_after_reload": parity,
            "queries": len(hidden_rows),
            "address_contract": "stable global row/column identities; serialized route and local-row offsets change together",
        }
        previous = reloaded
        adaptive["hidden"] = read_metrics(bank, matrix, hidden, domains)
        episode = {
            "index": index,
            "matrix_sha256": hashlib.sha256(matrix.tobytes()).hexdigest(),
            "shape": list(matrix.shape),
            "adaptive": adaptive,
        }
        replay_path = directory / f"episode-{index}" / "shared-replay.i32"
        replay_path.write_bytes(matrix.tobytes())
        metadata = json.dumps(
            {
                "shape": list(matrix.shape),
                "matrix_sha256": episode["matrix_sha256"],
                "domains": domains.tolist(),
                "row_identity": "stable integer row index",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        (replay_path.parent / "shared-schema.json").write_bytes(metadata)
        selection_bytes = np.packbits(selection.ravel(), bitorder="little").tobytes()
        (replay_path.parent / "selection-addresses.bits").write_bytes(selection_bytes)
        available_bytes = (
            b""
            if mask.all()
            else np.packbits(mask.ravel(), bitorder="little").tobytes()
        )
        if available_bytes:
            (replay_path.parent / "availability.bits").write_bytes(available_bytes)
        episode["shared_state"] = {
            "source_replay_bytes": replay_path.stat().st_size,
            "schema_bytes": len(metadata),
            "selection_address_bytes": len(selection_bytes),
            "availability_bytes": len(available_bytes),
            "fixed_owner_binding_bytes_per_arm": 80,
            "charged_bytes_per_arm": replay_path.stat().st_size
            + len(metadata)
            + len(selection_bytes)
            + len(available_bytes)
            + 80,
            "same_serving_state_cap_per_arm": budget + 80,
            "scope": "parameter/route artifact cap plus fixed 80-byte source/generation/artifact binding; shared raw replay remains additional maintenance storage",
        }
        for arm_name, selected in (("adaptive", bank),):
            binding = (
                b"HMOWNER3"
                + bytes.fromhex(selected.digest)
                + bytes.fromhex(episode["matrix_sha256"])
                + (index + 1).to_bytes(8, "little")
            )
            (replay_path.parent / arm_name / "owner-binding.bin").write_bytes(binding)
        for k in (1, 2, 4):
            fixed, report, efficient = _fixed(
                matrix,
                selection,
                domains,
                mask,
                budget,
                k,
                seed,
                directory / f"episode-{index}" / f"fixed-{k}",
                adaptive["work"]["total_work_proxy"],
            )
            report["hidden"] = read_metrics(fixed, matrix, hidden, domains)
            report["efficient_before_work_padding"]["hidden"] = read_metrics(
                efficient, matrix, hidden, domains
            )
            binding = (
                b"HMOWNER3"
                + bytes.fromhex(efficient.digest)
                + bytes.fromhex(episode["matrix_sha256"])
                + (index + 1).to_bytes(8, "little")
            )
            (replay_path.parent / f"fixed-{k}" / "owner-binding.bin").write_bytes(
                binding
            )
            episode[f"fixed_{k}"] = report
        episodes.append(episode)
    totals = {
        arm: _totals(episodes, arm)
        for arm in ("adaptive", "fixed_1", "fixed_2", "fixed_4")
    }
    totals.update(
        {
            f"efficient_fixed_{k}": _totals(episodes, f"fixed_{k}", efficient=True)
            for k in (1, 2, 4)
        }
    )
    # This comparator sees the entire flow's selection results, a stronger
    # privilege than the online adaptive owner. Hidden metrics do not choose it.
    best_fixed = min(
        ("efficient_fixed_1", "efficient_fixed_2", "efficient_fixed_4"),
        key=lambda arm: totals[arm]["selection_mse"],
    )
    best_matched = min(
        ("fixed_1", "fixed_2", "fixed_4"), key=lambda arm: totals[arm]["selection_mse"]
    )
    normalizer = max(totals["fixed_1"]["hidden_mse"], 1.0)
    base_work = max(
        sum(
            episode["adaptive"]["work"]["records"][0]["fit"]["svd_work_proxy"]
            for episode in episodes
        ),
        1,
    )
    base_bytes = max(
        sum(
            episode["adaptive"]["work"]["records"][0]["fit"]["artifact_bytes"]
            for episode in episodes
        ),
        1,
    )
    for total in totals.values():
        total["retained_state_bytes"] = (
            total["retained_artifact_bytes"]
            + total["retained_audit_metadata_bytes"]
            + total["common_replay_and_owner_bytes"]
        )
        total["priced_loss"] = (
            total["hidden_mse"] / normalizer
            + settings["training_price"] * total["work_proxy"] / base_work
            + settings["retention_price"] * total["retained_state_bytes"] / base_bytes
        )
        total["horizon_work_proxy"] = {
            str(h): total["work_proxy"] + h * total["query_factor_multiplications"]
            for h in (1, 10, 100)
        }
    adaptive, fixed = totals["adaptive"], totals[best_fixed]
    gain = (fixed["hidden_mse"] - adaptive["hidden_mse"]) / max(
        fixed["hidden_mse"], 1.0
    )
    matched_gain = (totals[best_matched]["hidden_mse"] - adaptive["hidden_mse"]) / max(
        totals[best_matched]["hidden_mse"], 1.0
    )
    retention = all(
        all(
            value
            <= episode["adaptive"]["single_selection"]["domain_mse"][domain]
            * (1 + settings["retention_relative"])
            + settings["retention_absolute_mse"]
            for domain, value in episode["adaptive"]["selection"]["domain_mse"].items()
        )
        for episode in episodes
    )
    return {
        "name": name,
        "seed": seed,
        "budget_bytes": budget,
        "best_fixed_by_whole_flow_selection": best_fixed,
        "best_matched_work_fixed_by_whole_flow_selection": best_matched,
        "fixed_selection_privilege": "hindsight over complete selection stream; never hidden read outcomes",
        "relative_hidden_mse_gain_vs_best_fixed": gain,
        "hidden_mse_regret_vs_best_fixed": adaptive["hidden_mse"] - fixed["hidden_mse"],
        "priced_loss_regret_vs_best_fixed": adaptive["priced_loss"]
        - fixed["priced_loss"],
        "strict_new_flow_gate": bool(
            gain >= settings["minimum_gain"]
            and matched_gain >= settings["minimum_gain"]
            and adaptive["priced_loss"] < fixed["priced_loss"]
            and adaptive["priced_loss"] < totals[best_matched]["priced_loss"]
            and retention
        ),
        "selection_retention_floor_pass": retention,
        "pricing": {
            "error_normalizer": normalizer,
            "single_fit_work_normalizer": base_work,
            "single_artifact_bytes_normalizer": base_bytes,
            "training_price": settings["training_price"],
            "retention_price": settings["retention_price"],
            "work_scope": "actual SVD proxy plus measured algorithmic multiply counts; not hardware FLOPs",
            "retained_scope": "all unique fitted bases, selected artifacts, audit ledger metadata, plus shared raw replay/schema/selection state and fixed owner binding",
            "work_padding_scope": "causal optimization-work control only; efficient unpadded fixed costs separately gate deployment net benefit",
        },
        "totals": totals,
        "episodes": episodes,
    }


def run_structure(protocol, output, source_commit, seeds, *, development=False):
    started = time.perf_counter()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    spec = protocol.get("structure", {})
    settings = {key: value for key, value in spec.items() if key in DEFAULTS}
    rows, columns, budget = (
        spec.get("rows", 256),
        spec.get("columns", 32),
        spec.get("budget_bytes", 4096),
    )
    results = []
    for seed in seeds:
        flows, domains = synthetic_flows(seed, rows, columns)
        for name, matrices in flows.items():
            result = evaluate_flow(
                name,
                matrices,
                domains,
                seed=seed,
                budget=budget,
                directory=output / f"seed-{seed}" / name,
                settings=settings,
            )
            results.append(result)
            print(
                json.dumps(
                    {
                        "structure": name,
                        "seed": seed,
                        "best_fixed": result["best_fixed_by_whole_flow_selection"],
                        "mse_gain": result["relative_hidden_mse_gain_vs_best_fixed"],
                        "priced_regret": result["priced_loss_regret_vs_best_fixed"],
                        "gate": result["strict_new_flow_gate"],
                    }
                ),
                flush=True,
            )
    receipt = {
        "schema": "memory-cell-v3.structure-study.v1",
        "source_commit": source_commit,
        "development": bool(development),
        "seeds": list(seeds),
        "protocol": {**DEFAULTS, **spec},
        "v2_frozen_gate": "unchanged historical failure: 2/5 structural wins; this new family/protocol does not overwrite it",
        "scope": "coordinate-addressed written numeric memory and learned matrix subspaces; not universal language or exact random-bit compression",
        "convergent_specific_gate": all(
            result["strict_new_flow_gate"]
            for result in results
            if result["name"] == "convergent"
        ),
        "all_cases_strict_gate_diagnostic": all(
            result["strict_new_flow_gate"] for result in results
        ),
        "negative_controls": [
            result
            for result in results
            if result["name"] in ("stable_lowrank", "random")
        ],
        "results": results,
        "wall_seconds": time.perf_counter() - started,
    }
    (output / "structure.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    return receipt
