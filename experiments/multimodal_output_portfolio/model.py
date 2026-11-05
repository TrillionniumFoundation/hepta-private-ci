"""Tiny learned four-modality encoder/generator for a synthetic mechanism pilot.

Each raw modality has an encoder. Its eight-class probabilities are the initial
generation state; a single shared, three-step residual network then feeds four
neural decoders. Canonical training targets are supplied by the caller and are
never stored in the model or consulted by inference. This is neither a pretrained
omnimodal model nor native NDU, diffusion training, or joint NDU/model training.
"""

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F


NUM_CLASSES = 8
MODALITIES = ("text", "audio", "image", "video")
WIDTH = 64
REFINEMENT_STEPS = 3
SCHEMA = "hepta.multimodal-output-portfolio.tiny-model.v1"


class OutputModel(nn.Module):
    """Four learned encoders, one shared refinement owner, four learned decoders."""

    def __init__(self, dimensions):
        super().__init__()
        if set(dimensions) != set(MODALITIES) or any(
            type(d) is not int or not 1 <= d <= 65536 for d in dimensions.values()
        ):
            raise ValueError("four bounded raw modality dimensions required")
        torch.set_num_threads(min(4, max(1, torch.get_num_threads())))
        self.dimensions = dict(dimensions)
        self.encoders = nn.ModuleDict({
            name: nn.Sequential(nn.Linear(dimensions[name], WIDTH), nn.GELU(),
                                nn.Linear(WIDTH, NUM_CLASSES))
            for name in MODALITIES
        })
        self.initial_latent = nn.Linear(NUM_CLASSES, WIDTH)
        self.refinement = nn.Sequential(
            nn.Linear(WIDTH, WIDTH), nn.Tanh(), nn.Linear(WIDTH, WIDTH)
        )
        self.decoders = nn.ModuleDict({
            name: nn.Sequential(nn.Linear(WIDTH, WIDTH), nn.GELU(),
                                nn.Linear(WIDTH, dimensions[name]))
            for name in MODALITIES
        })

    def forward(self, portfolios):
        latent = self.initial_latent(portfolios)
        for _ in range(REFINEMENT_STEPS):
            latent = latent + self.refinement(latent) / REFINEMENT_STEPS
        return {name: self.decoders[name](latent) for name in MODALITIES}


def _matrix(value, width=None):
    array = np.asarray(value)
    if (array.ndim != 2 or (width is not None and array.shape[1] != width)
            or array.dtype.kind not in "fiu" or not np.isfinite(array).all()):
        raise ValueError("finite numeric [batch, dimension] matrix required")
    result = np.array(array, dtype=np.float32, order="C", copy=True)
    if not np.isfinite(result).all():
        raise ValueError("matrix overflows float32")
    return result


def _weight_hashes(model):
    groups = {name: hashlib.sha256() for name in
              ("all", "encoders", "shared_refinement", "decoders")}
    for name, value in sorted(model.state_dict().items()):
        group = ("encoders" if name.startswith("encoders.") else
                 "decoders" if name.startswith("decoders.") else "shared_refinement")
        array = value.detach().cpu().contiguous().numpy()
        header = json.dumps([name, list(array.shape), str(array.dtype)],
                            separators=(",", ":")).encode()
        payload = array.tobytes(order="C")
        for key in ("all", group):
            groups[key].update(len(header).to_bytes(8, "little"))
            groups[key].update(header)
            groups[key].update(payload)
    return {name: digest.hexdigest() for name, digest in groups.items()}


def mac_counts(model):
    """Ideal dense Linear MACs; one multiply/add pair counts as one MAC.

    These formula counts exclude bias, activations, softmax, residual additions,
    transfers, backward, optimizer, and controller cost. They are not measured
    FLOPs, physical kernel counts, energy, latency, or end-to-end service cost.
    """
    encoder = {name: model.dimensions[name] * WIDTH + WIDTH * NUM_CLASSES
               for name in MODALITIES}
    shared = NUM_CLASSES * WIDTH + REFINEMENT_STEPS * 2 * WIDTH * WIDTH
    decoder = {name: WIDTH * WIDTH + WIDTH * model.dimensions[name]
               for name in MODALITIES}
    return {"unit": "ideal_dense_linear_MAC_per_example",
            "encoder": encoder, "shared_refinement": shared, "decoder": decoder,
            "generate_all_modalities": shared + sum(decoder.values()),
            "encode_all_and_generate": sum(encoder.values()) + shared + sum(decoder.values()),
            "shared_refinement_counted_once": True,
            "hardware_flops_or_total_cost_measurement": False}


def _mixtures(rng, count):
    """Fixed curriculum: half vertices, quarter edges, quarter Dirichlet(0.6)."""
    vertices = count // 2
    edges = count // 4
    result = np.zeros((count, NUM_CLASSES), dtype=np.float32)
    result[:vertices] = np.eye(NUM_CLASSES, dtype=np.float32)[
        rng.integers(NUM_CLASSES, size=vertices)]
    for i in range(vertices, vertices + edges):
        pair = rng.choice(NUM_CLASSES, 2, replace=False)
        weight = rng.uniform()
        result[i, pair] = (weight, 1.0 - weight)
    result[vertices + edges:] = rng.dirichlet(
        np.full(NUM_CLASSES, 0.6), size=count - vertices - edges)
    return torch.from_numpy(result)


@torch.inference_mode()
def _diagnostics(model, raw, labels, targets, mixtures):
    model.eval()
    accuracy, ce = {}, {}
    for name in MODALITIES:
        logits = model.encoders[name](raw[name])
        accuracy[name] = float((logits.argmax(1) == labels).float().mean())
        ce[name] = float(F.cross_entropy(logits, labels))
    outputs = model(mixtures)
    mse = {name: float(F.mse_loss(outputs[name], mixtures @ targets[name]))
           for name in MODALITIES}
    return {"encoder_training_accuracy": accuracy, "encoder_training_ce": ce,
            "generator_fixed_probe_mse": mse,
            "probe_is_heldout_task_evidence": False}


def train_model(train_raw, train_labels, canonical_targets, seed, steps=400):
    """Train on supplied clean rendered labels and supplied eight prototype rows.

    One AdamW update jointly fits four supervised encoders and the shared
    generator on a fixed vertex/edge/Dirichlet curriculum. The generator target
    is the convex combination of training prototypes. It is a deliberately
    specified output-mixing task, not discovered compositional understanding.
    Neither heldout outcomes nor the portfolio controller enter optimization.
    """
    if (set(train_raw) != set(MODALITIES) or set(canonical_targets) != set(MODALITIES)
            or type(seed) is not int or not 0 <= seed < 2**32
            or type(steps) is not int or not 1 <= steps <= 10000):
        raise ValueError("four modalities, bounded integer seed and positive steps required")
    labels = np.asarray(train_labels)
    if (labels.ndim != 1 or labels.dtype.kind not in "iu" or len(labels) < NUM_CLASSES
            or set(labels.tolist()) != set(range(NUM_CLASSES))):
        raise ValueError("training labels must cover exactly the eight semantic classes")
    arrays = {name: _matrix(train_raw[name]) for name in MODALITIES}
    dimensions = {name: int(array.shape[1]) for name, array in arrays.items()}
    target_arrays = {name: _matrix(canonical_targets[name], dimensions[name])
                     for name in MODALITIES}
    if (any(len(array) != len(labels) for array in arrays.values())
            or any(array.shape[0] != NUM_CLASSES for array in target_arrays.values())):
        raise ValueError("aligned training rows and eight canonical target rows required")
    raw = {name: torch.from_numpy(array) for name, array in arrays.items()}
    target = {name: torch.from_numpy(array) for name, array in target_arrays.items()}
    y = torch.from_numpy(np.array(labels, dtype=np.int64, copy=True))
    scale = {name: target[name].square().mean().clamp(min=0.05) for name in MODALITIES}
    rng = np.random.default_rng(seed)
    probes = torch.cat((torch.eye(NUM_CLASSES), _mixtures(
        np.random.default_rng(seed ^ 0x516E2B), 128)))
    batch_size = min(128, len(labels))
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model = OutputModel(dimensions)
        initial_hashes = _weight_hashes(model)
        initial_metrics = _diagnostics(model, raw, y, target, probes)
        optimizer = torch.optim.AdamW(model.parameters(), lr=0.003, weight_decay=0.0001)
        history = []
        model.train()
        for step in range(steps):
            index = torch.from_numpy(rng.integers(len(labels), size=batch_size))
            encoder_loss = sum(F.cross_entropy(model.encoders[name](raw[name][index]), y[index])
                               for name in MODALITIES) / len(MODALITIES)
            portfolios = _mixtures(rng, batch_size)
            outputs = model(portfolios)
            generator_loss = sum(F.mse_loss(outputs[name], portfolios @ target[name]) / scale[name]
                                 for name in MODALITIES) / len(MODALITIES)
            loss = encoder_loss + generator_loss
            if not torch.isfinite(loss):
                raise RuntimeError("nonfinite training loss")
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0, error_if_nonfinite=True)
            optimizer.step()
            if step == 0 or (step + 1) % 50 == 0 or step + 1 == steps:
                history.append({"step": step + 1, "encoder_ce": float(encoder_loss.detach()),
                                "generator_normalized_mse": float(generator_loss.detach())})
        model.eval()
        final_metrics = _diagnostics(model, raw, y, target, probes)
        final_hashes = _weight_hashes(model)
        model.requires_grad_(False)
    wall, cpu = time.perf_counter() - start_wall, time.process_time() - start_cpu
    if any(not torch.isfinite(value).all() for value in model.state_dict().values()):
        raise RuntimeError("nonfinite learned weights")
    counts = mac_counts(model)
    parameter_counts = {"all": sum(p.numel() for p in model.parameters()),
                        "encoders": sum(p.numel() for p in model.encoders.parameters()),
                        "decoders": sum(p.numel() for p in model.decoders.parameters())}
    parameter_counts["shared_refinement"] = (
        parameter_counts["all"] - parameter_counts["encoders"] - parameter_counts["decoders"])
    receipt = {
        "schema": SCHEMA, "seed": seed, "steps": steps, "optimizer_steps": steps,
        "train_examples": len(labels), "batch_size": batch_size, "dimensions": dimensions,
        "width": WIDTH, "shared_refinement_steps": REFINEMENT_STEPS,
        "optimizer": {"name": "AdamW", "lr": 0.003, "weight_decay": 0.0001,
                      "gradient_norm_cap": 5.0},
        "generator_curriculum": {"vertices": 0.5, "edges": 0.25,
                                  "dirichlet": 0.25, "dirichlet_concentration": 0.6},
        "generator_mse_normalizers": {name: float(scale[name]) for name in MODALITIES},
        "parameter_counts": parameter_counts,
        "initial_weight_sha256": initial_hashes, "final_weight_sha256": final_hashes,
        "parameter_groups_changed": {key: initial_hashes[key] != final_hashes[key]
                                     for key in initial_hashes},
        "initial_diagnostics": initial_metrics, "final_diagnostics": final_metrics,
        "loss_history": history, "mac_profile": counts,
        "training_forward_linear_macs": steps * batch_size * counts["encode_all_and_generate"],
        "diagnostic_forward_linear_macs": 2 * (
            len(labels) * sum(counts["encoder"].values())
            + len(probes) * counts["generate_all_modalities"]),
        "training_wall_seconds": wall, "training_process_cpu_seconds": cpu,
        "runtime": {"torch": str(torch.__version__), "numpy": np.__version__,
                    "device": "cpu", "dtype": "float32", "threads": torch.get_num_threads()},
        "inference_reads_renderer_or_targets": False,
        "training_uses_controller_or_heldout_outcomes": False,
        "scope": "synthetic_tiny_learned_encoder_generator_mechanism_pilot",
        "native_ndu_integration": False, "ndu_joint_training": False,
    }
    return model, receipt


@torch.inference_mode()
def encode(model, modality, raw):
    """Encode observed raw content; no latent world labels are accepted."""
    if modality not in MODALITIES:
        raise ValueError("unknown modality")
    array = _matrix(raw, model.dimensions[modality])
    model.eval()
    logits = model.encoders[modality](torch.from_numpy(array))
    probabilities = torch.softmax(logits, dim=1).cpu().numpy()
    return probabilities.argmax(axis=1).astype(np.int64), probabilities.astype(np.float32)


@torch.inference_mode()
def generate(model, portfolios):
    """Decode simplex portfolios through learned weights, without a renderer."""
    array = _matrix(portfolios, NUM_CLASSES)
    if (np.any(array < 0) or np.any(array > 1)
            or not np.allclose(array.sum(axis=1), 1.0, rtol=0, atol=2e-6)):
        raise ValueError("nonnegative unit-mass portfolios required")
    model.eval()
    outputs = model(torch.from_numpy(array))
    return {name: value.cpu().numpy().astype(np.float32) for name, value in outputs.items()}


def save_model(model, path):
    """Create a checkpoint without replacing existing experiment evidence."""
    with Path(path).open("xb") as destination:
        torch.save({"schema": SCHEMA, "dimensions": model.dimensions,
                    "state_dict": model.state_dict(), "weight_sha256": _weight_hashes(model)},
                   destination)


def load_model(path):
    """Load tensor-only checkpoint data on CPU and verify the recorded digest."""
    saved = torch.load(path, map_location="cpu", weights_only=True)
    if saved.get("schema") != SCHEMA:
        raise ValueError("unsupported checkpoint schema")
    model = OutputModel(saved["dimensions"])
    model.load_state_dict(saved["state_dict"], strict=True)
    if _weight_hashes(model) != saved["weight_sha256"]:
        raise ValueError("checkpoint weight digest mismatch")
    return model.eval().requires_grad_(False)
