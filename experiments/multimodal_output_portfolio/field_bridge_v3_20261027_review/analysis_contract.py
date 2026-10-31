"""Independent V3 statistical contract; accepts arrays, never opens outcomes.

Every panel maps observer -> method -> float64 array with axes
[fixed_model_seed, paired_complete_rollout, source_pair, condition].
Methods and observers share complete rollout and source-pair draws. Conditions
and the three historical model seeds have equal fixed weights. With one rollout
there is no rollout draw; this is the runtime/final conditional analysis.
"""

import hashlib
import numpy as np


OBSERVERS = ("reward", "audit")
ADAPTIVE_ORDER = ("generic", "richer", "h7")
ORDINARY_ORDER = tuple(f"ordinary_{i}" for i in range(4))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validated_panel(panel, observers=OBSERVERS):
    require(tuple(panel) == tuple(observers), "Observer order or membership differs")
    names = tuple(panel[observers[0]])
    require(names, "Empty method family")
    shape = None
    result = {}
    for observer in observers:
        require(tuple(panel[observer]) == names, "Method order differs between observers")
        result[observer] = {}
        for method in names:
            values = np.asarray(panel[observer][method], dtype=np.float64)
            require(values.ndim == 4 and all(n > 0 for n in values.shape), "Expected nonempty seed/rollout/pair/condition axes")
            require(np.isfinite(values).all(), "Missing or nonfinite outcomes cannot be dropped")
            shape = values.shape if shape is None else shape
            require(values.shape == shape, "Unpaired panel dimensions")
            result[observer][method] = values
    return result, shape, names


def bootstrap_family(panels, comparisons, *, draws, rng_seed, family_alpha,
                     family_comparisons, expected_seeds=3, expected_rollouts=None,
                     observers=OBSERVERS):
    """Compute one prespecified family with shared hierarchical draws.

    Panels are inserted in the registered order (task, then clean). Each
    comparison has name/panel/left/right/kind; NI additionally has margin.
    Optional condition_indices selects a fixed subset while retaining the
    panel's shared source draws (runtime clean NI uses the clean condition).
    The family denominator includes unrun comparisons, which are not silently
    removed. Missing-method comparisons must instead be omitted and reported
    as unrun by the calling study auditor.
    """
    require(type(draws) is int and draws >= 2, "Invalid bootstrap draw count")
    require(0 < family_alpha < 1 and type(family_comparisons) is int and
            family_comparisons >= len(comparisons) > 0, "Invalid comparison family")
    require(len({item["name"] for item in comparisons}) == len(comparisons), "Duplicate comparison names")
    normalized, shapes, methods = {}, {}, {}
    for panel_name, panel in panels.items():
        normalized[panel_name], shapes[panel_name], methods[panel_name] = validated_panel(panel, observers)
    require(panels, "Empty panel collection")
    seed_count, rollout_count = next(iter(shapes.values()))[:2]
    require(seed_count == expected_seeds, "Unexpected number of fixed model seeds")
    require(expected_rollouts is None or rollout_count == expected_rollouts, "Unexpected complete rollout count")
    require(all(shape[:2] == (seed_count, rollout_count) for shape in shapes.values()),
            "Task/clean rollout IDs cannot be paired by position")
    deltas, group_indices, points, seed_means = {}, {}, {}, {}
    for panel_name in panels:
        indices = [i for i, item in enumerate(comparisons) if item["panel"] == panel_name]
        require(indices, "Unused panel would alter the registered RNG draw stream")
        group_indices[panel_name] = indices
        per_observer = []
        for observer in observers:
            rows = []
            for index in indices:
                item = comparisons[index]
                require(item["kind"] in ("gain", "noninferiority"), "Unknown comparison kind")
                require(item["left"] in methods[panel_name] and item["right"] in methods[panel_name],
                        "Missing comparison method")
                if item["kind"] == "noninferiority":
                    require(item["margin"] > 0, "Noninferiority margin must be positive")
                difference = normalized[panel_name][observer][item["left"]] - normalized[panel_name][observer][item["right"]]
                if "condition_indices" in item:
                    subset = item["condition_indices"]
                    require(subset and len(set(subset)) == len(subset) and
                            all(type(i) is int and 0 <= i < difference.shape[3] for i in subset),
                            "Invalid registered condition subset")
                    difference = np.take(difference, subset, axis=3)
                # Equal condition weights are fixed, not resampled.
                rows.append(difference.mean(axis=3))
            per_observer.append(np.stack(rows))
        deltas[panel_name] = np.stack(per_observer)  # observer, contrast, seed, rollout, pair
        points[panel_name] = deltas[panel_name].mean(axis=(2, 3, 4))
        seed_means[panel_name] = deltas[panel_name].mean(axis=(3, 4))
    require(set(item["panel"] for item in comparisons) == set(panels), "Comparison refers to unknown panel")
    samples = np.zeros((draws, len(observers), len(comparisons)), dtype=np.float64)
    rng = np.random.default_rng(rng_seed)
    draw_digest = hashlib.sha256()
    for draw in range(draws):
        if rollout_count > 1:
            rollout_ids = rng.integers(0, rollout_count, size=(seed_count, rollout_count))
            draw_digest.update(np.asarray(rollout_ids, dtype="<i8").tobytes())
        else:
            rollout_ids = np.zeros((seed_count, 1), dtype=np.int64)
        for panel_name, shape in shapes.items():
            pair_ids = rng.integers(0, shape[2], size=shape[2])
            draw_digest.update(np.asarray(pair_ids, dtype="<i8").tobytes())
            means = np.zeros((len(observers), len(group_indices[panel_name])))
            for seed in range(seed_count):
                chosen_paths = np.take(deltas[panel_name][:, :, seed], rollout_ids[seed], axis=2)
                path_mean = chosen_paths.mean(axis=2)
                means += np.take(path_mean, pair_ids, axis=2).mean(axis=2) / seed_count
            for local, global_index in enumerate(group_indices[panel_name]):
                samples[draw, :, global_index] = means[:, local]
    tail = family_alpha / (2 * family_comparisons)
    intervals = np.quantile(samples, [tail, 1 - tail], axis=0, method="linear")
    results = []
    for index, item in enumerate(comparisons):
        name = item["panel"]
        local = group_indices[name].index(index)
        by_observer = {}
        for observer_index, observer in enumerate(observers):
            lo, hi = intervals[:, observer_index, index].tolist()
            per_seed = seed_means[name][observer_index, local].tolist()
            threshold = 0.0 if item["kind"] == "gain" else -float(item["margin"])
            signs_pass = item["kind"] != "gain" or all(value > 0 for value in per_seed)
            by_observer[observer] = {
                "mean": float(points[name][observer_index, local]), "per_seed_mean": per_seed,
                "interval": [lo, hi], "strict_lower_threshold": threshold,
                "lower_pass": bool(lo > threshold), "seed_signs_pass": bool(signs_pass),
                "pass": bool(lo > threshold and signs_pass),
            }
        results.append({**item, "observers": by_observer,
                        "pass": all(value["pass"] for value in by_observer.values())})
    return {
        "schema": "hepta.field-bridge.v3.paired-bootstrap-family.1",
        "draws": draws, "rng_seed": rng_seed, "rng": "numpy.random.default_rng(PCG64)",
        "draw_order": "each replicate: paired rollout matrix if R>1; then one paired source-index vector per panel in declared order",
        "draw_sha256": draw_digest.hexdigest(), "panel_order": list(panels),
        "panel_shapes": {name: list(shape) for name, shape in shapes.items()},
        "observer_order": list(observers), "family_alpha": family_alpha,
        "family_comparisons": family_comparisons, "interval_coverage_per_observer": 1 - 2 * tail,
        "quantile": "linear", "unrun_family_comparisons": family_comparisons - len(comparisons),
        "comparisons": results, "all_executed_comparisons_pass": all(row["pass"] for row in results),
        "complete_family_pass": len(comparisons) == family_comparisons and all(row["pass"] for row in results),
        "interpretation": "Conjunction across observers; fixed historical model seeds; source/rollout bootstrap is approximate, not simultaneous coverage of both observers' intervals",
    }


def select_development(task, clean, gate, *, observers=OBSERVERS):
    """Select only the registered ordinary and adaptive comparators on dev data."""
    task, task_shape, methods = validated_panel(task, observers)
    clean, clean_shape, clean_methods = validated_panel(clean, observers)
    require(task_shape[:2] == clean_shape[:2] and methods == clean_methods, "Unpaired development task/clean arrays")
    required = {"frozen", "field", *ORDINARY_ORDER, *ADAPTIVE_ORDER}
    require(set(methods) == required, "Incomplete or expanded development method family")
    clean_threshold = float(gate["each_seed_clean_delta_min"])
    pooled = lambda values: values.mean(axis=(1, 2, 3))
    ordinary = []
    ordinary_eligible = []
    for seed in range(task_shape[0]):
        eligible = [method for method in ORDINARY_ORDER if all(
            pooled(clean[observer][method] - clean[observer]["frozen"])[seed] >= clean_threshold
            for observer in observers)]
        ordinary_eligible.append(eligible)
        if not eligible:
            return {"status": "qualification_failure", "reason": "no_eligible_ordinary", "seed_index": seed,
                    "ordinary_eligible": ordinary_eligible, "pass": False}
        ordinary.append(max(eligible, key=lambda method: pooled(task["reward"][method])[seed]))
    adaptive_eligible = [method for method in ADAPTIVE_ORDER if all(
        np.all(pooled(clean[observer][method] - clean[observer]["frozen"]) >= clean_threshold)
        for observer in observers)]
    if not adaptive_eligible:
        return {"status": "qualification_failure", "reason": "no_eligible_adaptive",
                "ordinary_choices": ordinary, "pass": False}
    adaptive = max(adaptive_eligible, key=lambda method: task["reward"][method].mean())
    checks = {}
    for observer in observers:
        ordinary_task = np.stack([task[observer][method][seed] for seed, method in enumerate(ordinary)])
        ordinary_clean = np.stack([clean[observer][method][seed] for seed, method in enumerate(ordinary)])
        ordinary_gain = pooled(ordinary_task - task[observer]["frozen"])
        field_gain = float((task[observer]["field"] - ordinary_task).mean())
        adaptive_gain = float((task[observer]["field"] - task[observer][adaptive]).mean())
        field_clean = pooled(clean[observer]["field"] - clean[observer]["frozen"])
        ordinary_retention = pooled(ordinary_clean - clean[observer]["frozen"])
        checks[observer] = {
            "ordinary_per_seed_gain": ordinary_gain.tolist(), "ordinary_pooled_gain": float(ordinary_gain.mean()),
            "field_over_ordinary": field_gain, "field_over_selected_adaptive": adaptive_gain,
            "field_per_seed_clean": field_clean.tolist(), "ordinary_per_seed_clean": ordinary_retention.tolist(),
            "pass": bool(ordinary_gain.mean() >= gate["ordinary_pooled_gain_min"] and
                         np.all(ordinary_gain >= gate["ordinary_each_seed_gain_min"]) and
                         field_gain > gate["field_over_ordinary_pooled_gain_strict_min"] and
                         adaptive_gain >= gate["field_over_selected_adaptive_pooled_gain_min"] and
                         np.all(field_clean >= clean_threshold) and np.all(ordinary_retention >= clean_threshold)),
        }
    passed = all(row["pass"] for row in checks.values())
    return {"status": "pass" if passed else "qualification_failure", "pass": passed,
            "ordinary_choices": ordinary, "ordinary_eligible": ordinary_eligible,
            "selected_adaptive": adaptive, "adaptive_eligible": adaptive_eligible,
            "tie_order": {"ordinary": list(ORDINARY_ORDER), "adaptive": list(ADAPTIVE_ORDER)},
            "observers": checks}
