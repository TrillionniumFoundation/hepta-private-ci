"""Prototype continuous-time finite-DDE initial-amplitude adjoint.

This is not reverse differentiation of an adaptive BDF program. The fixed
finite delay equation has its own adjoint, numerically integrated backward in
physical time by a retarded method of steps. No Torch API or optimizer is here.
"""

from bisect import bisect_left
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
import time

import numpy as np
from scipy.integrate import BDF
from scipy.sparse import block_diag, csr_matrix

from qualification.hcsn_boundary_audit.spatial_generator import KilledSpatialGenerator
from qualification.hcsn_graded.model import GradedJointModel
from qualification.hcsn_graded.spatial import GradedSpatialGenerator
from qualification.hcsn_joint_dde.model import JointModel


MAX_STEPS = 4096
MAX_RHS = 100000
MAX_STORED_SCALARS = 1000000
MAX_QUADRATURE_EVALUATIONS = 250000


def _rational(value):
    if isinstance(value, bool) or not isinstance(
        value, (int, float, Fraction, np.integer, np.floating)
    ):
        raise ValueError("a finite fixed real time is required")
    if not math.isfinite(float(value)):
        raise ValueError("a finite fixed real time is required")
    return value if isinstance(value, Fraction) else Fraction(str(float(value)))


def _array(value):
    result = np.array(value, dtype=np.float64, copy=True, order="C")
    if not np.all(np.isfinite(result)):
        raise ValueError("nonfinite fixed coefficient")
    result.setflags(write=False)
    return result


def _identity(times, supports, transient, lower, upper, reset, nodes, delay, discount):
    metadata = dict(
        times=list(map(str, times)),
        supports=[list(map(str, p)) for p in supports],
        delay=str(delay),
        discount=discount,
    )
    digest = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode())
    for array in (transient, lower, upper, reset, nodes):
        digest.update(str(array.shape).encode())
        digest.update(array.tobytes())
    return digest.hexdigest()


@dataclass(frozen=True)
class FrozenProblem:
    times: tuple
    supports: tuple
    transient: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    reset: np.ndarray
    nodes: np.ndarray
    delay: Fraction
    discount: float
    identity: str

    @property
    def intervals(self):
        return len(self.lower) + 1


def freeze_problem(model, query_times, supports=()):
    """Copy actual geometry/physics/time/support values once, before a VJP.

    The numerical solver never reads the live model, caller time list or
    support containers afterward. A future custom backward must retain this
    forward-used snapshot, rather than re-freeze mutable metadata at backward.
    """
    uniform = (
        type(model) is JointModel and type(model.spatial) is KilledSpatialGenerator
    )
    graded = (
        type(model) is GradedJointModel
        and type(model.spatial) is GradedSpatialGenerator
    )
    if not (uniform or graded) or not 4 <= model.spatial.intervals <= 32:
        raise ValueError(
            "this new prototype admits only explicit small uniform/graded models"
        )
    if (
        not isinstance(query_times, (tuple, list, np.ndarray))
        or not 1 <= len(query_times) <= 5
    ):
        raise ValueError("one to five fixed query times required")
    times = tuple(map(_rational, query_times))
    delay, discount = _rational(model.delay), float(model.discount)
    if (
        delay <= 0
        or not 0.001 <= discount <= 4
        or times[0] < 0
        or any(b <= a for a, b in zip(times, times[1:]))
        or times[-1] > min(Fraction(3, 5), 3 * delay)
    ):
        raise ValueError("declared time/discount domain differs")
    if not isinstance(supports, (list, tuple)) or len(supports) > 8:
        raise ValueError("at most eight fixed phase supports required")
    fixed = []
    for pair in supports:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError("phase support pairs required")
        a, b = map(_rational, pair)
        if not 0 <= a <= b <= delay or (a < b and float(a) == float(b)):
            raise ValueError("phase support is invalid or numerically unresolved")
        fixed.append((a, b))
    transient, lower, upper, reset = map(_array, model.ingredients())
    n = len(lower)
    if transient.shape != (n, n) or upper.shape != (n,) or reset.shape != (n,):
        raise ValueError("fixed generator dimensions differ")
    if (
        np.min(lower) < 0
        or np.min(upper) < 0
        or np.min(reset) < 0
        or abs(reset.sum() - 1) > 1e-12
    ):
        raise ValueError("nonnegative exit/reset ingredients required")
    if max(np.max(abs(transient)), np.max(lower), np.max(upper)) > 1e8:
        raise ValueError("prototype coefficient magnitude budget exceeded")
    nodes = _array(
        model.spatial.nodes if graded else np.arange(n + 2) * model.spatial.spacing
    )
    identity = _identity(
        times, tuple(fixed), transient, lower, upper, reset, nodes, delay, discount
    )
    return FrozenProblem(
        times,
        tuple(fixed),
        transient,
        lower,
        upper,
        reset,
        nodes,
        delay,
        discount,
        identity,
    )


@dataclass
class _Segment:
    left: Fraction
    right: Fraction
    ends: list
    dense: list

    def value(self, time):
        time = min(float(self.right), max(float(self.left), float(time)))
        index = min(bisect_left(self.ends, time), len(self.dense) - 1)
        return self.dense[index](time)


class _Trajectory:
    def __init__(self, snapshots, segments, shape, stats):
        self.snapshots, self.segments, self.shape, self.stats = (
            snapshots,
            segments,
            shape,
            stats,
        )

    def after(self, exact_time):
        if exact_time in self.snapshots:
            return self.snapshots[exact_time]
        for segment in self.segments:
            if segment.left < exact_time < segment.right:
                value = float(exact_time)
                if not float(segment.left) < value < float(segment.right):
                    raise ValueError("atomic sampling side is numerically unresolved")
                return segment.value(value).reshape(self.shape)
        raise ArithmeticError("missing reverse sampling interval")


def _reverse_solve(
    times,
    delay,
    jumps,
    shape,
    instantaneous,
    jacobian,
    delayed,
    extra=(),
    *,
    rtol=2e-11,
    atol=2e-13,
    max_step=0.01,
):
    """Retarded reverse engine; negative reverse-time history is identically zero."""
    terminal = times[-1]
    state_size = int(np.prod(shape))
    if (
        not 1 <= state_size <= 185
        or not 1e-12 <= rtol <= 1e-3
        or not 1e-14 <= atol <= 1e-5
    ):
        raise ValueError("prototype state/error-control budget exceeded")
    if not math.isfinite(max_step) or not 0 < max_step <= float(delay):
        raise ValueError("positive max_step no greater than delay required")
    seeds = {Fraction(0), terminal, *jumps, *extra}
    knots = {Fraction(0), terminal}
    for base in seeds:
        for k in range(int(terminal / delay) + 2):
            value = base + k * delay
            if 0 <= value <= terminal:
                knots.add(value)
    knots = sorted(knots)
    if len(knots) > 64 or len(set(map(float, knots))) != len(knots):
        raise ValueError(
            "reverse breakpoint budget or floating-time resolution exceeded"
        )
    state = np.zeros(shape)
    snapshots, segments = {}, []
    counts = dict(
        internal_steps=0,
        rhs_evaluations=0,
        stored_scalars=0,
        maximum_current_jacobian_nonzeros=0,
        negative_history_zero=True,
    )
    for index, left in enumerate(knots):
        if left in jumps:
            state = state + jumps[left]
        if not np.all(np.isfinite(state)):
            raise ArithmeticError("nonfinite reverse jump state")
        snapshots[left] = state.copy()
        counts["stored_scalars"] += state_size
        if counts["stored_scalars"] > MAX_STORED_SCALARS:
            raise ValueError("adjoint dense/snapshot scalar budget exceeded")
        if index == len(knots) - 1:
            break
        right = knots[index + 1]
        midpoint = (left + right) / 2
        if not float(left) < float(midpoint) < float(right) or right - left > delay:
            raise ValueError("reverse step interval is unresolved or exceeds delay")
        past_mid = midpoint - delay
        past = None
        if past_mid >= 0:
            for candidate in segments:
                if candidate.left < past_mid < candidate.right:
                    past = candidate
                    break
            if past is None:
                raise ArithmeticError("reverse retarded history interval missing")

        def rhs(time, flat):
            counts["rhs_evaluations"] += 1
            if counts["rhs_evaluations"] > MAX_RHS:
                raise ValueError("reverse RHS evaluation budget exceeded")
            value = flat.reshape(shape)
            result = instantaneous(time, value)
            if past is not None:
                result = result + delayed(
                    past.value(time - float(delay)).reshape(shape)
                )
            if not np.all(np.isfinite(result)):
                raise ArithmeticError("nonfinite reverse derivative")
            return result.ravel()

        def exact_jacobian(time, unused):
            matrix = jacobian(time)
            counts["maximum_current_jacobian_nonzeros"] = max(
                counts["maximum_current_jacobian_nonzeros"], matrix.nnz
            )
            if (
                matrix.shape != (state_size, state_size)
                or matrix.nnz > 10000
                or not np.all(np.isfinite(matrix.data))
            ):
                raise ValueError(
                    "reverse instantaneous sparse-Jacobian budget exceeded"
                )
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
                raise ValueError("reverse accepted-step budget exceeded")
            solver.step()
            if solver.status == "failed" or not np.all(np.isfinite(solver.y)):
                raise ArithmeticError("reverse BDF step failed")
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
                raise ValueError("reverse dense/snapshot scalar budget exceeded")
            counts["stored_scalars"] += payload
            counts["internal_steps"] += 1
            dense.append(interpolant)
            ends.append(solver.t)
        state = solver.y.reshape(shape).copy()
        segments.append(_Segment(left, right, ends, dense))
    counts["method_segments"] = len(segments)
    return _Trajectory(snapshots, segments, shape, counts)


def amplitude_vjp(problem, cotangent, *, rtol=2e-11, atol=2e-13, max_step=0.01):
    """VJP of the continuous finite DDE under a forward-used frozen snapshot.

    Cotangent shape [query,N+5,marks]; rows match all seven #6241 fields.
    The returned [N+K,marks] covers active nodes 1..N (including upper escape)
    then fixed-support phase amplitudes. No initial amplitude values are read.
    """
    if type(problem) is not FrozenProblem:
        raise ValueError(
            "a separately validated fixed coefficient snapshot is required"
        )
    if not 4 <= problem.intervals <= 32 or problem.identity != _identity(
        problem.times,
        problem.supports,
        problem.transient,
        problem.lower,
        problem.upper,
        problem.reset,
        problem.nodes,
        problem.delay,
        problem.discount,
    ):
        raise ValueError("frozen snapshot identity or small-grid admission differs")
    if any(
        value.flags.writeable
        for value in (
            problem.transient,
            problem.lower,
            problem.upper,
            problem.reset,
            problem.nodes,
        )
    ):
        raise ValueError("snapshot coefficient arrays must remain read-only")
    start, cpu = time.perf_counter(), time.process_time()
    cotangent = np.array(cotangent, dtype=float, copy=True, order="C")
    count, terminal = problem.intervals, problem.times[-1]
    n, size = count - 1, count + 5
    if (
        cotangent.ndim != 3
        or cotangent.shape[:2] != (len(problem.times), size)
        or not 1 <= cotangent.shape[2] <= 5
        or not np.all(np.isfinite(cotangent))
        or np.max(abs(cotangent)) > 1e6
    ):
        raise ValueError("bounded finite cotangent dimensions required")
    marks = cotangent.shape[2]
    base, discounted = np.zeros((size, size)), np.zeros((size, size))
    base[:n, :n] = problem.transient
    base[:n, n] = problem.upper
    base[:n, n + 1] = base[:n, n + 2] = problem.lower
    base[:n, n + 5] = math.exp(-problem.discount * float(problem.delay)) * problem.lower
    base[n + 5, n + 5] = problem.discount
    discounted[:n, n + 3] = problem.lower
    discounted[:n, n + 4] = 1
    discounted[n, n + 4] = 1
    base, discounted = csr_matrix(base), csr_matrix(discounted)

    def exponential(reverse_time):
        return math.exp(
            -problem.discount
            * max(0.0, min(float(terminal), float(terminal) - reverse_time))
        )

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

    jumps = {
        terminal - t: cotangent[index].T.copy() for index, t in enumerate(problem.times)
    }
    extra = tuple(
        terminal - edge
        for pair in problem.supports
        for edge in pair
        if edge <= terminal
    )
    trajectory = _reverse_solve(
        problem.times,
        problem.delay,
        jumps,
        (marks, size),
        instantaneous,
        jacobian,
        delayed,
        extra,
        rtol=rtol,
        atol=atol,
        max_step=max_step,
    )
    initial = trajectory.after(terminal)
    active = np.column_stack([initial[:, :n], initial[:, n]]).T
    phase = np.empty((len(problem.supports), marks))
    quadrature_evaluations, max_difference = 0, 0.0

    def pairing(value):
        return value[:, :n] @ problem.reset - value[:, n + 1] - value[:, n + 5]

    for index, (a, b) in enumerate(problem.supports):
        if a == b:
            z0 = math.exp(-problem.discount * float(a))
            release = (
                pairing(trajectory.after(terminal - a))
                if a <= terminal
                else np.zeros(marks)
            )
        else:
            width = float(b - a)
            z0 = (
                math.exp(-problem.discount * float(a))
                * (-math.expm1(-problem.discount * width))
                / (problem.discount * width)
            )
            integral = []
            for order in (3, 4):
                nodes, weights = np.polynomial.legendre.leggauss(order)
                result = np.zeros(marks)
                low, high = max(0.0, float(terminal - b)), float(terminal - a)
                if high > low:
                    for segment in trajectory.segments:
                        for dense in segment.dense:
                            left, right = max(low, dense.t_old), min(high, dense.t)
                            if left >= right:
                                continue
                            for point, weight in zip(
                                (left + right) / 2 + (right - left) * nodes / 2, weights
                            ):
                                quadrature_evaluations += 1
                                if quadrature_evaluations > MAX_QUADRATURE_EVALUATIONS:
                                    raise ValueError(
                                        "phase-pairing quadrature budget exceeded"
                                    )
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
                raise ArithmeticError(
                    "BDF polynomial phase integration is numerically unresolved"
                )
            release = integral[1]
        phase[index] = initial[:, n + 1] + z0 * initial[:, n + 5] + release
    result = np.vstack([active, phase])
    if not np.all(np.isfinite(result)):
        raise ArithmeticError("nonfinite initial-amplitude adjoint")
    if problem.identity != _identity(
        problem.times,
        problem.supports,
        problem.transient,
        problem.lower,
        problem.upper,
        problem.reset,
        problem.nodes,
        problem.delay,
        problem.discount,
    ):
        raise ValueError("snapshot identity changed during the adjoint")
    return dict(
        vjp=result,
        problem_identity=problem.identity,
        statistics=dict(
            **trajectory.stats,
            quadrature_evaluations=quadrature_evaluations,
            phase_polynomial_integration_disagreement=max_difference,
            wall_seconds=time.perf_counter() - start,
            cpu_seconds=time.process_time() - cpu,
        ),
        continuous_finite_dde_vjp=True,
        discrete_bdf_program_reverse=False,
        new_adjoint_calls=1,
        forward_basis_calls=0,
        optimizer_updates=0,
        torch_autograd_qualified=False,
        large_mesh_qualified=False,
    )
