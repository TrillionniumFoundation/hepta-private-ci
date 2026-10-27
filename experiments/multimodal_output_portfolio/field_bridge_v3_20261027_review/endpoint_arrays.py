"""Independent shape, identity and arithmetic adapter for complete V3 endpoints."""

import hashlib
import json
import numpy as np

from analysis_contract import select_development


MODES = ("field", "generic", "richer", "h7")
OBSERVERS = ("reward", "audit")
KEYS = {"methods", "schedule_ids", "observer_names", "task_values", "clean_values",
        "original_task", "original_clean", "task_source_ids", "clean_source_ids",
        "task_conditions", "clean_conditions", "task_panel_identity", "clean_panel_identity"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def object_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def role_pairs(registry, role):
    ids = registry["roles"][role]["identities"]
    require(len(ids) % 2 == 0 and len(set(ids)) == len(ids), "Role contains incomplete or duplicate pairs")
    return [ids[i:i + 2] for i in range(0, len(ids), 2)]


def adapt(data, seed, phase, protocol, registry):
    require(phase in ("development", "audit"), "Endpoint adapter does not open final sources")
    require(set(data) == KEYS, "Endpoint NPZ key inventory differs")
    methods = ([f"ordinary_{i}" for i in range(4)] if phase == "development" else ["ordinary"]) + list(MODES)
    require(data["methods"].tolist() == methods and data["observer_names"].tolist() == list(OBSERVERS),
            "Endpoint method/observer order differs")
    schedules = protocol["training"][phase + "_schedule_ids"]
    require(data["schedule_ids"].tolist() == schedules and len(schedules) == len(set(schedules)) == 4,
            "Endpoint complete-rollout IDs differ")
    require(seed in protocol["seeds"], "Unknown historical seed")
    result = {"seed": seed, "phase": phase, "methods": methods, "schedules": schedules,
              "panels": {}, "paired_gains": {}, "panel_identity": {}, "score_values_checked": 0}
    for name in ("task", "clean"):
        conditions = protocol["training"]["conditions"] if name == "task" else ["clean"]
        pairs = role_pairs(registry, phase + "_" + name)
        count, c = len(pairs), len(conditions)
        expected_ids = pairs * c
        expected_conditions = [condition for condition in conditions for _ in pairs]
        require(data[name + "_source_ids"].tolist() == expected_ids, f"{name} endpoint source order or membership differs")
        require(data[name + "_conditions"].tolist() == expected_conditions, f"{name} condition-major order differs")
        values, original = data[name + "_values"], data["original_" + name]
        require(values.dtype == original.dtype == np.dtype("float64") and
                values.shape == (len(methods), 4, 2, c * count) and original.shape == (2, c * count),
                f"{name} endpoint value dimensions/dtypes differ")
        require(np.isfinite(values).all() and np.isfinite(original).all(), "Nonfinite endpoint value")
        identity = data[name + "_panel_identity"]
        require(identity.shape == () and isinstance(identity.item(), str) and len(identity.item()) == 64,
                "Invalid panel identity digest")
        result["panel_identity"][name] = identity.item()
        # Preserve the frozen stage selector's operation order, including ties:
        # subtract original per-example values first, then reduce paths and the
        # stored condition-major examples. Do not rank rounded display means.
        result["paired_gains"][name] = (values - original[None, None]).mean(axis=(1, 3))
        result["panels"][name] = {}
        for observer_index, observer in enumerate(OBSERVERS):
            arranged = {"frozen": np.broadcast_to(original[observer_index].reshape(c, count).T[None],
                                                   (4, count, c)).copy()}
            for index, method in enumerate(methods):
                arranged[method] = values[index, :, observer_index].reshape(4, c, count).transpose(0, 2, 1).copy()
            result["panels"][name][observer] = arranged
        result["score_values_checked"] += int(values.size + original.size)
    return result


def verify_panel_identity(record, converted, name, protocol, registry):
    require(record["independent_of_schedule_id"] is True, "Panel claims schedule-specific outcomes")
    batches = record["batches"]
    require(record["sha256"] == object_sha(batches) == converted["panel_identity"][name],
            "Panel identity digest differs")
    role = converted["phase"] + "_" + name
    pairs = role_pairs(registry, role)
    conditions = protocol["training"]["conditions"] if name == "task" else ["clean"]
    p = protocol["training"]
    expected = []
    role_seed = int(hashlib.sha256(role.encode()).hexdigest()[:8], 16)
    for condition_index, condition in enumerate(conditions):
        for offset in range(0, len(pairs), p["panel_batch_size"]):
            selected = pairs[offset:offset + p["panel_batch_size"]]
            common = converted["seed"] * 1009 + role_seed + condition_index * 1000003 + offset
            expected.append({"condition": condition, "batch_size": len(selected), "source_ids": selected,
                             "noise_seed": p["hard_forward_seed_offset"] + common})
    require(len(batches) == len(expected), "Endpoint batch count differs")
    for actual, want in zip(batches, expected, strict=True):
        require({key: actual[key] for key in want} == want, "Endpoint batch source/condition/RNG alignment differs")
        require(set(actual) == {*want, "public_sha256", "target_sha256"} and
                all(isinstance(actual[key], str) and len(actual[key]) == 64 for key in ("public_sha256", "target_sha256")),
                "Invalid endpoint observation/target identity fields")


def stack_panels(converted, protocol):
    require([row["seed"] for row in converted] == protocol["seeds"], "Historical seed order differs")
    methods = ["frozen", *converted[0]["methods"]]
    require(all(row["methods"] == methods[1:] and row["schedules"] == converted[0]["schedules"] for row in converted),
            "Cross-model method/path pairing differs")
    return {panel: {observer: {method: np.stack([row["panels"][panel][observer][method] for row in converted])
                               for method in methods} for observer in OBSERVERS} for panel in ("task", "clean")}


def development_selection(converted, protocol):
    require(all(row["phase"] == "development" for row in converted), "Selection may use development endpoints only")
    require([row["seed"] for row in converted] == protocol["seeds"], "Development seed order differs")
    require(protocol["training"]["ordinary_clean_min_delta"] == protocol["training_development_gate"]["each_seed_clean_delta_min"],
            "Ordinary eligibility has two conflicting thresholds")
    methods = converted[0]["methods"]
    paired = {panel: {observer: {"frozen": np.zeros((len(converted), 1, 1, 1))} for observer in OBSERVERS}
              for panel in ("task", "clean")}
    for panel in paired:
        for observer_index, observer in enumerate(OBSERVERS):
            for method_index, method in enumerate(methods):
                paired[panel][observer][method] = np.asarray([row["paired_gains"][panel][method_index, observer_index]
                    for row in converted], dtype=np.float64).reshape(len(converted), 1, 1, 1)
    contracted = select_development(paired["task"], paired["clean"], protocol["training_development_gate"])
    require(contracted.get("reason") != "no_eligible_ordinary", "No eligible ordinary candidate; stage selector must record failure")
    choices = contracted["ordinary_choices"]
    selected = contracted.get("selected_adaptive")
    gate = protocol["training_development_gate"]
    ordinary = np.stack([row["paired_gains"]["task"][methods.index(choice)] for row, choice in zip(converted, choices, strict=True)])
    field = np.stack([row["paired_gains"]["task"][methods.index("field")] for row in converted])
    field_clean = np.stack([row["paired_gains"]["clean"][methods.index("field")] for row in converted])
    adaptive = None if selected is None else np.stack([row["paired_gains"]["task"][methods.index(selected)] for row in converted])
    checks = {
        "ordinary_each_seed_nonnegative": bool(np.all(ordinary >= gate["ordinary_each_seed_gain_min"])),
        "ordinary_pooled_gain": bool(np.all(ordinary.mean(0) >= gate["ordinary_pooled_gain_min"])),
        "field_clean_eligible": bool(np.all(field_clean >= gate["each_seed_clean_delta_min"])),
        "field_over_ordinary": bool(np.all((field - ordinary).mean(0) > gate["field_over_ordinary_pooled_gain_strict_min"])),
        "eligible_adaptive_exists": selected is not None,
        "field_over_selected_adaptive": selected is not None and bool(np.all((field - adaptive).mean(0) >=
                                                    gate["field_over_selected_adaptive_pooled_gain_min"])),
    }
    require(all(checks.values()) == contracted["pass"], "Independent selection and gate contract disagree")
    return {"passed": all(checks.values()), "checks": checks,
            "ordinary_action_indices": {str(row["seed"]): int(choice.rsplit("_", 1)[-1]) for row, choice in zip(converted, choices, strict=True)},
            "selected_adaptive": selected, "eligible_adaptive_methods": contracted.get("adaptive_eligible", []),
            "per_seed": {str(row["seed"]): {method: {"task_gain": row["paired_gains"]["task"][index].tolist(),
                         "clean_gain": row["paired_gains"]["clean"][index].tolist()} for index, method in enumerate(methods)} for row in converted},
            "ordinary_pooled_gain": ordinary.mean(0).tolist(), "field_over_ordinary_pooled_gain": (field - ordinary).mean(0).tolist(),
            "field_over_selected_adaptive_pooled_gain": None if selected is None else (field - adaptive).mean(0).tolist(),
            "arithmetic_contract": "paired per-example deltas; mean over path and condition-major sample axes before comparator ranking"}
