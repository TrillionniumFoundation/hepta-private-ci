"""Torch VJP through the frozen visit-897 source-to-N128 migration."""

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import numpy as np
import torch
from qualification.hcsn_adjoint_torch.torch_flow import _primal, _signature
from qualification.hcsn_graded.model import GradedJointModel
from qualification.hcsn_graded.spatial import GradedSpatialGenerator
from qualification.hcsn_initial_law.migration import MigrationBasis, migrate
from qualification.hcsn_source_migration_vjp_n128.large_adjoint import (
    DELAY,
    INTERVALS,
    amplitude_vjp_n128,
    freeze_n128_problem,
)
from torch.autograd.function import once_differentiable

PACKAGE = Path(__file__).resolve().parent
PARENT_PACKAGE = PACKAGE.parent / "hcsn_source_migration_vjp_n128"
SELECTED = PARENT_PACKAGE / "inputs/SELECTED_ORIGINAL_LAW.json"
N128_JSON = PARENT_PACKAGE / "inputs/seed37-c0_b1-step24-pos1-n128.json"
N128_NPZ = PARENT_PACKAGE / "inputs/seed37-c0_b1-step24-pos1-n128.npz"
SELECTED_SHA256 = "7a4b7485bf224b5e343f2c17fccf4ea7ca2dfdd06121810d16c503134f9e92fb"
N128_JSON_SHA256 = "8f4f77b8ba2bc1d1e3012f64ce9614711d178503601878e091b3db8e7eadaf09"
N128_NPZ_SHA256 = "fda047c1a8fce3cc042246b5249859cd0a0ba449647460ba9e0a39592386ff7d"
MIGRATION_SHA256 = "0e85587433dee39f583fe2c1409e127c75498c96928640890936fadaa12de517"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require_digest(actual, expected, label):
    if (
        not isinstance(actual, str)
        or not isinstance(expected, str)
        or len(actual) != 64
        or actual != expected
    ):
        raise ValueError(f"immutable {label} digest differs")


def _lift_digest(weights):
    digest = hashlib.sha256()
    for row in weights:
        for value in row:
            digest.update(str(value.numerator).encode())
            digest.update(b"/")
            digest.update(str(value.denominator).encode())
            digest.update(b"\n")
    return digest.hexdigest()


def validate_selected_payload(selected):
    """Validate the immutable #6223 selection before any model admission."""
    selection = selected.get("selection", {}) if isinstance(selected, dict) else {}
    if (
        not isinstance(selected, dict)
        or selected.get("schema") != "hcsn-original-journal-selected-law-v1"
        or selection.get("arm") != "c0_b1"
        or selection.get("seed") != 37
        or selection.get("position") != 1
        or selection.get("update_index") != 24
        or selection.get("visit_index") != 897
        or selected.get("origin_line_sha256")
        != "fed0107753b35d114c0cb8c3c668fb7f205b78697bb23db98c6e5fafd8a4054b"
        or selected.get("new_model_executions") != 0
    ):
        raise ValueError("visit 897 or its arm/update/position identity differs")
    probability = np.asarray(selected["state"]["probability"], dtype=float)[0]
    content = np.asarray(selected["state"]["content_mass"], dtype=float)[0]
    if (
        probability.shape != (25,)
        or content.shape != (25, 4)
        or np.min(probability) <= 0
        or probability.sum() != 1
        or not np.all(np.isfinite(content))
    ):
        raise ValueError("the original 25-by-(1+4) source law differs")
    return probability, content, selected["parameters"]


def validate_n128_payload(metadata, active, content, nodes, spatial):
    """Validate the immutable #6234 N128 export and actual graded nodes."""
    if (
        metadata.get("intervals") != INTERVALS
        or metadata.get("npz_sha256") != N128_NPZ_SHA256
        or metadata.get("current_recorded_gap") != 0.02
        or np.asarray(active).shape != (129,)
        or np.asarray(content).shape != (129, 4)
        or np.asarray(nodes).shape != (129,)
        or not np.array_equal(nodes, spatial.nodes)
        or active[0] != 0
        or np.any(content[0] != 0)
    ):
        raise ValueError("the #6234 actual N128 export differs")


@dataclass
class CallBudget:
    identity: str
    forward_limit: int = 42
    adjoint_limit: int = 2
    forward_calls: int = 0
    adjoint_calls: int = 0
    backward_attempts: int = 0
    guard_rejections: int = 0
    metadata_checks: int = 0
    optimizer_updates: int = 0
    forward_records: list = field(default_factory=list)
    adjoint_records: list = field(default_factory=list)
    _locked: object = field(default=None, init=False, repr=False)

    def validate(self):
        if (
            self.identity
            != "hcsn-original-visit897-source-migration-vjp-n128-inventory-successor-20261112-c06d"
            or self.forward_limit != 42
            or self.adjoint_limit != 2
            or any(
                type(value) is not int or value < 0
                for value in (
                    self.forward_calls,
                    self.adjoint_calls,
                    self.backward_attempts,
                    self.guard_rejections,
                    self.metadata_checks,
                    self.optimizer_updates,
                )
            )
            or self.forward_calls > self.forward_limit
            or self.adjoint_calls > self.adjoint_limit
            or self.optimizer_updates != 0
        ):
            raise ValueError("the exact 42F/2adjoint/0optimizer ledger differs")
        limits = (self.identity, self.forward_limit, self.adjoint_limit)
        if self._locked is None:
            self._locked = limits
        elif self._locked != limits:
            raise ValueError("the admission ledger changed after first use")


@dataclass(frozen=True)
class FrozenSourceMigration:
    problem: object
    lift_exact: tuple
    lift_float: np.ndarray
    migration_basis: object
    migration_lift: object
    source_hashes: dict
    source_probability: np.ndarray
    source_content: np.ndarray
    source_marks: np.ndarray
    lift_digest: str
    model_representation: str
    model: object

    def check(self, budget):
        budget.metadata_checks += 1
        current = {str(path): sha(path) for path in (SELECTED, N128_JSON, N128_NPZ)}
        current["qualification/hcsn_initial_law/migration.py"] = sha(
            PACKAGE.parent / "hcsn_initial_law/migration.py"
        )
        valid = (
            current == self.source_hashes
            and self.problem.identity == freeze_n128_problem(self.model).identity
            and repr(self.model) == self.model_representation
            and not self.lift_float.flags.writeable
            and self.migration_lift.basis == self.migration_basis
            and self.migration_lift.weights is self.lift_exact
            and _lift_digest(self.lift_exact) == self.lift_digest
        )
        if not valid:
            raise RuntimeError("the frozen source/migration/N128 snapshot changed")


def freeze_source_migration():
    """Bind #6223 source bytes, #6234 N128 bytes and exact migration bytes."""
    source_hashes = {
        str(SELECTED): sha(SELECTED),
        str(N128_JSON): sha(N128_JSON),
        str(N128_NPZ): sha(N128_NPZ),
        "qualification/hcsn_initial_law/migration.py": sha(
            PACKAGE.parent / "hcsn_initial_law/migration.py"
        ),
    }
    expected_hashes = {
        str(SELECTED): SELECTED_SHA256,
        str(N128_JSON): N128_JSON_SHA256,
        str(N128_NPZ): N128_NPZ_SHA256,
        "qualification/hcsn_initial_law/migration.py": MIGRATION_SHA256,
    }
    for label, expected in expected_hashes.items():
        require_digest(source_hashes[label], expected, label)
    selected, metadata = (
        json.loads(SELECTED.read_text()),
        json.loads(N128_JSON.read_text()),
    )
    probability, content, physics = validate_selected_payload(selected)
    if (
        metadata["reset_distance"]
        != math.log(physics["absolute_reset"]) - physics["log_boundary"]
    ):
        raise ValueError("visit 897 reset distance differs")
    spatial = GradedSpatialGenerator(
        INTERVALS, 8.0, physics["mu"], physics["sigma"], 6.0
    )
    model = GradedJointModel(
        spatial,
        math.log(physics["absolute_reset"]) - physics["log_boundary"],
        float(DELAY),
        physics["discount"],
    )
    with np.load(N128_NPZ, allow_pickle=False) as stored:
        expected_active = stored["active"].copy()
        expected_content = stored["content"].copy()
        expected_nodes = stored["nodes"].copy()
    validate_n128_payload(
        metadata, expected_active, expected_content, expected_nodes, spatial
    )
    basis = MigrationBasis(
        4.8,
        16,
        1.0,
        DELAY,
        8,
        8.0,
        INTERVALS,
        actual_nodes=tuple(spatial.nodes),
    )
    lift = basis.lift()
    lift_float = np.asarray(lift.weights, dtype=np.float64)
    migrated = migrate(
        basis,
        probability,
        content,
        identity="visit897-exact-migration-freeze",
        lift=lift,
    )
    migrated_active, migrated_content, _ = migrated.solve_inputs()
    if (
        not np.array_equal(migrated_active, expected_active)
        or not np.array_equal(migrated_content, expected_content)
        or migrated_active[0] != 0
    ):
        raise ValueError("the exact migration does not reproduce #6234 N128 bytes")
    lift_float.setflags(write=False)
    probability.setflags(write=False)
    content.setflags(write=False)
    marks = content / probability[:, None]
    marks.setflags(write=False)
    problem = freeze_n128_problem(model)
    return FrozenSourceMigration(
        problem=problem,
        lift_exact=lift.weights,
        lift_float=lift_float,
        migration_basis=basis,
        migration_lift=lift,
        source_hashes=source_hashes,
        source_probability=probability,
        source_content=content,
        source_marks=marks,
        lift_digest=_lift_digest(lift.weights),
        model_representation=repr(model),
        model=model,
    )


def _source_to_amplitudes(snapshot, probability, content):
    migrated = migrate(
        snapshot.migration_basis,
        probability,
        content,
        identity="visit897-exact-migration-runtime",
        lift=snapshot.migration_lift,
    )
    active, marked, _ = migrated.solve_inputs()
    if active[0] != 0 or np.any(marked[0] != 0):
        raise ValueError("migration invented a lower atom")
    return active[1:], marked[1:], probability[17:], content[17:]


class _SourceMigration(torch.autograd.Function):
    @staticmethod
    def forward(ctx, snapshot, options, budget, probability, content):
        budget.validate()
        if budget.forward_calls >= 42:
            raise ValueError("the exact N128 forward-call budget is exhausted")
        snapshot.check(budget)
        budget.forward_calls += 1
        arrays = (
            probability.detach().numpy().copy(),
            content.detach().numpy().copy(),
        )
        amplitudes = _source_to_amplitudes(snapshot, *arrays)
        started, cpu = time.perf_counter(), time.process_time()
        value, steps = _primal(snapshot.problem, amplitudes, options)
        snapshot.check(budget)
        budget.forward_records.append(
            {
                "forward_call": budget.forward_calls,
                "internal_steps": steps,
                "wall_seconds": time.perf_counter() - started,
                "cpu_seconds": time.process_time() - cpu,
                "problem_identity": snapshot.problem.identity,
            }
        )
        ctx.snapshot, ctx.options, ctx.budget = snapshot, options, budget
        ctx.live_inputs = (probability, content)
        ctx.input_signatures = (_signature(probability), _signature(content))
        ctx.save_for_backward(
            probability,
            content,
            probability.detach().clone(),
            content.detach().clone(),
        )
        ctx.set_materialize_grads(False)
        return torch.from_numpy(value.copy())

    @staticmethod
    @once_differentiable
    def backward(ctx, gradient):
        budget, snapshot = ctx.budget, ctx.snapshot
        budget.validate()
        budget.backward_attempts += 1
        try:
            saved = ctx.saved_tensors
            originals, copies = ctx.live_inputs, saved[2:]
            if tuple(_signature(value) for value in originals) != ctx.input_signatures:
                raise RuntimeError("source tensor metadata/storage changed")
            if any(
                not torch.equal(value, copy) for value, copy in zip(originals, copies)
            ):
                raise RuntimeError("source tensor value changed after forward")
            snapshot.check(budget)
        except RuntimeError:
            budget.guard_rejections += 1
            raise
        if gradient is None:
            return (None,) * 5
        if budget.adjoint_calls >= 2:
            raise ValueError("the exact N128 adjoint-call budget is exhausted")
        if not bool(torch.isfinite(gradient).all()) or bool(
            (gradient.abs() > 1e6).any()
        ):
            raise ValueError("bounded finite N128 cotangent required")
        budget.adjoint_calls += 1
        result = amplitude_vjp_n128(
            snapshot.problem,
            gradient.detach().contiguous().numpy().copy(),
            options=ctx.options,
        )
        amplitude = result.pop("vjp")
        probability = np.r_[
            snapshot.lift_float[:, 1:] @ amplitude[:128, 0],
            amplitude[128:, 0],
        ]
        content = np.vstack(
            [
                snapshot.lift_float[:, 1:] @ amplitude[:128, 1:],
                amplitude[128:, 1:],
            ]
        )
        if probability.shape != (25,) or content.shape != (25, 4):
            raise ArithmeticError("all 125 source transpose coordinates required")
        budget.adjoint_records.append(
            dict(
                adjoint_call=budget.adjoint_calls,
                probability_vjp=probability.tolist(),
                content_vjp=content.tolist(),
                amplitude_vjp=amplitude.tolist(),
                **result,
            )
        )
        return (
            None,
            None,
            None,
            torch.from_numpy(probability.copy()),
            torch.from_numpy(content.copy()),
        )


def source_flow(
    snapshot,
    probability,
    content,
    *,
    budget,
    rtol=2e-11,
    atol=2e-13,
    max_step=0.002,
    trainable_metadata=None,
):
    """Ambient raw source VJP; no probability normalization is performed."""
    if trainable_metadata is not None:
        raise ValueError(
            "trainable physics, delay, support or migration is not admitted"
        )
    if type(snapshot) is not FrozenSourceMigration or type(budget) is not CallBudget:
        raise ValueError("the exact frozen source snapshot and ledger are required")
    if (
        not isinstance(probability, torch.Tensor)
        or not isinstance(content, torch.Tensor)
        or probability.dtype != torch.float64
        or content.dtype != torch.float64
        or probability.device.type != "cpu"
        or content.device.type != "cpu"
        or probability.shape != (25,)
        or content.shape != (25, 4)
        or not bool(torch.isfinite(probability).all())
        or not bool(torch.isfinite(content).all())
        or bool((probability < 0).any())
        or bool((probability.abs() > 1e6).any())
        or bool((content.abs() > 1e6).any())
    ):
        raise ValueError(
            "bounded nonnegative probability and signed source content required"
        )
    if (
        not 1e-12 <= rtol <= 1e-3
        or not 1e-14 <= atol <= 1e-5
        or not math.isfinite(max_step)
        or not 0 < max_step <= float(DELAY)
    ):
        raise ValueError("bounded explicit numerical controls required")
    budget.validate()
    return _SourceMigration.apply(
        snapshot,
        (float(rtol), float(atol), float(max_step)),
        budget,
        probability,
        content,
    )


def exact_fraction_transpose(snapshot, amplitude_vjp):
    """Independent rational-lift transpose, converted only at final scalars."""
    amplitude = np.asarray(amplitude_vjp, dtype=np.float64)
    if amplitude.shape != (136, 5) or not np.all(np.isfinite(amplitude)):
        raise ValueError("the full amplitude VJP is required")
    independent = MigrationBasis(
        4.8,
        16,
        1.0,
        DELAY,
        8,
        8.0,
        INTERVALS,
        actual_nodes=tuple(snapshot.model.spatial.nodes),
    ).lift()
    if (
        independent.weights is snapshot.lift_exact
        or _lift_digest(independent.weights) != snapshot.lift_digest
    ):
        raise ArithmeticError("independent exact migration recomputation differs")
    probability, content = [], []
    for row in independent.weights:
        probability.append(
            float(
                sum(w * Fraction(str(v)) for w, v in zip(row[1:], amplitude[:128, 0]))
            )
        )
        content.append(
            [
                float(
                    sum(
                        w * Fraction(str(v))
                        for w, v in zip(row[1:], amplitude[:128, channel])
                    )
                )
                for channel in range(1, 5)
            ]
        )
    probability.extend(amplitude[128:, 0].tolist())
    content.extend(amplitude[128:, 1:].tolist())
    return np.asarray(probability), np.asarray(content)
