"""Finite acquisition and committed-generation control; no streaming rollback.

The frozen v1 experiment is untouched. A terminal macroaction commits to one
supported portfolio and 0..3 deterministic refinements, then emits all four
modalities together. Every initialization/refinement/emission and acquisition
pays its modeled controller overhead. These units are not measured FLOPs.
"""

from collections import deque
from copy import copy
from dataclasses import dataclass
from functools import lru_cache
import math
import time

import numpy as np

from control import CalibrationModel, COSTS, MISSING, UNSEEN, next_preference, portfolio_grid


class InfeasibleGeneration(ValueError):
    """The remaining budget cannot satisfy the atomic four-output contract."""


@dataclass(frozen=True)
class Plan:
    value: float
    action: int
    portfolio: int | None
    depth: int | None


def _state_cache(method):
    cached = lru_cache(maxsize=None)(method)

    def evaluate(observations, budget, preference=0):
        return cached(observations, budget, preference)

    evaluate.cache_info, evaluate.cache_clear = cached.cache_info, cached.cache_clear
    return evaluate


def generation_cost(depth, controller_cost=1):
    if type(depth) is not int or not 0 <= depth <= 3:
        raise ValueError("depth must be an integer in [0, 3]")
    if type(controller_cost) is not int or controller_cost < 0:
        raise ValueError("controller_cost must be a nonnegative integer")
    return (depth + 2) * (1 + controller_cost)


def certainty_equivalent(values, probabilities, gamma):
    """Stable entropic CE over the final axis, including zero support/eta=0."""
    values = np.asarray(values, dtype=np.float64)
    probabilities = np.asarray(probabilities, dtype=np.float64)
    if (probabilities.ndim != 1 or probabilities.size == 0 or values.ndim == 0
            or values.shape[-1] != probabilities.size
            or not np.isfinite(values).all() or not np.isfinite(probabilities).all()
            or np.any(probabilities < 0)
            or not math.isclose(math.fsum(probabilities), 1.0, rel_tol=0, abs_tol=1e-12)):
        raise ValueError("finite values and a normalized nonnegative probability law required")
    if isinstance(gamma, (bool, np.bool_)) or not np.isfinite(gamma) or gamma < 0:
        raise ValueError("gamma must be finite and nonnegative")
    support = probabilities > 0
    probabilities = probabilities[support] / probabilities.sum()
    values = values[..., support]
    mean = np.sum(values * probabilities, axis=-1)
    if gamma == 0:
        return mean
    with np.errstate(over="ignore"):
        centered = -gamma * (values - mean[..., None])
    if np.all(np.abs(centered) < 1e-3):
        return mean - np.log1p(np.sum(probabilities * np.expm1(centered), axis=-1)) / gamma
    minimum = np.min(values, axis=-1, keepdims=True)
    with np.errstate(over="ignore"):
        exponent = -gamma * (values - minimum)
    return minimum[..., 0] - np.log(np.sum(probabilities * np.exp(exponent), axis=-1)) / gamma


class GenerationPlanner:
    def __init__(self, model, loss_table, portfolios=None, gamma=2.0, mode="ndu",
                 penalty=0.025, controller_cost=1):
        if not isinstance(model, CalibrationModel):
            raise ValueError("a CalibrationModel is required")
        if mode not in ("ndu", "neutral", "fixed", "myopic", "single"):
            raise ValueError("unsupported mode")
        for value in (gamma, penalty):
            if isinstance(value, (bool, np.bool_)) or not np.isfinite(value) or value < 0:
                raise ValueError("gamma and penalty must be finite and nonnegative")
        generation_cost(0, controller_cost)
        self.model = copy(model)
        self.model.joint = np.array(model.joint, dtype=np.float64, copy=True)
        self.loss = np.array(loss_table, dtype=np.float64, copy=True)
        self.portfolios = np.array(portfolio_grid() if portfolios is None else portfolios,
                                   dtype=np.float64, copy=True)
        joint, grid = self.model.joint, self.portfolios
        if (joint.shape != (8, 9, 9, 9, 9) or not np.isfinite(joint).all()
                or np.any(joint < 0) or not np.isclose(joint.sum(), 1.0, rtol=0, atol=1e-12)):
            raise ValueError("invalid normalized calibration law")
        if (grid.ndim != 2 or grid.shape[1] != 8 or not 9 <= len(grid) <= 331
                or not np.isfinite(grid).all() or np.any(grid < 0)
                or not np.allclose(grid.sum(axis=1), 1, rtol=0, atol=1e-12)
                or not np.array_equal(grid[-1], np.full(8, 1 / 8))
                or any(not np.any(np.all(grid == pure, axis=1)) for pure in np.eye(8))):
            raise ValueError("simplex grid needs every pure concept and a final uniform fallback")
        if self.loss.shape != (4, len(grid), 8) or not np.isfinite(self.loss).all() or np.any(self.loss < 0):
            raise ValueError("loss_table must be finite nonnegative [4, portfolio, 8]")
        for array in (joint, self.loss, grid):
            array.flags.writeable = False
        self.gamma, self.mode, self.penalty = float(gamma), mode, float(penalty)
        self.controller_cost = controller_cost
        self.compile_seconds = 0.0
        # Training creates fresh planners: class-wide caches would retain every
        # old snapshot and its states. Bind the existing calibration routines
        # to per-instance caches instead.
        for name in ("posterior", "predictive"):
            method = getattr(CalibrationModel, name).__wrapped__.__get__(self.model)
            setattr(self.model, name, lru_cache(maxsize=None)(method))
        self.candidates = lru_cache(maxsize=None)(self.candidates)
        for name in ("generate", "solve"):
            setattr(self, name, _state_cache(getattr(self, name)))

    @property
    def state_count(self):
        return self.solve.cache_info().currsize

    def compile(self, budgets):
        started = time.perf_counter()
        first_report_law = self.model.joint.sum(axis=(0, 2, 3, 4))
        for budget in budgets:
            for report, probability in enumerate(first_report_law):
                if probability > 0:
                    self.solve((report, -1, -1, -1), budget, 0)
        self.compile_seconds += time.perf_counter() - started
        return self.state_count

    def risk_aversion(self, preference):
        return (0.0 if self.mode == "neutral" else self.gamma * (1 + preference)
                if self.mode in ("ndu", "myopic") else self.gamma)

    def _validate_state(self, observations, budget, preference):
        if (type(observations) is not tuple or len(observations) != 4
                or any(type(x) is not int or not UNSEEN <= x <= MISSING for x in observations)
                or observations[0] == UNSEEN
                or type(budget) is not int or not 0 <= budget <= 64
                or type(preference) is not int or not 0 <= preference <= 3):
            raise ValueError("invalid public observations, bounded budget, or preference")
        if budget < generation_cost(0, self.controller_cost):
            raise InfeasibleGeneration("cannot initialize and emit the required four-output bundle")
        with np.errstate(divide="ignore", invalid="ignore"):
            posterior = self.model.posterior(observations)
        if not np.isfinite(posterior).all():
            raise ValueError("observation history has zero probability")

    def candidates(self, observations):
        present = {x for x in observations if 0 <= x < 8}
        if not present:
            return (len(self.portfolios) - 1,)
        allowed = np.all(self.portfolios[:, sorted(set(range(8)) - present)] == 0, axis=1)
        if self.mode == "single":
            allowed &= np.count_nonzero(self.portfolios, axis=1) == 1
        return tuple(int(i) for i in np.flatnonzero(allowed))

    def generate(self, observations, budget, preference=0):
        self._validate_state(observations, budget, preference)
        choices = self.candidates(observations)
        best = None
        for depth in range(4):
            cost = generation_cost(depth, self.controller_cost)
            if cost > budget:
                continue
            utilities = certainty_equivalent(-self.loss[depth, list(choices)],
                        self.model.posterior(observations), self.risk_aversion(preference))
            index = int(np.argmax(utilities))
            plan = Plan(float(utilities[index]) - self.penalty * cost, -1, choices[index], depth)
            if best is None or plan.value > best.value + 1e-12:
                best = plan
        return best

    def solve(self, observations, budget, preference=0):
        """Finite DP, with a 1e-12 improvement threshold for depth/action ties.

        Within each depth, portfolios use exact floating argmax and stable
        first-index ties. Claims of optimality retain this numerical tolerance.
        """
        best = self.generate(observations, budget, preference)
        for modality in (1, 2, 3):
            cost = COSTS[modality] + self.controller_cost
            if observations[modality] != UNSEEN or budget - cost < generation_cost(0, self.controller_cost):
                continue
            probabilities, children = [], []
            for outcome, probability in enumerate(self.model.predictive(observations, modality)):
                if probability <= 0:
                    continue
                child = list(observations)
                child[modality] = outcome
                state = (tuple(child), budget - cost, next_preference(preference, observations, outcome))
                evaluator = self.generate if self.mode == "myopic" else self.solve
                probabilities.append(float(probability))
                children.append(evaluator(*state).value)
            value = float(certainty_equivalent(children, probabilities, self.risk_aversion(preference)))
            value -= self.penalty * cost
            if value > best.value + 1e-12:
                best = Plan(value, modality, None, None)
        if self.mode == "myopic" and best.action != -1:
            # Selection is one-step; report the value of the policy actually deployed.
            values, probabilities = [], []
            for outcome, probability in enumerate(self.model.predictive(observations, best.action)):
                if probability > 0:
                    child = list(observations)
                    child[best.action] = outcome
                    values.append(self.solve(tuple(child), budget - COSTS[best.action] - self.controller_cost,
                                  next_preference(preference, observations, outcome)).value)
                    probabilities.append(float(probability))
            best = Plan(float(certainty_equivalent(values, probabilities, self.risk_aversion(preference)))
                        - self.penalty * (COSTS[best.action] + self.controller_cost), best.action, None, None)
        return best

    def evaluate_policy_torch(self, loss_tensor, observations, budget, preference=0):
        """Differentiate a fixed selected policy, with no gradient through decisions.

        Equal loss-table values reproduce solve().value. For a unique locally
        stable optimal policy this is its envelope derivative. A different
        tensor (e.g. unclipped MSE) instead differentiates that surrogate; it is
        not the gradient of the external selection objective. No global neural
        optimum or gradient through the calibration/preference law is claimed.
        """
        import torch

        if (not torch.is_tensor(loss_tensor) or tuple(loss_tensor.shape) != self.loss.shape
                or not loss_tensor.is_floating_point() or not torch.isfinite(loss_tensor).all()
                or torch.any(loss_tensor < 0)):
            raise ValueError("a finite nonnegative floating loss tensor of matching shape is required")

        def ce(values, probabilities, eta):
            p = torch.as_tensor(np.array(probabilities, copy=True), dtype=values.dtype, device=values.device)
            p = p / p.sum()
            keep = p > 0
            p, values = p[keep], values[keep]
            mean = (p * values).sum()
            if eta == 0:
                return mean
            centered = -eta * (values - mean)
            if bool(torch.max(torch.abs(centered)).detach() < 1e-3):
                return mean - torch.log1p((p * torch.expm1(centered)).sum()) / eta
            anchor = values.min()
            return anchor - torch.logsumexp(torch.log(p) - eta * (values - anchor), dim=0) / eta

        @lru_cache(maxsize=None)
        def visit(obs, remaining, pref):
            plan = self.solve(obs, remaining, pref)
            eta = self.risk_aversion(pref)
            if plan.action == -1:
                return ce(-loss_tensor[plan.depth, plan.portfolio], self.model.posterior(obs), eta) - (
                    self.penalty * generation_cost(plan.depth, self.controller_cost))
            values, probabilities = [], []
            cost = COSTS[plan.action] + self.controller_cost
            for outcome, probability in enumerate(self.model.predictive(obs, plan.action)):
                if probability > 0:
                    child = list(obs)
                    child[plan.action] = outcome
                    values.append(visit(tuple(child), remaining - cost, next_preference(pref, obs, outcome)))
                    probabilities.append(float(probability))
            return ce(torch.stack(values), probabilities, eta) - self.penalty * cost

        return visit(observations, budget, preference)


def bottom_up_reference(joint, loss_table, portfolios, roots, gamma=2.0, mode="ndu",
                        penalty=0.025, controller_cost=1):
    """Independent finite oracle: no planner, posterior, CE or preference calls.

    This reference accepts the planner-validated frozen problem arrays. It
    recomputes laws directly and uses a dependency order, not recursive policy
    selection. Values are floating CE evaluations with the same tie threshold.
    """
    data, pending, seen = {}, deque(roots), set(roots)
    minimum_cost = 2 * (1 + controller_cost)
    while pending:
        obs, remaining, pref = pending.popleft()
        if remaining < minimum_cost:
            raise InfeasibleGeneration("reference cannot satisfy output contract")
        if obs not in data:
            table = joint[(slice(None),) + tuple(slice(None) if x == -1 else x for x in obs)]
            mass = table.sum()
            if mass <= 0:
                raise ValueError("impossible reference history")
            posterior = table.sum(axis=tuple(range(1, table.ndim))) / mass
            laws = {}
            for axis, modality in enumerate([i for i, x in enumerate(obs) if x == -1], start=1):
                laws[modality] = table.sum(axis=tuple(i for i in range(table.ndim) if i != axis)) / mass
            present = {x for x in obs if x in range(8)}
            candidates = [i for i, q in enumerate(portfolios)
                          if (not present and i == len(portfolios) - 1)
                          or (present and all(q[j] == 0 for j in set(range(8)) - present)
                              and (mode != "single" or np.count_nonzero(q) == 1))]
            data[obs] = posterior, laws, candidates
        for modality, law in data[obs][1].items():
            after = remaining - COSTS[modality] - controller_cost
            if after < minimum_cost:
                continue
            for report, probability in enumerate(law):
                if probability <= 0:
                    continue
                child = list(obs)
                child[modality] = report
                step = 1 if any(x in range(8) and x != report for x in obs) else -1
                updated = pref if report == 8 else min(3, max(0, pref + step))
                state = tuple(child), after, updated
                if state not in seen:
                    pending.append(state)
                    seen.add(state)

    def aggregate(values, probabilities, eta):
        pairs = [(float(v), float(p)) for v, p in zip(values, probabilities) if p > 0]
        if eta == 0:
            return math.fsum(v * p for v, p in pairs) / math.fsum(p for _, p in pairs)
        anchor = min(v for v, _ in pairs)
        average = math.fsum(p * math.exp(-eta * (v - anchor)) for v, p in pairs)
        return anchor - math.log(average / math.fsum(p for _, p in pairs)) / eta

    result, terminal = {}, {}
    for state in sorted(seen, key=lambda s: s[0].count(-1)):
        obs, remaining, pref = state
        eta = 0 if mode == "neutral" else gamma * (1 + pref) if mode in ("ndu", "myopic") else gamma
        posterior, laws, candidates = data[obs]
        best = None
        for depth in range(4):
            cost = (depth + 2) * (controller_cost + 1)
            if cost <= remaining:
                values = [aggregate(-loss_table[depth, candidate], posterior, eta)
                          for candidate in candidates]
                selected = max(range(len(values)), key=values.__getitem__)
                value = values[selected] - penalty * cost
                if best is None or value > best.value + 1e-12:
                    best = Plan(value, -1, candidates[selected], depth)
        terminal[state] = best
        branches = {}
        for modality, law in laws.items():
            after = remaining - COSTS[modality] - controller_cost
            if after < minimum_cost:
                continue
            children, probabilities = [], []
            for report, probability in enumerate(law):
                if probability > 0:
                    child = list(obs)
                    child[modality] = report
                    step = 1 if any(x in range(8) and x != report for x in obs) else -1
                    updated = pref if report == 8 else min(3, max(0, pref + step))
                    children.append((tuple(child), after, updated))
                    probabilities.append(probability)
            branches[modality] = children, probabilities
            values = [(terminal if mode == "myopic" else result)[child].value for child in children]
            value = aggregate(values, probabilities, eta) - penalty * (COSTS[modality] + controller_cost)
            if value > best.value + 1e-12:
                best = Plan(value, modality, None, None)
        if mode == "myopic" and best.action != -1:
            children, probabilities = branches[best.action]
            value = aggregate([result[child].value for child in children], probabilities, eta)
            best = Plan(value - penalty * (COSTS[best.action] + controller_cost), best.action, None, None)
        result[state] = best
    return result
