"""Canonical identities, fixed phase streams, and explicit cost receipts."""

import gzip
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np

BASE = "5898cd8b0f724c3152b6cc52856721f72e5e08be"
SEEDS = [1709, 1721, 1741, 1753, 1777, 1789, 1801, 1811]
ARMS = [
    "fixed_margin",
    "learned_margin",
    "value_margin",
    "value_call",
    "value_dual",
    "generic_gate",
    "native_sparse",
    "event_reset",
    "dense_recurrent",
]
CONTROLS = ["dp", "always_keep", "always_repair", "always_stop"]
PAIRS = [
    {"name": "boundary", "treatment": "value_margin", "control": "learned_margin"},
    {"name": "dual", "treatment": "value_dual", "control": "value_call"},
    {"name": "flow", "treatment": "value_dual", "control": "event_reset"},
]
CANDIDATES = [
    {"decay": d, "gain_c": c, "gain_p": p, "fixed_boundary": b}
    for d, c, p, b in [
        (0.0, 0.0, 0.0, 0.25),
        (0.35, 0.2, 0.2, 0.25),
        (0.7, 0.5, 0.5, 0.25),
        (0.15, 0.1, 0.1, 0.5),
        (0.35, 0.2, 0.6, 0.5),
        (0.7, 0.6, 0.2, 0.5),
        (0.35, 0.4, 0.4, 0.8),
        (0.65, 0.4, 0.8, 0.8),
        (0.65, 0.8, 0.4, 0.8),
        (0.85, 0.25, 0.25, 1.1),
        (0.8, 0.5, 1.0, 1.1),
        (0.8, 1.0, 0.5, 1.1),
    ]
]


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def named_seed(seed, name):
    return int.from_bytes(hashlib.sha256(f"{seed}:{name}".encode()).digest()[:8], "big")


def rng_for(seed, name):
    return np.random.Generator(np.random.Philox(named_seed(seed, name)))


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical(data) + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
    return sha(raw)


def write_records(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = b"".join(canonical(row) + b"\n" for row in records)
    with path.open("xb") as stream:
        stream.write(gzip.compress(raw, compresslevel=9, mtime=0))
    return {
        "path": str(path),
        "sha256": sha(path.read_bytes()),
        "count": len(records),
        "uncompressed_sha256": sha(raw),
        "uncompressed_bytes": len(raw),
    }


class CostWindow:
    def __init__(self):
        self.wall = time.perf_counter()
        self.cpu = time.process_time()
        self.child = resource.getrusage(resource.RUSAGE_CHILDREN)

    def finish(self):
        child = resource.getrusage(resource.RUSAGE_CHILDREN)
        return {
            "wall_seconds": time.perf_counter() - self.wall,
            "python_cpu_seconds": time.process_time() - self.cpu,
            "completed_child_cpu_seconds": child.ru_utime
            + child.ru_stime
            - self.child.ru_utime
            - self.child.ru_stime,
            "child_cpu_scope": "children reaped inside this measurement window",
        }


def protocol():
    return {
        "schema": "hepta.continuous-boundary.protocol.v1",
        "base_commit": BASE,
        "seeds": SEEDS,
        "phase_ids": {
            "training": [
                f"{seed}.training.context{i}" for seed in SEEDS for i in range(12)
            ],
            "development": [
                f"{seed}.development.context{i}" for seed in SEEDS for i in range(8)
            ],
            "confirmation": [
                f"{seed}.{split}.context{i}"
                for seed in SEEDS
                for split in ("test_id", "test_ood")
                for i in range(8)
            ],
        },
        "arms": ARMS + CONTROLS,
        "primary_pairs": PAIRS,
        "train_contexts": 12,
        "train_episodes_per_context": 8,
        "development_contexts": 8,
        "development_episodes_per_context": 8,
        "confirmation_contexts_per_split": 8,
        "confirmation_episodes_per_context": 16,
        "splits": {"test_id": 128, "test_ood": 128},
        "split_weights": {"test_id": 0.5, "test_ood": 0.5},
        "grid_states": 64,
        "grid_upper_domain": 4.8,
        "native_width": 20,
        "native_top_k": 4,
        "readout_trainable_scalars": 42,
        "ridge_penalty": 0.01,
        "candidates": CANDIDATES,
        "selection": "maximum paired development mean net utility; smallest candidate index ties",
        "training": "same behavior trajectories and public-model DP Q teacher; ridge readout; frozen encoder; development-selected feedback",
        "boundary_training": "direct public-context threshold regression on training contexts only",
        "primary_sample_unit": "independent training/environment seed",
        "familywise_alpha": 0.05,
        "minimum_effect": 0.005,
        "message_price_per_byte": 0.000001,
        "message_price_scope": "numeric i64 model-port payload only; actual JSON wire bytes reported separately",
        "cpu_price": None,
        "energy_measurement": None,
        "cost_decision": "task net utility and measured total costs reported jointly; no universal efficiency claim",
        "risk_forecast": "action-conditioned current-window first hit, computed before outcome",
        "failure_recovery": "no production after failure until next decision window; reset then",
        "continuous_flow": "past action-conditioned expected first-hit flow; individual task paths remain sampled",
        "native_execution": "all neural arms use original source sparse kernel and NDU in persistent pure sessions; separate durable original owner study",
        "authority": "research only; original native DENY_ALL",
        "confirmation_failure": "exception aborts the incomplete run with prior evidence preserved; no episode omission, resampling or seed extension; audit requires every registered episode",
    }
