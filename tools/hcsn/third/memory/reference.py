"""Independent NumPy recurrence, including the rounded shared-endpoint table."""
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TABLE = {k: v.astype(np.float32) for k, v in
         dict(np.load(ROOT / "next/full_kernel/baseline_table.npz")).items()}


def closed_write(score):
    positive = np.maximum(score, 0.)
    small = np.minimum(positive, 1.)
    inverse = 1. / np.maximum(positive, 1.)
    return np.where(positive > 1., 1. / (1. + inverse * inverse), small * small / (1. + small * small))


def sigmoid(z):
    e = np.exp(-np.abs(z))
    return np.where(z >= 0, 1. / (1. + e), e / (1. + e))


def hermite(t, y0, y1, m0, m1, step):
    return y0 + (y1-y0)*t*t*(3-2*t) + step*m0*t*(1-t)**2 + step*m1*t*t*(t-1)


def cubic(u, coeff, step, end, slope):
    count = coeff.shape[1]
    index = np.clip(np.floor(u / step).astype(np.int32), 0, count-1)
    following = np.minimum(index+1, count-1)
    return hermite((u-index.astype(u.dtype)*step)/step, coeff[3, index],
                   np.where(index < count-1, coeff[3, following], end), coeff[2, index],
                   np.where(index < count-1, coeff[2, following], slope), step)


def full_gates(z):
    t = TABLE
    distance = np.abs(z)
    eps = t["epsilon_scaled"]
    patch = hermite(np.minimum(distance/eps, 1.), 1., t["risk_coeff"][3, 0],
                    0., t["risk_coeff"][2, 0], eps)
    risk = cubic(np.clip(distance, eps, t["risk_limit"])-eps, t["risk_coeff"],
                 t["risk_step"], t["risk_end"], -t["risk_end"]*t["risk_tail_rate"])
    tail = t["risk_end"]*np.exp(-t["risk_tail_rate"]*np.maximum(distance-t["risk_limit"], 0.))
    risk = np.where(distance > t["risk_limit"], tail, risk)
    risk = np.where(distance < eps, patch, risk)
    q = np.where(z < 0, .5*risk, 1-.5*risk)
    safe = t["diffusion_scale"]*np.maximum(-z, 0.)
    slope = t["call_tail_rate"]*(1-t["call_end"])*(t["diffusion_scale"]+t["call_distance_limit"])
    a = cubic(np.minimum(np.log1p(safe/t["diffusion_scale"]), t["call_limit"]),
              t["call_coeff"], t["call_step"], t["call_end"], slope)
    tail = 1-(1-t["call_end"])*np.exp(-t["call_tail_rate"]*np.maximum(safe-t["call_distance_limit"], 0.))
    return q, np.where(z < 0, np.where(safe > t["call_distance_limit"], tail, a), 0.)


def gates(z, name):
    if name in ("legacy_sigmoid", "legacy_hcsn"):
        e = np.exp(-np.abs(z))
        q = sigmoid(2*z) if name == "legacy_sigmoid" else np.where(z < 0, .5*e, 1-.5*e)
        return q, np.where(z < 0, 1-2*e/(1+e*e), 0.)
    if name == "c1":
        magnitude = closed_write(np.abs(z))
        return .5+.5*np.where(z < 0, -magnitude, magnitude), closed_write(-z)
    q, a = full_gates(z)
    return (sigmoid(2*z) if name == "sigmoid" else q), a


def forward(p, x, dt, name):
    u = np.concatenate([x, np.log1p(dt)[..., None]], axis=-1)
    batch, length = x.shape[:2]
    width = p["out"].shape[0]
    gram = np.zeros((batch, 16, 16), x.dtype)
    cross = np.zeros((batch, 16, width), x.dtype)
    mass = np.ones((batch, 1), x.dtype)
    xx = np.zeros((batch, width), x.dtype)
    yy = xx.copy()
    if name != "memory":
        fast = .2+4.8*sigmoid(p["tau_fast"])
        slow = 2.+98.*sigmoid(p["tau_slow"])
        regen, recover, call = 4.*sigmoid(p["regen"]), 6.*sigmoid(p["recover"]), 2.*sigmoid(p["call"])
    for index in range(length):
        incoming, delta = u[:, index], dt[:, index]
        hidden = np.tanh(incoming @ p["inp"]+p["bias"])
        key = np.tanh(incoming @ p["key"]+p["key_bias"])/np.float32(4.)
        candidate = hidden @ p["value"]+p["value_bias"]
        current = np.tanh(p["read_current"])*hidden
        if name != "memory":
            q, a = gates(xx-p["boundary"]-incoming @ p["boundary_weights"], name)
            drive = 3.*np.tanh(hidden+.5*np.tanh(p["recurrent_diag"])*(2*q-1))
            ef, es = np.exp(-delta[:, None]/fast), np.exp(-delta[:, None]/slow)
            xx = ef*xx+(1-ef)*(call*a+regen*q-yy+drive)
            yy = es*yy+(1-es)*recover*q
            candidate = candidate+.1*np.tanh(xx)
            current = current+np.tanh(p["read_fast"])*np.tanh(xx)+np.tanh(p["read_slow"])*np.tanh(yy)
        if index < length-1:
            value = np.tanh(candidate)
            write = closed_write(incoming @ p["write"]+p["write_bias"])
            mass = mass/(1+write*mass)
            alpha = (write*mass)[..., None]
            gram = (1-alpha)*gram+alpha*np.einsum("bi,bj->bij", key, key)
            cross = (1-alpha)*cross+alpha*np.einsum("bi,bj->bij", key, value)
    return dict(gram=gram, cross=cross, inverse_mass=mass, query=key, current=current, fast=xx, slow=yy)


def readout(p, state, mode, solver_dtype=None):
    g, h, r = (state[k] for k in ("gram", "cross", "inverse_mass"))
    output_dtype = g.dtype
    if solver_dtype is not None:
        g, h, r = (np.asarray(a, solver_dtype) for a in (g, h, r))
    ridge = .01*(r if mode == "mass" else np.ones_like(r))
    matrix = .5*(g+g.swapaxes(-1, -2))+ridge[..., None]*np.eye(16, dtype=g.dtype)
    fitted = np.linalg.solve(matrix, h)
    read = np.einsum("bi,bih->bh", state["query"].astype(g.dtype), fitted).astype(output_dtype)
    logits = (np.tanh(read)+state["current"]) @ p["out"]+p["out_bias"]
    residual = np.linalg.norm(matrix @ fitted-h, axis=(-2, -1))/np.maximum(np.linalg.norm(h, axis=(-2, -1)), 1e-12)
    return logits, dict(maximum_condition=float(np.max(np.linalg.cond(matrix.astype(np.float64)))),
                        maximum_relative_residual=float(residual.max()), maximum_read=float(np.abs(read).max()),
                        maximum_write_mass=float((1/r-1).max()))
