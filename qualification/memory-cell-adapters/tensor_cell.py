"""Trainable low-rank memory after a frozen, identity-bound feature encoder.

The operator is W_eff = I + B @ A.  The ONNX encoder is never differentiated.
Checkpoints contain float32 parameters and provenance, never training answers.
"""

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import zipfile

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F


BLOB_CAP = 512000
CHUNK_ELEMENTS = 100000


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class OutputSpec:
    name: str
    kind: str = "binary"
    size: int = 8
    weight: float = 1.0

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", self.name):
            raise ValueError("invalid output name")
        if self.kind not in {"binary", "multiclass", "regression"}:
            raise ValueError("unknown output kind")
        if type(self.size) is not int or not 1 <= self.size <= 4096:
            raise ValueError("invalid output size")
        if self.kind == "multiclass" and self.size < 2:
            raise ValueError("multiclass needs at least two classes")
        if not math.isfinite(self.weight) or self.weight <= 0:
            raise ValueError("invalid loss weight")


@dataclass(frozen=True)
class CellConfig:
    cell_id: str
    rank: int = 4
    input_dim: int = 384
    outputs: tuple = (OutputSpec("bits"),)
    seed: int = 0

    def __post_init__(self):
        if not isinstance(self.cell_id, str) or not 1 <= len(self.cell_id) <= 128:
            raise ValueError("invalid cell identity")
        if type(self.input_dim) is not int or not 1 <= self.input_dim <= 4096:
            raise ValueError("invalid feature dimension")
        if type(self.rank) is not int or not 1 <= self.rank <= self.input_dim:
            raise ValueError("rank must be in 1..input_dim")
        if not self.outputs or any(not isinstance(x, OutputSpec) for x in self.outputs):
            raise ValueError("typed output specifications required")
        if len({x.name for x in self.outputs}) != len(self.outputs):
            raise ValueError("duplicate output names")
        if type(self.seed) is not int or not 0 <= self.seed < 2**63:
            raise ValueError("invalid initialization seed")


TensorCellConfig = CellConfig


class TensorCell(nn.Module):
    """A CPU float32 residual adapter and an explicitly accounted task head."""

    def __init__(self, config, base_encoder_sha, source_ids=(), head=None):
        super().__init__()
        if not re.fullmatch(r"[0-9a-f]{64}", base_encoder_sha):
            raise ValueError("encoder identity must be a SHA-256 digest")
        self.config = config
        self.base_encoder_sha = base_encoder_sha
        self.source_ids = set(source_ids)
        self.parents = []
        self.training_history = []
        self.head_frozen = head is not None
        self._shared_head = head is not None
        width = sum(x.size for x in config.outputs)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(config.seed)
            self.A = nn.Parameter(torch.randn(config.rank, config.input_dim) * 0.02)
            self.B = nn.Parameter(torch.zeros(config.input_dim, config.rank))
            self.head = head if head is not None else nn.Linear(config.input_dim, width)
        if self.head.in_features != config.input_dim or self.head.out_features != width:
            raise ValueError("shared head is incompatible with the output schema")
        if self.head_frozen:
            self.freeze_head()

    def freeze_head(self):
        self.head_frozen = True
        self.head.requires_grad_(False)
        for parameter in self.head.parameters():
            parameter.grad = None
        return self

    def forward(self, features):
        return self.head(features + (features @ self.A.T) @ self.B.T)

    def _features(self, features):
        value = torch.as_tensor(np.asarray(features, dtype=np.float32)).detach()
        if value.ndim != 2 or value.shape[1] != self.config.input_dim:
            raise ValueError("features must have shape [N, input_dim]")
        if not torch.isfinite(value).all():
            raise ValueError("nonfinite features")
        return value

    def _targets(self, targets, count):
        if not isinstance(targets, dict):
            if len(self.config.outputs) != 1:
                raise ValueError("multiple outputs require a target dictionary")
            targets = {self.config.outputs[0].name: targets}
        if set(targets) != {s.name for s in self.config.outputs}:
            raise ValueError("target names differ from the output schema")
        result = {}
        for spec in self.config.outputs:
            value = torch.as_tensor(np.asarray(targets[spec.name])).detach()
            if spec.kind == "multiclass" and value.ndim == 1:
                if value.shape != (count,) or not torch.equal(value, value.long()):
                    raise ValueError("invalid class labels")
                value = value.long()
                if torch.any((value < 0) | (value >= spec.size)):
                    raise ValueError("class label outside vocabulary")
            else:
                if value.ndim == 1 and spec.size == 1:
                    value = value[:, None]
                value = value.float()
                if value.shape != (count, spec.size) or not torch.isfinite(value).all():
                    raise ValueError("invalid target shape or value")
                if spec.kind != "regression" and torch.any((value < 0) | (value > 1)):
                    raise ValueError("probability target outside [0, 1]")
                if spec.kind == "multiclass" and not torch.allclose(value.sum(1), torch.ones(count)):
                    raise ValueError("class probabilities must sum to one")
            result[spec.name] = value
        return result

    def _loss(self, raw, targets):
        start = 0
        losses = []
        for spec in self.config.outputs:
            values = raw[:, start : start + spec.size]
            target = targets[spec.name]
            if spec.kind == "binary":
                loss = F.binary_cross_entropy_with_logits(values, target)
            elif spec.kind == "multiclass":
                loss = F.cross_entropy(values, target)
            else:
                loss = F.mse_loss(values, target)
            losses.append(spec.weight * loss)
            start += spec.size
        return sum(losses) / sum(s.weight for s in self.config.outputs)

    def fit(self, features, targets, *, source_ids, steps=100, batch_size=32, lr=0.01, seed=0, train_head=None):
        """Perform exactly steps * batch_size sampled training presentations."""
        started, cpu_started = time.perf_counter(), time.process_time()
        x = self._features(features)
        count = len(x)
        ids = list(source_ids)
        if not count or len(ids) != count or any(not isinstance(s, str) or not s for s in ids):
            raise ValueError("one nonempty source identity per training row is required")
        if type(steps) is not int or steps < 1 or type(batch_size) is not int or batch_size < 1:
            raise ValueError("positive integer training budget required")
        if not math.isfinite(lr) or lr <= 0:
            raise ValueError("positive finite learning rate required")
        update_head = not self.head_frozen if train_head is None else train_head
        if update_head and self.head_frozen:
            raise ValueError("a frozen or shared head cannot be updated")
        self.head.requires_grad_(update_head)
        y = self._targets(targets, count)
        before = self.parameter_digest()
        with torch.no_grad():
            initial_loss = float(self._loss(self(x), y))
        optimizer = torch.optim.Adam([p for p in self.parameters() if p.requires_grad], lr=lr)
        generator = torch.Generator().manual_seed(seed)
        schedule = hashlib.sha256()
        seen = set()
        gradients = {name: 0.0 for name, p in self.named_parameters() if p.requires_grad}
        for _ in range(steps):
            rows = torch.randint(count, (batch_size,), generator=generator)
            schedule.update(rows.numpy().astype("<i8").tobytes())
            seen.update(rows.tolist())
            optimizer.zero_grad(set_to_none=True)
            loss = self._loss(self(x[rows]), {key: value[rows] for key, value in y.items()})
            if not torch.isfinite(loss):
                raise FloatingPointError("nonfinite training loss")
            loss.backward()
            for name, parameter in self.named_parameters():
                if parameter.requires_grad and parameter.grad is not None:
                    if not torch.isfinite(parameter.grad).all():
                        raise FloatingPointError("nonfinite parameter gradient")
                    gradients[name] = max(gradients[name], float(parameter.grad.norm()))
            optimizer.step()
        with torch.no_grad():
            final_loss = float(self._loss(self(x), y))
        if not math.isfinite(final_loss):
            raise FloatingPointError("nonfinite final training loss")
        self.source_ids.update(ids[index] for index in seen)
        receipt = {
            "schema": "memory-adapter.training.v1", "steps": steps, "batch_size": batch_size,
            "sample_presentations": steps * batch_size, "diagnostic_forward_rows": 2 * count,
            "unique_rows_seen": len(seen), "available_rows": count, "seed": seed, "lr": lr,
            "source_ids_sha256": digest(canonical(ids)), "sample_schedule_sha256": schedule.hexdigest(),
            "features_sha256": digest(x.numpy().astype("<f4").tobytes()),
            "targets_sha256": {key: digest(value.numpy().tobytes()) for key, value in y.items()},
            "initial_parameter_sha256": before, "final_parameter_sha256": self.parameter_digest(),
            "initial_loss": initial_loss, "final_loss": final_loss, "max_gradient_norm": gradients,
            "parameter_counts": self.parameter_counts(), "updated_head": bool(update_head),
            "cpu_seconds": time.process_time() - cpu_started, "wall_seconds": time.perf_counter() - started,
        }
        self.training_history.append(receipt)
        return receipt

    def raw_outputs(self, features):
        with torch.no_grad():
            return self(self._features(features)).numpy().copy()

    def predict_proba(self, features):
        raw = torch.from_numpy(self.raw_outputs(features))
        result, start = {}, 0
        for spec in self.config.outputs:
            value = raw[:, start : start + spec.size]
            if spec.kind == "binary":
                value = value.sigmoid()
            elif spec.kind == "multiclass":
                value = value.softmax(1)
            result[spec.name] = value.numpy().copy()
            start += spec.size
        return result

    def predict(self, features):
        result = self.predict_proba(features)
        for spec in self.config.outputs:
            if spec.kind == "binary":
                result[spec.name] = (result[spec.name] >= 0.5).astype(np.int64)
            elif spec.kind == "multiclass":
                result[spec.name] = result[spec.name].argmax(1)
        return result

    def parameter_counts(self):
        return {"adapter": self.A.numel() + self.B.numel(),
                "head": sum(p.numel() for p in self.head.parameters()),
                "total": sum(p.numel() for p in self.parameters()),
                "trainable": sum(p.numel() for p in self.parameters() if p.requires_grad)}

    def _arrays(self):
        return {name: value.detach().numpy().astype("<f4", copy=True)
                for name, value in self.state_dict().items()}

    def parameter_digest(self):
        hasher = hashlib.sha256()
        for name, array in sorted(self._arrays().items()):
            hasher.update(canonical([name, list(array.shape), "float32"]))
            hasher.update(array.tobytes())
        return hasher.hexdigest()

    def fork(self, cell_id):
        """Copy parent behavior, sharing only its now-frozen head."""
        self.freeze_head()
        child = TensorCell(replace(self.config, cell_id=cell_id), self.base_encoder_sha,
                           self.source_ids, head=self.head)
        child.load_state_dict(self.state_dict())
        child.parents = [{"cell_id": self.config.cell_id, "parameter_sha256": self.parameter_digest()}]
        return child

    def expand_rank(self, rank, cell_id):
        """Preserve behavior with zero new B columns and trainable random A rows."""
        if rank < self.config.rank:
            raise ValueError("rank expansion cannot remove existing channels")
        self.freeze_head()
        child = TensorCell(replace(self.config, cell_id=cell_id, rank=rank), self.base_encoder_sha,
                           self.source_ids, head=self.head)
        with torch.no_grad():
            child.A[: self.config.rank].copy_(self.A)
            child.B[:, : self.config.rank].copy_(self.B)
        child.parents = [{"cell_id": self.config.cell_id, "parameter_sha256": self.parameter_digest()}]
        return child

    def without_adapter(self, cell_id):
        """Ablate B @ A while retaining the identically trained, frozen task head."""
        control = self.fork(cell_id)
        with torch.no_grad():
            control.B.zero_()
        return control

    def save(self, directory):
        """Write a new checkpoint directory, with every blob at most 512000 bytes."""
        destination = Path(directory)
        if destination.exists():
            raise FileExistsError("checkpoint versions must not overwrite an existing directory")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".tensor-cell-", dir=destination.parent))
        try:
            manifest = {"schema": "memory-adapter.checkpoint.v1", "config": asdict(self.config),
                        "base_encoder_sha": self.base_encoder_sha, "base_operator": "identity",
                        "dtype": "float32", "parameter_sha256": self.parameter_digest(),
                        "head_frozen": self.head_frozen, "head_trainable": self.head.weight.requires_grad,
                        "source_ids": sorted(self.source_ids),
                        "parents": self.parents, "training_history": self.training_history, "tensors": {}}
            for name, array in self._arrays().items():
                parts = []
                flat = array.reshape(-1)
                for part, start in enumerate(range(0, len(flat), CHUNK_ELEMENTS)):
                    filename = f"{name}.{part:04d}.npz"
                    path = staging / filename
                    np.savez_compressed(path, values=flat[start : start + CHUNK_ELEMENTS])
                    raw = path.read_bytes()
                    if len(raw) > BLOB_CAP:
                        raise ValueError("tensor chunk exceeds checkpoint blob cap")
                    parts.append({"file": filename, "bytes": len(raw), "sha256": digest(raw)})
                manifest["tensors"][name] = {"shape": list(array.shape), "parts": parts}
            payload = canonical(manifest)
            if len(payload) > BLOB_CAP:
                raise ValueError("checkpoint manifest exceeds blob cap")
            (staging / "manifest.json").write_bytes(payload)
            stored_bytes = sum(p.stat().st_size for p in staging.iterdir())
            os.replace(staging, destination)
            return {"stored_bytes": stored_bytes, "manifest_sha256": digest(payload),
                    "parameter_sha256": manifest["parameter_sha256"]}
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    @classmethod
    def load(cls, directory, expected_encoder_sha=None, shared_head=None):
        root = Path(directory)
        payload = (root / "manifest.json").read_bytes()
        if len(payload) > BLOB_CAP:
            raise ValueError("oversized checkpoint manifest")
        manifest = json.loads(payload)
        if manifest["schema"] != "memory-adapter.checkpoint.v1" or manifest["dtype"] != "float32":
            raise ValueError("unsupported checkpoint format")
        if expected_encoder_sha is not None and manifest["base_encoder_sha"] != expected_encoder_sha:
            raise ValueError("checkpoint encoder identity mismatch")
        config = dict(manifest["config"])
        config["outputs"] = tuple(OutputSpec(**item) for item in config["outputs"])
        cell = cls(CellConfig(**config), manifest["base_encoder_sha"], manifest["source_ids"])
        if set(manifest["tensors"]) != set(cell.state_dict()):
            raise ValueError("checkpoint tensor set mismatch")
        arrays = {}
        for name, expected in cell.state_dict().items():
            entry = manifest["tensors"][name]
            if entry["shape"] != list(expected.shape):
                raise ValueError("checkpoint tensor shape mismatch")
            pieces = []
            for index, part in enumerate(entry["parts"]):
                if part["file"] != f"{name}.{index:04d}.npz":
                    raise ValueError("invalid tensor chunk name")
                path = root / part["file"]
                raw = path.read_bytes()
                if len(raw) > BLOB_CAP or len(raw) != part["bytes"] or digest(raw) != part["sha256"]:
                    raise ValueError("checkpoint chunk integrity failure")
                with zipfile.ZipFile(path) as archive:
                    if archive.namelist() != ["values.npy"] or archive.infolist()[0].file_size > 4 * CHUNK_ELEMENTS + 4096:
                        raise ValueError("invalid tensor chunk archive")
                with np.load(path, allow_pickle=False) as archive:
                    chunk = archive["values"]
                    if chunk.ndim != 1 or chunk.dtype != np.dtype("float32") or len(chunk) > CHUNK_ELEMENTS:
                        raise ValueError("invalid float32 tensor chunk")
                    pieces.append(chunk.copy())
            flat = np.concatenate(pieces)
            if flat.size != expected.numel() or not np.isfinite(flat).all():
                raise ValueError("invalid reconstructed tensor")
            arrays[name] = torch.from_numpy(flat.reshape(expected.shape))
        cell.load_state_dict(arrays)
        if cell.parameter_digest() != manifest["parameter_sha256"]:
            raise ValueError("checkpoint parameter digest mismatch")
        cell.parents = manifest["parents"]
        cell.training_history = manifest["training_history"]
        cell.head.requires_grad_(manifest["head_trainable"])
        if manifest["head_frozen"]:
            cell.freeze_head()
        if shared_head is not None:
            if any(not torch.equal(a, b) for a, b in zip(cell.head.parameters(), shared_head.parameters(), strict=True)):
                raise ValueError("shared head differs from the persisted checkpoint")
            cell.head = shared_head
            cell._shared_head = True
            cell.freeze_head()
        return cell


def unique_parameter_count(cells):
    """Count shared task-head objects once, while retaining every private adapter."""
    parameters = {id(p): p for cell in cells for p in cell.parameters()}
    return {"total": sum(p.numel() for p in parameters.values()),
            "trainable": sum(p.numel() for p in parameters.values() if p.requires_grad)}
