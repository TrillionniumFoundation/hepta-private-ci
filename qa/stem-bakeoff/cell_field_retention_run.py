"""Bounded deployment of optional retention control through the actual Cell state.

This is frozen-reference tangent MPC, not a nonlinear optimal-control solver.
Every suffix observes the real theta/m/v state and keeps the original reference
and old-loss anchor. Legacy policy fitting/action and published costs are intact.
No source acquisition, Encoder, final-label reader or production authority exists
here. Runtime limits are cooperative between bounded numerical operations.
"""

from dataclasses import asdict, dataclass
import hashlib
import math
import sys
import time

import numpy as np

from cell_field_control import Reference, fit_controller, quadratic_cost
from cell_field_retention import (PROFILE, RetentionSolveError, retention_cost,
                                  retention_targets, solve_retention_tangent)
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import canonical


RUN_PROFILE = "hepta.cell-retention.frozen-reference-mpc.v1"
ARMS = ("zero", "legacy_full_quadratic", "retention_hinge_suffix")


@dataclass(frozen=True)
class RetentionRunLimits:
    max_cpu_seconds: float = 10.0
    max_wall_seconds: float = 60.0
    max_action_l2: float = 10.0
    max_intervention_l2: float = 0.2
    max_scaled_displacement_l2: float = 100.0
    max_parameter_l2: float = 1000.0
    max_solver_iterations: int = 64
    gradient_tolerance: float = 1e-9


class RetentionRunError(RuntimeError):
    """Failed condition with incurred work and actual applied prefix preserved."""

    def __init__(self, message, result):
        super().__init__(message)
        self.result = result


def _hash_array(value):
    value = np.asarray(value)
    digest = hashlib.sha256(canonical([list(value.shape), value.dtype.str]))
    digest.update(value.tobytes(order="C"))
    return digest.hexdigest()


def _norm(value):
    result = math.hypot(*np.asarray(value).ravel())
    if not math.isfinite(result):
        raise ValueError("nonfinite magnitude diagnostic")
    return result


def _peak_rss():
    try:
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value if sys.platform == "darwin" else value * 1024)
    except ImportError:
        return None


def _positive(value, name):
    if (isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= 0):
        raise ValueError(f"finite positive {name} required")


def _validate(state, ref, arm, anchor, limits):
    if type(state) is not CellTrainingState or type(ref) is not Reference:
        raise ValueError("actual CellTrainingState and Reference required")
    if arm not in ARMS or type(limits) is not RetentionRunLimits:
        raise ValueError("declared arm and explicit bounded limits required")
    for name, value in asdict(limits).items():
        if name != "max_solver_iterations":
            _positive(value, name)
    if (type(limits.max_solver_iterations) is not int
            or not 1 <= limits.max_solver_iterations <= 128
            or not 1e-14 <= limits.gradient_tolerance <= 1e-4):
        raise ValueError("bounded numerical stopping settings required")
    n, d = ref.horizon, len(state.vector())
    if (not 1 <= n <= 64 or not 1 <= d <= 512 or not 0 < ref.dt <= 1
            or n * d * d > 2_000_000 or ref.A.shape != (n, d, d)
            or ref.C.shape != (n + 1, 4, d) or ref.states.shape != (n + 1, d)
            or ref.observations.shape != (n + 1, 4) or ref.scales.shape != (d,)
            or np.any(ref.scales <= 0)
            or not all(np.isfinite(v).all() for v in
                       (ref.A, ref.C, ref.states, ref.observations, ref.scales))
            or state.protocol["sampler"] != "full_batch" or state.step_count < 1
            or state.digest() != ref.state.digest()
            or not np.array_equal(state.vector(), ref.states[0])):
        raise ValueError("bounded finite original full-batch reference/state identity required")
    if (dataset_digest(ref.train_features, ref.train_labels)
            != state.contexts[state.active_context]):
        raise ValueError("current training context differs from the frozen reference")
    observed, _ = ref.observe(state.vector())
    if (not np.array_equal(observed, ref.observations[0])
            or isinstance(anchor, (bool, np.bool_)) or not math.isfinite(float(anchor))
            or float(anchor) != float(observed[1])):
        raise ValueError("anchor must be the original warmup old-probe loss exactly")
    for k in range(n):
        next_state = state.transition_vector(ref.states[k], state.step_count + k,
                                             ref.train_features, ref.train_labels)
        next_observed, _ = ref.observe(next_state)
        if (not np.array_equal(next_state, ref.states[k + 1])
                or not np.array_equal(next_observed, ref.observations[k + 1])):
            raise ValueError("original no-control reference does not replay exactly")


def _reference_id(ref):
    return {"initial_state": ref.state.digest(), "dt": ref.dt,
            "arrays": {name: _hash_array(value) for name, value in ref.arrays().items()},
            "training": dataset_digest(ref.train_features, ref.train_labels),
            "normalized_probes": [{"features": _hash_array(x), "labels": _hash_array(y)}
                                  for x, y in ref.probes]}


def run_retention_control(state, reference, *, arm, anchor, tolerance=0.02,
                          old_weight=1.0, current_target=-0.03, effort_price=0.1,
                          mask="bias", limits=None, stop_after=None, resume=None):
    """Execute one predeclared arm; no clipping, fallback or post-failure success.

    The original target path is built once. A suffix starts with the actual
    scaled state displacement and uses the remaining ORIGINAL A/E/C/targets.
    E already includes dt; the physical update separately uses dt*B@u exactly
    once. This does not relinearize around the controlled trajectory, constrain
    actual old loss, or certify the nonlinear policy's optimality.

    stop_after is an explicit pause for replay testing, not a completed arm.
    Resumption accepts only a paused prefix of this exact contract and verifies
    it by deterministic full-state replay; replay work is charged to this call.
    External interruption is not handled here: a durable supervisor must bound
    a worker and retain its last published checkpoint/log if a call is killed.
    """
    started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
    rss_before = _peak_rss()
    limits = RetentionRunLimits() if limits is None else limits
    _validate(state, reference, arm, anchor, limits)
    ref, initial_digest = reference, state.digest()
    target = retention_targets(ref.observations[:, :2], current_target,
                               anchor=anchor, tolerance=tolerance)
    legacy_target = retention_targets(ref.observations[:, :2], current_target,
                                      anchor=anchor, tolerance=0.0)
    # Validate charges even if an all-zero arm never invokes the tangent solver.
    B, E = ref.action_matrix(mask)
    retention_cost(np.zeros_like(target), np.zeros((ref.horizon, B.shape[1])),
                   target, ref.dt, effort_price, old_weight=old_weight)
    if E.shape[2] > 128 or ref.horizon * (len(ref.scales) ** 2 + E.shape[2] ** 2) > 2_000_000:
        raise ValueError("bounded action/state Riccati work required for every arm")
    if stop_after is None:
        stop_after = ref.horizon
    if type(stop_after) is not int or not 1 <= stop_after <= ref.horizon:
        raise ValueError("explicit pause must end at a bounded positive step")
    contract = {"profile": RUN_PROFILE, "objective": PROFILE, "arm": arm,
                "reference": _reference_id(ref), "anchor": float(anchor),
                "tolerance": float(tolerance), "old_weight": float(old_weight),
                "effort_price": float(effort_price), "mask": mask,
                "target_sha256": _hash_array(target),
                "legacy_target_sha256": _hash_array(legacy_target),
                "limits": asdict(limits), "authority": "DENY_ALL"}
    contract_sha = hashlib.sha256(canonical(contract)).hexdigest()
    current = state.clone()
    states, observations, actions, steps, solves = [], [], [], [], []
    phase_costs = {"admission": {"calls": 1, "wall_ns": time.perf_counter_ns() - started,
                                  "cpu_ns": time.process_time_ns() - cpu_started}}
    decisions, recovery = [], {"replayed_steps": 0}
    parameter_mask, policy, stage = np.any(B != 0, axis=1), None, "setup"

    def measured(phase, operation):
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        try:
            return operation()
        finally:
            counts = phase_costs.setdefault(phase, {"calls": 0, "wall_ns": 0, "cpu_ns": 0})
            counts["calls"] += 1
            counts["wall_ns"] += time.perf_counter_ns() - wall
            counts["cpu_ns"] += time.process_time_ns() - cpu

    def budget():
        if ((time.process_time_ns() - cpu_started) / 1e9 > limits.max_cpu_seconds
                or (time.perf_counter_ns() - started) / 1e9 > limits.max_wall_seconds):
            raise ValueError("cooperative runtime budget exceeded")

    def append_observation(k):
        value = current.vector()
        states.append(value)
        if (_norm(current.parameter_vector()) > limits.max_parameter_l2
                or _norm((value - ref.states[k]) / ref.scales)
                > limits.max_scaled_displacement_l2):
            raise ValueError("actual state exceeded predeclared magnitude guard")
        observed, _ = measured("actual_probe_observation", lambda: ref.observe(value))
        if not np.isfinite(observed).all():
            raise ValueError("nonfinite actual probe observation")
        observations.append(observed)

    def snapshot(status, error=None, costs=None):
        observed = np.asarray(observations, dtype=np.float64).reshape(-1, 4)
        fields = observed[:, :2] - ref.observations[:len(observed), :2]
        receipt = {"profile": RUN_PROFILE, "status": status, "contract_sha256": contract_sha,
                   "contract": contract, "initial_state_sha256": initial_digest,
                   "actual_state_sha256": current.digest(), "applied_steps": len(actions),
                   "observed_states": len(observed), "expected_steps": ref.horizon,
                   "failure_stage": stage if error else None, "error": error,
                   "wall_ns": time.perf_counter_ns() - started,
                   "cpu_ns": time.process_time_ns() - cpu_started,
                   "process_peak_rss_before_bytes": rss_before,
                   "process_peak_rss_after_bytes": _peak_rss(),
                   "rss_scope": "this process cumulative high-water mark; not per-arm incremental peak or full process tree",
                   "phase_costs": phase_costs, "recovery": recovery,
                   "solver_receipts": solves, "decisions": decisions,
                   "accounting": "phase times are subsets of this call, not additive to total; admission is included; reference construction, persistence, Encoder and final evaluation are external",
                   "cap_semantics": "cooperative checks between bounded calls, not hard preemption",
                   "reference_geometry": "unchanged original full-state tangent",
                   "hard_retention_guarantee": False, "nonlinear_optimum": False,
                   "authority": "DENY_ALL"}
        return {"state": current.clone(), "states": np.asarray(states),
                "observations": observed, "fields": fields,
                "actions": np.asarray(actions, dtype=np.float64).reshape(-1, B.shape[1]),
                "target": target.copy(), "legacy_target": legacy_target.copy(),
                "steps": steps, "receipt": receipt, "costs": costs}

    try:
        append_observation(0)
        budget()
        if resume is not None:
            stage = "recovery_verification"
            previous = resume["receipt"]
            count = previous["applied_steps"]
            if (previous["status"] != "paused" or previous["contract_sha256"] != contract_sha
                    or type(count) is not int or not 1 <= count < stop_after
                    or len(resume["actions"]) != count or len(resume["steps"]) != count
                    or np.shape(resume["states"]) != (count + 1, len(ref.scales))
                    or np.shape(resume["observations"]) != (count + 1, 4)
                    or not np.array_equal(resume["target"], target)
                    or not np.array_equal(resume["legacy_target"], legacy_target)):
                raise ValueError("paused prefix contract, cursor or array identity differs")
            recovery.update(previous_receipt=previous,
                            previous_actual_state_sha256=previous["actual_state_sha256"])
            for k, action in enumerate(resume["actions"]):
                action = np.asarray(action, dtype=np.float64)
                if not np.isfinite(action).all() or _norm(action) > limits.max_action_l2:
                    raise ValueError("replay action violates the original contract")
                delta = ref.dt * B @ action
                if _norm(delta) > limits.max_intervention_l2:
                    raise ValueError("replay intervention violates the original contract")
                step = measured("recovery_transition", lambda: current.advance(
                    ref.train_features, ref.train_labels, intervention=delta, mask=parameter_mask))
                actions.append(action.copy())
                steps.append(step)
                append_observation(k + 1)
                recovery["replayed_steps"] += 1
                if (step != resume["steps"][k]
                        or not np.array_equal(states[-1], resume["states"][k + 1])
                        or not np.array_equal(observations[-1], resume["observations"][k + 1])):
                    raise ValueError("paused prefix failed exact transition replay")
                budget()
            if current.digest() != previous["actual_state_sha256"]:
                raise ValueError("restored complete optimizer/sampler state differs")
        if arm != "retention_hinge_suffix":
            stage = "legacy_policy_build"
            policy = measured("legacy_policy_build", lambda: fit_controller(
                ref, mask=mask, mode="zero" if arm == "zero" else "full",
                target=legacy_target, effort_price=effort_price))
            budget()
        while len(actions) < stop_after:
            k, stage = len(actions), "policy_decision"
            budget()
            displacement = (current.vector() - ref.states[k]) / ref.scales
            if arm == "retention_hinge_suffix":
                try:
                    solved = measured("suffix_solve", lambda: solve_retention_tangent(
                        ref.A[k:], E[k:], ref.C[k:, :2], target[k:], ref.dt, effort_price,
                        initial=displacement, old_weight=old_weight,
                        max_iterations=limits.max_solver_iterations,
                        gradient_tolerance=limits.gradient_tolerance))
                except RetentionSolveError as error:
                    solves.append({"step": k, **error.receipt})
                    raise
                solves.append({"step": k, **solved["receipt"]})
                action = solved["actions"][0].copy()
                predicted_next = solved["states"][1]
            else:
                measured_state = displacement if arm != "zero" else np.zeros(policy.Cobs.shape[1])
                action = measured("legacy_action", lambda: policy.action(k, measured_state))
                predicted_next = ref.A[k] @ displacement + E[k] @ action
            delta = ref.dt * B @ action
            decision = {"step": k, "action_sha256": _hash_array(action),
                        "action_l2": _norm(action), "physical_intervention_l2": _norm(delta),
                        "applied": False}
            decisions.append(decision)
            budget()
            if (not np.isfinite(action).all() or not np.isfinite(delta).all()
                    or decision["action_l2"] > limits.max_action_l2
                    or decision["physical_intervention_l2"] > limits.max_intervention_l2):
                raise ValueError("action exceeded predeclared guard; no clipping or fallback")
            stage = "actual_nonlinear_transition"
            step = measured("actual_transition", lambda: current.advance(
                ref.train_features, ref.train_labels, intervention=delta, mask=parameter_mask))
            actions.append(action.copy())
            steps.append(step)
            decision["applied"] = True
            decision["actual_state_sha256"] = current.digest()
            append_observation(k + 1)
            decision["scaled_one_step_prediction_error_l2"] = _norm(
                (states[-1] - ref.states[k + 1]) / ref.scales - predicted_next)
            budget()
        if initial_digest != state.digest() or contract["reference"] != _reference_id(ref):
            raise ValueError("common initial state or frozen reference was mutated")
        if stop_after < ref.horizon:
            return snapshot("paused")
        stage = "separate_objective_scoring"
        fields = np.asarray(observations)[:, :2] - ref.observations[:, :2]
        path = np.asarray(actions)
        costs = measured("objective_diagnostics", lambda: {
            "optional_one_sided": retention_cost(fields, path, target, ref.dt,
                                                  effort_price, old_weight=old_weight),
            "legacy_quadratic": quadratic_cost(fields, path, legacy_target, ref.dt, effort_price)})
        if not all(math.isfinite(v) for group in costs.values() for v in group.values()):
            raise ValueError("nonfinite explicitly named objective score")
        budget()
        return snapshot("completed", costs=costs)
    except (ValueError, ArithmeticError, np.linalg.LinAlgError,
            RetentionSolveError, KeyError, TypeError) as error:
        result = snapshot("failed", error={"type": type(error).__name__, "message": str(error)})
        raise RetentionRunError(str(error), result) from error
