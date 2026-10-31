"""Read every frozen confirmation record; keep the original fit as the unit."""

import argparse
from collections import defaultdict
import gzip
import itertools
import json
from pathlib import Path

import numpy as np

from .protocol import SEEDS


PRIMARY = (
    ("first_passage/content_readout/hard", "direct/content_readout/hard"),
    ("first_passage/content_readout/hard", "clocked/content_readout/hard"),
    ("first_passage/content_readout/hard", "first_passage/baseline/hard"),
)
METRICS = ("registered_return", "task_return", "quality", "event_count", "decisions",
           "prediction_ns", "process_cpu_ns", "kernel_ns", "wire_bytes", "guard_fallbacks")


def fit_interval(values, alpha):
    values = np.asarray(values, dtype=np.float64)
    if values.shape != (5,):
        raise ValueError("all five registered fits are required")
    indexes = np.asarray(list(itertools.product(range(5), repeat=5)))
    boot = values[indexes].mean(-1)
    return np.quantile(boot, (alpha / 2, 1 - alpha / 2)).tolist()


def run(root, output):
    root, output = Path(root), Path(output)
    if output.exists():
        raise FileExistsError(output)
    summary = json.loads((root / "summary.json").read_text())
    records, sums, failures, identities = {}, defaultdict(lambda: defaultdict(float)), [], set()
    with gzip.open(root / "trajectories.jsonl.gz", "rt", encoding="utf8") as raw:
        for line in raw:
            row = json.loads(line)
            identity = (row["regime"], row["fit_seed"], row["world_seed"], row["arm"])
            if identity in identities:
                raise AssertionError("duplicate trajectory identity")
            identities.add(identity)
            if row["status"] != "complete":
                failures.append(row)
                continue
            records[identity] = {key: row[key] for key in METRICS}
            records[identity]["actions"] = [step["requested_action"] for step in row["steps"]]
            records[identity]["q"] = [step["prediction"]["q"] for step in row["steps"]]
            key = (row["regime"], row["arm"], row["fit_seed"])
            sums[key]["count"] += 1
            for metric in METRICS:
                sums[key][metric] += row[metric]
    if failures or len(identities) != summary["expected_attempts"]:
        raise AssertionError("incomplete confirmation; do not compute success-only inference")
    for recorded in summary["fit_arm_sums"]:
        key = (recorded["regime"], recorded["arm"], recorded["fit_seed"])
        for metric in ("count",) + METRICS:
            if not np.isclose(sums[key][metric], recorded[metric], rtol=2e-13, atol=1e-10):
                raise AssertionError("raw archive and run summary disagree")
    regimes = sorted({key[0] for key in sums})
    arms = sorted({key[1] for key in sums})
    tables, contrasts = [], []
    for regime in regimes:
        for arm in arms:
            fit_means = [{metric: sums[regime, arm, seed][metric] / sums[regime, arm, seed]["count"]
                          for metric in METRICS} for seed in SEEDS]
            mean = {metric: float(np.mean([fit[metric] for fit in fit_means])) for metric in METRICS}
            mean["accuracy"] = (mean["quality"] + 1) / 2
            tables.append(dict(regime=regime, arm=arm, fits=5, fit_means=fit_means, **mean))
        secondary = [
            (f"{mode}/content_readout/hard", f"{mode}/baseline/hard")
            for mode in ("direct", "continuous", "clocked")
        ] + [
            (f"{mode}/content_readout/hard", f"{mode}/content_readout/mean")
            for mode in ("direct", "continuous", "clocked", "first_passage")
        ] + [
            ("brownian_anchor/first_passage/hard", "brownian_anchor/clocked/hard"),
            ("brownian_anchor/clocked/hard", "brownian_anchor/continuous/hard"),
            ("unbounded/gaussian/hard", "brownian_anchor/continuous/hard"),
            ("unbounded/gaussian/mean", "brownian_anchor/continuous/mean"),
        ]
        for left, right in (*PRIMARY, *secondary):
            primary = (left, right) in PRIMARY
            differences = [sums[regime, left, seed]["registered_return"] / sums[regime, left, seed]["count"]
                           - sums[regime, right, seed]["registered_return"] / sums[regime, right, seed]["count"]
                           for seed in SEEDS]
            alpha = 0.05 / 6 if primary else 0.05
            contrasts.append({"regime": regime, "left": left, "right": right, "primary": primary,
                              "fit_differences": differences, "mean": float(np.mean(differences)),
                              "interval": fit_interval(differences, alpha), "confidence_level": 1 - alpha,
                              "positive_fits": sum(d > 0 for d in differences),
                              "sampling_unit": "fit and its complete paired world block"})
    identity_pairs, max_q_error, max_return_error = 0, 0.0, 0.0
    for identity, left in records.items():
        regime, seed, world, arm = identity
        if not arm.startswith("unbounded/gaussian/"):
            continue
        right = records[regime, seed, world, arm.replace("/gaussian/", "/probit/")]
        if left["actions"] != right["actions"]:
            raise AssertionError("algebraically identical Gaussian/probit policies diverged")
        max_q_error = max(max_q_error, float(np.max(np.abs(np.asarray(left["q"]) - np.asarray(right["q"])))))
        max_return_error = max(max_return_error, abs(left["registered_return"] - right["registered_return"]))
        identity_pairs += 1
    result = {"schema": "hepta.contract-closure.analysis.v1", "freeze_sha256": summary["freeze_sha256"],
              "attempts": len(identities), "failures": 0, "tables": tables, "contrasts": contrasts,
              "gaussian_probit_identity": {"paired_trajectories": identity_pairs,
                                           "maximum_q_difference": max_q_error,
                                           "maximum_return_difference": max_return_error},
              "inference_limit": "Five previously trained fits; paired fresh worlds. Bootstrap intervals are descriptive finite-fit evidence, not proof of broad-task superiority.",
              "cost_limit": "Shared-host Python process costs; actual artifact/native process costs are reported separately."}
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(args.root, args.output)
