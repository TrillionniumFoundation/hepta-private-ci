"""Shadow-only short-horizon FBSDE/System2 trajectory contracts.

The contract records a local contraction certificate and the digest lineage of
each forward/backward step. It does not solve an FBSDE, train a model, mutate
weights, or grant execution authority. A numerical solver must produce the
receipts and an independent evaluator must check residuals and holdouts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Tuple

from cell_fast_path_actionir import canonical_digest


ZERO = "0" * 64
STATUSES = frozenset(("succeeded", "failed", "cancelled", "indeterminate"))


def _digest(value: str, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{field} must be a 64-character digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{field} must be hexadecimal") from exc
    return value


def _positive(value: int, field: str, upper: int | None = None) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    if upper is not None and value > upper:
        raise ValueError(f"{field} must be <= {upper}")
    return value


def _bounded(value: int, field: str, upper: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > upper:
        raise ValueError(f"{field} must be an integer in [0, {upper}]")
    return value


@dataclass(frozen=True)
class FBSDEProblemV1:
    problem_id: str
    state_dim: int
    control_dim: int
    horizon_steps: int
    dt_nanos: int
    initial_state_digest: str
    terminal_condition_digest: str
    driver_digest: str
    diffusion_digest: str
    solver_digest: str
    stem_digest: str
    cell_digest: str
    snapshot_id: str
    generation: int
    step_contraction_ppm: int
    max_residual_ppm: int
    max_step_memory_bytes: int
    max_step_latency_ns: int
    authority: str = "DENY_ALL"

    def __post_init__(self) -> None:
        if not self.problem_id or not isinstance(self.problem_id, str):
            raise ValueError("problem_id must be non-empty")
        _positive(self.state_dim, "state_dim", 1_000_000)
        _positive(self.control_dim, "control_dim", 1_000_000)
        _positive(self.horizon_steps, "horizon_steps", 64)
        _positive(self.dt_nanos, "dt_nanos", 10**12)
        for name in (
            "initial_state_digest",
            "terminal_condition_digest",
            "driver_digest",
            "diffusion_digest",
            "solver_digest",
            "stem_digest",
            "cell_digest",
        ):
            _digest(getattr(self, name), name)
        if not self.snapshot_id or not isinstance(self.snapshot_id, str):
            raise ValueError("snapshot_id must be non-empty")
        _bounded(self.generation, "generation", 2**63 - 1)
        _bounded(self.step_contraction_ppm, "step_contraction_ppm", 999_999)
        _bounded(self.max_residual_ppm, "max_residual_ppm", 1_000_000)
        _positive(self.max_step_memory_bytes, "max_step_memory_bytes")
        _positive(self.max_step_latency_ns, "max_step_latency_ns")
        if self.horizon_steps * self.step_contraction_ppm >= 1_000_000:
            raise ValueError("short-horizon contraction certificate must have load < 1")
        if self.authority != "DENY_ALL":
            raise ValueError("FBSDE problems cannot carry authority")

    @property
    def problem_digest(self) -> str:
        return canonical_digest(
            {
                "schema": "hepta.fbsde-problem.v1",
                "problem_id": self.problem_id,
                "state_dim": self.state_dim,
                "control_dim": self.control_dim,
                "horizon_steps": self.horizon_steps,
                "dt_nanos": self.dt_nanos,
                "initial_state_digest": self.initial_state_digest,
                "terminal_condition_digest": self.terminal_condition_digest,
                "driver_digest": self.driver_digest,
                "diffusion_digest": self.diffusion_digest,
                "solver_digest": self.solver_digest,
                "stem_digest": self.stem_digest,
                "cell_digest": self.cell_digest,
                "snapshot_id": self.snapshot_id,
                "generation": self.generation,
                "step_contraction_ppm": self.step_contraction_ppm,
                "max_residual_ppm": self.max_residual_ppm,
                "max_step_memory_bytes": self.max_step_memory_bytes,
                "max_step_latency_ns": self.max_step_latency_ns,
                "authority": self.authority,
            }
        )

    @property
    def contraction_margin_ppm(self) -> int:
        return 1_000_000 - self.horizon_steps * self.step_contraction_ppm


@dataclass(frozen=True)
class FBSDEStepReceiptV1:
    problem_digest: str
    trajectory_id: str
    step_index: int
    parent_state_digest: str
    next_state_digest: str
    y_digest: str
    z_digest: str
    noise_digest: str
    utility_lcb_milli: int
    utility_ucb_milli: int
    residual_ppm: int
    observed_memory_bytes: int
    latency_ns: int
    status: str
    receipt_digest: str
    authority: str = "DENY_ALL"
    effect_admitted: bool = False

    def __post_init__(self) -> None:
        _digest(self.problem_digest, "problem_digest")
        if not self.trajectory_id or not isinstance(self.trajectory_id, str):
            raise ValueError("trajectory_id must be non-empty")
        _bounded(self.step_index, "step_index", 63)
        _digest(self.parent_state_digest, "parent_state_digest")
        _digest(self.next_state_digest, "next_state_digest")
        _digest(self.y_digest, "y_digest")
        _digest(self.z_digest, "z_digest")
        _digest(self.noise_digest, "noise_digest")
        _bounded(self.utility_lcb_milli, "utility_lcb_milli", 1_000_000)
        _bounded(self.utility_ucb_milli, "utility_ucb_milli", 1_000_000)
        _bounded(self.residual_ppm, "residual_ppm", 1_000_000)
        _bounded(self.observed_memory_bytes, "observed_memory_bytes", 2**63 - 1)
        _bounded(self.latency_ns, "latency_ns", 2**63 - 1)
        _digest(self.receipt_digest, "receipt_digest")
        if self.status not in STATUSES:
            raise ValueError(f"unknown status: {self.status}")
        if self.utility_lcb_milli > self.utility_ucb_milli:
            raise ValueError("utility lower bound must not exceed upper bound")
        if self.authority != "DENY_ALL" or self.effect_admitted:
            raise ValueError("FBSDE receipts cannot carry authority or effects")
        if self.status != "succeeded" and any(
            value != ZERO
            for value in (self.next_state_digest, self.y_digest, self.z_digest)
        ):
            raise ValueError("non-succeeded steps cannot carry output state or solution fields")


@dataclass(frozen=True)
class FBSDETrajectoryReceiptV1:
    problem_digest: str
    trajectory_id: str
    step_receipt_digests: Tuple[str, ...]
    completed_steps: int
    terminal_state_digest: Optional[str]
    status: str
    trajectory_digest: str
    authority: str = "DENY_ALL"
    effect_admitted: bool = False

    def __post_init__(self) -> None:
        _digest(self.problem_digest, "problem_digest")
        if not self.trajectory_id or not isinstance(self.trajectory_id, str):
            raise ValueError("trajectory_id must be non-empty")
        if tuple(sorted(set(self.step_receipt_digests))) != self.step_receipt_digests:
            raise ValueError("step_receipt_digests must be sorted and unique")
        for digest in self.step_receipt_digests:
            _digest(digest, "step_receipt_digest")
        _bounded(self.completed_steps, "completed_steps", 64)
        if self.completed_steps != len(self.step_receipt_digests):
            raise ValueError("completed_steps must equal the number of step receipts")
        if self.terminal_state_digest is not None:
            _digest(self.terminal_state_digest, "terminal_state_digest")
        if self.status not in STATUSES:
            raise ValueError(f"unknown status: {self.status}")
        if self.status in ("succeeded", "indeterminate") and self.completed_steps and self.terminal_state_digest is None:
            raise ValueError("non-empty trajectory must carry current state")
        _digest(self.trajectory_digest, "trajectory_digest")
        if self.authority != "DENY_ALL" or self.effect_admitted:
            raise ValueError("trajectories cannot carry authority or effects")


def _step_payload(step: FBSDEStepReceiptV1) -> Mapping[str, object]:
    return {
        "schema": "hepta.fbsde-step-receipt.v1",
        "problem_digest": step.problem_digest,
        "trajectory_id": step.trajectory_id,
        "step_index": step.step_index,
        "parent_state_digest": step.parent_state_digest,
        "next_state_digest": step.next_state_digest,
        "y_digest": step.y_digest,
        "z_digest": step.z_digest,
        "noise_digest": step.noise_digest,
        "utility_lcb_milli": step.utility_lcb_milli,
        "utility_ucb_milli": step.utility_ucb_milli,
        "residual_ppm": step.residual_ppm,
        "observed_memory_bytes": step.observed_memory_bytes,
        "latency_ns": step.latency_ns,
        "status": step.status,
        "authority": step.authority,
        "effect_admitted": step.effect_admitted,
    }


def _trajectory_payload(
    problem_digest: str,
    trajectory_id: str,
    step_receipt_digests: Tuple[str, ...],
    completed_steps: int,
    terminal_state_digest: Optional[str],
    status: str,
) -> Mapping[str, object]:
    return {
        "schema": "hepta.fbsde-trajectory-receipt.v1",
        "problem_digest": problem_digest,
        "trajectory_id": trajectory_id,
        "step_receipt_digests": step_receipt_digests,
        "completed_steps": completed_steps,
        "terminal_state_digest": terminal_state_digest,
        "status": status,
        "authority": "DENY_ALL",
        "effect_admitted": False,
    }


def append_verified_step(
    problem: FBSDEProblemV1,
    prior: Optional[FBSDETrajectoryReceiptV1],
    step: FBSDEStepReceiptV1,
) -> FBSDETrajectoryReceiptV1:
    """Append a verified non-effect step to a short-horizon trajectory."""

    if step.problem_digest != problem.problem_digest:
        raise ValueError("FBSDE_PROBLEM_DIGEST_MISMATCH")
    if step.status != "succeeded":
        raise ValueError("FBSDE_STEP_NOT_SUCCESSFUL")
    if step.residual_ppm > problem.max_residual_ppm:
        raise ValueError("FBSDE_RESIDUAL_OVER_BUDGET")
    if step.observed_memory_bytes > problem.max_step_memory_bytes:
        raise ValueError("FBSDE_MEMORY_OVER_BUDGET")
    if step.latency_ns > problem.max_step_latency_ns:
        raise ValueError("FBSDE_LATENCY_OVER_BUDGET")
    if step.step_index >= problem.horizon_steps:
        raise ValueError("FBSDE_HORIZON_EXCEEDED")
    if canonical_digest(_step_payload(step)) != step.receipt_digest:
        raise ValueError("FBSDE_STEP_RECEIPT_DIGEST_MISMATCH")
    if prior is None:
        if step.step_index != 0:
            raise ValueError("FBSDE_STEP_INDEX_NOT_ZERO")
        if step.parent_state_digest != problem.initial_state_digest:
            raise ValueError("FBSDE_INITIAL_STATE_MISMATCH")
        if step.trajectory_id == "":
            raise ValueError("FBSDE_TRAJECTORY_ID_EMPTY")
        digests = (step.receipt_digest,)
    else:
        if prior.problem_digest != problem.problem_digest:
            raise ValueError("FBSDE_PRIOR_PROBLEM_MISMATCH")
        if canonical_digest(
            _trajectory_payload(
                prior.problem_digest,
                prior.trajectory_id,
                prior.step_receipt_digests,
                prior.completed_steps,
                prior.terminal_state_digest,
                prior.status,
            )
        ) != prior.trajectory_digest:
            raise ValueError("FBSDE_PRIOR_TRAJECTORY_DIGEST_MISMATCH")
        if prior.trajectory_id != step.trajectory_id:
            raise ValueError("FBSDE_TRAJECTORY_ID_MISMATCH")
        if prior.status not in ("indeterminate", "succeeded"):
            raise ValueError("FBSDE_PRIOR_NOT_SUCCESSFUL")
        if step.receipt_digest in prior.step_receipt_digests:
            raise ValueError("FBSDE_REPLAY_DUPLICATE_STEP")
        if step.step_index != prior.completed_steps:
            raise ValueError("FBSDE_STEP_INDEX_NOT_SEQUENTIAL")
        if prior.terminal_state_digest != step.parent_state_digest:
            raise ValueError("FBSDE_PARENT_STATE_MISMATCH")
        digests = tuple(sorted((*prior.step_receipt_digests, step.receipt_digest)))
    completed = (prior.completed_steps if prior else 0) + 1
    status = "succeeded" if completed == problem.horizon_steps else "indeterminate"
    terminal = step.next_state_digest
    payload = _trajectory_payload(problem.problem_digest, step.trajectory_id, digests, completed, terminal, status)
    return FBSDETrajectoryReceiptV1(
        problem_digest=problem.problem_digest,
        trajectory_id=step.trajectory_id,
        step_receipt_digests=digests,
        completed_steps=completed,
        terminal_state_digest=terminal,
        status=status,
        trajectory_digest=canonical_digest(payload),
    )
