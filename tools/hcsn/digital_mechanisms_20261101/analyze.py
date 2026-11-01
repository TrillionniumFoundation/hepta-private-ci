"""Independent fit-level statistics and measured cost accounting.

No policy, task simulator or training implementation is imported. All declared
fits and all 24 fitted candidates must be present; episodes never become the
sample size for the between-fit uncertainty intervals.
"""
import argparse
import gzip
import itertools
import json
import math
from pathlib import Path

import numpy as np
from scipy import stats

FAMILIES = ("ordinary_base", "ordinary_bank", "clocked_bank", "first_passage_bank", "raw_history")
CPU_ARMS = ("ordinary_bank__structured_on__cpu", "first_passage_bank__structured_on__cpu",
            "first_passage_bank__impulse_on__cpu", "evidence_accumulator__structured_on__cpu")
ARMS = tuple(f"{family}__{method}" for family in FAMILIES
             for method in ("free_off", "structured_off", "structured_on")) + tuple(
    f"{family}__impulse_on" for family in ("ordinary_bank", "clocked_bank", "first_passage_bank")) + (
    "evidence_accumulator__free_off", "evidence_accumulator__structured_on") + CPU_ARMS
PRIMARY_NAMES = ("terminal_structure", "occupancy_supervision", "impulse_mechanism", "analytic_increment")


def read_json(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"required evidence missing: {path}")
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.name.endswith(".gz") else raw)


def _fit_ids(protocol, development=False):
    fits = protocol["development_fits" if development else "fits"]
    if (not isinstance(fits, list) or len(fits) < 2 or len(set(fits)) != len(fits)
            or any(not isinstance(fit, int) or isinstance(fit, bool) for fit in fits)):
        raise ValueError("at least two distinct registered integer fit IDs required")
    return fits


def _check_directories(root, fits):
    actual = {p.name for p in Path(root).glob("fit_*") if p.is_dir()}
    expected = {f"fit_{fit}" for fit in fits}
    if actual != expected:
        raise ValueError(f"registered fit directory mismatch: missing={sorted(expected-actual)}, extra={sorted(actual-expected)}")


def _index_summary(rows, fit, splits, protocol):
    expected = set(itertools.product(splits, (*ARMS, "bayes"), ("fixed", "value")))
    indexed = {}
    for row in rows:
        key = (row["split"], row["candidate"], row["controller"])
        if row["fit"] != fit or key not in expected or key in indexed:
            raise ValueError(f"unexpected or duplicate summary record for fit {fit}: {key}")
        if row["worlds"] != protocol[f"{row['split']}_worlds"]:
            raise ValueError(f"world count mismatch for fit {fit}: {key}")
        metrics = row["metrics"]
        if "utility" not in metrics or any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in metrics.values()):
            raise ValueError("finite numeric summary metrics required")
        indexed[key] = metrics
    if set(indexed) != expected:
        raise ValueError(f"missing declared candidate/controller/split records for fit {fit}")
    return indexed


def _primary(indexed, split, metric="utility"):
    def v(candidate):
        return indexed[(split, candidate, "value")][metric]
    return dict(
        terminal_structure=float(np.mean([v(f"{family}__structured_off") - v(f"{family}__free_off") for family in FAMILIES])),
        occupancy_supervision=v("first_passage_bank__structured_on") - v("first_passage_bank__structured_off"),
        impulse_mechanism=v("first_passage_bank__impulse_on") - v("first_passage_bank__structured_on"),
        analytic_increment=v("first_passage_bank__structured_on") - v("ordinary_bank__structured_on"))


def paired_interval(fits, values, alpha=.05, multiplicity=1, margin=None, signflip=False):
    values = np.asarray(values, dtype=np.float64)
    if values.shape != (len(fits),) or len(fits) < 2 or not np.all(np.isfinite(values)):
        raise ValueError("one finite paired difference per independent fit required")
    if not 0 < alpha < 1 or multiplicity < 1:
        raise ValueError("invalid confidence allocation")
    mean, sd = float(values.mean()), float(values.std(ddof=1))
    se = sd / math.sqrt(len(fits))
    critical = float(stats.t.ppf(1 - alpha / (2 * multiplicity), len(fits) - 1))
    interval = [mean - critical * se, mean + critical * se]
    result = dict(fits=list(fits), fit_differences=values.tolist(), n_independent_fits=len(fits),
                  degrees_of_freedom=len(fits)-1, mean=mean, sample_sd=sd, standard_error=se,
                  confidence_interval=interval, alpha_per_interval=alpha/multiplicity,
                  multiplicity=multiplicity, t_critical=critical,
                  distributional_assumption="Student t interval for independent fit-level paired differences")
    if margin is not None:
        result.update(practical_margin=margin, benefit_gate=bool(interval[0] > margin))
    if signflip:
        if len(fits) > 20:
            raise ValueError("exact sign-flip cap exceeded")
        signs = np.asarray(list(itertools.product((-1., 1.), repeat=len(fits))))
        null_values = signs @ values / len(fits)
        result.update(signflip_two_sided_p_unadjusted=float(np.mean(np.abs(null_values) >= abs(mean)-1e-14)),
                      signflip_null="zero effect with symmetric paired differences; descriptive, not the registered gate")
    return result


def plan_from_development(root, protocol):
    fits = _fit_ids(protocol, development=True)
    if len(fits) != 3:
        raise ValueError("registered planning requires exactly three development fits")
    _check_directories(root, fits)
    values = {name: [] for name in PRIMARY_NAMES}
    for fit in fits:
        indexed = _index_summary(read_json(Path(root)/f"fit_{fit}/validation_summary.json"), fit, ("validation",), protocol)
        primary = _primary(indexed, "validation")
        for name in values:
            values[name].append(primary[name])
    alpha, multiplicity = .05, 8
    threshold, target, power, multiplier = .02, .08, .8, 1.25
    z_critical, z_power = float(stats.norm.ppf(1-alpha/(2*multiplicity))), float(stats.norm.ppf(power))
    rows = []
    for name, differences in values.items():
        sd = float(np.std(differences, ddof=1))
        requested = math.ceil(((z_critical+z_power)*multiplier*sd/(target-threshold))**2)
        rows.append(dict(contrast=name, fit_ids=fits, fit_differences=differences,
                         sample_sd=sd, heuristic_planning_sd=multiplier*sd, required_fits_normal_approx=requested))
    required = max(row["required_fits_normal_approx"] for row in rows)
    selected = min(16, max(8, required))
    return dict(schema="digital-mechanism-fit-planning-v1", development_fits=fits, contrasts=rows,
                alpha=alpha, simultaneous_intervals=multiplicity, target_power=power,
                benefit_threshold=threshold, planning_true_effect=target,
                heuristic_sd_multiplier=multiplier, multiplier_is_confidence_bound=False,
                z_critical=z_critical, z_power=z_power, maximum_requested_fits=required,
                minimum_fits=8, resource_cap_fits=16, selected_fits=selected,
                resource_cap_binds=required>16, planned_power_claim=False,
                interpretation="Normal-approximation planning from only three validation fits; sd x1.25 is a heuristic, not a variance confidence bound. A binding resource cap explicitly misses the nominal planning requirement; finite-sample t power is not certified.")


def _process_receipt(root, fit, expected_stage, allow_failed=False):
    receipt = read_json(Path(root)/f"process_receipts/fit_{fit}.json")
    if receipt["fit"] != fit or receipt["stage"] != expected_stage or (receipt["returncode"] != 0 and not allow_failed):
        raise ValueError(f"missing successful {expected_stage} process for fit {fit}")
    for key in ("whole_process_cpu_seconds", "user_cpu_seconds", "system_cpu_seconds", "whole_process_wall_seconds", "peak_rss_kib"):
        if not math.isfinite(receipt[key]) or receipt[key] < 0:
            raise ValueError("nonfinite or negative full-process cost")
    if abs(receipt["whole_process_cpu_seconds"]-receipt["user_cpu_seconds"]-receipt["system_cpu_seconds"]) > 1e-6:
        raise ValueError("external process CPU accounting mismatch")
    return receipt


def _audit_raw_episodes(root, fit, indexed, protocol):
    checked = 0
    for split in ("iid", "ood"):
        rows = read_json(Path(root)/f"fit_{fit}/{split}_episodes.json.gz")
        groups = {key: [] for key in indexed if key[0] == split}
        for row in rows:
            key = (row["split"], row["candidate"], row["controller"])
            if row["fit"] != fit or key not in groups or not row["label_access_after_terminal"]:
                raise ValueError("invalid raw episode identity or terminal scoring order")
            groups[key].append(row)
        common_worlds = None
        for key, episodes in groups.items():
            worlds = [row["world"] for row in episodes]
            if len(worlds) != protocol[f"{split}_worlds"] or len(worlds) != len(set(worlds)):
                raise ValueError("missing or duplicated paired raw world")
            if common_worlds is not None and set(worlds) != common_worlds:
                raise ValueError("candidate arms do not share paired worlds")
            common_worlds = set(worlds)
            metrics = indexed[key]
            if any(set(row["metrics"]) != set(metrics) for row in episodes):
                raise ValueError("summary/raw metric schema mismatch")
            for metric in metrics:
                values = [row["metrics"][metric] for row in episodes]
                if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
                    raise ValueError("nonfinite raw episode metric")
                mean = float(np.mean(values))
                if not math.isclose(mean, metrics[metric], rel_tol=1e-10, abs_tol=1e-12):
                    raise ValueError("raw mean does not reproduce published fit summary")
                metrics[metric] = mean
                checked += 1
    return checked


def _training_records(root, fit, protocol):
    folder = Path(root)/f"fit_{fit}"
    finished = read_json(folder/"FINISHED.json")
    if finished["fit"] != fit or finished["development"] or set(finished["models"]) != set(ARMS):
        raise ValueError("incomplete or mislabeled formal training fit")
    receipts = {}
    for arm in ARMS:
        row = read_json(folder/"training"/(arm+".json.gz"))
        expected_budget = "cpu" if arm in CPU_ARMS else "updates"
        if row["fit"] != fit or row["spec"]["id"] != arm or row["spec"]["budget"] != expected_budget:
            raise ValueError("candidate training budget identity mismatch")
        if row["batch_size"] != protocol["batch_states"]:
            raise ValueError("candidate batch/update budget mismatch")
        if expected_budget == "updates" and row["optimizer_updates"] != protocol["updates"]:
            raise ValueError("declared equal-update candidate has incomplete update budget")
        if expected_budget == "cpu":
            if (row["training_cpu_budget"] != protocol["training_cpu_seconds"]
                    or row["learning_cpu_seconds"] < protocol["training_cpu_seconds"]
                    or abs(row["cpu_budget_overshoot"] - (row["learning_cpu_seconds"]-protocol["training_cpu_seconds"])) > 1e-6):
                raise ValueError("declared equal-CPU candidate budget/receipt mismatch")
        if (not math.isfinite(row["learning_cpu_seconds"]) or row["learning_cpu_seconds"] < 0
                or not math.isfinite(row["setup_cpu_seconds"]) or row["setup_cpu_seconds"] < 0):
            raise ValueError("invalid measured training CPU")
        receipts[arm] = row
    return finished, receipts


def analyze_confirmation(confirmation_root, training_root, protocol, development_root=None, additional_attempt_roots=()):
    fits = _fit_ids(protocol)
    _check_directories(confirmation_root, fits)
    _check_directories(training_root, fits)
    indexed, training, process = {}, {}, []
    source, raw_mean_checks = None, 0
    for fit in fits:
        indexed[fit] = _index_summary(read_json(Path(confirmation_root)/f"fit_{fit}/summary.json"), fit, ("iid", "ood"), protocol)
        raw_mean_checks += _audit_raw_episodes(confirmation_root, fit, indexed[fit], protocol)
        finished, training[fit] = _training_records(training_root, fit, protocol)
        if source is not None and finished["source_sha256"] != source:
            raise ValueError("formal fits do not share one frozen source combination")
        source = finished["source_sha256"]
        process.extend((_process_receipt(training_root, fit, "train"),
                        _process_receipt(confirmation_root, fit, "confirm")))
    if development_root is not None:
        for fit in _fit_ids(protocol, development=True):
            process.append(_process_receipt(development_root, fit, "development"))
    root_paths = [str(Path(root).resolve()) for root in additional_attempt_roots]
    if len(root_paths) != len(set(root_paths)) or set(root_paths) & {
            str(Path(root).resolve()) for root in (confirmation_root, training_root, development_root) if root is not None}:
        raise ValueError("duplicate attempt cost roots would double count process work")
    additional_processes = []
    for root in additional_attempt_roots:
        paths = sorted((Path(root)/"process_receipts").glob("fit_*.json"))
        if not paths:
            raise ValueError("requested additional attempt has no external CPU receipts")
        for path in paths:
            row = read_json(path)
            additional_processes.append(_process_receipt(root, row["fit"], row["stage"], allow_failed=True))
    process.extend(additional_processes)
    primaries, controller_effects, factorial, family_terminal = [], [], [], []
    quality = ("correct", "submitted", "wrong_stop", "wrong_submit", "terminal_sign_error",
               "selected_q_squared_error", "oracle_regret", "selected_margin", "aggregated_strata_unseen")
    for split in ("iid", "ood"):
        for name in PRIMARY_NAMES:
            values = [_primary(indexed[fit], split)[name] for fit in fits]
            result = paired_interval(fits, values, multiplicity=8, margin=.02, signflip=True)
            diagnostics = {}
            for metric in quality:
                if all(metric in row for fit in fits for row in indexed[fit].values()):
                    diagnostics[metric] = float(np.mean([_primary(indexed[fit], split, metric)[name] for fit in fits]))
            primaries.append(dict(contrast=name, split=split, **result, descriptive_diagnostic_differences=diagnostics))
        for arm in (*ARMS, "bayes"):
            difference = [indexed[fit][split, arm, "value"]["utility"]-indexed[fit][split, arm, "fixed"]["utility"] for fit in fits]
            controller_effects.append(dict(candidate=arm, split=split, **paired_interval(fits, difference), descriptive=True))
        for family in FAMILIES:
            difference = [indexed[fit][split, f"{family}__structured_off", "value"]["utility"]-
                          indexed[fit][split, f"{family}__free_off", "value"]["utility"] for fit in fits]
            family_terminal.append(dict(family=family, split=split, **paired_interval(fits, difference), descriptive=True))
        for method in ("free_off", "structured_off", "structured_on", "structured_on__cpu"):
            contrasts = {name: [] for name in ("B-A", "D-C", "C-A", "D-B", "interaction")}
            means = {arm: [] for arm in "ABCD"}
            for fit in fits:
                a, b = [indexed[fit][split, f"ordinary_bank__{method}", c]["utility"] for c in ("fixed", "value")]
                c, d = [indexed[fit][split, f"first_passage_bank__{method}", controller]["utility"] for controller in ("fixed", "value")]
                for arm, value in zip("ABCD", (a,b,c,d)):
                    means[arm].append(value)
                for name, value in zip(contrasts, (b-a, d-c, c-a, d-b, (d-c)-(b-a))):
                    contrasts[name].append(value)
            factorial.append(dict(method=method, split=split, fits=fits, arm_fit_means=means,
                                  contrasts={name: paired_interval(fits, values) for name, values in contrasts.items()}, descriptive=True))
    mean_panel = []
    for split, arm, controller in itertools.product(("iid", "ood"), (*ARMS, "bayes"), ("fixed", "value")):
        keys = set.intersection(*(set(indexed[fit][split, arm, controller]) for fit in fits))
        mean_panel.append(dict(split=split, candidate=arm, controller=controller,
                               metrics={key: float(np.mean([indexed[fit][split, arm, controller][key] for fit in fits])) for key in sorted(keys)},
                               fit_utility=[indexed[fit][split, arm, controller]["utility"] for fit in fits]))
    cost_panel = []
    for arm in ARMS:
        rows = [training[fit][arm] for fit in fits]
        cost_panel.append(dict(candidate=arm, fits=fits, budget=rows[0]["spec"]["budget"],
                               learning_cpu_seconds=[r["learning_cpu_seconds"] for r in rows],
                               setup_cpu_seconds=[r["setup_cpu_seconds"] for r in rows],
                               optimizer_updates=[r["optimizer_updates"] for r in rows],
                               overshoot_seconds=[r["cpu_budget_overshoot"] for r in rows],
                               nominal_cpu_budget=protocol["training_cpu_seconds"] if arm in CPU_ARMS else None,
                               capacity_by_fit=[r["capacity"] for r in rows],
                               scope="Assigned training setup/learning; these are nested within external process totals"))
    cost_totals = {stage: sum(row["whole_process_cpu_seconds"] for row in process if row["stage"] == stage)
                   for stage in sorted({"development", "train", "confirm"} | {row["stage"] for row in process})}
    return dict(schema="digital-mechanism-confirmation-analysis-v1", fits=fits,
                unit="independent fitted model/paired-world mean; not decisions or episodes",
                primary_results=primaries, all_eight_benefit_gates=all(row["benefit_gate"] for row in primaries),
                independently_recomputed_raw_means=raw_mean_checks,
                controller_value_minus_fixed=controller_effects, family_terminal_constraints=family_terminal,
                two_by_two=factorial, means=mean_panel, training_cost_panel=cost_panel,
                external_process_receipts=process, external_process_cpu_by_stage=cost_totals,
                external_process_cpu_total=sum(cost_totals.values()),
                development_cost_included=development_root is not None,
                additional_attempt_processes=additional_processes,
                wall_times_not_added_as_parallel_elapsed=True,
                cost_superiority_gate=False, cost_superiority_established=False,
                cost_limitation="Per-candidate execution and training work are measured; common setup, development, imports, serialization, diagnostics and shutdown are retained in whole-process totals. Deployment reuse/amortization and hardware energy are not fixed, so no complete-cost superiority gate is claimed. Nominal CPU-budget arms report actual overshoot and updates.",
                no_confirmation_tuning_claim="Source/model freezing and fresh-generation chronology require their separate provenance audit; fit-level statistics alone do not prove it.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("plan", "confirmation"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--development", type=Path)
    parser.add_argument("--confirmation", type=Path)
    parser.add_argument("--training", type=Path)
    parser.add_argument("--attempt-root", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    protocol = read_json(args.protocol)
    if args.stage == "plan":
        result = plan_from_development(args.development, protocol)
    else:
        result = analyze_confirmation(args.confirmation, args.training, protocol, args.development, args.attempt_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
