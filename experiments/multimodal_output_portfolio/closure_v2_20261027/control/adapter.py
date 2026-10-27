"""Public observation -> neural decoder -> actual media; truth stays separate."""

from dataclasses import dataclass
from pathlib import Path
import time

import numpy as np
import torch

from ...v6.data import Observation, Target, render_tokens
from ...v6.neural import parameter_hash
from ...v6.observer import CAPTION, observe_tensors, read_bundle, write_bundle
from ...v6.plan_training import ControlledSnapshot
from ...repair_20261026.joint.train import deploy
from .protocol import PROTOCOL as P, sha


@dataclass(frozen=True)
class PublicTask:
    observation: Observation
    noise_seed: int


class Generator:
    def __init__(self, path):
        if sha(path) != P["generator_sha256"]:
            raise ValueError("The preregistered generator changed")
        self.snapshot = ControlledSnapshot.load(path, expected_file_sha256=P["generator_sha256"])
        self.model = self.snapshot._base._model
        self.gate = self.snapshot._gate
        self.identity = (parameter_hash(self.model), parameter_hash(self.gate))

    def deliver(self, public, command, directory):
        if not isinstance(public, PublicTask) or command not in (0, 1):
            raise TypeError("Only public observations and a two-option command may enter generation")
        tokens = public.observation.text_tokens.clone()
        tokens[:, 1] = 9 + command
        observed = Observation(public.observation.pixels, public.observation.mask, tokens)
        rng = torch.Generator().manual_seed(public.noise_seed)
        noise = torch.randn(1, self.model.hidden, generator=rng)
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        with torch.inference_mode():
            generated, plan = deploy(self.model, self.gate, observed, noise)
        generated_ns = time.perf_counter_ns()
        paths = write_bundle(directory, render_tokens(generated.token_ids[0]), generated.image_logits[0].sigmoid())
        pixels, caption, hashes = read_bundle(paths)
        if self.identity != (parameter_hash(self.model), parameter_hash(self.gate)):
            raise ValueError("Frozen generation parameters changed")
        return {"command": command, "plan": int(plan[0]), "paths": paths,
            "sha256": hashes, "caption": caption, "delivered_monotonic_ns": time.monotonic_ns(),
            "model_identity": list(self.identity), "generator_file_sha256": P["generator_sha256"],
            "logical_work": {"encodes": 1, "gates": 1, "transitions": 2, "decodes": 1},
            "generation_wall_ns": generated_ns - wall,
            "generation_and_delivery_cpu_ns": time.process_time_ns() - cpu,
            "generation_and_delivery_wall_ns": time.perf_counter_ns() - wall}, pixels


def scalar_feedback(caption, preferred_labels):
    """An external evaluator returns only {-1,0,+1} after actual delivery."""
    match = CAPTION.fullmatch(caption.strip())
    if match is None:
        return 0
    digits = [int(match[1]), int(match[2])]
    relation = "less" if digits[0] < digits[1] else "greater" if digits[0] > digits[1] else "equal"
    if match[3] != relation:
        return 0
    if digits == list(preferred_labels):
        return 1
    if digits == list(reversed(preferred_labels)):
        return -1
    return 0


def score(observer, delivered, pixels, private_target):
    if not isinstance(private_target, Target):
        raise TypeError("Scoring requires a private Target")
    result = observe_tensors(observer, pixels, [delivered["caption"]], private_target.pixels, private_target.labels)[0]
    result["strict_success"] = int(result["text_fact"] == 0 and result["relation"] == 0 and result["image_fact"] == 0)
    return result


def generic_memory(feedback):
    """Ten-dimensional linear recurrence, two zero-input delays, no neuron."""
    state = np.zeros(10, dtype=np.float64)
    inputs = [np.array([feedback, abs(feedback), 1.0] + [0.0] * 7), np.zeros(10)]
    for drive in inputs:
        state = 0.5 * state + drive
    return np.r_[1.0, state]
