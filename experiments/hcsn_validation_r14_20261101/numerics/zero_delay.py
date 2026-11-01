"""Complete zero-delay regenerative law on a declared finite spatial grid.

The lower absorbing flux is counted and immediately reinserted at reset. Marked
count layers preserve event probabilities even when reset returns to the same
state. A separate upper cemetery meters truncation loss. No clipping or mass
renormalization occurs. The continuous target is assessed outside this module.
"""

import math

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import expm_multiply


class ZeroDelayFlow:
    def __init__(self, x, mu, sigma, reset, spacing, upper=8.0, count_cap=3):
        if not all(math.isfinite(v) for v in (x, mu, sigma, reset, spacing, upper)):
            raise ValueError("Finite model and grid parameters required")
        if x < 0 or min(sigma, reset, spacing, upper) <= 0:
            raise ValueError("Require x>=0 and positive sigma, reset and grid sizes")
        if type(count_cap) is not int or count_cap < 0:
            raise ValueError("A nonnegative integer exact-count cap is required")
        self.x, self.mu, self.sigma, self.reset = map(float, (x, mu, sigma, reset))
        self.upper, self.count_cap = float(upper), count_cap
        intervals = round(upper / spacing)
        if intervals < 3:
            raise ValueError("At least two interior spatial nodes are required")
        self.h = upper / intervals
        self.positions = np.arange(1, intervals) * self.h
        self.size, self.layers = len(self.positions) + 1, count_cap + 2
        self.up = sigma * sigma / (2 * self.h**2) + mu / (2 * self.h)
        self.down = sigma * sigma / (2 * self.h**2) - mu / (2 * self.h)
        if min(self.up, self.down) < 0:
            raise ValueError("Unresolved spatial drift: centered rates must be nonnegative")
        self.reset_law = self.atom(reset)
        self.initial_law = self.atom(reset if x == 0 else x)
        self.operator = self._operator(self.layers, self.up, self.down, self.reset_law)
        self.state = np.zeros(self.layers * self.size + 1)
        initial_layer = int(x == 0)
        start = initial_layer * self.size
        self.state[start:start + self.size - 1] = self.initial_law
        self.state[-1] = initial_layer
        self.time = 0.0

    def atom(self, position):
        coordinate = position / self.h - 1
        if coordinate < -1e-12 or coordinate > len(self.positions) - 1 + 1e-12:
            raise ValueError("Interior atoms must be resolved between the first and last grid nodes")
        coordinate = min(max(coordinate, 0.0), len(self.positions) - 1.0)
        left = min(math.floor(coordinate), len(self.positions) - 2)
        law = np.zeros_like(self.positions)
        law[left:left + 2] = (left + 1 - coordinate, coordinate - left)
        return law

    def atom_derivative(self, position):
        coordinate = position / self.h - 1
        if abs(coordinate - round(coordinate)) < 1e-10:
            raise ValueError("Ordinary interpolation derivative is undefined at a spatial knot")
        self.atom(position)
        derivative = np.zeros_like(self.positions)
        left = math.floor(coordinate)
        derivative[left:left + 2] = (-1 / self.h, 1 / self.h)
        return derivative

    def _operator(self, layers, up, down, reset_law):
        rows, columns, data = [], [], []
        n, count_index = self.size - 1, layers * self.size
        for layer in range(layers):
            start = layer * self.size
            destination = min(layer + 1, layers - 1) * self.size
            for i in range(n):
                rows.append(start + i); columns.append(start + i); data.append(-up - down)
                rows.append(start + i + 1); columns.append(start + i); data.append(up)
                if i:
                    rows.append(start + i - 1); columns.append(start + i); data.append(down)
            for j in np.flatnonzero(reset_law):
                rows.append(destination + j); columns.append(start); data.append(down * reset_law[j])
            rows.append(count_index); columns.append(start); data.append(down)
        return sparse.coo_matrix((data, (rows, columns)), shape=(count_index + 1,) * 2).tocsr()

    def advance_to(self, target):
        if not math.isfinite(target) or target < self.time:
            raise ValueError("A finite nondecreasing physical time is required")
        if target > self.time:
            interval = target - self.time
            matrix = interval * self.operator
            self.state = expm_multiply(matrix, self.state, traceA=matrix.diagonal().sum())
            self.time = float(target)
        return self

    def observables(self, edges):
        layers = self.state[:-1].reshape(self.layers, self.size)
        active = layers[:, :-1].sum(axis=0)
        bins = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            overlap = np.maximum(0, np.minimum(self.positions + self.h / 2, hi)
                                 - np.maximum(self.positions - self.h / 2, lo)) / self.h
            bins.append(float(active @ overlap))
        counts = layers.sum(axis=1)
        return {"time": self.time, "expected_count": float(self.state[-1]),
                "first_hit": float(1 - counts[0]), "count_pmf_with_overflow": counts.tolist(),
                "active_bins": bins, "active_mass": float(active.sum()),
                "upper_loss": float(layers[:, -1].sum()),
                "mass": float(layers.sum()), "minimum_probability": float(layers.min())}

    def count_sensitivities(self, horizon):
        """Exact finite-system tangents, x/mu/sigma/time/reset away from knots.

        Marks can be summed out for expected count. The augmented tangent
        equations differentiate the same finite generator without differencing
        its output. No claim about continuum derivatives is made here.
        """
        if self.x == 0 or not math.isfinite(horizon) or horizon < 0:
            raise ValueError("This ordinary derivative contract requires an interior initial atom")
        dx, dr = self.atom_derivative(self.x), self.atom_derivative(self.reset)
        base = self._operator(1, self.up, self.down, self.reset_law)
        dmu = self._operator(1, 1 / (2 * self.h), -1 / (2 * self.h), self.reset_law)
        dsigma = self._operator(1, self.sigma / self.h**2, self.sigma / self.h**2, self.reset_law)
        rows = np.flatnonzero(dr)
        dreset = sparse.coo_matrix((self.down * dr[rows], (rows, np.zeros(len(rows), dtype=int))),
                                  shape=base.shape).tocsr()
        derivatives = [sparse.csr_matrix(base.shape), dmu, dsigma, dreset]
        blocks = [[base if i == j else derivatives[i - 1] if i > 0 and j == 0 else None
                   for j in range(5)] for i in range(5)]
        tangent = sparse.bmat(blocks, format="csr")
        initial = np.zeros((5, self.size + 1))
        initial[0, :-2] = self.initial_law
        initial[1, :-2] = dx
        matrix = horizon * tangent
        result = expm_multiply(matrix, initial.ravel(), traceA=matrix.diagonal().sum()).reshape(initial.shape)
        time_derivative = float((base @ result[0])[-1])
        gradient = [float(result[1, -1]), float(result[2, -1]), float(result[3, -1]),
                    time_derivative, float(result[4, -1])]
        return {"expected_count": float(result[0, -1]), "gradient": gradient}

    def collapse_active_layers(self):
        """Deliberate negative control; preserve every count mass and its mean."""
        layers = self.state[:-1].reshape(self.layers, self.size)
        for layer in layers:
            mass = float(layer[:-1].sum())
            if mass > 0:
                mean = float(layer[:-1] @ self.positions / mass)
                layer[:-1] = mass * self.atom(mean)

