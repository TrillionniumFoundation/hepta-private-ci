"""Pure NumPy first-order chain reference for the two-layer boundary candidate.

No PyTorch, financial-kernel loading, temporal integration or parameter fitting.
Inputs are local financial outputs/Jacobians already evaluated by another tool.
FP64 algebra composes continuous-formula Jacobians at recorded intermediate
values. It does not differentiate rounding or supply a second-order derivative.
"""
import numpy as np

MODES = ('full', 'drive_only', 'conditioning_only', 'both_detached')


def _array(value, shape, name):
    result = np.asarray(value, dtype=np.float64)
    if result.shape != shape or not np.isfinite(result).all():
        raise ValueError(name + ' has wrong shape or nonfinite entries')
    return result


def _rows9(value, batch, name):
    result = np.asarray(value, dtype=np.float64)
    if result.shape == (9,):
        result = np.broadcast_to(result, (batch, 9))
    return _array(result, (batch, 9), name)


def _local_fields(raw, jac, asset, batch):
    raw = _array(raw, (batch, 5), 'financial outputs')
    jac = _array(jac, (batch, 5, 10), 'financial Jacobian')
    asset = _array(asset, (batch,), 'represented assets')
    b, e, f = raw[:, 0], raw[:, 1], raw[:, 2]
    if np.any(b <= 0) or np.any(asset <= 0):
        raise ValueError('Boundaries and represented assets must be positive')
    q_partial = jac[:, 1] / b[:, None] - e[:, None] * jac[:, 0] / b[:, None] ** 2
    r_partial = 2 * (1 - f[:, None]) * jac[:, 2]
    q_theta, r_theta = q_partial[:, :9], r_partial[:, :9]
    q_z, r_z = asset * q_partial[:, 9], asset * r_partial[:, 9]
    margin_theta = -jac[:, 0, :9] / b[:, None]
    # b_V is identically zero in the H-X model. Keeping this term explicit
    # makes the raw-Jacobian chain transparent and exposes a violated identity.
    margin_z = 1 - asset * jac[:, 0, 9] / b
    return q_theta, r_theta, q_z, r_z, margin_theta, margin_z


def _drift_partials(fields, coefficients, batch):
    q_theta, r_theta, q_z, r_z = fields[:4]
    k_e, k_r, leak, tau = [coefficients[k] for k in ('k_equity', 'k_risk', 'leak', 'tau')]
    state = np.zeros((batch, 2, 2), dtype=np.float64)
    state[:, 0, 0] = -leak - k_e * q_z - k_r * r_z
    state[:, 0, 1] = 1
    state[:, 1, 0] = k_r * r_z / tau
    state[:, 1, 1] = -1 / tau
    parameters = np.stack((-k_e * q_theta - k_r * r_theta, k_r * r_theta / tau), axis=1)
    return state, parameters


def compose_local(*, raw1, jac1, asset1, raw2, jac2, asset2,
                  base1, base2, tanh1, tanh2, config, mode='full'):
    """Return one old-state Euler Jacobian, with state order z1,a1,z2,a2.

    raw1/raw2: [batch,5]; jac1/jac2: [batch,5,10], asset coordinate.
    base/tanh inputs: [9] or [batch,9]. tanh inputs are actual recorded outputs,
    not tanh re-evaluated by this reference. Constants are represented as FP32.
    A: [batch,4,4], B: [batch,4,18]; raw order is raw_theta1 then raw_theta2.
    D1/D2 contain diagonal elements, shape [batch,9]. The two boundary_raw1
    fields are UNMASKED [batch,2,9] lower-state blocks and already include dt.
    Changing mode changes only cross-state and lower/raw1 blocks; forward
    fields, own-layer parameter blocks, and the eighteen parameter meanings
    remain identical. No second derivative of the state-dependent D2 is used.
    """
    if mode not in MODES:
        raise ValueError('Unknown gradient mode')
    raw1_array = np.asarray(raw1)
    if raw1_array.ndim != 2 or raw1_array.shape[0] == 0:
        raise ValueError('Expected nonempty [batch,5] financial output')
    batch = raw1_array.shape[0]
    names = ('dt', 'leak', 'k_equity', 'k_risk', 'tau', 'fraction', 'coupling_gain', 'conditioning_gain')
    coefficients = {name: float(np.float32(config[name])) for name in names}
    if any(not np.isfinite(value) or value <= 0 for value in coefficients.values()):
        raise ValueError('Expected positive finite represented coefficients')
    t1, t2 = _rows9(tanh1, batch, 'tanh1'), _rows9(tanh2, batch, 'tanh2')
    if np.any(np.abs(t1) > 1) or np.any(np.abs(t2) > 1):
        raise ValueError('Recorded tanh output must lie in [-1,1]')
    d1 = _rows9(base1, batch, 'base1') * coefficients['fraction'] * (1 - t1 ** 2)
    d2 = _rows9(base2, batch, 'base2') * coefficients['fraction'] * (1 - t2 ** 2)
    fields1 = _local_fields(raw1, jac1, asset1, batch)
    fields2 = _local_fields(raw2, jac2, asset2, batch)
    f1_state, g1 = _drift_partials(fields1, coefficients, batch)
    f2_state, g2 = _drift_partials(fields2, coefficients, batch)
    k_drive = np.zeros((batch, 2)); k_drive[:, 0] = coefficients['coupling_gain']
    k_condition = np.einsum('bij,bj->bi', g2, coefficients['conditioning_gain'] * d2)
    h_theta, h_z = fields1[4:]
    direct_boundary_raw1 = h_theta * d1
    dt = coefficients['dt']
    boundary_drive = dt * k_drive[:, :, None] * direct_boundary_raw1[:, None, :]
    boundary_condition = dt * k_condition[:, :, None] * direct_boundary_raw1[:, None, :]
    drive_active = mode in ('full', 'drive_only')
    condition_active = mode in ('full', 'conditioning_only')
    k_total = drive_active * k_drive + condition_active * k_condition
    A = np.zeros((batch, 4, 4)); B = np.zeros((batch, 4, 18))
    A[:, :2, :2] = np.eye(2)[None] + dt * f1_state
    A[:, 2:, 2:] = np.eye(2)[None] + dt * f2_state
    A[:, 2:, 0] = dt * k_total * h_z[:, None]
    B[:, :2, :9] = dt * g1 * d1[:, None, :]
    B[:, 2:, 9:] = dt * g2 * d2[:, None, :]
    B[:, 2:, :9] = drive_active * boundary_drive + condition_active * boundary_condition
    return {'A': A, 'B': B, 'K_drive': k_drive, 'K_condition': k_condition,
            'D1': d1, 'D2': d2, 'G1': g1, 'G2': g2,
            'margin_theta': h_theta, 'margin_z': h_z,
            'boundary_raw1_drive': boundary_drive,
            'boundary_raw1_condition': boundary_condition}


def reverse_steps(A, B, terminal_adj):
    """Compose first-order reverse AD for a shared eighteen-vector parameter.

    A:[time,batch,4,4], B:[time,batch,4,18], terminal_adj:[batch,4].
    No running loss is included. step_raw sums the batch, not time; shared_raw
    sums step_raw over time. state_adj retains every temporal adjoint.
    """
    a = np.asarray(A, dtype=np.float64)
    if a.ndim != 4 or a.shape[0] == 0 or a.shape[1] == 0:
        raise ValueError('Expected nonempty time and batch dimensions')
    time, batch = a.shape[:2]
    a = _array(a, (time, batch, 4, 4), 'A')
    b = _array(B, (time, batch, 4, 18), 'B')
    adjoint = _array(terminal_adj, (batch, 4), 'terminal adjoint').copy()
    state_adj = np.zeros((time + 1, batch, 4)); state_adj[-1] = adjoint
    step_raw = np.zeros((time, 18))
    for t in range(time - 1, -1, -1):
        step_raw[t] = np.einsum('bi,bij->j', adjoint, b[t])
        adjoint = np.einsum('bi,bij->bj', adjoint, a[t])
        state_adj[t] = adjoint
    return {'step_raw': step_raw, 'shared_raw': step_raw.sum(axis=0), 'state_adj': state_adj}
