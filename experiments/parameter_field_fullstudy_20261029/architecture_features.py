"""Twelve declared, paid stage-C observations with no future-tail outcomes.

The displacement coordinate measures the full generator against its own frozen
warmstart. It is not relabeled as the old eight-LoRA operator displacement.
"""

import numpy as np
import torch

from .architecture_kernel import batch_digest, objective, output, tape_seed, training_batches
from .architecture_state import digest


FIELD_NAMES = (
    "current_hard_value", "adapt_image_bce", "adapt_text_ce", "clean_joint_loss",
    "relative_full_parameter_displacement", "momentum_rms", "normalized_learning_time",
    "next_weighted_clipped_gradient_rms", "gradient_momentum_cosine",
    "response_image_bce_derivative_along_v", "response_text_ce_derivative_along_v",
    "clean_joint_loss_derivative_along_v",
)


def probe_losses(context, model):
    result = {}
    for name, panel in (("adapt", context.probe), ("clean", context.guard)):
        count, sums = sum(len(batch.source_ids) for batch, _ in panel), {}
        for batch, noise_seed in panel:
            predicted = output(model, batch, noise_seed, ("couple",), True,
                               context.work, name + "_feature_generator")
            losses = model.loss(predicted, batch.target)
            for key in ("image_bce", "text_ce", "joint"):
                sums[key] = sums.get(key, 0) + losses[key].sum() / count
        result[name] = sums
    return result


def measure(context, model, optimizer, step, schedule):
    if torch.is_inference_mode_enabled():
        raise ValueError("Stage-C direction observations require autograd")
    saved, before_work = context.snapshot(model, optimizer), context.work.snapshot()
    before = digest(saved)
    parameters = list(model.parameters())
    count = sum(parameter.numel() for parameter in parameters)
    try:
        current = context.hard(model, context.probe, "feature_hard")
        batches = training_batches(context.corpus, context.plan, context.seed, schedule, step)
        noise = tape_seed(context.seed, "continuation", schedule, step, "noise")
        optimizer.zero_grad(set_to_none=True)
        loss = objective(model, context.teacher, batches, noise, ("couple",), context.plan, context.work)
        loss.backward()
        context.work.add("directional_backward_calls")
        context.work.add("directional_backward_examples", sum(len(batch.source_ids) for batch in batches))
        norm = torch.nn.utils.clip_grad_norm_(parameters, context.plan.gradient_clip)
        if not torch.isfinite(loss) or not torch.isfinite(norm):
            raise FloatingPointError("Nonfinite current directional gradient")
        gradients, momenta, directions = [], [], []
        for parameter in parameters:
            gradient = torch.zeros_like(parameter) if parameter.grad is None else parameter.grad.detach().clone()
            carried = optimizer.state.get(parameter, {}).get("momentum_buffer")
            momentum = torch.zeros_like(parameter) if carried is None else carried.detach().clone()
            direction = (torch.zeros_like(parameter) if parameter.grad is None else
                         context.plan.momentum * momentum + gradient)
            gradients.append(gradient)
            momenta.append(momentum)
            directions.append(direction)
        g2 = sum(float(g.double().square().sum()) for g in gradients)
        m2 = sum(float(m.double().square().sum()) for m in momenta)
        gm = sum(float((g.double() * m.double()).sum()) for g, m in zip(gradients, momenta, strict=True))
        cosine = np.clip(gm / (g2 * m2) ** .5, -1., 1.) if g2 * m2 else 0.
        losses = probe_losses(context, model)
        derivatives = []
        for index, value in enumerate((losses["adapt"]["image_bce"], losses["adapt"]["text_ce"],
                                       losses["clean"]["joint"])):
            gradient = torch.autograd.grad(value, parameters, retain_graph=index == 0, allow_unused=True)
            derivatives.append(sum(float((g.detach().double() * v.double()).sum())
                                   for g, v in zip(gradient, directions, strict=True) if g is not None))
            context.work.add("feature_probe_reverse_calls")
            panel = context.probe if index < 2 else context.guard
            context.work.add("feature_probe_reverse_examples", sum(len(batch.source_ids) for batch, _ in panel))
        displacement = sum(float((p.detach().double() - q.detach().double()).square().sum())
                           for p, q in zip(model.parameters(), context.teacher.parameters(), strict=True))
        scale = sum(float(q.detach().double().square().sum()) for q in context.teacher.parameters())
        vector = [current["mean"], float(losses["adapt"]["image_bce"].detach()),
                  float(losses["adapt"]["text_ce"].detach()), float(losses["clean"]["joint"].detach()),
                  (displacement / max(scale, 1e-24)) ** .5, (m2 / count) ** .5,
                  step / context.plan.steps, (g2 / count) ** .5, float(cosine), *derivatives]
        receipt = {"gradient_sha256": digest(gradients), "momentum_sha256": digest(momenta),
                   "direction_sha256": digest(directions), "current_directional_loss": float(loss.detach()),
                   "current_batch_sha256": batch_digest(batches), "noise_seed": noise}
    except BaseException as error:
        context.last_failure = {
            "state": context.snapshot(model, optimizer),
            "metadata": {"operation": "field_measurement", "step": step, "schedule": schedule,
                         "before": before, "error_type": type(error).__name__,
                         "message": str(error), "work": context.work.snapshot()},
        }
        raise
    finally:
        context.restore(model, optimizer, saved)
    if len(vector) != 12 or not np.isfinite(vector).all():
        raise FloatingPointError("Invalid stage-C field measurement")
    return np.asarray(vector, dtype=np.float64), current, {
        "field_names": list(FIELD_NAMES), "state_sha256": before, "state_restored": True,
        "measurement": receipt, "work_before": before_work, "work_after": context.work.snapshot(),
    }
