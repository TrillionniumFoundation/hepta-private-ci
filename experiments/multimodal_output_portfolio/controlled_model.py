"""Controlled early exits of the existing finite synthetic generator.

No new renderer or model is substituted. Each refinement uses the original
learned residual field and its original 1/3 scale. The caller owns acquisition,
budget feasibility and policy selection. Training targets never enter a live
generation state; the smooth training surrogate and frozen external evaluation
loss are deliberately separate APIs.
"""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
import time

import numpy as np
import torch

from model import (MODALITIES, NUM_CLASSES, REFINEMENT_STEPS, WIDTH, OutputModel,
                   _matrix, _mixtures, _weight_hashes, mac_counts)
from metrics import CONTRADICTION_WEIGHT, RAW_ERROR_CAP, score_outputs


@dataclass(eq=False)
class _Stream:
    depth: int = 0
    sealed: bool = False


@dataclass(frozen=True, eq=False)
class GenerationState:
    """Immutable state snapshot; emission seals every snapshot of its stream."""

    _latent: torch.Tensor = field(repr=False)
    depth: int
    _owner: object = field(repr=False)
    _stream: _Stream = field(repr=False)

    @property
    def latent(self):
        """Return an independent tensor; callers cannot edit the stored latent."""
        return self._latent.clone()

    @property
    def sealed(self):
        return self._stream.sealed


def _depth(value):
    if type(value) is not int or not 0 <= value <= REFINEMENT_STEPS:
        raise ValueError("depth must be an integer in [0, 3]")
    return value


def _portfolios(value, base):
    parameter = next(base.parameters())
    if isinstance(value, torch.Tensor):
        if value.is_complex() or value.dtype == torch.bool:
            raise ValueError("portfolios must contain real numeric values")
        tensor = value.to(device=parameter.device, dtype=parameter.dtype).clone()
    else:
        tensor = torch.as_tensor(_matrix(value, NUM_CLASSES),
                                 device=parameter.device, dtype=parameter.dtype)
    if (tensor.ndim != 2 or tensor.shape[1] != NUM_CLASSES or tensor.shape[0] == 0
            or not bool(torch.isfinite(tensor).all())
            or bool((tensor < 0).any()) or bool((tensor > 1).any())
            or not torch.allclose(tensor.sum(1), torch.ones_like(tensor[:, 0]),
                                  rtol=0, atol=2e-6)):
        raise ValueError("nonempty finite [batch, 8] simplex portfolios required")
    return tensor


def _canonical(canonical, base):
    if not isinstance(canonical, Mapping) or set(canonical) != set(MODALITIES):
        raise ValueError("exactly four canonical training modalities required")
    arrays, normalizers = {}, {}
    for name in MODALITIES:
        source = np.asarray(canonical[name])
        if (source.ndim != 2 or source.shape != (NUM_CLASSES, base.dimensions[name])
                or source.dtype.kind not in "fiu" or not np.isfinite(source).all()):
            raise ValueError("finite [8, modality dimension] canonical rows required")
        array = np.array(source, dtype=np.float64, copy=True)
        # Identical to metrics.score_outputs: mean MSE of distinct class indices.
        distances = np.column_stack(
            [np.square(array - row).mean(axis=1) for row in array])
        normalizer = float(distances[~np.eye(NUM_CLASSES, dtype=bool)].mean())
        if not np.isfinite(normalizer) or normalizer <= 0:
            raise ValueError("each canonical modality needs finite semantic variation")
        arrays[name], normalizers[name] = array, normalizer
    return arrays, normalizers


class ControlledOutputModel:
    """Single-stream steps around an unchanged OutputModel parameterization."""

    def __init__(self, base_model, *, copy_model=True):
        if not isinstance(base_model, OutputModel):
            raise TypeError("an existing OutputModel is required")
        if type(copy_model) is not bool:
            raise ValueError("copy_model must be boolean")
        self.base = deepcopy(base_model) if copy_model else base_model
        self._owner = object()

    def initialize(self, portfolios):
        q = _portfolios(portfolios, self.base)
        latent = self.base.initial_latent(q)
        if not bool(torch.isfinite(latent).all()):
            raise ValueError("nonfinite initialized latent")
        return GenerationState(latent, 0, self._owner, _Stream())

    def _check(self, state):
        if not isinstance(state, GenerationState) or state._owner is not self._owner:
            raise ValueError("state belongs to another controlled generator")
        if state.sealed:
            raise ValueError("emitted trajectory is sealed")
        if state.depth != state._stream.depth:
            raise ValueError("stale state cannot rewind a generation trajectory")

    def refine_step(self, state):
        self._check(state)
        if state.depth >= REFINEMENT_STEPS:
            raise ValueError("maximum refinement depth reached")
        latent = state._latent + self.base.refinement(state._latent) / REFINEMENT_STEPS
        if not bool(torch.isfinite(latent).all()):
            raise ValueError("nonfinite refined latent")
        state._stream.depth += 1
        return GenerationState(latent, state.depth + 1, self._owner, state._stream)

    def decode_state(self, state):
        """Preview all four outputs; no target or new observation is accepted."""
        self._check(state)
        outputs = {name: self.base.decoders[name](state._latent) for name in MODALITIES}
        if any(not bool(torch.isfinite(value).all()) for value in outputs.values()):
            raise ValueError("nonfinite decoded output")
        return outputs

    def emit(self, state):
        """Publish all four outputs once, then forbid re-emission and refinement."""
        outputs = self.decode_state(state)
        state._stream.sealed = True
        return outputs

    def outputs_by_depth(self, portfolios, max_depth=REFINEMENT_STEPS):
        """Differentiable diagnostic/training rollout; every preview costs work."""
        _depth(max_depth)
        state = self.initialize(portfolios)
        result = [self.decode_state(state)]
        for _ in range(max_depth):
            state = self.refine_step(state)
            result.append(self.decode_state(state))
        return tuple(result)


def loss_table(model, portfolios, canonical_targets, max_depth=REFINEMENT_STEPS):
    """Return smooth uncapped normalized MSE, shaped [depth + 1, portfolio, 8].

    Targets are the supplied TRAINING prototypes, not the unknown truth of a live
    request. Normalizers equal the external metric's off-diagonal prototype MSE.
    Unlike external loss, this surrogate has no hard cap or nearest-class
    contradiction penalty. Parameters retain their caller-selected grad flags.
    """
    controlled = (model if isinstance(model, ControlledOutputModel)
                  else ControlledOutputModel(model, copy_model=False))
    canonical, normalizers = _canonical(canonical_targets, controlled.base)
    tables = []
    for outputs in controlled.outputs_by_depth(portfolios, max_depth):
        tables.append(_distances(outputs, canonical, normalizers).mean(0))
    return torch.stack(tables)


def _distances(outputs, canonical, normalizers):
    errors = []
    for name in MODALITIES:
        values = outputs[name].to(torch.float64)
        targets = torch.as_tensor(canonical[name], device=values.device)
        # Direct Euclidean kernel avoids both a large [Q,8,features]
        # temporary and subtractive cancellation near perfect outputs.
        distances = torch.cdist(values, targets, p=2,
                               compute_mode="donot_use_mm_for_euclid_dist").square()
        errors.append(distances / values.shape[1] / normalizers[name])
    return torch.stack(errors)


def external_loss_tensor(model, portfolios, canonical_targets,
                         max_depth=REFINEMENT_STEPS):
    """Exact frozen external loss values with their almost-everywhere derivative.

    Every modality's normalized raw MSE is clipped at 2 BEFORE averaging, as in
    metrics.score_outputs. The nearest-class contradiction term is a detached,
    locally constant function. Gradients do not differentiate argmin switches
    or establish an optimum across nonsmooth boundaries. At clipping/argmin
    ties no smooth derivative is claimed. Shape is [depth + 1, portfolio, 8].
    """
    controlled = (model if isinstance(model, ControlledOutputModel)
                  else ControlledOutputModel(model, copy_model=False))
    canonical, normalizers = _canonical(canonical_targets, controlled.base)
    tables = []
    for outputs in controlled.outputs_by_depth(portfolios, max_depth):
        distances = _distances(outputs, canonical, normalizers)
        nearest = distances.detach().argmin(dim=2)
        disagreement = torch.stack([
            nearest[left] != nearest[right]
            for left in range(len(MODALITIES))
            for right in range(left + 1, len(MODALITIES))
        ]).to(distances.dtype).mean(0)
        tables.append(distances.clamp(max=RAW_ERROR_CAP).mean(0)
                      + CONTRADICTION_WEIGHT * disagreement[:, None])
    return torch.stack(tables)


@torch.inference_mode()
def evaluation_loss_table(model, portfolios, canonical_targets,
                          max_depth=REFINEMENT_STEPS):
    """Frozen metrics.py clipped raw loss plus hard contradiction; NO gradient."""
    controlled = (model if isinstance(model, ControlledOutputModel)
                  else ControlledOutputModel(model, copy_model=False))
    canonical, _ = _canonical(canonical_targets, controlled.base)
    tables = []
    for outputs in controlled.outputs_by_depth(portfolios, max_depth):
        raw = {name: value.detach().cpu().numpy() for name, value in outputs.items()}
        count = len(next(iter(raw.values())))
        tables.append(np.column_stack([
            score_outputs(raw, np.full(count, truth, dtype=np.int64), canonical)["loss"]
            for truth in range(NUM_CLASSES)]))
    return np.stack(tables)


def train_controlled(base_model, canonical_targets, seed, steps=100, batch_size=64,
                     learning_rate=0.001):
    """Deep-supervise a COPY at depths 0..3; encoders and parent stay frozen.

    This optional warmup is supervised mixture reconstruction, not NDU training.
    It accepts no observed/test truth or controller outcome. The returned model
    is frozen, matching train_model; a later trainer must explicitly admit its
    own parameter groups. All four exits share the existing learned parameters.
    """
    if (type(seed) is not int or not 0 <= seed < 2**32
            or type(steps) is not int or not 1 <= steps <= 10000
            or type(batch_size) is not int or not 8 <= batch_size <= 512
            or not np.isfinite(learning_rate) or not 0 < learning_rate <= 0.01):
        raise ValueError("bounded seed, positive training steps/batch and learning rate required")
    started_wall, started_cpu = time.perf_counter(), time.process_time()
    controlled = ControlledOutputModel(base_model)
    base = controlled.base
    if next(base.parameters()).device.type != "cpu":
        raise ValueError("this registered finite warmup runs on CPU")
    canonical, normalizers = _canonical(canonical_targets, base)
    initial_hashes = _weight_hashes(base)
    base.requires_grad_(True)
    base.encoders.requires_grad_(False)
    base.train()
    targets = {name: torch.as_tensor(value, dtype=next(base.parameters()).dtype)
               for name, value in canonical.items()}
    rng = np.random.default_rng(seed)
    probes = torch.cat((torch.eye(NUM_CLASSES),
                        _mixtures(np.random.default_rng(seed ^ 0xDC0321), 32)))

    def losses(q):
        return torch.stack([
            torch.stack([((outputs[name] - q @ targets[name]).square().mean()
                          / normalizers[name]) for name in MODALITIES]).mean()
            for outputs in controlled.outputs_by_depth(q)])

    with torch.no_grad():
        initial_probe = losses(probes).tolist()
    optimizer = torch.optim.AdamW([p for p in base.parameters() if p.requires_grad],
                                  lr=learning_rate, weight_decay=0.0001)
    history = []
    for step in range(steps):
        q = _mixtures(rng, batch_size)
        depth_losses = losses(q)
        loss = depth_losses.mean()
        if not bool(torch.isfinite(loss)):
            raise RuntimeError("nonfinite warmup loss")
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(base.parameters(), 5.0, error_if_nonfinite=True)
        optimizer.step()
        if step == 0 or (step + 1) % 25 == 0 or step + 1 == steps:
            history.append({"step": step + 1, "loss": float(loss.detach()),
                            "depth_loss": depth_losses.detach().tolist()})
    with torch.no_grad():
        final_probe = losses(probes).tolist()
    base.eval().requires_grad_(False)
    final_hashes = _weight_hashes(base)
    if initial_hashes["encoders"] != final_hashes["encoders"]:
        raise RuntimeError("deep supervision changed frozen encoders")
    counts = mac_counts(base)
    per_example = (NUM_CLASSES * WIDTH + REFINEMENT_STEPS * 2 * WIDTH * WIDTH
                   + (REFINEMENT_STEPS + 1) * sum(counts["decoder"].values()))
    receipt = {
        "schema": "hepta.multimodal-output-portfolio.controlled-warmup.v2",
        "seed": seed, "optimizer_steps": steps, "batch_size": batch_size,
        "depths": list(range(REFINEMENT_STEPS + 1)), "depth_weights": [0.25] * 4,
        "optimizer": {"name": "AdamW", "lr": learning_rate, "weight_decay": 0.0001},
        "initial_weight_sha256": initial_hashes, "final_weight_sha256": final_hashes,
        "parameter_groups_changed": {key: initial_hashes[key] != final_hashes[key]
                                     for key in initial_hashes},
        "normalizers": normalizers, "initial_probe_depth_mse": initial_probe,
        "final_probe_depth_mse": final_probe, "loss_history": history,
        "training_forward_linear_macs": steps * batch_size * per_example,
        "diagnostic_forward_linear_macs": 2 * len(probes) * per_example,
        "cost_excludes_backward_optimizer_activations": True,
        "training_wall_seconds": time.perf_counter() - started_wall,
        "training_process_cpu_seconds": time.process_time() - started_cpu,
        "scope": "supervised_early_exit_warmup_of_existing_synthetic_model",
        "encoders_frozen": True, "parent_unchanged": True,
        "uses_heldout_truth": False, "ndu_joint_training": False,
    }
    return base, receipt
