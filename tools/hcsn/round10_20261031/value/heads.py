"""Matched-capacity differentiable action-value heads; full analytic gradients."""

from dataclasses import asdict
import math
import time

import numpy as np
from scipy.special import erfc, expit

from task import ACTIONS, legal, posterior
from oracle import choose


def features(config, state):
    belief = posterior(config, state)
    row = [2 * belief - 1, config.prior, state.clock / 16,
           config.deadline / 16, state.budget_left / 8,
           state.recovery_until / 16, state.next_packet / 4,
           config.refractory_ticks / 8, *config.costs]
    for i in range(4):
        if i < len(config.packets):
            p = config.packets[i]
            row += [p.arrival / 16, p.reliability, p.failure_probability, float(i >= state.next_packet)]
        else:
            row += [0, 0, 0, 0]
    horizon = .25 + (config.deadline - state.clock) / 8
    return np.asarray(row, dtype=float), horizon


def gate(z, horizon, family):
    if family == "ordinary":
        h = expit(z)
        return h, h * (1 - h)
    if family == "matched_c1":
        d = math.log(2)
        v = erfc(d / np.sqrt(2 * horizon))
        derivative = np.sqrt(2 / (math.pi * horizon)) * np.exp(-d * d / (2 * horizon)) / 2
        slope = derivative / (v * (1 - v))
        h = expit(np.log(v / (1 - v)) + slope * z)
        return h, slope * h * (1 - h)
    if family != "analytic":
        raise ValueError(family)
    distance = np.logaddexp(0, -z)
    h = erfc(distance / np.sqrt(2 * horizon))
    derivative = (np.sqrt(2 / (math.pi * horizon))
                  * np.exp(-distance * distance / (2 * horizon)) * expit(-z))
    return h, derivative


class Head:
    def __init__(self, dimensions, width, family, seed):
        self.family = family
        self.width = width
        rng = np.random.default_rng(seed)
        self.w = rng.normal(0, .3 / np.sqrt(dimensions), (dimensions + 1, width))
        self.v = rng.normal(0, .05 / np.sqrt(width), (width + 1, 2))
        self.mean = np.zeros(dimensions)
        self.scale = np.ones(dimensions)

    @property
    def parameter_count(self):
        return self.w.size + self.v.size

    def matrix(self, x):
        normalized = (x - self.mean) / self.scale
        return np.concatenate((normalized, np.ones((len(x), 1))), axis=1)

    def predict(self, x, horizon):
        h, _ = gate(self.matrix(x) @ self.w, np.asarray(horizon).reshape(-1, 1), self.family)
        return np.concatenate((h, np.ones((len(h), 1))), axis=1) @ self.v

    def loss_gradient(self, x, horizon, targets, mask, regularization=1e-5):
        design = self.matrix(x)
        h, dh = gate(design @ self.w, np.asarray(horizon).reshape(-1, 1), self.family)
        aug = np.concatenate((h, np.ones((len(h), 1))), axis=1)
        errors = (aug @ self.v - targets) * mask
        denominator = max(float(mask.sum()), 1)
        loss = float(np.sum(errors ** 2) / denominator
                     + regularization * (np.sum(self.w ** 2) + np.sum(self.v ** 2)))
        upstream = 2 * errors / denominator
        gv = aug.T @ upstream + 2 * regularization * self.v
        gw = design.T @ ((upstream @ self.v[:-1].T) * dh) + 2 * regularization * self.w
        return loss, (gw, gv)

    def train(self, data, validation, seed, steps=1800, batch=256):
        x, horizon, targets, mask = data
        self.mean, self.scale = x.mean(axis=0), np.maximum(x.std(axis=0), .03)
        rng = np.random.default_rng(seed)
        first = [np.zeros_like(self.w), np.zeros_like(self.v)]
        second = [np.zeros_like(self.w), np.zeros_like(self.v)]
        best = (math.inf, self.w.copy(), self.v.copy(), 0)
        start_cpu, start_wall = time.process_time(), time.perf_counter()
        history = []
        for step in range(1, steps + 1):
            index = rng.integers(0, len(x), batch)
            _, gradients = self.loss_gradient(x[index], horizon[index], targets[index], mask[index])
            rate = .008 * (.2 + .8 * (1 - step / steps))
            for i, (parameter, grad) in enumerate(zip((self.w, self.v), gradients)):
                first[i] *= .9
                first[i] += .1 * grad
                second[i] *= .999
                second[i] += .001 * grad ** 2
                parameter -= rate * (first[i] / (1 - .9 ** step)) / (
                    np.sqrt(second[i] / (1 - .999 ** step)) + 1e-8)
            if step % 100 == 0:
                val, _ = self.loss_gradient(*validation, regularization=0)
                history.append({"step": step, "validation_mse": val})
                if val < best[0]:
                    best = val, self.w.copy(), self.v.copy(), step
        self.w, self.v = best[1:3]
        return {"steps": steps, "selected_step": best[3], "validation_mse": best[0],
                "training_cpu_seconds": time.process_time() - start_cpu,
                "training_wall_seconds": time.perf_counter() - start_wall, "history": history}

    def q(self, config, state):
        row, horizon = features(config, state)
        advantage = self.predict(row[None], [horizon])[0]
        belief = posterior(config, state)
        stop = max(belief, 1 - belief) - config.stop_cost
        return np.r_[advantage + stop, stop]

    def policy(self, config, state):
        return choose(self.q(config, state), legal(config, state))

    def checkpoint(self):
        return {"family": self.family, "width": self.width, "w": self.w.tolist(),
                "v": self.v.tolist(), "mean": self.mean.tolist(), "scale": self.scale.tolist()}


def gradient_check():
    rng = np.random.default_rng(830)
    data = (rng.normal(size=(7, 5)), np.linspace(.25, 1.3, 7),
            rng.normal(size=(7, 2)), np.ones((7, 2)))
    results = []
    for family in ("ordinary", "matched_c1", "analytic"):
        head = Head(5, 4, family, 3)
        _, gradients = head.loss_gradient(*data)
        errors = []
        for parameter, gradient in zip((head.w, head.v), gradients):
            for flat in range(parameter.size):
                origin = parameter.flat[flat]
                parameter.flat[flat] = origin + 1e-6
                plus = head.loss_gradient(*data)[0]
                parameter.flat[flat] = origin - 1e-6
                minus = head.loss_gradient(*data)[0]
                parameter.flat[flat] = origin
                errors.append(abs((plus - minus) / 2e-6 - gradient.flat[flat]))
        results.append({"family": family, "max_abs_error": max(errors), "coordinates": len(errors)})
    times = np.linspace(.25, 2.25, 17)[:, None]
    a, da = gate(np.zeros_like(times), times, "analytic")
    b, db = gate(np.zeros_like(times), times, "matched_c1")
    assert max(r["max_abs_error"] for r in results) < 1e-7
    assert np.max(abs(a - b)) < 1e-14 and np.max(abs(da - db)) < 1e-14
    return {"gradients": results, "matched_value_error": float(np.max(abs(a-b))),
            "matched_slope_error": float(np.max(abs(da-db)))}
