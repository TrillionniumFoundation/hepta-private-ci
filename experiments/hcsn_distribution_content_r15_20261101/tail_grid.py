"""Nonuniform extension of the fixed zero-delay regenerative spatial process.

This is an explicit new discretization, not the unchanged uniform R14 generator.
The fine nodes are preserved and positive coarse-tail nodes are appended.
"""

import math

import numpy as np
from scipy import sparse

from experiments.hcsn_validation_r14_20261101.numerics.zero_delay import ZeroDelayFlow


class TailGridFlow(ZeroDelayFlow):
    """Node probability masses for a locally moment-matched Markov generator."""

    def __init__(self, x, mu, sigma, reset, spacing, fine_positions=182,
                 tail_spacing=.5, upper=40., count_cap=3):
        values = (x, mu, sigma, reset, spacing, tail_spacing, upper)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Finite physical and grid parameters required")
        if x < 0 or min(sigma, reset, spacing, tail_spacing) <= 0 or fine_positions < 2:
            raise ValueError("Positive physical/grid sizes and at least two fine nodes required")
        if type(count_cap) is not int or count_cap < 0:
            raise ValueError("Nonnegative integer exact-count cap required")
        fine = spacing*np.arange(1, fine_positions+1)
        if upper <= fine[-1]+tail_spacing:
            raise ValueError("Tail upper boundary must extend past the fine grid")
        tail = np.arange(fine[-1]+tail_spacing, upper, tail_spacing)
        # Do not create a near-zero final spacing due to endpoint roundoff.
        tail = tail[upper-tail > 1e-10*tail_spacing]
        self.positions = np.r_[fine, tail]
        self.x, self.mu, self.sigma, self.reset = map(float, (x, mu, sigma, reset))
        self.h, self.upper = float(spacing), float(upper)
        self.fine_positions, self.tail_spacing = fine_positions, float(tail_spacing)
        self.count_cap, self.layers = count_cap, count_cap+2
        self.size = len(self.positions)+1
        self.left_steps = np.diff(np.r_[0., self.positions])
        self.right_steps = np.diff(np.r_[self.positions, upper])
        left, right = self.left_steps, self.right_steps
        self.up = (sigma*sigma+mu*left)/(right*(left+right))
        self.down = (sigma*sigma-mu*right)/(left*(left+right))
        if min(self.up.min(), self.down.min()) < 0:
            raise ValueError("Unresolved drift: nonuniform Markov rates must be nonnegative")
        self.reset_law = self.atom(reset)
        self.initial_law = self.atom(reset if x == 0 else x)
        self.operator = self._operator(self.layers, self.up, self.down, self.reset_law)
        self.state = np.zeros(self.layers*self.size+1)
        initial_layer = int(x == 0)
        self.state[initial_layer*self.size:(initial_layer+1)*self.size-1] = self.initial_law
        self.state[-1] = initial_layer
        self.time = 0.

    def atom(self, position):
        if position < self.positions[0] or position > self.positions[-1]:
            raise ValueError("Interior atom must be resolved inside the grid nodes")
        right = int(np.searchsorted(self.positions, position, side="right"))
        right = min(max(right, 1), len(self.positions)-1)
        left = right-1
        weight = (position-self.positions[left])/(self.positions[right]-self.positions[left])
        law = np.zeros_like(self.positions)
        law[left], law[right] = 1.-weight, weight
        return law

    def atom_derivative(self, position):
        self.atom(position)
        if np.min(np.abs(self.positions-position)) < 1e-10:
            raise ValueError("Ordinary atom derivative is undefined at a grid knot")
        right = int(np.searchsorted(self.positions, position, side="right"))
        derivative = np.zeros_like(self.positions)
        derivative[right-1:right+1] = np.array([-1., 1.])/(self.positions[right]-self.positions[right-1])
        return derivative

    def _operator(self, layers, up, down, reset_law):
        n = self.size-1
        up, down = np.broadcast_to(up, (n,)), np.broadcast_to(down, (n,))
        rows, columns, data = [], [], []
        reward = layers*self.size
        for layer in range(layers):
            start = layer*self.size
            destination = min(layer+1, layers-1)*self.size
            for index in range(n):
                rows.extend((start+index, start+index+1))
                columns.extend((start+index, start+index))
                data.extend((-up[index]-down[index], up[index]))
                if index:
                    rows.append(start+index-1); columns.append(start+index); data.append(down[index])
            for index in np.flatnonzero(reset_law):
                rows.append(destination+index); columns.append(start); data.append(down[0]*reset_law[index])
            rows.append(reward); columns.append(start); data.append(down[0])
        return sparse.coo_matrix((data, (rows, columns)), shape=(reward+1, reward+1)).tocsr()

    def observables(self, edges):
        layers = self.state[:-1].reshape(self.layers, self.size)
        active = layers[:, :-1].sum(0)
        cell_left = self.positions-self.left_steps/2
        cell_right = self.positions+self.right_steps/2
        bins = []
        for lower, upper in zip(edges[:-1], edges[1:]):
            overlap = np.maximum(0., np.minimum(cell_right, upper)-np.maximum(cell_left, lower))
            bins.append(float(active@(overlap/(cell_right-cell_left))))
        counts = layers.sum(1)
        return dict(time=self.time, expected_count=float(self.state[-1]),
            first_hit=float(1.-counts[0]), count_pmf_with_overflow=counts.tolist(),
            active_bins=bins, active_mass=float(active.sum()), upper_loss=float(layers[:, -1].sum()),
            mass=float(layers.sum()), minimum_probability=float(layers.min()))

    def count_sensitivities(self, horizon):
        raise NotImplementedError("Nonuniform physical-parameter tangents are not qualified")
