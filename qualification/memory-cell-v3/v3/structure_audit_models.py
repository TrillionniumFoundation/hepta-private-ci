"""Read saved factor models and independently sum recorded training costs."""

import struct

import numpy as np

from .factor_cell import FactorBank
from .native_structure_audit_core import _prefix, require, same, sha


def _bank(reader, directory, digest):
    payload = reader.raw(_prefix(directory, f"{digest}.factor"))
    return FactorBank.from_bytes(payload, expected_sha256=digest)


def _metrics(bank, matrix, addresses, domains):
    rows, columns = np.nonzero(addresses)
    require(len(rows) > 0, "empty independent evaluation query set")
    predictions = bank.read(rows, columns)
    require(
        all(value is not None for value in predictions),
        "available coordinate refused by saved factor artifact",
    )
    prediction = np.asarray(predictions, dtype=np.float64)
    require(
        np.array_equal(prediction, bank.reconstruct()[rows, columns]),
        "coordinate router differs from full artifact reconstruction",
    )
    error = prediction - matrix[rows, columns]
    squared = error * error
    return {
        "count": int(len(rows)),
        "mse": float(squared.mean()),
        "mae": float(np.abs(error).mean()),
        "exact": float(np.count_nonzero(error == 0) / len(rows)),
        "read_factor_multiplications": int(
            sum(bank.blocks[int(bank.routes[row])].rank for row in rows)
        ),
        "domain_mse": {
            str(int(domain)): float(squared[domains[rows] == domain].mean())
            for domain in np.unique(domains[rows])
        },
    }


def _ledger(reader, directory, work, matrix, mask, *, snapshot_index):
    stored = reader.json(_prefix(directory, f"ledger-{snapshot_index}.json"))
    same(stored, work["records"], "cost ledger records")
    fits = [item["fit"] for item in stored if "fit" in item]
    seen = {item["fit"]["artifact_sha256"] for item in stored if "fit" in item}
    seen.update(
        item["allocation"]["deployed_sha256"] for item in stored if "allocation" in item
    )
    same(
        set(work["retained_by_sha256"]),
        seen,
        "retained artifact identities derive from actual fit/allocation records",
    )
    source_digest = sha(
        matrix.astype("<i4").tobytes()
        + np.packbits(mask.ravel(), bitorder="little").tobytes()
    )
    artifact_sizes, svd_work, reconstruction_work, svd_calls = {}, 0, 0, 0
    for digest, expected_size in work["retained_by_sha256"].items():
        payload = reader.raw(_prefix(directory, f"{digest}.factor"))
        same(sha(payload), digest, "cost ledger artifact identity")
        same(len(payload), expected_size, "cost ledger artifact byte count")
        artifact_sizes[digest] = len(payload)
    for fit in fits:
        bank = _bank(reader, directory, fit["artifact_sha256"])
        require(
            bank.shape == matrix.shape and np.array_equal(bank.mask, mask),
            "fitted artifact source shape/mask differs",
        )
        same(fit["source_sha256"], source_digest, "fit source frontier")
        same(len(bank.to_bytes()), fit["artifact_bytes"], "fitted serialized bytes")
        same(bank.parameter_bytes, fit["parameter_bytes"], "fitted tensor bytes")
        require(len(bank.blocks) == len(fit["blocks"]), "fit block count differs")
        local_svd, local_reconstruction, local_calls = 0, 0, 0
        for block, record in zip(bank.blocks, fit["blocks"], strict=True):
            n, d, rank = len(block.record_factors), matrix.shape[1], block.rank
            same(
                [record["rows"], record["columns"], record["rank"]],
                [n, d, rank],
                "fit block shape",
            )
            require(
                type(record["svd_calls"]) is int and record["svd_calls"] >= 0,
                "invalid recorded SVD call count",
            )
            if mask.all():
                same(record["svd_calls"], int(rank > 0), "complete-data SVD call count")
            local_calls += record["svd_calls"]
            local_svd += record["svd_calls"] * n * d * min(n, d)
            local_reconstruction += (record["svd_calls"] + 1) * n * d * rank
        same(local_calls, fit["svd_calls"], "fit SVD calls")
        same(local_svd, fit["svd_work_proxy"], "fit SVD work from tensor dimensions")
        same(
            local_reconstruction,
            fit["post_svd_reconstruction_mac_proxy"],
            "fit reconstruction work from tensor dimensions",
        )
        error = (bank.reconstruct()[mask] - matrix[mask]).astype(np.float64)
        same(float(np.mean(error**2)), fit["written_mse"], "saved fit written MSE")
        same(float(np.mean(np.abs(error))), fit["written_mae"], "saved fit written MAE")
        same(
            float(np.mean(error == 0)),
            fit["written_exact_accuracy"],
            "saved fit exact accuracy",
        )
        svd_calls += local_calls
        svd_work += local_svd
        reconstruction_work += local_reconstruction
    diagnostic = work["diagnostic_multiply_work_proxy"]
    require(
        type(diagnostic) is int and diagnostic >= 0, "invalid diagnostic work counter"
    )
    audit_bytes = sum(
        len(reader.raw(_prefix(directory, f"ledger-{index}.json")))
        for index in range(snapshot_index + 1)
    )
    recomputed = {
        "fit_calls": len(fits),
        "svd_calls": svd_calls,
        "svd_work_proxy": svd_work,
        "post_svd_reconstruction_mac_proxy": reconstruction_work,
        "total_work_proxy": svd_work + reconstruction_work + diagnostic,
        "fit_wall_seconds": sum(fit["fit_wall_seconds"] for fit in fits),
        "retained_artifact_bytes": sum(artifact_sizes.values()),
        "retained_audit_metadata_bytes": audit_bytes,
        "unique_artifacts_written": len(artifact_sizes),
        "temporary_factor_peak_bytes": max(
            (fit["artifact_bytes"] for fit in fits), default=0
        ),
    }
    for key, value in recomputed.items():
        same(value, work[key], f"cost ledger sum {key}")
    return recomputed


def _owner_binding(reader, directory, source_digest, generation):
    payload = reader.raw(_prefix(directory, "owner-binding.bin"))
    require(
        len(payload) == 80 and payload[:8] == b"HMOWNER3",
        "invalid structural owner binding",
    )
    require(
        payload[40:72].hex() == source_digest
        and struct.unpack_from("<Q", payload, 72)[0] == generation,
        "structural owner source/generation binding differs",
    )
    return payload[8:40].hex()


def _model_check(
    reader,
    directory,
    bank,
    report,
    matrix,
    mask,
    selection,
    domains,
    budget,
    snapshot_index,
):
    require(
        bank.shape == matrix.shape and np.array_equal(bank.mask, mask),
        "deployed source dimensions or availability differ",
    )
    require(len(bank.to_bytes()) <= budget, "deployed artifact exceeds declared budget")
    same(len(bank.to_bytes()), report["deployed_bytes"], "deployed artifact bytes")
    selected, hidden = (
        _metrics(bank, matrix, selection, domains),
        _metrics(bank, matrix, mask & ~selection, domains),
    )
    same(selected, report["selection"], "independent selection metrics")
    same(hidden, report["hidden"], "independent hidden/domain metrics")
    work = _ledger(
        reader, directory, report["work"], matrix, mask, snapshot_index=snapshot_index
    )
    return {
        "artifact_sha256": bank.digest,
        "selection": selected,
        "hidden": hidden,
        "work": work,
        "deployed_bytes": len(bank.to_bytes()),
        "owner_wall_seconds": report["owner_wall_seconds"],
    }
