"""Exact finite-plan NDU gradients from independently scored neural outputs.

Only offline training reads Target or the fixed observer. The deployed wrapper
contains frozen neural/gate parameters and public latent state. Its training
distribution is a declared finite latent-noise scenario profile; it is not a
claim about true-world risk or globally optimal unrestricted multimodal output.
"""

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import io
import json
import math
from pathlib import Path
import time

import numpy as np
from PIL import Image
import torch
from torch import nn
from torch.nn import functional as F

from .data import make_batch, render_tokens
from .neural import (CONDITIONED_SCHEMA, LEGACY_ARCHITECTURE, NeuralPortfolio, NeuralSnapshot,
                     NeuralState, PROFILES, parameter_hash, read_checkpoint, snapshot_from_record)
from .observer import METRIC_DIGEST, observe_tensors


PLANS = (
    ("refine_semantic", "couple"),
    ("couple", "refine_image"),
    ("couple", "refine_text"),
    ("refine_image", "refine_text"),
)
ALLOCATION_PLAN = ("refine_image", "refine_text")


class PlanHead(nn.Module):
    def __init__(self, context_size, hidden=32):
        super().__init__()
        self.config = {"context_size": context_size, "hidden": hidden}
        self.net = nn.Sequential(nn.Linear(context_size, hidden), nn.Tanh(),
                                 nn.Linear(hidden, len(PLANS)))

    def forward(self, context):
        return self.net(context)


def finite_ndu_loss(logits, utilities, risk_aversion=2.):
    """Per-case negative entropic CE over plan probability and K scenarios.

    Outcomes are detached, so the exact finite gradient is only through plan
    probabilities. The optimizer cannot raise its reward by changing a scorer.
    """
    if (utilities.ndim != 3 or logits.shape != utilities.shape[:2]
            or utilities.shape[2] < 1 or not math.isfinite(risk_aversion)
            or risk_aversion <= 0 or not torch.isfinite(utilities).all()
            or not torch.isfinite(logits).all()):
        raise ValueError("Invalid finite NDU distribution")
    log_probabilities = F.log_softmax(logits.double(), dim=1)
    terms = log_probabilities[:, :, None] - risk_aversion * utilities.detach().double()
    return (torch.logsumexp(terms.flatten(1), dim=1)
            - math.log(utilities.shape[2])) / risk_aversion


def _context(base, state):
    return base.state_features(state)[:, -base.config["hidden"]:]


def _png_roundtrip(pixels):
    """Return actual 8-bit PNG-decoded pixels and hashes of encoded PNG bytes."""
    quantized = (pixels.detach().cpu() * 255).round()
    if (quantized.ndim != 4 or quantized.shape[1:] != (1, 28, 56)
            or not torch.isfinite(quantized).all()
            or quantized.min() < 0 or quantized.max() > 255):
        raise ValueError("Invalid neural image for PNG encoding")
    restored, hashes = [], []
    for array in quantized.to(torch.uint8).squeeze(1).numpy():
        stream = io.BytesIO()
        Image.fromarray(array).save(stream, format="PNG")
        raw = stream.getvalue()
        hashes.append(hashlib.sha256(raw).hexdigest())
        with Image.open(io.BytesIO(raw)) as image:
            restored.append(torch.from_numpy(np.array(image, copy=True)).float()[None] / 255)
    return torch.stack(restored), hashes


@dataclass(frozen=True)
class ControlledState:
    neural: NeuralState
    plan_indices: tuple[int, ...]
    snapshot_digest: str

    @property
    def plan_index(self):
        return self.plan_indices[0] if len(self.plan_indices) == 1 else self.plan_indices


class ControlledSnapshot:
    """Inference-only latent plan gate; no target, observer or reward table."""

    initial_plan_cost = 2

    def __init__(self, base, gate, metadata=None):
        if gate.config["context_size"] != base.config["hidden"]:
            raise ValueError("Base/gate latent dimensions differ")
        self._base = base
        self._gate = deepcopy(gate).cpu().eval().requires_grad_(False)
        self.config = dict(base.config)
        self.metadata = {**deepcopy(base.metadata), **deepcopy(metadata or {})}
        self._gate_hash = parameter_hash(self._gate)
        self.fingerprint = self._combined_hash()

    def _combined_hash(self):
        schema = self._checkpoint_schema()
        bound = {"schema": schema,
                 "base": self._base.fingerprint, "gate": self._gate_hash,
                 "plans": PLANS, "selection": "deterministic_argmax",
                 "initial_plan_cost": self.initial_plan_cost}
        if schema.endswith(".v2"):
            bound["gate_config"] = self._gate.config
        return hashlib.sha256(json.dumps(bound, sort_keys=True).encode()).hexdigest()

    def _checkpoint_schema(self):
        legacy = self._base.config.get("architecture", LEGACY_ARCHITECTURE) == LEGACY_ARCHITECTURE
        return f"hepta.ndu-v6.controlled-snapshot.v{1 if legacy else 2}"

    def verify_integrity(self):
        self._base.verify_integrity()
        if (parameter_hash(self._gate) != self._gate_hash
                or self.fingerprint != self._combined_hash()
                or self.config != self._base.config):
            raise RuntimeError("Controlled inference snapshot changed")
        return self.fingerprint

    def _check_state(self, state):
        if (not isinstance(state, ControlledState)
                or state.snapshot_digest != self.fingerprint
                or len(state.plan_indices) != len(state.neural.h)
                or any(index not in {-1, *range(len(PLANS))} for index in state.plan_indices)):
            raise ValueError("Foreign or malformed controlled state")

    @torch.inference_mode()
    def encode(self, observation, noise_seed=0, *, content_control=True):
        if type(content_control) is not bool:
            raise TypeError("content_control must be a boolean policy flag")
        self.verify_integrity()
        initial = self._base.encode(observation, noise_seed=noise_seed)
        choices = (self._gate(_context(self._base, initial)).argmax(1) if content_control
                   else torch.full((len(initial.h),), -1, dtype=torch.long))
        groups, positions = [], []
        for plan_index, plan in (*enumerate(PLANS), (-1, ALLOCATION_PLAN)):
            ids = (choices == plan_index).nonzero().flatten()
            if not len(ids):
                continue
            substate = NeuralState(*(getattr(initial, name)[ids]
                                     for name in ("h", "image", "text", "context")),
                                   initial.snapshot_digest)
            for action in plan:
                substate = self._base.step(substate, action)
            groups.append(substate)
            positions.append(ids)
        order = torch.cat(positions).argsort()
        state = NeuralState(*(torch.cat([getattr(group, name) for group in groups])[order]
                              for name in ("h", "image", "text")),
                            initial.context, initial.snapshot_digest)
        return ControlledState(state, tuple(choices.tolist()), self.fingerprint)

    @torch.inference_mode()
    def plan_for(self, observation, noise_seed=0, *, content_control=True):
        if type(content_control) is not bool:
            raise TypeError("content_control must be a boolean policy flag")
        self.verify_integrity()
        state = self._base.encode(observation, noise_seed=noise_seed)
        if not content_control:
            return (ALLOCATION_PLAN,) * len(state.h)
        choices = self._gate(_context(self._base, state)).argmax(1).tolist()
        return tuple(PLANS[index] for index in choices)

    def step(self, state, action):
        self._check_state(state)
        if -1 in state.plan_indices and action not in ALLOCATION_PLAN:
            raise ValueError("Shared content controls are disabled for this state")
        return ControlledState(self._base.step(state.neural, action),
                               state.plan_indices, self.fingerprint)

    def decode(self, state):
        self._check_state(state)
        return self._base.decode(state.neural)

    def state_features(self, state):
        self._check_state(state)
        return self._base.state_features(state.neural)

    def state_key(self, state):
        self._check_state(state)
        bound = (self.fingerprint, self._base.state_key(state.neural), state.plan_indices)
        return hashlib.sha256(repr(bound).encode()).hexdigest()

    def observation_identity(self, state):
        self._check_state(state)
        bound = self.fingerprint + self._base.observation_identity(state.neural)
        return hashlib.sha256(bound.encode()).hexdigest()

    def save(self, path):
        self.verify_integrity()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        record = {"schema": "hepta.ndu-v6.controlled-snapshot.v1",
                  "base_config": self._base.config,
                  "base_state_dict": self._base._model.state_dict(),
                  "base_metadata": self._base.metadata,
                  "base_sha256": self._base.fingerprint,
                  "gate_config": self._gate.config,
                  "gate_state_dict": self._gate.state_dict(),
                  "gate_sha256": self._gate_hash, "plans": PLANS,
                  "metadata": self.metadata, "combined_sha256": self.fingerprint}
        if self._checkpoint_schema().endswith(".v2"):
            for key in ("base_config", "base_state_dict", "base_metadata"):
                del record[key]
            record["schema"] = self._checkpoint_schema()
            record["base_record"] = self._base.to_record()
        torch.save(record, temporary)
        temporary.replace(path)
        return self.fingerprint

    @classmethod
    def load(cls, path, *, expected_file_sha256=None):
        record = read_checkpoint(path, expected_file_sha256)
        if (record.get("schema") not in {"hepta.ndu-v6.controlled-snapshot.v1",
                                         "hepta.ndu-v6.controlled-snapshot.v2"}
                or record.get("plans") != PLANS):
            raise ValueError("Unsupported controlled snapshot/plan set")
        if record["schema"].endswith(".v1"):
            model = NeuralPortfolio(**record["base_config"])
            model.load_state_dict(record["base_state_dict"], strict=True)
            base = NeuralSnapshot(model, record["base_metadata"])
        else:
            if record.get("base_record", {}).get("schema") != CONDITIONED_SCHEMA:
                raise ValueError("Controlled v2 requires an explicit config-bound conditioned base")
            base = snapshot_from_record(record["base_record"])
        gate = PlanHead(**record["gate_config"])
        gate.load_state_dict(record["gate_state_dict"], strict=True)
        result = cls(base, gate, record["metadata"])
        if (base.fingerprint != record["base_sha256"]
                or result._gate_hash != record["gate_sha256"]
                or result.fingerprint != record["combined_sha256"]):
            raise ValueError("Controlled snapshot hash mismatch")
        return result


def fit_plan_head(base, corpus, observer_model, training_profile, seed,
                  fit_pairs=128, steps=120, scenarios=2, risk_aversion=2.):
    """Train a real-output content gate on training truth only, then discard it.

    Supervision imitates the best empirical mean-utility plan. NDU differentiates
    the exact finite plan/scenario certainty equivalent. Both use the same gate
    initialization, cases, scenarios, enumerated plans and update schedule.
    """
    if (training_profile not in PROFILES or fit_pairs < 2 or steps < 1
            or scenarios < 2 or not math.isfinite(risk_aversion) or risk_aversion <= 0):
        raise ValueError("Invalid plan-head training configuration")
    if observer_model.training or any(p.requires_grad for p in observer_model.parameters()):
        raise ValueError("Plan rewards require a separately frozen observer")
    base.verify_integrity()
    observer_digest = parameter_hash(observer_model)
    start = time.perf_counter_ns()
    batch_seed = int(seed) * 1000003 + 4409
    batch = make_batch(corpus, "train", fit_pairs, batch_seed, offset=0)
    utilities = torch.empty(fit_pairs, len(PLANS), scenarios, dtype=torch.float64)
    source_ids = [source for pair in batch.source_ids for source in pair]
    scenario_seeds = [int(seed) * 1000033 + k * 104729 for k in range(scenarios)]
    output_digest = hashlib.sha256()
    valid_captions = 0
    features = None
    for scenario_index, scenario_seed in enumerate(scenario_seeds):
        initial = base.encode(batch.observation, noise_seed=scenario_seed)
        current_context = _context(base, initial).detach().clone()
        if features is None:
            features = current_context
        elif not torch.equal(features, current_context):
            raise ValueError("Gate conditioning must be fixed across noise scenarios")
        for plan_index, plan in enumerate(PLANS):
            state = initial
            for action in plan:
                state = base.step(state, action)
            output = base.decode(state)
            pixels, png_hashes = _png_roundtrip(output.image_logits.sigmoid())
            captions = [render_tokens(row).encode("utf-8").decode("utf-8")
                        for row in output.token_ids]
            observed = observe_tensors(observer_model, pixels, captions,
                                       batch.target.pixels, batch.target.labels)
            utilities[:, plan_index, scenario_index] = torch.tensor(
                [item["utility"] for item in observed], dtype=torch.float64)
            for caption, png_hash, item in zip(captions, png_hashes, observed):
                output_digest.update(json.dumps({"caption": caption, "png": png_hash,
                                                  "utility": item["utility"]},
                                                 sort_keys=True).encode())
                valid_captions += int(item["caption_valid"])
    enumeration_ns = time.perf_counter_ns() - start
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(int(seed) + 65537)
        gate = PlanHead(base.config["hidden"])
    initial_hash = parameter_hash(gate)
    mean_best = utilities.mean(2).argmax(1)
    optimizer = torch.optim.Adam(gate.parameters(), lr=.005)
    rng = torch.Generator().manual_seed(int(seed) + 131071)
    histories, schedule_hash, gradient_max = [], hashlib.sha256(), 0.
    with torch.no_grad():
        initial_ce = -finite_ndu_loss(gate(features), utilities, risk_aversion).mean().item()
    optimization_start = time.perf_counter_ns()
    for iteration in range(steps):
        ids = torch.randperm(fit_pairs, generator=rng)[:min(32, fit_pairs)]
        logits = gate(features[ids])
        if training_profile == "supervised":
            loss = F.cross_entropy(logits, mean_best[ids])
        else:
            loss = finite_ndu_loss(logits, utilities[ids], risk_aversion).mean()
        if not torch.isfinite(loss):
            raise FloatingPointError("Non-finite content-plan objective")
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        gradient_max = max(gradient_max, sum(float(p.grad.detach().abs().sum())
                                            for p in gate.parameters() if p.grad is not None))
        optimizer.step()
        schedule_hash.update(ids.numpy().tobytes())
        histories.append(float(loss.detach()))
    optimization_ns = time.perf_counter_ns() - optimization_start
    with torch.no_grad():
        logits = gate(features)
        choices = logits.argmax(1)
        mixture_ce = -finite_ndu_loss(logits, utilities, risk_aversion).mean().item()
        per_plan_ce = -(torch.logsumexp(-risk_aversion * utilities, dim=2)
                        - math.log(scenarios)) / risk_aversion
        deployment_ce = per_plan_ce[torch.arange(fit_pairs), choices].mean().item()
    base.verify_integrity()
    if observer_digest != parameter_hash(observer_model):
        raise RuntimeError("Fixed training observer changed")
    metadata = {"content_plan_training_profile": training_profile,
                "content_plan_metric_sha256": METRIC_DIGEST,
                "content_plan_observer_sha256": observer_digest,
                "content_plan_scenario_count": scenarios,
                "content_plan_risk_aversion": risk_aversion}
    result = ControlledSnapshot(base, gate, metadata)
    candidate_count = fit_pairs * len(PLANS) * scenarios
    evidence = {
        **metadata, "schema": "hepta.ndu-v6.actual-output-plan-training.v1",
        "seed": seed, "fit_split": "train", "fit_pairs": fit_pairs,
        "source_manifest_sha256": corpus.manifest["manifest_sha256"],
        "source_ids_sha256": hashlib.sha256("\n".join(source_ids).encode()).hexdigest(),
        "batch_seed": batch_seed, "scenario_seeds": scenario_seeds, "plans": PLANS,
        "base_sha256": base.fingerprint, "initial_gate_sha256": initial_hash,
        "final_gate_sha256": result._gate_hash, "combined_sha256": result.fingerprint,
        "gate_update_schedule_sha256": schedule_hash.hexdigest(),
        "output_observation_sha256": output_digest.hexdigest(),
        "utility_table": utilities.tolist(), "objective_history": histories,
        "gate_gradient_abs_sum_max": gradient_max, "optimizer_updates": steps,
        "training_reward_is_independent_emitted_output_score": True,
        "reward_parameters_optimized": False,
        "exact_gradient_scope": "finite plan probabilities with detached fixed scenario rewards",
        "risk_scope": "finite empirical latent-noise profile; not true-world risk calibration",
        "selection_at_deployment": "deterministic argmax; distinct from stochastic training mixture",
        "initial_mixture_ce": initial_ce, "final_mixture_ce": mixture_ce,
        "deployment_argmax_ce": deployment_ce,
        "finite_empirical_oracle_ce": per_plan_ce.max(1).values.mean().item(),
        "plan_selection_counts": torch.bincount(choices, minlength=len(PLANS)).tolist(),
        "caption_valid_fraction": valid_captions / candidate_count,
        "costs": {"encoder_example_calls": fit_pairs * scenarios,
                  "neural_action_example_calls": 2 * candidate_count,
                  "decoder_example_calls": candidate_count,
                  "png_encode_decode_calls": candidate_count,
                  "observer_example_calls": candidate_count,
                  "gate_optimization_example_calls": steps * min(32, fit_pairs),
                  "enumeration_wall_ns": enumeration_ns,
                  "optimization_wall_ns": optimization_ns,
                  "total_wall_ns": time.perf_counter_ns() - start},
        "general_ndu_fbsde_claim": False,
    }
    return result, evidence
