"""Frozen paired analysis of actual selected-action output observations.

Intervals resample disjoint source-image pairs, keeping their conditions,
historical models, and arms together. They are conditional on three fixed
models, not uncertainty over newly trained models or new datasets. Percentile
bootstrap intervals are approximate; no finite-sample coverage is asserted.
Only NumPy and the frozen protocol are used; this module cannot run a model.
"""

from collections import defaultdict
import json
import math
from numbers import Integral, Real

import numpy as np

from .protocol import P


OBSERVERS = ("reward", "audit")
METRIC_WEIGHTS = {"text_fact": .30, "relation": .15, "image_fact": .35,
                  "crossmodal_disagreement": .10, "pixel_mse": .10}
RETENTION_ARMS = ("B_ordinary_fixed", "C_field_fixed", "D_frozen_native",
                  "E_field_native", "F_field_history", "G_ordinary_native",
                  "H_frozen_history", "J_generic_fixed", "K_richer_fixed")
BASELINE = "A_frozen_fixed"


def _finite(value, label):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite real number")
    return float(value)


def _score(row, observer):
    score = row[observer]
    values = {key: _finite(score[key], f"{observer}.{key}")
              for key in (*METRIC_WEIGHTS, "joint_loss", "utility")}
    if any(not -1e-8 <= values[key] <= 1 + 1e-8
           for key in (*METRIC_WEIGHTS, "joint_loss")):
        raise ValueError("Observed error component is outside the registered [0,1] range")
    joint = sum(METRIC_WEIGHTS[key] * values[key] for key in METRIC_WEIGHTS)
    if (abs(joint - values["joint_loss"]) > 1e-8
            or abs(1 - 2 * joint - values["utility"]) > 1e-8
            or type(score["caption_valid"]) is not bool):
        raise ValueError("Hard-output score does not match the frozen observation formula")
    return values["utility"] - P["refinement_charge"] * row["refinement_count"]


def _tables(rows):
    arms = {**P["canonical_arms"], **P["supplementary_arms"]}
    settings = {"test": (P["test_pairs"], P["test_conditions"]),
                "retention": (P["retention_pairs"], P["retention_conditions"])}
    result = {split: {observer: {arm: np.full((len(P["seeds"]), count, len(conditions)), np.nan)
                                for arm in arms} for observer in OBSERVERS}
              for split, (count, conditions) in settings.items()}
    actions = {split: {arm: np.full((len(P["seeds"]), count, len(conditions)), -1, dtype=np.int64)
                       for arm in arms} for split, (count, conditions) in settings.items()}
    grouped, pair_sources, source_owner, seen = defaultdict(list), {}, {}, set()
    for row in rows:
        seed, arm, split = row["seed"], row["arm"], row["split"]
        pair, condition = row["pair"], row["corruption"]
        if (isinstance(seed, bool) or not isinstance(seed, Integral) or seed not in P["seeds"] or arm not in arms
                or split not in settings or isinstance(pair, bool) or not isinstance(pair, Integral)):
            raise ValueError("Unknown seed, arm, split, or noninteger source-pair index")
        count, conditions = settings[split]
        if not 0 <= pair < count or condition not in conditions:
            raise ValueError("Observation is outside the frozen evaluation grid")
        key = seed, arm, split, int(pair), condition
        if key in seen:
            raise ValueError(f"Duplicate selected-action observation: {key}")
        seen.add(key)
        sources = tuple(row["source_ids"])
        if (len(sources) != 2 or sources[0] == sources[1]
                or any(not isinstance(source, str) or not source for source in sources)):
            raise ValueError("A source-pair cluster must contain two different source identities")
        cluster = split, int(pair)
        if pair_sources.setdefault(cluster, sources) != sources:
            raise ValueError("Paired arms/models/conditions do not share the same source images")
        for source in sources:
            if source_owner.setdefault(source, cluster) != cluster:
                raise ValueError("Source images overlap allegedly independent pair/split clusters")
        action, refinements = row["action"], row["refinement_count"]
        if (isinstance(action, bool) or not isinstance(action, Integral) or not 0 <= action < 5
                or isinstance(refinements, bool) or not isinstance(refinements, Integral)
                or refinements != 1 + (action != 0)):
            raise ValueError("Actual refinement count does not match the committed action")
        index = P["seeds"].index(seed), int(pair), conditions.index(condition)
        for observer in OBSERVERS:
            result[split][observer][arm][index] = _score(row, observer)
        actions[split][arm][index] = action
        grouped[split, arm].append(row)
    for split, observers in result.items():
        for observer, tables in observers.items():
            for arm, values in tables.items():
                if not np.isfinite(values).all():
                    raise ValueError(f"Incomplete selected-action evaluation grid: {split}/{observer}/{arm}")
    return result, actions, grouped, settings


def certainty_equivalent(values, gamma=None):
    """One CE over the entire supplied cohort, never a mean of conditional CEs."""
    gamma = P["secondary_ce_gamma"] if gamma is None else gamma
    values = np.asarray(values, dtype=np.float64)
    if values.size == 0 or not np.isfinite(values).all() or not math.isfinite(gamma) or gamma <= 0:
        raise ValueError("Certainty equivalent requires nonempty finite values and positive gamma")
    scaled = -gamma * values
    shift = float(scaled.max())
    return float(-(math.log(float(np.exp(scaled - shift).mean())) + shift) / gamma)


def _lower_tail(values, fraction=.1):
    ordered = np.sort(np.asarray(values).ravel())
    mass = len(ordered) * fraction
    whole = int(mass)
    total = float(ordered[:whole].sum())
    if mass > whole:
        total += (mass - whole) * float(ordered[whole])
    return total / mass


def _interval(bootstrap, tail):
    return np.quantile(bootstrap, [tail, 1 - tail], method="linear").tolist()


def _bootstrap(values, indices):
    pair_means = values.mean(axis=(0, 2))
    gamma = P["secondary_ce_gamma"]
    scaled = -gamma * values
    shift = float(scaled.max())
    pair_exponentials = np.exp(scaled - shift).mean(axis=(0, 2))
    return {"mean": pair_means[indices].mean(axis=1),
            "ce": -(np.log(pair_exponentials[indices].mean(axis=1)) + shift) / gamma}


def _contrast(tables, bootstraps, candidate, control, tail):
    first, second = tables[candidate], tables[control]
    difference = first - second
    per_seed = difference.mean(axis=(1, 2))
    interval = _interval(bootstraps[candidate]["mean"] - bootstraps[control]["mean"], tail)
    return {"mean_net_return_difference": float(difference.mean()),
            "paired_cluster_interval": interval,
            "interval_nominal_confidence": 1 - 2 * tail,
            "per_seed_mean_differences": [{"seed": seed, "difference": float(value)}
                                          for seed, value in zip(P["seeds"], per_seed, strict=True)],
            "positive_in_every_fixed_seed": bool(np.all(per_seed > 0)),
            "gain_supported": bool(interval[0] > 0 and np.all(per_seed > 0)),
            "pooled_ce_difference": certainty_equivalent(first) - certainty_equivalent(second),
            "pooled_ce_descriptive_95_interval": _interval(
                bootstraps[candidate]["ce"] - bootstraps[control]["ce"], .025)}


def _resource_summary(rows):
    keys = sorted({key for row in rows for key, value in row.get("resources", {}).items()
                   if isinstance(value, Real) and not isinstance(value, bool)})
    result = {}
    for key in keys:
        values = np.array([_finite(row["resources"][key], f"resources.{key}")
                           for row in rows if key in row.get("resources", {})])
        if np.any(values < 0):
            raise ValueError("Recorded physical resource/timing values must be nonnegative")
        result[key] = {"rows_with_measurement": len(values), "mean": float(values.mean()),
                       "median": float(np.median(values)), "p95": float(np.quantile(values, .95))}
    return result


def _summary(rows, tables, actions, conditions):
    observers = {}
    for observer in OBSERVERS:
        values = tables[observer]
        observers[observer] = {
            "mean_net_return": float(values.mean()), "pooled_ce": certainty_equivalent(values),
            "lower_decile_mean_net_return": _lower_tail(values),
            "mean_raw_utility": float(np.mean([row[observer]["utility"] for row in rows])),
            "mean_components": {key: float(np.mean([row[observer][key] for row in rows]))
                                for key in (*METRIC_WEIGHTS, "joint_loss")},
            "caption_valid_fraction": float(np.mean([row[observer]["caption_valid"] for row in rows])),
            "per_seed": [{"seed": seed, "mean_net_return": float(values[index].mean()),
                          "within_seed_ce": certainty_equivalent(values[index])}
                         for index, seed in enumerate(P["seeds"])],
            "per_condition": {condition: {"mean_net_return": float(values[:, :, index].mean()),
                                           "pooled_ce": certainty_equivalent(values[:, :, index])}
                              for index, condition in enumerate(conditions)},
        }
    return {"rows": len(rows), "observers": observers,
            "action_counts": np.bincount(actions.ravel(), minlength=5).tolist(),
            "mean_actual_refinements": float(np.mean([row["refinement_count"] for row in rows])),
            "mean_declared_refinement_charge": float(np.mean(
                [P["refinement_charge"] * row["refinement_count"] for row in rows])),
            "descriptive_resources": _resource_summary(rows),
            "descriptive_resources_by_condition": {
                condition: _resource_summary([row for row in rows if row["corruption"] == condition])
                for condition in conditions}}


def analyze(rows):
    """Validate the full frozen grid and return JSON-serializable evidence."""
    rows = list(rows)
    tables, actions, grouped, settings = _tables(rows)
    bootstrap = {}
    for split_index, (split, (count, _)) in enumerate(settings.items()):
        rng = np.random.default_rng(P["bootstrap_seed"] + split_index)
        indices = rng.integers(count, size=(P["bootstrap_samples"], count))
        bootstrap[split] = {observer: {arm: _bootstrap(values, indices)
                                      for arm, values in observer_tables.items()}
                            for observer, observer_tables in tables[split].items()}
    retention, primary = [], []
    retention_tail = P["family_alpha"] / (2 * len(RETENTION_ARMS))
    for arm in RETENTION_ARMS:
        checks = {observer: _contrast(tables["retention"][observer], bootstrap["retention"][observer],
                                       arm, BASELINE, retention_tail) for observer in OBSERVERS}
        for check in checks.values():
            check["noninferiority_supported"] = check["paired_cluster_interval"][0] >= -P["retention_margin"]
        retention.append({"candidate": arm, "control": BASELINE, "observers": checks,
                          "both_observers_noninferior": all(
                              check["noninferiority_supported"] for check in checks.values())})
    retention_pass = {entry["candidate"]: entry["both_observers_noninferior"] for entry in retention}
    primary_tail = P["family_alpha"] / (2 * len(P["primary_contrasts"]))
    for candidate, control in P["primary_contrasts"]:
        checks = {observer: _contrast(tables["test"][observer], bootstrap["test"][observer],
                                       candidate, control, primary_tail) for observer in OBSERVERS}
        gain = all(check["gain_supported"] for check in checks.values())
        primary.append({"candidate": candidate, "control": control, "observers": checks,
                        "both_observers_gain_supported": gain,
                        "candidate_retention_vs_frozen_supported": retention_pass[candidate],
                        "accepted_with_retention": gain and retention_pass[candidate]})
    interaction = {}
    e, c, d, a = P["interaction"]
    for observer in OBSERVERS:
        values, samples = tables["test"][observer], bootstrap["test"][observer]
        difference = values[e] - values[c] - values[d] + values[a]
        sampled = samples[e]["mean"] - samples[c]["mean"] - samples[d]["mean"] + samples[a]["mean"]
        interaction[observer] = {"mean_net_return_interaction": float(difference.mean()),
                                 "descriptive_95_interval": _interval(sampled, .025),
                                 "per_seed": [{"seed": seed, "difference": float(value)}
                                              for seed, value in zip(P["seeds"], difference.mean(axis=(1, 2)), strict=True)]}
    summaries = {f"{split}/{arm}": _summary(selected, {o: tables[split][o][arm] for o in OBSERVERS},
                                            actions[split][arm], settings[split][1])
                 for (split, arm), selected in sorted(grouped.items())}
    reset = {split: {"action_changes": int(np.count_nonzero(
                         actions[split]["E_field_native"] != actions[split]["I_field_reset"])),
                     "paired_rows": int(actions[split]["E_field_native"].size)} for split in settings}
    result = {"schema": "hepta.parameter-field-neuron-bridge.analysis.v1",
              "raw_selected_action_rows": len(rows), "complete_grid_verified": True,
              "source_pair_disjointness_verified": True, "fixed_model_seeds": P["seeds"],
              "independent_source_pairs": {split: value[0] for split, value in settings.items()},
              "primary_objective": P["primary_objective"], "summaries": summaries,
              "primary_contrasts": primary, "retention_vs_frozen": retention,
              "interaction_descriptive": {"expression": f"({e}-{c})-({d}-{a})", "observers": interaction},
              "native_state_reset_action_diagnostic": reset,
              "all_six_primary_gains_accepted": all(entry["accepted_with_retention"] for entry in primary),
              "uncertainty": {"method": "paired source-pair percentile bootstrap; NumPy linear quantiles",
                  "replicates": P["bootstrap_samples"], "seed": P["bootstrap_seed"],
                  "resampling": "same pair indices across all arms, conditions, and fixed models; splits independent",
                  "primary_family_size_per_observer": len(P["primary_contrasts"]),
                  "primary_interval_tail_probability": primary_tail,
                  "retention_family_size_per_observer": len(RETENTION_ARMS),
                  "retention_interval_tail_probability": retention_tail,
                  "family_alpha_per_observer": P["family_alpha"],
                  "conditioning": "three fixed historical models and this constructed source task",
                  "not_claimed": "new-model/new-dataset uncertainty, finite-sample coverage, or causal timing advantage"},
              "secondary_ce": {"definition": P["secondary_ce"], "gamma": P["secondary_ce_gamma"],
                               "used_for_acceptance": False,
                               "intervals": "descriptive paired 95%; no multiplicity guarantee"},
              "artifact_scope": "row scores and identities validated; file bytes/model provenance checked by execution owner",
              "cost_scope": "logical refinement tariff in objective; measured host/bridge timings descriptive and separate",
              "population_confirmation": False, "native_owner_integrated": False}
    return json.loads(json.dumps(result, sort_keys=True, allow_nan=False))
