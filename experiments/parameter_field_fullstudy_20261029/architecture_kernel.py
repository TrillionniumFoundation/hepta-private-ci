"""Stage-C full-generator SGD, fixed source panels and guarded transactions.

This is a separately declared kernel, not a silent change to frozen V3/V5.
Incoming gradients are cleared after every completed microstep. Rejection
restores the complete entry state while logical time and all work advance.
"""

from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import time

import numpy as np
import torch
from torch.nn import functional as F

from experiments.multimodal_output_portfolio.v6.data import make_batch, render_tokens
from experiments.multimodal_output_portfolio.v6.neural import ACTIONS, parameter_hash
from experiments.multimodal_output_portfolio.v6.observer import observe_tensors
from .architecture_state import capture, digest, restore


@dataclass(frozen=True)
class ArchitecturePlan:
    development_seeds: tuple = (701, 702)
    evaluation_seeds: tuple = tuple(range(801, 809))
    bank_schedules: tuple = (7000, 7001, 7002, 7003)
    evaluation_schedule: int = 8000
    hidden: int = 32
    warmup_steps: int = 400
    steps: int = 96
    macro_steps: int = 16
    batch_size: int = 32
    rehearsal_batch_size: int = 16
    learning_rate: float = .01
    momentum: float = .9
    gradient_clip: float = 1.
    teacher_anchor: float = .1
    rehearsal_weight: float = .5
    noise_scale: float = .15
    multipliers: tuple = (0., .25, 1., 2.)
    baseline: int = 2
    conditions: tuple = ("heavy_noise", "missing", "occlusion", "clean")
    gradient_role: str = "fit_gradient"
    rehearsal_role: str = "fit_rehearsal"
    probe_role: str = "fit_probe"
    guard_role: str = "fit_guard"
    panel_batch_size: int = 32
    refinement_charge: float = .002
    threads: int = 1

    @classmethod
    def from_mapping(cls, values):
        unknown = set(values) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"Unknown architecture execution choices: {sorted(unknown)}")
        converted = dict(values)
        for key in ("development_seeds", "evaluation_seeds", "bank_schedules", "multipliers", "conditions"):
            if key in converted:
                converted[key] = tuple(converted[key])
        result = cls(**converted)
        if result.steps % result.macro_steps or result.baseline != 2 or result.multipliers[2] != 1.:
            raise ValueError("Stage-C clock or baseline differs")
        if result.warmup_steps < 5 or result.batch_size < 1 or result.rehearsal_batch_size < 1:
            raise ValueError("Invalid stage-C training budget")
        if len(set(result.bank_schedules)) != 4:
            raise ValueError("Four separately grouped bank schedules are required")
        if set(result.development_seeds) & set(result.evaluation_seeds):
            raise ValueError("Development and final-training seeds overlap")
        return result

    def to_dict(self):
        return asdict(self)


class Work:
    def __init__(self):
        self.values, self.phase = {}, "initialization"
        self.cpu_start, self.wall_start = time.process_time(), time.perf_counter()

    def add(self, name, amount=1):
        key = self.phase + "." + name
        self.values[key] = self.values.get(key, 0) + int(amount)

    def snapshot(self):
        return {"counts": dict(self.values), "cpu_seconds": time.process_time() - self.cpu_start,
                "wall_seconds": time.perf_counter() - self.wall_start}


def tape_seed(seed, phase, schedule, step, channel):
    raw = f"hepta-fullstudy-C:{seed}:{phase}:{schedule}:{step}:{channel}".encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") % (2 ** 63 - 1)


def output(model, batch, noise_seed, actions, teacher_tokens, work, role):
    generator = torch.Generator().manual_seed(noise_seed)
    noise = torch.randn(len(batch.source_ids), model.hidden, generator=generator)
    work.add(role + "_forward_calls")
    work.add(role + "_forward_examples", len(batch.source_ids))
    work.add(role + "_latent_steps", len(actions) * len(batch.source_ids))
    state = model.encode(batch.observation, noise)
    for action in actions:
        state = model.step(state, action)
    return model.decode(state, batch.target.text_tokens if teacher_tokens else None)


def anchor(current, original):
    image = (current.image_logits.sigmoid() - original.image_logits.sigmoid()).square().mean()
    text = F.kl_div(current.text_logits.log_softmax(-1), original.text_logits.softmax(-1), reduction="batchmean")
    return image + .1 * text


def objective(model, teacher, batches, noise_seed, actions, plan, work):
    losses = []
    for index, batch in enumerate(batches):
        predicted = output(model, batch, noise_seed + index * 1000003, actions, True, work, "generator")
        value = model.loss(predicted, batch.target)["joint"].mean()
        if teacher is not None:
            with torch.no_grad():
                reference = output(teacher, batch, noise_seed + index * 1000003, actions, True, work, "teacher")
            value = value + plan.teacher_anchor * anchor(predicted, reference)
        losses.append(value)
    return (losses[0] if len(losses) == 1 else
            (losses[0] + plan.rehearsal_weight * losses[1]) / (1 + plan.rehearsal_weight))


def update(model, optimizer, teacher, batches, noise_seed, actions, multiplier, plan, work, gradient_seen=None):
    optimizer.zero_grad(set_to_none=True)
    loss = objective(model, teacher, batches, noise_seed, actions, plan, work)
    loss.backward()
    work.add("backward_calls")
    work.add("backward_examples", sum(len(batch.source_ids) for batch in batches))
    if gradient_seen is not None:
        for name, parameter in model.named_parameters():
            if name not in gradient_seen and parameter.grad is not None and bool(parameter.grad.ne(0).any()):
                gradient_seen.add(name)
    norm = torch.nn.utils.clip_grad_norm_(model.parameters(), plan.gradient_clip)
    if not torch.isfinite(loss) or not torch.isfinite(norm):
        raise FloatingPointError("Stage-C objective or gradient is nonfinite")
    if multiplier:
        for group in optimizer.param_groups:
            group["lr"] = plan.learning_rate * multiplier
        optimizer.step()
        work.add("optimizer_steps")
    # This is part of the new C algorithm, not omitted checkpoint information.
    optimizer.zero_grad(set_to_none=True)
    work.add("scheduled_gradient_microsteps")
    return {"loss": float(loss.detach()), "unclipped_gradient_norm": float(norm),
            "optimizer_advanced": bool(multiplier), "incoming_gradients_after_step": "None"}


def training_batches(corpus, plan, seed, schedule, step, phase="continuation"):
    adapt_seed = tape_seed(seed, phase, schedule, step, "gradient")
    adapt = make_batch(corpus, plan.gradient_role, plan.batch_size, adapt_seed,
                       corruption=plan.conditions[step % len(plan.conditions)])
    if phase == "warmup":
        return [adapt]
    rehearsal = make_batch(corpus, plan.rehearsal_role, plan.rehearsal_batch_size,
                           tape_seed(seed, phase, schedule, step, "rehearsal"), corruption="clean")
    return [adapt, rehearsal]


def batch_digest(batches):
    return digest([{"ids": batch.source_ids, "pixels": batch.observation.pixels,
                    "mask": batch.observation.mask, "tokens": batch.observation.text_tokens,
                    "target_pixels": batch.target.pixels, "target_tokens": batch.target.text_tokens,
                    "labels": batch.target.labels} for batch in batches])


class Context:
    def __init__(self, model, corpus, reward_observer, seed, plan, work, resource_check=lambda: None):
        self.teacher = deepcopy(model).eval().requires_grad_(False)
        self.teacher_sha = parameter_hash(self.teacher)
        self.corpus, self.observer, self.seed, self.plan, self.work = corpus, reward_observer, seed, plan, work
        if reward_observer.training or any(p.requires_grad for p in reward_observer.parameters()):
            raise ValueError("The training reward observer must be immutable and in evaluation mode")
        self.observer_sha = parameter_hash(reward_observer)
        self.resource_check = resource_check
        self.last_failure = None
        self.probe = self.panel(plan.probe_role, plan.conditions)
        self.guard = self.panel(plan.guard_role, ("clean",))
        self.baseline_guard = self.hard(model, self.guard, "original_guard")["values"]
        self.identity = digest({"teacher": self.teacher_sha, "observer": self.observer_sha, "plan": plan.to_dict(),
                                "seed": seed, "guard_values": self.baseline_guard,
                                "panels": [(batch.source_ids, noise) for batch, noise in self.probe + self.guard]})

    def panel(self, role, conditions):
        result, count = [], len(self.corpus.splits[role]) // 2
        for condition in conditions:
            for offset in range(0, count, self.plan.panel_batch_size):
                seed = tape_seed(self.seed, "panel:" + role, 0, offset, condition)
                batch = make_batch(self.corpus, role, min(self.plan.panel_batch_size, count - offset),
                                   seed, corruption=condition, offset=offset)
                result.append((batch, tape_seed(self.seed, "panel-noise:" + role, 0, offset, condition)))
        return result

    @torch.no_grad()
    def hard(self, model, panel, role):
        values, hashes = [], []
        for batch, noise_seed in panel:
            predicted = output(model, batch, noise_seed, ("couple",), False, self.work, role + "_generator")
            pixels = (predicted.image_logits.sigmoid() * 255).round().to(torch.uint8)
            captions = [render_tokens(row) for row in predicted.token_ids]
            self.work.add(role + "_reward_observer_calls", 2)
            self.work.add(role + "_reward_observer_digit_examples", 2 * len(batch.source_ids))
            scores = observe_tensors(self.observer, pixels.float() / 255, captions,
                                     batch.target.pixels, batch.target.labels)
            values.extend(row["utility"] - self.plan.refinement_charge for row in scores)
            hashes.extend(hashlib.sha256(pixel.numpy().tobytes() + text.encode()).hexdigest()
                          for pixel, text in zip(pixels, captions, strict=True))
        array = np.asarray(values, dtype=np.float64)
        if not len(array) or not np.isfinite(array).all():
            raise FloatingPointError("Empty or nonfinite stage-C hard panel")
        return {"values": array, "mean": float(array.mean()), "output_sha256": hashes}

    def snapshot(self, model, optimizer):
        self.work.add("complete_state_captures")
        return capture(model, optimizer)

    def restore(self, model, optimizer, saved):
        restore(model, optimizer, saved)
        self.work.add("complete_state_restores")

    def block(self, model, optimizer, start, action, schedule):
        if action not in range(4) or start not in range(0, self.plan.steps, self.plan.macro_steps):
            raise ValueError("Invalid stage-C action or decision clock")
        self.resource_check()
        saved, before_cost = self.snapshot(model, optimizer), self.work.snapshot()
        before = digest(saved)
        trace = []
        try:
            for step in range(start, start + self.plan.macro_steps):
                batches = training_batches(self.corpus, self.plan, self.seed, schedule, step)
                noise = tape_seed(self.seed, "continuation", schedule, step, "noise")
                info = update(model, optimizer, self.teacher, batches, noise, ("couple",),
                              self.plan.multipliers[action], self.plan, self.work)
                trace.append({"step": step, "tape_identity": batch_digest(batches), "noise_seed": noise, **info})
            candidate = digest(self.snapshot(model, optimizer))
            guard = self.hard(model, self.guard, "candidate_guard")
            delta = float((guard["values"] - self.baseline_guard).mean())
            accepted = delta >= 0
            if not accepted:
                self.restore(model, optimizer, saved)
                self.work.add("rejected_blocks")
                self.work.add("discarded_microsteps", self.plan.macro_steps)
            else:
                self.work.add("accepted_blocks")
            after = digest(self.snapshot(model, optimizer))
            if action == 0 and after != before:
                raise AssertionError("Zero training action changed complete entry state")
            if parameter_hash(self.teacher) != self.teacher_sha:
                raise AssertionError("Immutable warmstart teacher changed")
        except BaseException as error:
            self.last_failure = {
                "state": self.snapshot(model, optimizer),
                "metadata": {"start": start, "action": action, "schedule": schedule,
                             "before": before, "microsteps": trace,
                             "error_type": type(error).__name__, "message": str(error),
                             "work": self.work.snapshot()},
            }
            self.restore(model, optimizer, saved)
            raise
        return {"start": start, "end": start + self.plan.macro_steps, "action": action,
                "multiplier": self.plan.multipliers[action], "schedule": schedule,
                "before": before, "candidate": candidate, "after": after,
                "accepted": accepted, "guard_delta": delta,
                "guard_values": guard["values"].tolist(), "guard_output_sha256": guard["output_sha256"],
                "clock_advances": True, "microsteps": trace,
                "work_before": before_cost, "work_after": self.work.snapshot()}
