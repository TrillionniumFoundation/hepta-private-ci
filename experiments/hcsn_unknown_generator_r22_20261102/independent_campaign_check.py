"""Read-only raw campaign audit. No producer, generator, inference or scipy imports.

The Cartesian reference is scalar; bootstrap replication uses sample multiplicities
and matrix products rather than the producer's indexed coordinate summation.
"""

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import resource
import time

import numpy as np

from .independent_campaign_reference import MEMBERS, check_value, enumerate_public, owner_context, reference_policy

ROOT = Path(__file__).parent
COLS = ["accepted", "accepted_errors", "fractional", "fractional_errors", "payoff", "before_brier",
        "support_losses", "reads", "fees", "read_net_effect"]
DRAW_COLS = ["fractional_risk", "overall_risk", "mean_utility", "before_brier", "fractional_rate", "answer_rate"]
MAX_DIFFERENCE = 0.


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def close(actual, expected, tolerance=2e-8):
    global MAX_DIFFERENCE
    a, b = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
    assert a.shape == b.shape and np.isfinite(a).all() and np.isfinite(b).all()
    difference = float(np.max(np.abs(a - b), initial=0.))
    MAX_DIFFERENCE = max(MAX_DIFFERENCE, difference)
    assert difference <= tolerance, (difference, tolerance)


def bound(errors, count, delta):
    """Invert finite binomial lower tail, independently of beta quantiles."""
    assert 0 <= errors <= count and 0 < delta < 1
    if not count or errors == count:
        return 1.
    k = np.arange(errors + 1, dtype=float)
    combinations = np.zeros(errors + 1)
    for j in range(1, errors + 1):
        combinations[j] = combinations[j - 1] + math.log(count - j + 1) - math.log(j)
    low, high = 0., 1.
    for _ in range(72):
        p = (low + high) / 2
        log_terms = combinations + k * math.log(p) + (count - k) * math.log1p(-p)
        maximum = float(log_terms.max())
        log_cdf = maximum + math.log(float(np.exp(log_terms - maximum).sum()))
        if log_cdf > math.log(delta):
            low = p
        else:
            high = p
    return (low + high) / 2


def frozen(name, publication):
    source, receipt = read(ROOT / name), read(ROOT / publication)
    assert receipt["readback_verified"] is True and receipt["freeze_sha256"] == sha(ROOT / name)
    for path, expected in source["files"].items():
        assert sha(ROOT / path) == expected, path
    for local in ("independent_campaign_check.py", "independent_campaign_reference.py"):
        assert local in source["files"] or name != "SOURCE_FREEZE.json", local
    return dict(freeze_sha256=sha(ROOT / name), publication_sha256=sha(ROOT / publication), files=len(source["files"]))


def archived(meta):
    path = ROOT / meta["path"]
    assert sha(path) == meta["sha256"], str(path)
    raw = gzip.decompress(path.read_bytes())
    assert hashlib.sha256(raw).hexdigest() == meta["raw_sha256"]
    return json.loads(raw)


def models(spec):
    path = ROOT / "development_fit_final/MODELS.json.gz"
    assert sha(path) == spec["models_sha256"]
    result = json.loads(gzip.decompress(path.read_bytes()))
    legacy = ROOT / "inputs/r20_models.json.gz"
    assert sha(legacy) == "c6f68af4cf9027464d7560c5d5c23ebc96a3892c0e410453cee23329bc007a86"
    result["r20_context_common"] = json.loads(gzip.decompress(legacy.read_bytes()))["context_orbit"]
    assert set(result) == {member for values in MEMBERS.values() for member in values}
    return result


def policies(spec, calibration=None):
    result = {name:(name, spec["threshold"]) for name in spec["arms"]}
    if calibration is not None:
        for alias, base in spec["feasible_controls"].items():
            result[alias] = (base, spec["threshold"] if calibration["qualifications"][base] else spec["fallback_threshold"])
    return result


def collect(directory, name, count, clustered, declared, laws):
    size = count // clustered
    stats = {arm:np.zeros((size, 10)) for arm in declared}
    invalid, completed, replayed, replay_policies = dict.fromkeys(declared, 0), set(), 0, 0
    archives = read(directory / name / "ARCHIVES.json")
    for meta in archives:
        for row in archived(meta):
            assert row["stage"] == ("calibration" if clustered == 1 else "confirmation")
            assert row.get("stratum", row.get("panel")) == name
            generator, index = row["generator"], row["index"]
            assert isinstance(generator, int) and 0 <= generator < size and isinstance(index, int) and 0 <= index < clustered
            assert (generator, index) not in completed and set(row["predictions"]) == set(declared)
            completed.add((generator, index))
            owner_context(row)
            same_law = {}
            for arm, (base, threshold) in declared.items():
                value = row["predictions"][arm]
                vector = check_value(row, value, base, threshold)
                invalid[arm] += value["invalid"]
                if vector is None:
                    vector = [0.] * 10
                    vector[7:9] = [value["read_index"] is not None, value["fee"]]
                else:
                    law = MEMBERS[base][0]
                    before_key, after_key = (law, "before"), (law, value["read_index"])
                    for key, probability in ((before_key, value["before"]), (after_key, value["probability"])):
                        if key in same_law:
                            close(probability, same_law[key], 3e-12)
                        same_law[key] = probability
                stats[arm][generator] += vector
            # Deterministic prefix subset; selected only by position/mask size,
            # never by outcomes, successful decisions, or agreement with producer.
            if replayed < 8 and row["public"]["observed"].count(False) <= 3:
                belief = enumerate_public(row["public"], laws)
                for arm, (base, threshold) in declared.items():
                    reference = reference_policy(belief, MEMBERS[base], threshold, row["price"], row["public"])
                    actual = row["predictions"][arm]
                    assert not actual["invalid"]
                    for key in ("read_index", "accepted", "fee"):
                        assert actual[key] == reference[key], (name, generator, index, arm, key)
                    for key in ("before", "probability", "decision_confidence"):
                        close(actual[key], reference[key], 3e-11)
                    replay_policies += 1
                replayed += 1
    assert len(completed) == count and replayed == 8
    return stats, invalid, dict(rows=len(completed), archives=len(archives), cartesian_worlds=replayed, cartesian_policies=replay_policies)


def costs(directory, stage, names):
    workers = read(directory / "WORKER_RECEIPTS.json")
    assert set(workers) == set(names) and all(value["exit_code"] == 0 for value in workers.values())
    total = math.fsum(value["child_cpu_seconds"] for value in workers.values())
    receipt = read(ROOT / (stage.upper() + "_PROCESS_RECEIPT.json"))
    assert receipt["exit_code"] == 0 and receipt["worker_receipts_read_error"] is None
    assert receipt["accounting_sanity_total_at_least_workers"] is True
    close(total, receipt["parallel_worker_cpu_sum"])
    assert receipt["child_cpu_seconds"] + 1e-6 >= total
    return dict(worker_cpu_seconds=total, outer_descendant_cpu_seconds=receipt["child_cpu_seconds"],
                wall_seconds=receipt["wall_seconds"], peak_concurrent_family_rss_known=False,
                outer_includes_workers_do_not_add=True)


def calibration_audit(directory, spec, laws):
    result = read(directory / "CALIBRATION.json")
    assert result["bound_count"] == 70 and result["threshold"] == spec["threshold"] == .9
    delta = spec["family_error_probability"] / (len(spec["arms"]) * len(spec["calibration_strata"]) * 2)
    close(result["simultaneous_delta"], delta, 1e-16)
    reports, passed = {}, {arm:[] for arm in spec["arms"]}
    for name, count in spec["calibration_strata"].items():
        stats, invalid, reports[name] = collect(directory, name, count, 1, policies(spec), laws)
        saved_counts = read(directory / name / "COUNTS.json")
        for arm in spec["arms"]:
            total = stats[arm].sum(0)
            expected = dict(worlds=count, invalid=invalid[arm], accepted=int(total[0]), errors=int(total[1]),
                fractional=int(total[2]), fractional_errors=int(total[3]), utility=float(total[4]), before_brier=float(total[5]),
                support_losses=int(total[6]), reads=int(total[7]), fees=float(total[8]))
            entry = result["grid"][name][arm]
            for key, value in expected.items():
                close(saved_counts[arm][key], value)
                close(entry[key], value)
            overall, fractional = bound(int(total[1]), int(total[0]), delta), bound(int(total[3]), int(total[2]), delta)
            close(entry["upper_error"], overall, 2e-11)
            close(entry["upper_fractional_error"], fractional, 2e-11)
            close(entry["fractional_rate"], total[2] / count, 1e-15)
            success = not invalid[arm] and not total[6] and max(overall, fractional) <= spec["risk_limit"] and total[2] >= spec["minimum_fractional_count"] and total[2] / count >= spec["minimum_fractional_rate"]
            assert entry["population_quality_null"] == bool(invalid[arm]) and entry["passed"] == bool(success)
            passed[arm].append(bool(success))
    qualifications = {arm:all(values) for arm, values in passed.items()}
    primary = next((arm for arm in spec["primary_qualification_order"] if qualifications[arm]), None)
    assert result["qualifications"] == qualifications and result["primary"] == primary
    assert result["primary_selection_frozen_before_cases"] is True and result["fresh_confirmation_opened"] is False
    assert result["brier_nondegradation_waived"] is False and result["all_blockers_closed"] is False
    return dict(strata=reports, independent_binomial_bounds=70, qualifications=qualifications, primary=primary,
                costs=costs(directory, "calibration", spec["calibration_strata"]))


def bootstrap(stats, primary, spec, worlds):
    """Identical registered draws; independent count-vector reduction."""
    arms = list(stats)
    generators = len(stats[arms[0]])
    controls = [name for name in spec["arms"] if name != primary] + list(spec["feasible_controls"])
    rng = np.random.default_rng(spec["bootstrap_seed"])
    draws = {arm:np.zeros((spec["bootstrap_draws"], 6)) for arm in arms}
    paired = np.zeros((spec["bootstrap_draws"], len(controls) * 2))
    vectors = np.concatenate([stats[arm][:, :6] for arm in arms], axis=1)
    differences = np.column_stack([sign * (stats[primary][:, column] - stats[control][:, column])
        for control in controls for column, sign in ((4, 1), (5, -1))])
    for start in range(0, spec["bootstrap_draws"], spec["bootstrap_batch"]):
        batch = min(spec["bootstrap_batch"], spec["bootstrap_draws"] - start)
        indices = rng.integers(generators, size=(batch, generators))
        multiplicity = np.array([np.bincount(row, minlength=generators) for row in indices], dtype=float)
        all_totals = multiplicity @ vectors
        for j, arm in enumerate(arms):
            totals = all_totals[:, j * 6:(j + 1) * 6]
            value = draws[arm][start:start + batch]
            value[:, 0] = np.divide(totals[:, 3], totals[:, 2], out=np.ones(batch), where=totals[:, 2] > 0)
            value[:, 1] = np.divide(totals[:, 1], totals[:, 0], out=np.ones(batch), where=totals[:, 0] > 0)
            value[:, 2:] = np.column_stack((totals[:, 4:6] / worlds, totals[:, 2] / worlds, totals[:, 0] / worlds))
        paired[start:start + batch] = multiplicity @ differences / worlds
    return draws, paired, controls


def confirmation_audit(directory, spec, laws):
    calibration = read(ROOT / "calibration_01/CALIBRATION.json")
    primary, declared = calibration["primary"], policies(spec, calibration)
    assert primary in spec["primary_qualification_order"] and calibration["qualifications"][primary]
    combined, reports, contracts = read(directory / "SUMMARY.json"), {}, []
    for name, count in spec["confirmation_worlds"].items():
        stats, invalid, reports[name] = collect(directory, name, count, spec["worlds_per_generator"], declared, laws)
        saved = archived(read(directory / name / "CLUSTER_STATS_ARCHIVE.json"))
        assert saved["columns"] == COLS and set(saved["models"]) == set(declared)
        for arm in declared:
            close(saved["models"][arm], stats[arm])
        draws, paired, controls = bootstrap(stats, primary, spec, count)
        saved = archived(read(directory / name / "BOOTSTRAP_ARCHIVE.json"))
        assert saved["columns"] == DRAW_COLS and set(saved["models"]) == set(declared)
        assert saved["paired_columns"] == ["primary_minus_" + control + "_" + metric for control in controls for metric in ("utility", "brier_improvement")]
        for arm in declared:
            close(saved["models"][arm], draws[arm])
        close(saved["paired"], paired)
        summary = read(directory / name / "SUMMARY.json")
        assert combined["panels"][name] == summary
        assert summary["primary"] == primary and summary["worlds"] == count and summary["independent_generators"] == count // spec["worlds_per_generator"]
        gates = {}
        for arm, (base, threshold) in declared.items():
            entry, total = summary["policies"][arm], stats[arm].sum(0)
            assert entry["attempts"] == count and entry["invalid"] == invalid[arm] and entry["base_arm"] == base
            assert entry["threshold"] == threshold and entry["calibrated"] == calibration["qualifications"][base]
            assert entry["forecast_law"] == MEMBERS[base][0]
            if invalid[arm]:
                assert entry["quality"] is None
                gates[arm] = False
                continue
            quality = entry["quality"]
            for field, column in (("accepted", 0), ("errors", 1), ("fractional", 2), ("fractional_errors", 3), ("support_losses", 6), ("reads", 7), ("fees", 8)):
                close(quality[field], total[column])
            for field, value in (("mean_utility", total[4] / count), ("before_brier", total[5] / count), ("mean_read_net_effect", total[9] / count), ("fractional_rate", total[2] / count), ("answer_rate", total[0] / count)):
                close(quality[field], value)
            upper = np.quantile(draws[arm][:, :2], .95, axis=0)
            close([quality["upper95_fractional_risk"], quality["upper95_overall_risk"]], upper)
            gate = bool(entry["calibrated"] and not total[6] and total[2] >= spec["minimum_fractional_count"] and total[2] / count >= spec["minimum_fractional_rate"] and max(upper) <= spec["risk_limit"])
            assert quality["risk_coverage_gate"] == gate
            gates[arm] = gate
        brier_gates, utility_gates = {}, {}
        for j, control in enumerate(controls):
            entry = summary["comparisons"][control]
            if invalid[primary] or invalid[control]:
                assert entry is None
                brier_gates[control] = utility_gates[control] = False
                continue
            difference = (stats[primary] - stats[control]).sum(0) / count
            ci = np.quantile(paired[:, 2 * j:2 * j + 2], [.025, .975], axis=0)
            close([entry["utility_difference"], entry["brier_improvement"]], [difference[4], -difference[5]])
            close(entry["utility_ci95"], ci[:, 0]); close(entry["brier_ci95"], ci[:, 1])
            assert entry["calibrated_control"] == calibration["qualifications"][declared[control][0]]
            brier_gates[control], utility_gates[control] = bool(ci[0, 1] >= 0), bool(ci[0, 0] > 0)
        brier = all(brier_gates[name] for name in spec["primary_brier_controls"])
        utility = all(utility_gates[name] for name in spec["feasible_controls"])
        contract = gates[primary] and brier and utility
        assert summary["brier_nondegradation_gate"] == brier and summary["paid_utility_gain_gate"] == utility
        assert summary["bounded_content_contract_passed"] == contract
        assert summary["all_blockers_closed"] is False and summary["full_model_adoption"] is False
        contracts.append(contract)
        reports[name].update(primary_risk_coverage=gates[primary], strict_brier=brier, paid_utility=utility, contract=contract,
                             bootstrap_model_coordinates=sum(draw.size for draw in draws.values()), paired_coordinates=paired.size)
    assert combined["primary"] == primary and combined["all_panels_bounded_content_contract_passed"] == all(contracts)
    assert all(combined[key] is False for key in ("all_blockers_closed", "full_model_adoption", "production_activation"))
    return dict(panels=reports, all_panels_contract=all(contracts), costs=costs(directory, "confirmation", spec["confirmation_worlds"]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True, choices=("calibration", "confirmation"))
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    start, cpu = time.perf_counter(), time.process_time()
    spec = read(ROOT / "protocol.json")
    source = frozen("SOURCE_FREEZE.json", "SOURCE_PUBLICATION.json")
    post = frozen("POSTCALIBRATION_FREEZE.json", "CALIBRATION_PUBLICATION.json") if args.stage == "confirmation" else None
    directory = args.directory or ROOT / (args.stage + "_01")
    result = (calibration_audit if args.stage == "calibration" else confirmation_audit)(directory, spec, models(spec))
    result.update(passed=True, stage=args.stage, source=source, postcalibration=post,
        checker_sha256=sha(Path(__file__)), helper_sha256=sha(ROOT / "independent_campaign_reference.py"),
        maximum_absolute_recompute_difference=MAX_DIFFERENCE, audit_cpu_seconds=time.process_time() - cpu,
        audit_wall_seconds=time.perf_counter() - start, max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        new_world_generator_calls=0, scope="Independent arithmetic and bounded Cartesian replay; finite known law families only; no universal coverage or analytic-core attribution")
    output = args.output or ROOT / ("INDEPENDENT_" + args.stage.upper() + "_CHECK.json")
    with output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False); stream.write("\n")
    print(json.dumps(result, sort_keys=True, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
