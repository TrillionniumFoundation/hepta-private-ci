"""Streaming raw-owner/count audit and independent finite-binomial CP inversion."""

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


def owner_check(row, value, threshold):
    public = row["public"]
    events, prefix, mask = public["owner_events"], public["prefix"], public["observed"]
    assert row["price"] in (.02, .12, .3, .6)
    assert len(events) == len(prefix) == len(mask)
    assert all((a == b if seen else not any(b)) for a, b, seen in zip(events, prefix, mask, strict=True))
    alias = public["query"][19:23].index(1)
    key = next(bridge[:4].index(1) for bridge in public["bridges"] if bridge[19 + alias])
    target = next(event[4:8].index(1) for event in events[::-1] if event[12] and event[key])
    assert target == row["target"]
    if value["invalid"]:
        assert not value["accepted"] and value["read_index"] is None
        return
    p, before = value["probability"], value["before"]
    assert len(p) == len(before) == 4 and min(p) >= 0 and min(before) >= 0
    assert p[target] > 0 and before[target] > 0
    assert abs(sum(p) - 1) < 2e-12 and abs(sum(before) - 1) < 2e-12
    confidence, action = max(p), value["read_index"]
    correct, before_correct = p.index(confidence) == target, before.index(max(before)) == target
    assert value["correct"] == correct and abs(value["confidence"] - confidence) < 1e-14
    assert value["accepted"] == (value["admitted"] and confidence >= threshold)
    assert value["fractional"] == (confidence < 1 - 1e-9)
    fee = row["price"] if action is not None else 0.
    assert value["fee"] == fee
    if action is not None:
        assert 0 <= action < len(mask) and not mask[action] and value["actual_read"] == events[action]
    else:
        assert value["actual_read"] is None
    if not value["admitted"]:
        assert action is None and not value["accepted"]
    assert value["payoff"] == (2 * int(correct) - 1 if value["accepted"] else 0) - fee
    assert value["no_read_payoff"] == (2 * int(before_correct) - 1 if value["admitted"] and max(before) >= threshold else 0)
    for probabilities, name in ((p, "brier"), (before, "before_brier")):
        expected = sum((x - int(index == target)) ** 2 for index, x in enumerate(probabilities))
        assert abs(value[name] - expected) < 2e-12
    for probabilities, name in ((p, "log_loss"), (before, "before_log_loss")):
        if probabilities[target] > 0:
            assert abs(value[name] + math.log(probabilities[target])) < 2e-12
        else:
            assert value[name] is None
    assert value["true_probability"] == p[target]


def main():
    start = time.process_time()
    spec = json.loads((ROOT / "protocol_v2.json").read_text())
    directory = ROOT / "calibration_v2_01"
    calibration = json.loads((directory / "CALIBRATION.json").read_text())
    delta = spec["family_error_probability"] / (len(spec["models"]) * len(spec["calibration_strata"]) * 2)
    assert calibration["simultaneous_delta"] == delta
    assert calibration["original_r20_54_bound_gate"] == "FAILED; unchanged; not pooled"
    archive_checks, owner_checks, count_checks, bound_checks, maximum = 0, 0, 0, 0, 0.
    selected, strata_results = {}, {}
    for stratum, planned in spec["calibration_strata"].items():
        aggregates = {name:dict(accepted=0, errors=0, fractional=0, fractional_errors=0, invalid=0,
            payoff_sum=0., before_brier_sum=0., actual_reads=0) for name in spec["models"]}
        raw_count = 0
        indices = json.loads((directory / stratum / "ARCHIVES.json").read_text())
        for item in indices:
            path = ROOT / item["path"]
            assert path.resolve().is_relative_to(directory.resolve())
            compressed = path.read_bytes()
            raw = gzip.decompress(compressed)
            assert hashlib.sha256(compressed).hexdigest() == item["sha256"]
            assert hashlib.sha256(raw).hexdigest() == item["raw_sha256"]
            rows = json.loads(raw)
            assert len(rows) == item["records"]
            archive_checks += 1
            for row in rows:
                assert row["stratum"] == stratum and row["generator"] == raw_count
                assert row["phase"] == "r20_calibration_power_v2"
                assert set(row["predictions"]) == set(spec["models"])
                raw_count += 1
                for name in spec["models"]:
                    assert list(row["predictions"][name]) == [str(spec["threshold"])]
                    value = row["predictions"][name][str(spec["threshold"])]
                    owner_check(row, value, spec["threshold"])
                    owner_checks += 1
                    aggregate = aggregates[name]
                    aggregate["invalid"] += value["invalid"]
                    if not value["invalid"]:
                        a, f, e = value["accepted"], value["accepted"] and value["fractional"], not value["correct"]
                        for key, amount in (("accepted", a), ("errors", a and e), ("fractional", f), ("fractional_errors", f and e)):
                            aggregate[key] += amount
                        aggregate["payoff_sum"] += value["payoff"]
                        aggregate["before_brier_sum"] += value["before_brier"]
                        aggregate["actual_reads"] += value["read_index"] is not None
        assert raw_count == planned
        declared = json.loads((directory / stratum / "COUNTS.json").read_text())
        for name, counts in aggregates.items():
            entry = calibration["grid"][stratum][name]
            for key, value in counts.items():
                assert abs(value - entry[key]) < 2e-10 and abs(value - declared[name][key]) < 2e-10
                count_checks += 1
            total_upper = cp_upper(counts["errors"], counts["accepted"], delta)
            fractional_upper = cp_upper(counts["fractional_errors"], counts["fractional"], delta)
            for expected, key in ((total_upper, "upper_error"), (fractional_upper, "upper_fractional_error")):
                difference = abs(expected - entry[key])
                maximum = max(maximum, difference)
                assert difference < 2e-11
                bound_checks += 1
            passed = (not counts["invalid"] and max(total_upper, fractional_upper) <= spec["risk_limit"]
                and counts["fractional"] >= spec["minimum_fractional_answers"])
            assert entry["passed"] == passed
        strata_results[stratum] = aggregates
    for name in spec["models"]:
        selected[name] = dict(threshold=spec["threshold"], calibration_gate_passed=all(
            calibration["grid"][stratum][name]["passed"] for stratum in spec["calibration_strata"]))
    assert calibration["selected"] == selected
    original = json.loads((ROOT / "prepare_01/CALIBRATION.json").read_text())
    assert all(not item["calibration_gate_passed"] for item in original["selected"].values())
    assert not (ROOT / "confirm_01").exists()
    frozen = json.loads((ROOT / "CALIBRATION_V2_SOURCE_FREEZE.json").read_text())
    for name, expected in frozen["files"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    receipt = json.loads((ROOT / "CALIBRATION_V2_PROCESS_RECEIPT.json").read_text())
    workers = json.loads((directory / "WORKER_RECEIPTS.json").read_text())
    assert set(workers) == set(spec["calibration_strata"])
    assert all(item["exit_code"] == 0 for item in workers.values())
    worker_cpu = sum(item["child_cpu_seconds"] for item in workers.values())
    assert abs(worker_cpu - receipt["parallel_worker_cpu_sum"]) < 1e-10
    assert receipt["child_cpu_seconds"] + 1e-6 >= worker_cpu and receipt["accounting_sanity_total_at_least_workers"]
    print(json.dumps(dict(passed=True, worlds=sum(spec["calibration_strata"].values()),
        owner_prediction_records=owner_checks, checked_archives=archive_checks, count_checks=count_checks,
        binomial_tail_bound_checks=bound_checks, maximum_bound_difference=maximum, selected=selected,
        original_54_bound_gate_preserved_failed=True, original_confirmation_unopened=True,
        observed_true_label_support_losses=0,
        checker_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        observed_family_cpu_seconds=receipt["child_cpu_seconds"], workers_cpu_already_included=worker_cpu,
        scope="Streaming owner/receipt/fee/proper-score/count replay; finite-binomial log-CDF inversion; no candidate/scipy.stats imports or heldout generator calls",
        process_cpu_seconds=time.process_time() - start), sort_keys=True))


if __name__ == "__main__":
    main()
