"""Recompute historical audio metrics from raw outputs and check causal inputs."""

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np


def audit(output):
    records = json.loads((output / "PREDICTIONS.json").read_text())
    summary = json.loads((output / "SUMMARY.json").read_text())
    freeze = json.loads((output / "FREEZE.json").read_text())
    candidates = json.loads((output / "CANDIDATES.json").read_text())
    assert len(candidates) == 160
    assert min(candidates, key=lambda x: x["validation"]["nll"]) == freeze["selected"]
    assert hashlib.sha256((output / "selected_audio_model.npz").read_bytes()).hexdigest() == freeze["selected_model_sha256"]
    grouped, cases = {}, set()
    for row in records:
        identity = (row["split"], row["model"], row["recording"], row["prefix"])
        assert identity not in cases
        cases.add(identity)
        p, label = row["probabilities"], row["label"]
        assert len(p) == 6 and type(label) is int and 0 <= label < 6
        assert all(type(x) in (int, float) and math.isfinite(x) and 0 <= x <= 1 for x in p)
        assert math.isclose(sum(p), 1, abs_tol=1e-12)
        grouped.setdefault((row["split"], row["model"], str(row["prefix"])), []).append((row["recording"], row["actor"], label, p))
    checks = 0
    for (split, model, prefix), rows in grouped.items():
        expected = summary["by_split_model_prefix"][split][model][prefix]
        actual = {"count": len(rows),
                  "accuracy": sum(max(range(6), key=x[3].__getitem__) == x[2] for x in rows) / len(rows),
                  "nll": -sum(math.log(max(x[3][x[2]], 1e-15)) for x in rows) / len(rows)}
        assert actual["count"] == expected["count"]
        assert math.isclose(actual["accuracy"], expected["accuracy"], abs_tol=1e-14)
        assert math.isclose(actual["nll"], expected["nll"], abs_tol=1e-12)
        checks += 3
    populations = {}
    for split, size in (("train", 24), ("validation", 12), ("test", 12)):
        subset = [r for r in records if r["split"] == split]
        names = {r["recording"] for r in subset}
        actors = {r["actor"] for r in subset}
        assert len(names) == size
        assert len(subset) == size * 3 * 3
        for name in names:
            individual = [r for r in subset if r["recording"] == name]
            assert len({r["label"] for r in individual}) == 1
            assert len({r["actor"] for r in individual}) == 1
        populations[split] = {"recordings": sorted(names), "actors": sorted(actors)}
    for a, b in (("train", "validation"), ("train", "test"), ("validation", "test")):
        assert not set(populations[a]["recordings"]) & set(populations[b]["recordings"])
        assert not set(populations[a]["actors"]) & set(populations[b]["actors"])
    # Exercise on data that differs solely outside the accepted audio prefix.
    from .historical_audio_reference import audio_features
    x = np.zeros((4, 40)); x[:, 32] = 1; x[:, 34] = 1
    x[:, :16] = np.arange(4)[:, None]
    times = np.array([.5, 1., 2., 3.]); observed = np.ones(4, bool)
    boundary_checks = []
    for kind in ("moments", "quantiles"):
        original = audio_features(x, observed, times, 1., kind)
        future = x.copy(); future[2:, :16] = float("nan")
        assert np.array_equal(original, audio_features(future, observed, times, 1., kind))
        video = np.zeros((1, 40)); video[0, 33] = 1; video[0, 35] = 1; video[0, :16] = 1e9
        mixed = np.concatenate((x[:2], video, x[2:]))
        assert np.array_equal(original, audio_features(mixed, np.ones(5, bool), np.array([.5, 1., 1., 2., 3.]), 1., kind))
        missing = observed.copy(); missing[:2] = False
        assert not audio_features(x, missing, times, 1., kind).any()
        boundary_checks.extend([kind + ":future-NaN-isolation", kind + ":video-isolation", kind + ":missing-audio-is-zero"])
    binding = json.loads((output / "BINDING_AUDIO_IDENTIFIABILITY.json").read_text())
    groups = binding["labels_by_audio_sequence_sha256"]
    assert sum(map(len, groups.values())) == 24
    assert all(row.count(0) == row.count(1) for row in groups.values())
    assert binding["audio_only_maximum_deterministic_empirical_accuracy"] == .5
    return {"schema": "hcsn-v10-historical-audio-audit.v1", "passed": True,
            "prediction_rows": len(records), "unique_historical_recordings": 48,
            "metric_scalar_checks": checks, "boundary_checks": boundary_checks,
            "split_populations": populations, "binding_audio_bound": .5,
            "scientific_confirmation": False, "strong_audio_qualified": False,
            "scope": "Saved-output arithmetic and causal feature contract only; 48 previously exposed recordings, not raw-media or v6 recovery"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.output)
    with (args.output / "AUDIT.json").open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result, indent=2))
