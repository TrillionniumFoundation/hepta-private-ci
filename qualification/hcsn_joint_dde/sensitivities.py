"""First-order variational DDE for the finite CTMC/delay candidate.

The initial relative-coordinate law and phase packets are held fixed. Physical
coordinates are log boundary B, log drift mu, sigma, absolute reset Vr and q.
Only reset distance log(Vr)-B carries B/Vr dependence in this fixed-prior API.
There is no episode-initial-prior derivative or continuum accuracy claim.
"""

from fractions import Fraction
import math

import numpy as np
from scipy.integrate import solve_ivp
from scipy.sparse import block_diag, bmat, csr_matrix

from qualification.hcsn_joint_dde.model import JointModel
from qualification.hcsn_boundary_audit.spatial_generator import KilledSpatialGenerator


PARAMETERS = ("log_boundary", "mu", "sigma", "absolute_reset", "discount")


def _check_sensitivity_shape(model, content):
    marked = np.asarray(content)
    if marked.ndim != 2 or not 1 <= marked.shape[1] <= 16:
        raise ValueError("one to sixteen fixed signed channels required")
    cells, channels = model.spatial.intervals + 5, marked.shape[1] + 1
    if 6 * cells * channels > 32768 or 20 * cells * cells > 12_000_000:
        raise ValueError("declared augmented-state/dense-coefficient budget exceeded")


def solve_partials(model, query_times, active, content, phase=(), **options):
    """The uniform-grid physical Jacobian; other geometry must opt in separately."""
    if (
        type(model) is not JointModel
        or type(model.spatial) is not KilledSpatialGenerator
    ):
        raise ValueError(
            "this qualified Jacobian requires the frozen uniform JointModel"
        )
    _check_sensitivity_shape(model, content)
    count, h = model.spatial.intervals, model.spatial.spacing
    full = np.zeros((5, count + 1, count + 1))
    indices = np.arange(1, count)
    full[1, indices, indices - 1] = -1 / (2 * h)
    full[1, indices, indices + 1] = 1 / (2 * h)
    full[2, indices, indices - 1] = model.spatial.sigma / h**2
    full[2, indices, indices + 1] = model.spatial.sigma / h**2
    full[2, indices, indices] = -2 * model.spatial.sigma / h**2
    nodes = np.arange(count + 1) * h
    return _solve_variational(
        model, query_times, active, content, phase, nodes=nodes, full=full, **options
    )


def _solve_variational(
    model,
    query_times,
    active,
    content,
    phase=(),
    *,
    nodes,
    full,
    log_boundary=0.0,
    absolute_reset=None,
    rtol=2e-10,
    atol=2e-12,
    max_step=None,
):
    """Return primal and all five physical partials under fixed initial laws.

    Reset interpolation is piecewise affine. Two-sided partials at reset knots
    and at zero central jump rates are refused, not supplied with a surrogate.
    """
    if (
        isinstance(log_boundary, bool)
        or not isinstance(log_boundary, (int, float))
        or not math.isfinite(log_boundary)
    ):
        raise ValueError("finite log boundary required")
    try:
        vr = (
            math.exp(model.reset + log_boundary)
            if absolute_reset is None
            else absolute_reset
        )
    except OverflowError as error:
        raise ValueError("physical reset mapping is numerically unresolved") from error
    if (
        isinstance(vr, bool)
        or not isinstance(vr, (int, float))
        or not math.isfinite(vr)
        or vr <= 0
        or abs(math.log(vr) - log_boundary - model.reset) > 2e-13
    ):
        raise ValueError("absolute reset and boundary must identify this model")
    left_node = int(np.searchsorted(nodes, model.reset, side="right")) - 1
    h = nodes[left_node + 1] - nodes[left_node]
    fraction = (model.reset - nodes[left_node]) / h
    down, up = model.spatial.rates
    if min(np.min(down), np.min(up)) <= 0 or min(fraction, 1 - fraction) <= 1e-8:
        raise ValueError("two-sided partials need positive rates and an off-knot reset")
    # Reuse the candidate's actual input/packet validation without taking a step.
    initial = model.solve(
        [0.0], active, content, phase, rtol=rtol, atol=atol, max_step=max_step
    )["rows"][0]
    times = np.asarray(query_times, dtype=float)
    if (
        times.ndim != 1
        or not 1 <= len(times) <= 4096
        or not np.all(np.isfinite(times))
        or np.any(times < 0)
        or np.any(np.diff(times) <= 0)
        or times[-1] > 8
        or times[-1] / model.delay > 4094
        or (len(times) + 2 * len(phase) + 1) * (int(times[-1] / model.delay) + 2)
        > 16384
    ):
        raise ValueError("query/history budget or time domain differs")
    max_step = model.delay / 8 if max_step is None else float(max_step)
    transient, lower, upper, reset = model.ingredients()
    n, channels = len(lower), np.asarray(content).shape[1] + 1
    size = n + 6
    state = np.zeros((6, channels, size))
    state[0, :, :n] = initial["active"].T
    for offset, name in enumerate(
        (
            "upper",
            "refractory",
            "events",
            "discounted_events",
            "discounted_active_time",
            "discounted_remaining_phase",
        )
    ):
        state[0, :, n + offset] = initial[name]
    dr = np.zeros((5, n))
    reset_slope = np.zeros(model.spatial.intervals + 1)
    reset_slope[left_node], reset_slope[left_node + 1] = -1 / h, 1 / h
    try:
        with np.errstate(over="raise", divide="raise", invalid="raise"):
            dr[0], dr[3] = -reset_slope[1:-1], reset_slope[1:-1] / vr
    except FloatingPointError as error:
        raise ValueError(
            "physical reset derivative is numerically unresolved"
        ) from error
    if not np.all(np.isfinite(dr)):
        raise ValueError("physical reset derivative is nonfinite")
    dq = np.zeros(5)
    dq[4] = 1
    derivative_q = np.zeros((5, n, n))
    derivative_lower, derivative_upper = np.zeros((5, n)), np.zeros((5, n))
    derivative_q[:] = full[:, 1:-1, 1:-1]
    derivative_lower[:], derivative_upper[:] = full[:, 1:-1, 0], full[:, 1:-1, -1]
    linear = np.zeros((size, size))
    linear[:n, :n] = transient.T
    linear[n, :n], linear[n + 1, :n], linear[n + 2, :n] = upper, lower, lower
    eta = math.exp(-model.discount * model.delay)
    linear[n + 5, :n], linear[n + 5, n + 5] = eta * lower, model.discount
    dl = np.zeros((5, size, size))
    for j in range(5):
        dl[j, :n, :n] = derivative_q[j].T
        dl[j, n, :n] = derivative_upper[j]
        dl[j, n + 1, :n] = dl[j, n + 2, :n] = derivative_lower[j]
        dl[j, n + 5, :n] = eta * (derivative_lower[j] - model.delay * dq[j] * lower)
        dl[j, n + 5, n + 5] = dq[j]
    uniform, atoms = [], {}
    base_knots = [0.0, *times]
    quadrature_nodes, quadrature_weights = np.polynomial.legendre.leggauss(32)
    for packet in phase:
        vector = np.r_[float(packet.mass), np.asarray(packet.content, dtype=float)]
        a, b = float(packet.start), float(packet.end)
        base_knots.extend((a, b))
        if a == b:
            state[5, :, n + 5] -= a * math.exp(-model.discount * a) * vector
            if a == 0:
                state[1, :, :n] += vector[:, None] * dr[0]
                state[4, :, :n] += vector[:, None] * dr[3]
            else:
                atoms[a] = atoms.get(a, np.zeros(channels)) + vector
        else:
            nodes = a + (b - a) * (quadrature_nodes + 1) / 2
            derivative = -0.5 * np.dot(
                quadrature_weights, nodes * np.exp(-model.discount * nodes)
            )
            state[5, :, n + 5] += derivative * vector
            uniform.append((a, b, vector / (b - a)))
    knots = {Fraction(0), Fraction(str(float(times[-1])))}
    for base in base_knots:
        for k in range(int(times[-1] / model.delay) + 2):
            value = Fraction(str(base)) + k * Fraction(str(model.delay))
            if 0 <= value <= Fraction(str(float(times[-1]))):
                knots.add(value)
    knots = list(map(float, sorted(knots)))
    if len(knots) * 6 * channels * size > 2_000_000:
        raise ValueError("declared snapshot/history budget exceeded")
    history, snapshots, steps = [], {}, 0
    support = linear.copy()
    support[n + 3, :n] = 1
    support[n + 4, : n + 1] = 1
    self_support = block_diag([csr_matrix(support != 0)] * channels, format="csr")
    blocks = [[None] * 6 for _ in range(6)]
    for j in range(6):
        blocks[j][j] = self_support
        if j:
            # Delayed flux and source release are known history/forcing in
            # each method-of-steps segment, not instantaneous state couplings.
            # The remaining primal-to-partial coupling is d(linear)/dtheta,
            # plus the two explicitly overwritten discounted integrators.
            cross_support = dl[j - 1] != 0
            cross_support[n + 3, :n] = (derivative_lower[j - 1] != 0) | (
                (dq[j - 1] != 0) & (lower != 0)
            )
            cross_support[n + 4, : n + 1] = dq[j - 1] != 0
            blocks[j][0] = block_diag(
                [csr_matrix(cross_support)] * channels, format="csr"
            )
    sparsity = bmat(blocks, format="csr")
    if sparsity.nnz > 2_000_000:
        raise ValueError("declared actual sparse-Jacobian nonzero budget exceeded")

    def instantaneous_jacobian(time, unused_state):
        exponential = math.exp(-model.discount * time)
        current_linear = linear.copy()
        current_linear[n + 3, :n] = exponential * lower
        current_linear[n + 4, : n + 1] = exponential
        diagonal = block_diag([csr_matrix(current_linear)] * channels, format="csr")
        values = [[None] * 6 for _ in range(6)]
        for j in range(6):
            values[j][j] = diagonal
            if j:
                coupling = dl[j - 1].copy()
                coupling[n + 3, :n] = exponential * (
                    derivative_lower[j - 1] - time * dq[j - 1] * lower
                )
                coupling[n + 4, : n + 1] = -time * dq[j - 1] * exponential
                values[j][0] = block_diag(
                    [csr_matrix(coupling)] * channels, format="csr"
                )
        result = bmat(values, format="csr")
        if not np.all(np.isfinite(result.data)):
            raise ArithmeticError("instantaneous Jacobian is nonfinite")
        return result

    initial_flux = state[:, :, :n] @ lower
    initial_flux[1:] += np.einsum("cn,jn->jc", state[0, :, :n], derivative_lower)

    def past_flux(time):
        if time < 0:
            return np.zeros((6, channels))
        for a, b, dense in reversed(history):
            if a <= time <= b:
                past = dense(time).reshape(6, channels, size)
                hit = past[:, :, :n] @ lower
                hit[1:] += np.einsum("cn,jn->jc", past[0, :, :n], derivative_lower)
                return hit
        if time == 0:
            return initial_flux.copy()
        raise ArithmeticError("missing delayed sensitivity history")

    for i, left in enumerate(knots):
        if left in atoms:
            vector = atoms[left]
            state[0, :, :n] += vector[:, None] * reset
            state[0, :, n + 1] -= vector
            state[0, :, n + 5] -= vector
            for j in range(5):
                state[j + 1, :, :n] += vector[:, None] * dr[j]
        snapshots[left] = state.copy()
        if i == len(knots) - 1:
            break
        right = knots[i + 1]
        midpoint = (left + right) / 2
        source = sum(
            (v for a, b, v in uniform if a <= midpoint < b), np.zeros(channels)
        )

        def rhs(time, flat):
            current = flat.reshape(6, channels, size)
            hit = current[:, :, :n] @ lower
            hit[1:] += np.einsum("cn,jn->jc", current[0, :, :n], derivative_lower)
            release = past_flux(min(time, np.nextafter(right, left)) - model.delay)
            release[0] += source
            result = current @ linear.T
            for j in range(5):
                result[j + 1] += current[0] @ dl[j].T
            result[:, :, :n] += release[:, :, None] * reset
            for j in range(5):
                result[j + 1, :, :n] += release[0, :, None] * dr[j]
            result[:, :, n + 1] -= release
            result[:, :, n + 5] -= release
            exponential = math.exp(-model.discount * time)
            result[:, :, n + 3] = exponential * hit
            occupation = current[:, :, :n].sum(2) + current[:, :, n]
            result[:, :, n + 4] = exponential * occupation
            result[5, :, n + 3] -= time * exponential * hit[0]
            result[5, :, n + 4] -= time * exponential * occupation[0]
            return result.ravel()

        integration = solve_ivp(
            rhs,
            (left, right),
            state.ravel(),
            method="BDF",
            rtol=rtol,
            atol=atol,
            max_step=max_step,
            jac=instantaneous_jacobian,
            dense_output=True,
        )
        if not integration.success or not np.all(np.isfinite(integration.y)):
            raise ArithmeticError("variational DDE failed")
        history.append((left, right, integration.sol))
        state = integration.y[:, -1].reshape(6, channels, size)
        steps += len(integration.t) - 1
    rows = []
    for time in times:
        value = snapshots[float(time)]
        if not np.all(np.isfinite(value)):
            raise ArithmeticError("returned primal or physical partial is nonfinite")
        fields = {"active": value[:, :, :n].transpose(0, 2, 1)}
        for offset, name in enumerate(
            (
                "upper",
                "refractory",
                "events",
                "discounted_events",
                "discounted_active_time",
                "discounted_remaining_phase",
            )
        ):
            fields[name] = value[:, :, n + offset]
        rows.append(
            dict(
                time=float(time),
                primal={k: v[0] for k, v in fields.items()},
                partials={
                    name: {k: v[j + 1] for k, v in fields.items()}
                    for j, name in enumerate(PARAMETERS)
                },
            )
        )
    return dict(
        rows=rows,
        parameters=PARAMETERS,
        internal_steps=steps,
        fixed_initial_relative_law=True,
        episode_prior_gradients=False,
        reset_semantics="piecewise_affine_fixed_stencil",
        augmented_state_scalars=6 * channels * size,
        instantaneous_jacobian_nonzeros=int(sparsity.nnz),
        instantaneous_jacobian_shape=list(sparsity.shape),
        rtol=rtol,
        atol=atol,
    )
