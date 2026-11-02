"""Original renewal observation boundary with persistent and packet forecasts."""

import copy
import importlib.util
from pathlib import Path
import sys

import numpy as np


def load_physics(output):
    path = Path(output) / "source_snapshot/physics.py"
    spec = importlib.util.spec_from_file_location("hcsn_v10_frozen_renewal", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def packet(now, dt, observation, physics, read=False):
    # Only the last accepted observation is carried; no current hidden path.
    return np.array([dt, read, observation["has_read"], observation["x"],
        observation["refractory_remaining"], *observation["content_probs"],
        now - observation["time"], physics.nu, physics.sigma, physics.reset,
        physics.refractory, now], dtype=float)


def initial_observation(x, classes=5):
    return {"time": 0., "x": x, "refractory_remaining": 0.,
            "content_probs": [1 / classes] * classes, "has_read": False}


def reveal(episode, tick, config):
    # This function belongs to the executor. Policies never receive an episode.
    path = episode["path"]
    return {"time": tick * config.dt, "x": path["x"][tick],
        "refractory_remaining": path["refractory_remaining"][tick],
        "content_probs": np.eye(config.classes)[path["content"][tick]].tolist(),
        "has_read": True}


class View:
    def __init__(self, physics_module, physics, config, initial_x, family, model=None):
        self.module, self.physics, self.config = physics_module, physics, config
        self.family, self.model = family, model
        self.observation = initial_observation(initial_x, config.classes)
        self.history = [copy.deepcopy(self.observation)]
        self.tick = -1
        self.h = None if model is None else model.zero()
        self.probability = np.full(config.classes, 1 / config.classes)

    def clone(self):
        result = copy.copy(self)
        result.observation = copy.deepcopy(self.observation)
        result.history = list(self.history)
        result.h = None if self.h is None else self.h.copy()
        result.probability = self.probability.copy()
        return result

    def advance(self, tick, observation=None):
        if tick != self.tick + 1:
            raise ValueError("A persistent view must advance exactly one tick")
        dt = 0 if tick == 0 else self.config.dt
        self.tick = tick
        if observation is not None:
            if observation["time"] != tick * self.config.dt:
                raise ValueError("READ timestamp mismatch")
            self.observation = copy.deepcopy(observation)
            self.history.append(copy.deepcopy(observation))
        if self.model is not None:
            x = packet(tick * self.config.dt, dt, self.observation, self.physics, observation is not None)
            self.h, output, _ = self.model.step(x[None], self.h)
            self.probability = output[0]
        else:
            # H reconstructs its sufficient packet from raw visible READ history.
            obs = self.observation if self.family == "analytic" else self.history[-1]
            counts, _ = self.module.renewal_counts(obs["x"], tick * self.config.dt - obs["time"],
                self.physics, obs["refractory_remaining"])
            self.probability = self.module.content_from_counts(counts, obs["content_probs"],
                self.module.transition_matrix(self.config.classes))
        return self.probability.copy()

    def forecast(self, tick):
        result = self.clone()
        while result.tick < tick:
            result.advance(result.tick + 1)
        return result.probability.copy()

    def hypothetical_read(self, arrival, observation):
        result = self.clone()
        while result.tick + 1 < arrival:
            result.advance(result.tick + 1)
        result.advance(arrival, observation)
        return result


def choose_action(view, controller, budget, simulation_seed):
    """Original one-planned-READ heuristic; accepts visible state, never a path."""
    config, module = view.config, view.module
    future = [d for d in config.deadlines if d > view.tick]
    if not future or budget <= 0:
        return "STOP", {"reason": "no_future_output_or_budget"}
    prior = {d: view.forecast(d) for d in future}
    if controller == "lightweight":
        error = float(1 - prior[future[0]].max())
        action = "READ" if error > config.light_threshold and future[0] - view.tick <= 2 else "WAIT"
        return action, {"forecast_error": error}
    obs = view.observation
    start_tick = round(obs["time"] / config.dt)
    grid = np.arange(start_tick, config.ticks + 1) * config.dt
    rng = np.random.default_rng(simulation_seed)
    matrix = module.transition_matrix(config.classes)
    samples = [module.generate_path(rng, view.physics, grid, obs["x"],
        int(rng.choice(config.classes, p=obs["content_probs"])), matrix,
        obs["refractory_remaining"]) for _ in range(config.particles)]
    baseline = sum(1 - p.max() for p in prior.values()) / len(config.deadlines)
    candidates = sorted(set([view.tick + 1] + future))
    values = []
    for arrival in candidates:
        loss = 0.
        for sample in samples:
            index = arrival - start_tick
            fake = {"time": arrival * config.dt, "x": sample["x"][index],
                    "refractory_remaining": sample["refractory_remaining"][index],
                    "content_probs": np.eye(config.classes)[sample["content"][index]].tolist(),
                    "has_read": True}
            branch = view.hypothetical_read(arrival, fake)
            for deadline in future:
                predicted = prior[deadline] if deadline < arrival else branch.forecast(deadline)
                loss += 1 - predicted.max()
        loss /= config.particles * len(config.deadlines)
        values.append({"arrival_tick": arrival, "net_value": float(baseline - loss - config.read_cost)})
    best = max(values, key=lambda r: (r["net_value"], -r["arrival_tick"]))
    action = "STOP" if best["net_value"] <= 0 else ("READ" if best["arrival_tick"] == view.tick + 1 else "WAIT")
    return action, {"candidate_values": values, "selected_arrival": best["arrival_tick"],
                    "value_scope": "original_one_planned_read_heuristic"}


def rollout(episode, config, module, family, controller, model=None):
    physics = module.Physics(**episode["calibration"]["estimated"])
    view = View(module, physics, config, episode["initial_x"], family, model)
    budget, pending, stopped = config.budget, None, False
    trace, predictions, reads = [], [], 0
    for tick in range(config.ticks + 1):
        observation = reveal(episode, tick, config) if pending == tick else None
        if pending == tick:
            pending = None
        probability = view.advance(tick, observation)
        if tick in config.deadlines:
            truth = episode["path"]["content"][tick]
            predictions.append({"tick": tick, "probabilities": probability.tolist(),
                "truth_for_scoring_only": truth, "correct": int(probability.argmax() == truth),
                "brier": float(np.sum((probability - np.eye(config.classes)[truth]) ** 2)),
                "nll": float(-np.log(max(probability[truth], 1e-12)))})
        action, detail = None, {}
        if tick < config.ticks and not stopped:
            seed = int(np.random.SeedSequence([episode["seed"], tick, 4337]).generate_state(1)[0])
            action, detail = choose_action(view, controller, budget, seed)
            if action == "READ":
                budget -= 1; reads += 1; pending = tick + 1
            if action == "STOP":
                stopped = True
        trace.append({"tick": tick, "observed": observation, "visible_observation": copy.deepcopy(view.observation),
            "probabilities": probability.tolist(), "action": action, "budget_after": budget,
            "read_reveal_tick": pending, "policy_detail": detail,
            "state": None if view.h is None else view.h[0].tolist()})
    accuracy = float(np.mean([p["correct"] for p in predictions]))
    return {"family": family, "controller": controller, "trace": trace, "predictions": predictions,
        "summary": {"accuracy": accuracy, "reads": reads, "read_cost": reads * config.read_cost,
            "net_reward": accuracy - reads * config.read_cost,
            "nll": float(np.mean([p["nll"] for p in predictions])),
            "brier": float(np.mean([p["brier"] for p in predictions]))}}
