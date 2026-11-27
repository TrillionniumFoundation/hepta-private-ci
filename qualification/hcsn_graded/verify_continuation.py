"""Read-only verification of actual-migration all-visit continuation evidence."""

import hashlib
import json
from pathlib import Path
import sys

import numpy as np


def verify(directory):
    directory = Path(directory)
    summary = json.loads((directory / "SUMMARY.json").read_text())
    if (
        summary["original_threshold"] != 0.01
        or summary["threshold_unchanged"] is not True
        or summary["all_original_positions"] != 14336
        or summary["inputs_unchanged"] is not True
        or summary["source_sha256_before"] != summary["source_sha256_after"]
    ):
        raise ValueError("source/input/coverage/threshold evidence changed")
    panels = []
    for expected in summary["panels"]:
        n = expected["intervals"]
        path = directory / f"ALL_VISITS_n{n}.npz"
        if (
            hashlib.sha256(path.read_bytes()).hexdigest()
            != summary["output_sha256"][path.name]
        ):
            raise ValueError("original output digest changed")
        with np.load(path, allow_pickle=False) as archive:
            values = archive["rows"]
        if (
            values.shape != (14336, 11)
            or not np.isfinite(values).all()
            or len({tuple(row[:2]) for row in values}) != 14336
        ):
            raise ValueError("complete unique finite values required")
        scale = np.maximum(1, abs(values[:, 5]))
        error = abs(values[:, 2] - values[:, 5]) / scale
        components = np.c_[
            values[:, 2] - values[:, 3],
            values[:, 3] - values[:, 4],
            values[:, 4] - values[:, 5],
        ]
        np.testing.assert_allclose(components, values[:, 8:11], rtol=0, atol=1e-15)
        conservative = np.sum(abs(components), axis=1) / scale
        np.testing.assert_allclose(error, values[:, 6], rtol=0, atol=1e-16)
        np.testing.assert_allclose(conservative, values[:, 7], rtol=0, atol=1e-16)
        if (
            max(error) != expected["maximum_scaled_error"]
            or max(conservative) != expected["maximum_non_cancelling_scaled_error"]
            or int(sum(error > 0.01)) != expected["failures_at_original_0_01"]
            or int(sum(conservative > 0.01))
            != expected["non_cancelling_failures_at_0_01"]
        ):
            raise ValueError("retained arithmetic summary changed")
        panels.append(
            {
                "intervals": n,
                "positions": len(values),
                "max_non_cancelling_error": float(max(conservative)),
                "failures": int(sum(conservative > 0.01)),
            }
        )
    if {row["intervals"] for row in panels} != {256, 512}:
        raise ValueError("both declared refinement profiles required")
    return {
        "status": "passed_retained_arithmetic",
        "model_executions": 0,
        "panels": panels,
        "all_closed": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(sys.argv[1]), sort_keys=True))
