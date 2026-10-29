"""Paired endpoint inference for the frozen B/C designs; no model or data loading."""

import hashlib
import json

import numpy as np

OBSERVERS = ("reward", "audit")
CONDITIONS = ("heavy_noise", "missing", "occlusion", "clean")
B_METHODS = ("ordinary", "field12", "full_current_state", "history6", "fixed_taper", "frozen")
C_ARMS = (("ordinary", "ordinary"), ("ordinary", "field12"), ("dual", "ordinary"),
          ("dual", "field12"), ("ordinary", "frozen"), ("dual", "frozen"))
# An expression (a, b) means a minus b. Nested differences preserve exact pairing.
B_EFFECTS = (
    ("ordinary-frozen task", "task", (0, 5)), ("field-ordinary task", "task", (1, 0)),
    ("field-history task", "task", (1, 3)), ("full-state-field task", "task", (2, 1)),
    ("ordinary-frozen clean", "clean", (0, 5)), ("field-frozen clean", "clean", (1, 5)),
    ("full-state-frozen clean", "clean", (2, 5)), ("history-frozen clean", "clean", (3, 5)),
    ("fixed-taper-field task (secondary)", "task", (4, 1)),
    ("fixed-taper-frozen clean (secondary)", "clean", (4, 5)),
)
C_EFFECTS = (
    ("interaction task", "task", ((3, 2), (1, 0))),
    ("dual field increment task", "task", (3, 2)),
    ("ordinary field increment task", "task", (1, 0)),
    ("dual-field minus ordinary-field task", "task", (3, 1)),
    ("ordinary-baseline minus warmstart clean", "clean", (0, 4)),
    ("ordinary-field minus warmstart clean", "clean", (1, 4)),
    ("dual-baseline minus warmstart clean", "clean", (2, 5)),
    ("dual-field minus warmstart clean", "clean", (3, 5)),
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _aligned(record, pair_count):
    role = record["role"]
    conditions = CONDITIONS if role == "task" else ("clean",)
    ids = np.asarray(record["source_ids"], dtype=object)
    marks = np.asarray(record["conditions"], dtype=object)
    require(ids.ndim == 2 and ids.shape[1] == 2 and marks.shape == (len(ids),), "Source/condition shape differs")
    pairs = [tuple(row) for row in ids.tolist()]
    require(all(all(type(i) is str and i for i in pair) and pair[0] != pair[1] for pair in pairs), "Invalid source pair")
    require(all(type(c) is str and c in conditions for c in marks.tolist()), "Unregistered endpoint condition")
    unique = tuple(sorted(set(pairs)))
    require(len(unique) == pair_count and len({i for pair in unique for i in pair}) == 2 * pair_count,
            "Source pairs are incomplete or share individual sources")
    keys = list(zip(pairs, marks.tolist(), strict=True))
    expected = [(pair, condition) for pair in unique for condition in conditions]
    require(len(keys) == len(set(keys)) and set(keys) == set(expected), "Each source pair needs exactly the registered conditions")
    require(set(record["values"]) == set(OBSERVERS), "Both frozen observers are required")
    values = [np.asarray(record["values"][o]) for o in OBSERVERS]
    require(all(v.shape == (len(ids),) and v.dtype.kind in "fiu" and np.isfinite(v).all() for v in values), "Nonfinite or malformed endpoint values")
    positions = {key: i for i, key in enumerate(keys)}
    ordered = np.stack(values, axis=1).astype(np.float64)[[positions[key] for key in expected]]
    return unique, ordered.reshape(pair_count, len(conditions), 2).mean(axis=1)


def _numeric_costs(costs, prefix=""):
    require(type(costs) is dict, "Costs must be an explicit numeric ledger")
    result = {}
    for name, value in costs.items():
        require(type(name) is str and name and "/" not in name, "Cost key must be a nonempty unambiguous name")
        key = prefix + name
        if type(value) is dict:
            result.update(_numeric_costs(value, key + "/"))
        else:
            require(type(value) in (int, float) and np.isfinite(value) and value >= 0, "Cost ledger contains a nonphysical numeric value")
            result[key] = float(value)
    return result


def _configuration(stage, protocol):
    require(stage in ("B", "C"), "Only registered B/C endpoint analyses are supported")
    cfg = protocol["stage_" + stage]
    effects = B_EFFECTS if stage == "B" else C_EFFECTS
    statistics = cfg["statistics"]
    require(statistics["bootstrap_draws"] == 8000 and statistics["bootstrap_seed"] == (291029 if stage == "B" else 291030)
            and statistics["formal_family_size_per_observer"] == len(effects) and statistics["family_alpha"] == .05
            and statistics["retention_margin"] == .01, "Registered bootstrap/family choices differ")
    if stage == "B":
        seeds = tuple(protocol["shared_guard48_learning"]["fixed_model_seeds"])
        schedules = tuple(cfg["schedule_ids"])
        require(seeds == (17, 29, 43) and cfg["fixed_model_count"] == 3 and schedules == tuple(range(106000, 106016)), "B fixed models/schedules differ")
        require(tuple(cfg["methods"]) == B_METHODS[:-1] and cfg["statistics"]["formal_family"] == [e[0] for e in effects], "B methods or effect family differ")
        arms, population = tuple((None, m) for m in B_METHODS), "fresh_qualification"
    else:
        seeds, schedules = tuple(cfg["paired_training_seeds"]), (None,)
        require(seeds == tuple(range(801, 809)), "C paired training seeds differ")
        arms, population = C_ARMS, "fresh_final"
    counts = {role: protocol["task_and_data"][population][role + "_pairs"] for role in ("task", "clean")}
    require(all(type(n) is int and n > 1 for n in counts.values()), "Invalid registered source-pair counts")
    return seeds, schedules, arms, effects, statistics, counts


def _assemble(records, stage, seeds, schedules, arms, counts):
    table, costs, paths, pair_ids, c_schedules = {}, {}, set(), {}, {}
    for record in records:
        seed, sid, role, method = record["seed"], record["schedule_id"], record["role"], record["method"]
        architecture = record.get("architecture")
        require(type(seed) is int and seed in seeds and role in counts, "Unexpected endpoint seed/role")
        require(type(sid) is int or (method == "frozen" and sid is None), "Only a frozen reference may omit its training schedule")
        require((architecture, method) in arms, "Unexpected or missing architecture/method")
        if stage == "B" and method != "frozen":
            require(sid in schedules, "Unregistered B schedule")
        if stage == "C" and method != "frozen":
            require(c_schedules.setdefault(seed, sid) == sid, "C arms do not share their paired schedule")
        slot = None if method == "frozen" or stage == "C" else sid
        path = (seed, architecture, method, slot)
        key = (*path, role)
        require(key not in table, "Duplicate endpoint path; frozen outputs must appear once per model/architecture/role")
        pairs, values = _aligned(record, counts[role])
        require(pair_ids.setdefault(role, pairs) == pairs, "Methods/models/schedules do not share source pairs")
        table[key] = values
        paths.add(path)
        if "costs" in record:
            ledger = _numeric_costs(record["costs"])
            if ledger:
                require(path not in costs or costs[path] == ledger, "Repeated path cost ledgers differ between roles")
                costs[path] = ledger
    require(set(pair_ids) == set(counts), "Missing task or clean endpoint records")
    require(not ({i for p in pair_ids["task"] for i in p} & {i for p in pair_ids["clean"] for i in p}), "Task and clean source identities overlap")
    data, expected = {}, set()
    for role, count in counts.items():
        values = np.empty((len(seeds), len(schedules), len(arms), count, 2), dtype=np.float64)
        for i, seed in enumerate(seeds):
            for j, schedule in enumerate(schedules):
                for k, (architecture, method) in enumerate(arms):
                    key = (seed, architecture, method, None if method == "frozen" else schedule, role)
                    expected.add(key)
                    require(key in table, "Missing registered endpoint: " + repr(key))
                    values[i, j, k] = table[key]
        data[role] = values
    require(set(table) == expected, "Unexpected endpoint replicas")
    return data, pair_ids, paths, costs


def _effect(data, expression):
    if type(expression) is int:
        return data[:, :, expression]
    return _effect(data, expression[0]) - _effect(data, expression[1])


def _weights(rng, batches, count):
    indices = rng.integers(count, size=(batches, count))
    flat = (indices + np.arange(batches)[:, None] * count).ravel()
    return np.bincount(flat, minlength=batches * count).reshape(batches, count) / count


def _bootstrap(effects, stage, statistics):
    draws = statistics["bootstrap_draws"]
    rng = np.random.default_rng(statistics["bootstrap_seed"])
    models, schedules = effects["task"].shape[:2]
    samples = {role: np.empty((draws, x.shape[3], 2)) for role, x in effects.items()}
    flattened = {role: x.transpose(2, 0, 1, 3, 4).reshape(x.shape[2], -1) for role, x in effects.items()}
    for start in range(0, draws, 128):
        count = min(128, draws - start)
        shared = (_weights(rng, count * models, schedules).reshape(count, models, schedules) if stage == "B"
                  else _weights(rng, count, models))
        for role in ("task", "clean"):
            x = effects[role]
            pairs = _weights(rng, count, x.shape[2])
            means = (pairs @ flattened[role]).reshape(count, models, schedules, x.shape[3], 2)
            samples[role][start:start + count] = (np.einsum("bms,bmseo->beo", shared, means) / models if stage == "B"
                                                else np.einsum("bm,bmeo->beo", shared, means[:, :, 0]))
    return samples


def _cost_summary(paths, costs, stage):
    grouped = {}
    for path in sorted(paths):
        label = path[2] if stage == "B" else path[1] + "+" + path[2]
        grouped.setdefault(label, []).append(path)
    result = {"scope": "Recorded per-path training ledgers; empty role ledgers ignored and identical duplicates counted once. scoring_costs and shared/offline costs are reported separately by the runner, not imputed here.", "arms": {}}
    for label, members in sorted(grouped.items()):
        available = [costs[p] for p in members if p in costs]
        metrics = {}
        for key in sorted({k for ledger in available for k in ledger}):
            values = [ledger[key] for ledger in available if key in ledger]
            summary = {"paths": len(values), "mean": float(np.mean(values)), "minimum": min(values), "maximum": max(values)}
            if "peak" not in key.lower() and "max_rss" not in key.lower():
                summary["sum_over_recorded_paths"] = float(sum(values))
            metrics[key] = summary
        result["arms"][label] = {"expected_paths": len(members), "paths_with_costs": len(available), "metrics": metrics}
    if stage == "B":
        differences = {}
        for p in sorted(paths):
            if p[2] != "field12":
                continue
            other = (p[0], p[1], "fixed_taper", p[3])
            if p in costs and other in costs:
                for key in costs[p].keys() & costs[other].keys():
                    differences.setdefault(key, []).append(costs[p][key] - costs[other][key])
        result["field_minus_taper_descriptive"] = {k: {"paired_paths": len(v), "mean_difference": float(np.mean(v)),
                                                       **({"sum_difference": float(sum(v))} if "peak" not in k.lower()
                                                          and "max_rss" not in k.lower() else {})} for k, v in sorted(differences.items())}
    return result


def _claims(effects, stage, seeds):
    lower = lambda name, observer: effects[name]["ci"][observer][0]
    retention = [name for name, effect in effects.items() if effect["role"] == "clean"]
    all_retained = all(lower(name, o) > -.01 for name in retention for o in OBSERVERS)
    if stage == "C":
        positive = all(lower("interaction task", o) > 0 for o in OBSERVERS)
        return {"interaction_positive_both_observers": positive, "all_four_arms_retained_both_observers": all_retained,
                "interaction_and_retention_thresholds_pass": positive and all_retained}
    field = all(lower("field-ordinary task", o) > .001 and lower("field-history task", o) > 0
                and lower("field-frozen clean", o) > -.01 for o in OBSERVERS)
    per_model = all(effects[name]["per_seed"][str(seed)][o] >= 0 for name in ("field-ordinary task", "field-history task")
                    for seed in seeds for o in OBSERVERS)
    ordinary = all(lower("ordinary-frozen task", o) > 0 and lower("ordinary-frozen clean", o) > -.01 for o in OBSERVERS)
    return {"ordinary_gain_thresholds_pass": ordinary, "field_task_deltas_nonnegative_each_fixed_model": per_model,
            "field_advantage_thresholds_pass": field and per_model,
            "ordinary_pooled_development_target_0.005_met": all(effects["ordinary-frozen task"]["point"][o] >= .005 for o in OBSERVERS)}


def summarize(records, stage, protocol):
    """Summarize a complete frozen endpoint grid; negatives and all registered effects remain."""
    seeds, schedules, arms, family, statistics, counts = _configuration(stage, protocol)
    data, pair_ids, paths, costs = _assemble(records, stage, seeds, schedules, arms, counts)
    by_role = {role: [entry for entry in family if entry[1] == role] for role in ("task", "clean")}
    differences = {role: np.stack([_effect(data[role], e[2]) for e in entries], axis=3) for role, entries in by_role.items()}
    samples = _bootstrap(differences, stage, statistics)
    tail = statistics["family_alpha"] / (2 * len(family))
    output = {}
    for role, entries in by_role.items():
        per_seed = differences[role].mean(axis=(1, 2))
        intervals = np.quantile(samples[role], [tail, 1 - tail], axis=0, method="linear")
        for i, (name, _, _) in enumerate(entries):
            output[name] = {"role": role, "secondary": "secondary" in name,
                            "point": {o: float(per_seed[:, i, j].mean()) for j, o in enumerate(OBSERVERS)},
                            "per_seed": {str(seed): {o: float(per_seed[k, i, j]) for j, o in enumerate(OBSERVERS)} for k, seed in enumerate(seeds)},
                            "ci": {o: [float(v) for v in intervals[:, i, j]] for j, o in enumerate(OBSERVERS)}}
    arm_means = {role: {(method if stage == "B" else architecture + "+" + method):
                        {o: float(x[:, :, a, :, j].mean()) for j, o in enumerate(OBSERVERS)}
                        for a, (architecture, method) in enumerate(arms)} for role, x in data.items()}
    return {"schema": "hepta.parameter-field-fullstudy.paired-endpoint-analysis.1", "stage": stage,
            "protocol_sha256": _hash(protocol), "seeds": list(seeds), "source_pairs": counts,
            "source_pair_identities_sha256": {r: _hash(ids) for r, ids in pair_ids.items()},
            "conditions_equal_weight": list(CONDITIONS), "observers": list(OBSERVERS), "arm_means": arm_means,
            "formal_family": [e[0] for e in family], "effects": {e[0]: output[e[0]] for e in family},
            "statistics": {"draws": 8000, "seed": statistics["bootstrap_seed"], "family_size_per_observer": len(family),
                           "family_alpha": .05, "quantiles": [tail, 1 - tail], "quantile_method": "linear",
                           "rng": "NumPy default_rng/PCG64", "batch_size": 128, "numpy": np.__version__,
                           "draw_order": "Within each batch: shared schedule/seed draws, shared task pairs, separate shared clean pairs",
                           "bootstrap_distribution_sha256": {r: hashlib.sha256(x.tobytes()).hexdigest() for r, x in samples.items()},
                           "coverage": "Approximate percentile intervals with correction per observer; no simultaneous cross-observer coverage assertion."},
            "scope": ("Conditional on three fixed historical models. Only schedules within each model and source pairs are resampled; no pretrained-model population generalization." if stage == "B"
                      else "Eight paired training seeds in this fixed architecture/task experiment, jointly resampled across arms; approximate limited-replication inference."),
            "statistical_thresholds": _claims(output, stage, seeds),
            "admission": "Not assessed here: requires the separate integrity, mechanism-activity and full-cost decisions.",
            "costs": _cost_summary(paths, costs, stage)}
