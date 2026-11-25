"""True SmallHCSN features and new local corpora for the two-host study."""

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import time

for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[name] = "1"

import numpy as np
import torch

CAPSULE_SHA = "7ebe8aed55ce2e209f8be5dd016b4b13a8bb3fe6243b918d9648dd9a7114fe96"
PROVENANCE_SHA = "72194249d27b8af51cf95f89f5db494fa525e44c156eaf11b56e417ccc8c3b55"
NODES = ("pocket4", "ai395")
torch.set_num_threads(1)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def array_hash(*arrays):
    value = hashlib.sha256()
    for array in arrays:
        array = np.ascontiguousarray(array)
        value.update(encode([array.dtype.str, list(array.shape)]))
        value.update(array.tobytes())
    return value.hexdigest()


def source_identity():
    root = Path(__file__).parent
    return {name: file_sha(root / name) for name in ("features.py", "prepare.py")}


def load_model(capsule, width, seed):
    capsule = Path(capsule).resolve()
    if file_sha(capsule / "source_provenance.json") != PROVENANCE_SHA:
        raise ValueError("Physical source manifest differs from the pinned capsule")
    provenance = json.loads((capsule / "source_provenance.json").read_text())
    for name, expected in provenance["research_source_hashes"].items():
        if file_sha(capsule / "src" / name) != expected:
            raise ValueError("Physical source differs: " + name)
    sys.path.insert(0, str(capsule / "src"))
    from qualification.hcsn_smallnet_20261124.model import ModelConfig, SmallHCSN

    for name, module in sys.modules.items():
        if name.startswith("qualification") and getattr(module, "__file__", None):
            if not Path(module.__file__).resolve().is_relative_to(capsule / "src"):
                raise ValueError("Physical module imported outside the pinned capsule")
    torch.manual_seed(910000 + 101 * width + seed)
    model = SmallHCSN(ModelConfig(neurons=width, precision="float64", backend="dense"))
    model.eval()
    state_hashes = {name: array_hash(value.detach().cpu().numpy())
                    for name, value in model.state_dict().items()}
    return model, {"config": asdict(model.config), "state_sha256": digest(state_hashes),
                   "tensor_sha256": state_hashes,
                   "source_provenance_sha256": file_sha(capsule / "source_provenance.json")}


def corpus(split, node, seed, batch, count):
    if split not in ("calibration", "train", "test") or node not in NODES:
        raise ValueError("Unknown corpus namespace")
    source = {"calibration": 710000, "train": 720000, "test": 730000}[split]
    source += NODES.index(node) * 100 + batch
    rng = np.random.default_rng(20261125 + seed * 65537 + source * 1009)
    a = rng.uniform(-1, 1, count)
    bounds = (-1, .35) if node == NODES[0] else (-.35, 1)
    b = rng.uniform(*(bounds if split == "train" else (-1, 1)), count)
    arrival = rng.integers(4, 7, count) if split != "test" else rng.integers(3, 9, count)
    gain = rng.uniform(.8, 1.2)
    x = np.zeros((12, count, 6), dtype=np.float64)
    x[0, :, 0], x[0, :, 2] = gain * a, 1
    x[arrival, np.arange(count), 1], x[arrival, np.arange(count), 3] = gain * b, 1
    x[:, :, 4] = np.arange(12)[:, None] / 11
    noise = rng.normal(size=(12, count)) if node == NODES[0] else rng.laplace(size=(12, count))
    x[:, :, 5] = rng.uniform(.1, .3) * noise
    margin = rng.uniform(.4 if split == "test" else .45, .9 if split == "test" else .85, count)
    labels = None if split == "calibration" else np.where(a + b > 0, 1., -1.)
    return {"x": x, "margin": margin, "y": labels, "arrival": arrival,
            "source": source, "split": split, "node": node, "seed": seed,
            "ids": [f"actual-p2p-v2:{split}:{source}:{seed}:{i}" for i in range(count)]}


@torch.no_grad()
def extract(model, batch, chunk=16):
    features, margins, max_mass, max_mark = [], [], 0., 0.
    started = time.perf_counter()
    for offset in range(0, len(batch["margin"]), chunk):
        margin = torch.tensor(batch["margin"][offset:offset + chunk], dtype=torch.float64)
        x = torch.tensor(batch["x"][:, offset:offset + chunk], dtype=torch.float64)
        state = model.initial_state(len(margin), margin[:, None])
        logits, value, _ = model(x, state=state, return_features=True)
        features.append(value[-1].cpu().numpy())
        margins.append((logits[-1, :, 1] - logits[-1, :, 0]).cpu().numpy())
        max_mass = max(max_mass, model.last_diagnostics["mass_error"])
        max_mark = max(max_mark, model.last_diagnostics["mark_excess"])
    return np.concatenate(features), {"wall_s": time.perf_counter() - started,
                                      "mass_error": max_mass, "mark_excess": max_mark,
                                      "model_logit_margin": np.concatenate(margins).tolist()}


def coordinates(features, basis):
    normalized = (features - np.asarray(basis["mean"])) / np.asarray(basis["scale"])
    return np.column_stack((normalized, np.ones(len(normalized))))
