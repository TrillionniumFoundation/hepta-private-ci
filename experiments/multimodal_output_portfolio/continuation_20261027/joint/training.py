"""Train actual-outcome moment predictions and replay-protected generators.

The generator derivative is an explicitly labelled supervised proxy with
detached actual-risk weights. The controller learns the deployed greedy
action's conditional exponential moment without a soft-plan deployment gap.
"""

from copy import deepcopy
import hashlib
import time

import torch
from torch.nn import functional as F

from ...v6.data import render_tokens
from ...v6.neural import parameter_hash, snapshot_from_model
from ...v6.observer import observe_tensors
from ...v6.plan_training import ControlledSnapshot, PLANS, _png_roundtrip
from ...repair_20261026.joint.train import apply_plan
from .data import training_batch
from .protocol import PROTOCOL as P, checksum, write_json


def predicted_moment(logits):
    """Positive bounded moment; its order exactly reverses argmax(raw logits)."""
    return torch.exp(-P["gamma"] * torch.tanh(logits / P["gamma"]))


def actual_utilities(output, target, observer):
    pixels, hashes = _png_roundtrip(output.image_logits.sigmoid())
    captions = [render_tokens(row).encode("utf-8").decode("utf-8") for row in output.token_ids]
    scores = observe_tensors(observer, pixels, captions, target.pixels, target.labels)
    values = torch.tensor([row["utility"] for row in scores])
    return values, hashes, captions


def distillation(output, teacher, count):
    pixel = (output.image_logits[:count].sigmoid() - teacher.image_logits[:count].sigmoid()).square().flatten(1).mean(1)
    text = F.kl_div(output.text_logits[:count].log_softmax(-1),
                    teacher.text_logits[:count].softmax(-1), reduction="none").sum(-1).mean(-1)
    return (pixel + .1 * text).mean()


def fit(original, corpus, observer, seed, arm, output, steps=None):
    if arm not in P["arms"][1:]:
        raise ValueError("Unknown update arm")
    steps = P["steps"] if steps is None else steps
    model = deepcopy(original._base._model).train().requires_grad_(True)
    gate = deepcopy(original._gate).train().requires_grad_(True)
    teacher = original._base._model
    before = {name: parameter_hash(module) for name, module in model.named_children()}
    gate_before, teacher_hash, observer_hash = parameter_hash(gate), parameter_hash(teacher), parameter_hash(observer)
    optimizer = torch.optim.Adam([
        {"params": model.parameters(), "lr": P["learning_rate_core"]},
        {"params": gate.parameters(), "lr": P["learning_rate_gate"]}])
    schedule, outcomes = hashlib.sha256(), hashlib.sha256()
    history, checkpoints = [], []
    rng = torch.Generator().manual_seed(seed * 1009 + 270027)
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    for step in range(steps):
        batch, batch_seed = training_batch(corpus, seed, step)
        noise = torch.randn(P["batch_size"], model.hidden, generator=rng)
        schedule.update(str(batch_seed).encode())
        schedule.update(noise.numpy().tobytes())
        initial = model.encode(batch.observation, noise)
        logits = gate(initial.context.detach())
        choices = logits.detach().argmax(-1)
        utilities, losses, anchors = [], [], []
        with torch.no_grad():
            teacher_initial = teacher.encode(batch.observation, noise)
        for plan in PLANS:
            final = apply_plan(model, initial, plan)
            with torch.no_grad():
                delivered = model.decode(final)
                value, hashes, captions = actual_utilities(delivered, batch.target, observer)
                outcomes.update("\n".join(hashes + captions).encode())
                teacher_output = teacher.decode(apply_plan(teacher, teacher_initial, plan), batch.target.text_tokens)
            forced = model.decode(final, batch.target.text_tokens)
            parts = model.loss(forced, batch.target)
            losses.append(parts["image_bce"] + .7 * parts["text_ce"] + .25 * parts["digit_ce"])
            anchors.append(distillation(forced, teacher_output, P["batch_size"] // 2))
            utilities.append(value)
        actual = torch.stack(utilities, dim=1)
        per_plan_loss = torch.stack(losses, dim=1)
        selected_actual = actual.gather(1, choices[:, None]).squeeze(1)
        selected_loss = per_plan_loss.gather(1, choices[:, None]).squeeze(1)
        weights = (torch.softmax(-P["gamma"] * selected_actual, dim=0) * len(selected_actual)
                   if arm == "joint_risk" else torch.ones_like(selected_actual))
        generator_loss = (weights.detach() * selected_loss).mean() + .1 * per_plan_loss.mean() + .3 * torch.stack(anchors).mean()
        moments = torch.exp(-P["gamma"] * actual)
        gate_loss = (predicted_moment(logits) - moments).square().mean()
        objective = generator_loss + gate_loss
        if not torch.isfinite(objective):
            raise FloatingPointError("Nonfinite actual-moment/replay objective")
        optimizer.zero_grad(set_to_none=True)
        objective.backward()
        torch.nn.utils.clip_grad_norm_([*model.parameters(), *gate.parameters()], P["gradient_clip"])
        optimizer.step()
        history.append({"step": step + 1, "generator_proxy": float(generator_loss.detach()),
                        "moment_mse": float(gate_loss.detach()), "actual_mean_utility": float(selected_actual.mean()),
                        "maximum_risk_weight": float(weights.max()),
                        "selected_plans": torch.bincount(choices, minlength=4).tolist()})
        if (step + 1) % 50 == 0:
            print(f"train seed={seed} arm={arm} step={step + 1} proxy={history[-1]['generator_proxy']:.5f} moment={history[-1]['moment_mse']:.5f}", flush=True)
        if step + 1 in P["checkpoints"] or step + 1 == steps:
            snapshot = ControlledSnapshot(snapshot_from_model(model, {"study": P["study"]}), gate,
                                          {"arm": arm, "seed": seed, "step": step + 1})
            path = output / f"seed-{seed}-{arm}-step-{step + 1}.pt"
            snapshot.save(path)
            reloaded = ControlledSnapshot.load(path)
            if reloaded.fingerprint != snapshot.fingerprint:
                raise RuntimeError("Checkpoint reload identity differs")
            checkpoints.append({"step": step + 1, "path": path.name, "sha256": checksum(path),
                                "snapshot_sha256": snapshot.fingerprint})
    if teacher_hash != parameter_hash(teacher) or observer_hash != parameter_hash(observer):
        raise RuntimeError("Frozen training reference mutated")
    after = {name: parameter_hash(module) for name, module in model.named_children()}
    evidence = {"seed": seed, "arm": arm, "steps": steps, "history": history, "checkpoints": checkpoints,
        "schedule_sha256": schedule.hexdigest(), "actual_training_output_sha256": outcomes.hexdigest(),
        "before": before, "after": after, "changed": {k: before[k] != after[k] for k in before},
        "gate_changed": gate_before != parameter_hash(gate), "observer_sha256": observer_hash,
        "teacher_sha256": teacher_hash, "wall_ns": time.perf_counter_ns() - started_wall,
        "cpu_ns": time.process_time_ns() - started_cpu,
        "training_counts": {"examples": steps * P["batch_size"], "model_encodes": steps * P["batch_size"],
            "model_transitions": steps * P["batch_size"] * 8,
            "model_decodes": steps * P["batch_size"] * 8,
            "teacher_encodes": steps * P["batch_size"],
            "teacher_transitions": steps * P["batch_size"] * 8,
            "teacher_decodes": steps * P["batch_size"] * 4,
            "actual_png_roundtrips": steps * P["batch_size"] * 4,
            "observer_digit_examples": steps * P["batch_size"] * 8},
        "exact_generator_actual_reward_gradient": False, "target_enters_deployment": False}
    write_json(output / f"TRAINING-{seed}-{arm}.json", evidence)
    return evidence
