"""Exact finite-law NDU benchmark. Research only; no production wire semantics."""
from dataclasses import dataclass
from decimal import Decimal, localcontext
import numpy as np
import torch


@dataclass(frozen=True)
class World:
    bits: int
    left: np.ndarray
    right: np.ndarray
    probability: np.ndarray
    cost: np.ndarray
    risk: np.ndarray
    discount: float = 0.9

    def __post_init__(self):
        n = 3 * 2**self.bits
        if not 1 <= self.bits <= 8 or not 0 < self.discount <= 1:
            raise ValueError("invalid world size or discount")
        for name in ("left", "right", "probability", "cost", "risk"):
            a = np.array(getattr(self, name), copy=True)
            if a.shape != (n,) or not np.isfinite(a).all():
                raise ValueError("invalid world array")
            a.setflags(write=False)
            object.__setattr__(self, name, a)
        for a in (self.left, self.right):
            if a.dtype.kind not in 'iu' or np.any((a < 0) | (a >= n)):
                raise ValueError("invalid successor")
        if np.any((self.probability <= 0) | (self.probability >= 1)):
            raise ValueError("degenerate Bernoulli driver")
        if np.any(self.risk < 0):
            raise ValueError("negative risk outside profile")

    @property
    def size(self):
        return len(self.left)

    def kernel(self):
        p = np.zeros((self.size, self.size))
        for i in range(self.size):
            p[i, self.left[i]] += self.probability[i]
            p[i, self.right[i]] += 1 - self.probability[i]
        return p

    def tensor(self):
        return {
            'left': torch.tensor(self.left, dtype=torch.long),
            'right': torch.tensor(self.right, dtype=torch.long),
            'p': torch.tensor(self.probability, dtype=torch.float64),
            'c': torch.tensor(self.cost, dtype=torch.float64),
            'risk': torch.tensor(self.risk, dtype=torch.float64),
            'gamma': self.discount,
        }


def make_world(bits=2, changed=False, probability_profile=False):
    """Binary shift-register X, experience-driven bounded preference P in {0,1,2}."""
    n = 3 * 2**bits
    left, right, prob, cost, risk = [], [], [], [], []
    for s in range(n):
        x, pref = divmod(s, 3)
        for bit, out in ((0, left), (1, right)):
            xx = ((2 * x + bit) % 2**bits)
            if changed:
                xx ^= 1 << (bits - 1)
            pp = min(2, max(0, pref + (1 if bit else -1)))
            out.append(3 * xx + pp)
        prob.append(0.25 + 0.35 * x.bit_count() / bits + 0.1 * pref)
        cost.append(0 if probability_profile else 0.03 * (1 + pref) * x.bit_count() / bits)
        risk.append(0 if probability_profile else 0.35 + 0.4 * pref)
    return World(bits, np.array(left), np.array(right), np.array(prob),
                 np.array(cost), np.array(risk), 1.0 if probability_profile else 0.9)


def terminals(world, split):
    """Entire *training* terminal law is enumerated; held-out laws are transfer."""
    if split not in ('train', 'transfer', 'probability'):
        raise ValueError("unknown split")
    rng = np.random.default_rng({'train': 1201, 'transfer': 8237, 'probability': 9901}[split])
    count = 12 if split == 'train' else 8
    if split == 'probability':
        return (rng.uniform(size=(count, world.size)) > 0.5).astype(float)
    return rng.uniform(-0.8, 0.8, (count, world.size))


def exact_step(v, w):
    """Stable binary entropic cost; zero-risk branch is ordinary expectation."""
    a, b, p, r = v[..., w['left']], v[..., w['right']], w['p'], w['risk']
    mean = p * a + (1 - p) * b
    safe = torch.where(r == 0, torch.ones_like(r), r)
    ce = torch.logaddexp(torch.log(p) + safe * a,
                        torch.log1p(-p) + safe * b) / safe
    return w['c'] + w['gamma'] * torch.where(r == 0, mean, ce)


def decimal_oracle(world, g, horizon):
    """Independent scalar Decimal-50 recursion, not a call to exact_step/D."""
    if not 0 <= horizon <= 16:
        raise ValueError("invalid horizon")
    with localcontext() as context:
        context.prec = 50
        d = lambda x: Decimal(str(float(x)))
        v = [[d(x) for x in row] for row in np.asarray(g)]
        out = [np.asarray(g, dtype=float)]
        for _ in range(horizon):
            nxt = []
            for row in v:
                values = []
                for i in range(world.size):
                    a, b, p = row[world.left[i]], row[world.right[i]], d(world.probability[i])
                    r = d(world.risk[i])
                    ce = p * a + (1-p) * b if not r else (p*(r*a).exp()+(1-p)*(r*b).exp()).ln()/r
                    values.append(d(world.cost[i]) + d(world.discount)*ce)
                nxt.append(values)
            v = nxt
            out.append(np.array([[float(x) for x in row] for row in v]))
        return np.stack(out)


def bernoulli_fbsde_defect(v, w):
    """Z=(v_left-v_right), dM=I_left-p: no incorrect covariance division."""
    a, b, p = v[..., w['left']], v[..., w['right']], w['p']
    z, mean = a-b, p*a+(1-p)*b
    return torch.stack((a-mean-z*(1-p), b-mean+z*p))
