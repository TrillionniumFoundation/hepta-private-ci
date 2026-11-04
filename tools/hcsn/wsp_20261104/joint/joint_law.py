"""Independent NumPy/SciPy environment law for the declared finite renewal CTMC.

This implementation does not import the differentiable kernel. Its generator is
finite in space; SciPy expm integrates that generator in continuous time. It is
not an exact Brownian simulator or an independently inferred decoder law.
"""
from functools import lru_cache

import numpy as np
from scipy.linalg import expm
from scipy.special import expit, ndtr

RAW_NAMES = ("boundary", "diffusion", "gain", "drift_bias", "reset_plus",
             "reset_minus", "recovery_rate", "reset_sd")


class IndependentLaw:
    def __init__(self, raw, n_grid=31):
        self.raw = np.asarray(raw, dtype=np.float64).copy()
        if self.raw.shape != (8,) or not np.isfinite(self.raw).all():
            raise ValueError("eight finite raw coordinates required")
        self.raw.setflags(write=False)
        if not isinstance(n_grid, int) or n_grid < 31 or n_grid % 2 != 1:
            raise ValueError("odd n_grid>=31 required")
        self.n_grid, self.n_states = n_grid, n_grid+2
        self.u = np.r_[np.linspace(-1., 1., n_grid+2)[1:-1], -1., 1.]
        self.positive = self.u > 0.
        self.physical = self._physical()

    def _physical(self):
        r = self.raw
        b = .8+.4*expit(r[0])
        return dict(boundary=b, diffusion=.35+.45*expit(r[1]), gain=.9*np.tanh(r[2]),
                    drift_bias=.2*np.tanh(r[3]), reset_plus=.6*b*np.tanh(r[4]),
                    reset_minus=.6*b*np.tanh(r[5]), recovery_rate=.25+1.75*expit(r[6]),
                    reset_sd=b*(.06+.06*expit(r[7])))

    def initial_mass(self, distance=.375):
        if distance not in (.125, .375, .75):
            raise ValueError("unsupported public prior distance")
        active = self.u[:self.n_grid]
        mass = np.zeros(self.n_states)
        mass[np.argmin(np.abs(active-distance))] += .5
        mass[np.argmin(np.abs(active+distance))] += .5
        return mass

    def generator(self, drive):
        if drive not in (-1, 0, 1):
            raise ValueError("drive must be -1/0/+1")
        p, n = self.physical, self.n_grid
        b = p["boundary"]; dx = 2*b/(n+1)
        mu = p["drift_bias"]+p["gain"]*drive
        right = p["diffusion"]**2/(2*dx**2)+mu/(2*dx)
        left = p["diffusion"]**2/(2*dx**2)-mu/(2*dx)
        if min(right, left) <= 0:
            raise ArithmeticError("positive-rate envelope violated")
        q = np.zeros((n+2, n+2))
        for i in range(n):
            q[i, i+1 if i+1 < n else n+1] = right
            q[i, i-1 if i else n] = left
            q[i, i] = -right-left
        x = b*self.u[:n]
        edges = np.r_[-b, (x[:-1]+x[1:])/2, b]
        for index, key in ((n, "reset_minus"), (n+1, "reset_plus")):
            cumulative = ndtr((edges-p[key])/p["reset_sd"])
            bins = np.diff(cumulative)/(cumulative[-1]-cumulative[0])
            q[index, :n] = p["recovery_rate"]*bins
            q[index, index] = -p["recovery_rate"]
        return q

    @lru_cache(maxsize=128)
    def transition(self, dt, drive):
        if not np.isfinite(dt) or not 0 <= dt <= 2:
            raise ValueError("duration outside [0,2]")
        result = expm(float(dt)*self.generator(drive))
        if result.min() < -2e-12 or np.max(np.abs(result.sum(1)-1)) > 2e-11:
            raise ArithmeticError("invalid independent transition")
        result.setflags(write=False)
        return result

    def emission(self, reliability, confusion):
        confusion = np.asarray(confusion, dtype=np.float64)
        if (confusion.shape != (2, 2) or not np.isfinite(confusion).all()
                or np.any(confusion <= 0) or not np.allclose(confusion.sum(1), 1.)
                or not .5 <= reliability <= 1.):
            raise ValueError("positive stochastic decoder law and r>=.5 required")
        noise = np.array([[reliability, 1-reliability], [1-reliability, reliability]])
        return (noise @ confusion)[self.positive.astype(int)]

    def export(self):
        return dict(schema="joint-independent-renewal-law-v1", raw=self.raw.tolist(),
                    n_grid=self.n_grid, physical=self.physical,
                    state_order="active internal ascending nodes, lower_ref, upper_ref",
                    positive_label="normalized_coordinate>0; zero belongs to label0",
                    approximation="finite-space CTMC, independent scipy expm")
