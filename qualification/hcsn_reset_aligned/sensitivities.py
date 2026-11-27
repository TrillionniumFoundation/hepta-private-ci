"""Variational DDE for the exact-reset moving-mesh discretization.

The five analytic generator derivatives include every mesh-rate change.
Initial nodal weights and exact phase supports are held fixed. This propagates
all delayed sensitivity histories, without a detached-history shortcut.
"""

from fractions import Fraction
import math

import numpy as np
from scipy.integrate import solve_ivp
from scipy.sparse import block_diag, bmat, csr_matrix

from qualification.hcsn_joint_dde.model import JointModel


PARAMETERS = ("log_boundary", "mu", "sigma", "absolute_reset", "discount")


def solve_aligned_partials(model, derivative_generator, query_times, active, content, phase=(), *,
                           rtol=2e-10, atol=2e-12, max_step=None):
    """First-order physical derivatives at fixed moving-nodal initial weights."""
    if not isinstance(model, JointModel):
        raise ValueError("JointModel required")
    full = np.asarray(derivative_generator, dtype=float)
    if full.shape != (5, model.spatial.intervals+1, model.spatial.intervals+1) or not np.isfinite(full).all():
        raise ValueError("five finite analytic generator Jacobians required")
    reset = model.ingredients()[3]
    if np.count_nonzero(reset) != 1 or reset.max() != 1:
        raise ValueError("reset must be an exact mesh node")
    # Reuse the candidate's actual input/packet validation without taking a step.
    initial = model.solve([0.], active, content, phase, rtol=rtol, atol=atol,
                          max_step=max_step)["rows"][0]
    times = np.asarray(query_times, dtype=float)
    if (times.ndim != 1 or not 1 <= len(times) <= 4096 or not np.all(np.isfinite(times))
            or np.any(times < 0) or np.any(np.diff(times) <= 0) or times[-1] > 8
            or times[-1] / model.delay > 4094
            or (len(times)+2*len(phase)+1)*(int(times[-1]/model.delay)+2) > 16384):
        raise ValueError("query/history budget or time domain differs")
    max_step = model.delay / 8 if max_step is None else float(max_step)
    transient, lower, upper, reset = model.ingredients()
    n, channels = len(lower), np.asarray(content).shape[1]+1
    size = n+6
    state = np.zeros((6, channels, size))
    state[0, :, :n] = initial["active"].T
    for offset, name in enumerate(("upper", "refractory", "events", "discounted_events",
                                    "discounted_active_time", "discounted_remaining_phase")):
        state[0, :, n+offset] = initial[name]
    dr = np.zeros((5, n))  # Reset index is fixed while its physical node moves.
    dq = np.zeros(5)
    dq[4] = 1
    derivative_q = full[:, 1:-1, 1:-1]
    derivative_lower, derivative_upper = full[:, 1:-1, 0], full[:, 1:-1, -1]
    linear = np.zeros((size, size))
    linear[:n, :n] = transient.T
    linear[n, :n], linear[n+1, :n], linear[n+2, :n] = upper, lower, lower
    eta = math.exp(-model.discount*model.delay)
    linear[n+5, :n], linear[n+5, n+5] = eta*lower, model.discount
    dl = np.zeros((5, size, size))
    for j in range(5):
        dl[j, :n, :n] = derivative_q[j].T
        dl[j, n, :n] = derivative_upper[j]
        dl[j, n+1, :n] = dl[j, n+2, :n] = derivative_lower[j]
        dl[j, n+5, :n] = eta*(derivative_lower[j]-model.delay*dq[j]*lower)
        dl[j, n+5, n+5] = dq[j]
    uniform, atoms = [], {}
    base_knots = [0., *times]
    quadrature_nodes, quadrature_weights = np.polynomial.legendre.leggauss(32)
    for packet in phase:
        vector = np.r_[float(packet.mass), np.asarray(packet.content, dtype=float)]
        a, b = float(packet.start), float(packet.end)
        base_knots.extend((a, b))
        if a == b:
            state[5, :, n+5] -= a*math.exp(-model.discount*a)*vector
            if a == 0:
                state[1, :, :n] += vector[:, None]*dr[0]
                state[4, :, :n] += vector[:, None]*dr[3]
            else:
                atoms[a] = atoms.get(a, np.zeros(channels))+vector
        else:
            nodes = a+(b-a)*(quadrature_nodes+1)/2
            derivative = -.5*np.dot(quadrature_weights, nodes*np.exp(-model.discount*nodes))
            state[5, :, n+5] += derivative*vector
            uniform.append((a, b, vector/(b-a)))
    knots = {Fraction(0), Fraction(str(float(times[-1])))}
    for base in base_knots:
        for k in range(int(times[-1]/model.delay)+2):
            value = Fraction(str(base))+k*Fraction(str(model.delay))
            if 0 <= value <= Fraction(str(float(times[-1]))):
                knots.add(value)
    knots = list(map(float, sorted(knots)))
    history, snapshots, steps = [], {}, 0
    support = linear.copy()
    support[n+3, :n] = 1
    support[n+4, :n+1] = 1
    self_support = block_diag([csr_matrix(support != 0)]*channels, format="csr")
    # Conservative same-channel primal-to-partial blocks, no cross-mark mixing.
    cross = block_diag([csr_matrix(np.ones((size, size)))]*channels, format="csr")
    blocks = [[None]*6 for _ in range(6)]
    for j in range(6):
        blocks[j][j] = self_support
        if j:
            blocks[j][0] = cross
    sparsity = bmat(blocks, format="csr")
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
            state[0, :, :n] += vector[:, None]*reset
            state[0, :, n+1] -= vector
            state[0, :, n+5] -= vector
            for j in range(5):
                state[j+1, :, :n] += vector[:, None]*dr[j]
        snapshots[left] = state.copy()
        if i == len(knots)-1:
            break
        right = knots[i+1]
        midpoint = (left+right)/2
        source = sum((v for a, b, v in uniform if a <= midpoint < b), np.zeros(channels))

        def rhs(time, flat):
            current = flat.reshape(6, channels, size)
            hit = current[:, :, :n] @ lower
            hit[1:] += np.einsum("cn,jn->jc", current[0, :, :n], derivative_lower)
            release = past_flux(min(time, np.nextafter(right, left))-model.delay)
            release[0] += source
            result = current @ linear.T
            for j in range(5):
                result[j+1] += current[0] @ dl[j].T
            result[:, :, :n] += release[:, :, None]*reset
            for j in range(5):
                result[j+1, :, :n] += release[0, :, None]*dr[j]
            result[:, :, n+1] -= release
            result[:, :, n+5] -= release
            exponential = math.exp(-model.discount*time)
            result[:, :, n+3] = exponential*hit
            occupation = current[:, :, :n].sum(2)+current[:, :, n]
            result[:, :, n+4] = exponential*occupation
            result[5, :, n+3] -= time*exponential*hit[0]
            result[5, :, n+4] -= time*exponential*occupation[0]
            return result.ravel()

        integration = solve_ivp(rhs, (left, right), state.ravel(), method="BDF", rtol=rtol,
                                atol=atol, max_step=max_step, jac_sparsity=sparsity,
                                dense_output=True)
        if not integration.success or not np.all(np.isfinite(integration.y)):
            raise ArithmeticError("variational DDE failed")
        history.append((left, right, integration.sol))
        state = integration.y[:, -1].reshape(6, channels, size)
        steps += len(integration.t)-1
    rows = []
    for time in times:
        value = snapshots[float(time)]
        fields = {"active": value[:, :, :n].transpose(0, 2, 1)}
        for offset, name in enumerate(("upper", "refractory", "events", "discounted_events",
                                      "discounted_active_time", "discounted_remaining_phase")):
            fields[name] = value[:, :, n+offset]
        rows.append(dict(time=float(time), primal={k: v[0] for k, v in fields.items()},
                         partials={name: {k: v[j+1] for k, v in fields.items()}
                                   for j, name in enumerate(PARAMETERS)}))
    return dict(rows=rows, parameters=PARAMETERS, internal_steps=steps,
                fixed_initial_moving_nodal_law=True, physical_prior_geometry_gradients=False,
                reset_semantics="exact_point_at_moving_node", rtol=rtol, atol=atol)
