"""Finite-model DP distillation; only uncertain continuation targets are learned."""

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import time
import torch
from torch import nn
from torch.nn import functional as F
from . import finite as f

MODES = ("trained", "reset")


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def model_identity(model):
    return digest(
        {
            "parameters": asdict(model),
            "source": hashlib.sha256(Path(f.__file__).read_bytes()).hexdigest(),
        }
    )


def state_key(state):
    return tuple(asdict(state).values())


class AdvantageNet(nn.Module):
    """Identical backbone for fixed and trainable hidden-feature conditions."""

    def __init__(self, width, hidden=24):
        super().__init__()
        self.hidden = nn.Linear(width, hidden)
        self.readout = nn.Linear(hidden, 1)
        self.double()

    def forward(self, features, initial=None):
        hidden = (
            self.hidden(features) if initial is None else F.linear(features, *initial)
        )
        return self.readout(hidden.tanh()).squeeze(-1)


@dataclass
class Candidate:
    network: AdvantageNet
    initial: tuple
    support: frozenset
    model_id: str
    receipt: dict
    calibrations: dict

    def predict(self, state, action, mode="trained"):
        if mode not in MODES:
            raise ValueError("Unknown deployment feature ablation")
        if (state_key(state), action.name) not in self.support:
            raise ValueError("Unsupported state/action pair")
        features = torch.tensor(f.numeric_features(state, action), dtype=torch.float64)
        with torch.inference_mode():
            value = float(
                self.network(features, self.initial if mode == "reset" else None)
            )
        if not math.isfinite(value):
            raise ValueError("Nonfinite advantage prediction")
        return value

    def choose(self, state, model, *, mode="trained", margin=0.002):
        """Online uncertain-action inference never calls the DP teacher."""
        if mode not in MODES or not math.isfinite(margin) or margin < 0:
            raise ValueError("Invalid deployment mode or practical margin")
        started = time.perf_counter()
        legal, stop = f.legal_actions(state, model), f.terminal_value(state, model)
        scores, rejected, intervals = {}, [], {}
        compatible = self.model_id == model_identity(model)
        calibration = self.calibrations.get(mode)
        for action in legal:
            if not f.uncertain(state, action, model):
                scores[action] = f.known_score(state, action, model)
                continue
            if not compatible or calibration is None or calibration["radius"] is None:
                rejected.append(action.name)
                continue
            try:
                prediction = self.predict(state, action, mode)
            except ValueError:
                rejected.append(action.name)
                continue
            radius = calibration["radius"]
            scores[action] = stop + prediction - radius - margin
            intervals[action.name] = [prediction - radius, prediction + radius]
        action = (
            max(scores, key=scores.get)
            if scores
            else next(a for a in legal if a.verb == "STOP")
        )
        return action, {
            "controller_seconds": time.perf_counter() - started,
            "unsupported_actions": rejected,
            "advantage_intervals": intervals,
            "profile_matches": compatible,
            "fallback": bool(rejected),
            "conditional_coverage_guarantee": False,
        }


def fit_candidate(
    roots, model, *, seed, trainable_features=True, epochs=240, learning_rate=0.015
):
    """Exhaust finite support and fit only uncertain stop-relative advantages."""
    if type(seed) is not int or type(epochs) is not int or not 1 <= epochs <= 5000:
        raise ValueError("Bounded training seed/epochs required")
    if not math.isfinite(learning_rate) or not 0 < learning_rate <= 0.1:
        raise ValueError("Invalid learning rate")
    started, cpu = time.perf_counter(), time.process_time()
    torch.manual_seed(seed)
    states = tuple(sorted(f.reachable_states(roots, model), key=state_key))
    pairs, targets = [], []
    for state in states:
        scores = None
        for action in f.legal_actions(state, model):
            if f.uncertain(state, action, model):
                scores = f.exact_scores(state, model) if scores is None else scores
                pairs.append((state, action))
                targets.append(scores[action] - f.terminal_value(state, model))
    if not pairs:
        raise ValueError("No uncertain continuation targets in declared support")
    x = torch.tensor([f.numeric_features(s, a) for s, a in pairs], dtype=torch.float64)
    y = torch.tensor(targets, dtype=torch.float64)
    network = AdvantageNet(x.shape[1])
    initial = (
        network.hidden.weight.detach().clone(),
        network.hidden.bias.detach().clone(),
    )
    network.hidden.requires_grad_(trainable_features)
    optimizer = torch.optim.Adam(
        (p for p in network.parameters() if p.requires_grad), lr=learning_rate
    )
    with torch.no_grad():
        initial_loss = float((network(x) - y).square().mean())
    for _ in range(epochs):
        optimizer.zero_grad(set_to_none=True)
        loss = (network(x) - y).square().mean()
        if not bool(torch.isfinite(loss)):
            raise ValueError("Nonfinite training loss")
        loss.backward()
        optimizer.step()
    network.eval().requires_grad_(False)
    with torch.no_grad():
        final_loss = float((network(x) - y).square().mean())
    support = frozenset((state_key(s), a.name) for s, a in pairs)
    receipt = {
        "training_seed": seed,
        "feature_training": "trainable" if trainable_features else "fixed",
        "epochs": epochs,
        "learning_rate": learning_rate,
        "initial_mse": initial_loss,
        "final_mse": final_loss,
        "reachable_states": len(states),
        "uncertain_pairs": len(pairs),
        "supported_pairs": len(support),
        "uncertain_pair_coverage": len(support) / len(pairs),
        "terminal_training_targets": 0,
        "teacher": "exact_declared_finite_model_DP",
        "semantic_encoder_joint_training": False,
        "observed_return_RL": False,
        "training_seconds": time.perf_counter() - started,
        "training_cpu_seconds": time.process_time() - cpu,
        "model_id": model_identity(model),
        "torch": torch.__version__,
        "device": "cpu",
        "parameters": sum(p.numel() for p in network.parameters()),
        "support_identity": digest(sorted((list(s), a) for s, a in support)),
    }
    return Candidate(network, initial, support, model_identity(model), receipt, {})


def calibrate(
    candidate, model, groups, *, mode="trained", alpha=0.1, training_sources=()
):
    """Group-max n+1 split residual radius; no conditional/OOD coverage claim."""
    if (
        mode not in MODES
        or not 0 < alpha < 1
        or not groups
        or set(groups) & set(training_sources)
    ):
        raise ValueError("Calibration sources must be disjoint and alpha valid")
    if candidate.model_id != model_identity(model):
        raise ValueError("Calibration model differs from frozen candidate")
    started, residuals, count = time.perf_counter(), [], 0
    for source, pairs in sorted(groups.items()):
        if not isinstance(source, str) or not source or not pairs:
            raise ValueError("Every calibration source needs support")
        errors = []
        for state, action in pairs:
            if not f.uncertain(state, action, model):
                raise ValueError("Calibration must target uncertain continuation")
            target = f.exact_scores(state, model)[action] - f.terminal_value(
                state, model
            )
            errors.append(abs(candidate.predict(state, action, mode) - target))
        residuals.append(max(errors))
        count += len(errors)
    ordered = sorted(residuals)
    rank = math.ceil((len(ordered) + 1) * (1 - alpha))
    radius = ordered[rank - 1] if rank <= len(ordered) else None
    result = {
        "mode": mode,
        "alpha": alpha,
        "groups": len(groups),
        "pairs": count,
        "source_ids": sorted(groups),
        "radius": radius,
        "rank": rank,
        "group_max_residuals": ordered,
        "residual_cdf": [[v, (i + 1) / len(ordered)] for i, v in enumerate(ordered)],
        "scope": "exchangeable procedural sources in declared finite model; DP approximation errors",
        "conditional_coverage_guarantee": False,
        "ood_coverage_guarantee": False,
        "probability_prediction": False,
        "brier_score": None,
        "ece": None,
        "calibration_seconds": time.perf_counter() - started,
    }
    candidate.calibrations[mode] = result
    return result


def save_candidate(candidate, path):
    """Portable JSON checkpoint, authenticated at cold load by external SHA256."""
    value = {
        "schema": "hepta.bimodal.uncertain-advantage.v1",
        "model_id": candidate.model_id,
        "weights": {k: v.tolist() for k, v in candidate.network.state_dict().items()},
        "initial": [v.tolist() for v in candidate.initial],
        "support": [[list(s), a] for s, a in sorted(candidate.support)],
        "receipt": candidate.receipt,
        "calibrations": candidate.calibrations,
    }
    raw = (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()
    path = Path(path)
    with path.open("xb") as stream:
        stream.write(raw)
    return {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def load_candidate(path, expected_sha256, model):
    path = Path(path)
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > 32 * 1024 * 1024
    ):
        raise ValueError("Checkpoint outside bounded regular-file profile")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("Checkpoint pin differs")
    value = json.loads(raw)
    if value["schema"] != "hepta.bimodal.uncertain-advantage.v1" or value[
        "model_id"
    ] != model_identity(model):
        raise ValueError("Checkpoint source/model profile differs")
    weights = value["weights"]
    width, hidden = len(weights["hidden.weight"][0]), len(weights["hidden.weight"])
    if not 1 <= width <= 256 or not 1 <= hidden <= 256:
        raise ValueError("Checkpoint network shape outside bounded profile")
    network = AdvantageNet(width, hidden)
    tensors = {k: torch.tensor(v, dtype=torch.float64) for k, v in weights.items()}
    if not all(bool(torch.isfinite(v).all()) for v in tensors.values()):
        raise ValueError("Nonfinite checkpoint weights")
    network.load_state_dict(tensors, strict=True)
    network.eval().requires_grad_(False)
    initial = tuple(torch.tensor(v, dtype=torch.float64) for v in value["initial"])
    if len(initial) != 2 or any(
        a.shape != b.shape
        for a, b in zip(initial, (network.hidden.weight, network.hidden.bias))
    ):
        raise ValueError("Initial feature checkpoint schema differs")
    if not all(bool(torch.isfinite(v).all()) for v in initial):
        raise ValueError("Nonfinite initial features")
    support = frozenset((tuple(s), a) for s, a in value["support"])
    if (
        len(support) != len(value["support"])
        or digest(sorted((list(s), a) for s, a in support))
        != value["receipt"]["support_identity"]
    ):
        raise ValueError("Checkpoint support differs")
    return Candidate(
        network,
        initial,
        support,
        value["model_id"],
        value["receipt"],
        value["calibrations"],
    )
