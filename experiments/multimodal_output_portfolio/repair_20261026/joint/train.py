"""Jointly update the original generator and plan gate; preserve a frozen teacher.

The gradient is a stated surrogate. Only independent post-codec observations
in evaluate.py can establish output benefit; a decreasing surrogate cannot.
"""

from copy import deepcopy
import hashlib
import math
import time

import torch
from torch.nn import functional as F

from ...v6.data import DIGIT_OFFSET, make_batch
from ...v6.neural import parameter_hash, snapshot_from_model
from ...v6.plan_training import ControlledSnapshot, PLANS
from .protocol import PROTOCOL as P


def apply_plan(model, state, plan):
    for action in plan:
        state = model.step(state, action)
    return state


def soft_utility(output, target, observer):
    pixels = output.image_logits.sigmoid()
    quantized = pixels + ((pixels * 255).round() / 255 - pixels).detach()
    image_prob = torch.stack((observer(quantized[:, :, :, :28]).softmax(-1),
                              observer(quantized[:, :, :, 28:]).softmax(-1)), dim=1)
    words = output.text_logits.softmax(-1)
    digit_prob = words[:, [1, 3], DIGIT_OFFSET:DIGIT_OFFSET + 10]
    correct_image = image_prob.gather(-1, target.labels[:, :, None]).squeeze(-1).mean(1)
    correct_text = digit_prob.gather(-1, target.labels[:, :, None]).squeeze(-1).mean(1)
    correct_relation = words[:, 5].gather(1, target.text_tokens[:, 6:7]).squeeze(1)
    disagreement = 1 - (image_prob * digit_prob).sum(-1).mean(1)
    mse = (quantized - target.pixels).square().flatten(1).mean(1)
    loss = (.3 * (1 - correct_text) + .15 * (1 - correct_relation)
            + .35 * (1 - correct_image) + .1 * disagreement + .1 * mse)
    return 1 - 2 * loss


def portfolio_loss(logits, utilities, gamma):
    if gamma == 0:
        return -(logits.softmax(-1) * utilities.mean(-1)).sum(-1).mean()
    terms = logits.log_softmax(-1)[:, :, None] - gamma * utilities
    return ((torch.logsumexp(terms.flatten(1), dim=1)
             - math.log(utilities.shape[-1])) / gamma).mean()


def deploy(model, gate, observation, noise):
    """Public-only execution, same two-transition budget in every arm."""
    initial = model.encode(observation, noise)
    choices = gate(initial.context).argmax(-1)
    groups, positions = [], []
    from ...v6.neural import NeuralState
    for index, plan in enumerate(PLANS):
        ids = torch.where(choices == index)[0]
        if not len(ids):
            continue
        state = NeuralState(*(getattr(initial, field)[ids]
                              for field in ("h", "image", "text", "context")))
        groups.append(apply_plan(model, state, plan))
        positions.append(ids)
    order = torch.cat(positions).argsort()
    state = NeuralState(*(torch.cat([getattr(group, field) for group in groups])[order]
                          for field in ("h", "image", "text", "context")))
    return model.decode(state), choices


def fit(original, corpus, observer, seed, arm):
    if arm not in {"joint_mean", "joint_entropic"}:
        raise ValueError("Unknown matched training arm")
    model = deepcopy(original._base._model).train().requires_grad_(True)
    gate = deepcopy(original._gate).train().requires_grad_(True)
    teacher = original._base._model
    if observer.training or any(p.requires_grad for p in observer.parameters()):
        raise ValueError("Training observer must be frozen")
    observer_hash, teacher_hash = parameter_hash(observer), parameter_hash(teacher)
    before = {name: parameter_hash(module) for name, module in model.named_children()}
    gate_before = parameter_hash(gate)
    optimizer = torch.optim.Adam([
        {"params": model.parameters(), "lr": P["learning_rate_core"]},
        {"params": gate.parameters(), "lr": P["learning_rate_gate"]}])
    generator = torch.Generator().manual_seed(seed * 1009 + 2701)
    schedule, history, gradients = hashlib.sha256(), [], {}
    started = time.perf_counter_ns()
    gamma = 0. if arm == "joint_mean" else P["gamma"]
    for step in range(P["steps"]):
        batch_seed = seed * 1000003 + step
        batch = make_batch(corpus, "train", P["batch_size"], batch_seed)
        noise = torch.randn(P["scenarios"], P["batch_size"], model.hidden, generator=generator)
        schedule.update(str(batch_seed).encode())
        schedule.update(noise.numpy().tobytes())
        utilities, supervised, anchor, logits = [], [], [], None
        with torch.no_grad():
            teacher_state = apply_plan(teacher, teacher.encode(batch.observation, noise[0]), PLANS[-1])
            teacher_output = teacher.decode(teacher_state, batch.target.text_tokens)
        for scenario in range(P["scenarios"]):
            state = model.encode(batch.observation, noise[scenario])
            if logits is None:
                logits = gate(state.context)
            values = []
            for plan in PLANS:
                final = apply_plan(model, state, plan)
                output = model.decode(final)
                values.append(soft_utility(output, batch.target, observer))
                forced = model.decode(final, batch.target.text_tokens)
                supervised.append(model.loss(forced, batch.target)["joint"])
                if scenario == 0:
                    pixel_anchor = (forced.image_logits.sigmoid()
                                    - teacher_output.image_logits.sigmoid()).square().mean()
                    text_anchor = F.kl_div(forced.text_logits.log_softmax(-1),
                                          teacher_output.text_logits.softmax(-1), reduction="batchmean")
                    anchor.append(pixel_anchor + .1 * text_anchor)
            utilities.append(torch.stack(values, dim=1))
        utility = torch.stack(utilities, dim=-1)
        objective = portfolio_loss(logits, utility, gamma)
        objective = (objective + P["supervised_anchor"] * torch.stack(supervised).mean()
                     + P["distillation_anchor"] * torch.stack(anchor).mean())
        if not torch.isfinite(objective):
            raise FloatingPointError("Non-finite joint objective")
        optimizer.zero_grad(set_to_none=True)
        objective.backward()
        for name, module in [*model.named_children(), ("plan_gate", gate)]:
            norm = sum(float(p.grad.abs().sum()) for p in module.parameters() if p.grad is not None)
            gradients[name] = max(gradients.get(name, 0.), norm)
        torch.nn.utils.clip_grad_norm_([*model.parameters(), *gate.parameters()], P["gradient_clip"])
        optimizer.step()
        history.append(float(objective.detach()))
        if step % 40 == 0:
            print(f"joint seed={seed} arm={arm} step={step} objective={history[-1]:.6f}", flush=True)
    if observer_hash != parameter_hash(observer) or teacher_hash != parameter_hash(teacher):
        raise RuntimeError("Training mutated its frozen observer or teacher")
    after = {name: parameter_hash(module) for name, module in model.named_children()}
    changed = {name: before[name] != after[name] for name in before}
    evidence = {"seed": seed, "arm": arm, "steps": P["steps"], "parameter_changes": changed,
                "gate_changed": gate_before != parameter_hash(gate), "gradient_abs_sum_max": gradients,
                "schedule_sha256": schedule.hexdigest(), "initial_modules": before, "final_modules": after,
                "objective_history": history, "observer_sha256": observer_hash,
                "frozen_teacher_sha256": teacher_hash, "wall_ns": time.perf_counter_ns() - started,
                "trainable_parameters": sum(p.numel() for p in model.parameters()) + sum(p.numel() for p in gate.parameters()),
                "training_decoder_examples": P["steps"] * P["batch_size"] * (P["scenarios"] * len(PLANS) * 2 + 1),
                "training_observer_digit_examples": P["steps"] * P["batch_size"] * P["scenarios"] * len(PLANS) * 2,
                "exact_actual_output_reward_gradient": False}
    snapshot = ControlledSnapshot(snapshot_from_model(model, {"repair_study": P["study"]}), gate,
                                  {"repair_arm": arm, "seed": seed})
    return snapshot, evidence
