"""Scalar finite-branch control reference and actual indexed-owner acquisition probes."""

import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from experiments.hcsn_unknown_generator_r18_20261101.posterior import Posterior
from . import controller

ROOT = Path(__file__).parent


def probabilities(state, key, indices):
    total = math.fsum(float(state.weights[i]) for i in indices)
    return [math.fsum(float(state.weights[i]) for i in indices if int(state.final[i, key]) == value) / total
            for value in range(4)]


def branch_rule(p, threshold):
    label = max(range(4), key=lambda value:p[0][value])
    confidence = min(row[label] for row in p)
    return label, confidence >= threshold


def scalar_choice(states, key, price, threshold, rectangular=False):
    all_rows = list(range(len(states[0].weights)))
    p = [probabilities(state, key, all_rows) for state in states]
    label, accepted = branch_rule(p, threshold)
    best_value = min(2 * row[label] - 1 for row in p) if accepted else 0.
    best, values = None, {"STOP":best_value}
    for column, index in enumerate(states[0].missing):
        member_values, branch_worst = [-price] * len(states), -price
        for code in sorted({int(row[column]) for row in states[0].hidden}):
            rows = [i for i, row in enumerate(states[0].hidden) if int(row[column]) == code]
            mass = [math.fsum(float(state.weights[i]) for i in rows) for state in states]
            if min(mass) <= 0:
                raise ValueError("Reference branch has no support")
            posterior = [probabilities(state, key, rows) for state in states]
            label, accepted = branch_rule(posterior, threshold)
            terms = [m * (2 * row[label] - 1) if accepted else 0.
                     for m, row in zip(mass, posterior, strict=True)]
            member_values = [a + b for a, b in zip(member_values, terms, strict=True)]
            branch_worst += min(terms)
        value = branch_worst if rectangular else min(member_values)
        values[str(index)] = value
        if value > best_value + 1e-12:
            best, best_value = index, value
    return best, values


def token(code):
    event = np.zeros(24, dtype=np.int8)
    kind, key, value = (2, 0, 0) if code == -1 else (0, code // 4, code % 4)
    event[[key, 4 + value, 12 + kind, 16]] = 1
    return event


class TracedState:
    def __init__(self, base, name, trace):
        self.base, self.name, self.trace = base, name, trace

    def __getattr__(self, name):
        return getattr(self.base, name)

    def probability(self, key):
        self.trace.append(("probability", self.name))
        return self.base.probability(key)

    def acquire(self, index, event):
        self.trace.append(("condition", self.name, index, id(event)))
        return TracedState(self.base.acquire(index, event), self.name, self.trace)

    def choose(self, key, price, threshold):
        self.trace.append(("nominal_choose", self.name))
        return self.base.choose(key, price, threshold)


class Owner:
    def __init__(self, response, trace):
        self.response, self.trace, self.calls = response, trace, 0

    def __getitem__(self, index):
        self.calls += 1
        self.trace.append(("owner", index))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class World:
    def __init__(self, price, target, owner, trace, expected_updates, forbid_target=False):
        self.price, self.target, self.owner, self.trace = price, target, owner, trace
        self.expected_updates, self.forbid_target, self.target_reads = expected_updates, forbid_target, 0

    def __getitem__(self, name):
        if name == "price":
            return self.price
        if name == "owner_events":
            return self.owner
        if name == "target":
            self.target_reads += 1
            assert not self.forbid_target
            assert sum(event[0] == "condition" for event in self.trace) == self.expected_updates
            self.trace.append(("target", self.target))
            return self.target
        raise KeyError(name)


def main():
    start = time.process_time()
    rng = np.random.default_rng(220711)
    comparisons, single_checks, order_checks, reads = 0, 0, 0, 0
    for trial in range(48):
        rows = 16 + trial % 17
        hidden = rng.integers(-1, 4, size=(rows, 3), dtype=np.int16)
        final = rng.integers(4, size=(rows, 4), dtype=np.int8)
        if trial % 2 == 0:
            final[:, 0] = np.where(hidden[:, 0] < 0, 3, hidden[:, 0])
        states = [Posterior(final, hidden, rng.dirichlet(np.full(rows, .8)), (2, 7, 11), .5) for _ in range(2)]
        for key in range(4):
            for threshold in (.51, .75, .95, .99):
                for price in (0., .02, .12, .3, .6):
                    expected, _ = scalar_choice(states, key, price, threshold)
                    actual = controller.choose(states, key, price, threshold)
                    assert actual == expected
                    assert controller.choose(states[::-1], key, price, threshold) == actual
                    comparisons += 1
                    order_checks += 1
                    reads += actual is not None
                    assert controller.choose(states[:1], key, price, threshold) == states[0].choose(key, price, threshold)[0]
                    assert scalar_choice(states[:1], key, price, threshold)[0] == states[0].choose(key, price, threshold)[0]
                    single_checks += 1
    final = np.array([[0] * 4, [1] * 4], dtype=np.int8)
    hidden = np.array([[0], [1]], dtype=np.int16)
    witness = [Posterior(final, hidden, np.array(w), (5,), .25) for w in ((.9, .1), (.1, .9))]
    fixed, fixed_values = scalar_choice(witness, 0, .3, .8)
    rectangle, rectangle_values = scalar_choice(witness, 0, .3, .8, rectangular=True)
    assert fixed == controller.choose(witness, 0, .3, .8) == 5 and rectangle is None
    assert abs(fixed_values["5"] - .7) < 1e-14 and abs(rectangle_values["5"] + .1) < 1e-14
    execution_checks, failing_receipts = 0, 0
    for list_receipt in (False, True):
        for outcome in (0, 1):
            trace = []
            states = [TracedState(state, str(i), trace) for i, state in enumerate(witness)]
            event = token(outcome)
            owner = Owner(event.tolist() if list_receipt else event, trace)
            world = World(.3, outcome, owner, trace, 2)
            snapshots = [state.weights.copy() for state in witness]
            value = controller.execute(world, states, 0, .8)
            assert owner.calls == world.target_reads == 1 and trace[-1][0] == "target"
            conditions = [event for event in trace if event[0] == "condition"]
            assert len(conditions) == 2 and conditions[0][3] == conditions[1][3]
            assert value["read_index"] == 5 and value["fee"] == .3 and abs(value["payoff"] - .7) < 1e-14
            assert abs(sum(value["probability"]) - 1) < 1e-14 and value["probability"][outcome] == 1
            assert value["accepted"] and value["correct"] and value["decision_confidence"] == 1
            assert all(np.array_equal(a, state.weights) for a, state in zip(snapshots, witness, strict=True))
            execution_checks += 1
    # Two separate policies must fetch again; sharing one receipt across model hypotheses is allowed.
    trace = []
    owner = Owner(token(0), trace)
    for _ in range(2):
        local_trace = []
        states = [TracedState(state, str(i), local_trace) for i, state in enumerate(witness)]
        world = World(.3, 0, owner, local_trace, 2)
        controller.execute(world, states, 0, .8)
    assert owner.calls == 2
    separate_policy_fetches = owner.calls
    for response in (None, np.zeros(24, dtype=np.int8), np.zeros(23, dtype=np.int8), token(2), OSError("Synthetic receipt failure")):
        trace = []
        states = [TracedState(state, str(i), trace) for i, state in enumerate(witness)]
        owner = Owner(response, trace)
        world = World(.3, 0, owner, trace, 2, forbid_target=True)
        try:
            controller.execute(world, states, 0, .8)
            raise AssertionError("Invalid issued READ succeeded")
        except controller.ReceiptFailure as error:
            assert error.read_index == 5 and error.fee == .3 and owner.calls == 1 and world.target_reads == 0
        failing_receipts += 1
    # No acquisition: proper forecast remains first normalized model; lower envelope is not substituted.
    final = np.array([[0] * 4, [0] * 4, [1] * 4, [1] * 4], dtype=np.int8)
    hidden = np.array([[0], [1], [0], [1]], dtype=np.int16)
    stable = [Posterior(final, hidden, np.array(w), (5,), .2) for w in ((.48, .48, .02, .02), (.47, .47, .03, .03))]
    trace = []
    owner = Owner(OSError("STOP must not fetch"), trace)
    states = [TracedState(state, str(i), trace) for i, state in enumerate(stable)]
    world = World(.1, 0, owner, trace, 0)
    value = controller.execute(world, states, 0, .9)
    assert value["read_index"] is None and value["fee"] == 0 and owner.calls == 0
    assert np.allclose(value["probability"], [.96, .04, 0, 0], rtol=0, atol=1e-14)
    assert abs(value["decision_confidence"] - .94) < 1e-14 and abs(value["confidence"] - .96) < 1e-14
    rejects = 0
    bad_states = [[], [stable[0], Posterior(final, hidden, stable[1].weights, (6,), .2)],
                  [witness[0], Posterior(witness[1].final, witness[1].hidden, np.array([1., 0.]), (5,), .2)]]
    for bad in bad_states:
        try:
            controller.choose(bad, 0, .3, .8)
            raise AssertionError("Unsupported ambiguity state accepted")
        except ValueError:
            rejects += 1
    for price, threshold in ((-.1, .8), (float("inf"), .8), (float("nan"), .8), (.1, .5), (.1, 1.), (.1, float("nan"))):
        try:
            controller.choose(witness, 0, price, threshold)
            raise AssertionError("Invalid controller contract accepted")
        except ValueError:
            rejects += 1
    files = {"controller.py":ROOT / "controller.py", "independent_controller_check.py":Path(__file__),
             "../hcsn_unknown_generator_r18_20261101/posterior.py":ROOT.parent / "hcsn_unknown_generator_r18_20261101/posterior.py"}
    print(json.dumps(dict(passed=True, synthetic_choice_comparisons=comparisons, synthetic_choices_with_read=reads,
        nominal_reference_checks=single_checks, ambiguity_order_invariance_checks=order_checks,
        valid_receipt_executions=execution_checks, invalid_receipt_fee_preserving_rejections=failing_receipts,
        contract_rejections=rejects, separate_policy_owner_fetches=separate_policy_fetches,
        nonrectangular_witness=dict(fixed_model_action=fixed, fixed_model_read_value=fixed_values["5"],
                                   rectangular_action=rectangle, rectangular_read_value=rectangle_values["5"]),
        normalized_first_forecast_preserved=True, target_access_after_policy_and_receipt=True,
        source_sha256={name:hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()},
        process_cpu_seconds=time.process_time() - start, world_generator_called=False,
        scope="Synthetic aligned finite beliefs; scalar fixed-member branch totals, not task generalization evidence"), sort_keys=True))


if __name__ == "__main__":
    main()
