"""Raw risk-selection reconstruction with a binomial-tail CP inversion."""

import gzip
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

ROOT = Path(__file__).parent


def cp_upper(errors, count, delta):
    if not count or errors == count:
        return 1.
    if not errors:
        return -math.expm1(math.log(delta) / count)
    k = np.arange(errors + 1, dtype=float)
    coefficients = np.array([math.lgamma(count + 1) - math.lgamma(int(j) + 1)
                             - math.lgamma(count - int(j) + 1) for j in k])
    low, high, target = 0., 1., math.log(delta)
    for _ in range(80):
        p = (low + high) / 2
        terms = coefficients + k * math.log(p) + (count - k) * math.log1p(-p)
        maximum = float(terms.max())
        log_cdf = maximum + math.log(float(np.exp(terms - maximum).sum()))
        if log_cdf > target:
            low = p
        else:
            high = p
    return (low + high) / 2


def main():
    start = time.process_time()
    spec = json.loads((ROOT / "protocol.json").read_text())
    prepared = ROOT / "prepare_01"
    archive_bytes = (prepared / "ARCHIVES.json").read_bytes()
    calibration_bytes = (prepared / "CALIBRATION.json").read_bytes()
    calibration = json.loads(calibration_bytes)
    raw, archive_checks = [], 0
    for item in json.loads(archive_bytes):
        compressed = (ROOT / item["path"]).read_bytes()
        data = gzip.decompress(compressed)
        assert hashlib.sha256(compressed).hexdigest() == item["sha256"]
        assert hashlib.sha256(data).hexdigest() == item["raw_sha256"]
        rows = json.loads(data)
        assert len(rows) == item["records"]
        archive_checks += 1
        if "training" not in item["path"]:
            raw.extend(rows)
    assert len(raw) == sum(spec["calibration_strata"].values())
    assert len({(row["stratum"], row["generator"]) for row in raw}) == len(raw)
    delta = spec["family_error_probability"] / (len(spec["models"]) * len(spec["thresholds"])
        * len(spec["calibration_strata"]) * 2)
    assert delta == calibration["simultaneous_delta"]
    bound_checks, count_checks, maximum, selected = 0, 0, 0., {}
    for name in spec["models"]:
        choices = []
        for threshold in spec["thresholds"]:
            entries = []
            for stratum, expected_count in spec["calibration_strata"].items():
                predictions = [row["predictions"][name][str(threshold)] for row in raw if row["stratum"] == stratum]
                assert len(predictions) == expected_count
                accepted = [p for p in predictions if not p["invalid"] and p["accepted"]]
                fractional = [p for p in accepted if p["fractional"]]
                counts = dict(accepted=len(accepted), errors=sum(not p["correct"] for p in accepted),
                    fractional=len(fractional), fractional_errors=sum(not p["correct"] for p in fractional),
                    invalid=sum(p["invalid"] for p in predictions))
                entry = calibration["grid"][stratum][name][str(threshold)]
                for key in counts:
                    assert counts[key] == entry[key]
                    count_checks += 1
                total_upper = cp_upper(counts["errors"], counts["accepted"], delta)
                fractional_upper = cp_upper(counts["fractional_errors"], counts["fractional"], delta)
                for expected, key in ((total_upper, "upper_error"), (fractional_upper, "upper_fractional_error")):
                    difference = abs(expected - entry[key])
                    maximum = max(maximum, difference)
                    assert difference < 2e-11, (stratum, name, threshold, key, difference)
                    bound_checks += 1
                passed = (not counts["invalid"] and max(total_upper, fractional_upper) <= spec["risk_limit"]
                          and counts["fractional"] >= spec["minimum_fractional_calibration_answers"])
                assert passed == entry["passed"]
                entries.append((passed, counts["fractional"]))
            if all(passed for passed, _ in entries):
                choices.append((sum(n for _, n in entries), -threshold, threshold))
        selected[name] = dict(calibration_gate_passed=bool(choices), threshold=max(choices)[2] if choices else 1 - 1e-12)
        assert selected[name] == calibration["selected"][name]
    print(json.dumps(dict(passed=True, calibration_worlds=len(raw), raw_prediction_records=len(raw)
        * len(spec["models"]) * len(spec["thresholds"]), checked_archives=archive_checks,
        count_checks=count_checks, binomial_tail_bound_checks=bound_checks, maximum_bound_difference=maximum,
        selected=selected, simultaneous_delta=delta,
        hashes={"ARCHIVES.json":hashlib.sha256(archive_bytes).hexdigest(),
                "CALIBRATION.json":hashlib.sha256(calibration_bytes).hexdigest()},
        scope="No candidate or scipy.stats imports; CP bounds invert finite binomial log-CDF by bisection; all candidates and strata reconstructed from raw",
        process_cpu_seconds=time.process_time() - start), sort_keys=True))


if __name__ == "__main__":
    main()
