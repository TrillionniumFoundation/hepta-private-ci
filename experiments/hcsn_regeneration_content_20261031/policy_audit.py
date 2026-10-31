"""Independent causal execution and finite-world audits for policy.py."""

import argparse
from dataclasses import replace
import itertools
import json
import math
import time

import numpy as np

try:
    from . import policy
except ImportError:
    import policy


class Meter:
    def __init__(self):
        self.cpu, self.wall = {}, {}

    def call(self, stage, function, *args):
        cpu, wall = time.process_time(), time.perf_counter()
        value = function(*args)
        self.cpu[stage] = self.cpu.get(stage, 0.) + time.process_time() - cpu
        self.wall[stage] = self.wall.get(stage, 0.) + time.perf_counter() - wall
        return value


class World:
    """The actor is never given this object, its hidden label or future draws."""

    def __init__(self, identifier, label, outcomes, config, support):
        self.identifier = identifier
        self._label, self._outcomes = int(label), tuple(outcomes)
        self._config, self._support = config, support
        self.accesses = []

    def read(self, slot):
        if slot in self.accesses:
            raise RuntimeError("Duplicate raw observation access")
        raw, _ = self._support(self._config.modalities[slot],
                               self._config.q_a, self._config.q_b)
        index = self._outcomes[slot]
        self.accesses.append(slot)
        return index, np.array(raw[index], copy=True)

    def score(self, prediction):
        return float(prediction == self._label)

    def manifest(self):
        return {"world_id": self.identifier, "hidden_label_evaluator_only": self._label,
                "outcomes_evaluator_only": self._outcomes}


class Oracle:
    kind = "history_oracle"


def execute(model, config, support, controller, world, graph=None, keep_trace=True):
    """Actual READ accesses raw input; SKIP and STOP cannot do so."""
    meter = Meter()
    cpu, wall = time.process_time(), time.perf_counter()
    state = policy.PublicState(meter.call("initial_state", model.initial, 1),
                               0, config.budget, 0.)
    history, charge, traces, max_state_error = (), 0., [], 0.
    for _ in range(len(config.dts) + 1):
        before_hash = meter.call("evidence_hash", policy.state_digest, state)
        if graph is not None:
            reference = graph.nodes[history]["state"]
            max_state_error = max(max_state_error, float(np.max(abs(state.h - reference.h))),
                                  abs(state.pending_dt - reference.pending_dt))
            assert state.slot == reference.slot and state.budget == reference.budget
        if isinstance(controller, Oracle):
            if graph is None:
                raise ValueError("Oracle requires history graph")
            node = graph.nodes[history]
            requested, scores = meter.call("controller", lambda: (
                node["action"], dict(node["q"])))
        else:
            requested, scores = meter.call("controller", controller.choose, model, state, config)
        legal = meter.call("guard", policy.legal_actions, state, config)
        rejected = requested not in legal
        action = "STOP" if rejected else requested
        fee = config.invalid_cost if rejected else 0.
        old_slot, old_budget, old_dt = state.slot, state.budget, state.pending_dt
        observed_index, raw_observation = None, None
        if action == "READ":
            observed_index, raw_observation = meter.call("raw_read", world.read, state.slot)
            state = meter.call("content_step", policy.after_read, model, state, config,
                               raw_observation)
            history += (observed_index,)
            fee += config.read_cost
        elif action == "SKIP":
            state = meter.call("skip_clock", policy.after_skip, state, config)
            history += (-1,)
            fee += config.skip_cost
        elif action != "STOP":
            raise ValueError(action)
        charge += fee
        after_hash = meter.call("evidence_hash", policy.state_digest, state)
        if keep_trace:
            traces.append({"slot": old_slot, "budget_before": old_budget,
                           "pending_dt_before": old_dt, "requested": requested,
                           "executed": action, "guard_rejected": rejected,
                           "fee": fee, "cumulative_fee": charge,
                           "raw_accessed": observed_index is not None,
                           "raw_outcome_index": observed_index,
                           "raw_observation": None if raw_observation is None else raw_observation.tolist(),
                           "scores": scores, "state_before_sha256": before_hash,
                           "state_after_sha256": after_hash,
                           "slot_after": state.slot, "budget_after": state.budget,
                           "pending_dt_after": state.pending_dt})
        if action == "STOP":
            logits = meter.call("stop_readout", model.logits, state.h)
            prediction = int(np.argmax(logits))
            correct = meter.call("evaluator_score", world.score, prediction)
            return {"world_id": world.identifier, "return": correct - charge,
                    "correct": correct, "fee": charge, "prediction": prediction,
                    "raw_accesses": world.accesses, "steps": traces,
                    "final_history": history, "max_graph_state_error": max_state_error,
                    "phase_cpu_seconds": meter.cpu, "phase_wall_seconds": meter.wall,
                    "total_cpu_seconds": time.process_time() - cpu,
                    "total_wall_seconds": time.perf_counter() - wall}
    raise RuntimeError("Controller failed to terminate within declared horizon")


def worlds(config, support):
    """Independent full latent-world enumeration; no Bellman transitions reused."""
    tables = [support(m, config.q_a, config.q_b)[1] for m in config.modalities]
    domains = [range(table.shape[1]) for table in tables]
    for label in (0, 1):
        prior = config.prior if label else 1 - config.prior
        for outcomes in itertools.product(*domains):
            weight = prior * math.prod(table[label, index]
                                       for table, index in zip(tables, outcomes))
            identifier = str(label) + ":" + ",".join(map(str, outcomes))
            yield weight, World(identifier, label, outcomes, config, support)


def sampled_worlds(config, support, count, seed):
    rng = np.random.default_rng(seed)
    for index in range(count):
        label = int(rng.random() < config.prior)
        outcomes = []
        for modality in config.modalities:
            _, likelihood = support(modality, config.q_a, config.q_b)
            outcomes.append(int(rng.choice(likelihood.shape[1], p=likelihood[label])))
        yield World(f"{seed}:{index}", label, outcomes, config, support)


def independent_expectation(model, config, support, controller, graph, sink=None):
    total, mass, maximum, count, accesses = 0., 0., 0., 0, 0
    cpu, wall = time.process_time(), time.perf_counter()
    for weight, world in worlds(config, support):
        outcome = execute(model, config, support, controller, world, graph,
                          keep_trace=sink is not None)
        total += weight * outcome["return"]
        mass += weight
        maximum = max(maximum, outcome["max_graph_state_error"])
        count += 1
        accesses += len(outcome["raw_accesses"])
        if sink is not None:
            sink({"weight": weight, "source": world.manifest(), "execution": outcome})
    expected = graph.nodes[()]["value"] if isinstance(controller, Oracle) else (
        graph.exact_policy(controller)["return"])
    error = abs(total - expected)
    assert abs(mass - 1) < 2e-12 and error < 2e-10 and maximum < 2e-10
    return {"worlds": count, "probability_mass": mass, "actual_expected_return": total,
            "dynamic_program_expectation": expected, "absolute_error": error,
            "max_state_error": maximum, "actual_raw_accesses": accesses,
            "cpu_seconds": time.process_time() - cpu,
            "wall_seconds": time.perf_counter() - wall}


def boundary_execution_check(model, graph, support, fitted, root_boundary, sink=None):
    """Reexecute both sides of a root cost boundary on all finite raw worlds."""
    if not root_boundary["crossing"]:
        return {"status": "No registered root crossing; none manufactured."}
    original = graph.config
    rows = []
    try:
        root = root_boundary["read_cost_boundary"]
        for side, cost in (("below", max(0., root - 1e-4)), ("above", root + 1e-4)):
            graph.config = replace(original, read_cost=cost)
            graph.solve()
            node = graph.nodes[()]
            predicted_action, predicted_scores = fitted.choose(model, node["state"], graph.config)
            def side_sink(record):
                if sink is not None:
                    sink({"boundary_side": side, "read_cost": cost, **record})
            execution = independent_expectation(model, graph.config, support, Oracle(), graph,
                                                side_sink if sink is not None else None)
            rows.append({"side": side, "read_cost": cost, "oracle_root_q": dict(node["q"]),
                         "oracle_root_action": node["action"],
                         "learned_root_action": predicted_action,
                         "learned_root_advantages": predicted_scores,
                         "learned_exact_policy": graph.exact_policy(fitted),
                         "actual_oracle_exhaustive_execution": execution})
    finally:
        graph.config = original
        graph.solve()
    return {"root": root_boundary["read_cost_boundary"], "sides": rows,
            "scope": "Cost changes only; all state transitions and raw distributions held fixed."}


def contract_checks(model, config, support):
    """Meaningful negative controls for hidden-label and future-read leakage."""
    outcomes = tuple(0 for _ in config.dts)
    fixed = policy.Lightweight("fixed", min(2, config.budget))
    first = execute(model, config, support, fixed, World("same", 0, outcomes, config, support))
    second = execute(model, config, support, fixed, World("same", 1, outcomes, config, support))
    assert first["steps"] == second["steps"]
    assert first["prediction"] == second["prediction"]
    assert first["fee"] == second["fee"]
    unseen = list(outcomes)
    for i in range(min(2, config.budget), len(unseen)):
        unseen[i] = support(config.modalities[i], config.q_a, config.q_b)[0].shape[0] - 1
    third = execute(model, config, support, fixed, World("same", 0, unseen, config, support))
    assert first["steps"] == third["steps"]

    class Always:
        def __init__(self, action):
            self.action = action

        def choose(self, *args):
            return self.action, {}

    rejected = execute(model, config, support, Always("READ"),
                       World("invalid", 0, outcomes, config, support))
    last = rejected["steps"][-1]
    assert last["guard_rejected"] and last["executed"] == "STOP"
    assert not last["raw_accessed"] and last["budget_after"] == last["budget_before"]
    assert last["fee"] == config.invalid_cost
    skipped = execute(model, config, support, Always("SKIP"),
                      World("skip", 0, outcomes, config, support))
    assert not skipped["raw_accesses"]
    assert abs(skipped["steps"][-1]["pending_dt_after"] - sum(config.dts)) < 1e-12
    return {"hidden_label_invariance": True, "unread_future_invariance": True,
            "invalid_read_no_access_or_budget_change": True,
            "invalid_attempt_fee_charged": True, "skip_accumulates_pending_dt": True,
            "scope": "Causal interface checks on finite synthetic raw observations."}


def tiny():
    class Fixture:
        def initial(self, batch):
            return np.zeros((batch, 2))

        def step(self, x, h, dt):
            z = x[:, 1] - x[:, 0] + x[:, 2]
            return np.tanh(np.exp(-.2 * dt) * h + z[:, None] * np.array([[.7, -.3]]))

        def logits(self, h):
            return np.stack([-h[:, 0], h[:, 0]], axis=1)

    def support(modality, q_a=.7, q_b=.75):
        if modality == "A":
            return np.array([[1., 0., 0.], [0., 1., 0.]]), np.array([[q_a, 1-q_a], [1-q_a, q_a]])
        return np.array([[0., 0., -1.], [0., 0., 1.]]), np.array([[q_b, 1-q_b], [1-q_b, q_b]])

    config = policy.Config("tiny_only", ("A", "B", "A"), (1., .5, 1.5),
                           .7, .75, .035, .004, budget=2)
    model = Fixture()
    graph = policy.TeacherGraph(model, config, support)
    graph.solve()
    fitted = policy.RidgeValue.fit([graph])
    controls = [policy.Lightweight("stop"), policy.Lightweight("fixed", 2),
                policy.Lightweight("confidence", .8), fitted, Oracle()]
    audits = [independent_expectation(model, config, support, c, graph) for c in controls]
    return {"scope": "Development fixture, not formal fits or heldout evidence.",
            "nodes": len(graph.nodes), "controller_audits": audits,
            "negative_controls": contract_checks(model, config, support),
            "boundaries": policy.boundary_diagnostic(graph)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tiny", action="store_true", required=True)
    args = parser.parse_args()
    print(json.dumps(tiny(), indent=2, allow_nan=False))
