"""Bounded candidate-only Cell operators; no runtime, store or selection authority.

The Encoder never belongs to this module. Candidate copies are next-generation
research tensors, not live neuron.runtime checkpoints or signed artifacts.
"""

from copy import deepcopy
import hashlib
import math
import time

import torch
from torch import nn
from torch.nn import functional as F


MAX_ELEMENTS = 4_194_304


def checked_tensor(x, ndim, name):
    if (not isinstance(x, torch.Tensor) or x.ndim != ndim
            or x.device.type != "cpu" or x.dtype not in (torch.float32, torch.float64)
            or not 0 < x.numel() <= MAX_ELEMENTS or not torch.isfinite(x).all()):
        raise ValueError(f"invalid bounded CPU tensor: {name}")
    return x


def parameter_digest(module):
    """Content identity only; NOT a signed load or execution receipt."""
    h = hashlib.sha256(b"hepta.stem.development.tensors.v1")
    for name, value in sorted(module.state_dict().items()):
        value = value.detach().cpu().contiguous()
        descriptor = f"{name}:{value.dtype}:{tuple(value.shape)}".encode()
        h.update(len(descriptor).to_bytes(8, "big"))
        h.update(descriptor)
        h.update(value.numpy().tobytes())
    return h.hexdigest()


class BasisCellHeads(nn.Module):
    """One frozen organ basis, 2*rank+1 trainable numbers per Cell.

    logits = base(x) + sigmoid(gate(x)) * sum_r coefficient[r] * x @ basis[r].
    All persistent Cell state and all promotion decisions remain external.
    """

    def __init__(self, width, classes, rank, cell_ids, *, generation=1, seed=7347):
        super().__init__()
        if (any(type(v) is not int for v in (width, classes, rank, generation, seed))
                or not 1 <= width <= 512 or not 2 <= classes <= 128
                or not 1 <= rank <= 64 or generation < 1
                or width * classes * rank > MAX_ELEMENTS):
            raise ValueError("unsupported head dimensions/generation")
        if not isinstance(cell_ids, (tuple, list)):
            raise ValueError("invalid Cell identity sequence")
        ids = tuple(cell_ids)
        if (not 1 <= len(ids) <= 4096
                or any(type(i) is not str or not 0 < len(i) <= 128 for i in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError("invalid Cell identities")
        self.width, self.classes, self.rank = width, classes, rank
        self.cell_ids, self.generation = ids, generation
        self.awake = tuple(True for _ in ids)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            self.base = nn.Linear(width, classes).requires_grad_(False)
            self.basis = nn.Parameter(torch.randn(rank, width, classes) / math.sqrt(width), requires_grad=False)
            self.register_buffer("gate_axes", torch.randn(rank, width) / math.sqrt(width))
        self.coefficients = nn.Parameter(torch.zeros(len(ids), rank))
        self.gates = nn.Parameter(torch.zeros(len(ids), rank + 1))

    def forward(self, x, indices):
        checked_tensor(x, 2, "features")
        if (x.shape[1] != self.width or x.dtype != self.base.weight.dtype
                or not isinstance(indices, torch.Tensor) or indices.dtype != torch.long
                or indices.device.type != "cpu" or indices.shape != (len(x),)
                or bool(((indices < 0) | (indices >= len(self.cell_ids))).any())):
            raise ValueError("invalid Cell batch")
        if any(not self.awake[i] for i in indices.tolist()):
            raise ValueError("dormant Cell cannot execute")
        gates = self.gates[indices]
        activation = torch.sigmoid((x @ self.gate_axes.T * gates[:, :-1]).sum(1) + gates[:, -1])
        residual = torch.einsum("bd,rdk,br->bk", x, self.basis, self.coefficients[indices])
        return self.base(x) + activation[:, None] * residual

    def parameter_counts(self):
        return {"shared": self.base.weight.numel() + self.base.bias.numel()
                + self.basis.numel() + self.gate_axes.numel(),
                "cell_local": self.coefficients.numel() + self.gates.numel(),
                "encoder_copies": 0}


def split_candidate(bank, parent, child, *, maximum_local_parameters):
    """Function-preserving birth; clone only a small bank, never an Encoder."""
    if (parent not in bank.cell_ids or child in bank.cell_ids or type(child) is not str
            or not 0 < len(child) <= 128 or len(bank.cell_ids) >= 4096
            or type(maximum_local_parameters) is not int):
        raise ValueError("invalid split")
    count = (len(bank.cell_ids) + 1) * (2 * bank.rank + 1)
    if count > maximum_local_parameters:
        raise ValueError("split exceeds physical local-parameter budget")
    i = bank.cell_ids.index(parent)
    if not bank.awake[i]:
        raise ValueError("cannot split dormant Cell")
    out = deepcopy(bank)
    out.coefficients = nn.Parameter(torch.cat((bank.coefficients.detach(), bank.coefficients[i:i+1].detach())).clone())
    out.gates = nn.Parameter(torch.cat((bank.gates.detach(), bank.gates[i:i+1].detach())).clone())
    out.cell_ids += (child,)
    out.awake += (True,)
    out.generation += 1
    return out


def merge_identical_candidate(bank, removed, retained):
    """Exact merge only; nonidentical specialists require distillation first."""
    if removed == retained or removed not in bank.cell_ids or retained not in bank.cell_ids:
        raise ValueError("invalid merge identities")
    a, b = bank.cell_ids.index(removed), bank.cell_ids.index(retained)
    if (not bank.awake[b] or not torch.equal(bank.coefficients[a], bank.coefficients[b])
            or not torch.equal(bank.gates[a], bank.gates[b])):
        raise ValueError("nonidentical merge requires separate distillation/evaluation")
    keep = [i for i in range(len(bank.cell_ids)) if i != a]
    out = deepcopy(bank)
    out.coefficients = nn.Parameter(bank.coefficients.detach()[keep].clone())
    out.gates = nn.Parameter(bank.gates.detach()[keep].clone())
    out.cell_ids = tuple(bank.cell_ids[i] for i in keep)
    out.awake = tuple(bank.awake[i] for i in keep)
    out.generation += 1
    return out


def dormancy_candidate(bank, cell, *, awake):
    if cell not in bank.cell_ids or type(awake) is not bool:
        raise ValueError("invalid dormancy change")
    out = deepcopy(bank)
    out.awake = tuple(awake if i == cell else old for i, old in zip(bank.cell_ids, bank.awake))
    out.generation += 1
    return out


def fit_cell_candidate(bank, cell, x, labels, *, fit, steps, seed):
    """Delegate supervised fitting to existing model_runner.train_head.

    Isolate one Cell's parameters, including optimizer weight decay. Merely
    zeroing other rows' gradients would still allow AdamW to change them.
    """
    checked_tensor(x, 2, "training features")
    if (cell not in bank.cell_ids or type(steps) is not int or not 1 <= steps <= 1000
            or type(seed) is not int or not isinstance(labels, torch.Tensor)
            or labels.dtype != torch.long or labels.device.type != "cpu"
            or labels.shape != (len(x),) or x.shape[1] != bank.width
            or x.dtype != bank.base.weight.dtype
            or bool(((labels < 0) | (labels >= bank.classes)).any())):
        raise ValueError("invalid bounded Cell training")
    index = bank.cell_ids.index(cell)
    if not bank.awake[index]:
        raise ValueError("cannot train dormant Cell")
    out = deepcopy(bank).requires_grad_(False)

    class LocalHead(nn.Module):
        def __init__(self):
            super().__init__()
            self.coefficient = nn.Parameter(bank.coefficients[index].detach().clone())
            self.gate = nn.Parameter(bank.gates[index].detach().clone())

        def forward(self, features):
            activation = torch.sigmoid((features @ out.gate_axes.T * self.gate[:-1]).sum(1) + self.gate[-1])
            residual = torch.einsum("bd,rdk,r->bk", features, out.basis, self.coefficient)
            return out.base(features) + activation[:, None] * residual

    head = LocalHead()
    start = time.process_time_ns()
    fit(torch, head, x.detach().clone(), labels.clone(), steps=steps, seed=seed)
    elapsed = time.process_time_ns() - start
    if any(not torch.isfinite(p).all() for p in head.parameters()):
        raise ValueError("nonfinite learned candidate")
    with torch.no_grad():
        out.coefficients[index].copy_(head.coefficient)
        out.gates[index].copy_(head.gate)
    out.generation += 1
    return out, {"training_cpu_ns": elapsed, "steps": steps,
                 "trainable_parameters": sum(p.numel() for p in head.parameters()),
                 "production_authorized": False}


def distill_shared_candidate(bank, x, indices, teacher_logits, *, steps=100, temperature=2.0):
    """Fit common basis/readout to sealed teachers; do not select the result.

    Caller must supply train/replay folds only. Held-out retention, teacher
    preparation costs and independent future evidence are separate requirements.
    """
    checked_tensor(teacher_logits, 2, "teacher logits")
    if (type(steps) is not int or not 1 <= steps <= 1000
            or type(temperature) not in (int, float) or not math.isfinite(temperature)
            or not 0.1 <= temperature <= 10):
        raise ValueError("invalid distillation budget")
    with torch.no_grad():
        expected = bank(x, indices)
    if teacher_logits.shape != expected.shape or teacher_logits.dtype != x.dtype:
        raise ValueError("teacher shape/dtype mismatch")
    teacher = torch.softmax(teacher_logits.detach().clone() / temperature, dim=-1)
    out = deepcopy(bank).requires_grad_(False)
    out.base.requires_grad_(True)
    out.basis.requires_grad_(True)
    optimizer = torch.optim.AdamW([p for p in out.parameters() if p.requires_grad], lr=0.01, weight_decay=0)
    start = time.process_time_ns()
    for _ in range(steps):
        loss = F.kl_div(F.log_softmax(out(x.detach(), indices) / temperature, dim=-1),
                        teacher, reduction="batchmean") * temperature**2
        if not torch.isfinite(loss):
            raise ValueError("nonfinite distillation")
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        nn.utils.clip_grad_norm_([p for p in out.parameters() if p.requires_grad], 1.0)
        optimizer.step()
    out.requires_grad_(False)
    out.generation += 1
    if any(not torch.isfinite(v).all() for v in out.state_dict().values()):
        raise ValueError("nonfinite distilled parameters")
    return out, {"distillation_cpu_ns": time.process_time_ns() - start,
                 "steps": steps, "production_authorized": False}
