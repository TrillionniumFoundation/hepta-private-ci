"""Causal, metered stochastic refinement for an explicitly artificial benchmark.

The known source-conditioned anchor is corrupted by mandatory *external* noise.
A learned conditional gain contracts the current residual before the next noise
arrives. This construction tests feedback control; decoding the clean anchor is
a valid bypass reference and it is not evidence of a diffusion/SOTA advantage.
No truth, canonical target, unread modality or future random draw enters a live
stream. Pure tensor calls serve offline training/planning and account their real
forward work separately from the runtime stream's budget.
"""

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import time

import numpy as np
import torch
from torch import nn

from controlled_model import _canonical, _distances, _portfolios
from metrics import CONTRADICTION_WEIGHT, RAW_ERROR_CAP
from model import MODALITIES, NUM_CLASSES, WIDTH, OutputModel, _mixtures, mac_counts


def innovation_bank(seed, scale=0.8):
    """Fixed ordered support [-direction, zero, +direction]; no hidden truth.

    This rank-one, three-outcome law cannot establish same-marginal/different-
    covariance robustness. Alternative probability laws must use this order.
    """
    if (type(seed) is not int or not 0 <= seed < 2**32
            or isinstance(scale, bool) or not np.isfinite(scale) or not 0 < scale <= 10):
        raise ValueError("bounded seed and positive finite innovation scale required")
    direction = np.random.default_rng(seed).normal(size=WIDTH)
    direction *= float(scale) / np.sqrt(np.mean(direction ** 2))
    return np.stack((-direction, np.zeros(WIDTH), direction)).astype(np.float32), np.array([.25, .5, .25])


@dataclass(eq=False)
class _Stream:
    budget_macs: int
    spent_macs: int
    depth: int = 0
    feedback_depth: int = -1
    sealed: bool = False
    feedback_events: int = 0
    preview_events: int = 0


@dataclass(frozen=True, eq=False)
class FeedbackState:
    _q: torch.Tensor = field(repr=False)
    _anchor: torch.Tensor = field(repr=False)
    _latent: torch.Tensor = field(repr=False)
    _last_update: torch.Tensor = field(repr=False)
    depth: int
    _owner: object = field(repr=False)
    _stream: _Stream = field(repr=False)

    @property
    def latent(self):
        return self._latent.clone()

    @property
    def sealed(self):
        return self._stream.sealed

    @property
    def receipt(self):
        return {"depth": self._stream.depth, "sealed": self.sealed,
                "linear_macs": self._stream.spent_macs,
                "budget_macs": self._stream.budget_macs,
                "feedback_events": self._stream.feedback_events,
                "preview_events": self._stream.preview_events}


class FeedbackOutputModel(nn.Module):
    """Existing four decoders plus a new learned residual contraction field.

    gain=sigmoid(MLP(q, z-anchor)); z'=anchor+(1-gain)*(z-anchor)+innovation.
    The noiseless contraction is an architectural assumption, not a discovered
    convergence theorem. The v2 initial map and unused v2 residual field remain
    frozen. Callers explicitly admit decoder/refiner parameters for NDU training.
    """

    def __init__(self, base_model, seed=0, max_refinements=3):
        super().__init__()
        if not isinstance(base_model, OutputModel):
            raise TypeError("an existing learned OutputModel checkpoint is required")
        if (type(seed) is not int or not 0 <= seed < 2**32
                or type(max_refinements) is not int or not 0 <= max_refinements <= 8):
            raise ValueError("bounded integer seed and refinement horizon required")
        self.base = deepcopy(base_model).requires_grad_(False)
        self.dimensions = dict(base_model.dimensions)
        parameter = next(self.base.parameters())
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            self.refinement = nn.Sequential(
                nn.Linear(NUM_CLASSES + WIDTH, WIDTH), nn.GELU(),
                nn.Linear(WIDTH, WIDTH), nn.Sigmoid()).to(parameter)
        self.max_refinements = max_refinements
        self._owner = object()
        self.reset_costs()

    def cost_profile(self):
        decoders = mac_counts(self.base)["decoder"]
        return {"anchor": NUM_CLASSES * WIDTH,
                "refinement": (NUM_CLASSES + WIDTH) * WIDTH + WIDTH * WIDTH,
                "decoder": decoders, "emit_all": sum(decoders.values()),
                "feedback_linear_macs": 0,
                "exclusions": ["bias/activation/elementwise/reduction arithmetic",
                               "backward/optimizer", "controller decision arithmetic"],
                "feedback_cost": "counted events; dense Linear MACs are zero"}

    def reset_costs(self):
        self._work = {"linear_macs": 0, "anchor_examples": 0,
                      "refinement_examples": 0, "feedback_examples": 0,
                      "decoder_examples": {name: 0 for name in MODALITIES}}

    def work_receipt(self):
        return deepcopy(self._work)

    def _record(self, operation, count):
        profile = self.cost_profile()
        if operation in MODALITIES:
            self._work["decoder_examples"][operation] += count
            self._work["linear_macs"] += count * profile["decoder"][operation]
        else:
            self._work[operation + "_examples"] += count
            self._work["linear_macs"] += count * profile.get(operation, 0)

    def _tensor(self, value, rows, name, broadcast=False):
        parameter = next(self.parameters())
        if isinstance(value, np.ndarray) and not value.flags.writeable:
            value = value.copy()
        tensor = torch.as_tensor(value, device=parameter.device)
        if tensor.is_complex() or tensor.dtype == torch.bool:
            raise ValueError(name + " must be real numeric data")
        tensor = tensor.to(dtype=parameter.dtype)
        if broadcast and tensor.shape in ((WIDTH,), (1, WIDTH)):
            tensor = tensor.reshape(1, WIDTH).expand(rows, WIDTH)
        if tensor.shape != (rows, WIDTH) or not bool(torch.isfinite(tensor).all()):
            raise ValueError(name + " requires finite [batch,64] values")
        return tensor.clone()

    def anchor_tensor(self, portfolios):
        q = _portfolios(portfolios, self.base)
        self._record("anchor", len(q))
        return self.base.initial_latent(q)

    def initialize_tensor(self, portfolios, innovation, *, anchor=None):
        q = _portfolios(portfolios, self.base)
        noise = self._tensor(innovation, len(q), "innovation", broadcast=True)
        anchor = self.anchor_tensor(q) if anchor is None else self._tensor(anchor, len(q), "anchor")
        return anchor + noise

    def refine_tensor(self, portfolios, latent, innovation, *, anchor=None):
        q = _portfolios(portfolios, self.base)
        latent = self._tensor(latent, len(q), "latent")
        noise = self._tensor(innovation, len(q), "innovation", broadcast=True)
        anchor = self.anchor_tensor(q) if anchor is None else self._tensor(anchor, len(q), "anchor")
        self._record("refinement", len(q))
        residual = latent - anchor
        gain = self.refinement(torch.cat((q, residual), dim=1))
        result = anchor + (1 - gain) * residual + noise
        if not bool(torch.isfinite(result).all()):
            raise RuntimeError("nonfinite refinement result")
        return result

    def decode_tensor(self, latent, modalities=MODALITIES):
        modalities = tuple(modalities)
        if not modalities or len(set(modalities)) != len(modalities) or not set(modalities) <= set(MODALITIES):
            raise ValueError("a nonempty unique subset of the four modalities is required")
        if not isinstance(latent, torch.Tensor) or latent.ndim != 2 or len(latent) == 0:
            raise ValueError("nonempty tensor latent required")
        latent = self._tensor(latent, len(latent), "latent")
        outputs = {}
        for name in modalities:
            self._record(name, len(latent))
            outputs[name] = self.base.decoders[name](latent)
        if any(not bool(torch.isfinite(value).all()) for value in outputs.values()):
            raise RuntimeError("nonfinite decoded output")
        return outputs

    def initialize(self, portfolios, innovation, *, budget_macs):
        q = _portfolios(portfolios, self.base)
        noise = self._tensor(innovation, len(q), "innovation", broadcast=True)
        profile = self.cost_profile()
        if (type(budget_macs) is not int
                or budget_macs < len(q) * (profile["anchor"] + profile["emit_all"])):
            raise ValueError("integer budget must cover initialization and final four outputs")
        anchor = self.anchor_tensor(q)
        latent = self.initialize_tensor(q, noise, anchor=anchor)
        return FeedbackState(q.clone(), anchor, latent, noise.clone(), 0, self._owner,
                             _Stream(budget_macs, len(q) * profile["anchor"]))

    def _check(self, state, decision=False):
        if not isinstance(state, FeedbackState) or state._owner is not self._owner:
            raise ValueError("state belongs to another feedback generator")
        if state.sealed:
            raise ValueError("emitted trajectory is sealed")
        if state.depth != state._stream.depth:
            raise ValueError("stale snapshot cannot rewind the trajectory")
        if decision and state._stream.feedback_depth != state.depth:
            raise ValueError("read current feedback before choosing STOP or CONTINUE")

    def _charge(self, state, work, reserve_emit=True):
        reserve = len(state._q) * self.cost_profile()["emit_all"] if reserve_emit else 0
        if state._stream.spent_macs + work + reserve > state._stream.budget_macs:
            raise ValueError("operation exceeds budget with final four outputs reserved")
        state._stream.spent_macs += work

    def feedback(self, state):
        """Observe current causal latent consistency, never evaluator correctness."""
        self._check(state)
        state._stream.feedback_depth = state.depth
        state._stream.feedback_events += 1
        self._record("feedback", len(state._q))
        return {"latent": state.latent,
                "residual_rms": (state._latent - state._anchor).square().mean(1).sqrt(),
                "last_update_rms": state._last_update.square().mean(1).sqrt(),
                "latent_rms": state._latent.square().mean(1).sqrt(),
                "depth": state.depth, "linear_macs": state._stream.spent_macs,
                "remaining_macs": state._stream.budget_macs - state._stream.spent_macs}

    def refine_step(self, state, innovation):
        self._check(state, decision=True)
        if state.depth >= self.max_refinements:
            raise ValueError("maximum refinement horizon reached")
        noise = self._tensor(innovation, len(state._q), "innovation", broadcast=True)
        self._charge(state, len(state._q) * self.cost_profile()["refinement"])
        latent = self.refine_tensor(state._q, state._latent, noise, anchor=state._anchor)
        state._stream.depth += 1
        return FeedbackState(state._q, state._anchor, latent, latent - state._latent,
                             state.depth + 1, self._owner, state._stream)

    def preview(self, state, modalities=MODALITIES):
        self._check(state)
        modalities = tuple(modalities)
        if not modalities or len(set(modalities)) != len(modalities) or not set(modalities) <= set(MODALITIES):
            raise ValueError("a nonempty unique subset of modalities is required")
        work = len(state._q) * sum(self.cost_profile()["decoder"][name] for name in modalities)
        self._charge(state, work)
        state._stream.preview_events += 1
        return self.decode_tensor(state._latent, modalities)

    def emit(self, state):
        self._check(state, decision=True)
        self._charge(state, len(state._q) * self.cost_profile()["emit_all"], reserve_emit=False)
        outputs = self.decode_tensor(state._latent)
        state._stream.sealed = True
        return outputs


def external_loss_from_outputs(model, outputs, canonical_targets):
    """Exact metrics.py loss [batch,8]; derivative is local and a.e. only."""
    canonical, normalizers = _canonical(canonical_targets, model.base)
    if set(outputs) != set(MODALITIES):
        raise ValueError("all four actually generated modalities are required")
    distances = _distances(outputs, canonical, normalizers)
    nearest = distances.detach().argmin(2)
    disagreement = torch.stack([nearest[i] != nearest[j]
                                for i in range(4) for j in range(i + 1, 4)]).double().mean(0)
    return distances.clamp(max=RAW_ERROR_CAP).mean(0) + CONTRADICTION_WEIGHT * disagreement[:, None]


def weight_hashes(model):
    groups = {name: hashlib.sha256() for name in (
        "all", "encoders", "initial_latent", "unused_v2_refinement", "refinement",
        *("decoders." + name for name in MODALITIES))}
    for name, value in sorted(model.state_dict().items()):
        if name.startswith("base.decoders."):
            group = ".".join(name.split(".")[1:3])
        elif name.startswith("base."):
            group = name.split(".")[1]
            if group == "refinement":
                group = "unused_v2_refinement"
        else:
            group = "refinement"
        array = value.detach().cpu().contiguous().numpy()
        header = repr((name, tuple(array.shape), str(array.dtype))).encode()
        for target in ("all", group):
            groups[target].update(len(header).to_bytes(8, "little") + header + array.tobytes())
    return {name: digest.hexdigest() for name, digest in groups.items()}


def train_feedback_denoiser(base_model, canonical_targets, seed, steps=100,
                           batch_size=64, noise_scale=0.8, learning_rate=0.003,
                           max_refinements=3):
    """Supervised one-step denoising only; it is NOT NDU objective training.

    The original base, all its decoders and source map stay frozen. IID Gaussian
    corruptions cover directions beyond the later finite stochastic support.
    Future innovations are set to zero when learning the conditional mean
    correction; no future random outcome is supplied to the refiner.
    """
    innovation_bank(seed, noise_scale)
    if (type(steps) is not int or not 1 <= steps <= 10000
            or type(batch_size) is not int or not 8 <= batch_size <= 512
            or isinstance(learning_rate, bool) or not np.isfinite(learning_rate)
            or not 0 < learning_rate <= .01):
        raise ValueError("bounded positive training settings required")
    model = FeedbackOutputModel(base_model, seed, max_refinements)
    if next(model.parameters()).device.type != "cpu":
        raise ValueError("this mechanism pilot runs on CPU")
    canonical, normalizers = _canonical(canonical_targets, model.base)
    target = {name: torch.as_tensor(value, dtype=next(model.parameters()).dtype)
              for name, value in canonical.items()}
    initial_hash = weight_hashes(model)
    rng = np.random.default_rng(seed ^ 0x5EED123)
    probe_rng = np.random.default_rng(seed ^ 0x8173)
    probes = _mixtures(probe_rng, 32)
    probe_noise = torch.from_numpy(probe_rng.normal(0, noise_scale, (32, WIDTH)).astype(np.float32))

    def reconstruction(outputs, q):
        return torch.stack([((outputs[name] - q @ target[name]).square().mean()
                             / normalizers[name]) for name in MODALITIES]).mean()

    def diagnostics():
        with torch.no_grad():
            anchor = model.anchor_tensor(probes)
            noisy = model.initialize_tensor(probes, probe_noise, anchor=anchor)
            refined = model.refine_tensor(probes, noisy, torch.zeros(WIDTH), anchor=anchor)
            return {name: float(reconstruction(model.decode_tensor(latent), probes))
                    for name, latent in (("clean_anchor", anchor), ("noisy", noisy), ("one_refinement", refined))}

    started_wall, started_cpu = time.perf_counter(), time.process_time()
    before = diagnostics()
    diagnostic_cost = model.work_receipt()
    model.reset_costs()
    optimizer = torch.optim.AdamW(model.refinement.parameters(), lr=learning_rate, weight_decay=1e-4)
    history, gradient_norms = [], []
    model.train()
    for step in range(steps):
        q = _mixtures(rng, batch_size)
        noise = rng.normal(size=(batch_size, WIDTH)) * rng.uniform(0, 2 * noise_scale, (batch_size, 1))
        anchor = model.anchor_tensor(q)
        noisy = model.initialize_tensor(q, noise, anchor=anchor)
        refined = model.refine_tensor(q, noisy, torch.zeros(WIDTH), anchor=anchor)
        loss = reconstruction(model.decode_tensor(refined), q)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        norm = torch.nn.utils.clip_grad_norm_(model.refinement.parameters(), 5, error_if_nonfinite=True)
        optimizer.step()
        if step in (0, steps - 1):
            gradient_norms.append({"step": step + 1, "supervised_refinement_gradient_l2": float(norm)})
        if step == 0 or (step + 1) % 25 == 0 or step == steps - 1:
            history.append({"step": step + 1, "normalized_reconstruction_mse": float(loss.detach())})
    training_cost = model.work_receipt()
    model.reset_costs()
    after = diagnostics()
    second_diagnostic_cost = model.work_receipt()
    model.eval().requires_grad_(False)
    final_hash = weight_hashes(model)
    if any(initial_hash[key] != final_hash[key] for key in initial_hash if key not in ("all", "refinement")):
        raise AssertionError("supervised denoising modified the frozen original model")
    model.reset_costs()
    return model, {
        "schema": "hepta.feedback-denoising-mechanism.v3", "seed": seed,
        "optimizer_steps": steps, "batch_size": batch_size, "noise_scale": noise_scale,
        "optimizer": {"name": "AdamW", "lr": learning_rate, "weight_decay": 1e-4},
        "initial_hashes": initial_hash, "final_hashes": final_hash,
        "groups_changed": {key: initial_hash[key] != final_hash[key] for key in initial_hash},
        "before_training_probe": before, "after_training_probe": after,
        "history": history, "gradient_evidence": gradient_norms,
        "training_forward_work": training_cost,
        "diagnostic_forward_linear_macs": diagnostic_cost["linear_macs"] + second_diagnostic_cost["linear_macs"],
        "wall_seconds": time.perf_counter() - started_wall,
        "process_cpu_seconds": time.process_time() - started_cpu,
        "ndu_training": False, "uses_heldout_truth": False,
        "source_and_all_decoders_frozen": True, "parent_unchanged": True,
        "scope": "supervised stochastic latent-denoising mechanism, no natural-data/SOTA claim",
        "cost_exclusions": model.cost_profile()["exclusions"],
    }
