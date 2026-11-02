"""Recompute risk-selection and confirmation statistics from immutable raw data."""

import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.stats import beta

ROOT = Path(__file__).parent


def rows(directory):
    result = []
    for item in json.loads((directory / "ARCHIVES.json").read_text()):
        data = (ROOT / item["path"]).read_bytes()
        raw = gzip.decompress(data)
        assert hashlib.sha256(data).hexdigest() == item["sha256"]
        assert hashlib.sha256(raw).hexdigest() == item["raw_sha256"]
        if "training" not in item["path"]:
            result.extend(json.loads(raw))
    return result


def main():
    start = time.process_time()
    spec = json.loads((ROOT / "protocol.json").read_text())
    prepare = ROOT / "prepare_01"
    calibration = json.loads((prepare / "CALIBRATION.json").read_text())
    raw = rows(prepare)
    checks = 0
    for name in spec["models"]:
        passing = []
        for threshold in spec["thresholds"]:
            predictions = [r["predictions"][name][str(threshold)] for r in raw]
            assert not any(p["invalid"] for p in predictions)
            accepted = [p for p in predictions if p["accepted"]]
            fractional = [p for p in accepted if p["fractional"]]
            counts = dict(accepted=len(accepted), errors=sum(not p["correct"] for p in accepted),
                fractional=len(fractional), fractional_errors=sum(not p["correct"] for p in fractional), invalid=0)
            entry = calibration["grid"][name][str(threshold)]
            assert all(entry[k] == v for k, v in counts.items())
            bounds = []
            for prefix in ("", "fractional_"):
                n = counts["fractional"] if prefix else counts["accepted"]
                e = counts[prefix + "errors"]
                upper = 1. if not n or e == n else float(beta.ppf(1 - .05 / 16, e + 1, n - e))
                assert abs(upper - entry["upper_" + prefix + "error"]) < 1e-12
                bounds.append(upper)
            passed = max(bounds) <= .1 and len(fractional) >= 20
            assert entry["passed"] == passed
            if passed:
                passing.append((len(fractional), -threshold, threshold))
            checks += 8
        expected = dict(calibration_gate_passed=bool(passing), threshold=max(passing)[2] if passing else 1 - 1e-12)
        assert expected == calibration["selected"][name]
    confirmation = ROOT / "confirm_01"
    raw = rows(confirmation)
    summary = json.loads((confirmation / "SUMMARY.json").read_text())
    for panel in spec["panels"]:
        boot = np.random.default_rng(1905513).integers(256, size=(4096, 256))
        stored = {}
        for name in spec["models"]:
            grouped = np.zeros((256, 8))
            for row in (r for r in raw if r["panel"] == panel):
                p = next(iter(row["predictions"][name].values()))
                assert not p["invalid"]
                a, f, e = p["accepted"], p["accepted"] and p["fractional"], not p["correct"]
                grouped[row["generator"]] += [a, a and e, f, f and e, p["payoff"], p["before_brier"],
                    p["true_probability"] <= 0, p["read_index"] is not None]
            total, draws = grouped.sum(0), grouped[boot].sum(1)
            expected = summary["models"][panel + ":" + name]["quality"]
            for col, key in enumerate(("accepted", "errors", "fractional", "fractional_errors")):
                assert total[col] == expected[key]
            assert abs(total[4] / 1024 - expected["payoff"]) < 1e-12
            assert abs(total[5] / 1024 - expected["before_brier"]) < 1e-12
            for e, n, key in ((3, 2, "upper95_fractional"), (1, 0, "upper95_overall")):
                ratio = np.divide(draws[:, e], draws[:, n], out=np.ones(4096), where=draws[:, n] > 0)
                assert abs(float(np.quantile(ratio, .95)) - expected[key]) < 1e-12
            passed = (calibration["selected"][name]["calibration_gate_passed"] and not total[6]
                and total[2] >= 32 and max(expected["upper95_fractional"], expected["upper95_overall"]) <= .1)
            assert expected["gate"] == passed
            stored[name] = grouped / 4
            checks += 9
        paired = summary[panel + ":paired"]
        for col, sign, mean_key, interval_key in ((4, 1, "payoff_difference", "payoff_ci95"),
                (5, -1, "before_brier_improvement", "before_brier_ci95")):
            difference = sign * (stored["full_transition"][:, col] - stored["restricted_markov"][:, col])
            assert abs(difference.mean() - paired[mean_key]) < 1e-12
            assert np.max(np.abs(np.quantile(difference[boot].mean(1), [.025, .975]) - paired[interval_key])) < 1e-12
            checks += 3
    assert summary["unseen_family_gate"] == all(summary["models"][panel + ":full_transition"]["quality"]["gate"]
        for panel in ("reverse", "lag2"))
    print(json.dumps(dict(passed=True, calibration_prediction_records=2048 * 2 * 4,
        confirmation_prediction_records=len(raw) * 2, numerical_statistic_checks=checks,
        process_cpu_seconds=time.process_time() - start), sort_keys=True))


if __name__ == "__main__":
    main()
