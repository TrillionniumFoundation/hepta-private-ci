"""Finite raw-observation task, exact history teacher and public-feature policies.

The teacher integrates possible observations; deployed controllers never receive
the teacher posterior, unobserved outcomes, labels, or counterfactual values.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, replace

import numpy as np


ACTIONS = ("STOP", "READ", "SKIP")


@dataclass(frozen=True)
class Config:
    name: str
    modalities: tuple
    dts: tuple
    q_a: float
    q_b: float
    read_cost: float
    skip_cost: float
    budget: int = 4
    prior: float = 0.5
    invalid_cost: float = 0.005

    def validate(self):
        assert 0 < len(self.modalities) == len(self.dts) <= 8
        assert all(m in ("A", "B") for m in self.modalities)
        assert all(d > 0 for d in self.dts)
        assert 0 < self.q_a < 1 and 0 < self.q_b < 1
        assert 0 < self.prior < 1 and 0 <= self.budget <= len(self.dts)
        assert min(self.read_cost, self.skip_cost, self.invalid_cost) >= 0
        return self

    def payload(self):
        return asdict(self)


def configurations():
    def make(name, order, q_a, q_b, read, skip, dts):
        return Config(name, tuple(order), tuple(dts), q_a, q_b, read, skip).validate()

    return {
        "train": [
            make("train_a", "ABABAB", .65, .75, .02, .004, [1.] * 6),
            make("train_b", "BABABA", .75, .70, .045, .003, [.75] * 6),
            make("train_c", "ABABAB", .70, .80, .06, .004, [.5, 1.5] * 3),
            make("train_d", "BABABA", .60, .65, .015, .002, [1.5, .5] * 3),
        ],
        "dev": [
            make("dev_a", "ABABAB", .70, .75, .035, .004, [1.] * 6),
            make("dev_b", "BABABA", .68, .77, .04, .006, [.75] * 6),
        ],
        "heldout": [
            make("heldout_a", "ABABAB", .72, .78, .03, .005, [.8] * 6),
            make("heldout_b", "BABABA", .62, .82, .055, .006, [.5, 1.5] * 3),
            make("heldout_c", "ABABAB", .80, .60, .025, .002, [1.2] * 6),
            make("heldout_d", "BABABA", .70, .75, .08, .004, [1.] * 6),
        ],
    }


@dataclass
class PublicState:
    h: np.ndarray
    slot: int
    budget: int
    pending_dt: float


def state_digest(state):
    digest = hashlib.sha256(np.asarray(state.h, dtype="<f8").tobytes())
    digest.update(json.dumps([state.slot, state.budget, state.pending_dt]).encode())
    return digest.hexdigest()


def probabilities(logits):
    values = np.asarray(logits, dtype=float).reshape(-1)
    values = np.exp(values - np.max(values))
    return values / values.sum()


def public_features(model, state, config):
    """A fixed feature map with no labels, posterior or observed-history object."""
    horizon = len(config.dts)
    slot = state.slot
    schedule = [float(m == "B") for m in config.modalities]
    context = [slot / horizon, state.budget / max(config.budget, 1),
               state.pending_dt, config.q_a, config.q_b, config.read_cost,
               config.skip_cost, config.prior]
    return np.concatenate([state.h.ravel(), probabilities(model.logits(state.h)),
                           context, schedule, config.dts])


def legal_actions(state, config):
    if state.slot >= len(config.dts):
        return ("STOP",)
    return ("STOP", "READ", "SKIP") if state.budget else ("STOP", "SKIP")


def after_skip(state, config):
    return PublicState(state.h.copy(), state.slot + 1, state.budget,
                       state.pending_dt + config.dts[state.slot])


def after_read(model, state, config, observation):
    h = model.step(np.asarray(observation)[None, :], state.h.copy(),
                   state.pending_dt + config.dts[state.slot])
    return PublicState(np.asarray(h), state.slot + 1, state.budget - 1, 0.)


class TeacherGraph:
    """Enumerate all causal histories and their expectation-valued successors."""

    def __init__(self, model, config, support):
        self.model, self.config, self.support = model, config.validate(), support
        self.nodes = {}
        self.root = self._visit((), PublicState(model.initial(1), 0,
                                               config.budget, 0.), config.prior)

    def _visit(self, history, state, posterior):
        pred = int(np.argmax(self.model.logits(state.h)))
        stop = posterior if pred else 1 - posterior
        node = {"history": history, "state": state, "posterior": posterior,
                "prediction": pred, "q": {"STOP": float(stop)}, "edges": {},
                "features": public_features(self.model, state, self.config)}
        self.nodes[history] = node
        legal = legal_actions(state, self.config)
        if "SKIP" in legal:
            child = history + (-1,)
            self._visit(child, after_skip(state, self.config), posterior)
            node["edges"]["SKIP"] = [(1., child, None)]
        if "READ" in legal:
            raw, likelihood = self.support(self.config.modalities[state.slot],
                                           self.config.q_a, self.config.q_b)
            assert np.allclose(likelihood.sum(axis=1), 1.)
            mixture = (1 - posterior) * likelihood[0] + posterior * likelihood[1]
            edges = []
            for index, probability in enumerate(mixture):
                child = history + (index,)
                child_posterior = posterior * likelihood[1, index] / probability
                self._visit(child, after_read(self.model, state, self.config, raw[index]),
                            float(child_posterior))
                edges.append((float(probability), child, index))
            node["edges"]["READ"] = edges
        return history

    def solve(self, read_cost=None):
        cost = self.config.read_cost if read_cost is None else float(read_cost)
        for history in sorted(self.nodes, key=len, reverse=True):
            node = self.nodes[history]
            for action, edges in node["edges"].items():
                charge = cost if action == "READ" else self.config.skip_cost
                node["q"][action] = -charge + sum(
                    probability * self.nodes[child]["value"]
                    for probability, child, _ in edges)
            node["action"] = max(ACTIONS, key=lambda a: node["q"].get(a, -np.inf))
            node["value"] = node["q"][node["action"]]
        return self.nodes[()]["value"]

    def exact_policy(self, controller):
        values, choices = {}, {}
        for history in sorted(self.nodes, key=len, reverse=True):
            node = self.nodes[history]
            action = controller.choose(self.model, node["state"], self.config)[0]
            assert action in legal_actions(node["state"], self.config)
            choices[history] = action
            values[history] = node["q"]["STOP"] if action == "STOP" else (
                -(self.config.read_cost if action == "READ" else self.config.skip_cost)
                + sum(p * values[child] for p, child, _ in node["edges"][action]))
        occupancy, regrets, read_count, skip_count = {(): 1.}, 0., 0., 0.
        for history in sorted(self.nodes, key=len):
            mass = occupancy.get(history, 0.)
            node, action = self.nodes[history], choices[history]
            regrets += mass * (node["value"] - node["q"][action])
            read_count += mass * (action == "READ")
            skip_count += mass * (action == "SKIP")
            for p, child, _ in node["edges"].get(action, []):
                occupancy[child] = occupancy.get(child, 0.) + mass * p
        gap = self.nodes[()]["value"] - values[()]
        return {"return": values[()], "oracle": self.nodes[()]["value"],
                "gap": gap, "regret_sum": regrets,
                "performance_identity_error": abs(gap - regrets),
                "expected_reads": read_count, "expected_skips": skip_count}

    def records(self):
        for history, node in self.nodes.items():
            state = node["state"]
            yield {"history": history, "posterior_teacher_only": node["posterior"],
                   "public_state": [state.slot, state.budget, state.pending_dt],
                   "state_sha256": state_digest(state), "h": state.h.tolist(),
                   "public_features": node["features"].tolist(),
                   "q": node["q"], "value": node["value"],
                   "action": node["action"], "successors": node["edges"]}


class Lightweight:
    def __init__(self, kind, parameter=0.):
        self.kind, self.parameter = kind, float(parameter)

    def choose(self, model, state, config):
        legal = legal_actions(state, config)
        if "READ" not in legal or self.kind == "stop":
            return "STOP", {}
        read_count = config.budget - state.budget
        if self.kind == "fixed":
            action = "READ" if read_count < self.parameter else "STOP"
        elif self.kind == "confidence":
            confidence = float(np.max(probabilities(model.logits(state.h))))
            action = "STOP" if confidence >= self.parameter else "READ"
        else:
            raise ValueError(self.kind)
        return action, {}

    def payload(self):
        return {"kind": self.kind, "parameter": self.parameter}


class RidgeValue:
    """Fit READ/STOP and SKIP/STOP advantages on train histories only."""

    def __init__(self, mean, scale, weights, ridge=1.):
        self.mean, self.scale = np.asarray(mean), np.asarray(scale)
        self.weights, self.ridge = np.asarray(weights), float(ridge)

    def design(self, features):
        z = np.clip((np.atleast_2d(features) - self.mean) / self.scale, -20., 20.)
        return np.concatenate([np.ones((len(z), 1)), z, z * z], axis=1)

    @classmethod
    def fit(cls, graphs, ridge=1.):
        nodes = [node for graph in graphs for node in graph.nodes.values()]
        features = np.stack([node["features"] for node in nodes])
        mean, scale = features.mean(axis=0), features.std(axis=0)
        scale[scale < 1e-8] = 1.
        model = cls(mean, scale, np.zeros((1 + 2 * features.shape[1], 2)), ridge)
        design = model.design(features)
        for column, action in enumerate(("READ", "SKIP")):
            mask = np.array([action in node["q"] for node in nodes])
            x = design[mask]
            y = np.array([node["q"][action] - node["q"]["STOP"]
                          for node in nodes if action in node["q"]])
            penalty = ridge * np.eye(x.shape[1]); penalty[0, 0] = 0.
            model.weights[:, column] = np.linalg.solve(x.T @ x + penalty, x.T @ y)
        return model

    def choose(self, model, state, config):
        estimates = self.design(public_features(model, state, config))[0] @ self.weights
        scores = {"STOP": 0., "READ": float(estimates[0]), "SKIP": float(estimates[1])}
        action = max(legal_actions(state, config), key=scores.__getitem__)
        return action, scores

    def payload(self):
        return {"kind": "ridge_value", "mean": self.mean.tolist(),
                "scale": self.scale.tolist(), "weights": self.weights.tolist(),
                "ridge": self.ridge, "targets": ["Q_READ-Q_STOP", "Q_SKIP-Q_STOP"]}


def select_lightweight(model, dev_graphs):
    candidates = [Lightweight("stop")]
    candidates += [Lightweight("fixed", k) for k in range(1, 5)]
    candidates += [Lightweight("confidence", t)
                   for t in (.5, .6, .7, .8, .9, .95, .99, 1.01)]
    scored = [{"controller": c.payload(), "mean_return": float(np.mean([
        g.exact_policy(c)["return"] for g in dev_graphs]))} for c in candidates]
    selected = max(range(len(scored)), key=lambda i: scored[i]["mean_return"])
    return candidates[selected], scored


def calibration(graph, controller):
    errors, signs, regrets = [], [], []
    for node in graph.nodes.values():
        action, scores = controller.choose(graph.model, node["state"], graph.config)
        regrets.append(node["value"] - node["q"][action])
        for candidate in ("READ", "SKIP"):
            if candidate in node["q"]:
                target = node["q"][candidate] - node["q"]["STOP"]
                errors.append((scores[candidate] - target) ** 2)
                signs.append((scores[candidate] > 0) == (target > 0))
    return {"legal_advantage_rmse": float(np.sqrt(np.mean(errors))),
            "legal_advantage_sign_accuracy": float(np.mean(signs)),
            "uniform_state_oracle_regret": float(np.mean(regrets)),
            "scope": "All reachable histories, uniform weighting; not occupancy weighting."}


def boundary_diagnostic(graph, histories=((), (0,), (-1,), (1,)), controller=None):
    """Cost-ray stopping surfaces; no smooth-pasting or scalar-voltage claim."""
    result = []
    for history in histories:
        if history not in graph.nodes:
            continue
        node = graph.nodes[history]
        if not node["edges"]:
            continue
        def advantage(cost):
            graph.solve(cost)
            return max(v for a, v in node["q"].items() if a != "STOP") - node["q"]["STOP"]
        grid = np.linspace(0., .5, 21)
        values, actions, learned = [], [], []
        for cost in grid:
            values.append(advantage(cost))
            actions.append({"cost": float(cost), "q": dict(node["q"]),
                            "oracle_action": node["action"]})
            if controller is not None:
                action, scores = controller.choose(graph.model, node["state"],
                                                    replace(graph.config, read_cost=float(cost)))
                learned.append({"cost": float(cost), "action": action, "advantages": scores})
        crossing = values[0] > 0 and values[-1] < 0
        root = None
        if crossing:
            left, right = 0., .5
            for _ in range(35):
                middle = (left + right) / 2
                if advantage(middle) > 0:
                    left = middle
                else:
                    right = middle
            root = (left + right) / 2
        result.append({"history": history, "cost_grid": grid.tolist(),
                       "continuation_advantage": values,
                       "nonincreasing": bool(np.max(np.diff(values)) <= 1e-11),
                       "crossing": crossing, "read_cost_boundary": root,
                       "residual": None if root is None else advantage(root),
                       "oracle_values_and_actions": actions,
                       "learned_public_controller": learned,
                       "kind": "Full-history task-value surface along a public cost ray."})
    graph.solve()
    return result
