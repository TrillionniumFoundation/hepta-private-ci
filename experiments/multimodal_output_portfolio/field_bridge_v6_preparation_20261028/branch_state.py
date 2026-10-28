"""Complete declared CPU branch state; no scientific model adapter or runner."""

import hashlib
import re

import numpy as np

from .codec import digest, dumps, loads, require

SCHEMA = "hepta.field-bridge.v6-preparation.branch-state.1"
ROLES = ["development_gradient", "development_rehearsal", "development_probe", "development_guard"]
BASELINE = {17: 2, 29: 3, 43: 3}


def _sha(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), "Expected a SHA256 identity")


def environment_identity(state):
    return digest({"binding": state["binding"], "immutable": state["immutable"]})


def validate(state, expected_environment_sha256):
    require(set(state) == {"schema", "binding", "immutable", "parameters", "buffers", "requires_grad",
            "optimizer", "optimizer_parameter_names", "gradients", "rng", "cursor", "remaining_schedule"},
            "Branch-state field inventory differs")
    require(state["schema"] == SCHEMA, "Unsupported branch schema")
    binding = state["binding"]
    require(set(binding) == {"study_id", "proposal_sha256", "source_freeze_sha256", "runtime_sha256",
                             "prospective_protocol_sha256", "global_resource_limits_sha256"}, "Binding inventory differs")
    require(isinstance(binding["study_id"], str) and binding["study_id"], "Missing study identity")
    for name, value in binding.items():
        if name.endswith("sha256"):
            _sha(value)
    fixed = state["immutable"]
    require(set(fixed) == {"model_refs", "model_configuration", "source_roles", "context_input_sha256", "guard_baseline"},
            "Immutable context inventory differs")
    require(environment_identity(state) == expected_environment_sha256, "Immutable dependency or execution binding differs")
    require(fixed["source_roles"] == ROLES, "Unapproved source role")
    require(set(fixed["model_refs"]) == {"frozen_base", "original_generator", "reward_observer"}, "Model binding inventory differs")
    for value in (*fixed["model_refs"].values(), fixed["context_input_sha256"]):
        _sha(value)
    config = fixed["model_configuration"]
    require(set(config) == {"device", "architecture_sha256", "module_training", "parameters", "buffers", "named_rngs"}
            and config["device"] == "cpu", "Incomplete declared CPU model configuration")
    _sha(config["architecture_sha256"])
    require(type(config["module_training"]) is dict and config["module_training"]
            and all(type(k) is str and type(v) is bool for k, v in config["module_training"].items()), "Missing immutable module modes")
    require(set(config["parameters"]) == set(state["parameters"]) and set(config["buffers"]) == set(state["buffers"]),
            "Mutable tensor inventory differs from its immutable declaration")
    for section in ("parameters", "buffers"):
        for name, layout in config[section].items():
            require(type(name) is str and name and set(layout) == ({"dtype", "shape", "requires_grad"}
                    if section == "parameters" else {"dtype", "shape"}), "Incomplete declared tensor layout")
            require(type(layout["shape"]) is list and all(type(n) is int and n >= 0 for n in layout["shape"]), "Invalid declared tensor shape")
            array = state[section][name]
            require(isinstance(array, np.ndarray) and array.dtype.str == layout["dtype"]
                    and list(array.shape) == layout["shape"], "Mutable tensor layout differs from its declaration")
            if section == "parameters":
                require(type(layout["requires_grad"]) is bool and state["requires_grad"].get(name) is layout["requires_grad"],
                        "Mutable requires_grad differs from its declaration")
    require(type(config["named_rngs"]) is list and all(type(k) is str and k for k in config["named_rngs"])
            and config["named_rngs"] == sorted(set(config["named_rngs"]))
            and set(config["named_rngs"]) == set(state["rng"]["named"]), "Named RNG inventory differs from its declaration")
    baseline = fixed["guard_baseline"]
    require(set(baseline) == {"panel_sha256", "source_ids", "output_sha256", "values"}, "Guard baseline is incomplete")
    _sha(baseline["panel_sha256"])
    values = baseline["values"]
    require(isinstance(values, np.ndarray) and values.ndim == 1 and values.dtype == np.float64
            and len(values) > 0 and np.isfinite(values).all(), "Invalid immutable guard values")
    require(len(values) == len(baseline["source_ids"]) == len(baseline["output_sha256"]), "Guard pairing differs")
    for pair, output in zip(baseline["source_ids"], baseline["output_sha256"], strict=True):
        require(len(pair) == 2 and all(isinstance(v, str) and v for v in pair), "Invalid guard source pair")
        _sha(output)
    parameters, gradients = state["parameters"], state["gradients"]
    require(isinstance(parameters, dict) and parameters and set(gradients) == set(parameters)
            and set(state["requires_grad"]) == set(parameters), "Parameter/gradient inventory differs")
    for name, parameter in parameters.items():
        require(isinstance(name, str) and isinstance(parameter, np.ndarray) and parameter.dtype.kind == "f"
                and parameter.flags.c_contiguous and np.isfinite(parameter).all(), "Invalid mutable parameter")
        require(type(state["requires_grad"][name]) is bool, "Missing requires_grad state")
        gradient = gradients[name]
        require(gradient is None or (isinstance(gradient, np.ndarray) and gradient.shape == parameter.shape
                and gradient.dtype == parameter.dtype and gradient.flags.c_contiguous and np.isfinite(gradient).all()),
                "Incoming gradient differs from its named parameter")
    require(isinstance(state["buffers"], dict) and all(isinstance(v, np.ndarray) and v.flags.c_contiguous
            and v.dtype.kind in "buif" and np.isfinite(v).all() for v in state["buffers"].values()), "Invalid mutable buffer")
    optimizer, names = state["optimizer"], state["optimizer_parameter_names"]
    require(set(optimizer) == {"kind", "state", "param_groups"} and optimizer["kind"] == "SGD", "Unsupported optimizer state")
    require(isinstance(names, dict) and all(type(k) is int and k >= 0 for k in names)
            and len(names) == len(set(names.values())) == len(parameters)
            and set(names.values()) == set(parameters), "Optimizer parameter-name map differs")
    ids = [index for group in optimizer["param_groups"] for index in group["params"]]
    require(all(type(index) is int for index in ids) and len(ids) == len(set(ids)) == len(names)
            and set(ids) == set(names), "Optimizer parameter order/inventory differs")
    for group in optimizer["param_groups"]:
        require(set(group) == {"params", "lr", "momentum", "dampening", "weight_decay", "nesterov", "maximize",
                "foreach", "differentiable", "fused"}, "Incomplete SGD parameter-group configuration")
        require(all(type(group[k]) in (int, float) and np.isfinite(group[k]) and group[k] >= 0
                    for k in ("lr", "momentum", "dampening", "weight_decay")), "Invalid SGD scalar")
        require(all(type(group[k]) is bool for k in ("nesterov", "maximize", "differentiable"))
                and all(group[k] is None or type(group[k]) is bool for k in ("foreach", "fused")), "Invalid SGD flags")
    require(all(type(k) is int for k in optimizer["state"]) and set(optimizer["state"]) <= set(names), "Unknown optimizer state parameter")
    for index, fields in optimizer["state"].items():
        require(set(fields) <= {"momentum_buffer"}, "Unsupported SGD state field")
        if "momentum_buffer" in fields:
            momentum, parameter = fields["momentum_buffer"], parameters[names[index]]
            require(isinstance(momentum, np.ndarray) and momentum.shape == parameter.shape
                    and momentum.dtype == parameter.dtype and np.isfinite(momentum).all(), "Momentum buffer differs")
    rng = state["rng"]
    require(set(rng) == {"torch_cpu", "python", "numpy", "named"}, "RNG inventory differs")
    require(isinstance(rng["torch_cpu"], np.ndarray) and rng["torch_cpu"].dtype == np.uint8
            and rng["torch_cpu"].ndim == 1 and rng["torch_cpu"].size > 0, "Missing Torch CPU RNG bytes")
    require(type(rng["python"]) is tuple and type(rng["numpy"]) is tuple and isinstance(rng["named"], dict), "Missing other RNG state")
    cursor, tape = state["cursor"], state["remaining_schedule"]
    require(set(cursor) == {"seed", "schedule_id", "path_kind", "clock", "total_steps", "remaining_steps",
            "decision_index", "guard_grain", "baseline_action_index", "schedule_sha256"}, "Logical cursor inventory differs")
    require(all(type(cursor[key]) is int for key in ("seed", "schedule_id", "clock", "total_steps",
            "remaining_steps", "decision_index", "guard_grain", "baseline_action_index")), "Logical cursor requires exact integer types")
    require(cursor["seed"] in BASELINE and cursor["schedule_id"] in range(6000, 6004)
            and cursor["path_kind"] in ("baseline", "balanced", "ordinary", "field", "richer"), "Unregistered path identity")
    clock = cursor["clock"]
    require(type(clock) is int and clock in range(0, 289, 48) and cursor["total_steps"] == 288
            and cursor["remaining_steps"] == 288 - clock and cursor["decision_index"] == clock // 48
            and cursor["guard_grain"] == 48 and cursor["baseline_action_index"] == BASELINE[cursor["seed"]], "Clock/budget/guard semantics differ")
    require(type(tape) is list and len(tape) == 288 - clock and digest(tape) == cursor["schedule_sha256"], "Paired future schedule identity differs")
    for step, row in enumerate(tape, clock):
        require(set(row) == {"step", "adapt_seed", "clean_seed", "noise_seed", "condition"}
                and type(row["step"]) is int and row["step"] == step
                and row["condition"] in ("clean", "occlusion", "missing", "heavy_noise")
                and all(type(row[k]) is int and row[k] >= 0 for k in ("adapt_seed", "clean_seed", "noise_seed")), "Invalid paired schedule mark")
    return True


def seal(state, expected_environment_sha256):
    validate(state, expected_environment_sha256)
    raw = dumps(state)
    return raw, hashlib.sha256(raw).hexdigest()


def restore(raw, expected_sha256, expected_environment_sha256, maximum_bytes):
    state = loads(raw, expected_sha256, maximum_bytes)
    validate(state, expected_environment_sha256)
    return state


def _ledger_error(before, after):
    if type(after) is not dict or not all(type(k) is str and k and type(v) is int and v >= 0 for k, v in after.items()):
        return "External work ledger has invalid counter names or values"
    if any(after.get(k, -1) < v for k, v in before.items()):
        return "External work ledger regressed or removed an earlier counter"
    return None


def fork_all(raw, expected_sha256, environment_sha256, action_order, transition, work_ledger):
    """Generic synthetic harness; caller owns immutable evidence and monotone costs.

    Restoring logical remaining_steps never restores the external execution
    ledger. No Torch object, scientific transition or model is constructed here.
    """
    action_order = tuple(action_order)
    require(all(type(action) is int for action in action_order) and sorted(action_order) == [0, 1, 2, 3],
            "Every integer action must appear exactly once")
    require(_ledger_error({}, work_ledger) is None, "Invalid initial external work ledger")
    result = {"complete": False, "branches": {}, "failure": None}
    for action in action_order:
        state = restore(raw, expected_sha256, environment_sha256, len(raw))
        before = dict(work_ledger)
        try:
            outcome = transition(state, action, work_ledger)
            ledger_error = _ledger_error(before, work_ledger)
            require(ledger_error is None, ledger_error)
            validate(state, environment_sha256)
            result["branches"][action] = {"state": state, "state_sha256": digest(state), "outcome": outcome}
        except Exception as error:
            ledger_error = _ledger_error(before, work_ledger)
            result["failure"] = {"action": action, "type": type(error).__name__, "message": str(error),
                                 "last_state": state, "work_before": before, "work_after": dict(work_ledger),
                                 "work_ledger_integrity_failure": ledger_error is not None,
                                 "work_ledger_integrity_error": ledger_error}
            return result
    require(set(result["branches"]) == {0, 1, 2, 3}, "Incomplete branch inventory")
    result["complete"] = True
    return result
