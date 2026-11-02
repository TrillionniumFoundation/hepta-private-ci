"""Read-only audit of a completed panel while other fixed panels continue."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .independent_v2_calibration_check import owner_check
from .independent_v2_confirmation_check import bootstrap_reference, payload

ROOT = Path(__file__).parent


def main():
    start = time.process_time()
    parser = argparse.ArgumentParser()
    parser.add_argument("panel", choices=("confirm", "reverse", "lag2", "relabeled_lag2", "lag2_skip"))
    args = parser.parse_args()
    spec = json.loads((ROOT / "protocol_v2.json").read_text())
    calibration = json.loads((ROOT / "calibration_v2_01/CALIBRATION.json").read_text())
    output = ROOT / "confirm_v2_01" / args.panel
    summary = json.loads((output / "SUMMARY.json").read_text())
    worlds = spec["confirmation_worlds"][args.panel]
    generators = worlds // spec["worlds_per_generator"]
    stats = {name:np.zeros((generators, 9)) for name in spec["confirmation_arms"]}
    thresholds = {name:spec["threshold"] for name in spec["models"]}
    for alias, base in spec["feasible_controls"].items():
        thresholds[alias] = spec["threshold"] if calibration["selected"][base]["calibration_gate_passed"] else spec["fallback_threshold"]
    invalid, raw_count, archives, owner_records = dict.fromkeys(stats, 0), 0, 0, 0
    for item in json.loads((output / "ARCHIVES.json").read_text()):
        archives += 1
        for row in payload(item):
            assert row["panel"] == args.panel and row["phase"] == "r20_powered_confirmation_v2"
            assert row["generator"] == raw_count // spec["worlds_per_generator"]
            assert row["index"] == raw_count % spec["worlds_per_generator"]
            raw_count += 1
            for name, matrix in stats.items():
                assert list(row["predictions"][name]) == [str(thresholds[name])]
                value = row["predictions"][name][str(thresholds[name])]
                owner_check(row, value, thresholds[name])
                owner_records += 1
                invalid[name] += value["invalid"]
                if not value["invalid"]:
                    a, f, e = value["accepted"], value["accepted"] and value["fractional"], not value["correct"]
                    matrix[row["generator"]] += [a, a and e, f, f and e, value["payoff"], value["before_brier"],
                        value["true_probability"] <= 0, value["read_index"] is not None, value["payoff"] - value["no_read_payoff"]]
    assert raw_count == worlds
    recorded_stats = payload(json.loads((output / "CLUSTER_STATS_ARCHIVE.json").read_text()))
    for name in stats:
        assert np.max(np.abs(stats[name] - recorded_stats[name])) < 2e-12
    draws, paired = bootstrap_reference(stats, spec, worlds)
    recorded = payload(json.loads((output / "BOOTSTRAP_ARCHIVE.json").read_text()))
    maximum = max(float(np.max(np.abs(draws[name] - recorded["models"][name]))) for name in stats)
    maximum = max(maximum, float(np.max(np.abs(paired - recorded["paired"]))))
    assert maximum < 3e-12
    gates = {}
    for name, matrix in stats.items():
        model = summary["models"][name]
        assert model["invalid"] == invalid[name] and model["attempts"] == worlds
        if invalid[name]:
            assert model["quality"] is None
            gates[name] = dict(registered_gate=False, invalid=invalid[name])
            continue
        total, q = matrix.sum(0), model["quality"]
        assert q["fractional"] == total[2] and q["fractional_errors"] == total[3]
        assert abs(q["payoff"] - total[4] / worlds) < 3e-12
        fractional_upper, overall_upper = np.quantile(draws[name][:, :2], .95, axis=0)
        assert abs(q["upper95_fractional"] - fractional_upper) < 3e-12
        assert abs(q["upper95_overall"] - overall_upper) < 3e-12
        base = spec["feasible_controls"].get(name, name)
        passed = (calibration["selected"][base]["calibration_gate_passed"] and not total[6]
            and total[2] >= spec["minimum_fractional_confirmation_answers"]
            and max(fractional_upper, overall_upper) <= spec["risk_limit"])
        assert q["gate"] == passed
        gates[name] = dict(registered_gate=bool(passed), fractional=int(total[2]), fractional_errors=int(total[3]),
            fractional_rate=float(total[2] / worlds), upper95_fractional=float(fractional_upper), policy_threshold=thresholds[name])
    controls = ["orbit_first_order"] + list(spec["feasible_controls"])
    for column, control in enumerate(controls):
        if not invalid["context_orbit"] and not invalid[control]:
            value = summary["paired"] if column == 0 else summary["feasible_control_comparisons"][control]
            assert np.max(np.abs(np.quantile(paired[:, 2 * column], [.025, .975]) - value["payoff_ci95"])) < 3e-12
            assert value["model_adoption_claim"] is False
    print(json.dumps(dict(passed=True, completed_panel=args.panel, worlds=worlds, independent_generators=generators,
        raw_archives=archives, owner_prediction_records=owner_records, bootstrap_draws=spec["bootstrap_draws"],
        maximum_bootstrap_difference=maximum, arms=gates, full_confirmation_audited=False,
        whole_study_qualified=None, fixed_samples_and_gates_modified=False,
        checker_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        process_cpu_seconds=time.process_time() - start,
        scope="Completedpanel only; immutable fullchecker functions reused for independent owner/multiplicity calculations; no candidate imports or generators"), sort_keys=True))


if __name__ == "__main__":
    main()
