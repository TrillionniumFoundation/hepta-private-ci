"""Synthetic arithmetic/IO fixtures only; never calls a world generator."""

import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from . import study
from .runner import resample


def main():
    start = time.process_time()
    root = Path(__file__).parent
    spec = json.loads((root / "protocol.json").read_text())
    fixture = dict(spec, bootstrap_draws=137, bootstrap_batch=7, arms=["a", "b"], feasible_controls={"safe":"b"})
    rng = np.random.default_rng(917)
    stats = {name:rng.uniform(size=(13, 10)) for name in ("a", "b", "safe")}
    for values in stats.values():
        values[:, 0:4] = np.floor(values[:, 0:4] * 5)
        values[:, 0], values[:, 2] = 2, 0
    draws, paired, controls = resample(stats, "a", fixture, 52)
    # Independently draw rows singly. RNG ordering must match batched production.
    reference_rng = np.random.default_rng(fixture["bootstrap_seed"])
    maximum = 0.
    for i in range(fixture["bootstrap_draws"]):
        rows = reference_rng.integers(13, size=13).tolist()
        for name, values in stats.items():
            sums = [sum(float(values[g, c]) for g in rows) for c in range(6)]
            expected = [sums[3] / sums[2] if sums[2] else 1., sums[1] / sums[0] if sums[0] else 1.,
                        sums[4] / 52, sums[5] / 52, sums[2] / 52, sums[0] / 52]
            maximum = max(maximum, float(np.max(np.abs(draws[name][i] - expected))))
        for j, control in enumerate(controls):
            for offset, column, sign in ((0, 4, 1), (1, 5, -1)):
                expected = sign * sum(float(stats["a"][g, column] - stats[control][g, column]) for g in rows) / 52
                maximum = max(maximum, abs(float(paired[i, 2 * j + offset]) - expected))
    assert maximum < 1e-14
    temporary = root / "engineering_io_fixture"
    temporary.mkdir(exist_ok=False)
    original = study.ROOT
    study.ROOT = temporary
    try:
        (temporary / "protocol.json").write_text(json.dumps(dict(total_output_budget_bytes=4096)))
        study.write(temporary / "exclusive.json", {"valid":True})
        exclusive = False
        try:
            study.write(temporary / "exclusive.json", {"valid":False})
        except FileExistsError:
            exclusive = True
        budget = False
        try:
            study.write(temporary / "too_big.json", "x" * 5000)
        except OSError:
            budget = True
        assert exclusive and budget and not (temporary / "too_big.json").exists()
    finally:
        study.ROOT = original
    record = dict(passed=True, synthetic_only=True, new_world_generator_called=False,
        bootstrap_draws=137, batch=7, scalar_max_abs=maximum,
        zero_fractional_denominator_risk_one=True, exclusive_io_and_budget_rejection=True,
        checker_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        cpu_seconds=time.process_time() - start)
    study.write(root / "ENGINEERING_CHECK.json", record)
    print(json.dumps(record, sort_keys=True))


if __name__ == "__main__":
    main()
