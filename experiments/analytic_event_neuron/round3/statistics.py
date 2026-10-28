"""Frozen paired whole-trajectory statistics; no adaptive stopping or selection."""

import argparse
import json
from pathlib import Path

import numpy as np

from ..run import digest, write_json
from ..round2.statistics import calibration, paired_interval
from . import freeze


def summarize(run_dir, protocol):
    root = Path(run_dir)
    frozen = freeze.verify(root)
    if protocol != json.loads((freeze.PROJECT / "PROTOCOL.json").read_text()):
        raise ValueError("Summary gates differ from the frozen registration")
    index = json.loads((root / "main" / "RUN_INDEX.json").read_text())
    if index["source_commit"] != frozen["source_commit"]:
        raise ValueError("Summary index differs from the frozen source commit")
    seeds = protocol["training_seeds"]
    laws = [protocol["laws"]["primary"], *protocol["laws"]["mismatch"]]
    expected = {(seed, law) for seed in seeds for law in laws}
    actual = [(x["seed"], x["law"]) for x in index["scopes"]]
    if not index["complete"] or len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("All registered seed/law scopes must complete exactly once")
    loaded = {}
    unique_ids = set()
    for entry in index["scopes"]:
        path = (root / entry["analysis"]).resolve()
        if not path.is_relative_to(root.resolve()) or digest(path) != entry["analysis_sha256"]:
            raise ValueError("Changed analysis artifact")
        if not entry["audit_passed"]:
            raise ValueError("Unaudited scope")
        with np.load(path, allow_pickle=False) as data:
            arrays = {key: data[key].copy() for key in data.files}
        ids = arrays["control_ids__analytic"]
        if len(set(ids)) != len(ids) or unique_ids.intersection(ids):
            raise ValueError("Repeated or overlapping confirmation trajectory identities")
        unique_ids.update(ids)
        loaded[(entry["seed"], entry["law"])] = arrays
    result = {"schema": "hepta.analytic-event.round3.main-results.v1",
        "source_commit": index["source_commit"], "independent_trajectories": len(unique_ids),
        "training_seed_count": len(seeds), "laws": {}, "primary_contrasts": {},
        "secondary_contrasts": {}, "mismatch_contrasts": {},
        "sampling_scope": "Independent trajectory is sampling unit; horizons and model outputs are dependent measurements",
        "interval_scope": "Empirical paired two-stage percentile bootstrap; five fitted seeds, no population guarantee"}
    for law in laws:
        scopes = [loaded[(seed, law)] for seed in seeds]
        arms = sorted(k.split("__", 1)[1] for k in scopes[0] if k.startswith("utility__"))
        metrics = {}
        for arm in arms:
            value = {}
            for metric in ("utility", "squared_error", "paid_cost", "severe_loss", "elapsed_ns", "cpu_ns",
                           "packet_bytes", "packets", "logical_unit_events", "refinement_packets",
                           "precision_rebases", "uncertified_decisions"):
                key = metric + "__" + arm
                if key not in scopes[0]:
                    continue
                a = np.concatenate([scope[key] for scope in scopes])
                if not np.isfinite(a).all():
                    raise ValueError("Nonfinite metric: " + key)
                value[metric] = {"mean": float(a.mean()), "sum": float(a.sum()),
                    "q05": float(np.quantile(a, .05)), "median": float(np.median(a)),
                    "q95": float(np.quantile(a, .95)), "maximum": float(a.max())}
            actions = np.concatenate([scope["actions__" + arm] for scope in scopes])
            names, counts = np.unique(actions, return_counts=True)
            value["actions"] = dict(zip(names.tolist(), counts.tolist()))
            if "nll__" + arm in scopes[0]:
                for metric in ("nll", "brier", "mse"):
                    value[metric] = float(np.concatenate([scope[metric + "__" + arm] for scope in scopes]).mean())
                probabilities = np.concatenate([scope["probabilities__" + arm] for scope in scopes])
                labels = np.concatenate([scope["labels__" + arm] for scope in scopes])
                z = np.concatenate([scope["standardized_error__" + arm] for scope in scopes])
                value["calibration"] = calibration(probabilities, labels)
                value["coverage95"] = float(np.mean(abs(z) <= 1.959963984540054))
                value["prediction_scope"] = "initial public history, before action-specific codec refinement"
            metrics[arm] = value
        result["laws"][law] = metrics
    registered = protocol["statistics"]

    def compare(candidate, baseline, law, number, primary=False):
        differences = []
        for seed in seeds:
            scope = loaded[(seed, law)]
            if not np.array_equal(scope["control_ids__" + candidate], scope["control_ids__" + baseline]):
                raise ValueError("Unpaired comparison")
            differences.append(scope["utility__" + candidate] - scope["utility__" + baseline])
        alpha = registered["family_alpha"] / registered["primary_family_size"] if primary else .05
        value = paired_interval(np.asarray(differences), registered["bootstrap_replicates"],
                                registered["bootstrap_seed"] + number, alpha)
        value.update(candidate=candidate, baseline=baseline, law=law, primary=primary)
        if primary:
            value["passes_registered_superiority"] = bool(
                value["interval"][0] > registered["minimum_useful_net_utility_gain"]
                and min(value["per_seed_mean_difference"]) > 0)
        else:
            value["descriptive_only"] = True
        return value

    names = ("analytic_vs_history", "analytic_vs_native", "event_vs_continuous")
    for i, (name, pair) in enumerate(zip(names, registered["primary_contrasts"])):
        candidate, baseline = pair
        result["primary_contrasts"][name] = compare(candidate, baseline, "gaussian", i, True)
        for offset, law in enumerate(laws[1:], 1):
            item = compare(candidate, baseline, law, 100 * offset + i)
            item["empirical_lower_above_negative_margin"] = bool(
                item["interval"][0] > -registered["mismatch_descriptive_margin"])
            item["population_noninferiority_established"] = False
            if law == "student_t":
                item["limitation"] = "Student-t(4) lacks a fourth moment; squared-loss bootstrap coverage is not guaranteed"
            result["mismatch_contrasts"][law + ":" + name] = item
    for i, pair in enumerate(protocol["secondary_contrasts"]):
        candidate, baseline = pair
        result["secondary_contrasts"][candidate + "_vs_" + baseline] = compare(candidate, baseline, "gaussian", 1000 + i)
    event = result["primary_contrasts"]["event_vs_continuous"]
    margin = registered["event_utility_noninferiority_margin"]
    result["event_noninferiority"] = {
        "margin": margin, "same_adjusted_interval_as_primary": True,
        "passes_empirical_noninferiority": bool(event["interval"][0] > -margin
            and min(event["per_seed_mean_difference"]) > -margin),
        "original_superiority_gate_unchanged": True}
    equality = {}
    for law in laws:
        scopes = [loaded[(seed, law)] for seed in seeds]
        entry = {}
        for a, b, label in (("event_adaptive", "event_direct", "direct_control"),
                            ("analytic", "equivalent_gaussian", "gaussian_control")):
            numeric, actions = 0.0, 0
            for scope in scopes:
                for metric in ("probabilities", "utility", "paid_cost", "squared_error"):
                    numeric = max(numeric, float(np.max(abs(scope[metric + "__" + a] - scope[metric + "__" + b]))))
                actions += int(np.count_nonzero(scope["actions__" + a] != scope["actions__" + b]))
            entry[label] = {"maximum_numeric_difference": numeric, "action_disagreements": actions,
                            "exact": numeric == 0.0 and actions == 0}
        entry["event_vs_analytic_action_disagreements"] = sum(int(np.count_nonzero(
            scope["actions__event_adaptive"] != scope["actions__analytic"])) for scope in scopes)
        entry["squared_error_reduction"] = float(np.mean(np.concatenate([
            scope["squared_error__analytic"] - scope["squared_error__event_adaptive"] for scope in scopes])))
        entry["paid_cost_increase"] = float(np.mean(np.concatenate([
            scope["paid_cost__event_adaptive"] - scope["paid_cost__analytic"] for scope in scopes])))
        entry["net_utility_difference"] = entry["squared_error_reduction"] - entry["paid_cost_increase"]
        equality[law] = entry
    result["mechanism_controls"] = equality
    result["production_promotion"] = False
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    arguments = parser.parse_args()
    protocol = json.loads(Path(__file__).with_name("PROTOCOL.json").read_text())
    result = summarize(arguments.run_dir, protocol)
    write_json(arguments.run_dir / "MAIN_RESULTS.json", result)
    print(json.dumps({"primary_contrasts": result["primary_contrasts"],
                      "event_noninferiority": result["event_noninferiority"]}))
