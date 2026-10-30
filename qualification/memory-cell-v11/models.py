"""Trainable V11 memory operators; internal adapters are inside the Transformer.

Feature models consume frozen features. TransformerAdapter consumes tokenized
text and trains LoRA matrices in attention query/value projections. Its head is
also trainable, so adapter influence must be evaluated by intervention rather
than inferred from overall accuracy. No reader receives a gold address.
"""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F


def verify_base(encoder_dir, expected=None):
    """Authenticate all local model/tokenizer assets against the frozen manifest."""
    root = Path(encoder_dir).resolve()
    payload = (root / "MODEL_IDENTITY.json").read_bytes()
    identity = hashlib.sha256(payload).hexdigest()
    if expected is not None and expected != identity:
        raise ValueError("base identity differs from checkpoint")
    manifest = json.loads(payload)
    if manifest.get("schema") != "hepta.memory.v11.base-model.v1":
        raise ValueError("unsupported base identity manifest")
    listed = set()
    for entry in manifest["files"]:
        name = entry["path"]
        path = root / name
        if name in listed or path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("invalid base asset path")
        data = path.read_bytes()
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError("base asset identity mismatch: " + name)
        listed.add(name)
    assets = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()
              and p.suffix in (".json", ".safetensors", ".bin", ".txt", ".model")
              and p.name != "MODEL_IDENTITY.json" and not any(c.startswith(".") for c in p.relative_to(root).parts)}
    if assets - listed or "config.json" not in listed:
        raise ValueError("base manifest omits an executable model/tokenizer asset")
    return identity


def digest_state(state):
    digest = hashlib.sha256()
    for name, value in sorted(state.items()):
        array = value.detach().cpu().contiguous().numpy()
        digest.update(name.encode() + str(array.shape).encode() + array.tobytes())
    return digest.hexdigest()


class FeatureMemory(nn.Module):
    """Affine, nonlinear, or trainable soft associative memory on the same input."""

    input_kind = "features"

    def __init__(self, kind, dimension, width, *, seed=0, hidden=128, slots=32):
        super().__init__()
        if kind not in ("linear", "mlp", "associative"):
            raise ValueError("unknown feature memory")
        self.spec = dict(kind=kind, dimension=dimension, width=width, seed=seed,
                         hidden=hidden, slots=slots)
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            if kind == "linear":
                self.operator = nn.Linear(dimension, width)
            elif kind == "mlp":
                self.operator = nn.Sequential(nn.Linear(dimension, hidden), nn.GELU(),
                                              nn.Linear(hidden, width))
            else:
                self.keys = nn.Parameter(torch.randn(slots, dimension) / dimension ** .5)
                self.values = nn.Parameter(torch.randn(slots, width) * .02)
                self.log_scale = nn.Parameter(torch.tensor(2.0))
                self.bias = nn.Parameter(torch.zeros(width))

    def prepare(self, data):
        return torch.as_tensor(np.asarray(data), dtype=torch.float32)

    def forward(self, x):
        if self.spec["kind"] != "associative":
            return self.operator(x)
        similarity = F.normalize(x, dim=-1) @ F.normalize(self.keys, dim=-1).T
        weights = torch.softmax(similarity * self.log_scale.exp().clamp(max=100), dim=-1)
        return weights @ self.values + self.bias


class LoRALinear(nn.Module):
    def __init__(self, base, rank):
        super().__init__()
        self.base, self.rank, self.enabled = base, rank, True
        self.base.requires_grad_(False)
        self.A = nn.Parameter(torch.randn(rank, base.in_features) * .02)
        self.B = nn.Parameter(torch.zeros(base.out_features, rank))

    def forward(self, x):
        result = self.base(x)
        return result + F.linear(F.linear(x, self.A), self.B) if self.enabled else result


class TransformerAdapter(nn.Module):
    """A pinned local encoder with genuine attention-internal low-rank updates."""

    input_kind = "text"

    def __init__(self, encoder_dir, width, *, rank=4, seed=0, max_tokens=128,
                 base_identity=None, encoder=None, tokenizer=None):
        super().__init__()
        if rank < 1:
            raise ValueError("adapter rank must be positive")
        if encoder is None:
            base_identity = verify_base(encoder_dir, base_identity)
            from transformers import AutoModel, AutoTokenizer
            encoder = AutoModel.from_pretrained(str(encoder_dir), local_files_only=True,
                                                trust_remote_code=False)
            tokenizer = AutoTokenizer.from_pretrained(str(encoder_dir), local_files_only=True,
                                                       trust_remote_code=False)
        self.encoder, self.tokenizer = encoder, tokenizer
        self.encoder.requires_grad_(False)
        targets = [(name, module) for name, module in self.encoder.named_modules()
                   if name.rsplit(".", 1)[-1] in ("query", "value", "q_lin", "v_lin")
                   and isinstance(module, nn.Linear)]
        if not targets:
            raise ValueError("no supported attention query/value projections found")
        with torch.random.fork_rng():
            torch.manual_seed(seed)
            for name, module in targets:
                parent_name, _, attr = name.rpartition(".")
                parent = self.encoder.get_submodule(parent_name) if parent_name else self.encoder
                setattr(parent, attr, LoRALinear(module, rank))
            self.head = nn.Linear(self.encoder.config.hidden_size, width)
        self.spec = dict(kind="transformer_adapter", dimension=self.encoder.config.hidden_size,
                         width=width, rank=rank, seed=seed, max_tokens=max_tokens,
                         encoder_dir=str(encoder_dir), base_identity=base_identity,
                         adapted_modules=[name for name, _ in targets])
        self.encoder.eval()  # deterministic frozen dropout; gradients remain enabled

    def train(self, mode=True):
        super().train(mode)
        self.encoder.eval()
        return self

    def prepare(self, data):
        if isinstance(data, dict):
            return {k: torch.as_tensor(v) for k, v in data.items()}
        if self.tokenizer is None:
            raise ValueError("text input requires the pinned tokenizer")
        return dict(self.tokenizer(list(data), padding=True, truncation=True,
                                   max_length=self.spec["max_tokens"], return_tensors="pt"))

    def forward(self, x):
        hidden = self.encoder(**x).last_hidden_state
        mask = x["attention_mask"].unsqueeze(-1).to(hidden.dtype)
        pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp_min(1)
        return self.head(F.normalize(pooled, dim=-1))

    @contextmanager
    def disabled_adapters(self):
        modules = [m for m in self.modules() if isinstance(m, LoRALinear)]
        previous = [m.enabled for m in modules]
        try:
            for module in modules:
                module.enabled = False
            yield
        finally:
            for module, enabled in zip(modules, previous, strict=True):
                module.enabled = enabled


def grouped_loss(raw, target, outputs):
    losses, start = [], 0
    for kind, width in outputs:
        values, labels = raw[:, start:start + width], target[:, start:start + width]
        if kind == "binary":
            losses.append(F.binary_cross_entropy_with_logits(values, labels))
        elif kind == "multiclass":
            losses.append(-(labels * F.log_softmax(values, dim=-1)).sum(dim=-1).mean())
        else:
            raise ValueError("unsupported output contract")
        start += width
    if start != raw.shape[1] or raw.shape != target.shape or not losses:
        raise ValueError("target/output dimensions differ")
    return torch.stack(losses).mean()


def _slice(inputs, rows):
    return {k: v[rows] for k, v in inputs.items()} if isinstance(inputs, dict) else inputs[rows]


def predict(model, data, *, batch_size=32):
    model.eval()
    inputs = model.prepare(data)
    count = len(next(iter(inputs.values()))) if isinstance(inputs, dict) else len(inputs)
    with torch.no_grad():
        result = [model(_slice(inputs, slice(i, i + batch_size))).cpu().numpy()
                  for i in range(0, count, batch_size)]
    return np.concatenate(result) if result else np.empty((0, model.spec["width"]), np.float32)


def fit(model, data, targets, outputs, schedule, *, lr=.01, source_ids=None,
        label="fit", optimizer=None, deadline=None):
    """Fit only declared rows; the caller owns training/calibration/test isolation.

    A reusable optimizer may be supplied for persistent online updates. Otherwise
    Adam moments reset, explicitly recorded. No held data or stopping rule is read.
    The optional perf_counter deadline is checked between minibatches; it cannot
    interrupt a single running tensor operation and is not a hard realtime bound.
    """
    start, cpu = time.perf_counter(), time.process_time()
    inputs, y = model.prepare(data), torch.as_tensor(np.asarray(targets), dtype=torch.float32)
    schedule = np.asarray(schedule, dtype=np.int64)
    count = len(next(iter(inputs.values()))) if isinstance(inputs, dict) else len(inputs)
    if schedule.ndim != 2 or not schedule.size or schedule.min() < 0 or schedule.max() >= count:
        raise ValueError("invalid declared row schedule")
    if len(y) != count or (source_ids is not None and len(source_ids) != count):
        raise ValueError("source/target/input lengths differ")
    params = {k: v for k, v in model.named_parameters() if v.requires_grad}
    initial = {k: v.detach().clone() for k, v in params.items()}
    before = digest_state(initial)
    created_optimizer = optimizer is None
    optimizer = optimizer or torch.optim.Adam(params.values(), lr=lr)
    norms = {k: 0.0 for k in params}
    first_loss, last_loss, trace = None, None, []
    model.train()
    for step, rows in enumerate(schedule):
        if deadline is not None and time.perf_counter() >= deadline:
            raise TimeoutError("training deadline reached before next minibatch")
        optimizer.zero_grad(set_to_none=True)
        loss = grouped_loss(model(_slice(inputs, rows)), y[rows], outputs)
        if not torch.isfinite(loss):
            raise FloatingPointError("nonfinite training loss")
        loss.backward()
        for name, value in params.items():
            if value.grad is not None:
                if not torch.isfinite(value.grad).all():
                    raise FloatingPointError("nonfinite gradient")
                norms[name] = max(norms[name], float(value.grad.norm()))
        optimizer.step()
        last_loss = float(loss.detach())
        first_loss = last_loss if first_loss is None else first_loss
        if step == 0 or (step + 1) % 100 == 0 or step + 1 == len(schedule):
            trace.append({"step": step + 1, "minibatch_loss": last_loss})
    changes = {k: float((v.detach() - initial[k]).norm()) for k, v in params.items()}
    return dict(schema="hepta.memory.v11.torch-fit.v1", label=label, spec=model.spec,
                steps=len(schedule), batch_size=schedule.shape[1], sample_presentations=int(schedule.size),
                initial_parameter_sha256=before, final_parameter_sha256=digest_state(params),
                trainable_parameters=sum(v.numel() for v in params.values()),
                total_parameters=sum(v.numel() for v in model.parameters()),
                max_gradient_norm=norms, parameter_change_norm=changes, trace=trace,
                initial_minibatch_loss=first_loss, final_minibatch_loss=last_loss,
                optimizer="torch Adam", optimizer_moments_reset=created_optimizer, learning_rate=lr,
                schedule_sha256=hashlib.sha256(schedule.astype("<i8").tobytes()).hexdigest(),
                source_ids=sorted(set(source_ids or [])),
                cpu_seconds=time.process_time() - cpu, wall_seconds=time.perf_counter() - start)


def save(model, destination, *, metadata=None):
    """Store mutable weights, not a second copy of the frozen backbone."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    trainable = {k: p.detach().cpu() for k, p in model.named_parameters() if p.requires_grad}
    torch.save(trainable, destination / "weights.pt")
    payload = (destination / "weights.pt").read_bytes()
    manifest = dict(schema="hepta.memory.v11.torch-checkpoint.v1", spec=model.spec,
                    trainable_parameter_sha256=digest_state(trainable),
                    weights_sha256=hashlib.sha256(payload).hexdigest(),
                    mutable_weight_bytes=len(payload), metadata=metadata or {})
    (destination / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return manifest


def load(destination, *, encoder_dir=None):
    destination = Path(destination)
    manifest = json.loads((destination / "manifest.json").read_text())
    if manifest.get("schema") != "hepta.memory.v11.torch-checkpoint.v1":
        raise ValueError("unsupported checkpoint")
    payload = (destination / "weights.pt").read_bytes()
    if hashlib.sha256(payload).hexdigest() != manifest["weights_sha256"]:
        raise ValueError("checkpoint byte corruption")
    spec = manifest["spec"]
    if spec["kind"] == "transformer_adapter":
        model = TransformerAdapter(encoder_dir or spec["encoder_dir"], spec["width"],
                                   rank=spec["rank"], seed=spec["seed"], max_tokens=spec["max_tokens"],
                                   base_identity=spec.get("base_identity"))
        if model.spec["adapted_modules"] != spec["adapted_modules"]:
            raise ValueError("adapter locations differ from checkpoint")
    else:
        model = FeatureMemory(**spec)
    state = torch.load(destination / "weights.pt", map_location="cpu", weights_only=True)
    expected = {k for k, p in model.named_parameters() if p.requires_grad}
    if set(state) != expected or digest_state(state) != manifest["trainable_parameter_sha256"]:
        raise ValueError("mutable parameter contract differs")
    model.load_state_dict(state, strict=False)
    return model
