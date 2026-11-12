"""Exact-scope N128 continuous finite-DDE initial-amplitude adjoint.

This is a separate one-law admission.  It does not widen the small-grid API in
``qualification.hcsn_initial_adjoint`` and is not a reverse pass through the
adaptive BDF instruction stream.
"""

import math
import time
from bisect import bisect_left
from fractions import Fraction

import numpy as np
from scipy.integrate import BDF
from scipy.sparse import block_diag, csr_matrix

from qualification.hcsn_graded.model import GradedJointModel
from qualification.hcsn_graded.spatial import GradedSpatialGenerator
from qualification.hcsn_initial_adjoint.solver import (
    FrozenProblem,
    _array,
    _identity,
)

INTERVALS = 128
QUERY_TIME = Fraction(1, 50)
DELAY = Fraction(1, 5)
DISCOUNT = 0.15
SUPPORTS = tuple((Fraction(j, 40), Fraction(j + 1, 40)) for j in range(8))
MAX_STEPS = 4096
MAX_RHS = 100000
MAX_STORED_SCALARS = 16000000
MAX_JACOBIAN_NONZEROS = 50000
MAX_QUADRATURE_EVALUATIONS = 250000


def freeze_n128_problem(model):
    """Freeze the sole admitted N128 geometry, physics and first-cycle query."""
    if (
        type(model) is not GradedJointModel
        or type(model.spatial) is not GradedSpatialGenerator
        or model.spatial.intervals != INTERVALS
        or model.spatial.endpoint != 8.0
        or model.spatial.mu != -0.11999999999999998
        or model.spatial.sigma != 0.35
        or model.spatial.stretch != 6.0
        or Fraction(str(model.delay)) != DELAY
        or model.discount != DISCOUNT
    ):
        raise ValueError("the exact original N128 fixed-physics model is required")
    transient, lower, upper, reset = map(_array, model.ingredients())
    nodes = _array(model.spatial.nodes)
    if (
        transient.shape != (127, 127)
        or lower.shape != (127,)
        or upper.shape != (127,)
        or reset.shape != (127,)
        or nodes.shape != (129,)
        or nodes[0] != 0
        or nodes[-1] != 8
        or np.min(lower) < 0
        or np.min(upper) < 0
        or np.min(reset) < 0
        or abs(reset.sum() - 1) > 1e-12
        or max(np.max(abs(transient)), np.max(lower), np.max(upper)) > 1e8
    ):
        raise ValueError("the exact original N128 generator dimensions differ")
    identity = _identity(
        (QUERY_TIME,),
        SUPPORTS,
        transient,
        lower,
        upper,
        reset,
        nodes,
        DELAY,
        DISCOUNT,
    )
    return FrozenProblem(
        (QUERY_TIME,),
        SUPPORTS,
        transient,
        lower,
        upper,
        reset,
        nodes,
        DELAY,
        DISCOUNT,
        identity,
    )


class _Segment:
    def __init__(self, left, right, ends, dense):
        self.left, self.right, self.ends, self.dense = left, right, ends, dense

    def value(self, when):
        when = min(float(self.right), max(float(self.left), float(when)))
        index = min(bisect_left(self.ends, when), len(self.dense) - 1)
        return self.dense[index](when)


class _Trajectory:
    def __init__(self, snapshots, segments, shape, statistics):
        self.snapshots = snapshots
        self.segments = segments
        self.shape = shape
        self.statistics = statistics

    def after(self, exact_time):
        if exact_time in self.snapshots:
            return self.snapshots[exact_time]
        for segment in self.segments:
            if segment.left < exact_time < segment.right:
                value = float(exact_time)
                if not float(segment.left) < value < float(segment.right):
                    raise ValueError("atomic sampling side is unresolved")
                return segment.value(value).reshape(self.shape)
        raise ArithmeticError("reverse sampling interval is missing")


def _reverse_solve(jumps, shape, instantaneous, jacobian, delayed, extra, options):
    terminal = QUERY_TIME
    rtol, atol, max_step = options
    state_size = int(np.prod(shape))
    if (
        state_size != 665
        or not 1e-12 <= rtol <= 1e-3
        or not 1e-14 <= atol <= 1e-5
        or not math.isfinite(max_step)
        or not 0 < max_step <= float(DELAY)
    ):
        raise ValueError("exact N128 reverse/error-control budget differs")
    seeds = {Fraction(0), terminal, *jumps, *extra}
    knots = {Fraction(0), terminal}
    for base in seeds:
        for k in range(int(terminal / DELAY) + 2):
            value = base + k * DELAY
            if 0 <= value <= terminal:
                knots.add(value)
    knots = sorted(knots)
    if len(knots) > 64 or len(set(map(float, knots))) != len(knots):
        raise ValueError("reverse breakpoint budget differs")
    state = np.zeros(shape)
    snapshots, segments = {}, []
    counts = {
        "internal_steps": 0,
        "rhs_evaluations": 0,
        "stored_scalars": 0,
        "maximum_current_jacobian_nonzeros": 0,
        "negative_history_zero": True,
    }
    for index, left in enumerate(knots):
        if left in jumps:
            state = state + jumps[left]
        if not np.all(np.isfinite(state)):
            raise ArithmeticError("nonfinite reverse jump state")
        snapshots[left] = state.copy()
        counts["stored_scalars"] += state_size
        if counts["stored_scalars"] > MAX_STORED_SCALARS:
            raise ValueError("N128 adjoint retained-scalar budget exceeded")
        if index == len(knots) - 1:
            break
        right = knots[index + 1]
        midpoint = (left + right) / 2
        if not float(left) < float(midpoint) < float(right) or right - left > DELAY:
            raise ValueError("reverse step interval differs")
        past_mid = midpoint - DELAY
        past = None
        if past_mid >= 0:
            for candidate in segments:
                if candidate.left < past_mid < candidate.right:
                    past = candidate
                    break
            if past is None:
                raise ArithmeticError("reverse retarded history is missing")
        past_segment = past

        def rhs(when, flat, _past=past_segment):
            counts["rhs_evaluations"] += 1
            if counts["rhs_evaluations"] > MAX_RHS:
                raise ValueError("N128 reverse RHS budget exceeded")
            current = flat.reshape(shape)
            result = instantaneous(when, current)
            if _past is not None:
                result = result + delayed(
                    _past.value(when - float(DELAY)).reshape(shape)
                )
            if not np.all(np.isfinite(result)):
                raise ArithmeticError("nonfinite reverse derivative")
            return result.ravel()

        def exact_jacobian(when, unused):
            matrix = jacobian(when)
            counts["maximum_current_jacobian_nonzeros"] = max(
                counts["maximum_current_jacobian_nonzeros"], matrix.nnz
            )
            if (
                matrix.shape != (state_size, state_size)
                or matrix.nnz > MAX_JACOBIAN_NONZEROS
                or not np.all(np.isfinite(matrix.data))
            ):
                raise ValueError("N128 sparse-Jacobian budget exceeded")
            return matrix

        solver = BDF(
            rhs,
            float(left),
            state.ravel(),
            float(right),
            jac=exact_jacobian,
            rtol=rtol,
            atol=atol,
            max_step=max_step,
        )
        dense, ends = [], []
        while solver.status == "running":
            if counts["internal_steps"] >= MAX_STEPS:
                raise ValueError("N128 reverse accepted-step budget exceeded")
            solver.step()
            if solver.status == "failed" or not np.all(np.isfinite(solver.y)):
                raise ArithmeticError("N128 reverse BDF step failed")
            interpolant = solver.dense_output()
            if not 1 <= interpolant.order <= 5 or interpolant.D.shape != (
                interpolant.order + 1,
                state_size,
            ):
                raise ValueError("unsupported BDF dense polynomial layout")
            payload = (
                interpolant.D.size + interpolant.t_shift.size + interpolant.denom.size
            )
            if counts["stored_scalars"] + payload > MAX_STORED_SCALARS:
                raise ValueError("N128 adjoint retained-scalar budget exceeded")
            counts["stored_scalars"] += payload
            counts["internal_steps"] += 1
            dense.append(interpolant)
            ends.append(solver.t)
        state = solver.y.reshape(shape).copy()
        segments.append(_Segment(left, right, ends, dense))
    counts["method_segments"] = len(segments)
    return _Trajectory(snapshots, segments, shape, counts)


def amplitude_vjp_n128(problem, cotangent, *, options):
    """Return the 128 active plus eight phase-amplitude VJP rows."""
    expected_identity = _identity(
        (QUERY_TIME,),
        SUPPORTS,
        problem.transient,
        problem.lower,
        problem.upper,
        problem.reset,
        problem.nodes,
        DELAY,
        DISCOUNT,
    )
    if (
        type(problem) is not FrozenProblem
        or problem.intervals != INTERVALS
        or problem.times != (QUERY_TIME,)
        or problem.supports != SUPPORTS
        or problem.identity != expected_identity
        or any(
            value.flags.writeable
            for value in (
                problem.transient,
                problem.lower,
                problem.upper,
                problem.reset,
                problem.nodes,
            )
        )
    ):
        raise ValueError("the frozen original N128 snapshot differs")
    started, cpu = time.perf_counter(), time.process_time()
    cotangent = np.array(cotangent, dtype=float, copy=True, order="C")
    n, size, marks = 127, 133, 5
    if (
        cotangent.shape != (1, size, marks)
        or not np.all(np.isfinite(cotangent))
        or np.max(abs(cotangent)) > 1e6
    ):
        raise ValueError("the exact bounded N128 cotangent differs")
    base, discounted = np.zeros((size, size)), np.zeros((size, size))
    base[:n, :n] = problem.transient
    base[:n, n] = problem.upper
    base[:n, n + 1] = base[:n, n + 2] = problem.lower
    base[:n, n + 5] = math.exp(-DISCOUNT * float(DELAY)) * problem.lower
    base[n + 5, n + 5] = DISCOUNT
    discounted[:n, n + 3] = problem.lower
    discounted[:n, n + 4] = 1
    discounted[n, n + 4] = 1
    base, discounted = csr_matrix(base), csr_matrix(discounted)

    def exponential(reverse_time):
        return math.exp(-DISCOUNT * max(0.0, float(QUERY_TIME) - reverse_time))

    def instantaneous(reverse_time, current):
        return (base @ current.T).T + exponential(reverse_time) * (
            discounted @ current.T
        ).T

    def jacobian(reverse_time):
        current = base + exponential(reverse_time) * discounted
        return block_diag([current] * marks, format="csr")

    def delayed(past):
        pairing = past[:, :n] @ problem.reset - past[:, n + 1] - past[:, n + 5]
        result = np.zeros_like(past)
        result[:, :n] = pairing[:, None] * problem.lower
        return result

    jumps = {Fraction(0): cotangent[0].T.copy()}
    extra = tuple(
        QUERY_TIME - edge for pair in SUPPORTS for edge in pair if edge <= QUERY_TIME
    )
    trajectory = _reverse_solve(
        jumps,
        (marks, size),
        instantaneous,
        jacobian,
        delayed,
        extra,
        options,
    )
    initial = trajectory.after(QUERY_TIME)
    active = np.column_stack([initial[:, :n], initial[:, n]]).T
    phase = np.empty((len(SUPPORTS), marks))
    quadrature_evaluations, max_difference = 0, 0.0

    def pairing(value):
        return value[:, :n] @ problem.reset - value[:, n + 1] - value[:, n + 5]

    for index, (a, b) in enumerate(SUPPORTS):
        width = float(b - a)
        z0 = (
            math.exp(-DISCOUNT * float(a))
            * (-math.expm1(-DISCOUNT * width))
            / (DISCOUNT * width)
        )
        integral = []
        for order in (3, 4):
            nodes, weights = np.polynomial.legendre.leggauss(order)
            result = np.zeros(marks)
            low, high = max(0.0, float(QUERY_TIME - b)), float(QUERY_TIME - a)
            if high > low:
                for segment in trajectory.segments:
                    for dense in segment.dense:
                        left, right = max(low, dense.t_old), min(high, dense.t)
                        if left >= right:
                            continue
                        for point, weight in zip(
                            (left + right) / 2 + (right - left) * nodes / 2,
                            weights,
                        ):
                            quadrature_evaluations += 1
                            if quadrature_evaluations > MAX_QUADRATURE_EVALUATIONS:
                                raise ValueError("phase quadrature budget exceeded")
                            result += (
                                (right - left)
                                * weight
                                * pairing(dense(point).reshape(marks, size))
                                / 2
                            )
            integral.append(result / width)
        difference = np.max(abs(integral[0] - integral[1]))
        max_difference = max(max_difference, float(difference))
        if np.any(abs(integral[0] - integral[1]) > 1e-10 + 1e-8 * abs(integral[1])):
            raise ArithmeticError("phase integration is unresolved")
        phase[index] = initial[:, n + 1] + z0 * initial[:, n + 5] + integral[1]
    result = np.vstack([active, phase])
    if not np.all(np.isfinite(result)) or result.shape != (136, 5):
        raise ArithmeticError("nonfinite N128 initial-amplitude adjoint")
    if problem.identity != expected_identity:
        raise ValueError("N128 frozen snapshot changed during adjoint")
    return {
        "vjp": result,
        "problem_identity": problem.identity,
        "statistics": dict(
            **trajectory.statistics,
            quadrature_evaluations=quadrature_evaluations,
            phase_polynomial_integration_disagreement=max_difference,
            wall_seconds=time.perf_counter() - started,
            cpu_seconds=time.process_time() - cpu,
        ),
        "continuous_finite_dde_vjp": True,
        "discrete_bdf_program_reverse": False,
        "new_adjoint_calls": 1,
        "forward_basis_calls": 0,
        "optimizer_updates": 0,
        "large_mesh_qualified": False,
        "fullnetwork_qualified": False,
    }
