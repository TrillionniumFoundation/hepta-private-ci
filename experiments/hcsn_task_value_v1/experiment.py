"""Shared task inputs and active-parameter-matched external controls."""

from functools import lru_cache

import numpy as np
import torch
from torch import nn

from experiments.continuous_spiking_network.baseline import build_baseline, match_parameter_budget
from experiments.hcsn_free_boundary_v1.datasets import synthetic
from .model import Classifier


EXTERNAL = ("two_gates", "transformer", "lif_snn")
DATA_SEED = 2026103107


class ExternalClassifier(nn.Module):
    def __init__(self, name, input_dim, output_dim, width, seed):
        super().__init__()
        self.matching = matching(name, input_dim, output_dim, width)
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            self.frontend = nn.Sequential(nn.Linear(input_dim + 3, width), nn.LayerNorm(width), nn.Tanh())
            self.readout = nn.Linear(width, output_dim)
            self.backbone = build_baseline(name, width, hidden_width=self.matching["hidden_width"])
        self.config = dict(name=name, input_dim=input_dim, output_dim=output_dim,
                           width=width, seed=seed, matching=self.matching,
                           recurrent_clock="one step per observed event; physical seconds remain shared input features")

    def event_recurrence(self, sequence, observed):
        """Conventional event-index recurrence; zero elapsed time cannot erase input.

        The reused physical-dt baseline skips the first token when dt=0. Here
        each actual observation takes one recurrent step, including simultaneous
        arrivals. No observation skips the step. This is explicit discrete event
        time, not a claim of a continuous physical-time baseline solution.
        """
        sequence = self.backbone.input_proj(sequence)
        states, events = [], sequence.new_zeros(())
        for block in self.backbone.blocks:
            previous = sequence.new_zeros(sequence.shape[0], block.width)
            state = (previous, previous.clone()) if self.config["name"] == "lif_snn" else previous
            outputs = []
            unit = sequence.new_ones(sequence.shape[0], 1)
            for index in range(sequence.shape[1]):
                candidate, proposed = block.cell.step(sequence[:, index], state, unit)
                valid = observed[:, index, None]
                previous = torch.where(valid, candidate, previous)
                if isinstance(state, tuple):
                    state = tuple(torch.where(valid, new, old) for new, old in zip(proposed, state, strict=True))
                    events = events + torch.where(valid, candidate, torch.zeros_like(candidate)).sum()
                else:
                    state = torch.where(valid, proposed, state)
                outputs.append(previous)
            sequence = torch.stack(outputs, 1)
            states.append(state)
        return self.backbone.output_proj(sequence), dict(state=states, event_count=events)

    def forward(self, x, dt, observed=None, return_aux=False):
        observed = torch.ones_like(dt, dtype=torch.bool) if observed is None else observed.bool()
        common = torch.cat((x, dt[..., None], dt.cumsum(1)[..., None] / 3.2,
                            observed[..., None]), -1)
        if self.config["name"] in ("two_gates", "lif_snn"):
            sequence, aux = self.event_recurrence(self.frontend(common), observed)
        else:
            sequence, aux = self.backbone(self.frontend(common), dt)
        logits = self.readout(sequence)
        return (logits, aux) if return_aux else logits

    def parameter_groups(self):
        return {"content": list(self.named_parameters())}


@lru_cache(maxsize=32)
def matching(name, input_dim, output_dim, width):
    target = sum(p.numel() for p in Classifier(input_dim, output_dim, width).cell.parameters())
    return match_parameter_budget(name, width, target, candidates=range(2, 5 * width + 1))


def build(arm, input_dim, output_dim, width, seed):
    if arm in EXTERNAL:
        return ExternalClassifier(arm, input_dim, output_dim, width, seed)
    freeze = arm.removeprefix("freeze_") if arm.startswith("freeze_") else None
    if freeze:
        boundary, channels = "value", "dual"
    elif arm == "stop_gradient_dual":
        boundary, channels = "stop_gradient", "dual"
    else:
        boundary, channels = arm.split("_")
    model = Classifier(input_dim, output_dim, width, seed, boundary, channels)
    if freeze:
        model.freeze(freeze)
    return model


def synthetic_batch(task, split, length=32, size=256):
    if task != "delayed_recall":
        x, dt, y, _ = synthetic(task, size, split, length, seed=DATA_SEED)
        dt = dt * .1
    else:
        split_id = ("train", "val", "test").index(split)
        rng = np.random.default_rng(np.random.SeedSequence([DATA_SEED, split_id, 91, length]))
        x = np.zeros((size, length, 64), np.float32)
        dt = rng.uniform(.05, .15, (size, length)).astype(np.float32)
        y = np.full((size, length), -100, np.int64)
        answer = rng.integers(0, 8, size)
        x[np.arange(size), 0, answer] = 1
        x[:, 0, 8] = 1
        distractors = rng.integers(0, 8, (size, length - 2))
        x[:, 1:-1, 16:24] = np.eye(8)[distractors]
        x[:, -1, 9] = 1
        y[:, -1] = answer
    dt[:, 0] = 0
    return dict(x=x, dt=dt, y=y, observed=np.ones(dt.shape, bool))


def data(task, split, length=32, size=256, av_directory=None, missing_modality=None):
    if task != "async_av":
        return synthetic_batch(task, split, length, size)
    from .async_av import load_batch
    batch = load_batch(av_directory, "validation" if split == "val" else split,
                       missing_modality=missing_modality)
    content_width = batch["x"].shape[-1] - 8
    payload_observed = batch["x"][..., content_width + 2:content_width + 4].any(-1)
    return dict(x=batch["x"], dt=batch["dt"], y=batch["y_sequence"],
                observed=batch["valid"] & payload_observed, valid=batch["valid"],
                lengths=batch["lengths"], clip_ids=batch["clip_ids"])


def tensor_batch(values, index):
    selected = {key: value[index] for key, value in values.items()
                if key in ("x", "dt", "y", "observed", "valid")}
    valid = selected.get("valid", np.ones(selected["dt"].shape, bool))
    last = int(np.max(np.where(valid, np.arange(valid.shape[1]) + 1, 0)))
    return {key: torch.from_numpy(value[:, :last]) for key, value in selected.items() if key != "valid"}
