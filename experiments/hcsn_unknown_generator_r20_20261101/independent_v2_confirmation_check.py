"""Streamed powered-confirmation replay with multinomial-count bootstrap reference."""

import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .independent_v2_calibration_check import owner_check

ROOT = Path(__file__).parent


def payload(item):
    path = ROOT / item["path"]
    assert path.resolve().is_relative_to(ROOT.resolve())
    compressed = path.read_bytes()
    raw = gzip.decompress(compressed)
    assert hashlib.sha256(compressed).hexdigest() == item["sha256"]
    assert hashlib.sha256(raw).hexdigest() == item["raw_sha256"]
    value = json.loads(raw)
    assert len(value) == item["records"]
    return value


def bootstrap_reference(stats, spec, worlds):
    names = spec["confirmation_arms"]
    controls = ["orbit_first_order"] + list(spec["feasible_controls"])
    generators = next(iter(stats.values())).shape[0]
    rng = np.random.default_rng(spec["bootstrap_seed"])
    draws = {name:np.empty((spec["bootstrap_draws"], 4)) for name in names}
    paired = np.empty((spec["bootstrap_draws"], 2 * len(controls)))
    # Same registered RNG order; independent contraction through resample multiplicities.
    for start in range(0, spec["bootstrap_draws"], spec["bootstrap_batch"]):
        count = min(spec["bootstrap_batch"], spec["bootstrap_draws"] - start)
        indices = rng.integers(generators, size=(count, generators))
        for offset, selected in enumerate(indices):
            multiplicity = np.bincount(selected, minlength=generators)
            totals = {name:multiplicity @ stats[name] for name in names}
            row = start + offset
            for name, total in totals.items():
                draws[name][row] = [total[3] / total[2] if total[2] else 1.,
                    total[1] / total[0] if total[0] else 1., total[4] / worlds, total[5] / worlds]
            for column, control in enumerate(controls):
                delta = totals["context_orbit"] - totals[control]
                paired[row, 2 * column:2 * column + 2] = [delta[4] / worlds, -delta[5] / worlds]
    return draws, paired


def main():
    start = time.process_time()
    spec = json.loads((ROOT / "protocol_v2.json").read_text())
    calibration = json.loads((ROOT / "calibration_v2_01/CALIBRATION.json").read_text())
    assert calibration["selected"]["context_orbit"]["calibration_gate_passed"]
    directory = ROOT / "confirm_v2_01"
    combined = json.loads((directory / "SUMMARY.json").read_text())
    assert set(combined["panels"]) == set(spec["confirmation_worlds"])
    thresholds = {name:spec["threshold"] for name in spec["models"]}
    for alias, base in spec["feasible_controls"].items():
        thresholds[alias] = spec["threshold"] if calibration["selected"][base]["calibration_gate_passed"] else spec["fallback_threshold"]
    archive_checks, owner_checks, coordinates, draw_checks, maximum = 0, 0, 0, 0, 0.
    panels = {}
    for panel, worlds in spec["confirmation_worlds"].items():
        output = directory / panel
        generators = worlds // spec["worlds_per_generator"]
        stats = {name:np.zeros((generators, 9)) for name in spec["confirmation_arms"]}
        invalid = dict.fromkeys(stats, 0)
        raw_count = 0
        for item in json.loads((output / "ARCHIVES.json").read_text()):
            rows = payload(item)
            archive_checks += 1
            for row in rows:
                assert row["phase"] == "r20_powered_confirmation_v2" and row["panel"] == panel
                assert row["generator"] == raw_count // spec["worlds_per_generator"]
                assert row["index"] == raw_count % spec["worlds_per_generator"]
                assert set(row["predictions"]) == set(stats)
                raw_count += 1
                for name, matrix in stats.items():
                    assert list(row["predictions"][name]) == [str(thresholds[name])]
                    value = row["predictions"][name][str(thresholds[name])]
                    owner_check(row, value, thresholds[name])
                    owner_checks += 1
                    invalid[name] += value["invalid"]
                    if not value["invalid"]:
                        a, f, e = value["accepted"], value["accepted"] and value["fractional"], not value["correct"]
                        matrix[row["generator"]] += [a, a and e, f, f and e, value["payoff"], value["before_brier"],
                            value["true_probability"] <= 0, value["read_index"] is not None, value["payoff"] - value["no_read_payoff"]]
                for alias, base in spec["feasible_controls"].items():
                    a = next(iter(row["predictions"][alias].values()))
                    b = next(iter(row["predictions"][base].values()))
                    if thresholds[alias] == spec["threshold"]:
                        assert a == b
                    elif not a["invalid"] and not b["invalid"]:
                        assert a["before"] == b["before"] and a["surprise"] == b["surprise"]
                        if a["read_index"] == b["read_index"]:
                            assert a["probability"] == b["probability"] and a["actual_read"] == b["actual_read"]
        assert raw_count == worlds
        stored_stats = payload(json.loads((output / "CLUSTER_STATS_ARCHIVE.json").read_text()))
        for name, matrix in stats.items():
            assert np.max(np.abs(matrix - stored_stats[name])) < 2e-12
            coordinates += matrix.size
        draws, paired = bootstrap_reference(stats, spec, worlds)
        recorded = payload(json.loads((output / "BOOTSTRAP_ARCHIVE.json").read_text()))
        controls = ["orbit_first_order"] + list(spec["feasible_controls"])
        assert recorded["paired_columns"] == ["context_minus_" + name + "_" + measure for name in controls
            for measure in ("payoff", "before_brier_improvement")]
        for name, value in draws.items():
            difference = float(np.max(np.abs(value - recorded["models"][name])))
            maximum = max(maximum, difference)
            assert difference < 3e-12
            draw_checks += value.size
        difference = float(np.max(np.abs(paired - recorded["paired"])))
        maximum = max(maximum, difference)
        assert difference < 3e-12
        draw_checks += paired.size
        summary = json.loads((output / "SUMMARY.json").read_text())
        assert summary == combined["panels"][panel]
        for name, matrix in stats.items():
            declared = summary["models"][name]
            assert declared["attempts"] == worlds and declared["invalid"] == invalid[name]
            base = spec["feasible_controls"].get(name, name)
            assert declared["calibration"]["threshold"] == thresholds[name]
            assert declared["calibration"]["calibration_gate_passed"] == calibration["selected"][base]["calibration_gate_passed"]
            if invalid[name]:
                assert declared["quality"] is None
                continue
            total, quality = matrix.sum(0), declared["quality"]
            for index, key in enumerate(("accepted", "errors", "fractional", "fractional_errors")):
                assert quality[key] == total[index]
            for expected, key in ((total[4] / worlds, "payoff"), (total[5] / worlds, "before_brier"),
                    (total[6], "support_losses"), (total[7], "reads"), (total[8] / worlds, "read_net_effect"),
                    (np.quantile(draws[name][:, 0], .95), "upper95_fractional"),
                    (np.quantile(draws[name][:, 1], .95), "upper95_overall")):
                assert abs(quality[key] - expected) < 3e-12
            passed = (declared["calibration"]["calibration_gate_passed"] and not total[6]
                and total[2] >= spec["minimum_fractional_confirmation_answers"]
                and max(quality["upper95_fractional"], quality["upper95_overall"]) <= spec["risk_limit"])
            assert quality["gate"] == passed
        for column, control in enumerate(controls):
            if invalid["context_orbit"] or invalid[control]:
                continue
            delta = (stats["context_orbit"] - stats[control]).sum(0) / worlds
            declared = summary["paired"] if column == 0 else summary["feasible_control_comparisons"][control]
            assert abs(delta[4] - declared["payoff_difference"]) < 3e-12
            assert abs(-delta[5] - declared["before_brier_improvement"]) < 3e-12
            assert np.max(np.abs(np.quantile(paired[:, 2 * column], [.025, .975]) - declared["payoff_ci95"])) < 3e-12
            assert np.max(np.abs(np.quantile(paired[:, 2 * column + 1], [.025, .975]) - declared["before_brier_ci95"])) < 3e-12
            assert declared["model_adoption_claim"] is False
        quality = summary["models"]["context_orbit"]["quality"]
        panels[panel] = bool(quality is not None and quality["gate"])
    assert combined["known_failure_repair_gate"] == (panels["reverse"] and panels["lag2"])
    assert combined["label_transport_gate"] == panels["relabeled_lag2"]
    assert combined["untouched_structural_shift_gate"] == panels["lag2_skip"]
    assert not combined["all_blockers_closed"] and not combined["production_activation"]
    assert not (ROOT / "confirm_01").exists()
    receipt = json.loads((ROOT / "CONFIRM_V2_PROCESS_RECEIPT.json").read_text())
    workers = json.loads((directory / "WORKER_RECEIPTS.json").read_text())
    assert set(workers) == set(spec["confirmation_worlds"])
    assert all(value["exit_code"] == 0 for value in workers.values())
    worker_cpu = sum(value["child_cpu_seconds"] for value in workers.values())
    assert abs(worker_cpu - receipt["parallel_worker_cpu_sum"]) < 1e-10
    assert receipt["child_cpu_seconds"] + 1e-6 >= worker_cpu
    print(json.dumps(dict(passed=True, worlds=sum(spec["confirmation_worlds"].values()),
        independent_generators={panel:count // spec["worlds_per_generator"] for panel, count in spec["confirmation_worlds"].items()},
        owner_prediction_records=owner_checks, raw_archives=archive_checks, cluster_stat_coordinates=coordinates,
        bootstrap_coordinates=draw_checks, maximum_bootstrap_difference=maximum, panel_gates=panels,
        checker_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        owner_checker_sha256=hashlib.sha256((ROOT / "independent_v2_calibration_check.py").read_bytes()).hexdigest(),
        original_confirmation_unopened=True, process_cpu_seconds=time.process_time() - start,
        scope="No candidateimports or worldgeneratorcalls; owner/action/fee/score replay and independent multinomial-count contraction of all registered draws"), sort_keys=True))


if __name__ == "__main__":
    main()
