"""Shared finite Bellman tree with batched equal-horizon descendants."""

import sys
import time

import numpy as np

from ..addressed_decision_r15_20261101.planner import Planner
from ..support_retention_r16_20261101.compression import COLLECT, SPREAD, GROUP


def validate_rows(p, width, minimum):
    """Same scalar-reference rtol=0 probability predicate without generic isclose.

    abs(sum-1)<=2e-11 is precisely the inherited allclose(sum,1,rtol=0,
    atol=2e-11) condition. Finiteness and the inherited negative allowance
    remain explicit. Returned numeric arrays are never altered.
    """
    if (p.ndim < 1 or p.shape[-1] != width or not np.isfinite(p).all()
            or np.any(p < minimum) or not np.all(np.abs(p.sum(-1) - 1.) <= 2e-11)):
        raise ValueError("Invalid finite probability rows")
    return p


class KernelCache:
    """Bounded per-owner immutable transition/readout cache; never caches decisions."""

    def __init__(self, maximum=64):
        self.maximum, self.entries = maximum, {}
        self.hits = self.misses = 0
        self.preparation_cpu = 0.

    def get(self, law, dt):
        key = (id(law), law.identity, float(dt).hex())
        if key in self.entries:
            self.hits += 1
            return self.entries[key]
        self.misses += 1
        started = time.process_time()
        matrices = {h: law.transition(h * dt) for h in range(4)}
        rewards = {h: matrix @ law.reward for h, matrix in matrices.items()}
        for value in rewards.values():
            value.setflags(write=False)
        result = matrices, rewards
        if len(self.entries) < self.maximum:
            self.entries[key] = result
        self.preparation_cpu += time.process_time() - started
        return result

    def metrics(self):
        seen, array_bytes, python_bytes = set(), 0, 0
        def visit(value):
            nonlocal array_bytes, python_bytes
            if id(value) in seen:
                return
            seen.add(id(value))
            python_bytes += sys.getsizeof(value)
            if isinstance(value, np.ndarray):
                array_bytes += value.nbytes
            elif isinstance(value, dict):
                for key, item in value.items():
                    visit(key)
                    visit(item)
            elif isinstance(value, (tuple, list)):
                for item in value:
                    visit(item)
        visit(self.entries)
        return dict(entries=len(self.entries), maximum=self.maximum, hits=self.hits, misses=self.misses,
                    referenced_numpy_bytes=array_bytes, recursive_getsizeof_bytes=python_bytes,
                    preparation_cpu_seconds=self.preparation_cpu,
                    scope="Unique cache-referenced arrays include shared law transitions; getsizeof overlaps ndarray data and is not added to numpy bytes. Not RSS or transient planner memory.")


class BatchedPlanner(Planner):
    """Evaluate every branch, grouping WAIT/READ descendants at equal horizons.

    Uniformly impossible observations retain the same prior substitution and zero
    branch weights. Full and anchored projection points match their old planners.
    Costs, action ordering and answer tie handling are inherited without change.
    """

    def __init__(self, law, dt, read_cost=.025, refresh_cost=.07, time_price=.003,
                 projection="full", method="expm", anchored=False, cache=None):
        if method != "expm" or projection not in ("full", "block"):
            raise ValueError("Only declared full/anchored expm planning is supported")
        if not np.isfinite([dt, read_cost, refresh_cost, time_price]).all() or dt <= 0:
            raise ValueError("Invalid public prices or interval")
        if min(read_cost, refresh_cost, time_price) < 0:
            raise ValueError("Costs must be nonnegative")
        self.law, self.dt, self.projection, self.method = law, float(dt), projection, method
        self.read_cost, self.refresh_cost, self.time_price = read_cost, refresh_cost, time_price
        self.anchored = anchored
        started = time.process_time()
        if cache is None:
            self.P = {h: law.transition(h * self.dt) for h in range(4)}
            self.reward_at = {h: matrix @ law.reward for h, matrix in self.P.items()}
        else:
            self.P, self.reward_at = cache.get(law, self.dt)
        self.preparation_cpu = time.process_time() - started
        self.calls = self.belief_evaluations = 0

    def _project_many(self, arrays):
        # Only validation is batched. Every numerical product keeps its original
        # logical frame shape, so BLAS reduction order cannot change at ties.
        merged = (arrays[0].reshape(-1, 40) if len(arrays) == 1 else
                  np.concatenate([p.reshape(-1, 40) for p in arrays], axis=0))
        if self.projection == "full":
            validate_rows(merged, 40, -1e-13)
            return [p.copy() for p in arrays]
        validate_rows(merged, 40, 0.)
        packed = [p @ COLLECT for p in arrays]
        merged_packed = (packed[0].reshape(-1, 8) if len(packed) == 1 else
                         np.concatenate([p.reshape(-1, 8) for p in packed], axis=0))
        validate_rows(merged_packed, 8, 0.)
        expanded = [p @ SPREAD for p in packed]
        for p, result in zip(packed, expanded, strict=True):
            if np.any((p[..., GROUP] > 0) & (result == 0)):
                raise ValueError("Positive support is unrepresentable at this floating-point scale")
        return expanded

    def _posteriors(self, before, emission):
        likelihoods, posteriors = [], []
        for p in before:
            joint = p[:, None, :] * emission.T[None, :, :]
            likelihood = joint.sum(-1)
            posterior = np.divide(joint, likelihood[..., None], out=np.zeros_like(joint),
                                  where=likelihood[..., None] > 0)
            posterior[likelihood <= 0] = self.law.prior
            likelihoods.append(likelihood)
            posteriors.append(posterior)
        return likelihoods, self._project_many(posteriors)

    def _forest(self, frames, remaining):
        frames = [np.asarray(p, dtype=float).reshape(-1, 40) for p in frames]
        self.belief_evaluations += sum(len(p) for p in frames)
        if not remaining:
            return [np.max(p @ self.reward_at[0], axis=1)[:, None] for p in frames]
        results = []
        for p in frames:
            result = np.full((len(p), 4), -np.inf)
            result[:, 0] = np.max(p @ self.reward_at[remaining], axis=1)
            results.append(result)
        before = [p @ self.P[1] for p in frames]
        if not self.anchored:
            before = self._project_many(before)
        likelihoods, posteriors = self._posteriors(before, self.law.E_read)
        descendants = []
        for p, posterior in zip(before, posteriors, strict=True):
            descendants.extend((p, posterior.reshape(-1, 40)))
        successors = self._forest(descendants, remaining - 1)
        for index, (result, likelihood) in enumerate(zip(results, likelihoods, strict=True)):
            result[:, 1] = np.max(successors[2 * index], axis=1) - self.time_price * self.dt
            successor = np.max(successors[2 * index + 1], axis=1)
            result[:, 2] = np.sum(likelihood * successor.reshape(likelihood.shape), axis=1)
            if self.anchored:
                result[:, 2] -= self.read_cost + self.dt * self.time_price
            else:
                result[:, 2] = result[:, 2] - self.read_cost - self.dt * self.time_price
        if remaining >= 2:
            before = [p @ self.P[2] for p in frames]
            if not self.anchored:
                before = self._project_many(before)
            likelihoods, posteriors = self._posteriors(before, self.law.E_refresh)
            successors = self._forest([p.reshape(-1, 40) for p in posteriors], remaining - 2)
            for result, likelihood, successor in zip(results, likelihoods, successors, strict=True):
                result[:, 3] = np.sum(likelihood * np.max(successor, axis=1).reshape(likelihood.shape), axis=1)
                if self.anchored:
                    result[:, 3] -= self.refresh_cost + 2 * self.dt * self.time_price
                else:
                    result[:, 3] = result[:, 3] - self.refresh_cost - 2 * self.dt * self.time_price
        return results

    def _values(self, p, remaining):
        return self._forest([p], remaining)[0]
