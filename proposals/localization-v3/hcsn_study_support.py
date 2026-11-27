"""Source identity, padded batches and weighted effective-batch gradients.

A unique module name avoids the official S4 repository's top-level train.py.
"""

import inspect
from pathlib import Path
import time

import torch
from cores import ROOT
from data import sha


def sources(model=None):
    paths = set()
    for directory in (
        ROOT / "proposals/localization-v2",
        Path(__file__).parent,
        ROOT / "qualification/hcsn_differentiable",
    ):
        paths.update(p.resolve() for p in directory.glob("*.py"))
    if model is not None:
        for module in model.modules():
            try:
                path = inspect.getsourcefile(type(module))
            except TypeError:
                path = None
            if path:
                paths.add(Path(path).resolve())
        paths.update(Path(p).resolve() for p in getattr(model, "official_sources", []))
    return {str(p): sha(p.read_bytes()) for p in sorted(paths)}


def batches(rows, indices, batch_size):
    for start in range(0, len(indices), batch_size):
        selected = [rows[i] for i in indices[start : start + batch_size]]
        length = max(len(row["y"]) for row in selected)
        x = torch.zeros(len(selected), length, 25, dtype=torch.float64)
        dt = torch.zeros(len(selected), length, dtype=torch.float64)
        y = torch.full((len(selected), length), -1, dtype=torch.long)
        for i, row in enumerate(selected):
            n = len(row["y"])
            x[i, :n] = torch.as_tensor(row["x"], dtype=torch.float64)
            dt[i, :n] = torch.as_tensor(row["dt"], dtype=torch.float64)
            y[i, :n] = torch.as_tensor(row["y"], dtype=torch.long)
        yield [r["id"] for r in selected], x, dt, y


def backward_effective_batch(
    model, x, dt, y, weights, *, micro_batch_size=None, before_forward=None
):
    """Whole-batch weighted CE gradient, with complete-window microbatches.

    Every slice retains the original padded time length. The denominator is
    the sum of target class weights over the entire effective batch. Callers
    zero gradients before this function and clip/step only once afterwards.
    """
    count = x.shape[0]
    size = count if micro_batch_size is None else micro_batch_size
    if type(size) is not int or size < 1:
        raise ValueError("micro_batch_size must be a positive integer")
    valid = y >= 0
    if not bool(valid.any()):
        raise ValueError("effective batch contains no labelled events")
    denominator = weights[y[valid]].sum()
    total, calls, forward_seconds, backward_seconds = 0.0, 0, 0.0, 0.0
    diagnostics = {}
    for start in range(0, count, size):
        end = min(start + size, count)
        if before_forward:
            before_forward(start, end)
        started = time.perf_counter()
        logits = model(x[start:end], dt[start:end])
        forward_seconds += time.perf_counter() - started
        selected = valid[start:end]
        numerator = torch.nn.functional.cross_entropy(
            logits[selected], y[start:end][selected], weight=weights, reduction="sum"
        )
        loss = numerator / denominator
        if not bool(torch.isfinite(loss)):
            raise FloatingPointError("nonfinite microbatch loss")
        started = time.perf_counter()
        loss.backward()
        backward_seconds += time.perf_counter() - started
        total += float(loss.detach())
        calls += 1
        diagnostics = getattr(model.core, "diagnostics", {})
    return {
        "loss": total,
        "events": int(valid.sum()),
        "micro_forward_calls": calls,
        "forward_seconds": forward_seconds,
        "backward_seconds": backward_seconds,
        "last_microbatch_diagnostics": diagnostics,
    }
