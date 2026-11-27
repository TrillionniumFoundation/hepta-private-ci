"""Read-only arithmetic verifier for every retained actual-law cost row."""

import hashlib
import json
from pathlib import Path
import numpy as np


def main():
    root = Path(__file__).resolve().parent
    repo = root.parents[1]
    folder = root / "evidence/cost-attempt002-audit/outputs"
    s = json.loads((folder / "SUMMARY.json").read_text())
    assert s["inputs_unchanged"] and s["threshold_unchanged"]
    assert s["original_scaled_continuation_gate"] == 0.01
    assert s["source_sha256_before"] == s["source_sha256_after"]
    for recorded, expected in s["source_sha256_before"].items():
        relative = "qualification/" + recorded.split("/qualification/", 1)[1]
        assert hashlib.sha256((repo / relative).read_bytes()).hexdigest() == expected
    for name, expected in s["output_sha256"].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == expected
    reference_path = repo / "qualification/hcsn_graded/evidence/actual-migrated-continuation-attempt002/ALL_VISITS_n512.npz"
    assert hashlib.sha256(reference_path.read_bytes()).hexdigest() == "af6bb4f42bc4a89f1e9fa4a42f824544b230e8342b5585f88d9459ead4292af9"
    with np.load(reference_path, allow_pickle=False) as a:
        old = a["rows"].copy()
    total_rows = 0
    for profile, parts in s["profile_parts"].items():
        data = []
        for part in parts:
            path = folder / part["file"]
            assert path.stat().st_size == part["bytes"] <= 1048576
            assert hashlib.sha256(path.read_bytes()).hexdigest() == part["sha256"]
            with np.load(path, allow_pickle=False) as a:
                columns = a["columns"].tolist()
                value = a["rows"].copy()
            assert len(value) == part["positions"]
            assert value[0, 0] == part["first_global_position"]
            data.append(value)
        values = np.concatenate(data)
        assert values.shape == (14336, 24) and np.isfinite(values).all()
        def col(name):
            return values[:, columns.index(name)]
        np.testing.assert_array_equal(col("global_position"), np.arange(14336))
        np.testing.assert_array_equal(col("published_halfline_reference"), old[:, 5])
        np.testing.assert_array_equal(col("published_exp512_candidate"), old[:, 2])
        a, b, c, d = [col(name) for name in
                      ("halfline_original", "finite_original", "migrated_finite", "candidate_migrated")]
        np.testing.assert_array_equal(col("migration_signed"), c - b)
        np.testing.assert_array_equal(col("operator_reset_signed"), d - c)
        np.testing.assert_array_equal(col("upper_truncation_signed"), b - a)
        scale = np.maximum(1, np.abs(old[:, 5]))
        total = np.abs(d - old[:, 5]) / scale
        conservative = (np.abs(c - b) + np.abs(d - c) + np.abs(b - a)
                        + np.abs(a - old[:, 5])) / scale
        np.testing.assert_array_equal(col("scaled_total_error"), total)
        np.testing.assert_array_equal(col("scaled_non_cancelling_error"), conservative)
        report = s["profiles"][profile]
        assert report["positions"] == len(values)
        assert report["maximum_scaled_total_error"] == total.max()
        assert report["maximum_scaled_non_cancelling_error"] == conservative.max()
        assert report["failures_at_unchanged_0_01"] == (total > 0.01).sum()
        assert report["non_cancelling_failures_at_unchanged_0_01"] == (conservative > 0.01).sum()
        total_rows += len(values)
    assert s["training_executions"] == s["filter_replays"] == s["dde_rollouts"] == 0
    assert len(json.loads((folder / "LINEAGE.json").read_text())) == 384
    assert len(json.loads((folder / "PHYSICS.json").read_text())) == 184
    print(json.dumps({"read_only": True, "retained_profile_posterior_rows": total_rows,
                      "new_model_calls": 0, "new_kernel_calls": 0,
                      "original_threshold": 0.01, "status": "HOLD_NO_GO"}))


if __name__ == "__main__":
    main()
