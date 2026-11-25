"""Shared true-SmallHCSN utilities; train-fitted scaling never changes physics."""
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_name] = "1"
CAPSULE = Path(os.environ["PFT_HCSN_CAPSULE"]).resolve()
sys.path.insert(0, str(CAPSULE / "src"))
import numpy as np
import torch
from qualification.hcsn_smallnet_20261124.model import ModelConfig, SmallHCSN

FIELDS = ("density", "boundary", "drift", "cost", "message")
torch.set_num_threads(1)
torch.set_num_interop_threads(1)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def dump(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n")


def validate_sources():
    provenance = json.loads((CAPSULE / "source_provenance.json").read_text())
    for name, expected in provenance["research_source_hashes"].items():
        if sha(CAPSULE / "src" / name) != expected:
            raise ValueError("Physical source changed: " + name)
    imported = {name: str(Path(module.__file__).resolve()) for name, module in sys.modules.items()
                if (name == "qualification" or name.startswith("qualification.")) and getattr(module, "__file__", None)}
    if any(not Path(p).is_relative_to(CAPSULE / "src") for p in imported.values()):
        raise ValueError("Physical source imported outside frozen capsule")
    return {"capsule_source_provenance_sha256": sha(CAPSULE / "source_provenance.json"),
            "imported_paths": imported, "research_source_hashes": provenance["research_source_hashes"]}


def runtime():
    return {"python": platform.python_version(), "numpy": np.__version__, "torch": str(torch.__version__),
            "threads": torch.get_num_threads(), "interop_threads": torch.get_num_interop_threads(),
            "device": "cpu", "capsule": str(CAPSULE)}


def data(split, per_source=16, seed=271, phase="diagnosis"):
    allowed = ("train", "dev") if phase == "diagnosis" else ("train", "dev", "test")
    if split not in allowed:
        raise ValueError("Split forbidden in this phase")
    prefix = 440000 if phase == "diagnosis" else 540000
    start = prefix + {"train": 0, "dev": 100, "test": 200}[split]
    xs, ys, margins, late, latent, ids = [], [], [], [], [], []
    for source in range(start, start + 4):
        rng = np.random.default_rng(20261125 + seed * 10007 + source * 1009)
        a, b = rng.uniform(-1, 1, (2, per_source))
        gain, noise, correlation = rng.uniform(.85, 1.15), rng.uniform(.08, .35), rng.uniform(-.5, .7)
        arrival = rng.integers(4, 7, per_source)
        x = np.zeros((12, per_source, 6))
        x[0, :, 0], x[0, :, 2] = gain * a, 1
        x[arrival, np.arange(per_source), 1], x[arrival, np.arange(per_source), 3] = gain * b, 1
        x[:, :, 4] = np.arange(12)[:, None] / 11
        for tick in range(12):
            x[tick, :, 5] = noise * rng.normal(size=per_source)
            if tick:
                x[tick, :, 5] += correlation * x[tick - 1, :, 5]
        xs.append(x); ys.append((a + b > 0).astype(np.int64)); latent.append(np.stack((a, b), -1))
        margins.append(rng.uniform(.45, .85, per_source)); late.append(arrival)
        ids.extend(f"actual-v2:{phase}:{seed}:{source}:{i}" for i in range(per_source))
    return {"x": torch.tensor(np.concatenate(xs, 1), dtype=torch.float64),
            "y": torch.tensor(np.concatenate(ys)), "margin": torch.tensor(np.concatenate(margins)),
            "late": torch.tensor(np.concatenate(late)), "latent": np.concatenate(latent), "ids": ids}


def data_hash(batch):
    h = hashlib.sha256()
    for key in ("x", "y", "margin", "late"):
        a = batch[key].numpy()
        h.update(str((a.dtype.str, a.shape)).encode()); h.update(a.tobytes())
    h.update("\n".join(batch["ids"]).encode())
    return h.hexdigest()


def select(batch, indices):
    idx = torch.as_tensor(indices)
    return {**batch, "x": batch["x"][:, idx], "y": batch["y"][idx],
            "margin": batch["margin"][idx], "late": batch["late"][idx]}


def make_model(width, seed, bank="value_risk", message="full", connection="learned"):
    torch.manual_seed(seed + 101 * width)
    model = SmallHCSN(ModelConfig(neurons=width, precision="float64", backend="dense",
                                 feature_bank=bank, message_mode=message))
    model.recurrent.weight.requires_grad_(connection == "learned")
    return model


def forward(model, batch):
    x = batch["x"].to(model.input_drive.weight)
    state = model.initial_state(len(batch["y"]), batch["margin"][:, None])
    return model(x, state=state, return_features=True)


@torch.no_grad()
def extract(model, batch, chunk=8):
    start = time.perf_counter()
    logits, features, errors = [], [], []
    for offset in range(0, len(batch["y"]), chunk):
        lo, fe, state = forward(model, select(batch, range(offset, min(offset + chunk, len(batch["y"])))))
        logits.append(lo); features.append(fe); errors.append(dict(model.last_diagnostics))
    return torch.cat(logits, 1), torch.cat(features, 1), {
        "wall_s": time.perf_counter() - start,
        "mass_error": max(e["mass_error"] for e in errors),
        "mark_excess": max(e["mark_excess"] for e in errors),
        "min_probability": min(e["probability_min"] for e in errors)}


def metrics(logits, batch):
    logits = torch.as_tensor(logits).double()
    if logits.ndim == 2:
        logits = logits[None]
    y = batch["y"]
    p = logits[-1].softmax(-1)
    target = torch.nn.functional.one_hot(y, 2).double()
    result = {"accuracy": float((p.argmax(-1) == y).double().mean()),
              "cross_entropy": float(torch.nn.functional.cross_entropy(logits[-1], y)),
              "brier": float(((p - target) ** 2).sum(-1).mean()), "n": len(y)}
    if len(logits) == 12:
        early = logits[batch["late"] - 1, torch.arange(len(y))]
        result["pre_late_accuracy"] = float((early.argmax(-1) == y).double().mean())
    return result


def fit_ridge(features, labels, ridge, scaled=True, floor=1e-6):
    x = np.asarray(features, dtype=np.float64)
    mean = x.mean(0)
    observed_std = x.std(0)
    scale = np.maximum(observed_std, floor) if scaled else np.ones(x.shape[1])
    z = (x - mean) / scale
    y = 2 * np.eye(2)[np.asarray(labels)] - 1
    bias = y.mean(0)
    start = time.perf_counter()
    gram = z.T @ z / len(z)
    weight = np.linalg.solve(gram + ridge * np.eye(z.shape[1]), z.T @ (y - bias) / len(z))
    return {"mean": mean, "scale": scale, "weight": weight, "bias": bias,
            "solve_s": time.perf_counter() - start, "std": observed_std,
            "ridge": ridge, "floor": floor}


def ridge_logits(fit, features):
    return ((np.asarray(features) - fit["mean"]) / fit["scale"]) @ fit["weight"] + fit["bias"]


class ScaledReadout(torch.nn.Module):
    """Train-only frozen statistics, with a well-scaled trainable linear head."""
    def __init__(self, fit):
        super().__init__()
        self.register_buffer("mean", torch.tensor(fit["mean"], dtype=torch.float64))
        self.register_buffer("scale", torch.tensor(fit["scale"], dtype=torch.float64))
        self.linear = torch.nn.Linear(len(fit["mean"]), 2, dtype=torch.float64)
        with torch.no_grad():
            self.linear.weight.copy_(torch.tensor(fit["weight"].T))
            self.linear.bias.copy_(torch.tensor(fit["bias"]))

    def forward(self, features):
        return self.linear((features - self.mean) / self.scale)


def feature_statistics(features, y):
    x = np.asarray(features, dtype=np.float64)
    centered = x - x.mean(0)
    std = centered.std(0)
    sv = np.linalg.svd(centered / np.sqrt(len(x)), compute_uv=False)
    target = 2 * np.asarray(y) - 1
    covariance = centered.T @ (target - target.mean()) / len(x)
    correlation = covariance / np.maximum(std * target.std(), 1e-30)
    groups = {}
    for i, name in enumerate(("value", "risk", "signed_rate", "rate", "margin")):
        s = std[i::5]
        groups[name] = {"std_min": float(s.min()), "std_median": float(np.median(s)),
                        "std_max": float(s.max()), "max_abs_label_correlation": float(np.abs(correlation[i::5]).max())}
    positive = sv[sv > (sv[0] * 1e-10 if len(sv) else 0)]
    return {"groups": groups, "singular_values": sv.tolist(),
            "centered_effective_rank_relative_1e10": len(positive),
            "condition_positive_spectrum": float(sv[0] / positive[-1]) if len(positive) else None,
            "constant_columns_at_1e12": int((std < 1e-12).sum()),
            "fraction_variance_below_old_penalty_0p02": float((std ** 2 < .02).mean())}


def state_payload(model):
    return {name: value.detach().clone() for name, value in model.state_dict().items()}


def parameter_summary(model):
    allocated = model.recurrent.weight.numel()
    active = int(torch.count_nonzero(model.synaptic_mask))
    return {"allocated": sum(p.numel() for p in model.parameters()),
            "trainable": sum(p.numel() for p in model.parameters() if p.requires_grad),
            "recurrent_allocated": allocated, "recurrent_mask_active": active,
            "recurrent_trainable": model.recurrent.weight.requires_grad,
            "physical_backend": model.config.backend, "physical_precision": model.config.precision}
