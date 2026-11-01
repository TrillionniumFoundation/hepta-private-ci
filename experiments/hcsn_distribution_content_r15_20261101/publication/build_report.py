#!/usr/bin/env python3
"""Publish already computed R15 evidence without fitting or opening raw test data.

``build`` consumes completed JSON summaries, the independent audit and the
nonadditive runtime ledger. ``selfcheck`` creates artificial JSON inputs only.
This publication helper is separate from the scientific source freeze. It does
not import the experiment, load checkpoints/NPZs, compute a new interval, select
a model, or choose a favorable domain. Missing required evidence is an error;
optional evidence is explicitly unavailable, never replaced by a numeric zero.
"""

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import tempfile


SOURCE = Path(__file__).resolve()
ORDINARY, ANALYTIC = "ordinary_distribution", "analytic_distribution"
CONTRASTS = ("B-A", "D-C", "C-A", "D-B", "interaction")
ARMS = {"A": (ORDINARY, "light", "light"), "B": (ORDINARY, "value", "value"),
        "C": (ANALYTIC, "light", "light"), "D": (ANALYTIC, "value", "value")}
ACTIONS = ("none", "reset_only", "replay_only", "reset_replay")
METRICS = ("utility", "accuracy", "read_count", "fee", "initial_stop")
STAGES = ("train", "evaluate", "recovery_fit", "recovery_confirm", "full_online_confirmation", "train_execution_cross")
RECOVERY_EFFECTS = ("selected_minus_protected_none", "selected_minus_unprotected_none",
                    "reset_replay_minus_none", "reset_replay_interaction")
CROSS_CELLS = ("LL", "LV", "VL", "VV")
CROSS_EFFECTS = ("training_given_light", "training_given_value", "execution_given_light",
                 "execution_given_value", "interaction")
CROSS_LABELS = {"training_given_light": "VL−LL（固定 light 执行）",
                "training_given_value": "VV−LV（固定 value 执行）",
                "execution_given_light": "LV−LL（固定 light 训练）",
                "execution_given_value": "VV−VL（固定 value 训练）",
                "interaction": "VV−VL−LV+LL"}
NUMERICAL_LIMITS = {"first_hit": .0005, "expected_count": .002,
                    "count_pmf_l1": .002, "active_bins_l1": .003}
PHYSICAL_INITIAL = {"x": 1., "reset": .8, "mu": -.25, "sigma": 1., "tail_upper": 60.}
UNAVAILABLE = "not_available"


class ReportError(ValueError):
    """Recorded input cannot support the requested report."""


def require(condition, message):
    if not condition:
        raise ReportError(message)


def numeric(value, label, minimum=None):
    require(type(value) in (int, float) and math.isfinite(value), "Missing/nonfinite number: " + label)
    require(minimum is None or value >= minimum, "Out-of-range number: " + label)
    return value


def integer(value, label, minimum=0):
    require(type(value) is int and value >= minimum, "Missing/invalid integer: " + label)
    return value


def boolean(value, label):
    require(type(value) is bool, "Missing/invalid boolean: " + label)
    return value


def close(a, b):
    return math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10)


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key: " + key)
        result[key] = value
    return result


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


class Inputs:
    def __init__(self):
        self.records = []

    def read(self, path, required=True):
        path = Path(path).resolve()
        if not path.is_file():
            require(not required, "Missing completed input: " + str(path))
            return None
        raw = path.read_bytes()
        try:
            value = json.loads(raw, object_pairs_hook=unique_pairs,
                               parse_constant=lambda x: (_ for _ in ()).throw(ReportError("Nonfinite JSON: " + x)))
        except (json.JSONDecodeError, UnicodeError) as error:
            raise ReportError("Invalid JSON: " + str(path)) from error
        require(isinstance(value, dict), "Expected JSON object: " + str(path))
        self.records.append(dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
        return value


def keyed(rows, fields, label):
    require(isinstance(rows, list), "Missing list: " + label)
    table = {}
    for row in rows:
        require(isinstance(row, dict) and all(field in row for field in fields), "Missing identity: " + label)
        key = tuple(row[field] for field in fields)
        require(key not in table, "Duplicate " + label + ": " + str(key))
        table[key] = row
    return table


def statistic(item, seeds, label, cluster=False):
    """Check, then retain the existing estimator; never calculate a new CI."""
    require(isinstance(item, dict), "Missing statistic: " + label)
    require(item.get("fit_count") == len(seeds) and item.get("fit_df") == len(seeds)-1,
            "Fit count/df differs from registration: " + label)
    values = item.get("fit_values")
    require(isinstance(values, list) and len(values) == len(seeds), "Missing paired fit values: " + label)
    for value in values:
        numeric(value, label + ".fit_values")
    mean = numeric(item.get("mean"), label + ".mean")
    require(close(mean, math.fsum(values)/len(values)), "Stored mean disagrees with fit values: " + label)
    bounds = item.get("fit_t95")
    require(isinstance(bounds, list) and len(bounds) == 2, "Missing t95: " + label)
    lo, hi = (numeric(x, label + ".fit_t95") for x in bounds)
    require(lo <= mean+1e-10 and mean <= hi+1e-10, "Invalid t95 bounds: " + label)
    count = sum(x > 0 for x in values)
    require(item.get("positive_fit_count") == count and close(numeric(item.get("positive_fit_fraction"), label + ".positive_fit_fraction"), count/len(values)),
            "Stored positive-fit count differs: " + label)
    if "fit_seeds" in item:
        require(item["fit_seeds"] == seeds, "Paired seed order differs: " + label)
    if cluster:
        interval = item.get("fixed_fit_object_cluster95")
        require(isinstance(interval, list) and len(interval) == 2, "Missing replay cluster interval: " + label)
        low, high = (numeric(x, label + ".cluster95") for x in interval)
        require(low <= high, "Reversed cluster interval: " + label)
        integer(item.get("partition_cluster_count"), label + ".partition_cluster_count", 2)
    return item


def same_metric(first, second, label, atol=None):
    require(all(close(a, b) if atol is None else abs(a-b) <= atol
                for a, b in zip(first["fit_values"], second["fit_values"])),
            "Inconsistent duplicated metric: " + label)


def protocol_check(protocol):
    tasks, seeds = protocol.get("tasks"), protocol.get("seeds")
    require(isinstance(tasks, list) and tasks == ["recall", "binding"], "Unexpected registered task order")
    require(isinstance(seeds, list) and len(seeds) == 8 and len(set(seeds)) == 8
            and all(type(seed) is int for seed in seeds), "This report requires eight registered fit seeds")
    require(protocol.get("modes") == ["light", "value"], "Unknown training cells")
    families = protocol.get("families")
    require(isinstance(families, list) and len(set(families)) == len(families)
            and all(f in families for f in (ORDINARY, ANALYTIC)), "Invalid model inventory")
    domains = protocol.get("domains")
    require(isinstance(domains, dict) and set(domains) == set(tasks), "Missing domain registration")
    for task in tasks:
        require(isinstance(domains[task], list) and len(set(domains[task])) == len(domains[task])
                and "iid" in domains[task], "Invalid domain list: " + task)
    rules = protocol.get("acceptance")
    require(isinstance(rules, dict), "Missing original acceptance rules")
    expected = dict(minimum_iid_accuracy=.7, primary_lower95=0., minimum_positive_seed_fraction=.75,
                    pressure_tolerance=-.02, pressure_domains=["long_distractors", "blank_retention", "irregular_dt", "clock4x", "query_swap"],
                    required_tasks=tasks, full_cost_advantage_required=True)
    require(rules == expected, "Acceptance rules differ from the registered R15 contract; do not silently replace them")
    for task in tasks:
        require(set(rules["pressure_domains"]).issubset(domains[task]), "Missing registered pressure domain")
    require(isinstance(protocol.get("splits"), dict) and isinstance(protocol["splits"].get("test"), list), "Missing registered cohort size")
    integer(protocol["splits"]["test"][0], "test objects", 1)
    return tasks, seeds, families, domains


def actual_analysis(protocol, online):
    tasks, seeds, families, domains = protocol_check(protocol)
    require(online.get("schema") == "hcsn.r15.full-online-supplement.summary.v1", "Unknown full-online summary schema")
    expected = sum(len(domains[task]) for task in tasks)*len(seeds)*len(families)*3
    objects = expected*protocol["splits"]["test"][0]
    require(online.get("conditions") == online.get("expected_conditions") == expected,
            "Full-online condition matrix is not complete")
    require(online.get("object_executions") == online.get("expected_object_executions") == objects,
            "Full-online object matrix is not complete")
    analysis = online.get("actual_outcome_analysis")
    require(isinstance(analysis, dict), "Missing actual outcome analysis")
    domain_keys = set((task, domain) for task in tasks for domain in domains[task])
    cells = keyed(analysis.get("primary_four_cells"), ("task", "domain"), "actual four cells")
    effects = keyed(analysis.get("total_effects"), ("task", "domain", "contrast"), "actual effects")
    conditional = keyed(analysis.get("conditional_execution_effects"), ("task", "domain", "contrast"), "actual conditional effects")
    selected = keyed(analysis.get("validation_selected_comparator"), ("task", "domain"), "actual selected comparator")
    outcomes = keyed(analysis.get("outcomes"), ("task", "domain", "family", "train_mode", "exec_mode"), "actual outcomes")
    require(set(cells) == set(selected) == domain_keys, "Incomplete actual task/domain cells")
    effect_keys = {(task, domain, contrast) for task, domain in domain_keys for contrast in CONTRASTS}
    require(set(effects) == set(conditional) == effect_keys, "Incomplete actual five-contrast matrix")
    expected_outcomes = {(task, domain, family, mode, execution) for task, domain in domain_keys
                         for family in families for mode, execution in (("light", "light"), ("value", "light"), ("value", "value"))}
    require(set(outcomes) == expected_outcomes, "Incomplete full-family actual outcomes")
    for table in (cells, effects, conditional, selected, outcomes):
        for key, row in table.items():
            require(row.get("fit_seeds") == seeds, "Actual row seed order mismatch: " + str(key))
            require(row.get("object_count") == protocol["splits"]["test"][0], "Actual object count mismatch: " + str(key))
            if table is not outcomes:
                integer(row.get("partition_cluster_count"), "actual partition clusters", 2)
    for key, row in cells.items():
        require(set(row.get("cells", {})) == set(ARMS), "Missing A/B/C/D")
        for letter, identity in ARMS.items():
            arm = row["cells"][letter]
            require(tuple(arm.get(field) for field in ("family", "train_mode", "exec_mode")) == identity,
                    "Mislabeled independent-training arm: " + letter)
            for metric in METRICS:
                statistic(arm.get("metrics", {}).get(metric), seeds, str(key) + letter + metric)
                stat = statistic(outcomes[(*key, *identity)].get("metrics", {}).get(metric), seeds, "actual outcome " + metric)
                same_metric(arm["metrics"][metric], stat, str(key) + letter + metric)
    for table in (effects, conditional, selected, outcomes):
        for key, row in table.items():
            for metric in METRICS:
                statistic(row.get("metrics", {}).get(metric), seeds, str(key) + metric)
    # B and D are the identical value-trained/value-executed observations in
    # both estimands. Other contrasts may differ when the A/C weights change.
    for task,domain in domain_keys:
        for metric in METRICS:
            same_metric(effects[(task,domain,"D-B")]["metrics"][metric],
                        conditional[(task,domain,"D-B")]["metrics"][metric],
                        "actual total vs same-value-weights D-B " + str((task,domain,metric)),atol=1e-12)
    for task in tasks:
        chosen = None
        for domain in domains[task]:
            row = selected[(task, domain)]
            values = row.get("selected_families")
            require(isinstance(values, dict) and set(values) == {str(seed) for seed in seeds}, "Missing validation-selected families")
            require(all(f in families and not f.startswith("analytic") for f in values.values()), "Invalid ordinary comparator")
            require(chosen is None or chosen == values, "Comparator changed across confirmation domains")
            chosen = values
    return dict(cells=cells, effects=effects, conditional=conditional, selected=selected, outcomes=outcomes)


def gates(protocol, tables):
    rules = protocol["acceptance"]
    per_task = {}
    for task in rules["required_tasks"]:
        accuracy = {letter: tables["cells"][(task, "iid")]["cells"][letter]["metrics"]["accuracy"]["mean"] for letter in ARMS}
        effect = tables["effects"][(task, "iid", "D-B")]["metrics"]["utility"]
        pressure = {domain: tables["effects"][(task, domain, "D-B")]["metrics"]["utility"]["mean"] for domain in rules["pressure_domains"]}
        checks = dict(all_four_iid_quality_pass=all(x >= rules["minimum_iid_accuracy"] for x in accuracy.values()),
                      iid_D_minus_B_fit_lower95_pass=effect["fit_t95"][0] > rules["primary_lower95"],
                      iid_D_minus_B_positive_seed_fraction_pass=effect["positive_fit_fraction"] >= rules["minimum_positive_seed_fraction"],
                      pressure_pass=all(x >= rules["pressure_tolerance"] for x in pressure.values()))
        per_task[task] = dict(iid_accuracies=accuracy, iid_D_minus_B=effect, pressure_D_minus_B_means=pressure,
                              **checks, registered_quality_effect_pressure_gate_pass=all(checks.values()))
    return dict(protocol_rules=rules, estimate_source="FULL_ONLINE_CONFIRMATION_SUMMARY.actual_outcome_analysis",
                per_task=per_task, registered_quality_effect_pressure_gate_pass=all(row["registered_quality_effect_pressure_gate_pass"] for row in per_task.values()),
                strong_ordinary_and_posterior_are_separate_evidence_not_new_primary_gate=True,
                full_cost_advantage_established=False, foundation_core_acceptance=False, all_user_requirements_closed=False,
                original_full_successor_requirement_closed=False,
                reason="Finite registered quality/effect/pressure tests do not close full cost, general law, media or scale requirements.")


def cross_tables(protocol, actual, cross):
    """Validate the separately registered LL/LV/VL/VV evidence, without a new gate."""
    coverage = cross.get("coverage")
    require(isinstance(coverage, dict), "Missing train/execution cross coverage")
    conditions = 2*len(protocol["seeds"])*sum(len(protocol["domains"][task]) for task in protocol["tasks"])
    objects = conditions*protocol["splits"]["test"][0]
    require(coverage.get("all_conditions_present") is True
            and coverage.get("expected_conditions") == coverage.get("conditions") == conditions,
            "Incomplete added LV condition matrix")
    require(coverage.get("expected_object_executions") == coverage.get("object_executions") == objects,
            "Incomplete added LV object execution")
    families = keyed(cross.get("families"), ("task", "domain", "family"), "train/execution cross families")
    cores = keyed(cross.get("core_differences"), ("task", "domain", "cell"), "train/execution cross core differences")
    expected = {(task, domain, family) for task in protocol["tasks"] for domain in protocol["domains"][task]
                for family in (ORDINARY, ANALYTIC)}
    expected_cores = {(task, domain, cell) for task in protocol["tasks"] for domain in protocol["domains"][task] for cell in CROSS_CELLS}
    require(set(families) == expected and set(cores) == expected_cores, "Incomplete true train/execution two-by-two matrix")
    seeds = protocol["seeds"]
    for key, row in families.items():
        require(row.get("fit_seeds") == seeds and row.get("object_count") == protocol["splits"]["test"][0],
                "Cross fit seed/object identity mismatch")
        require(set(row.get("cells", {})) == set(CROSS_CELLS), "Missing LL/LV/VL/VV cell")
        require(set(row.get("effects", {})) == set(CROSS_EFFECTS), "Missing train/execution effect")
        for cell, item in row["cells"].items():
            expected_mode = "light" if cell[0] == "L" else "value"
            expected_execution = "light" if cell[1] == "L" else "value"
            require((item.get("train_mode"), item.get("exec_mode")) == (expected_mode, expected_execution),
                    "Cross cell label disagrees with training/execution identity")
            for metric in METRICS:
                value = statistic(item.get("metrics", {}).get(metric), seeds, "cross " + str(key) + cell + metric)
                if cell != "LV":
                    mode, execution = {"LL": ("light", "light"), "VL": ("value", "light"), "VV": ("value", "value")}[cell]
                    reused = actual["outcomes"][(*key, mode, execution)]["metrics"][metric]
                    same_metric(value, reused, "cross reuses original actual " + str(key) + cell + metric)
        for contrast, item in row["effects"].items():
            for metric in METRICS:
                statistic(item.get("metrics", {}).get(metric), seeds, "cross " + str(key) + contrast + metric)
    for key, row in cores.items():
        require(row.get("fit_seeds") == seeds and row.get("contrast") == "analytic_distribution-ordinary_distribution",
                "Cross core difference has the wrong seed order or direction")
        for metric in METRICS:
            value = statistic(row.get("metrics", {}).get(metric), seeds, "cross core " + str(key) + metric)
            task, domain, cell = key
            if cell in ("LL", "VV"):
                contrast = "C-A" if cell == "LL" else "D-B"
                reused = actual["effects"][(task, domain, contrast)]["metrics"][metric]
                same_metric(value, reused, "cross core reuses original actual " + str(key) + metric)
    return dict(families=families, core_differences=cores)


def replay_analysis(protocol, summary):
    seeds = protocol["seeds"]
    expected = {(task, domain, contrast) for task in protocol["tasks"] for domain in protocol["domains"][task] for contrast in CONTRASTS}
    tables = {}
    for field in ("total_effects", "conditional_execution_effects"):
        table = keyed(summary.get(field), ("task", "domain", "contrast"), "replay " + field)
        require(set(table) == expected, "Incomplete replay contrast matrix: " + field)
        for key, row in table.items():
            statistic(row, seeds, "replay " + str(key), cluster=True)
        tables[field] = table
    selected = keyed(summary.get("validation_selected_comparator"), ("task", "domain"), "replay selected")
    require(set(selected) == {(task, domain) for task in protocol["tasks"] for domain in protocol["domains"][task]}, "Incomplete replay comparator")
    for key, row in selected.items():
        statistic(row, seeds, "replay selected " + str(key), cluster=True)
    tables["selected"] = selected
    ablations = keyed(summary.get("distribution_ablations"), ("task", "domain", "contrast"), "distribution ablations")
    expected_ablations = {(task, domain, "full_minus_" + action) for task in protocol["tasks"] for domain in protocol["domains"][task]
                         for action in ("content_independence", "mean_position", "readout_independence")}
    require(set(ablations) == expected_ablations, "Incomplete registered three-ablation matrix")
    for key, row in ablations.items():
        statistic(row, seeds, "ablation " + str(key), cluster=True)
    tables["ablations"] = ablations
    return tables


def alignment_summary(online):
    aligned = boolean(online.get("all_conditions_aligned"), "all_conditions_aligned")
    rows = online.get("mismatch_conditions")
    require(isinstance(rows, list) and aligned == (len(rows) == 0), "Contradictory online/replay alignment")
    names = ("prediction", "read_count", "fee", "utility", "elapsed")
    totals = {name: dict(mismatches=0, maximum_absolute_difference=0.) for name in names}
    identities = set()
    for row in rows:
        key = tuple(row[name] for name in ("task", "seed", "family", "train_mode", "exec_mode", "domain"))
        require(key not in identities, "Duplicate mismatch condition")
        identities.add(key)
        require(row.get("alignment", {}).get("aligned") is False, "Mismatch row declares alignment")
        observed_mismatch = False
        for name in names:
            item = row["alignment"].get(name)
            require(isinstance(item, dict), "Missing mismatch field: " + name)
            count = integer(item.get("mismatches"), name + " mismatches")
            error = numeric(item.get("maximum_absolute_difference"), name + " difference", 0)
            numeric(item.get("tolerance"), name + " tolerance", 0)
            totals[name]["mismatches"] += count
            totals[name]["maximum_absolute_difference"] = max(totals[name]["maximum_absolute_difference"], error)
            observed_mismatch |= count > 0
        require(observed_mismatch, "Mismatch condition has no mismatching outcome")
    return dict(all_conditions_aligned=aligned, mismatch_condition_count=len(rows), totals=totals,
                mismatch_conditions=rows,
                zero_count_scope="Counts sum the explicitly retained nonaligned conditions. Aligned conditions declare no tolerance-exceeding differences.",
                maximum_difference_scope="Maximum among retained nonaligned conditions; if none, tolerance-exceeding difference is zero, not a claim of bitwise float equality.",
                raw_masks="FULL_ONLINE_CONFIRMATION_INDEX.json paths retain mismatch_prediction/read_count/fee/utility/elapsed arrays")


def runtime_check(ledger, online, cross, run):
    require(ledger.get("schema") == "hcsn.r15.publication.runtime-ledger.v3", "Require runtime-ledger.v3, including the six stages and preserved ENOSPC attempts")
    require(ledger.get("formal_run") == run.name and Path(ledger.get("result_root", "")).resolve()/run.name == run,
            "Runtime ledger identifies another run")
    complete = boolean(ledger.get("formal_stage_receipts_complete"), "ledger stage coverage")
    require(complete, "Publication requires the completed six-stage runtime ledger")
    stages = keyed(ledger.get("formal_03_stages"), ("stage",), "runtime stages")
    require(set(stages) == {(stage,) for stage in STAGES}, "Missing runtime stage")
    observed, successful, failed = [], [], []
    for (name,), stage in stages.items():
        require(stage.get("coverage") == "complete", "Incomplete runtime stage: " + name)
        count = integer(stage.get("recorded_jobs"), name + " jobs", 1)
        require(count == stage.get("expected_jobs"), "Incomplete runtime job matrix: " + name)
        integer(stage.get("failed_jobs"), name + " failed jobs")
        measured = numeric(stage.get("observed_worker_cpu_seconds"), name + " CPU", 0)
        ok = numeric(stage.get("successful_completed_worker_cpu_seconds"), name + " successful CPU", 0)
        bad = numeric(stage.get("failed_completed_worker_cpu_seconds"), name + " failed CPU", 0)
        require(close(measured, ok+bad), "Runtime success/failure CPU arithmetic mismatch")
        numeric(stage.get("elapsed_wall_seconds"), name + " stage wall", 0)
        numeric(stage.get("maximum_individual_worker_rss_kib"), name + " RSS", 0)
        observed.append(measured); successful.append(ok); failed.append(bad)
    totals = ledger.get("totals")
    require(isinstance(totals, dict) and totals.get("status") == "lower_bound", "Runtime total must retain lower-bound status")
    for name, value in (("formal_03_observed_completed_process_cpu_seconds", math.fsum(observed)),
                        ("formal_03_successful_completed_process_cpu_seconds", math.fsum(successful)),
                        ("formal_03_failed_completed_process_cpu_seconds", math.fsum(failed))):
        require(close(numeric(totals.get(name), name, 0), value), "Runtime ledger total mismatch: " + name)
    complete_waste = numeric(totals.get("abandoned_attempt_complete_wait4_cpu_seconds"), "abandoned complete CPU", 0)
    partial_waste = numeric(totals.get("abandoned_attempt_interrupted_process_cpu_lower_bound_seconds"), "abandoned snapshot CPU", 0)
    waste = numeric(totals.get("abandoned_attempt_cpu_lower_bound_seconds"), "abandoned CPU lower bound", 0)
    total = numeric(totals.get("successful_failed_and_abandoned_cpu_lower_bound_seconds"), "all-attempt CPU lower bound", 0)
    recovery = ledger.get("enospc_training_recovery")
    require(isinstance(recovery,dict) and recovery.get("original_launcher_completed") is False
            and recovery.get("same_scientific_freeze_and_contexts") is True, "Missing disclosed same-freeze ENOSPC recovery")
    retained = integer(recovery.get("retained_original_success_count"),"retained original successful groups")
    resumed = integer(recovery.get("resumed_success_count"),"resumed successful groups")
    require(retained+resumed == recovery.get("canonical_success_count") == stages[("train",)]["recorded_jobs"],
            "Retained plus resumed groups do not cover canonical training")
    unknown = recovery.get("unknown_process_attempts")
    require(isinstance(unknown,list) and recovery.get("unknown_process_attempt_count")==len(unknown),"Missing ENOSPC unknown-attempt inventory")
    require(all(row.get("cpu_seconds") is None and row.get("measurement_status")=="not_measured" for row in unknown)
            and recovery.get("missing_process_cpu_seconds") is None and totals.get("enospc_unknown_process_cpu_seconds") is None,
            "Missing process CPU was incorrectly replaced by a number")
    require(totals.get("enospc_unknown_process_attempt_count")==len(unknown),"Unknown-attempt totals disagree")
    charges = recovery.get("additional_measured_processes")
    addends = recovery.get("additional_observed_cpu_addends")
    require(isinstance(charges,list) and isinstance(addends,list) and len(charges)==len(addends),"Missing distinct additional attempt accounting")
    for charge,value in zip(charges,addends):
        require(close(numeric(charge.get("cpu_seconds"),"additional attempt CPU",0),numeric(value,"additional CPU addend",0)),
                "Additional attempt CPU differs from its additive ledger")
    measured = math.fsum(addends) if addends else None
    for field,actual in (("additional_observed_cpu_lower_bound_seconds",measured),):
        require(field in recovery and ((recovery[field] is None) if actual is None else close(numeric(recovery[field],field,0),actual)),
                "Missing/incorrect additional observed CPU subtotal")
    require("enospc_additional_observed_cpu_lower_bound_seconds" in totals
            and ((totals["enospc_additional_observed_cpu_lower_bound_seconds"] is None) if measured is None else
                 close(numeric(totals["enospc_additional_observed_cpu_lower_bound_seconds"],"ENOSPC additional total",0),measured)),
            "ENOSPC additional total disagrees")
    for field in ("additional_complete_wait4_cpu_seconds","additional_partial_cpu_lower_bound_seconds"):
        require(field in recovery and "enospc_"+field in totals,"Missing additional complete/partial CPU status")
        first,second=recovery[field],totals["enospc_"+field]
        require((first is None and second is None) or (first is not None and second is not None and close(numeric(first,field,0),numeric(second,"enospc_"+field,0))),
                "Additional complete/partial CPU subtotal differs")
    require(close(waste, complete_waste+partial_waste) and close(total, math.fsum([*observed,waste,*addends])), "All-attempt accounting is not disjoint")
    training=stages[("train",)]
    require(training.get("original_launcher_completed") is False and training.get("accounting_kind")=="resumed_consolidated"
            and training.get("wall_scope")=="elapsed_since_original_restart_including_interruption_and_resume",
            "Resumed training must label its consolidated receipts and interrupted wall span")
    require(close(numeric(totals.get("hours_lower_bound"), "CPU hours lower bound", 0), total/3600), "CPU hours disagree")
    for key in ("group_cpu_seconds", "nested_actor_cpu_seconds"):
        numeric(online.get(key), "full online " + key, 0)
    for key in ("actual_reads", "processed_prefix_tokens", "model_calls", "controller_batch_calls"):
        integer(online.get(key), "full online " + key)
    receipt = online.get("process_receipt")
    require(isinstance(receipt, dict), "Missing full-online wait4 aggregate")
    require(close(numeric(receipt.get("process_cpu_seconds"), "full online worker CPU", 0), stages[("full_online_confirmation",)]["observed_worker_cpu_seconds"]),
            "Full-online summary differs from runtime worker ledger")
    resources = cross.get("resources")
    require(isinstance(resources, dict), "Missing additional LV resources")
    for key in ("group_cpu_seconds", "nested_actor_cpu_seconds"):
        numeric(resources.get(key), "added LV " + key, 0)
    for key in ("actual_reads", "processed_prefix_tokens", "model_calls", "controller_batch_calls"):
        integer(resources.get(key), "added LV " + key)
    receipt = resources.get("process_receipt")
    require(isinstance(receipt, dict) and receipt.get("stage") == "train_execution_cross", "Missing added LV wait4 receipt")
    require(close(numeric(receipt.get("process_cpu_seconds"), "added LV worker CPU", 0), stages[("train_execution_cross",)]["observed_worker_cpu_seconds"]),
            "Additional LV summary differs from runtime worker ledger")
    return dict(stages=stages,every_canonical_formal_worker_successful=all(row["failed_jobs"]==0 for row in stages.values()),
                original_training_launcher_completed=False,all_process_attempts_successful=False,
                enospc_unknown_process_attempts=len(unknown))


def recovery_evidence(inputs, run, protocol, summary):
    recovery = summary.get("recovery")
    require(isinstance(recovery, dict) and type(recovery.get("available")) is bool, "Missing recovery availability status")
    if not recovery["available"]:
        return dict(available=False, status=UNAVAILABLE, reason="Frozen summary explicitly has no recovery confirmation evidence")
    seeds = protocol["seeds"]
    expected = set(itertools.product(protocol["tasks"], ("iid", "long_distractors"), ("none", "sign", "zero"), (ORDINARY, ANALYTIC)))
    fields = ("task", "domain", "cohort", "family")
    outcomes = keyed(recovery.get("outcomes"), fields, "recovery outcomes")
    effects = keyed(recovery.get("effects"), (*fields, "contrast"), "recovery effects")
    sensitivities = keyed(recovery.get("sensitivities"), fields, "recovery sensitivity")
    require(set(outcomes) == set(sensitivities) == expected, "Incomplete recovery domain/cohort matrix")
    require(set(effects) == {(*key, contrast) for key in expected for contrast in RECOVERY_EFFECTS}, "Incomplete recovery contrasts")
    for key, row in outcomes.items():
        for field in ("selected_utility", "selected_accuracy", "selected_fee", "clean_accuracy"):
            statistic(row.get(field), seeds, "recovery " + str(key) + field)
        fraction = numeric(row.get("alarm_fraction"), "alarm fraction", 0)
        require(fraction <= 1 and (key[2] != "none" or fraction == 0), "Invalid fault cohort alarm fraction")
        counts = row.get("action_counts_by_fit")
        require(isinstance(counts, dict) and set(counts) == {str(seed) for seed in seeds}, "Missing recovery action counts")
        for seed in seeds:
            values = counts[str(seed)]
            require(isinstance(values, list) and len(values) == 4, "Missing four-action counts")
            for value in values: integer(value, "selected action count")
            require(sum(values) == protocol["splits"]["test"][0], "Recovery action counts do not cover the cohort")
    for key, row in effects.items(): statistic(row, seeds, "recovery effect " + str(key), cluster=True)
    for key, row in sensitivities.items():
        require(row.get("fixed_policy") is True, "Recovery sensitivity reselects the policy")
        require([r.get("incremental_price_multiplier") for r in row.get("values", [])] == [0., .5, 1., 2., 4.], "Missing registered recovery price sensitivity")
        for item in row["values"]: statistic(item.get("gain_vs_unprotected_none"), seeds, "recovery price " + str(key))
    actual = recovery.get("actual_execution_records")
    receipts = keyed(actual, ("task", "domain", "cohort", "family", "seed"), "recovery actual execution")
    require(set(receipts) == {(*key, seed) for key in expected for seed in seeds}, "Incomplete selected-action actual execution")
    mismatch = 0
    for row in actual:
        numeric(row.get("cpu_seconds"), "selected recovery actor CPU", 0)
        numeric(row.get("wall_seconds"), "selected recovery actor wall", 0)
        require(row.get("episodes") == protocol["splits"]["test"][0], "Incomplete recovery actor cohort")
        for key in ("prediction_mismatches", "action_mismatches"):
            mismatch += integer(row.get(key), key)
    require(recovery.get("actual_execution_mismatches") == mismatch, "Recovery actual mismatch count disagrees")
    index = inputs.read(run / "recovery/CONFIRMATION_INDEX.json", required=False)
    arms = dict(available=False, status=UNAVAILABLE, reason="No existing recovery CONFIRMATION_INDEX with four-arm summaries supplied")
    if index is not None:
        records = keyed(index.get("records"), (*fields, "seed"), "recovery four-arm summaries")
        require(set(records) == set(receipts), "Four-arm summary identities differ from selected actor receipts")
        rows = []
        for key, row in records.items():
            value = row.get("summary")
            require(isinstance(value, dict) and value.get("episodes") == protocol["splits"]["test"][0], "Missing existing arm summary")
            require(set(value.get("arms", {})) == set(ACTIONS), "Missing a recovery arm")
            for action in ACTIONS:
                for metric in ("accuracy", "fee", "utility"):
                    numeric(value["arms"][action].get(metric), "recovery arm " + metric)
            rows.append({**{field: row[field] for field in (*fields, "seed")}, "summary": value})
        arms = dict(available=True, rows=rows, estimator="Existing per-fit four-arm means only; no new averaging or intervals")
    return dict(available=True, frozen_summary=recovery, four_arms=arms,
                selected_actual_prediction_action_mismatches=mismatch,
                selected_actor_cpu_seconds_sum=math.fsum(row["cpu_seconds"] for row in actual),
                selected_actor_cpu_is_nested_not_added=True,
                scientific_general_recovery_benefit_established=False)


def numerical_evidence(inputs, study):
    """Summarize retained fixed-initial-atom checks, never rerun a solver."""
    numerical = inputs.read(study / "tail_numerics_03.json", required=False)
    law = inputs.read(study / "law_tail_final_checks_01.json", required=False)
    independent = inputs.read(study / "tail_independent_review_qualified.json", required=False)
    result = dict(formal_profile="tail_half_upper60", expected_horizons=[.25,1.,1.75,4.],
        physical_initial=PHYSICAL_INITIAL,
        original_full_successor_requirement_closed=False,
        uniform_learned_posterior_continuum_certificate=False,
        scope="Existing fixed initial atom x=1, reset=.8, mu=-.25, sigma=1 at four registered horizons only. No new numerical run or posterior-wide certificate.")
    if numerical is None:
        result["continuous_reference"] = dict(available=False,status=UNAVAILABLE)
    else:
        rows = numerical.get("rows")
        require(isinstance(rows,list) and len(rows)==12, "Expected the retained 4-horizon by 3-profile numerical record")
        selected = [row for row in rows if row.get("profile")==result["formal_profile"]]
        require(len(selected)==4 and sorted(row.get("horizon") for row in selected)==result["expected_horizons"],
                "Missing a fixed formal upper60 initial-atom horizon")
        maxima = {}
        for row in selected:
            require(isinstance(row.get("config"),dict) and all(row["config"].get(k)==v for k,v in PHYSICAL_INITIAL.items()),
                    "Numerical reference is not the formal60 fixed initial state")
            boolean(row.get("passed"), "numerical row passed")
            for metric,limit in NUMERICAL_LIMITS.items():
                require(row.get("limits",{}).get(metric)==limit, "Numerical threshold changed: "+metric)
                error = numeric(row.get("errors",{}).get(metric),"numerical error "+metric,0)
                maxima[metric] = max(maxima.get(metric,error),error)
        metrics = {name:dict(maximum_error=maxima[name],registered_limit=limit,passed=maxima[name]<=limit)
                   for name,limit in NUMERICAL_LIMITS.items()}
        result["continuous_reference"] = dict(available=True,retained_profile_rows=len(rows),selected_profile_rows=len(selected),
            numerical_file_passed=boolean(numerical.get("passed"),"numerical file passed"),
            selected_profile_rows_passed=all(row["passed"] for row in selected),
            all_four_registered_errors_pass=all(item["passed"] for item in metrics.values()),
            horizons=result["expected_horizons"],metrics=metrics,selected_rows=selected,
            other_retained_profiles=sorted({row.get("profile") for row in rows if row.get("profile")!=result["formal_profile"]}),
            serialization_history=numerical.get("serialization",{"status":UNAVAILABLE}))
    if law is None:
        result["finite_law_checks"] = dict(available=False,status=UNAVAILABLE)
    else:
        require(law.get("schema")=="hcsn-r15.finite-law-checks.v1", "Unknown retained finite-law check schema")
        require(isinstance(law.get("config"),dict) and all(law["config"].get(k)==v for k,v in PHYSICAL_INITIAL.items()),
                "Final finite-law check record does not use formal60 configuration")
        count = integer(law.get("count"),"law check count",1)
        require(isinstance(law.get("checks"),list) and len(law["checks"])==count and isinstance(law.get("failed"),list),
                "Finite-law check count/failure inventory is inconsistent")
        passed = boolean(law.get("passed"),"law check passed")
        require(passed==(not law["failed"]),"Law check status contradicts recorded failures")
        result["finite_law_checks"] = dict(available=True,count=count,passed=passed,failed=law["failed"],config=law["config"],
            continuous_model_acceptance=law.get("continuous_model_acceptance",UNAVAILABLE),
            source_scope=law.get("scope",UNAVAILABLE))
    if independent is None:
        result["independent_structural_review"] = dict(available=False,status=UNAVAILABLE)
    else:
        require(independent.get("schema")=="hcsn.r15.independent-tail-review.v1", "Unknown independent tail review schema")
        require(isinstance(independent.get("checks"),list), "Missing independent structural checks")
        upper = numeric(independent.get("upper"),"independent review upper",0)
        positions = integer(independent.get("positions"),"independent review positions",1)
        result["independent_structural_review"] = dict(available=True,passed=boolean(independent.get("passed"),"independent structural passed"),
            check_count=len(independent["checks"]),upper=upper,positions=positions,
            confirmation_data_accessed=boolean(independent.get("confirmation_data_accessed"),"structural review test access"),
            formal_upper_matches=upper==PHYSICAL_INITIAL["tail_upper"],
            formal60_independent_numerical_certificate=False,
            source_scope=independent.get("scope",UNAVAILABLE),
            warning=f"This is the retained upper{upper:g}/{positions}-position structural review, not an independent numerical certificate for formal upper60.")
    return result


def assemble(run, ledger_path, source_commit=None, study=None):
    """Read only completed JSON evidence; return review plus rendering context."""
    run = Path(run).resolve()
    study = Path(study).resolve() if study is not None else run.parent.parent
    if source_commit is not None:
        require(re.fullmatch(r"[0-9a-f]{40}", source_commit) is not None, "--source-commit requires a full lowercase Git SHA")
    inputs = Inputs()
    protocol = inputs.read(run / "PROTOCOL.json")
    freeze = inputs.read(run / "SOURCE_FREEZE.json")
    require(freeze.get("protocol_sha256") == digest(run / "PROTOCOL.json"), "Protocol differs from scientific freeze")
    online = inputs.read(run / "FULL_ONLINE_CONFIRMATION_SUMMARY.json")
    cross = inputs.read(run / "TRAIN_EXECUTION_CROSS_SUMMARY.json")
    require(cross.get("schema") == "hcsn.r15.train-execution-cross.summary.v1", "Unknown train/execution cross summary schema")
    require(cross.get("existing_primary_contrasts_unchanged") is True and cross.get("no_new_selection_or_acceptance_gate") is True,
            "Cross supplement changes original selection or acceptance contract")
    summary = inputs.read(run / "SUMMARY.json")
    require(summary.get("source_protocol_sha256") == digest(run / "PROTOCOL.json"), "Frozen replay summary identifies another protocol")
    audit = inputs.read(run / "INDEPENDENT_AUDIT.json")
    require(audit.get("schema") == "hcsn-r15.independent-audit.v1", "Unknown audit schema")
    require(Path(audit.get("run", "")).resolve() == run, "Audit identifies another run")
    require(isinstance(audit.get("failures"), list) and boolean(audit.get("passed"), "audit passed") == (not audit["failures"]), "Audit status contradicts failures")
    integer(audit.get("checks"), "audit checks", 1)
    ledger = inputs.read(ledger_path)
    actual = actual_analysis(protocol, online)
    crossed = cross_tables(protocol, actual, cross)
    replay = replay_analysis(protocol, summary)
    for key, row in actual["selected"].items():
        require(row["selected_families"] == replay["selected"][key].get("selected_families"), "Actual comparator differs from frozen validation choice")
    runtime = runtime_check(ledger, online, cross, run)
    alignment = alignment_summary(online)
    recovery = recovery_evidence(inputs, run, protocol, summary)
    numerical = numerical_evidence(inputs,study)
    registration = inputs.read(run / "full_online_confirmation/SELF_REGISTRATION.json", required=False)
    if registration is not None:
        require(registration.get("parent_source_freeze_sha256") == digest(run / "SOURCE_FREEZE.json")
                and registration.get("parent_protocol_sha256") == digest(run / "PROTOCOL.json"), "Supplement registration identifies another freeze")
        require(registration.get("confirmation_opened_at_registration") is False and registration.get("batch_size") == 32,
                "Supplement chronology or batch contract differs")
    cross_registration_path = run / "train_execution_cross/SELF_REGISTRATION.json"
    cross_registration = inputs.read(cross_registration_path)
    require(cross_registration.get("schema") == "hcsn.r15.train-execution-cross.registration.v1",
            "Unknown cross supplement registration schema")
    require(registration is not None and cross_registration.get("parent_source_freeze_sha256") == digest(run/"SOURCE_FREEZE.json")
            and cross_registration.get("parent_protocol_sha256") == digest(run/"PROTOCOL.json")
            and cross_registration.get("parent_online_registration_sha256") == digest(run/"full_online_confirmation/SELF_REGISTRATION.json"),
            "Cross registration identifies different parent records")
    require(cross_registration.get("confirmation_opened_at_registration") is False and cross_registration.get("batch_size") == 32,
            "Cross chronology or batch-size declaration differs")
    require(cross.get("registration_sha256") == digest(cross_registration_path)
            and cross.get("source_sha256") == cross_registration.get("source_sha256"),
            "Cross summary differs from its registered source identity")
    old_freeze_path = run.parent / "formal_02/SOURCE_FREEZE.json"
    old_freeze = inputs.read(old_freeze_path, required=False)
    restart_identity = dict(available=False, status=UNAVAILABLE,
                            reason="The abandoned attempt source-freeze metadata was not supplied")
    if old_freeze is not None:
        require(isinstance(old_freeze.get("files"), dict) and old_freeze["files"], "Empty abandoned source inventory")
        source_equal = old_freeze["files"] == freeze.get("files")
        protocol_equal = old_freeze.get("protocol_sha256") == freeze["protocol_sha256"]
        restart_identity = dict(available=True, prior_run="formal_02", current_run=run.name,
            previous_source_freeze_sha256=digest(old_freeze_path), current_source_freeze_sha256=digest(run/"SOURCE_FREEZE.json"),
            same_registered_source_inventory=source_equal, same_registered_protocol_sha256=protocol_equal,
            same_registered_source_and_protocol=source_equal and protocol_equal,
            scope="Compare the existing freeze inventories and registered protocol hashes; this is not a new chronology proof")
    posterior = summary.get("posterior_qualification")
    if posterior is not None:
        require(isinstance(posterior, dict) and posterior.get("upper_loss_limit") == 1e-7, "Missing registered posterior upper-loss limit")
        for field in ("evidence_complete", "finite_diagnostics", "metadata_consistent", "registered_continuous_tail_qualification_pass", "confirmation_all_prefix_upper_loss_pass", "confirmation_occupied_upper_loss_pass"):
            boolean(posterior.get(field), "posterior " + field)
    resources = summary.get("resources")
    require(isinstance(resources, dict), "Missing training/resource identity evidence")
    pairs = keyed(resources.get("independent_training_pairs"), ("task", "seed"), "training pairs")
    require(set(pairs) == set(itertools.product(protocol["tasks"], protocol["seeds"])), "Incomplete independent-training pairs")
    for pair in pairs.values():
        boolean(pair.get("identical_initialization"), "paired initialization")
        boolean(pair.get("separate_checkpoint_paths"), "independent checkpoint paths")
        for field in ("selected_hashes_equal", "final_hashes_equal"):
            require(set(pair.get(field, {})) == set(protocol["families"]), "Missing separate selected/final family hashes")
            for value in pair[field].values(): boolean(value, field)
    acceptance = gates(protocol, actual)
    unavailable = []
    if registration is None: unavailable.append("supplement_registration_identity")
    if not restart_identity["available"]: unavailable.append("abandoned_to_current_freeze_identity")
    for name in ("continuous_reference","finite_law_checks","independent_structural_review"):
        if not numerical[name]["available"]: unavailable.append("numerical_qualification."+name)
    if posterior is None: unavailable.append("retained_prefix_posterior_qualification")
    if not recovery["available"]: unavailable.append("recovery_confirmation")
    elif not recovery["four_arms"]["available"]: unavailable.append("recovery_four_arm_absolute_outcomes")
    review = dict(schema="hcsn.r15.publication.acceptance-review.v1", created_utc=datetime.now(timezone.utc).isoformat(),
        run=str(run), report_generator_sha256=digest(SOURCE), source_commit=source_commit,
        source_commit_scope="Published scientific source commit supplied by operator; not the report commit and not remotely verified by this helper",
        source_protocol_sha256=digest(run / "PROTOCOL.json"), source_freeze_sha256=digest(run / "SOURCE_FREEZE.json"),
        primary_estimate_source="actual whole-cohort execution", actual_acceptance=acceptance,
        actual_D_minus_B_identity_check=dict(passed=True,absolute_tolerance=1e-12,
            metrics=list(METRICS),paired_fit_count=8,
            scope="All task/domain actual total and same-value-weights D-B fit values are identical within the fixed tolerance"),
        frozen_replay_acceptance=summary.get("acceptance", {"status": UNAVAILABLE}),
        actual_outcome_analysis=online["actual_outcome_analysis"],
        train_execution_cross=dict(summary=cross, registration=cross_registration,
            reused_LL_VL_VV_match_original_actual_fit_values=True,
            no_new_primary_gate=True, original_registered_acceptance_unchanged=True),
        frozen_replay=dict(total_effects=summary["total_effects"], conditional_execution_effects=summary["conditional_execution_effects"],
            validation_selected_comparator=summary["validation_selected_comparator"], distribution_ablations=summary["distribution_ablations"]),
        runtime_alignment=alignment, audit=audit,
        audit_pass_is_arithmetic_identity_coverage_not_science=True,
        runtime=dict(whole_cohort_actual={key: online[key] for key in ("conditions", "expected_conditions", "object_executions", "expected_object_executions", "actual_reads", "processed_prefix_tokens", "model_calls", "controller_batch_calls", "group_cpu_seconds", "nested_actor_cpu_seconds", "process_receipt")},
            ledger=ledger,every_canonical_formal_worker_successful=runtime["every_canonical_formal_worker_successful"],
            original_training_launcher_completed=False,all_process_attempts_successful=False,
            canonical_success_is_not_all_historical_attempt_success=True,nested_times_added_to_worker_total=False),
        recovery=recovery, posterior_qualification=posterior if posterior is not None else {"status": UNAVAILABLE},
        numerical_qualification=numerical,
        actual_online_direct_state_tail_qualification=dict(status=UNAVAILABLE,
            reason="Retained posterior arrays belong to frozen replay prefix computation. Actual execution saves outcomes, not an independent state-trace qualification; changed read trajectories cannot inherit replay occupied masks.",
            replay_read_trajectory_mismatch_count=alignment["totals"]["read_count"]["mismatches"]),
        training_resources=resources,
        restart_freeze_identity=restart_identity,
        supplement_registration=registration if registration is not None else {"status": UNAVAILABLE},
        unavailable_sections=unavailable, foundation_core_acceptance=False, all_user_requirements_closed=False,
        full_cost_advantage_established=False, input_files=inputs.records,
        analysis_scope="Extraction and the unchanged registered threshold comparisons only. No new training, selection, confidence intervals, pooling, filtering or raw test access.")
    context = dict(protocol=protocol, freeze=freeze, online=online, summary=summary, audit=audit, ledger=ledger,
                   actual=actual, crossed=crossed, cross=cross, replay=replay, runtime=runtime, recovery=recovery, pairs=pairs, review=review)
    return review, context


def fnum(value, digits=6):
    if value is None:
        return "未提供（not_available）"
    if value != 0 and abs(value) < 10**(-digits):
        return f"{value:.5e}"
    return f"{value:.{digits}f}"


def interval(item):
    return f"{fnum(item['mean'])} [{fnum(item['fit_t95'][0])}, {fnum(item['fit_t95'][1])}]"


def yes(value):
    return "通过" if value else "未通过"


def escape(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def table(headers, rows):
    lines = ["| " + " | ".join(map(escape, headers)) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(map(escape, row)) + " |" for row in rows)
    return "\n".join(lines)


def render_cross(protocol, cross, tables):
    """Display the new estimands under their own labels, never as A/B/C/D."""
    lines = ["## 独立补充：每个核心的训练 × 执行四格", "",
        "本节使用另行登记的 LL/LV/VL/VV。首字母是内容模型的训练程序，末字母是执行规则；L 为 light，V 为 value。LL、VL、VV 复用原全对象实际执行，LV 是新增执行。它与前文 core × value 程序的 A/B/C/D 是两个不同的二维设计，不能互换标签。",
        "LV 将 light-trained 内容模型交给相同 task/seed 的 value-trained 组控制器执行。这个控制器来自六模型 value 共训组，在 LV 不重训、不重新校准、不重新选阈值或 checkpoint；控制器迁移本身是该固定执行干预的组成部分。light/value 内容训练仍限于已登记联合优化、共同裁剪和组级选 step 的程序，不能外推为各架构独自训练的普适效应。",
        f"新增 LV 覆盖 {cross['coverage']['conditions']:,}/{cross['coverage']['expected_conditions']:,} 条件、{cross['coverage']['object_executions']:,}/{cross['coverage']['expected_object_executions']:,} 次对象条件执行。这是相同确认对象的附加执行，不增加独立对象数。新补充单独登记，不改写原冻结记录、原主门、模型/策略选择或前文实际/replay差异。", "",
        "### 两个任务的 IID LL/LV/VL/VV", ""]
    rows = []
    for task in protocol["tasks"]:
        for family in (ORDINARY, ANALYTIC):
            for cell in CROSS_CELLS:
                metrics = tables["families"][(task,"iid",family)]["cells"][cell]["metrics"]
                rows.append((task,family,cell,fnum(metrics["accuracy"]["mean"]),interval(metrics["utility"]),
                             fnum(metrics["read_count"]["mean"]),fnum(metrics["fee"]["mean"]),fnum(metrics["initial_stop"]["mean"])))
    lines += [table(["任务","核心","单元格","准确率","效用 [fit t95]","READ/对象","费用/对象","初始 STOP 比例"],rows), "",
        "### 固定另一层的五项效应", "",
        "每个区间直接抽取补充已计算的八 seed 配对 fit t95，df=7，nominal；报告未重算区间、合并域或新增科学接受门。缺失模态仍单独列为负对照。", ""]
    for negative in (False,True):
        if negative: lines += ["#### 缺失模态负对照", ""]
        rows = []
        for task in protocol["tasks"]:
            for domain in protocol["domains"][task]:
                if domain.startswith("missing") != negative: continue
                for family in (ORDINARY,ANALYTIC):
                    effects = tables["families"][(task,domain,family)]["effects"]
                    rows.append((task,domain,family,*[interval(effects[name]["metrics"]["utility"]) for name in CROSS_EFFECTS]))
        lines += [table(["任务","域","核心",*[CROSS_LABELS[name] for name in CROSS_EFFECTS]],rows), ""]
    lines += ["### 四个训练/执行单元格中的 analytic−ordinary", "",
        table(["任务","域",*[cell+" [fit t95]" for cell in CROSS_CELLS]],[(task,domain,*[interval(tables["core_differences"][(task,domain,cell)]["metrics"]["utility"]) for cell in CROSS_CELLS]) for task in protocol["tasks"] for domain in protocol["domains"][task]]), "",
        "LL 与原 C−A、VV 与原 D−B 复用相同实际输出；这是已有对比在另一张表中的定位，不是新增独立复现。新增 LV、原 LL/VL/VV 与每个控制器的 checkpoint/hash 来源保存在补充登记和 INDEX 中。完整指标、fit 值及控制器来源保留在 ACCEPTANCE_REVIEW.json.train_execution_cross。"]
    return lines


def render_numerics(evidence):
    lines = ["### 固定初始 atom 的现成数值资格", "",
        "这里只整理已有检查，不重新运行求解器。formal_03 的指定 profile 是 tail_half_upper60；固定初始 x=1、reset=0.8、漂移 −0.25、扩散 1，在 t=0.25、1、1.75、4 四个登记时点比较连续参照。不能把其他 tail profile 的结果冒充正式配置，也不能把这些初始 atom 结果当作所有学得后验的连续精度证书。", ""]
    numerical = evidence["continuous_reference"]
    if numerical["available"]:
        lines += [f"数值文件保留 {numerical['retained_profile_rows']} 行（三种 profile × 四时点）；下表只按预先指定 formal profile 的 {numerical['selected_profile_rows']} 行取各指标最大误差。文件整体 passed={numerical['numerical_file_passed']}；指定 profile 四行 passed={numerical['selected_profile_rows_passed']}。", "",
            table(["指标","指定 profile 四时点最大误差","登记阈值","判断"],[(name,fnum(value["maximum_error"],10),fnum(value["registered_limit"],6),yes(value["passed"])) for name,value in numerical["metrics"].items()]), ""]
        if "original_cli_failure" in numerical["serialization_history"]:
            lines += ["保留的序列化历史记录了一次计算后 JSON 写出失败；后续包装器仅将 NumPy scalar 转为原生 Python scalar。原失败输出、包装器与计算源码身份仍在数值文件的 serialization 字段中，不把它删成一条无失败运行。", ""]
    else:
        lines += ["指定 profile 的连续数值参照：not_available；没有把缺失误差填成零或通过。", ""]
    law = evidence["finite_law_checks"]
    if law["available"]:
        lines += [f"最终有限 law 检查：{law['count']} 项，passed={law['passed']}，配置 upper={fnum(law['config']['tail_upper'],0)}，continuous_model_acceptance={law['continuous_model_acceptance']}。这份有限状态、内容矩与守恒等检查不是一般连续模型接受证书。", ""]
    else:
        lines += ["最终有限 law 检查：not_available。", ""]
    independent = evidence["independent_structural_review"]
    if independent["available"]:
        lines += [f"另存的独立结构复核有 {independent['check_count']} 项，passed={independent['passed']}，对应 upper={fnum(independent['upper'],0)}、{independent['positions']} 个位置。它检验生成元代数、插值、锚点含义、缓存与开发接口；**不能描述成 formal upper60 的独立数值全证**。", ""]
    else:
        lines += ["独立结构复核：not_available；未用其他 profile 的检查补成正式数值资格。", ""]
    return lines


def render(context, artificial=False):
    p, online, frozen, review = (context[k] for k in ("protocol", "online", "summary", "review"))
    actual, replay, ledger, recovery = (context[k] for k in ("actual", "replay", "ledger", "recovery"))
    verdict = review["actual_acceptance"]
    lines = ["# R15 分布内容网络：正式证据与验收复核", ""]
    if artificial:
        lines += ["> **人工 fixture 候选报告。以下数值全部为代码构造的检查数据，不是 formal_03 实验结果，未读取正式确认数据。**", ""]
    iid = "; ".join(f"{task} 的实际 D−B 为 {interval(actual['effects'][(task, 'iid', 'D-B')]['metrics']['utility'])}" for task in p["tasks"])
    lines += [f"本轮已记录 {online['conditions']:,}/{online['expected_conditions']:,} 个真实执行条件、{online['object_executions']:,}/{online['expected_object_executions']:,} 次对象条件执行。{iid}。方括号是八个配对拟合均值的 t95 区间，df=7。",
        f"另行登记的真正训练×执行交叉新增 {context['cross']['coverage']['conditions']:,} 个 LV 条件、{context['cross']['coverage']['object_executions']:,} 次对象条件执行；复用原 LL/VL/VV，不增加独立对象或拟合重复。",
        f"按实际执行结果重列原登记的质量、效应及压力门，结论为 **{yes(verdict['registered_quality_effect_pressure_gate_pass'])}**。完整成本优势、基础核心资格与用户全部要求仍为 **未建立 / false**；实现覆盖、独立审计或某个子门通过均不自动关闭这些要求。",
        "主结果使用全对象 batch-32 实际 rollout；冻结 replay 的差异与区间单独保留。所有区间是 nominal，未作多重比较校正。", "",
        "## 1. 来源、完成范围与科学单位", "",
        f"基线提交：`{p['baseline_sha']}`。已发布源码提交：`{review['source_commit']}`。" if review["source_commit"] else f"基线提交：`{p['baseline_sha']}`。已发布源码提交：未提供（not_available）。",
        f"主协议 SHA256：`{review['source_protocol_sha256']}`。主冻结记录 SHA256：`{review['source_freeze_sha256']}`。报告抽取器 SHA256：`{review['report_generator_sha256']}`。源码提交字段由调用者提供；此工具不验证远端发布，也不将报告所在提交写作自己的源码来源。",
        "全对象执行补充在主冻结之后、已记录确认访问之前单独登记；不能追溯写成原主协议的一部分。其身份见本报告末尾输入清单及 ACCEPTANCE_REVIEW.json。哈希与冻结声明支持记录身份，不独自证明访问时间线。",
        f"训练资源身份覆盖 {len(context['pairs'])*2} 个 task/seed/train_mode 组及每组 {len(p['families'])} 个家族；实际进程成功与失败数另按第 8 节 wait4 收据列账。",
        "八个 seed 是每个程序单元格的拟合重复。六家族、两任务、light/value 的模型数不是更多独立重复；同一确认对象跨 seed 重复出现也不增加独立对象数。", "",
        "## 2. 用户九项要求逐项复核", ""]
    posterior = review["posterior_qualification"]
    posterior_status = yes(posterior["registered_continuous_tail_qualification_pass"]) if "registered_continuous_tail_qualification_pass" in posterior else "证据未提供"
    rows = [
        ("固定零延迟完整后继、多次事件、复位余时", "有限生成元、cemetery 与实际学习后验诊断已接入", "登记保留前缀上界门："+posterior_status, "不自动关闭连续完整后继要求；全在线状态诊断未单独保存"),
        ("同一前缀真实后续动作价值、初始 STOP、实际费用", "真实 Qπ 训练目标、零观测 STOP 与付费 READ；全对象实际执行", f"{online['conditions']:,} 条件；与 replay 不一致条件 {review['runtime_alignment']['mismatch_condition_count']}", "完整 dt 日程和有限预算是公开信息；标签只在评分/目标端使用；不声称一般最优控制"),
        ("相同价值控制下解析核心稳定增益", "主 pair 在每个 value 组共用同一 controller", "实际注册质量/效应/压力门："+yes(verdict["registered_quality_effect_pressure_gate_pass"]), "强普通另列；完整成本与基础核心资格未建立"),
        ("保持与长度压力域内容收益", "五个注册压力域均保留", "逐域实际 D−B 和所有退化见第 4 节", "不合并成有利总平均；缺失模态单列负对照"),
        ("主动恢复后重新处理实际收益", "四个同前缀动作、train/val 冻结策略及真实所选动作执行", "第 7 节逐故障域报告实际预测、全费用与固定策略价格敏感性" if recovery["available"] else "not_available", "完美 alarm、可信 cache、内容故障；恢复耗时期间外部任务冻结；通用恢复收益未证明"),
        ("完整条件分布进入内容网络后的收益", "有限位置 law 与条件内容一阶矩进入传播/观察/读出", "主效应与三项冻结执行消融均保留", "一阶矩 closure 不是任意内容向量完整联合条件分布"),
        ("独立训练×执行四格总效应", "原 core×value A/B/C/D；另补每 core 的 train×exec LL/LV/VL/VV", "独立附加 LV 真实执行；两种二维设计及同权重效应分开", "该联合训练方案内的程序单元格差；LV 控制器来自 value 组且不重校准；不等于架构独自训练的普适效应"),
        ("通用学习、移动边界、真实多模态、大规模外推", "固定物理核的两个合成向量任务", "本轮没有对应一般性确认数据", "物理漂移/扩散/reset/边界固定；向量 binding 不是实际音视频图像"),
        ("GPU、物理能耗、真实获取/服务成本", "实际 CPU、wall、RSS 与含失败 attempt 的下界账", "第 8 节给全对象 actor、worker 与废弃开销", "GPU/Joules/外部账单未测；归一化 tariff 不是账单或能耗")]
    lines += [table(["用户要求", "实现范围", "本轮证据", "保留边界"], rows), "",
        "## 3. 实际 IID 程序四格与原登记门", "",
        "A=ordinary distribution，light 训练/light 执行；B=ordinary distribution，value 训练/value 执行；C=analytic distribution，light 训练/light 执行；D=analytic distribution，value 训练/value 执行。下表准确率、效用、READ 数、费用与初始 STOP 均来自真实 rollout。效用=正确率−归一化 READ/时间费用，尚未扣物理计算或外部服务账。", ""]
    iid_rows = []
    for task in p["tasks"]:
        for letter in ARMS:
            m = actual["cells"][(task, "iid")]["cells"][letter]["metrics"]
            iid_rows.append((task, letter, fnum(m["accuracy"]["mean"]), interval(m["utility"]), fnum(m["read_count"]["mean"]), fnum(m["fee"]["mean"]), fnum(m["initial_stop"]["mean"])))
    lines += [table(["任务", "臂", "准确率", "效用 [fit t95]", "READ/对象", "费用/对象", "初始 STOP 比例"], iid_rows), ""]
    gate_rows = []
    for task, item in verdict["per_task"].items():
        primary = item["iid_D_minus_B"]
        gate_rows.append((task, yes(item["all_four_iid_quality_pass"]), interval(primary), f"{primary['positive_fit_count']}/8", yes(item["pressure_pass"]), yes(item["registered_quality_effect_pressure_gate_pass"])))
    lines += [table(["任务", "四臂 IID 准确率≥0.70", "IID D−B [t95]，下界须>0", "正 seed，须≥6/8", "五压力均值≥−0.02", "该任务有限门"], gate_rows), "",
        "判据严格照原协议：准确率阈值含等号，D−B 的 t95 下界严格大于零，正 seed 用效应严格大于零计数，压力均值允许等于 −0.02。强普通对照和后验资格另列，未偷偷增删原门。即使有限门全部通过，完整成本、foundation_core_acceptance、all_user_requirements_closed 仍为 false。", "",
        "### IID 的五项总效应", "",
        table(["任务", "对比", "实际净效用效应 [fit t95]", "正 seed"], [(task, c, interval(actual["effects"][(task,"iid",c)]["metrics"]["utility"]), str(actual["effects"][(task,"iid",c)]["metrics"]["utility"]["positive_fit_count"])+"/8") for task in p["tasks"] for c in CONTRASTS]), "",
        "本表的“独立训练总效应”指该联合训练方案内的程序单元格差。light/value 各有独立优化器与整组 checkpoint；每组共享全参数 grad_clip，并按六模型平均验证效用共同选择 step。value 组还共同训练并共用同一个 controller。D−B 在每个 task/seed 内确为同一 controller 权重，但内容特征不同，动作仍可不同。Q-MSE 可经 logits→probability/entropy/margin 的特征路径反传内容网络；detach 用在 realized-Q target 与后继动作分支，不能写成内容特征全部被 detach。精确程序口径另见 publication/ESTIMAND_REVIEW_ZH.md。", "",
        "## 4. 全部注册域的实际主效应与强普通对照", "",
        "每行保持一个 task/domain。主效应是 D−B；强普通差是 D 减该 seed 的 value 训练 SUMMARY.strongest_ordinary，不在确认集重新排名。", ""]
    def domain_rows(negative):
        result = []
        for task in p["tasks"]:
            for domain in p["domains"][task]:
                if domain.startswith("missing") != negative: continue
                effect = actual["effects"][(task,domain,"D-B")]
                m = effect["metrics"]
                result.append((task, domain, interval(m["utility"]), fnum(m["accuracy"]["mean"]), fnum(m["fee"]["mean"]), f"{m['utility']['positive_fit_count']}/8", interval(actual["selected"][(task,domain)]["metrics"]["utility"]), effect["partition_cluster_count"]))
        return result
    headers = ["任务", "域", "D−B 效用 [fit t95]", "准确率差", "费用差", "正 seed", "D−预选普通 [fit t95]", "partition 数"]
    lines += [table(headers, domain_rows(False)), "", "### 缺失模态负对照（不纳入压力门或有利汇总）", "", table(headers, domain_rows(True)), "",
        "### 验证阶段已选定的普通家族", "",
        table(["任务", "seed", "预选普通家族"], [(task, seed, actual["selected"][(task,"iid")]["selected_families"][str(seed)]) for task in p["tasks"] for seed in p["seeds"]]), "",
        "### 同 value 权重的执行效应（独立列示）", "",
        "下表 A/C 使用 value-trained 权重进行 read-all 执行，因此属于固定权重执行条件效应，不与上面的独立训练总效应混称。全部域的五项结果保留在 ACCEPTANCE_REVIEW.json；此处显示 IID。", "",
        "两种 estimand 中的 B/D 是同一组实际 value-trained/value-executed 输出，因此 D−B 必须相同。生成器已对全部域、全部指标的八个 fit 值逐一检查，绝对容差为 1e−12；其他对比可随 A/C 的训练权重变化。", "",
        table(["任务", "对比", "同权重实际执行效应 [fit t95]"], [(task,c,interval(actual["conditional"][(task,"iid",c)]["metrics"]["utility"])) for task in p["tasks"] for c in CONTRASTS]), "",
        *render_cross(p,context["cross"],context["crossed"]), "",
        "## 5. 全对象实际执行与冻结 replay 的差异", "",
        f"不一致条件数：**{review['runtime_alignment']['mismatch_condition_count']}**。预测与 READ 使用精确相等比较；费用、效用和经过时间按补充登记的数值容差判定。差异 mask 与原始路径保留，未覆盖旧记录或删除不一致条件。", "",
        table(["字段", "不一致对象条件数", "不一致条件中最大绝对差"], [(name, item["mismatches"], fnum(item["maximum_absolute_difference"], 10)) for name,item in review["runtime_alignment"]["totals"].items()]), "",
        "若无不一致条件，表中差值零表示没有超过容差的差异，不宣称浮点逐 bit 相等。完整不一致条件清单在 ACCEPTANCE_REVIEW.json.runtime_alignment.mismatch_conditions；原始 mask 位置由 FULL_ONLINE_CONFIRMATION_INDEX.json 指明。", "",
        table(["任务", "域", "actual D−B [fit t95]", "replay D−B [fit t95]", "replay 固定 fit 的 partition cluster95", "partition 数"], [(task,domain,interval(actual["effects"][(task,domain,"D-B")]["metrics"]["utility"]),interval(replay["total_effects"][(task,domain,"D-B")]),str(replay["total_effects"][(task,domain,"D-B")]["fixed_fit_object_cluster95"]),replay["total_effects"][(task,domain,"D-B")]["partition_cluster_count"]) for task in p["tasks"] for domain in p["domains"][task]]), "",
        "fit t95 表示八次配对优化重复的变动；冻结 replay 的 cluster95 先平均固定八个 fit，再按较粗 partition_ids 整簇重采样 5,000 次，seed=151999。不能把该 replay 区间贴到另一份 actual 均值上，也不能把四组合 group 或重复 seed 当作独立确认对象。", "",
        "## 6. 分布内容状态、执行消融与后验边界", "",
        "模型使用完整有限位置概率和条件内容一阶矩 closure：p 与 m 在间隔内沿同一有限生成元推进，再由学习的观测、写入、位置加权读出更新。默认 280 个活动位置和 1 个 upper cemetery，宽度 16；每对象 4,777 个 recurrent scalars、20,232 字节状态本体，未包含梯度、临时张量、框架或 transition cache。两主核心均 2,028 个训练参数。物理初始位置 1、漂移 −0.25、扩散 1、reset 0.8、零延迟固定。ordinary 使用匹配 stationary law/慢衰减率的单速率混合先验。",
        "这不是任意内容向量的完整联合条件分布，也不是已证明精确的物理 sensor Bayesian filter。物理 reset 保留内容，与主动恢复清空整个状态的 reset 不同。通用物理参数梯度、移动边界与真实媒体不在本轮资格。",
        "content_independence 保持 p 和未加权内容总矩，但可能立刻改变加权读出；mean_position 同时改变多种性质，不能叫纯方差效应；readout_independence 保持干预当下 feature/logit/controller score，再删除位置内容相关，但不保持未加权均值。以下是冻结 replay 上同权重干预效应，不是重新训练架构的总效应。", "",
        table(["任务", "域", "full−content_independence [fit t95]", "full−mean_position [fit t95]", "full−readout_independence [fit t95]"], [(task,domain,*[interval(replay["ablations"][(task,domain,"full_minus_"+name)]) for name in ("content_independence","mean_position","readout_independence")]) for task in p["tasks"] for domain in p["domains"][task]]), ""]
    lines += render_numerics(review["numerical_qualification"])
    if "upper_loss_limit" in posterior:
        lines += ["### 已保存前缀的后验上界资格", "", table(["诊断", "记录值"], [
            ("上界阈值", "≤ 1e-7"), ("诊断证据完整", posterior["evidence_complete"]),
            ("最大 validation upper loss", fnum(posterior.get("maximum_validation_upper_loss"), 12)),
            ("最大确认全前缀 upper loss", fnum(posterior.get("maximum_confirmation_upper_loss"), 12)),
            ("最大 replay 已访问前缀 upper loss", fnum(posterior.get("maximum_occupied_confirmation_upper_loss"), 12)),
            ("最大质量误差", fnum(posterior.get("maximum_reported_mass_error"), 12)),
            ("最小概率", fnum(posterior.get("minimum_reported_probability"), 12)),
            ("登记连续 tail 子门", yes(posterior["registered_continuous_tail_qualification_pass"])),
            ("全在线独立状态 trace 资格", "not_available")]), ""]
    else:
        lines += ["后验诊断：未提供（not_available）。不能将空字段写成 upper loss=0 或自动通过。", ""]
    lines += ["上界失败时仍保留有限模型结果，连续 tail 资格不能通过。即使上界通过，也不证明每个学习后验的连续离散化精度、完整后继、reset 或一阶矩闭合。上述 occupied mask 属于冻结 replay 的 read_count；实际 online 若读取轨迹不同，不能继承这个 mask 的资格。真实在线输出未保存独立状态诊断，故该项明确 not_available。", "",
        "## 7. 收费主动恢复与重新处理", "",
        "四臂都从同一付费受损前缀分支：none、reset_only、replay_only、reset_replay。原 READ/时间、监测、缓存、reset、重新读取和处理及服务时间收费全部保留。replay_only 只重新观察缓存内容，不重复推进历史物理时间；reset_replay 重建历史前缀。策略只在 IID train/val 选择，确认期间冻结。", ""]
    if recovery["available"]:
        r = recovery["frozen_summary"]
        eff = keyed(r["effects"], ("task","domain","cohort","family","contrast"), "recovery render")
        rows = []
        for row in r["outcomes"]:
            key = tuple(row[field] for field in ("task","domain","cohort","family"))
            rows.append((*key, fnum(row["clean_accuracy"]["mean"]), fnum(row["selected_accuracy"]["mean"]), fnum(row["selected_fee"]["mean"]),
                         interval(eff[(*key,"selected_minus_protected_none")]), interval(eff[(*key,"selected_minus_unprotected_none")]), interval(eff[(*key,"reset_replay_interaction")])))
        lines += [table(["任务","域","故障 cohort","家族","clean 准确率","selected 准确率","selected 全费用","selected−保护 none [t95]","selected−无保护 none [t95]","reset×replay [t95]"], rows), "",
            f"真实所选动作执行与四臂 evaluator 对应预测/动作的差异数为 {recovery['selected_actual_prediction_action_mismatches']}。这些实际 actor CPU 合计 {fnum(recovery['selected_actor_cpu_seconds_sum'],3)} 秒，嵌套于 recovery_confirm worker，未重复加入账本。无保护 none 是去掉监测/缓存费用的会计参照，不是另测的实现性能。", "",
            "### 选定动作的实际次数", "",
            "每格按既有八个 fit 的动作计数求和，单位是对象条件执行次数，不是独立对象；各 fit 原计数保存在 ACCEPTANCE_REVIEW.json。", "",
            table(["任务","域","cohort","家族","alarm 比例","none","reset_only","replay_only","reset_replay"], [(*[row[field] for field in ("task","domain","cohort","family")], fnum(row["alarm_fraction"]), *[sum(counts[j] for counts in row["action_counts_by_fit"].values()) for j in range(4)]) for row in r["outcomes"]]), "",
            "### 固定策略收费敏感性", "",
            "只缩放相对无保护 none 的增量费用，策略和动作保持不变；每格为 selected−无保护 none 的已计算均值与 fit t95，不在确认集选择价格或策略。", "",
            table(["任务","域","cohort","家族","×0","×0.5","×1","×2","×4"], [(*[row[field] for field in ("task","domain","cohort","family")], *[interval(value["gain_vs_unprotected_none"]) for value in row["values"]]) for row in r["sensitivities"]]), ""]
        if recovery["four_arms"]["available"]:
            lines += ["### 四臂绝对结果：直接保留每个 fit 的既有均值", "",
                "每格为 准确率 / 全费用 / 净效用；不新增跨 fit 汇总、区间或筛选。none 是付监测与缓存费的保护基线。", "",
                table(["任务","域","cohort","家族","seed",*ACTIONS], [(*[row[field] for field in ("task","domain","cohort","family","seed")], *[" / ".join(fnum(row["summary"]["arms"][action][metric]) for metric in ("accuracy","fee","utility")) for action in ACTIONS]) for row in recovery["four_arms"]["rows"]]), ""]
        else:
            lines += ["四臂绝对结果：未提供（not_available）；现有 frozen SUMMARY 只保存选定结果及若干四臂对比，不用默认零补出缺失臂。", ""]
    else:
        lines += ["恢复确认结果：未提供（not_available）。", ""]
    lines += ["恢复边界：故障仅为本地模拟内容 sign/zero，alarm 完美且所有臂相同，缓存可信。恢复服务期间外部任务不演化，服务时间只按登记 tariff 收费。这是 read-all 恢复 profile，不能称原 STOP policy 的一般恢复价值。两家族分别校准恢复 selector；恢复系统之间的差异不是共享 selector 下的纯核心效应。无故障开销完整保留。", "",
        "## 8. 全对象实际计算与全部已记录 attempt 成本", "",
        table(["全对象实际执行量", "数值"], [("对象条件执行", f"{online['object_executions']:,}"), ("实际 READ", f"{online['actual_reads']:,}"),
            ("重算 prefix token", f"{online['processed_prefix_tokens']:,}"), ("model calls", f"{online['model_calls']:,}"), ("controller batch calls", f"{online['controller_batch_calls']:,}"),
            ("全对象 actor CPU 秒（嵌套）", fnum(online["nested_actor_cpu_seconds"],3)), ("全对象 group CPU 秒（包含 actor）", fnum(online["group_cpu_seconds"],3)),
            ("全对象 worker CPU 秒（完整 wait4）", fnum(online["process_receipt"]["process_cpu_seconds"],3))]), "",
        table(["另行登记 LV 执行量", "数值"], [("新增对象条件执行", f"{context['cross']['coverage']['object_executions']:,}"),
            ("新增实际 READ", f"{context['cross']['resources']['actual_reads']:,}"),
            ("新增重算 prefix token", f"{context['cross']['resources']['processed_prefix_tokens']:,}"),
            ("新增 model calls", f"{context['cross']['resources']['model_calls']:,}"),
            ("新增 controller batch calls", f"{context['cross']['resources']['controller_batch_calls']:,}"),
            ("LV actor CPU 秒（嵌套）", fnum(context['cross']['resources']['nested_actor_cpu_seconds'],3)),
            ("LV group CPU 秒（包含 actor）", fnum(context['cross']['resources']['group_cpu_seconds'],3)),
            ("LV worker CPU 秒（完整 wait4）", fnum(context['cross']['resources']['process_receipt']['process_cpu_seconds'],3))]), "",
        "actor 是全部注册对象的 batch-32 执行，包含条件首块的 transition-cache 准备；group 另含 checkpoint、数据生成、比较与 IO；worker 另含进程导入等。三层互相嵌套，只单列解释，不相加。该测量没有将 core 快慢和动作数量混淆为相同计算量的硬件效率。", "",
        table(["stage","canonical 完成/应有 jobs","canonical 失败 jobs","canonical worker CPU 秒","wall 秒（train为含中断span）","workers","最大单进程 RSS KiB"], [(row["stage"],f"{row['recorded_jobs']}/{row['expected_jobs']}",row["failed_jobs"],fnum(row["observed_worker_cpu_seconds"],3),fnum(row["elapsed_wall_seconds"],3),row.get("launcher_total",{}).get("workers",UNAVAILABLE),fnum(row["maximum_individual_worker_rss_kib"],0)) for row in ledger["formal_03_stages"]]), ""]
    totals = ledger["totals"]
    enospc = ledger["enospc_training_recovery"]
    lines += [table(["非重复计费范围", "CPU 秒"], [("formal_03 canonical 成功进程", fnum(totals["formal_03_successful_completed_process_cpu_seconds"],3)),
        ("formal_03 canonical 已结束失败进程", fnum(totals["formal_03_failed_completed_process_cpu_seconds"],3)),
        ("废弃 OOM attempt 的完整 wait4", fnum(totals["abandoned_attempt_complete_wait4_cpu_seconds"],3)),
        ("废弃 attempt 存活 worker 的 /proc 快照下界", "≥ "+fnum(totals["abandoned_attempt_interrupted_process_cpu_lower_bound_seconds"],3)),
        ("未被 canonical 引用的独立 ENOSPC/恢复进程 wait4",fnum(totals["enospc_additional_complete_wait4_cpu_seconds"],3)),
        ("独立 ENOSPC/恢复进程的部分 CPU 下界",fnum(totals["enospc_additional_partial_cpu_lower_bound_seconds"],3)),
        ("丢失完整收据的历史 process-attempt CPU", "未测（null）；"+str(enospc["unknown_process_attempt_count"])+" 个已记录未知 attempt"),
        ("所有已记录成功、失败、废弃 worker 的总下界", "≥ "+fnum(totals["successful_failed_and_abandoned_cpu_lower_bound_seconds"],3)),
        ("对应 CPU 小时下界", "≥ "+fnum(totals["hours_lower_bound"],6))]), "",
        "六 worker 的原尝试发生 OOM 后，以两个 worker 重启；源码/协议身份核对结果：" + (str(review["restart_freeze_identity"]["same_registered_source_and_protocol"]) if review["restart_freeze_identity"]["available"] else "not_available，未提供旧 freeze 元数据") + "。比较的是两个冻结记录中的源码清单与协议 SHA，完整记录 SHA 另保留在 ACCEPTANCE_REVIEW.json.restart_freeze_identity；不能凭目录名认定同冻结。",
        "废弃 CPU 按 canonical formal_02/attempts/train_01_oom 的完整 wait4，加未被完整收据覆盖的 /proc 快照计入；formal_02 根重复副本、TOTAL 聚合以及 body/actor 不重复相加。快照后的终止尾部 CPU 未测，所以给下界而不是精确总成本。",
        f"随后 formal_03 的原训练启动器在保住 {enospc['retained_original_success_count']} 个完整组后遇到 ENOSPC 写收据故障。原完整组不重训，其余 {enospc['resumed_success_count']} 组在相同科学源码、协议与训练上下文冻结下，于独立工作根从原登记初始化重新执行；未加载旧残缺产物。包括零字节 final.pt 在内的旧文件只保留字节与 SHA 证据，不视为有效模型，不替代 selected，也不能根据字节不同推断模型状态不同。原残缺产物、零字节收据和日志已经隔离保留。",
        "训练 TOTAL 是恢复后的 canonical 成功收据汇总，original_launcher_completed=false，不能称原启动器正常完成。13 个旧成功与 19 个恢复成功各计一次；新工作根和 canonical 的相同 receipt SHA 是同一进程的副本。相同 job 的另一次失败或失联进程具有不同 process_attempt_id，其已测 CPU 另加、未知 CPU 保持 null，不能被后来的成功进程抵消。",
        "train 的 wall 数值是从原 RESTART_REGISTRATION 的时间到恢复汇总结束的 elapsed span，包含中断、等待和恢复；不是连续运行的原启动器 wall，也不是各并行 job wall 之和。其他 stage 使用其启动器记录的经过时间。RSS 是最大单进程峰值，不是全容器并发峰值。六模型联合训练组的 CPU 不除以六冒充各家族单独实测成本。",
        "旧 first-1/16 的 cold/warm_median3 微基准仍在冻结 SUMMARY.cpu_comparisons，作为另一组小样本描述；cold 只清理 transition cache，不等于冷进程或冷操作系统。主要运行证据为本节全对象执行，不能用微基准均值替代总体延迟或吞吐。",
        "未测：原 ENOSPC 少数未保住 wait4 的进程 CPU、中断后尾部 CPU、原/恢复 launcher 的准备与复制/校验 CPU、没有独立收据的开发/分析/出版开销、GPU、物理 Joules、真实获取/服务账单、竞争性的优化部署。表中 null/not_available 不等于零；归一化 tariff 不是物理成本，CPU 秒不能换算成未测 GPU、能耗或账单。", "",
        "## 9. 训练身份、独立审计与最终接受范围", "",
        table(["任务","seed","同初始化","独立路径","selected 相同家族","final 相同家族","light/value selected step"], [(pair["task"],pair["seed"],pair["identical_initialization"],pair["separate_checkpoint_paths"],",".join(f for f,v in pair["selected_hashes_equal"].items() if v) or "无",",".join(f for f,v in pair["final_hashes_equal"].items() if v) or "无",str(pair.get("selected_steps",UNAVAILABLE))) for pair in frozen["resources"]["independent_training_pairs"]]), "",
        "独立优化与独立 checkpoint 路径不保证最终选中的权重不同：step zero 可合法被选中。上表分别报告 selected/final 的实际相等性；完整 checkpoint SHA 在 ACCEPTANCE_REVIEW.json.training_resources 中保留，不混用。",
        f"冻结主实验工件的独立审计：**{yes(context['audit']['passed'])}**，{context['audit']['checks']} 个检查，{len(context['audit']['failures'])} 项失败；最终 canonical worker 收据全部 exit=0：{context['runtime']['every_canonical_formal_worker_successful']}。这不表示所有历史 worker/launcher 成功；原 OOM/ENOSPC 失败与缺失 CPU 仍按第 8 节保留。该审计验证主工件的算术、身份和覆盖；全在线补充的身份/完整性检查属于其独立的 combine 路径，不能把主审计扩称为另一轮全在线独立审计。两者均不认证科学收益或一般性。", ""]
    if context["audit"]["failures"]:
        lines += [table(["失败检查","详情"], [(row.get("check",UNAVAILABLE),json.dumps(row.get("detail",UNAVAILABLE),ensure_ascii=False)) for row in context["audit"]["failures"]]), ""]
    lines += [table(["最终字段","结论"], [("registered_quality_effect_pressure_gate_pass（actual）", verdict["registered_quality_effect_pressure_gate_pass"]),
        ("full_cost_advantage_established", False), ("foundation_core_acceptance", False), ("all_user_requirements_closed", False),
        ("original_full_successor_requirement_closed", False)]), "",
        "这些 false 保留了本轮有限 profile 的真实边界：固定位置 law 与条件一阶矩、有限合成任务、公开时间表、完美故障诊断与可信缓存、未测 GPU/Joules/实际服务账。若质量、强普通、压力或故障恢复存在负结果，均在对应表中保留；覆盖完成不等于科学接受。", "",
        "## 10. 可复核输入与完整机器记录", "",
        "ACCEPTANCE_REVIEW.json 保存实际所有任务/域/家族单元格、五差、独立与同权重 estimand、另行登记 LL/LV/VL/VV 及其既有统计、全部 replay 效应与消融、恢复四臂/收费敏感性、原始审计失败、后验记录及六 stage 成本账本。此报告仅抽取既有结果和重列原登记阈值，没有重新训练、选模型/策略、选域、重新计算区间或打开 raw NPZ。", "",
        table(["输入路径","字节数","SHA256"], [(row["path"],row["bytes"],row["sha256"]) for row in review["input_files"]]), "",
        "输入中未提供的可选证据：" + ("、".join(review["unavailable_sections"]) if review["unavailable_sections"] else "无；全在线独立状态 trace 与范围外物理成本仍按正文标为未测。"), ""]
    return "\n\n".join(line for line in lines if line).rstrip()+"\n"


def build(run, ledger_path, output, source_commit=None, artificial=False, study=None):
    review, context = assemble(run, ledger_path, source_commit, study=study)
    report = render(context, artificial=artificial)
    output = Path(output)
    require(not output.exists(), "Output directory already exists; preserve prior reports")
    output.mkdir(parents=True)
    review["artificial_fixture"] = artificial
    write_json(output / "ACCEPTANCE_REVIEW.json", review)
    (output / "REPORT_ZH.md").write_text(report)
    return review, report


def fixture_stat(mean, seeds, cluster=False):
    result = dict(mean=mean, fit_values=[mean]*len(seeds), fit_count=len(seeds), fit_df=len(seeds)-1,
                  fit_t95=[mean,mean], positive_fit_count=len(seeds) if mean > 0 else 0,
                  positive_fit_fraction=1. if mean > 0 else 0.)
    if cluster:
        result.update(fit_seeds=seeds, object_count=512, partition_cluster_count=23,
                      fixed_fit_object_cluster95=[mean-.001,mean+.001], bootstrap_replicates=5000, bootstrap_seed=151999)
    return result


def fixture_inputs(root):
    """Generate a complete artificial schema, deliberately actual != replay."""
    run = root / "formal_03"
    seeds = list(range(15131,15139))
    tasks = ["recall","binding"]
    pressure = ["long_distractors","blank_retention","irregular_dt","clock4x","query_swap"]
    families = [ORDINARY,ANALYTIC,"ordinary_dual","analytic_fixed","mamba1","transformer"]
    domains = {"recall":["iid",*pressure,"missing_payload"], "binding":["iid",*pressure,"missing_a","missing_b"]}
    protocol = dict(tasks=tasks,seeds=seeds,families=families,domains=domains,modes=["light","value"],
                    baseline_sha="c0949e9cde89a54609a5133c0fb7f9c65bc80f4a", splits={"test":[512,151103]},
                    acceptance=dict(minimum_iid_accuracy=.7,primary_lower95=0.,minimum_positive_seed_fraction=.75,
                        pressure_tolerance=-.02,pressure_domains=pressure,required_tasks=tasks,full_cost_advantage_required=True))
    write_json(run/"PROTOCOL.json",protocol)
    write_json(run/"SOURCE_FREEZE.json",dict(protocol_sha256=digest(run/"PROTOCOL.json"),files={"artificial_source.py":"0"*64},heldout_opened=False))
    write_json(root/"formal_02/SOURCE_FREEZE.json",json.loads((run/"SOURCE_FREEZE.json").read_text()))
    write_json(run/"full_online_confirmation/SELF_REGISTRATION.json",dict(parent_source_freeze_sha256=digest(run/"SOURCE_FREEZE.json"),parent_protocol_sha256=digest(run/"PROTOCOL.json"),confirmation_opened_at_registration=False,batch_size=32))
    effects, conditional, selected, outcomes, cells = [],[],[],[],[]
    replay_effects, replay_conditional, replay_selected, ablations = [],[],[],[]
    coefficients = {"B-A":(-1,1,0,0),"D-C":(0,0,-1,1),"C-A":(-1,0,1,0),"D-B":(0,-1,0,1),"interaction":(1,-1,-1,1)}
    for task in tasks:
        for domain in domains[task]:
            base = .50 if domain.startswith("missing") else .76
            d_gain = -.03 if (task,domain)==("binding","clock4x") else .02
            means = [base,base+.04,base+.03,base+.04+d_gain]
            fees = [.02,.03,.02,.03]
            details = dict(task=task,domain=domain,fit_seeds=seeds,object_count=512,partition_cluster_count=23,negative_control=domain.startswith("missing"))
            cell = dict(**details,cells={})
            for index,(letter,arm) in enumerate(ARMS.items()):
                metric = dict(accuracy=means[index],fee=fees[index],utility=means[index]-fees[index],read_count=7. if index%2==0 else 5.,initial_stop=0. if index%2==0 else .05)
                cell["cells"][letter] = dict(family=arm[0],train_mode=arm[1],exec_mode=arm[2],metrics={name:fixture_stat(value,seeds) for name,value in metric.items()})
            cells.append(cell)
            current_outcomes = {}
            for family,mode,execution in itertools.product(families,["light","value"],["light","value"]):
                if mode=="light" and execution=="value": continue
                match = next((letter for letter,identity in ARMS.items() if identity==(family,mode,execution)),None)
                metrics = copy.deepcopy(cell["cells"][match]["metrics"]) if match else {name:fixture_stat(value,seeds) for name,value in dict(accuracy=base+.08,fee=.03,utility=base+.05,read_count=5.,initial_stop=.05).items()}
                outcomes.append(dict(task=task,domain=domain,fit_seeds=seeds,object_count=512,family=family,train_mode=mode,exec_mode=execution,metrics=metrics))
                current_outcomes[(family,mode,execution)] = metrics
            same_weights = [current_outcomes[(ORDINARY,"value","light")],cell["cells"]["B"]["metrics"],
                            current_outcomes[(ANALYTIC,"value","light")],cell["cells"]["D"]["metrics"]]
            replay_arms = [cell["cells"][letter]["metrics"]["utility"]["mean"]+offset
                           for letter,offset in zip(ARMS,(.01,.04,-.01,0.))]
            replay_same_weights = [same_weights[0]["utility"]["mean"]+.015,replay_arms[1],
                                   same_weights[2]["utility"]["mean"]-.005,replay_arms[3]]
            for contrast,coef in coefficients.items():
                metrics = {name:fixture_stat(math.fsum(c*cell["cells"][letter]["metrics"][name]["mean"] for c,letter in zip(coef,ARMS)),seeds) for name in METRICS}
                effects.append(dict(**details,contrast=contrast,metrics=metrics))
                conditional.append(dict(**details,contrast=contrast,metrics={name:fixture_stat(math.fsum(c*arm[name]["mean"] for c,arm in zip(coef,same_weights)),seeds) for name in METRICS}))
                replay_effects.append(dict(task=task,domain=domain,contrast=contrast,**fixture_stat(math.fsum(c*value for c,value in zip(coef,replay_arms)),seeds,True)))
                replay_conditional.append(dict(task=task,domain=domain,contrast=contrast,**fixture_stat(math.fsum(c*value for c,value in zip(coef,replay_same_weights)),seeds,True)))
            chosen = {str(seed):"ordinary_dual" for seed in seeds}
            selected_metrics = {name:fixture_stat(cell["cells"]["D"]["metrics"][name]["mean"]-current_outcomes[("ordinary_dual","value","value")][name]["mean"],seeds) for name in METRICS}
            selected.append(dict(**details,selected_families=chosen,metrics=selected_metrics))
            replay_selected.append(dict(task=task,domain=domain,selected_families=chosen,**fixture_stat(selected_metrics["utility"]["mean"]-.04,seeds,True)))
            for ablation in ("content_independence","mean_position","readout_independence"):
                ablations.append(dict(task=task,domain=domain,contrast="full_minus_"+ablation,**fixture_stat(.005,seeds,True)))
    mismatch = dict(task="recall",seed=seeds[0],family=ANALYTIC,train_mode="value",exec_mode="value",domain="iid",alignment={name:dict(mismatches=count,maximum_absolute_difference=1. if name in ("prediction","read_count") else .01,tolerance=0. if name in ("prediction","read_count") else 3e-6) for name,count in (("prediction",2),("read_count",1),("fee",1),("utility",2),("elapsed",1))})
    mismatch["alignment"]["aligned"]=False
    online = dict(schema="hcsn.r15.full-online-supplement.summary.v1",conditions=2160,expected_conditions=2160,object_executions=1105920,expected_object_executions=1105920,
        all_conditions_aligned=False,mismatch_conditions=[mismatch],group_cpu_seconds=120.,nested_actor_cpu_seconds=100.,actual_reads=10000,processed_prefix_tokens=50000,model_calls=1000,controller_batch_calls=800,
        process_receipt=dict(process_cpu_seconds=320.,stage="full_online_confirmation",jobs=32,failed=0),
        actual_outcome_analysis=dict(outcomes=outcomes,primary_four_cells=cells,total_effects=effects,conditional_execution_effects=conditional,validation_selected_comparator=selected))
    write_json(run/"FULL_ONLINE_CONFIRMATION_SUMMARY.json",online)
    cross_source = "b"*64
    cross_registration = dict(schema="hcsn.r15.train-execution-cross.registration.v1", source_sha256=cross_source,
        parent_source_freeze_sha256=digest(run/"SOURCE_FREEZE.json"), parent_protocol_sha256=digest(run/"PROTOCOL.json"),
        parent_online_registration_sha256=digest(run/"full_online_confirmation/SELF_REGISTRATION.json"),
        confirmation_opened_at_registration=False, batch_size=32)
    write_json(run/"train_execution_cross/SELF_REGISTRATION.json",cross_registration)
    original_outcomes = keyed(outcomes,("task","domain","family","train_mode","exec_mode"),"fixture original outcomes")
    cross_families,cross_cores = [],[]
    cross_coefficients = {"training_given_light":(-1,0,1,0), "training_given_value":(0,-1,0,1),
        "execution_given_light":(-1,1,0,0), "execution_given_value":(0,0,-1,1), "interaction":(1,-1,-1,1)}
    cross_contrasts = {"training_given_light":"VL-LL", "training_given_value":"VV-LV",
        "execution_given_light":"LV-LL", "execution_given_value":"VV-VL", "interaction":"VV-LV-VL+LL"}
    for task in tasks:
        for domain in domains[task]:
            current = {}
            for family in (ORDINARY,ANALYTIC):
                cross_cells = {}
                for cell in CROSS_CELLS:
                    mode = "light" if cell[0]=="L" else "value"
                    execution = "light" if cell[1]=="L" else "value"
                    if cell=="LV":
                        reference = original_outcomes[(task,domain,family,"light","light")]["metrics"]
                        offsets = dict(accuracy=.005,fee=.001,utility=.004,read_count=-.5,initial_stop=.03)
                        cell_metrics = {metric:fixture_stat(reference[metric]["mean"]+offsets[metric],seeds) for metric in METRICS}
                    else:
                        cell_metrics = copy.deepcopy(original_outcomes[(task,domain,family,mode,execution)]["metrics"])
                    cross_cells[cell] = dict(train_mode=mode,exec_mode=execution,metrics=cell_metrics)
                cross_effects = {name:dict(contrast=cross_contrasts[name],metrics={metric:fixture_stat(math.fsum(coef*cross_cells[cell]["metrics"][metric]["mean"] for coef,cell in zip(coefficients,CROSS_CELLS)),seeds) for metric in METRICS}) for name,coefficients in cross_coefficients.items()}
                current[family] = cross_cells
                cross_families.append(dict(task=task,domain=domain,family=family,fit_seeds=seeds,object_count=512,partition_cluster_count=23,negative_control=domain.startswith("missing"),cells=cross_cells,effects=cross_effects))
            for cell in CROSS_CELLS:
                cross_cores.append(dict(task=task,domain=domain,cell=cell,fit_seeds=seeds,contrast="analytic_distribution-ordinary_distribution",negative_control=domain.startswith("missing"),metrics={metric:fixture_stat(current[ANALYTIC][cell]["metrics"][metric]["mean"]-current[ORDINARY][cell]["metrics"][metric]["mean"],seeds) for metric in METRICS}))
    cross = dict(schema="hcsn.r15.train-execution-cross.summary.v1",registration_sha256=digest(run/"train_execution_cross/SELF_REGISTRATION.json"),source_sha256=cross_source,
        coverage=dict(expected_conditions=240,conditions=240,expected_object_executions=122880,object_executions=122880,all_conditions_present=True),
        controller_policy="Artificial fixture: unchanged value-group controller, no recalibration", training_scope="Artificial joint-program fixture",
        families=cross_families,core_differences=cross_cores,resources=dict(group_cpu_seconds=60.,nested_actor_cpu_seconds=50.,actual_reads=1000,processed_prefix_tokens=5000,model_calls=100,controller_batch_calls=80,process_receipt=dict(stage="train_execution_cross",jobs=16,failed=0,process_cpu_seconds=160.)),
        existing_primary_contrasts_unchanged=True,no_new_selection_or_acceptance_gate=True,foundation_core_acceptance=False,all_user_requirements_closed=False)
    write_json(run/"TRAIN_EXECUTION_CROSS_SUMMARY.json",cross)
    routcomes,reffects,sensitivity,actors,records = [],[],[],[],[]
    for task,domain,cohort,family in itertools.product(tasks,("iid","long_distractors"),("none","sign","zero"),(ORDINARY,ANALYTIC)):
        details = dict(task=task,domain=domain,cohort=cohort,family=family)
        faulty = cohort!="none"
        accuracy,fee,base_accuracy = (.78,.07,.6) if faulty else (.8,.052,.8)
        arms = {name:dict(accuracy=a,fee=f,utility=a-f,prediction_changes_vs_none=10 if name!="none" else 0) for name,a,f in (("none",base_accuracy,.052),("reset_only",.55,.062),("replay_only",.65,.064),("reset_replay",.78,.07))}
        selected_utility = accuracy-fee
        gain = selected_utility-(base_accuracy-.052)
        values = dict(selected_minus_protected_none=gain,selected_minus_unprotected_none=selected_utility-(base_accuracy-.05),reset_replay_minus_none=arms["reset_replay"]["utility"]-arms["none"]["utility"],reset_replay_interaction=arms["reset_replay"]["utility"]-arms["reset_only"]["utility"]-arms["replay_only"]["utility"]+arms["none"]["utility"])
        routcomes.append(dict(**details,selected_utility=fixture_stat(selected_utility,seeds),selected_accuracy=fixture_stat(accuracy,seeds),selected_fee=fixture_stat(fee,seeds),clean_accuracy=fixture_stat(.8,seeds),alarm_fraction=.5 if faulty else 0.,action_counts_by_fit={str(seed):[256,0,0,256] if faulty else [512,0,0,0] for seed in seeds}))
        reffects.extend(dict(**details,contrast=name,**fixture_stat(value,seeds,True)) for name,value in values.items())
        sensitivity.append(dict(**details,fixed_policy=True,values=[dict(incremental_price_multiplier=m,gain_vs_unprotected_none=fixture_stat(accuracy-base_accuracy-m*(fee-.05),seeds)) for m in (0.,.5,1.,2.,4.)]))
        for seed in seeds:
            actors.append(dict(**details,seed=seed,cpu_seconds=.1,wall_seconds=.2,episodes=512,prediction_mismatches=0,action_mismatches=0))
            records.append(dict(**details,seed=seed,summary=dict(episodes=512,alarms=256 if faulty else 0,clean_accuracy=.8,arms=arms)))
    write_json(run/"recovery/CONFIRMATION_INDEX.json",dict(records=records))
    pairs = [dict(task=task,seed=seed,identical_initialization=True,separate_checkpoint_paths=True,selected_hashes_equal={f:(task=="recall" and seed==seeds[0] and f==ORDINARY) for f in families},final_hashes_equal={f:False for f in families},selected_steps=dict(light=128,value=256),selected_checkpoint_sha256=dict(light="1"*64,value="2"*64),final_checkpoint_sha256=dict(light="3"*64,value="4"*64)) for task,seed in itertools.product(tasks,seeds)]
    posterior = dict(upper_loss_limit=1e-7,evidence_complete=True,finite_diagnostics=True,metadata_consistent=True,registered_continuous_tail_qualification_pass=True,confirmation_all_prefix_upper_loss_pass=True,confirmation_occupied_upper_loss_pass=True,maximum_validation_upper_loss=5e-10,maximum_confirmation_upper_loss=2e-9,maximum_occupied_confirmation_upper_loss=1e-9,maximum_reported_mass_error=3e-14,minimum_reported_probability=0.,original_full_successor_requirement_closed=False)
    summary = dict(source_protocol_sha256=digest(run/"PROTOCOL.json"),total_effects=replay_effects,conditional_execution_effects=replay_conditional,validation_selected_comparator=replay_selected,distribution_ablations=ablations,
        recovery=dict(available=True,outcomes=routcomes,effects=reffects,sensitivities=sensitivity,actual_execution_records=actors,actual_execution_mismatches=0),posterior_qualification=posterior,
        resources=dict(independent_training_pairs=pairs,training_body_cpu_seconds_total=99999.,full_cost_advantage_established=False),
        acceptance=dict(registered_quality_effect_pressure_gate_pass=False,foundation_core_acceptance=False,all_user_requirements_closed=False))
    write_json(run/"SUMMARY.json",summary)
    write_json(run/"INDEPENDENT_AUDIT.json",dict(schema="hcsn-r15.independent-audit.v1",run=str(run),passed=True,checks=42,failures=[],notes=["Artificial records only"]))
    stage_rows = []
    for stage in STAGES:
        jobs = 16 if stage.startswith("recovery_") or stage=="train_execution_cross" else 32
        stage_rows.append(dict(stage=stage,expected_jobs=jobs,recorded_jobs=jobs,failed_jobs=0,coverage="complete",observed_worker_cpu_seconds=10.*jobs,successful_completed_worker_cpu_seconds=10.*jobs,failed_completed_worker_cpu_seconds=0.,elapsed_wall_seconds=8.*jobs,maximum_individual_worker_rss_kib=100000.,launcher_total=dict(workers=2)))
    total = math.fsum(row["observed_worker_cpu_seconds"] for row in stage_rows)
    stage_rows[0].update(original_launcher_completed=False,accounting_kind="resumed_consolidated",
        wall_scope="elapsed_since_original_restart_including_interruption_and_resume",
        status="canonical_jobs_complete_after_operational_recovery")
    enospc = dict(original_launcher_completed=False,same_scientific_freeze_and_contexts=True,
        retained_original_success_count=13,resumed_success_count=19,canonical_success_count=32,
        unknown_process_attempts=[dict(process_attempt_id="formal03/train_original/"+name,cpu_seconds=None,measurement_status="not_measured") for name in ("recall_s15137_value","recall_s15138_light")],
        unknown_process_attempt_count=2,missing_process_cpu_seconds=None,
        additional_measured_processes=[dict(process_attempt_id="train_resume_001/recall_s15137_value",cpu_seconds=7.,exit_code=1,measurement_status="complete_process_lifetime_wait4")],
        additional_observed_cpu_addends=[7.],additional_complete_wait4_cpu_seconds=7.,
        additional_partial_cpu_lower_bound_seconds=None,additional_observed_cpu_lower_bound_seconds=7.)
    ledger = dict(schema="hcsn.r15.publication.runtime-ledger.v3",result_root=str(root),formal_run="formal_03",formal_stage_receipts_complete=True,formal_03_stages=stage_rows,
        enospc_training_recovery=enospc,
        totals=dict(status="lower_bound",formal_03_successful_completed_process_cpu_seconds=total,formal_03_failed_completed_process_cpu_seconds=0.,formal_03_observed_completed_process_cpu_seconds=total,abandoned_attempt_complete_wait4_cpu_seconds=5.,abandoned_attempt_interrupted_process_cpu_lower_bound_seconds=7.,abandoned_attempt_cpu_lower_bound_seconds=12.,
            enospc_additional_complete_wait4_cpu_seconds=7.,enospc_additional_partial_cpu_lower_bound_seconds=None,enospc_additional_observed_cpu_lower_bound_seconds=7.,enospc_unknown_process_attempt_count=2,enospc_unknown_process_cpu_seconds=None,
            successful_failed_and_abandoned_cpu_lower_bound_seconds=total+19.,hours_lower_bound=(total+19.)/3600),
        unmeasured=dict(gpu="not_measured",physical_energy_joules="not_measured",provider_bill="not_measured"))
    write_json(root/"RUNTIME_LEDGER.json",ledger)
    study = root/"study"
    numerical_rows = []
    for profile,upper,base in (("tail_half_upper40",40.,.00046),("tail_quarter_upper40",40.,.00045),("tail_half_upper60",60.,.00040)):
        for index,horizon in enumerate((.25,1.,1.75,4.)):
            errors = dict(first_hit=base+index*.00001,expected_count=.0006+index*.00001,
                          count_pmf_l1=.0009+index*.00001,active_bins_l1=.0015+index*.00001)
            numerical_rows.append(dict(profile=profile,horizon=horizon,config={**PHYSICAL_INITIAL,"tail_upper":upper},
                                       errors=errors,limits=NUMERICAL_LIMITS,passed=True))
    write_json(study/"tail_numerics_03.json",dict(rows=numerical_rows,passed=True,checks=[],scope="Artificial fixed-initial-atom fixture"))
    write_json(study/"law_tail_final_checks_01.json",dict(schema="hcsn-r15.finite-law-checks.v1",count=157,
        config=PHYSICAL_INITIAL,checks=[dict(passed=True)]*157,passed=True,failed=[],continuous_model_acceptance=False,scope="Artificial finite-law fixture"))
    write_json(study/"tail_independent_review_qualified.json",dict(schema="hcsn.r15.independent-tail-review.v1",
        checks=[dict(passed=True)]*106,passed=True,positions=240,upper=40.,confirmation_data_accessed=False,scope="Artificial upper40 structural-only fixture"))
    return run,root/"RUNTIME_LEDGER.json"


def selfcheck(output):
    output = Path(output)
    require(not output.exists(), "Selfcheck output already exists")
    root = Path(tempfile.mkdtemp(prefix="hcsn-report-artificial-"))
    run,ledger = fixture_inputs(root)
    study = root/"study"
    review,report = build(run,ledger,output,source_commit="a"*40,artificial=True,study=study)
    checks = dict(actual_estimate_not_replay=close(review["actual_acceptance"]["per_task"]["recall"]["iid_D_minus_B"]["mean"],.02),
        pressure_failure_retained=not review["actual_acceptance"]["per_task"]["binding"]["pressure_pass"],
        all_global_claims_stay_false=not any(review[name] for name in ("foundation_core_acceptance","all_user_requirements_closed","full_cost_advantage_established")),
        no_negative_control_in_pressure_gate="missing_a" not in review["actual_acceptance"]["per_task"]["binding"]["pressure_D_minus_B_means"],
        replay_difference_retained=review["runtime_alignment"]["mismatch_condition_count"]==1 and review["runtime_alignment"]["totals"]["read_count"]["mismatches"]==1,
        replay_tail_not_transferred=review["actual_online_direct_state_tail_qualification"]["status"]==UNAVAILABLE,
        full_runtime_not_nested_body_sum=review["runtime"]["ledger"]["totals"]["successful_failed_and_abandoned_cpu_lower_bound_seconds"]==1459.,
        same_selected_weights_do_not_cancel_independent_training=review["training_resources"]["independent_training_pairs"][0]["selected_hashes_equal"][ORDINARY],
        four_arm_existing_records_retained=len(review["recovery"]["four_arms"]["rows"])==192,
        no_fault_cost_is_negative=review["recovery"]["frozen_summary"]["effects"][1]["mean"] < 0,
        candidate_explicitly_artificial="人工 fixture 候选报告" in report and review["artificial_fixture"],
        source_commit_not_self_reference=review["source_commit"]=="a"*40)
    checks["canonical_success_does_not_claim_all_history_succeeded"] = review["runtime"]["every_canonical_formal_worker_successful"] and not review["runtime"]["all_process_attempts_successful"] and not review["runtime"]["original_training_launcher_completed"]
    checks["enospc_retained13_resumed19_unknown2_in_report"] = "13 个旧成功与 19 个恢复成功" in report and "2 个已记录未知 attempt" in report and "含中断span" in report
    ledger_original=ledger.read_text();changed_ledger=json.loads(ledger_original)
    changed_ledger["schema"]="hcsn.r15.publication.runtime-ledger.v2";ledger.write_text(json.dumps(changed_ledger))
    try:assemble(run,ledger,study=study)
    except ReportError:checks["v2_cannot_omit_known_enospc_history"]=True
    else:checks["v2_cannot_omit_known_enospc_history"]=False
    ledger.write_text(ledger_original)
    changed_ledger=json.loads(ledger_original)
    changed_ledger["enospc_training_recovery"]["unknown_process_attempts"][0]["cpu_seconds"]=0.
    ledger.write_text(json.dumps(changed_ledger))
    try:assemble(run,ledger,study=study)
    except ReportError:checks["unknown_enospc_cpu_zero_fill_rejected"]=True
    else:checks["unknown_enospc_cpu_zero_fill_rejected"]=False
    ledger.write_text(ledger_original)
    changed_ledger=json.loads(ledger_original)
    changed_ledger["enospc_training_recovery"].update(additional_measured_processes=[],additional_observed_cpu_addends=[],
        additional_complete_wait4_cpu_seconds=None,additional_partial_cpu_lower_bound_seconds=None,additional_observed_cpu_lower_bound_seconds=None)
    changed_ledger["totals"].update(enospc_additional_complete_wait4_cpu_seconds=None,enospc_additional_partial_cpu_lower_bound_seconds=None,
        enospc_additional_observed_cpu_lower_bound_seconds=None,successful_failed_and_abandoned_cpu_lower_bound_seconds=1452.,hours_lower_bound=1452./3600)
    ledger.write_text(json.dumps(changed_ledger));limited,_=assemble(run,ledger,study=study)
    checks["no_extra_measured_receipt_is_null_not_an_invented_zero"] = limited["runtime"]["ledger"]["totals"]["enospc_additional_observed_cpu_lower_bound_seconds"] is None
    ledger.write_text(ledger_original)
    _, boundary_context = assemble(run,ledger,study=study)
    boundary_tables = copy.deepcopy(boundary_context["actual"])
    for task in ("recall","binding"):
        for letter in ARMS:
            boundary_tables["cells"][(task,"iid")]["cells"][letter]["metrics"]["accuracy"]["mean"] = .7
        primary = boundary_tables["effects"][(task,"iid","D-B")]["metrics"]["utility"]
        primary["fit_t95"] = [.0001,.1]
        primary["positive_fit_fraction"] = .75
        for domain in boundary_context["protocol"]["acceptance"]["pressure_domains"]:
            boundary_tables["effects"][(task,domain,"D-B")]["metrics"]["utility"]["mean"] = -.02
    checks["inclusive_quality_positive_fraction_and_pressure_boundaries"] = gates(boundary_context["protocol"],boundary_tables)["registered_quality_effect_pressure_gate_pass"]
    boundary_tables["effects"][("recall","iid","D-B")]["metrics"]["utility"]["fit_t95"][0] = 0.
    checks["zero_lower_confidence_bound_fails_strict_gate"] = not gates(boundary_context["protocol"],boundary_tables)["registered_quality_effect_pressure_gate_pass"]
    checks["small_nonzero_diagnostics_not_printed_as_zero"] = "e-14" in fnum(3e-14,12)
    checks["restart_freeze_compared_from_metadata"] = review["restart_freeze_identity"]["same_registered_source_and_protocol"]
    checks["cross_240_new_conditions_not_pooled_with_original_2160"] = review["train_execution_cross"]["summary"]["coverage"]["conditions"]==240 and review["runtime"]["whole_cohort_actual"]["conditions"]==2160
    checks["cross_control_origin_and_no_new_gate_retained"] = review["train_execution_cross"]["no_new_primary_gate"] and review["train_execution_cross"]["original_registered_acceptance_unchanged"]
    checks["sixth_stage_added_once"] = len(review["runtime"]["ledger"]["formal_03_stages"])==6 and review["train_execution_cross"]["summary"]["resources"]["process_receipt"]["process_cpu_seconds"]==160.
    cross_path=run/"TRAIN_EXECUTION_CROSS_SUMMARY.json"
    cross_original=cross_path.read_text(); bad_cross=json.loads(cross_original)
    bad_cross["families"][0]["cells"]["LL"]["metrics"]["utility"] = fixture_stat(.123,boundary_context["protocol"]["seeds"])
    cross_path.write_text(json.dumps(bad_cross))
    try: assemble(run,ledger,study=study)
    except ReportError: checks["cross_reused_cell_mismatch_rejected"]=True
    else: checks["cross_reused_cell_mismatch_rejected"]=False
    cross_path.write_text(cross_original)
    qualification=review["numerical_qualification"]
    checks["formal60_profile_only_maximum_not_all_profiles"] = close(qualification["continuous_reference"]["metrics"]["first_hit"]["maximum_error"],.00043)
    checks["law_count_and_independent_upper40_kept_distinct"] = qualification["finite_law_checks"]["count"]==157 and qualification["independent_structural_review"]["upper"]==40. and not qualification["independent_structural_review"]["formal60_independent_numerical_certificate"]
    numeric_path=study/"tail_numerics_03.json"
    numeric_original=numeric_path.read_text(); numeric_path.unlink()
    limited,_=assemble(run,ledger,study=study)
    checks["optional_numerical_reference_missing_not_zero"] = not limited["numerical_qualification"]["continuous_reference"]["available"]
    numeric_path.write_text(numeric_original)
    online_path=run/"FULL_ONLINE_CONFIRMATION_SUMMARY.json"
    original=online_path.read_text()
    changed=json.loads(original)
    item=next(row for row in changed["actual_outcome_analysis"]["conditional_execution_effects"] if row["contrast"]=="D-B")
    item["metrics"]["utility"] = fixture_stat(item["metrics"]["utility"]["mean"]+2e-12,boundary_context["protocol"]["seeds"])
    online_path.write_text(json.dumps(changed))
    try: assemble(run,ledger,study=study)
    except ReportError: checks["actual_D_B_total_conditional_inequality_rejected"]=True
    else: checks["actual_D_B_total_conditional_inequality_rejected"]=False
    online_path.write_text(original)
    changed=json.loads(original)
    item=next(row for row in changed["actual_outcome_analysis"]["conditional_execution_effects"] if row["contrast"]=="D-B")
    item["metrics"]["utility"] = fixture_stat(item["metrics"]["utility"]["mean"]+5e-13,boundary_context["protocol"]["seeds"])
    online_path.write_text(json.dumps(changed))
    within_tolerance,_=assemble(run,ledger,study=study)
    checks["actual_D_B_equality_absolute_1e_minus_12_tolerance"] = within_tolerance["actual_D_minus_B_identity_check"]["passed"] and within_tolerance["actual_D_minus_B_identity_check"]["absolute_tolerance"]==1e-12
    online_path.write_text(original)
    broken=json.loads(original)
    del broken["actual_outcome_analysis"]["primary_four_cells"][0]["cells"]["D"]["metrics"]["fee"]
    online_path.write_text(json.dumps(broken))
    try: assemble(run,ledger,study=study)
    except ReportError: checks["required_stat_missing_errors"]=True
    else: checks["required_stat_missing_errors"]=False
    online_path.write_text(original)
    recovery_path=run/"recovery/CONFIRMATION_INDEX.json"
    recovery_original=recovery_path.read_text(); recovery_path.unlink()
    limited,_=assemble(run,ledger,study=study)
    checks["optional_arm_summary_not_zero_filled"]=not limited["recovery"]["four_arms"]["available"] and "recovery_four_arm_absolute_outcomes" in limited["unavailable_sections"]
    recovery_path.write_text(recovery_original)
    summary_path=run/"SUMMARY.json"
    summary=json.loads(summary_path.read_text()); original_summary=summary_path.read_text()
    del summary["posterior_qualification"]; summary_path.write_text(json.dumps(summary))
    limited,_=assemble(run,ledger,study=study)
    checks["missing_posterior_explicitly_unavailable"]=limited["posterior_qualification"]["status"]==UNAVAILABLE
    summary_path.write_text(original_summary)
    changed=json.loads(original)
    changed["expected_conditions"]-=1; online_path.write_text(json.dumps(changed))
    try: assemble(run,ledger,study=study)
    except ReportError: checks["incomplete_whole_cohort_refused"]=True
    else: checks["incomplete_whole_cohort_refused"]=False
    online_path.write_text(original)
    result=dict(schema="hcsn.r15.publication.report-fixture.v1",source_sha256=digest(SOURCE),fixture_root=str(root),
                report_directory=str(output.resolve()),checks=checks,passed=all(checks.values()),
                real_runtime_records_read=False,confirmation_data_accessed=False,raw_npz_or_checkpoints_loaded=False)
    write_json(output/"SELFCHECK.json",result)
    require(result["passed"], "Artificial report fixture failed")
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("build","selfcheck"))
    parser.add_argument("--run",type=Path)
    parser.add_argument("--runtime-ledger",type=Path)
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--source-commit")
    parser.add_argument("--study",type=Path,help="Optional study directory for retained numerical JSON checks; defaults to RUN/../..")
    args=parser.parse_args()
    if args.action=="selfcheck":
        result=selfcheck(args.output_dir)
        print(json.dumps(dict(passed=result["passed"],checks=len(result["checks"]),output=str(args.output_dir),confirmation_data_accessed=False)))
    else:
        require(args.run is not None and args.runtime_ledger is not None,"build requires --run and --runtime-ledger")
        result,_=build(args.run,args.runtime_ledger,args.output_dir,args.source_commit,study=args.study)
        print(json.dumps(dict(output=str(args.output_dir),actual_registered_gate=result["actual_acceptance"]["registered_quality_effect_pressure_gate_pass"],foundation_core_acceptance=False,all_user_requirements_closed=False)))


if __name__=="__main__":
    main()
