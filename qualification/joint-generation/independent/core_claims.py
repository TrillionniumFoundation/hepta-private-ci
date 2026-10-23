"""Pure four-arm, always-full summaries; no dataset, service or training calls."""

from numbers import Integral, Real

import numpy as np


SYSTEMS = ("supervised", "anchor", "additive", "ndu")
METRICS = ("task_utility", "joint_success", "greedy_joint_success", "consistency",
           "pixel_mse", "net_utility", "runtime_net_utility",
           "runtime_cpu_net_utility", "cpu_net_utility")
PRIMARY = ("task_utility", "joint_success", "cpu_net_utility")
CONTRASTS = (("additive", "anchor"), ("ndu", "additive"))
CPU_METRICS = frozenset(("runtime_cpu_net_utility", "cpu_net_utility"))


def _finite(value, name):
    if (isinstance(value, (bool, np.bool_)) or not isinstance(value, Real)
            or not np.isfinite(value)):
        raise ValueError("finite numeric " + name + " required")
    return float(value)


def _integer(value, name, minimum=0, maximum=100000):
    if (isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral)
            or not minimum <= value <= maximum):
        raise ValueError("bounded integer " + name + " required")
    return int(value)


def _seeds(plan):
    seeds = plan["model_seeds"]
    if not isinstance(seeds, (list, tuple)) or not seeds:
        raise ValueError("nonempty model seeds required")
    result = [_integer(seed, "model seed", maximum=2**63 - 1) for seed in seeds]
    if len(set(result)) != len(result):
        raise ValueError("duplicate model seed")
    return result


def _index(rows, seeds):
    expected = {(system, seed) for system in SYSTEMS for seed in seeds}
    indexed = {}
    if not isinstance(rows, (list, tuple)):
        raise ValueError("system/seed rows required")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("system/seed row mapping required")
        seed = _integer(row.get("seed"), "row seed", maximum=2**63 - 1)
        identity = (row.get("system"), seed)
        if identity not in expected or identity in indexed or row.get("mode") != "full":
            raise ValueError("exact four-arm unique full system/seed identity required")
        if any(row.get(key) is not None for key in (
                "controller_file", "controller_sha256", "controller_type", "controller", "critic", "critic_kind",
                "gain_head_kind", "controller_calibration")):
            raise ValueError("always-full core rows must not carry a critic")
        indexed[identity] = row
    if set(indexed) != expected:
        raise ValueError("missing system/seed")
    return indexed


def _maximum_drop(values, seeds):
    return max(values[(right, seed)] - values[(left, seed)]
               for left, right in CONTRASTS for seed in seeds)


def _measured_seeds(measures, seeds):
    if not isinstance(measures, dict) or set(measures) != set(SYSTEMS):
        raise ValueError("exact four-arm measured identity required")
    canonical = {str(seed): seed for seed in seeds}
    normalized = {}
    for system in SYSTEMS:
        reports = measures[system]
        if not isinstance(reports, dict):
            raise ValueError("measured seed mapping required")
        indexed = {}
        for key, report in reports.items():
            if isinstance(key, str):
                if key not in canonical:
                    raise ValueError("canonical measured seed string required")
                seed = canonical[key]
            else:
                seed = _integer(key, "measured seed", maximum=2**63 - 1)
            if seed not in seeds or seed in indexed:
                raise ValueError("unexpected or aliased measured seed")
            indexed[seed] = report
        if set(indexed) != set(seeds):
            raise ValueError("missing measured seed")
        normalized[system] = indexed
    return normalized


def validation_summary(selected, measures, plan):
    """Raw full-validation contrasts plus final, fully attributed CPU means."""
    seeds = _seeds(plan)
    indexed = _index(selected, seeds)
    measures = _measured_seeds(measures, seeds)
    values, greedy, corruption, violations = {}, {}, True, 0
    for identity, row in indexed.items():
        system, seed = identity
        full = row["validation"]["full"]
        report = measures[system][seed]
        if report.get("mode") != "full":
            raise ValueError("full validation service measurement required")
        violations += _integer(report["budget_violations"], "budget violations", maximum=65536)
        for metric in PRIMARY:
            source = report["means"] if metric == "cpu_net_utility" else full
            values[identity, metric] = _finite(source[metric], metric)
        greedy[identity] = _finite(full["greedy_joint_success"], "greedy success")
        corruption = (_finite(report["decoder_corruption_score_drop"], "corruption drop") > 0
                      and corruption)
    contrasts = {left + "-" + right + ":" + metric: float(np.mean([
        values[(left, seed), metric] - values[(right, seed), metric] for seed in seeds]))
        for left, right in CONTRASTS for metric in PRIMARY}
    return {"contrasts": contrasts, "maximum_greedy_drop": _maximum_drop(greedy, seeds),
            "corruption": bool(corruption), "budget_violations": violations}


def make_claims(rows, plan, source_ids, paired_interval_fn):
    """Report all intervals; require the intersection of exactly six primaries.

    Only ``always_full`` is a service report. An optional ``selected`` alias is
    never a second observation or budget charge. CPU intervals are conditional
    on fixed row-order batch cohorts crossed with the same model seeds.
    """
    seeds = _seeds(plan)
    indexed = _index(rows, seeds)
    sources = np.asarray(source_ids)
    if sources.ndim != 1 or not 1 <= len(sources) <= 65536:
        raise ValueError("bounded one-dimensional source identities required")
    n = len(sources)
    batch = _integer(plan.get("runtime_batch_size", 1), "runtime batch", 1, 64)
    replicates = _integer(plan["bootstrap_replicates"], "bootstrap replicates", 1)
    bootstrap_seed = _integer(plan.get("bootstrap_seed", 77431), "bootstrap seed", maximum=2**63 - 1)
    maximum_allowed = _finite(plan["maximum_greedy_drop"], "maximum greedy drop")
    if maximum_allowed < 0:
        raise ValueError("nonnegative maximum greedy drop required")
    values, greedy, violations, corruption = {}, {}, 0, True
    for identity, row in indexed.items():
        report = row["always_full"]
        if report.get("mode") != "full" or ("selected" in row and row["selected"].get("mode") != "full"):
            raise ValueError("only full core reports or aliases allowed")
        violations += _integer(report["budget_violations"], "budget violations", maximum=65536)
        corruption = (_finite(report["decoder_corruption_score_drop"], "corruption drop") > 0
                      and corruption)
        for metric in METRICS:
            array = np.asarray(report["per_row"][metric], dtype=np.float64)
            mean = _finite(report["means"][metric], metric + " mean")
            if (array.shape != (n,) or not np.isfinite(array).all()
                    or not np.isclose(array.mean(), mean, rtol=1e-12, atol=1e-12)):
                raise ValueError("finite matching per-row metric and mean required: " + metric)
            values[identity, metric] = array
        greedy[identity] = float(values[identity, "greedy_joint_success"].mean())
    cohorts = np.asarray(["cohort:" + str(index // batch) for index in range(n)])

    def interval(left, right, metric):
        cpu = metric in CPU_METRICS
        observed = paired_interval_fn(left, right, cohorts if cpu else sources,
            seeds=seeds, replicates=replicates, bootstrap_seed=bootstrap_seed,
            cluster_kind="fixed_service_batch_cohort" if cpu else "physical_source")
        bounds = observed["ci95"]
        if (len(bounds) != 2 or _finite(bounds[0], "CI lower") > _finite(bounds[1], "CI upper")):
            raise ValueError("ordered finite interval required")
        _finite(observed["mean"], "interval mean")
        return observed

    def array(system, metric):
        return np.stack([values[(system, seed), metric] for seed in seeds])

    comparisons = {left + "_minus_" + right: {
        metric: interval(array(left, metric), array(right, metric), metric) for metric in METRICS}
        for left, right in (*CONTRASTS, ("ndu", "supervised"))}
    system_intervals = {system: {metric: interval(array(system, metric),
        np.zeros((len(seeds), n)), metric) for metric in METRICS} for system in SYSTEMS}
    primary = {left + "_minus_" + right + ":" + metric:
        bool(comparisons[left + "_minus_" + right][metric]["ci95"][0] > 0)
        for left, right in CONTRASTS for metric in PRIMARY}
    maximum_drop = _maximum_drop(greedy, seeds)
    gates = {"core_conjunction": all(primary.values()), "primary_intervals": primary,
        "greedy_retention": maximum_drop <= maximum_allowed, "maximum_greedy_drop": maximum_drop,
        "budget_violations": violations, "decoder_corruption_reduces_score": bool(corruption),
        "all_seeds_reported": True}
    verified = (gates["core_conjunction"] and gates["greedy_retention"]
                and violations == 0 and corruption)
    return {"comparisons": comparisons, "system_intervals": system_intervals,
            "gates": gates, "benefit_verified": bool(verified)}
