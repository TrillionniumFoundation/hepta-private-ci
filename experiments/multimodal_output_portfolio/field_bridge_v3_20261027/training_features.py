"""Prospective H12 / common richer30 measurements for V3 terminal control."""

import hashlib

import numpy as np
import torch

from ..field_bridge_20261027.adapters import local_parameters
from .learning import forward, hard_panel, schedule, state_identity, update
from .training_common import configuration, require


H7_NAMES = ("current_hard_value", "adapt_image_bce", "adapt_text_ce", "clean_joint_loss",
            "effective_operator_displacement", "momentum_rms", "normalized_learning_time")
DIRECTION_NAMES = ("next_weighted_clipped_gradient_rms", "gradient_momentum_cosine",
                   "response_image_bce_derivative_along_v", "response_text_ce_derivative_along_v",
                   "clean_joint_loss_derivative_along_v")
EXTRA_NAMES = ("adapt_digit_ce", "clean_image_bce", "clean_text_ce", "clean_digit_ce",
               "module_displacement_0", "module_displacement_1", "module_displacement_2", "module_displacement_3",
               "module_displacement_4", "module_displacement_5", "module_displacement_6", "module_displacement_7",
               "text_margin_mean", "text_margin_q10", "image_margin_mean", "image_margin_q10",
               "text_margin_below_025", "image_margin_below_01")
NAMES = H7_NAMES + DIRECTION_NAMES + EXTRA_NAMES


def tensor_hash(values):
    result = hashlib.sha256()
    for value in values:
        if value is None:
            result.update(b"none\0")
        else:
            result.update(str((tuple(value.shape), str(value.dtype))).encode() + b"\0")
            result.update(value.detach().cpu().contiguous().numpy().tobytes())
    return result.hexdigest()


def probe_losses(context, model):
    """Sample-weighted teacher losses; the response image/text share one graph."""
    p, values = configuration(context.protocol), {}
    for name, panel in (("adapt", context.probe), ("clean", context.guard)):
        total = sum(len(part.batch.source_ids) for part in panel)
        accumulated = {}
        for index, part in enumerate(panel):
            n = len(part.batch.source_ids)
            output = forward(model, part.batch, context.action, p["probe_forward_seed_offset"] + part.noise_seed,
                             True, context.costs, name + "_feature_probe")
            measured = model.loss(output, part.batch.target)
            for component in ("image_bce", "text_ce", "digit_ce", "joint"):
                accumulated[component] = accumulated.get(component, 0) + measured[component].mean() * n / total
        values[name] = accumulated
    return values


@torch.inference_mode()
def margins(context, model):
    text, image = [], []
    observer = context.observers["reward"]
    for part in context.probe:
        output = forward(model, part.batch, context.action, part.noise_seed, False,
                         context.costs, "margin_generator")
        ordered = output.text_logits[:, [1, 3]].topk(2, dim=-1).values
        text.extend((ordered[:, :, 0] - ordered[:, :, 1]).reshape(-1).tolist())
        pixels = (output.image_logits.sigmoid() * 255).round() / 255
        for digit in (pixels[:, :, :, :28], pixels[:, :, :, 28:]):
            context.costs.add("margin_reward_observer_calls")
            context.costs.add("margin_reward_observer_digit_examples", len(digit))
            ordered = observer(digit).softmax(-1).topk(2, dim=-1).values
            image.extend((ordered[:, 0] - ordered[:, 1]).tolist())
    return [float(np.mean(text)), float(np.quantile(text, .1)), float(np.mean(image)),
            float(np.quantile(image, .1)), float(np.mean(np.asarray(text) < .25)),
            float(np.mean(np.asarray(image) < .1))]


def measure_state(context, model, optimizer, step, schedule_id, retain=False):
    """Preserve parameters, optimizer, incoming gradient objects/values, and RNG."""
    if torch.is_inference_mode_enabled():
        raise ValueError("V3 direction measurements require autograd")
    p, costs = configuration(context.protocol), context.costs
    require(isinstance(optimizer, torch.optim.SGD), "Only the frozen plain-SGD dynamics are supported")
    groups = {}
    for group in optimizer.param_groups:
        require(not group.get("nesterov", False) and not group.get("maximize", False)
                and group.get("dampening", 0) == 0 and group.get("weight_decay", 0) == 0
                and group["momentum"] == p["momentum"], "Optimizer direction semantics changed")
        for parameter in group["params"]:
            require(id(parameter) not in groups, "Duplicate optimizer parameter")
            groups[id(parameter)] = group
    parameters = local_parameters(model)
    require(set(groups) == {id(parameter) for parameter in parameters}, "Incomplete optimizer parameter inventory")
    before, before_cost = state_identity(model, optimizer), costs.snapshot()
    incoming = [parameter.grad for parameter in parameters]
    incoming_hash, rng = tensor_hash(incoming), torch.get_rng_state().clone()
    try:
        current = hard_panel(model, context.probe, {"reward": context.observers["reward"]}, context.action,
                             context.protocol, costs, "current_hard_value", retain=retain)
        with torch.enable_grad():
            next_schedule = schedule(context.seed, schedule_id, step, 1, context.protocol)[0]
            adapt, rehearsal = context.batches(next_schedule)
            next_gradient = update(model, context.original, optimizer, adapt, rehearsal, context.action, 0.,
                                   next_schedule["noise_seed"], context.protocol, costs, name="directional")
            gradients, momenta, directions = [], [], []
            for parameter in parameters:
                g = parameter.grad.detach().clone() if parameter.grad is not None else torch.zeros_like(parameter)
                carried = optimizer.state.get(parameter, {}).get("momentum_buffer")
                m = torch.zeros_like(parameter) if carried is None else carried.detach().clone()
                v = m * groups[id(parameter)]["momentum"] + g if parameter.grad is not None else torch.zeros_like(parameter)
                gradients.append(g)
                momenta.append(m)
                directions.append(v.detach())
            g2 = sum(float(value.double().square().sum()) for value in gradients)
            m2 = sum(float(value.double().square().sum()) for value in momenta)
            gm = sum(float((g.double() * m.double()).sum()) for g, m in zip(gradients, momenta, strict=True))
            cosine = min(1., max(-1., gm / (g2 * m2) ** .5)) if g2 * m2 > 0 else 0.
            losses = probe_losses(context, model)
            derivative_losses = [losses["adapt"]["image_bce"], losses["adapt"]["text_ce"], losses["clean"]["joint"]]
            derivatives = []
            for index, loss in enumerate(derivative_losses):
                probe = torch.autograd.grad(loss, parameters, retain_graph=index == 0, allow_unused=True)
                derivatives.append(sum(float((gradient.detach().double() * v.double()).sum())
                                       for gradient, v in zip(probe, directions, strict=True) if gradient is not None))
                costs.add("feature_probe_reverse_calls")
                costs.add("feature_probe_reverse_examples", sum(len(part.batch.source_ids)
                          for part in (context.probe if index < 2 else context.guard)))
            direction = [(g2 / sum(value.numel() for value in gradients)) ** .5, cosine, *derivatives]
            delta = [float(((module.up @ module.down).norm() / module.base.weight.norm().clamp_min(1e-12)).detach())
                     for module in (model.get_submodule(name) for name in p["adapter_modules"])]
            h7 = [current["means"]["reward"], float(losses["adapt"]["image_bce"].detach()),
                  float(losses["adapt"]["text_ce"].detach()), float(losses["clean"]["joint"].detach()),
                  float(np.sqrt(np.mean(np.square(delta)))), (m2 / sum(value.numel() for value in momenta)) ** .5,
                  step / p["steps"]]
            richer = [float(losses["adapt"]["digit_ce"].detach()), float(losses["clean"]["image_bce"].detach()),
                      float(losses["clean"]["text_ce"].detach()), float(losses["clean"]["digit_ce"].detach()), *delta]
        vector = h7 + direction + richer + margins(context, model)
        require(len(vector) == len(NAMES) == 30 and np.isfinite(vector).all(), "Invalid richer30 field")
        measured = {"gradient_sha256": tensor_hash(gradients), "momentum_sha256": tensor_hash(momenta),
                    "direction_sha256": tensor_hash(directions), "gradient_l2": g2 ** .5,
                    "momentum_l2": m2 ** .5, "gradient_momentum_dot": gm, "next_gradient": next_gradient,
                    "direction_convention": "detached positive plain-SGD beta*m+clipped_g; motion is -lr*multiplier*v",
                    "weighted_objective": "(adapt+.5*rehearsal)/1.5, each including the same .1 teacher anchor"}
    finally:
        for parameter, gradient in zip(parameters, incoming, strict=True):
            parameter.grad = gradient
    require(state_identity(model, optimizer) == before and tensor_hash([p.grad for p in parameters]) == incoming_hash
            and torch.equal(rng, torch.get_rng_state()), "Feature measurement mutated training state, gradients, or RNG")
    return vector, current, {"names": list(NAMES), "before": before, "state_grad_rng_invariant": True,
                             "measured": measured, "resources": costs.since(before_cost)}
