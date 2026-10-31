"""Causal, equally sized NumPy recurrent models with exact BPTT.

The analytic gates are two ONE-SIDED first-passage probabilities from the same
frozen Brownian drift/variance. They may overlap and are not competing events.
This is an operator-gated content model, not a full regenerative He--Xiong cell.
"""
from functools import lru_cache

import numpy as np
from scipy.special import expit, logsumexp, ndtr

KINDS = ("ordinary", "ordinary_dual", "matched_slope", "analytic_single", "analytic_dual")
INPUT_DIM = 8
BARRIER, DRIFT_SCALE, SIGMA_MIN, SIGMA_SPAN = .55, .7, .35, .45


def hit(mu, sigma, dt, derivatives=False):
    root = np.sqrt(dt)
    u, v = (mu * dt - BARRIER) / (sigma * root), (-mu * dt - BARRIER) / (sigma * root)
    e = np.exp(2 * mu * BARRIER / sigma**2)
    nv = ndtr(v)
    p = ndtr(u) + e * nv
    if not derivatives:
        return p
    pu, pv = np.exp(-.5 * u*u) / np.sqrt(2*np.pi), np.exp(-.5 * v*v) / np.sqrt(2*np.pi)
    dm = pu*root/sigma + e*(2*BARRIER/sigma**2*nv - pv*root/sigma)
    ds = -pu*u/sigma + e*(-4*mu*BARRIER/sigma**3*nv - pv*v/sigma)
    return p, dm, ds


@lru_cache(maxsize=64)
def matched_constants(dt):
    sigma = SIGMA_MIN + .5*SIGMA_SPAN
    p, dm, ds = hit(0., sigma, dt, True)
    return (float(np.log(p)-np.log1p(-p)),
            float(dm*DRIFT_SCALE/(p*(1-p))), float(ds*.25*SIGMA_SPAN/(p*(1-p))))


def gates(kind, a, b, dt, derivatives=False):
    if kind == "ordinary_dual":
        up, down = expit(a), expit(b)
        slopes = (up*(1-up), np.zeros_like(up), np.zeros_like(up), down*(1-down))
    elif kind == "matched_slope":
        constants = np.asarray([matched_constants(float(x)) for x in dt[:, 0]])
        c, ma, mb = [constants[:, i, None] for i in range(3)]
        up, down = expit(c + ma*a + mb*b), expit(c - ma*a + mb*b)
        slopes = (up*(1-up)*ma, up*(1-up)*mb, -down*(1-down)*ma, down*(1-down)*mb)
    elif kind in ("analytic_dual", "analytic_single"):
        tanh_a, sb = np.tanh(a), expit(b)
        mu = DRIFT_SCALE*tanh_a
        sigma = SIGMA_MIN + SIGMA_SPAN*(sb if kind == "analytic_dual" else .5)
        if derivatives:
            up, um, us = hit(mu, sigma, dt, True)
            down, dm, ds = hit(-mu, sigma, dt, True)
            da = DRIFT_SCALE*(1-tanh_a*tanh_a)
            db = SIGMA_SPAN*sb*(1-sb) if kind == "analytic_dual" else np.zeros_like(sb)
            slopes = (um*da, us*db, -dm*da, ds*db)
        else:
            up, down = hit(mu, sigma, dt), hit(-mu, sigma, dt)
            slopes = None
    else:
        up = expit(a)
        down = up
        slopes = (up*(1-up), np.zeros_like(up), up*(1-up), np.zeros_like(up))
    return up, down, slopes


class Model:
    def __init__(self, kind, width=12, seed=0):
        if kind not in KINDS:
            raise ValueError(kind)
        self.kind, self.width = kind, width
        rng = np.random.default_rng(seed)
        scale = np.sqrt(6/(INPUT_DIM+2*width))
        self.p = dict(w=rng.uniform(-scale, scale, (INPUT_DIM+width, 3*width)),
                      b=np.zeros(3*width), out=rng.normal(0, .25, (width, 2)), bias=np.zeros(2))

    @property
    def parameters(self):
        return sum(x.size for x in self.p.values())

    def step(self, x, dt, h, retain=False, intervention=None):
        if np.any(dt <= 0) or not np.all(np.isfinite(x)):
            raise ValueError("Invalid causal frame")
        q = np.concatenate((x, h), axis=1)
        a, b, c = np.split(q @ self.p["w"] + self.p["b"], 3, axis=1)
        up, down, slopes = gates(self.kind, a, b, dt[:, None], retain)
        single = self.kind in ("ordinary", "analytic_single")
        tb = np.tanh(b)
        candidate = np.tanh(c + .5*tb*h) if single else np.tanh(c)
        if single:
            down = up
        if intervention == "remove_up":
            up = np.zeros_like(up)
        elif intervention == "remove_down":
            down = np.zeros_like(down)
        new = np.tanh((1-down)*h + up*candidate)
        logits = new @ self.p["out"] + self.p["bias"]
        cache = (q, h, new, candidate, up, down, slopes, tb) if retain else None
        return logits, new, cache, (up, down)

    def forward(self, x, dt, retain=False, intervention=None):
        h = np.zeros((len(x), self.width))
        logits, states, history = [], [], []
        for t in range(x.shape[1]):
            out, h, cache, _ = self.step(x[:, t], dt[:, t], h, retain, intervention)
            logits.append(out); states.append(h); history.append(cache)
        return np.stack(logits, axis=1), np.stack(states, axis=1), history

    def loss(self, x, dt, y, mask, gradients=True):
        logits, states, history = self.forward(x, dt, gradients)
        target = np.broadcast_to(y[:, None], logits.shape[:2])
        normalizer = float(mask.sum())
        loss = float(np.sum(mask*(logsumexp(logits, axis=2)-np.take_along_axis(logits, target[..., None], 2)[..., 0]))/normalizer)
        if not gradients:
            return loss
        dlogit = np.exp(logits-logsumexp(logits, axis=2, keepdims=True))
        dlogit -= np.eye(2)[target]
        dlogit *= mask[..., None]/normalizer
        grad = {k: np.zeros_like(v) for k, v in self.p.items()}
        grad["out"] = states.reshape(-1, self.width).T @ dlogit.reshape(-1, 2)
        grad["bias"] = dlogit.sum((0, 1))
        dh = np.zeros((len(x), self.width))
        for t in range(x.shape[1]-1, -1, -1):
            q, before, new, candidate, up, down, slopes, tb = history[t]
            dh += dlogit[:, t] @ self.p["out"].T
            dz = dh*(1-new*new)
            dc = dz*up*(1-candidate*candidate)
            direct = dz*(1-down)
            ua, ub, da, db = slopes
            if self.kind in ("ordinary", "analytic_single"):
                gate_derivative = dz*(candidate-before)
                dpre = np.concatenate((gate_derivative*ua,
                    dc*.5*before*(1-tb*tb), dc), axis=1)
                direct += dc*.5*tb
            else:
                du, dd = dz*candidate, -dz*before
                dpre = np.concatenate((du*ua+dd*da, du*ub+dd*db, dc), axis=1)
            grad["w"] += q.T @ dpre
            grad["b"] += dpre.sum(0)
            dh = direct + dpre @ self.p["w"][INPUT_DIM:].T
        if not np.isfinite(loss) or any(not np.isfinite(v).all() for v in grad.values()):
            raise FloatingPointError("Nonfinite BPTT")
        return loss, grad


class Adam:
    def __init__(self, model, learning_rate=.003):
        self.m = {k: np.zeros_like(v) for k, v in model.p.items()}
        self.v = {k: np.zeros_like(v) for k, v in model.p.items()}
        self.rate, self.steps = learning_rate, 0

    def update(self, model, grad):
        norm = float(np.sqrt(sum(np.sum(x*x) for x in grad.values())))
        factor = min(1., 2./max(norm, 1e-30)); self.steps += 1
        for key in model.p:
            g = grad[key]*factor
            self.m[key] = .9*self.m[key] + .1*g
            self.v[key] = .999*self.v[key] + .001*g*g
            model.p[key] -= self.rate*(self.m[key]/(1-.9**self.steps))/(np.sqrt(self.v[key]/(1-.999**self.steps))+1e-8)
        return norm


def encode_prefix(model, observations, deltas, temperature=1.):
    """No labels/posteriors: observations are encoded causal eight-field frames."""
    x, dt = np.asarray(observations, float), np.asarray(deltas, float)
    if x.ndim != 2 or x.shape != (len(dt), INPUT_DIM) or len(dt) == 0:
        raise ValueError("Expected a nonempty observed prefix")
    h = np.zeros((1, model.width))
    for frame, elapsed in zip(x, dt):
        logits, h, _, channels = model.step(frame[None], np.array([elapsed]), h)
    p = np.exp(logits/temperature-logsumexp(logits/temperature, axis=1, keepdims=True))
    return dict(belief=float(p[0, 1]), hidden=h[0].tolist(),
                p_up=channels[0][0].tolist(), p_down=channels[1][0].tolist(), frames_read=len(dt))
