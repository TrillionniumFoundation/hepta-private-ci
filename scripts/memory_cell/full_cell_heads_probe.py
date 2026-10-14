"""Hermetic PyTorch probe for the full Cell-head comparison.

The probe trains only a small head on immutable ``Features`` rows.  It is a
mechanism smoke test, not a reader or capability benchmark: source-support
labels are accepted as weak supervision and all reported efficacy fields are
kept local to the supplied tensor fixture.

``LowRankOutputAdapter`` is deliberately an output adapter.  It applies a
low-rank residual to the encoder output and never updates or wraps a layer's
base weight; it must not be described as layer-internal LoRA.
"""

import hashlib
import json
import math
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, Sequence

try:
    import torch
    from torch import nn
except ImportError:  # pragma: no cover - CI installs pinned torch
    torch = None

    class _MissingNN:
        Module = object

    nn = _MissingNN()


HEAD_KINDS = ("linear", "gated", "low_rank_output_adapter", "top1_sparse_expert")


def _require_torch() -> None:
    if torch is None:
        raise RuntimeError("full_cell_heads_probe requires PyTorch")


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def source_digest(rows: Sequence[Any]) -> str:
    """Digest feature identity and values without claiming semantic authority."""
    _require_torch()
    h = hashlib.sha256()
    for row in rows:
        f = row.features
        h.update(str(getattr(f, "question_id", "")).encode())
        h.update(str(getattr(f, "family", "")).encode())
        h.update(str(getattr(f, "encoder_identity", "")).encode())
        h.update(str(getattr(f, "pool_digest", "")).encode())
        h.update(repr(tuple(getattr(f, "candidate_ids", ()))).encode())
        h.update(repr(tuple(sorted(getattr(f, "roots", ())))).encode())
        for tensor in (f.paired, f.frozen_scores):
            # Torch bfloat16 and numpy-less CPU builds must retain EXACT tensor bytes.
            # Hash dtype and shape as well, so identical payload bytes in different
            # representations cannot silently share a feature identity.
            contiguous = tensor.detach().cpu().contiguous()
            descriptor = json.dumps(
                {"dtype": str(contiguous.dtype), "shape": list(contiguous.shape)},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            raw = bytes(contiguous.view(torch.uint8).reshape(-1).tolist())
            h.update(len(descriptor).to_bytes(4, "big"))
            h.update(descriptor)
            h.update(len(raw).to_bytes(8, "big"))
            h.update(raw)
        h.update(repr(tuple(getattr(row, "positive_indices", ()))).encode())
    return h.hexdigest()


def _validate_rows(
    rows: Sequence[Any], cut: Any, dimension: int, encoder_identity: str
) -> None:
    if not rows or len(rows) > 256:
        raise ValueError("bounded admitted rows required")
    seen: set[str] = set()
    revoked = set(getattr(cut, "forbidden_roots", ()))
    for row in rows:
        f = row.features
        if hasattr(f, "validate"):
            f.validate(dimension)
        n = len(f.candidate_ids)
        if (
            f.encoder_identity != encoder_identity
            or f.question_id in seen
            or f.question_id not in cut.question_ids
            or f.family not in cut.families
            or not set(f.roots).issubset(set(cut.allowed_roots))
            or set(f.roots).intersection(revoked)
            or f.paired.shape != (n, dimension)
            or f.frozen_scores.shape != (n,)
            or f.paired.requires_grad
            or f.frozen_scores.requires_grad
            or not torch.isfinite(f.paired).all()
            or not torch.isfinite(f.frozen_scores).all()
        ):
            raise ValueError("invalid, held-out, withdrawn or incompatible feature row")
        positives = tuple(row.positive_indices)
        if len(set(positives)) != len(positives) or any(
            type(i) is not int or not 0 <= i < n for i in positives
        ):
            raise ValueError("invalid support indices")
        seen.add(f.question_id)
    if not getattr(cut, "admission_digest", ""):
        raise ValueError("training cut admission digest required")


class _Head(nn.Module):
    kind = ""

    def __init__(self, dimension: int) -> None:
        super().__init__()
        if type(dimension) is not int or not 1 <= dimension <= 4096:
            raise ValueError("bounded feature dimension required")
        self.dimension = dimension

    def residual(self, x: "torch.Tensor") -> "torch.Tensor":
        raise NotImplementedError

    def scores(self, features: Any) -> "torch.Tensor":
        x = features.paired
        residual = self.residual(x) if len(x) else x.new_zeros((0,))
        null = x.mean(0) if len(x) else x.new_zeros((self.dimension,))
        null_score = self.null_residual(null).reshape(1)
        return torch.cat((features.frozen_scores + residual, null_score))


class LinearHead(_Head):
    kind = "linear"

    def __init__(self, dimension: int) -> None:
        super().__init__(dimension)
        self.output = nn.Linear(dimension, 1)
        self.null_residual = nn.Linear(dimension, 1)

    def residual(self, x: "torch.Tensor") -> "torch.Tensor":
        return self.output(x).flatten()


class GatedHead(_Head):
    kind = "gated"

    def __init__(self, dimension: int, rank: int = 16) -> None:
        super().__init__(dimension)
        if type(rank) is not int or not 1 <= rank <= dimension:
            raise ValueError("bounded gate rank required")
        self.down = nn.Linear(dimension, rank, bias=False)
        self.up = nn.Linear(rank, dimension, bias=False)
        self.gate = nn.Linear(dimension, dimension)
        self.output = nn.Linear(dimension, 1)
        self.null_residual = nn.Linear(dimension, 1)

    def residual(self, x: "torch.Tensor") -> "torch.Tensor":
        transformed = self.up(torch.tanh(self.down(x)))
        return self.output(x + torch.sigmoid(self.gate(x)) * transformed).flatten()


class LowRankOutputAdapter(_Head):
    """Low-rank output residual; no base Transformer layer is modified."""

    kind = "low_rank_output_adapter"

    def __init__(self, dimension: int, rank: int = 16) -> None:
        super().__init__(dimension)
        if type(rank) is not int or not 1 <= rank <= dimension:
            raise ValueError("bounded output-adapter rank required")
        self.down = nn.Linear(dimension, rank, bias=False)
        self.up = nn.Linear(rank, dimension, bias=False)
        self.output = nn.Linear(dimension, 1)
        self.null_residual = nn.Linear(dimension, 1)

    def residual(self, x: "torch.Tensor") -> "torch.Tensor":
        return self.output(x + self.up(torch.tanh(self.down(x)))).flatten()


class Top1SparseExpert(_Head):
    kind = "top1_sparse_expert"

    def __init__(self, dimension: int, experts: int = 2, hidden: int = 16) -> None:
        super().__init__(dimension)
        if (
            type(experts) is not int
            or not 2 <= experts <= 8
            or type(hidden) is not int
            or not 1 <= hidden <= 256
        ):
            raise ValueError("bounded sparse expert shape required")
        self.experts = nn.ModuleList(
            nn.Sequential(nn.Linear(dimension, hidden), nn.GELU(), nn.Linear(hidden, 1))
            for _ in range(experts)
        )
        self.router = nn.Linear(dimension, experts)
        self.null_residual = nn.Linear(dimension, 1)

    def residual(self, x: "torch.Tensor") -> "torch.Tensor":
        route = self.router(x).argmax(dim=-1)
        # Evaluate only the selected expert for each token.  Computing every
        # expert and gathering afterward would report dense, not top-1 sparse,
        # active FLOPs.
        output = x.new_zeros((len(x),))
        for index, expert in enumerate(self.experts):
            selected = route == index
            if selected.any():
                output[selected] = expert(x[selected]).flatten()
        return output


def make_head(kind: str, dimension: int, *, rank: int = 16) -> _Head:
    _require_torch()
    if kind == "linear":
        return LinearHead(dimension)
    if kind == "gated":
        return GatedHead(dimension, rank)
    if kind == "low_rank_output_adapter":
        return LowRankOutputAdapter(dimension, rank)
    if kind == "top1_sparse_expert":
        return Top1SparseExpert(dimension)
    raise ValueError(f"unknown head kind: {kind}")


def actual_param_counts(head: "nn.Module") -> dict[str, int]:
    total = sum(p.numel() for p in head.parameters())
    trainable = sum(p.numel() for p in head.parameters() if p.requires_grad)
    return {"total": total, "trainable": trainable, "frozen": total - trainable}


def _loss(
    head: _Head, row: Any, positives: tuple[int, ...] | None = None
) -> "torch.Tensor":
    logits = head.scores(row.features)
    positives = tuple(row.positive_indices) if positives is None else positives
    selected = list(positives) or [len(logits) - 1]
    return torch.logsumexp(logits, 0) - torch.logsumexp(logits[selected], 0)


def train_head(
    head: _Head,
    rows: Sequence[Any],
    cut: Any,
    *,
    steps: int = 32,
    lr: float = 0.03,
    shuffle_labels: bool = False,
    seed: int = 1837,
) -> dict[str, Any]:
    """Train only head parameters after validating every row."""
    _require_torch()
    _validate_rows(
        rows,
        cut,
        head.dimension,
        getattr(cut, "encoder_identity", "") or rows[0].features.encoder_identity,
    )
    if (
        type(steps) is not int
        or not 1 <= steps <= 2048
        or not math.isfinite(lr)
        or not 0 < lr <= 1
    ):
        raise ValueError("bounded finite training budget required")
    for p in head.parameters():
        p.requires_grad_(True)
    before_ids = {id(p) for p in head.parameters()}
    generator = torch.Generator().manual_seed(seed)
    optimizer = torch.optim.SGD(head.parameters(), lr=lr)
    losses: list[float] = []
    for step in range(steps):
        row = rows[step % len(rows)]
        positives = tuple(row.positive_indices)
        if shuffle_labels:
            positives = tuple(
                torch.randperm(len(row.features.candidate_ids), generator=generator)[
                    : len(positives)
                ].tolist()
            )
        optimizer.zero_grad(set_to_none=True)
        loss = _loss(head, row, positives)
        if not torch.isfinite(loss):
            raise ValueError("nonfinite head loss")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(
            list(head.parameters()), 1.0, error_if_nonfinite=True
        )
        optimizer.step()
        losses.append(float(loss.detach()))
    assert before_ids == {id(p) for p in head.parameters()}
    return {
        "steps": len(losses),
        "mean_loss": statistics.fmean(losses),
        "shuffled_labels": shuffle_labels,
        "trainable_params": actual_param_counts(head)["trainable"],
    }


@torch.no_grad() if torch is not None else (lambda fn: fn)
def accuracy(head: _Head, rows: Sequence[Any], *, frozen: bool = False) -> float:
    correct = 0
    for row in rows:
        scores = (
            row.features.frozen_scores if frozen else head.scores(row.features)[:-1]
        )
        best = int(scores.argmax()) if len(scores) else -1
        correct += int(best in tuple(row.positive_indices))
    return correct / len(rows) if rows else 0.0


def profile_flops(head: _Head, features: Any) -> int | None:
    """Return profiler-measured FLOPs, or null where this backend cannot report them."""
    _require_torch()
    if not hasattr(torch, "profiler"):
        return None
    try:
        with torch.profiler.profile(
            activities=[torch.profiler.ProfilerActivity.CPU], with_flops=True
        ) as prof:
            head.scores(features)
        flops = sum(
            int(getattr(event, "flops", 0) or 0) for event in prof.key_averages()
        )
        return flops or None
    except (RuntimeError, TypeError, AttributeError):
        return None


def latency_ms(head: _Head, features: Any, *, repeats: int = 20) -> float:
    _require_torch()
    for _ in range(3):
        head.scores(features)
    measurements = []
    for _ in range(repeats):
        start = time.perf_counter()
        head.scores(features)
        measurements.append((time.perf_counter() - start) * 1000)
    return statistics.median(measurements)


def run_probe(
    rows: Sequence[Any], cut: Any, *, steps: int = 32, rank: int = 16, seed: int = 1837
) -> dict[str, Any]:
    """Run all heads on one shared tensor fixture and preserve every denominator."""
    _require_torch()
    dimension = rows[0].features.paired.shape[1]
    if type(rank) is not int or not 1 <= rank <= dimension:
        raise ValueError("explicit probe rank exceeds frozen feature dimension")
    digest = source_digest(rows)
    reports = []
    frozen_accuracy = accuracy(make_head("linear", dimension), rows, frozen=True)
    for kind in HEAD_KINDS:
        torch.manual_seed(seed)
        head = make_head(kind, dimension, rank=rank)
        report = {
            "kind": kind,
            "param_counts": actual_param_counts(head),
            "frozen_control_accuracy": frozen_accuracy,
            "accuracy": None,
            "shuffled_control_accuracy": None,
            "median_latency_ms": None,
            "profiler_flops": None,
            "training": None,
            "status": "failed",
            "error": None,
            "efficacy_claim": False,
        }
        try:
            report["training"] = train_head(head, rows, cut, steps=steps, seed=seed)
            report["accuracy"] = accuracy(head, rows)
            try:
                shuffled = _shuffle_trained(kind, rows, cut, steps, rank, seed)
                report["shuffled_control_accuracy"] = accuracy(shuffled, rows)
            except (RuntimeError, ValueError, TypeError) as exc:
                report["error"] = f"shuffled-control: {exc}"
            report["median_latency_ms"] = latency_ms(head, rows[0].features)
            report["profiler_flops"] = profile_flops(head, rows[0].features)
            report["status"] = "completed"
        except (RuntimeError, ValueError, TypeError) as exc:
            report["error"] = str(exc)
        reports.append(report)
    return {
        "schema": "hepta.full-cell-heads-probe.v1",
        "source_digest": digest,
        "rows": len(rows),
        "denominator": len(rows),
        "reports": reports,
        "completed_heads": sum(r["status"] == "completed" for r in reports),
        "failed_heads": sum(r["status"] == "failed" for r in reports),
        "shared_inputs_frozen": True,
        "encoder_updates": 0,
        "mechanism_smoke_only": True,
        "reader_gate_checked": False,
        "production_accepted": False,
    }


def _shuffle_trained(
    kind: str, rows: Sequence[Any], cut: Any, steps: int, rank: int, seed: int
) -> _Head:
    head = make_head(kind, rows[0].features.paired.shape[1], rank=rank)
    train_head(head, rows, cut, steps=steps, shuffle_labels=True, seed=seed)
    return head


@dataclass
class _FixtureFeatures:
    question_id: str
    family: str
    encoder_identity: str
    pool_digest: str
    candidate_ids: tuple[str, ...]
    roots: frozenset[str]
    paired: object
    frozen_scores: object

    def validate(self, dimension: int) -> None:
        if self.paired.shape != (
            len(self.candidate_ids),
            dimension,
        ) or self.frozen_scores.shape != (len(self.candidate_ids),):
            raise ValueError("fixture shape")


@dataclass
class _FixtureRow:
    features: _FixtureFeatures
    positive_indices: tuple[int, ...]


def fixture() -> tuple[list[_FixtureRow], Any]:
    """Generate a deterministic tensor-only smoke fixture, never a task corpus."""
    _require_torch()
    torch.manual_seed(7)
    rows = []
    for i in range(6):
        rows.append(
            _FixtureRow(
                _FixtureFeatures(
                    f"q{i}",
                    "fixture",
                    "enc-fixture",
                    f"pool-{i}",
                    (f"c{i}-0", f"c{i}-1", f"c{i}-2"),
                    frozenset({"root-fixture"}),
                    torch.randn(3, 8),
                    torch.tensor([0.0, 0.1, 0.0]),
                ),
                (i % 2,),
            )
        )
    cut = SimpleNamespace(
        question_ids=frozenset(row.features.question_id for row in rows),
        families=frozenset({"fixture"}),
        allowed_roots=frozenset({"root-fixture"}),
        forbidden_roots=frozenset(),
        admission_digest="fixture-cut",
    )
    return rows, cut


def main(argv: list[str]) -> int:
    _require_torch()
    if len(argv) != 2:
        print("usage: full_cell_heads_probe.py OUTPUT_JSON", file=sys.stderr)
        return 2
    rows, cut = fixture()
    # Synthetic smoke fixture has 8 features; do not silently request rank 16.
    # The effective rank is explicit, and the normal public runner rejects
    # invalid rank overrides instead of treating failures as usable results.
    actual_rank = min(16, rows[0].features.paired.shape[1])
    result = run_probe(rows, cut, rank=actual_rank)
    result["actual_probe_rank"] = actual_rank
    Path(argv[1]).write_text(
        json.dumps(result, sort_keys=True, allow_nan=False, indent=2) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
