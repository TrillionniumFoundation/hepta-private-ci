"""Prespecified analysis of recorded outcomes; never generates confirmation data."""

import argparse
import csv
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t


ORDINARY, ANALYTIC = "ordinary_distribution", "analytic_distribution"
CONDITION = ("task", "seed", "family", "train_mode", "exec_mode", "domain")
BOOTSTRAPS, BOOTSTRAP_SEED = 5000, 151999
POSTERIOR_UPPER_LOSS_LIMIT = 1e-7
CONTRASTS = {"B-A": (-1, 1, 0, 0), "D-C": (0, 0, -1, 1),
             "C-A": (-1, 0, 1, 0), "D-B": (0, -1, 0, 1),
             "interaction": (1, -1, -1, 1)}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, data):
    with Path(path).open("x") as stream:
        json.dump(data, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def load_arrays(root, row):
    path = (root / row["path"]).resolve()
    if not path.is_relative_to(root.resolve()) or sha(path) != row["sha256"]:
        raise ValueError("Recorded artifact path or hash is invalid: " + row["path"])
    with np.load(path, allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in archive.files}
    if "partition_ids" not in arrays:
        raise ValueError("Missing coarse partition identities: " + row["path"])
    return arrays


def fit_interval(values):
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 1 or len(values) < 2 or not np.isfinite(values).all():
        raise ValueError("At least two finite paired fit values required")
    mean = float(values.mean())
    half = float(student_t.ppf(.975, len(values)-1) * values.std(ddof=1) / np.sqrt(len(values)))
    return dict(mean=mean, fit_values=values.tolist(), fit_count=len(values),
                fit_t95=[mean-half, mean+half], fit_df=len(values)-1,
                positive_fit_count=int((values > 0).sum()),
                positive_fit_fraction=float((values > 0).mean()))


class Analysis:
    """Two uncertainties: paired fit means and fixed-fit object resampling."""

    def __init__(self, seeds):
        self.seeds, self.cluster_cache, self.csv_rows = list(seeds), {}, []

    def effect(self, matrix, partitions):
        matrix = np.asarray(matrix, dtype=np.float64)
        partitions = np.asarray(partitions)
        if matrix.shape != (len(self.seeds), len(partitions)) or not np.isfinite(matrix).all():
            raise ValueError("Unpaired or nonfinite fit/object effect array")
        result = fit_interval(matrix.mean(1))
        result["fit_seeds"] = self.seeds
        key = hashlib.sha256(partitions.tobytes()).hexdigest()
        if key not in self.cluster_cache:
            unique, inverse, counts = np.unique(partitions, return_inverse=True, return_counts=True)
            if len(unique) < 2:
                raise ValueError("At least two heldout partition clusters required")
            weights = np.random.default_rng(BOOTSTRAP_SEED).multinomial(
                len(unique), np.full(len(unique), 1/len(unique)), size=BOOTSTRAPS)
            self.cluster_cache[key] = inverse, counts, weights, weights @ counts
        inverse, counts, weights, denominator = self.cluster_cache[key]
        # Every heldout object contributes once after averaging fixed fit seeds.
        per_object = matrix.mean(0)
        sums = np.bincount(inverse, weights=per_object, minlength=len(counts))
        bootstrap = (weights @ sums) / denominator
        result.update(object_count=len(partitions), partition_cluster_count=len(counts),
                      fixed_fit_object_cluster95=np.quantile(bootstrap, [.025, .975]).tolist(),
                      equal_partition_mean=float((sums/counts).mean()),
                      object_resampling="Resample whole partition_ids with replacement; all rows within a selected cluster retained; variable-size ratio mean; fit seeds averaged first",
                      bootstrap_replicates=BOOTSTRAPS, bootstrap_seed=BOOTSTRAP_SEED,
                      intervals_are_nominal_not_simultaneous=True)
        return result

    def append_effect(self, task, domain, estimand, contrast, matrix, partitions, **details):
        stats = self.effect(matrix, partitions)
        result = dict(task=task, domain=domain, estimand=estimand, contrast=contrast,
                      negative_control=domain.startswith("missing"), **details, **stats)
        self.csv_rows.append(dict(task=task, domain=domain, estimand=estimand, contrast=contrast,
            negative_control=result["negative_control"], mean=stats["mean"],
            fit_t95_low=stats["fit_t95"][0], fit_t95_high=stats["fit_t95"][1],
            positive_fit_fraction=stats["positive_fit_fraction"], fit_count=stats["fit_count"],
            object_count=stats["object_count"], partition_clusters=stats["partition_cluster_count"],
            object_cluster95_low=stats["fixed_fit_object_cluster95"][0],
            object_cluster95_high=stats["fixed_fit_object_cluster95"][1]))
        return result


def aligned(reference, candidate):
    for name in ("labels", "ids", "partition_ids", "context_ids"):
        if name not in candidate or not np.array_equal(reference[name], candidate[name]):
            raise ValueError("Paired conditions disagree in " + name)


def metrics(arrays):
    return dict(utility=arrays["utility"].astype(np.float64),
                accuracy=(arrays["prediction"] == arrays["labels"]).astype(np.float64),
                read_count=arrays["read_count"].astype(np.float64),
                fee=arrays["fee"].astype(np.float64),
                initial_stop=(arrays["read_count"] == 0).astype(np.float64))


def main_effects(root, protocol, training, analysis):
    rows = read(root / "EVALUATION_INDEX.json")["records"]
    table = {}
    for row in rows:
        key = tuple(row[name] for name in CONDITION)
        if key in table:
            raise ValueError("Duplicate evaluation condition")
        table[key] = row
    expected = {(task, seed, family, mode, execution, domain)
                for task in protocol["tasks"] for seed in protocol["seeds"]
                for family in protocol["families"] for domain in protocol["domains"][task]
                for mode, execution in (("light", "light"), ("value", "light"), ("value", "value"))}
    if set(table) != expected:
        raise ValueError("Incomplete or extra evaluation matrix")
    effects, conditional, selected, outcomes, anchors = [], [], [], [], {}
    ablation_rows = read(root / "ABLATION_INDEX.json")["records"]
    ablation_table = {(r["task"], r["seed"], r["domain"], r["ablation"]): r for r in ablation_rows}
    ablations = []
    for task in protocol["tasks"]:
        for domain in protocol["domains"][task]:
            loaded, reference = {}, None
            for family in protocol["families"]:
                for mode, execution in (("light", "light"), ("value", "light"), ("value", "value")):
                    measurements = []
                    for seed in protocol["seeds"]:
                        item = load_arrays(root, table[(task, seed, family, mode, execution, domain)])
                        if reference is None:
                            reference = item
                        aligned(reference, item)
                        loaded[(seed, family, mode, execution)] = item
                        measurements.append(metrics(item))
                    summary = {name: fit_interval([m[name].mean() for m in measurements])
                               for name in measurements[0]}
                    outcomes.append(dict(task=task, domain=domain, family=family, train_mode=mode,
                        exec_mode=execution, negative_control=domain.startswith("missing"),
                        object_count=len(reference["ids"]), partition_cluster_count=len(np.unique(reference["partition_ids"])),
                        metrics=summary))
            partitions = reference["partition_ids"]
            arms, same_weights, strongest, chosen = [], [], [], {}
            for seed in protocol["seeds"]:
                a = loaded[(seed, ORDINARY, "light", "light")]["utility"]
                b = loaded[(seed, ORDINARY, "value", "value")]["utility"]
                c = loaded[(seed, ANALYTIC, "light", "light")]["utility"]
                d = loaded[(seed, ANALYTIC, "value", "value")]["utility"]
                av = loaded[(seed, ORDINARY, "value", "light")]["utility"]
                cv = loaded[(seed, ANALYTIC, "value", "light")]["utility"]
                arms.append(np.stack((a, b, c, d)).astype(np.float64))
                same_weights.append(np.stack((av, b, cv, d)).astype(np.float64))
                family = training[(task, seed, "value")]["strongest_ordinary"]
                if family not in protocol["families"] or family.startswith("analytic"):
                    raise ValueError("Invalid validation-selected ordinary comparator")
                chosen[str(seed)] = family
                strongest.append(d.astype(np.float64)-loaded[(seed, family, "value", "value")]["utility"])
            arms, same_weights = np.stack(arms), np.stack(same_weights)
            for name, coefficient in CONTRASTS.items():
                weights = np.asarray(coefficient)[None, :, None]
                effects.append(analysis.append_effect(task, domain, "independent_training_total_effect", name,
                                                      (arms*weights).sum(1), partitions))
                conditional.append(analysis.append_effect(task, domain, "value_weights_execution_effect", name,
                                                          (same_weights*weights).sum(1), partitions,
                                                          light_arms="A,C are read-all execution of value-trained weights"))
            selected.append(analysis.append_effect(task, domain, "validation_selected_ordinary", "D-B_selected",
                                                  np.stack(strongest), partitions, selected_families=chosen,
                                                  selection_source="value training SUMMARY.strongest_ordinary; never confirmation ranking"))
            for ablation in ("content_independence", "mean_position", "readout_independence"):
                changes = []
                for seed in protocol["seeds"]:
                    row = ablation_table[(task, seed, domain, ablation)]
                    item = load_arrays(root, row); aligned(reference, item)
                    full = loaded[(seed, ANALYTIC, "value", "value")]
                    changes.append(full["utility"].astype(np.float64)-item["utility"])
                detail = {} if ablation != "readout_independence" else dict(
                    instantaneous_readout_preserved=True, unweighted_content_mean_preserved=False,
                    intervention_scope="At each intervention replace each position's content moment by probability times one common content vector normalized to preserve the current weighted read_state, logits and controller scores. Later differences test propagation after removing position-content dependence rather than an immediate readout shock.")
                ablations.append(analysis.append_effect(task, domain, "same_weights_distribution_ablation",
                                                       "full_minus_"+ablation, np.stack(changes), partitions, **detail))
            anchors[(task, domain)] = {"partition_ids": partitions, "ids": reference["ids"],
                                       "context_ids": reference["context_ids"], "labels": reference["labels"]}
    return dict(outcomes=outcomes, total_effects=effects, conditional_execution_effects=conditional,
                validation_selected_comparator=selected, distribution_ablations=ablations), anchors


def cpu_comparisons(root, protocol, training):
    records = read(root / "COST_INDEX.json")["records"]
    table = {tuple(r[name] for name in CONDITION): r for r in records}
    if len(table) != len(records):
        raise ValueError("Duplicate CPU condition")
    result = []
    for task in protocol["tasks"]:
        for domain in protocol["domains"][task]:
            if domain.startswith("missing"):
                continue
            for mode, execution in (("light", "light"), ("value", "light"), ("value", "value")):
                comparisons = ("primary_pair", "validation_selected_ordinary") if execution == "value" else ("primary_pair",)
                for comparison, batch, phase in itertools.product(comparisons, (1, 16), ("cold", "warm_median3")):
                    paired = []
                    for seed in protocol["seeds"]:
                        ordinary = ORDINARY if comparison == "primary_pair" else training[(task, seed, "value")]["strongest_ordinary"]
                        values = {}
                        for family in (ordinary, ANALYTIC):
                            record = table[(task, seed, family, mode, execution, domain)]
                            selected = [x for x in record["measurements"] if x["batch_size"] == batch
                                        and (x["phase"] == "cold" if phase == "cold" else x["phase"].startswith("warm_"))]
                            if len(selected) != (1 if phase == "cold" else 3):
                                raise ValueError("Incomplete registered cold/warm CPU measurement")
                            values[family] = dict(cpu=float(np.median([x["cpu_seconds"] for x in selected])),
                                wall=float(np.median([x["wall_seconds"] for x in selected])),
                                processed=float(np.median([x["processed_prefix_tokens"] for x in selected])),
                                model_calls=float(np.median([x["model_calls"] for x in selected])))
                        if values[ordinary]["cpu"] <= 0:
                            raise ValueError("Nonpositive measured comparator CPU")
                        paired.append(dict(seed=seed, ordinary_family=ordinary,
                            ordinary_cpu_seconds=values[ordinary]["cpu"], analytic_cpu_seconds=values[ANALYTIC]["cpu"],
                            analytic_over_ordinary=values[ANALYTIC]["cpu"]/values[ordinary]["cpu"],
                            ordinary_processed_tokens=values[ordinary]["processed"],
                            analytic_processed_tokens=values[ANALYTIC]["processed"],
                            ordinary_wall_seconds=values[ordinary]["wall"], analytic_wall_seconds=values[ANALYTIC]["wall"]))
                    ratios = [x["analytic_over_ordinary"] for x in paired]
                    result.append(dict(task=task, domain=domain, train_mode=mode, exec_mode=execution,
                        comparison=comparison, batch_size=batch, phase=phase,
                        median_paired_ratio=float(np.median(ratios)), minimum_paired_ratio=float(np.min(ratios)),
                        maximum_paired_ratio=float(np.max(ratios)), pairs=paired,
                        scope="Descriptive actual online work on the first 1 or 16 confirmation rows only; not population latency or throughput",
                        cold_scope="Transition matrix cache cleared where supported; not a new process or cold operating system"))
    return result


def training_and_resources(root, protocol, groups):
    training = {(g["task"], g["seed"], g["train_mode"]): g for g in groups}
    expected = set(itertools.product(protocol["tasks"], protocol["seeds"], ("light", "value")))
    if len(training) != len(groups) or set(training) != expected:
        raise ValueError("Training group coverage differs from registration")
    pairs = []
    for task, seed in itertools.product(protocol["tasks"], protocol["seeds"]):
        light, value = training[(task, seed, "light")], training[(task, seed, "value")]
        pairs.append(dict(task=task, seed=seed,
            identical_initialization=light["initial_hashes"] == value["initial_hashes"],
            separate_checkpoint_paths=light["checkpoint_path"] != value["checkpoint_path"],
            selected_hashes_equal={f: light["model_hashes"][f] == value["model_hashes"][f] for f in protocol["families"]},
            final_hashes_equal={f: light["final_hashes"][f] == value["final_hashes"][f] for f in protocol["families"]},
            selected_steps=dict(light=light["selected_step"], value=value["selected_step"]),
            selected_checkpoint_sha256=dict(light=light["checkpoint_sha256"], value=value["checkpoint_sha256"]),
            final_checkpoint_sha256=dict(light=light["final_checkpoint_sha256"], value=value["final_checkpoint_sha256"])))
    if not all(p["identical_initialization"] and p["separate_checkpoint_paths"] for p in pairs):
        raise ValueError("Training treatments lack paired initialization or independent checkpoints")
    bodies = [{"task": g["task"], "seed": g["seed"], "train_mode": g["train_mode"],
               "cpu_seconds": g["training_cpu_seconds"], "wall_seconds": g["training_wall_seconds"]} for g in groups]
    stages = []
    for stage in ("train", "evaluate", "recovery_fit", "recovery_confirm"):
        directory = root / "receipts" / stage
        total_path = directory / "TOTAL.json"
        if not total_path.exists():
            stages.append(dict(stage=stage, available=False)); continue
        total = read(total_path)
        jobs = [read(p) for p in sorted(directory.glob("*.json")) if p.name != "TOTAL.json"]
        jobs = [j for j in jobs if "cpu_user_seconds" in j and "cpu_system_seconds" in j]
        stages.append(dict(stage=stage, available=True, total_receipt=total,
            measured_child_cpu_seconds=sum(j["cpu_user_seconds"]+j["cpu_system_seconds"] for j in jobs),
            child_receipts=len(jobs), child_failures=sum(j["exit_code"] != 0 for j in jobs),
            maximum_rss_kib=max((j["maximum_rss_kib"] for j in jobs), default=None),
            note="Full child CPU includes imports and output work; body CPU is nested and must not be added"))
    return training, dict(independent_training_pairs=pairs, training_body_records=bodies,
        training_body_cpu_seconds_total=sum(x["cpu_seconds"] for x in bodies), worker_stages=stages,
        accounting_rule="Report child worker CPU and nested body CPU separately. Never add body, actor, evaluator or recovery diagnostics to their enclosing worker totals.",
        full_cost_advantage_established=False,
        missing_costs=["GPU", "physical Joules", "production acquisition and service billing", "competitive optimized deployment implementation"])


def recovery_effects(root, protocol, analysis, anchors):
    path = root / "recovery" / "CONFIRMATION_INDEX.json"
    if not path.exists():
        return dict(available=False, scientific_recovery_benefit_established=False)
    rows = read(path)["records"]
    table = {(r["task"], r["seed"], r["family"], r["domain"], r["cohort"]): r for r in rows}
    recovery_protocol = read(root / "recovery" / "PROTOCOL.json")
    expected = set(itertools.product(protocol["tasks"], protocol["seeds"], (ORDINARY, ANALYTIC),
                                     recovery_protocol["confirmation_domains"], recovery_protocol["cohorts"]))
    if len(table) != len(rows) or set(table) != expected:
        raise ValueError("Recovery confirmation coverage differs from registration")
    effects, outcomes, sensitivities, between = [], [], [], []
    for task, domain, cohort in itertools.product(protocol["tasks"], recovery_protocol["confirmation_domains"], recovery_protocol["cohorts"]):
        family_selected = {}
        anchor = anchors[(task, domain)]
        for family in (ORDINARY, ANALYTIC):
            batches, identity = [], None
            for seed in protocol["seeds"]:
                row = table[(task, seed, family, domain, cohort)]
                data = load_arrays(root, row); aligned(anchor, data)
                if identity is not None:
                    for field in ("alarm", "labels", "ids", "partition_ids"):
                        if not np.array_equal(identity[field], data[field]):
                            raise ValueError("Recovery seeds do not share paired objects/faults")
                identity = data; batches.append(data)
            partitions = anchor["partitions"] if "partitions" in anchor else anchor["partition_ids"]
            selected_utility = np.stack([b["selected_utility"] for b in batches])
            none = np.stack([b["utility"][:, 0] for b in batches])
            unprotected = np.stack([b["correct"][:, 0]-b["unprotected_fee"] for b in batches])
            family_selected[family] = selected_utility
            for name, values in (("selected_minus_protected_none", selected_utility-none),
                                 ("selected_minus_unprotected_none", selected_utility-unprotected),
                                 ("reset_replay_minus_none", np.stack([b["utility"][:, 3]-b["utility"][:, 0] for b in batches])),
                                 ("reset_replay_interaction", np.stack([b["utility"][:, 3]-b["utility"][:, 1]-b["utility"][:, 2]+b["utility"][:, 0] for b in batches]))):
                effects.append(analysis.append_effect(task, domain, "recovery_"+family+"_"+cohort,
                                                      name, values, partitions, family=family, cohort=cohort))
            outcomes.append(dict(task=task, domain=domain, cohort=cohort, family=family,
                selected_utility=fit_interval(selected_utility.mean(1)),
                selected_accuracy=fit_interval([b["selected_correct"].mean() for b in batches]),
                selected_fee=fit_interval([b["selected_fee"].mean() for b in batches]),
                clean_accuracy=fit_interval([b["clean_correct"].mean() for b in batches]),
                alarm_fraction=float(batches[0]["alarm"].mean()),
                action_counts_by_fit={str(seed): np.bincount(b["selected_action"], minlength=4).tolist()
                                      for seed, b in zip(protocol["seeds"], batches)}))
            gross = np.stack([b["selected_correct"]-b["correct"][:, 0] for b in batches])
            overhead = np.stack([b["selected_fee"]-b["unprotected_fee"] for b in batches])
            sensitivities.append(dict(task=task, domain=domain, cohort=cohort, family=family,
                fixed_policy=True, values=[dict(incremental_price_multiplier=m,
                    gain_vs_unprotected_none=fit_interval((gross-m*overhead).mean(1)))
                    for m in recovery_protocol["sensitivity_multipliers"]]))
        between.append(analysis.append_effect(task, domain, "recovered_system_"+cohort,
            "analytic_minus_ordinary", family_selected[ANALYTIC]-family_selected[ORDINARY],
            anchor["partition_ids"], cohort=cohort,
            warning="Separately validation-selected recovery rules; not an identical-selector core-only effect"))
    actual = read(root / "recovery" / "ACTUAL_EXECUTION_INDEX.json")["records"]
    return dict(available=True, effects=effects, outcomes=outcomes, sensitivities=sensitivities,
        recovered_system_effects=between, actual_execution_records=actual,
        actual_execution_mismatches=sum(r["prediction_mismatches"]+r["action_mismatches"] for r in actual),
        scientific_recovery_benefit_established=False,
        scope="Diagnosed synthetic faults and trusted cache; service-delay price but no external evolution during recovery; domain/fit effects reported without a general recovery claim")


def acceptance(protocol, results, resources):
    rules = protocol["acceptance"]
    outcome = {(r["task"], r["domain"], r["family"], r["train_mode"], r["exec_mode"]): r
               for r in results["outcomes"]}
    effect = {(r["task"], r["domain"], r["contrast"]): r for r in results["total_effects"]}
    per_task = {}
    for task in rules["required_tasks"]:
        quality = {name: outcome[(task, "iid", family, mode, execution)]["metrics"]["accuracy"]["mean"]
                   for name, family, mode, execution in (("A", ORDINARY, "light", "light"),
                     ("B", ORDINARY, "value", "value"), ("C", ANALYTIC, "light", "light"), ("D", ANALYTIC, "value", "value"))}
        primary = effect[(task, "iid", "D-B")]
        pressure = {domain: effect[(task, domain, "D-B")]["mean"] for domain in rules["pressure_domains"]}
        per_task[task] = dict(iid_accuracies=quality,
            all_four_iid_quality_pass=all(v >= rules["minimum_iid_accuracy"] for v in quality.values()),
            iid_D_minus_B_fit_lower95_pass=primary["fit_t95"][0] > rules["primary_lower95"],
            iid_D_minus_B_positive_seed_fraction_pass=primary["positive_fit_fraction"] >= rules["minimum_positive_seed_fraction"],
            iid_D_minus_B_object_cluster_lower95_positive=primary["fixed_fit_object_cluster95"][0] > 0,
            pressure_D_minus_B_means=pressure,
            pressure_pass=all(v >= rules["pressure_tolerance"] for v in pressure.values()))
    primary_pass = all(all(v[name] for name in ("all_four_iid_quality_pass", "iid_D_minus_B_fit_lower95_pass",
                      "iid_D_minus_B_positive_seed_fraction_pass", "pressure_pass")) for v in per_task.values())
    return dict(protocol_rules=rules, per_task=per_task,
        registered_quality_effect_pressure_gate_pass=primary_pass,
        full_cost_advantage_established=resources["full_cost_advantage_established"],
        foundation_core_acceptance=False, all_user_requirements_closed=False,
        remaining_out_of_scope=["full conditional content law beyond first-moment closure", "general learned/moving boundaries",
            "real multimodal media", "large-scale extrapolation", "physical energy and GPU", "production acquisition/service economics"],
        reason="Implementation coverage is separate from scientific acceptance; full-cost and general-system requirements remain unestablished")


def posterior_qualification(root, protocol, groups):
    """Recompute observed tail diagnostics; never promote them to full-law proof."""
    validation, confirmation = [], []
    for group in groups:
        for family in (ORDINARY, ANALYTIC):
            for domain in protocol["domains"][group["task"]]:
                item = group.get("posterior_qualification", {}).get(family, {}).get(domain)
                row = dict(task=group["task"], seed=group["seed"], train_mode=group["train_mode"],
                           family=family, domain=domain, evidence_available=item is not None,
                           evidence_scope="selected-model validation maxima in training SUMMARY")
                if item is None:
                    row.update(upper_loss_pass=False, finite_diagnostics=False, metadata_consistent=False)
                else:
                    values = {name: float(item[name]) for name in
                              ("maximum_upper_loss", "maximum_mass_error", "minimum_probability")}
                    finite = all(np.isfinite(v) for v in values.values())
                    passed = finite and values["maximum_upper_loss"] <= POSTERIOR_UPPER_LOSS_LIMIT
                    row.update({name: value if np.isfinite(value) else None for name, value in values.items()})
                    row.update(upper_loss_pass=passed, finite_diagnostics=finite,
                               metadata_consistent=bool(item["upper_loss_pass"]) == passed)
                validation.append(row)
    index = read(root / "EVALUATION_INDEX.json")["records"]
    fields = ("upper_loss_prefix", "mass_error_prefix", "minimum_probability_prefix")
    for entry in index:
        if entry["family"] not in (ORDINARY, ANALYTIC):
            continue
        data = load_arrays(root, entry)
        row = {name: entry[name] for name in CONDITION}
        available = all(name in data for name in fields) and "posterior_qualification" in entry
        row.update(evidence_available=available, evidence_scope="recomputed from retained selected-model prefix arrays")
        if not available:
            row.update(all_prefix_upper_loss_pass=False, occupied_upper_loss_pass=False,
                       finite_diagnostics=False, metadata_consistent=False)
            confirmation.append(row); continue
        shape = (len(data["ids"]), data["dt"].shape[1] + 1)
        if any(data[name].shape != shape for name in fields):
            raise ValueError("Posterior prefix diagnostic shape does not match the causal timeline")
        upper, mass, minimum = (data[name] for name in fields)
        occupied = np.arange(shape[1])[None] <= data["read_count"][:, None]
        finite = all(np.isfinite(data[name]).all() for name in fields)
        row.update(finite_diagnostics=bool(finite), all_prefix_count=int(upper.size),
                   occupied_prefix_count=int(occupied.sum()))
        if not finite:
            row.update(all_prefix_upper_loss_pass=False, occupied_upper_loss_pass=False,
                       metadata_consistent=False, diagnostic_failure="nonfinite retained prefix diagnostic")
            confirmation.append(row); continue
        values = dict(all_prefix_maximum_upper_loss=float(upper.max()),
                      occupied_maximum_upper_loss=float(upper[occupied].max()),
                      maximum_mass_error=float(mass.max()), minimum_probability=float(minimum.min()))
        all_pass = values["all_prefix_maximum_upper_loss"] <= POSTERIOR_UPPER_LOSS_LIMIT
        occupied_pass = values["occupied_maximum_upper_loss"] <= POSTERIOR_UPPER_LOSS_LIMIT
        metadata = entry["posterior_qualification"]
        consistency = all(name in metadata and np.isclose(float(metadata[name]), value, rtol=1e-12, atol=1e-15)
                          for name, value in values.items())
        consistency &= bool(metadata.get("all_prefix_upper_loss_pass")) == all_pass
        row.update(**values, all_prefix_upper_loss_pass=all_pass, occupied_upper_loss_pass=occupied_pass,
                   metadata_consistent=bool(consistency),
                   all_prefix_exceeding_object_count=int(np.any(upper > POSTERIOR_UPPER_LOSS_LIMIT, axis=1).sum()),
                   occupied_exceeding_object_count=int(np.any((upper > POSTERIOR_UPPER_LOSS_LIMIT) & occupied, axis=1).sum()))
        confirmation.append(row)
    available = bool(validation and confirmation) and all(r["evidence_available"] for r in validation+confirmation)
    finite = available and all(r["finite_diagnostics"] for r in validation+confirmation)
    consistent = available and all(r["metadata_consistent"] for r in validation+confirmation)
    val_pass = finite and consistent and all(r["upper_loss_pass"] for r in validation)
    all_pass = finite and consistent and all(r["all_prefix_upper_loss_pass"] for r in confirmation)
    occupied_pass = finite and consistent and all(r["occupied_upper_loss_pass"] for r in confirmation)
    def maximum(records, name):
        values = [r[name] for r in records if r.get(name) is not None]
        return max(values) if values else None
    return dict(upper_loss_limit=POSTERIOR_UPPER_LOSS_LIMIT, evidence_complete=available,
        finite_diagnostics=finite, metadata_consistent=consistent,
        validation_upper_loss_pass=val_pass, confirmation_all_prefix_upper_loss_pass=all_pass,
        confirmation_occupied_upper_loss_pass=occupied_pass,
        registered_continuous_tail_qualification_pass=val_pass and all_pass,
        maximum_validation_upper_loss=maximum(validation, "maximum_upper_loss"),
        maximum_confirmation_upper_loss=maximum(confirmation, "all_prefix_maximum_upper_loss"),
        maximum_occupied_confirmation_upper_loss=maximum(confirmation, "occupied_maximum_upper_loss"),
        maximum_reported_mass_error=maximum(validation+confirmation, "maximum_mass_error"),
        minimum_reported_probability=min((r["minimum_probability"] for r in validation+confirmation
                                           if r.get("minimum_probability") is not None), default=None),
        validation_records=validation, confirmation_records=confirmation,
        validation_failed_conditions=sum(not r.get("upper_loss_pass", False) for r in validation),
        confirmation_failed_all_prefix_conditions=sum(not r.get("all_prefix_upper_loss_pass", False) for r in confirmation),
        confirmation_failed_occupied_conditions=sum(not r.get("occupied_upper_loss_pass", False) for r in confirmation),
        finite_model_results_retained=True, original_full_successor_requirement_closed=False,
        scope="Upper loss is cumulative cemetery mass under the actual learned posterior. Exceeding 1e-7 fails the registered continuous-tail gate while retaining finite-model outcomes. A passing tail gate alone does not certify the continuous full successor, gradient, moment closure, reset semantics or the user's original complete-process requirement.")


def summarize_run(root):
    root = Path(root).resolve()
    protocol, frozen = read(root / "PROTOCOL.json"), read(root / "SOURCE_FREEZE.json")
    if sha(root / "PROTOCOL.json") != frozen["protocol_sha256"]:
        raise ValueError("Analysis protocol changed after freeze")
    source = Path(__file__).resolve()
    relative = str(source.relative_to(source.parent.parents[1]))
    if relative not in frozen["files"] or sha(source) != frozen["files"][relative]:
        raise ValueError("Summarizer was not frozen before confirmation")
    groups = read(root / "TRAINING_INDEX.json")["groups"]
    training, resources = training_and_resources(root, protocol, groups)
    analysis = Analysis(protocol["seeds"])
    results, anchors = main_effects(root, protocol, training, analysis)
    results.update(cpu_comparisons=cpu_comparisons(root, protocol, training), resources=resources,
                   inference=dict(fit_unit="paired independent optimization seed; eight fits, df=7", 
                       object_unit="partition_ids, not row or four-combination group; fixed fits averaged before resampling",
                       bootstrap_replicates=BOOTSTRAPS, bootstrap_seed=BOOTSTRAP_SEED,
                       multiplicity="All intervals are nominal; no simultaneous or multiplicity-adjusted significance claim",
                       domains="Each task/domain separately; missing modalities are negative controls and never pooled with primary domains"),
                   recovery=recovery_effects(root, protocol, analysis, anchors),
                   posterior_qualification=posterior_qualification(root, protocol, groups))
    results["acceptance"] = acceptance(protocol, results, resources)
    results["acceptance"]["actual_posterior_continuous_tail_gate_pass"] = results["posterior_qualification"]["registered_continuous_tail_qualification_pass"]
    results["source_protocol_sha256"] = sha(root / "PROTOCOL.json")
    write(root / "SUMMARY.json", results)
    with (root / "EFFECTS.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(analysis.csv_rows[0]))
        writer.writeheader(); writer.writerows(analysis.csv_rows)
    return dict(effects=len(analysis.csv_rows), outcomes=len(results["outcomes"]),
                foundation_core_acceptance=False, all_user_requirements_closed=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(summarize_run(args.output), sort_keys=True))
