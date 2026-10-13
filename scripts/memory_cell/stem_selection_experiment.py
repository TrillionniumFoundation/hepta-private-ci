"""Experiment 1: shared Stem + per-Cell Head selection.

This is a bounded, research-only runner for comparing a shared encoder/Stem
against full-model replication.  The default backend is deterministic and
synthetic: it produces *estimates* from a preregistered cost/quality profile so
that the experiment can be run in CI without downloading model weights.  A
real backend can be supplied by implementing ``StemBenchmarkBackend``.

The runner deliberately keeps four dimensions separate:

* task utility and per-task quality;
* utility per active FLOP;
* p50/p95/p99 latency and memory;
* negative transfer and incremental per-Cell cost.

No candidate is promoted or selected for serving by this module.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
from typing import Any, Protocol, Sequence

SCHEMA = "hepta.experiment1-stem-selection.v1"
PROFILE_SCHEMA = "hepta.stem-selection-profile.v1"
DEFAULT_SEED = 20261013
MAX_TASKS = 4096
MAX_VARIANTS = 64
MAX_CELLS = 4096


class ValidationError(ValueError):
    """Invalid or unbound experimental input."""


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(float(value))


def _bounded_float(value: Any, *, low: float, high: float, name: str) -> float:
    if not _finite(value) or not low <= float(value) <= high:
        raise ValidationError(f"{name} outside bounded range")
    return float(value)


def _bounded_int(value: Any, *, low: int, high: int, name: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValidationError(f"{name} outside bounded range")
    return value


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _quantile(values: Sequence[float], q: float) -> float:
    if not values:
        raise ValidationError("latency sample set is empty")
    ordered = sorted(float(x) for x in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])


@dataclass(frozen=True)
class TaskCase:
    """A fixed evaluation item shared by all Stem variants."""

    task_id: str
    family: str
    difficulty: float = 0.5
    weight: float = 1.0

    def validate(self) -> None:
        if not self.task_id or not self.family:
            raise ValidationError("task_id and family are required")
        _bounded_float(self.difficulty, low=0.0, high=1.0, name="difficulty")
        _bounded_float(self.weight, low=0.0, high=1000.0, name="weight")


@dataclass(frozen=True)
class StemVariant:
    """Cost and capacity profile for one candidate architecture.

    ``replicate_full`` models a separate 421M model per Cell.  The other
    variants share one Stem and add a small Cell-specific Head.  Parameter
    counts are metadata/estimates, not proof that a model has task capacity.
    """

    variant_id: str
    stem_params_m: float
    head_params_m: float
    stem_memory_mb: float
    head_memory_mb: float
    stem_flops_per_token_g: float
    head_flops_per_token_g: float
    quality_ceiling: float
    negative_transfer_penalty: float = 0.0
    replicate_full: bool = False

    def validate(self) -> None:
        if not self.variant_id:
            raise ValidationError("variant_id is required")
        for field in (
            "stem_params_m", "head_params_m", "stem_memory_mb", "head_memory_mb",
            "stem_flops_per_token_g", "head_flops_per_token_g",
            "quality_ceiling", "negative_transfer_penalty",
        ):
            value = getattr(self, field)
            _bounded_float(value, low=0.0, high=10_000_000.0, name=field)
        _bounded_float(self.quality_ceiling, low=0.0, high=1.0, name="quality_ceiling")
        _bounded_float(self.negative_transfer_penalty, low=0.0, high=1.0, name="negative_transfer_penalty")
        if self.replicate_full and self.head_params_m != 0.0:
            raise ValidationError("replicate_full candidates cannot have a shared head")

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "StemVariant":
        if not isinstance(value, dict):
            raise ValidationError("variant must be an object")
        item = cls(
            variant_id=str(value.get("variant_id", "")),
            stem_params_m=value.get("stem_params_m", 0.0),
            head_params_m=value.get("head_params_m", 0.0),
            stem_memory_mb=value.get("stem_memory_mb", 0.0),
            head_memory_mb=value.get("head_memory_mb", 0.0),
            stem_flops_per_token_g=value.get("stem_flops_per_token_g", 0.0),
            head_flops_per_token_g=value.get("head_flops_per_token_g", 0.0),
            quality_ceiling=value.get("quality_ceiling", 0.0),
            negative_transfer_penalty=value.get("negative_transfer_penalty", 0.0),
            replicate_full=bool(value.get("replicate_full", False)),
        )
        item.validate()
        return item


@dataclass(frozen=True)
class TaskObservation:
    task_id: str
    quality: float
    active_flops_g: float
    latency_us: float
    cell_memory_mb: float


class StemBenchmarkBackend(Protocol):
    """Narrow interface for a real Stem/head benchmark implementation."""

    benchmark_mode: str

    def evaluate(
        self,
        variant: StemVariant,
        tasks: Sequence[TaskCase],
        *,
        cells: int,
        training_budget: int,
        seed: int,
    ) -> Sequence[TaskObservation]:
        """Return one observation per task for a fixed variant/workload."""


class SyntheticStemBackend:
    """Deterministic cost/quality model used for local smoke and CI runs."""

    benchmark_mode = "synthetic_estimate"

    def evaluate(
        self,
        variant: StemVariant,
        tasks: Sequence[TaskCase],
        *,
        cells: int,
        training_budget: int,
        seed: int,
    ) -> Sequence[TaskObservation]:
        variant.validate()
        _bounded_int(cells, low=1, high=MAX_CELLS, name="cells")
        _bounded_int(training_budget, low=1, high=10_000_000, name="training_budget")
        rng = random.Random(f"{seed}:{variant.variant_id}:{cells}:{training_budget}")
        out: list[TaskObservation] = []
        # A shared Stem is paid once, while a replicated model pays it per Cell.
        stem_multiplier = cells if variant.replicate_full else 1
        active_flops = (
            stem_multiplier * variant.stem_flops_per_token_g
            + cells * variant.head_flops_per_token_g
        )
        memory = (
            stem_multiplier * variant.stem_memory_mb
            + cells * variant.head_memory_mb
        )
        for task in tasks:
            # The quality curve saturates with a bounded budget.  Difficulty
            # and a tiny deterministic jitter model task heterogeneity.
            budget_gain = 1.0 - math.exp(-training_budget / 2000.0)
            capacity = variant.quality_ceiling * budget_gain
            quality = capacity - 0.28 * task.difficulty
            quality -= variant.negative_transfer_penalty * max(0.0, task.difficulty - 0.3)
            quality += rng.uniform(-0.0025, 0.0025)
            quality = max(0.0, min(1.0, quality))
            # Latency is per request; shared Stem supports continuous batch.
            latency = 80.0 + active_flops * 11.0 + task.difficulty * 25.0
            latency *= 1.0 + rng.uniform(-0.015, 0.015)
            out.append(TaskObservation(task.task_id, quality, active_flops, latency, memory))
        return out


DEFAULT_VARIANTS: tuple[StemVariant, ...] = (
    StemVariant("small_stem_head", 80.0, 1.0, 320.0, 8.0, 0.22, 0.006, 0.67, 0.025),
    StemVariant("medium_stem_head", 180.0, 2.0, 720.0, 12.0, 0.48, 0.012, 0.76, 0.015),
    StemVariant("421m_stem_head", 421.0, 2.0, 1684.0, 12.0, 1.08, 0.012, 0.83, 0.008),
    StemVariant("replicate_full_421m", 421.0, 0.0, 1684.0, 0.0, 1.08, 0.0, 0.85, 0.0, True),
)


def default_tasks(count: int = 16) -> tuple[TaskCase, ...]:
    count = _bounded_int(count, low=1, high=MAX_TASKS, name="task_count")
    families = ("retrieval", "temporal", "planning", "classification")
    tasks = tuple(
        TaskCase(f"task-{i:04d}", families[i % len(families)], 0.15 + ((i * 17) % 80) / 100.0)
        for i in range(count)
    )
    for task in tasks:
        task.validate()
    return tasks


def _validate_tasks(tasks: Sequence[TaskCase]) -> tuple[TaskCase, ...]:
    if not 1 <= len(tasks) <= MAX_TASKS:
        raise ValidationError("task set outside bounded range")
    result = tuple(tasks)
    ids = set()
    for task in result:
        task.validate()
        if task.task_id in ids:
            raise ValidationError("duplicate task_id")
        ids.add(task.task_id)
    return result


def run_experiment(
    tasks: Sequence[TaskCase],
    variants: Sequence[StemVariant] = DEFAULT_VARIANTS,
    *,
    cells: int = 32,
    training_budget: int = 1000,
    seed: int = DEFAULT_SEED,
    backend: StemBenchmarkBackend | None = None,
) -> dict[str, Any]:
    """Run all variants over exactly the same tasks/cells/budget."""
    tasks = _validate_tasks(tasks)
    variants = tuple(variants)
    if not 1 <= len(variants) <= MAX_VARIANTS:
        raise ValidationError("variant set outside bounded range")
    for variant in variants:
        variant.validate()
    if len({v.variant_id for v in variants}) != len(variants):
        raise ValidationError("duplicate variant_id")
    cells = _bounded_int(cells, low=1, high=MAX_CELLS, name="cells")
    training_budget = _bounded_int(training_budget, low=1, high=10_000_000, name="training_budget")
    seed = _bounded_int(seed, low=0, high=2**31 - 1, name="seed")
    backend = backend or SyntheticStemBackend()
    observations: dict[str, list[TaskObservation]] = {}
    for variant in variants:
        rows = tuple(backend.evaluate(variant, tasks, cells=cells, training_budget=training_budget, seed=seed))
        if len(rows) != len(tasks) or {r.task_id for r in rows} != {t.task_id for t in tasks}:
            raise ValidationError(f"backend returned incomplete task observations for {variant.variant_id}")
        for row in rows:
            if not all(_finite(getattr(row, f)) for f in ("quality", "active_flops_g", "latency_us", "cell_memory_mb")):
                raise ValidationError("backend returned nonfinite observation")
            if not 0.0 <= row.quality <= 1.0 or row.active_flops_g < 0 or row.latency_us < 0 or row.cell_memory_mb < 0:
                raise ValidationError("backend returned out-of-range observation")
        observations[variant.variant_id] = list(rows)

    # Full-model replication is the diagnostic reference for negative transfer.
    reference_id = next((v.variant_id for v in variants if v.replicate_full), variants[-1].variant_id)
    reference = {r.task_id: r.quality for r in observations[reference_id]}
    result_rows: list[dict[str, Any]] = []
    for variant in variants:
        rows = observations[variant.variant_id]
        weighted = math.fsum(r.quality * t.weight for r, t in zip(sorted(rows, key=lambda r: r.task_id), sorted(tasks, key=lambda t: t.task_id)))
        total_weight = math.fsum(t.weight for t in tasks)
        utility = weighted / total_weight if total_weight else 0.0
        mean_flops = statistics.fmean(r.active_flops_g for r in rows)
        mean_latency = statistics.fmean(r.latency_us for r in rows)
        quality_by_id = {r.task_id: r.quality for r in rows}
        deficits = [max(0.0, reference[r.task_id] - r.quality) for r in rows if r.task_id in reference and r.task_id != reference_id]
        # For the reference itself this is defined as zero by convention.
        negative_transfer = 0.0 if variant.variant_id == reference_id else math.fsum(deficits) / len(deficits) if deficits else 0.0
        negative_count = 0 if variant.variant_id == reference_id else sum(d > 0.01 for d in deficits)
        base_memory = variant.stem_memory_mb * (cells if variant.replicate_full else 1)
        head_memory = variant.head_memory_mb * cells
        incremental_memory = head_memory + (variant.stem_memory_mb if variant.replicate_full else 0.0)
        params = variant.stem_params_m * (cells if variant.replicate_full else 1) + variant.head_params_m * cells
        result_rows.append(
            dict(
                variant_id=variant.variant_id,
                shared_stem=not variant.replicate_full,
                cells=cells,
                stem_params_m=variant.stem_params_m,
                head_params_m=variant.head_params_m,
                total_parameters_m=params,
                resident_memory_mb=base_memory + head_memory,
                incremental_parameters_per_cell_m=(
                    variant.stem_params_m if variant.replicate_full else variant.head_params_m
                ),
                incremental_memory_per_cell_mb=(
                    variant.head_memory_mb
                    + (variant.stem_memory_mb if variant.replicate_full else 0.0)
                ),
                incremental_active_flops_per_cell_g=(
                    variant.stem_flops_per_token_g + variant.head_flops_per_token_g
                ),
                utility=utility,
                utility_per_active_flop=(utility / mean_flops if mean_flops > 0 else None),
                active_flops_per_request_g=mean_flops,
                latency_us=dict(
                    p50=_quantile([r.latency_us for r in rows], 0.50),
                    p95=_quantile([r.latency_us for r in rows], 0.95),
                    p99=_quantile([r.latency_us for r in rows], 0.99),
                ),
                negative_transfer_mean=negative_transfer,
                negative_transfer_count=negative_count,
                quality_by_task=quality_by_id,
                task_observations=[asdict(r) for r in sorted(rows, key=lambda r: r.task_id)],
            )
        )
    profile = dict(
        schema=PROFILE_SCHEMA,
        candidates=[asdict(v) for v in variants],
        task_ids=[t.task_id for t in tasks],
        cells=cells,
        training_budget=training_budget,
        seed=seed,
        reference_variant_id=reference_id,
    )
    return dict(
        schema=SCHEMA,
        benchmark_mode=getattr(backend, "benchmark_mode", type(backend).__name__),
        profile_digest=_digest(profile),
        profile=profile,
        results=result_rows,
        production_accepted=False,
        model_selection_authority=False,
        note="Synthetic mode is a cost/quality scaffold; it is not evidence of pretrained task capability.",
    )


def load_tasks(path: Path) -> tuple[TaskCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload.get("tasks") if isinstance(payload, dict) else payload
    if not isinstance(values, list):
        raise ValidationError("tasks JSON must be a list or {tasks: [...]}")
    return _validate_tasks(tuple(TaskCase(**item) for item in values))


def load_variants(path: Path) -> tuple[StemVariant, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload.get("variants") if isinstance(payload, dict) else payload
    if not isinstance(values, list):
        raise ValidationError("variants JSON must be a list or {variants: [...]}")
    return tuple(StemVariant.from_mapping(item) for item in values)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, help="JSON task list; default is deterministic local tasks")
    parser.add_argument("--variants", type=Path, help="JSON candidate profiles; default is four registered candidates")
    parser.add_argument("--cells", type=int, default=32)
    parser.add_argument("--training-budget", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output", type=Path, required=True, help="new JSON report path")
    args = parser.parse_args(argv)
    tasks = load_tasks(args.tasks) if args.tasks else default_tasks()
    variants = load_variants(args.variants) if args.variants else DEFAULT_VARIANTS
    report = run_experiment(tasks, variants, cells=args.cells, training_budget=args.training_budget, seed=args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
