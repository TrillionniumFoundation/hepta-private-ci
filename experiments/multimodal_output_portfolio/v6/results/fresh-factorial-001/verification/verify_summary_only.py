"""Read-only consistency check of received summaries; not a full row/seal audit."""

import argparse
import hashlib
import json
from pathlib import Path
import platform

import numpy as np


EXPECTED = {
    "ndu-fresh-summary.json": "d8ec3a2430cd3f491c1ae58fbd88371d8ef62fc6c3f57a871e1dfaab90398a88",
    "ndu-fresh-evidence-v1-harness-summary.json": "05cfabb069ce63ff49b4c1d9c5509f9d30b3d6f306cbef18266ad765fcf1f746",
    "ndu-fresh-execution-v1-result.json": "d29409b8059b4a6b1efa21cd0f50a2997d0273edd8aad5469df373d3933dcc96",
}
ARMS = ("b0g0", "b0g1", "b1g0", "b1g1")
NAMES = ("base_main_effect", "gate_main_effect", "interaction")
STRATA = ("clean", "occlusion", "missing", "heavy_noise", "wrong_hint", "missing_no_hint")


def main(directory, output):
    root, target = Path(directory), Path(output)
    records, identities = {}, {}
    for name, expected in EXPECTED.items():
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ValueError("ordinary original summary file required")
        data = path.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise ValueError("received original identity differs: " + name)
        records[name] = json.loads(data)
        identities[name] = {"bytes": len(data), "sha256": actual}
    summary, harness, execution = [records[name] for name in EXPECTED]
    source = summary["source_differences"]
    assert [row["case_id"] for row in source] == [f"future-{i:04}" for i in range(120, 180)]
    assert [row["corruption"] for row in source] == [STRATA[i % 6] for i in range(60)]
    means = np.array([[row["fixed_seed_mean_losses"][arm] for arm in ARMS] for row in source])
    assert means.shape == (60, 4) and np.isfinite(means).all()
    differences = np.column_stack((
        (means[:, 2] + means[:, 3] - means[:, 0] - means[:, 1]) / 2,
        (means[:, 1] + means[:, 3] - means[:, 0] - means[:, 2]) / 2,
        means[:, 3] - means[:, 2] - means[:, 1] + means[:, 0],
    ))
    stored = np.array([[row[name] for name in NAMES] for row in source])
    assert np.max(np.abs(differences - stored)) <= 1e-15
    rng = np.random.default_rng(431125)
    draws = np.concatenate([
        rng.choice(np.array([i for i in range(60) if i % 6 == stratum]), (10000, 10), replace=True)
        for stratum in range(6)
    ], axis=1)
    bootstrap = differences[draws].mean(axis=1)
    intervals = np.quantile(bootstrap, [.05 / 6, 1 - .05 / 6], axis=0, method="linear")
    primary = {}
    for i, name in enumerate(NAMES):
        row = summary["primary"][name]
        estimate = float(differences[:, i].mean())
        lower, upper = map(float, intervals[:, i])
        delta = max(abs(estimate - row["estimate"]), abs(lower - row["interval"][0]), abs(upper - row["interval"][1]))
        assert delta <= 1e-15
        assert row["direction"] == ("negative" if upper < 0 else "positive" if lower > 0 else "unresolved")
        assert row["main_effect_improvement"] == (None if name == "interaction" else bool(upper < 0))
        primary[name] = {"estimate": estimate, "interval": [lower, upper], "maximum_absolute_difference": delta}
    assert harness["complete"] is True and execution["exit"] == 0
    assert harness["automatic_retries"] == execution["automatic_retries"] == 0
    assert [row["stage"] for row in harness["stages"]] == ["prepare", "bootstrap", "gates", "inference", "replay", "evaluate"]
    for row in harness["stages"]:
        assert row["returncode"] == 0 and row["failure"] is None and row["automatic_retries"] == 0
        assert row["command"][row["command"].index("--source-commit") + 1] == execution["published_head"]
    total_cpu = sum(row["cpu_ns_including_import_and_exit"] for row in harness["stages"])
    total_wall = sum(row["wall_ns_including_import_and_exit"] for row in harness["stages"])
    assert total_cpu == harness["total_stage_cpu_ns"]
    assert 0 <= harness["total_wall_ns"] - total_wall < 1_000_000_000
    assert harness["total_wall_ns"] < 1800 * 10**9
    assert summary["binding"]["source_commit"] == execution["published_head"]
    assert summary["binding"]["source_owner_directory"] == execution["owner"]
    result = {
        "schema": "hepta.ndu-fresh.summary-only-review.v1",
        "scope": "Internal source-difference/summary and outer execution receipt consistency only; raw scored rows, complete seals, model files and state/output bytes not yet inspected by this check",
        "status": "passed_with_full_evidence_review_pending",
        "inputs": identities,
        "analysis_environment": {"python": platform.python_version(), "numpy": np.__version__},
        "source_pair_differences_checked": 60,
        "primary_recomputed_from_summary_source_differences": primary,
        "stage_cpu_sum_ns": total_cpu,
        "stage_wall_sum_ns": total_wall,
        "harness_outside_stage_wall_ns": harness["total_wall_ns"] - total_wall,
        "all_six_stage_receipts_report_exit_zero": True,
        "fresh_model_executed": False,
        "final_targets_opened": False,
        "full_independent_reproduction_claimed": False,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x") as f:
        json.dump(result, f, sort_keys=True, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps({"status": result["status"], "maximum_primary_difference": max(x["maximum_absolute_difference"] for x in primary.values()), "output": str(target)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--output", required=True)
    main(**vars(parser.parse_args()))
