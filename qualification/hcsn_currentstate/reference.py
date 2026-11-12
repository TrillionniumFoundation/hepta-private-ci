"""Independent direct serial-state semigroups and release quadrature.

This module never imports packets.py and never reconstructs current spatial
coordinates from renewal totals. Only numpy/scipy and explicit fixture data.
"""
from fractions import Fraction as F
import math
import numpy as np
from scipy.linalg import expm
from numpy.polynomial.legendre import leggauss


class Reference:
    def __init__(self, name, order):
        self.name = name; self.order = order; self.expm_calls = 0; self.quad_nodes = 0
        if name == "mixed":
            self.Q = np.array([[-3., 1.], [3., -3.5]])
            self.k = np.array([2., 0.]); self.u = np.array([0., .5]); self.r = np.array([.25, .75])
            self.initial = np.array([[1/8, 1/4], [1/16, -1/8], [-3/32, 1/16]])
        elif name == "rare":
            self.Q = np.array([[-(.5+2**-14)]])
            self.k = np.array([2**-14]); self.u = np.array([.5]); self.r = np.array([1.])
            self.initial = np.array([[3/8], [1/16], [-3/32]])
        else:
            raise ValueError("reference fixture")
        self.q = .15; self.d = .2; self.nodes, self.weights = leggauss(order)
        self.cache = {}

    def exponential(self, a):
        self.expm_calls += 1
        if self.expm_calls > 20000:
            raise RuntimeError("reference expm cap")
        return expm(a)

    def primitive(self, matrix, selector, t, q=0.):
        n = len(matrix); selector = np.atleast_2d(selector).reshape(n, -1)
        k = selector.shape[1]
        extended = np.zeros((n+k, n+k)); extended[:n, :n] = matrix-q*np.eye(n)
        extended[:n, n:] = selector
        e = self.exponential(extended*t)
        return e[:n, n:]

    def point(self, t):
        """Unit initial distribution's per-generation direct observables."""
        key = float(t).hex()
        if key in self.cache:
            return self.cache[key]
        n = len(self.k); out = {k: np.zeros((n, 2)) for k in ("M", "H", "R", "Z", "A", "upper")}
        out["active"] = np.zeros((n, 2, n))
        if t <= 0:
            out["active"][:, 0] = np.eye(n)
            self.cache[key] = out; return out
        for g in (1, 2):
            shift = (g-1)*self.d; deadline = t-shift
            if deadline <= 0:
                continue
            b = np.zeros((g*n, g*n))
            for j in range(g):
                b[j*n:(j+1)*n, j*n:(j+1)*n] = self.Q
                if j+1 < g:
                    b[j*n:(j+1)*n, (j+1)*n:(j+2)*n] = self.k[:, None]*self.r
            lower = np.zeros(g*n); lower[-n:] = self.k
            upper = np.zeros(g*n); upper[-n:] = self.u
            out["active"][:, g-1] = self.exponential(b*deadline)[:n, -n:]
            out["upper"][:, g-1] = self.primitive(b, upper, deadline)[:n, 0]
            out["M"][:, g-1] = self.primitive(b, lower, deadline)[:n, 0]
            out["H"][:, g-1] = math.exp(-self.q*shift)*self.primitive(b, lower, deadline, self.q)[:n, 0]
            window_left = max(0., deadline-self.d)
            pre = self.exponential(b*window_left)
            out["R"][:, g-1] = (pre@self.primitive(b, lower, deadline-window_left))[:n, 0]
            discounted = self.primitive(b, lower, deadline-window_left, self.q)
            out["Z"][:, g-1] = math.exp(-self.q*(self.d-t+shift+window_left))*(pre@discounted)[:n, 0]
            # Direct occupation: upper sink for this generation, no other sinks.
            a = np.zeros((g*n+1, g*n+1)); a[:-1, :-1] = b; a[:-1, -1] = upper
            occupation = np.zeros(g*n+1); occupation[(g-1)*n:] = 1
            out["A"][:, g-1] = math.exp(-self.q*shift)*self.primitive(a, occupation, deadline, self.q)[:n, 0]
        self.cache[key] = out
        return out

    def at(self, t):
        """Signed release mixture, with quadrature splits at exact kinks."""
        t = float(t); n = len(self.k)
        result = {k: np.zeros((3, 2)) for k in ("M", "H")}
        result.update({k: np.zeros((3, 3)) for k in ("R", "Z", "A", "upper")})
        result["active"] = np.zeros((3, 2, n))
        def add(release, row):
            if release > t:
                return
            v = self.point(t-release)
            for k in ("M", "R", "Z", "upper"):
                target = result[k] if k == "M" else result[k][:, 1:]
                target += row@v[k]
            for k in ("H", "A"):
                target = result[k] if k == "H" else result[k][:, 1:]
                target += math.exp(-self.q*release)*(row@v[k])
            result["active"][:] += np.einsum("cn,ngj->cgj", row, v["active"])
        add(0., self.initial)
        uniform = np.array([3/8, 1/8, -1/16]); width = .025
        end = min(t, width)
        cuts = sorted(set([0., end]+[x for x in (t-self.d, t-2*self.d) if 0 < x < end]))
        for a, b in zip(cuts[:-1], cuts[1:]):
            for node, weight in zip(self.nodes, self.weights):
                r = a+(b-a)*(node+1)/2
                row = (uniform*(b-a)*weight/(2*width))[:, None]*self.r
                self.quad_nodes += 1
                if self.quad_nodes > 2500:
                    raise RuntimeError("reference GL-node cap")
                add(r, row)
        if t < width:
            result["R"][:, 0] += uniform*(width-t)/width
            result["Z"][:, 0] += uniform*(-math.expm1(-self.q*(width-t)))/(self.q*width)
        atom = np.array([1/8, 1/16, -1/8]); atom_time = .0625
        if t < atom_time:
            result["R"][:, 0] += atom
            result["Z"][:, 0] += atom*math.exp(-self.q*(atom_time-t))
        else:
            add(atom_time, atom[:, None]*self.r)
        initial_upper = np.array([1/8, -1/32, 1/16])
        result["upper"][:, 0] = initial_upper
        result["A"][:, 0] = initial_upper*(-math.expm1(-self.q*t))/self.q
        return result
