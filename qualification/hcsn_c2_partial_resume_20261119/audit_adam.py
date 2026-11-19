"""Independent NumPy arithmetic for the first genuinely resumed AdamW update."""

import math

import numpy as np


def verify_first_adam(before, after, gradients):
    names = [name for name in before["model"] if name in gradients]
    groups = before["optimizer"]["param_groups"]
    slots = [slot for group in groups for slot in group["params"]]
    if len(names) != 11 or len(names) != len(gradients) or len(slots) != len(names):
        raise ValueError("complete first clipped gradients and parameter order required")
    # state_dict and named_parameters preserve module registration order; buffers
    # and frozen parameters are removed by the exact saved gradient-name set.
    position, maxima, coordinates = 0, {}, 0
    for group in groups:
        if group.get("amsgrad") or group.get("maximize") or group["weight_decay"] != 0:
            raise ValueError("unchanged original AdamW configuration required")
        beta1, beta2 = group["betas"]
        for slot in group["params"]:
            name = names[position]
            position += 1
            old, new = before["optimizer"]["state"][slot], after["optimizer"]["state"][slot]
            g = gradients[name].numpy()
            p = before["model"][name].numpy()
            if g.shape != p.shape or not np.isfinite(g).all():
                raise ValueError("finite correctly shaped clipped gradient required")
            age = float(old["step"]) + 1
            if float(new["step"]) != age or age != before["main_updates"] + 1:
                raise ValueError("first resumed AdamW age")
            mean = beta1 * old["exp_avg"].numpy() + (1 - beta1) * g
            square = beta2 * old["exp_avg_sq"].numpy() + (1 - beta2) * g * g
            updated = p - group["lr"] / (1 - beta1 ** age) * mean / (
                np.sqrt(square) / math.sqrt(1 - beta2 ** age) + group["eps"])
            errors = {"exp_avg": float(np.max(np.abs(mean - new["exp_avg"].numpy()))),
                      "exp_avg_sq": float(np.max(np.abs(square - new["exp_avg_sq"].numpy()))),
                      "parameter": float(np.max(np.abs(updated - after["model"][name].numpy())))}
            if not all(math.isfinite(v) and v <= 1e-12 for v in errors.values()):
                raise ValueError("independent first AdamW arithmetic failed: " + name + " " + str(errors))
            maxima[name] = errors
            coordinates += g.size
    return {"parameters": len(names), "gradient_coordinates": coordinates,
            "absolute_arithmetic_bound": 1e-12, "per_parameter_max_absolute_difference": maxima,
            "maximum_absolute_difference": max(v for row in maxima.values() for v in row.values()),
            "optimizer_calls": 0, "forward_backward_calls": 0,
            "scope": "Stored clipped gradients, full restored moments and parameter arithmetic; no regenerated gradient or new optimizer execution."}
