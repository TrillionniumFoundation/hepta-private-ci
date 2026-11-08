"""Validated local restoration helpers for the bounded research candidate.

This is an in-memory rollback transaction, not a production durable owner.
The optimizer schema deliberately supports ordinary torch.optim.Adam only.
"""

import copy
from contextlib import contextmanager
import math

import torch
from torch import Tensor


ADAM_SCHEMA = "torch.optim.Adam.basic.v1"


def validate_model_state(module, candidate):
    expected = module.state_dict()
    if not isinstance(candidate, dict) or candidate.keys() != expected.keys() or any(
        not isinstance(value, Tensor) or value.shape != expected[name].shape
        or value.dtype != expected[name].dtype or not bool(torch.isfinite(value).all())
        for name, value in candidate.items()
    ):
        raise ValueError("checkpoint model keys, shapes, dtype or finite values mismatch")


@contextmanager
def rollback_on_error(module, optimizer):
    model_before = {name: value.detach().clone() for name, value in module.state_dict().items()}
    optimizer_before = copy.deepcopy(optimizer.state_dict()) if optimizer is not None else None
    rng_before = torch.random.get_rng_state().clone()
    try:
        yield
    except Exception:
        module.load_state_dict(model_before, strict=True)
        if optimizer is not None:
            optimizer.load_state_dict(optimizer_before)
        torch.random.set_rng_state(rng_before)
        raise


def _real(value, name, *, upper=None):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0 or (upper is not None and value >= upper)):
        raise ValueError(f"invalid Adam {name}")


def validate_adam_state(module, optimizer, candidate):
    """Validate moments against their actual destination parameters before load.

    Adam's scalar step is not a parameter-shaped moment. FP32 step counters for
    FP64 parameters and ordinary CPU step counters remain legal.
    """
    if type(optimizer) is not torch.optim.Adam:
        raise TypeError("this checkpoint profile supports torch.optim.Adam only")
    if not isinstance(candidate, dict) or set(candidate) != {"state", "param_groups"}:
        raise ValueError("invalid Adam state envelope")
    groups, states = candidate["param_groups"], candidate["state"]
    if not isinstance(groups, list) or not isinstance(states, dict) or len(groups) != len(optimizer.param_groups):
        raise ValueError("Adam parameter-group count/type mismatch")
    owned = {id(parameter) for parameter in module.parameters()}
    mapping, live_ids = {}, set()
    for saved, live in zip(groups, optimizer.param_groups):
        if not isinstance(saved, dict) or set(saved) != set(live):
            raise ValueError("Adam parameter-group schema mismatch")
        identifiers = saved["params"]
        if not isinstance(identifiers, list) or len(identifiers) != len(live["params"]):
            raise ValueError("Adam group parameter count mismatch")
        for name in ("lr", "eps", "weight_decay"):
            _real(saved[name], name)
        if "initial_lr" in saved:
            _real(saved["initial_lr"], "initial_lr")
        if not isinstance(saved["betas"], (tuple, list)) or len(saved["betas"]) != 2:
            raise ValueError("invalid Adam betas")
        for beta in saved["betas"]:
            _real(beta, "beta", upper=1.)
        for name in ("amsgrad", "maximize", "capturable", "differentiable", "decoupled_weight_decay"):
            if name in saved and not isinstance(saved[name], bool):
                raise ValueError(f"invalid Adam boolean {name}")
        for name in ("foreach", "fused"):
            if saved.get(name) is not None and not isinstance(saved[name], bool):
                raise ValueError(f"invalid Adam optional boolean {name}")
        if saved.get("capturable") or saved.get("differentiable") or saved.get("fused"):
            raise ValueError("capturable/differentiable/fused Adam is outside this checkpoint profile")
        for identifier, parameter in zip(identifiers, live["params"]):
            if (isinstance(identifier, bool) or not isinstance(identifier, int) or identifier < 0
                    or identifier in mapping or id(parameter) in live_ids or id(parameter) not in owned):
                raise ValueError("invalid, duplicate, or unowned Adam parameter mapping")
            mapping[identifier] = (parameter, saved["amsgrad"])
            live_ids.add(id(parameter))
    if any(identifier not in mapping for identifier in states):
        raise ValueError("Adam state refers to an unknown parameter")
    for identifier, entry in states.items():
        if not isinstance(entry, dict):
            raise ValueError("Adam per-parameter state must be a dictionary")
        if not entry:  # A parameter may not have received a gradient yet.
            continue
        parameter, amsgrad = mapping[identifier]
        expected = {"step", "exp_avg", "exp_avg_sq"} | ({"max_exp_avg_sq"} if amsgrad else set())
        if set(entry) != expected:
            raise ValueError("Adam moment schema mismatch")
        step = entry["step"]
        if isinstance(step, Tensor):
            if (step.ndim != 0 or step.requires_grad
                    or step.dtype not in (torch.float32, torch.float64, torch.int64)
                    or step.device.type != "cpu" and step.device != parameter.device):
                raise ValueError("Adam step must be a scalar counter on a supported device")
            step = float(step.detach())
        _real(step, "step")
        if step != math.floor(step):
            raise ValueError("Adam step must be an integer-valued counter")
        for name in expected - {"step"}:
            value = entry[name]
            if (not isinstance(value, Tensor) or value.shape != parameter.shape
                    or value.dtype != parameter.dtype or value.requires_grad
                    or value.device.type != "cpu" and value.device != parameter.device
                    or not bool(torch.isfinite(value).all())):
                raise ValueError(f"Adam {name} shape/dtype/device/finite mismatch")
            if name != "exp_avg" and bool((value < 0).any()):
                raise ValueError(f"Adam {name} must be nonnegative")
        if amsgrad and bool((entry["max_exp_avg_sq"] < entry["exp_avg_sq"]).any()):
            raise ValueError("Adam AMSGrad maximum is below its second moment")


def pack_adam_state(module, optimizer):
    if optimizer is None:
        return None
    state = copy.deepcopy(optimizer.state_dict())
    validate_adam_state(module, optimizer, state)
    return {"schema": ADAM_SCHEMA, "state": state,
            "parameter_names": _parameter_name_layout(module, optimizer)}


def _parameter_name_layout(module, optimizer):
    names = {id(parameter): name for name, parameter in module.named_parameters()}
    try:
        return [[names[id(parameter)] for parameter in group["params"]]
                for group in optimizer.param_groups]
    except KeyError as error:
        raise ValueError("optimizer contains a parameter not owned by the restored module") from error


def restore_adam_state(module, optimizer, payload):
    if optimizer is None:
        return
    if (not isinstance(payload, dict) or set(payload) != {"schema", "state", "parameter_names"}
            or payload["schema"] != ADAM_SCHEMA):
        raise ValueError("requested Adam restoration requires a supported optimizer schema")
    layout = payload["parameter_names"]
    if (not isinstance(layout, list) or any(not isinstance(group, list)
                                          or any(not isinstance(name, str) for name in group) for group in layout)
            or layout != _parameter_name_layout(module, optimizer)):
        raise ValueError("Adam parameter-name layout/order mismatch")
    validate_adam_state(module, optimizer, payload["state"])
    optimizer.load_state_dict(payload["state"])
