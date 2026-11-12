"""Read-only arithmetic/coverage verification of the retained all-visit arrays."""

import hashlib
import json
from pathlib import Path
import sys

import numpy as np


def verify(directory):
    directory = Path(directory)
    summary = json.loads((directory / "SUMMARY.json").read_text())
    if (
        summary["original_scaled_value_error_limit"] != 0.01
        or summary["original_threshold_unchanged"] is not True
        or summary["source_sha256_before"] != summary["source_sha256_after"]
        or summary["audited_positions"] != 14336
        or summary["training_rows"] != 384
    ):
        raise ValueError(
            "source identity, original threshold or complete coverage changed"
        )
    roster = {
        (seed, arm)
        for seed in (11, 23, 37)
        for arm in ("c0_b0", "c0_b1", "c1_b0", "c1_b1")
    }
    if (
        len(summary["arms"]) != 12
        or {(a["seed"], a["arm"]) for a in summary["arms"]} != roster
    ):
        raise ValueError("original arm roster changed")
    panels = []
    for n in (128, 256, 512):
        name = f"ALL_VISITS_{n}.npz"
        path = directory / name
        if (
            hashlib.sha256(path.read_bytes()).hexdigest()
            != summary["array_sha256"][name]
        ):
            raise ValueError("retained array digest mismatch")
        with np.load(path, allow_pickle=False) as archive:
            rows, columns = archive["rows"], archive["columns"].tolist()
        expected = [
            "arm_index",
            "visit_index",
            "update_index",
            "position",
            "intervals",
            "candidate",
            "original_80digit_reference",
            "finite_continuum",
            "halfline_recheck",
            "scaled_error",
            "non_cancelling_scaled_error",
            "original_projected_scaled_error",
        ]
        if (
            columns != expected
            or rows.shape != (14336, len(expected))
            or not np.isfinite(rows).all()
        ):
            raise ValueError("complete finite retained rows required")
        if np.any(rows[:, 4] != n) or len({tuple(row[:2]) for row in rows}) != 14336:
            raise ValueError("duplicated visit identity or wrong grid")
        scale = np.maximum(1.0, abs(rows[:, 6]))
        error = abs(rows[:, 5] - rows[:, 6]) / scale
        conservative = (
            abs(rows[:, 5] - rows[:, 7]) + abs(rows[:, 7] - rows[:, 6])
        ) / scale
        np.testing.assert_allclose(error, rows[:, 9], atol=1e-16, rtol=0)
        np.testing.assert_allclose(conservative, rows[:, 10], atol=1e-16, rtol=0)
        if max(abs(rows[:, 8] - rows[:, 6])) > 5e-12 or np.any(rows[:, 11] <= 0.01):
            raise ValueError("reference recheck or original negative result changed")
        for arm_index, arm in enumerate(summary["arms"]):
            part = rows[rows[:, 0] == arm_index]
            recorded = arm["grids"][str(n)]
            if (
                len(part) != arm["visits"]
                or set(part[:, 1]) != set(range(arm["visits"]))
                or max(part[:, 9]) != recorded["maximum_scaled_value_error"]
                or max(part[:, 10]) != recorded["maximum_non_cancelling_scaled_error"]
            ):
                raise ValueError("per-arm coverage or arithmetic summary changed")
        panels.append(
            {
                "intervals": n,
                "visits": len(rows),
                "max_scaled_error": float(max(error)),
                "max_non_cancelling_scaled_error": float(max(conservative)),
                "failures_at_original_0_01": int(sum(conservative > 0.01)),
            }
        )
    return {
        "status": "passed_retained_array_arithmetic",
        "model_executions": 0,
        "scientific_admission": "HOLD_NO_GO",
        "panels": panels,
    }


if __name__ == "__main__":
    print(json.dumps(verify(sys.argv[1]), sort_keys=True))
