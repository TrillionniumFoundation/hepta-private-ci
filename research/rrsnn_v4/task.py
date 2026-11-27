"""Identified communication pulses with independent terminal query outcomes.

This is a new task contract. Task-output pulses spend a common ledger unit;
latent neuron spikes and continuous-state updates have separately measured
compute costs. A finite decision oracle optimizes expected query utility.
"""

from dataclasses import asdict, dataclass
from functools import lru_cache
from itertools import product
import hashlib
import json
import math

import numpy as np


FEATURES = [
    "expected_query_value_cue_0", "expected_query_value_cue_1",
    "expected_query_value_cue_2", "expected_query_value_cue_3",
    "budget_over_6", "live_fraction", "mean_remaining_over_4",
    "remaining_0_over_4", "remaining_1_over_4", "remaining_2_over_4",
    "remaining_3_over_4", "live_0", "live_1", "live_2", "live_3",
    "shock_amount_cue_over_3", "shock_time_cue_over_4",
    "refill_amount_cue_over_2", "refill_time_cue_over_4", "time_over_4",
    "initial_cue", "renewal_and_output_unit_cost_over_6",
]
ACTION_DIGITS = np.asarray(list(product(range(3), repeat=4)), dtype=np.int8)
N_ACTIONS = len(ACTION_DIGITS)
MAX_STEPS = 32
EPS = 1e-9


@dataclass(frozen=True)
class Scenario:
    values: tuple[float, float, float, float]
    deadlines: tuple[float, float, float, float]
    budget: int
    shock_amount: int
    refill_amount: int
    shock_time: float = 1.5
    refill_time: float = 2.5
    horizon: float = 4.0
    renewal_period: float = 2.0
    early_penalty: float = 0.15
    delivery_latency: float = 0.1
    query_probability: float = 0.75
    initial_live: int = 15
    profile: str = "A"
    split: str = "development"

    def __post_init__(self):
        if len(self.values) != 4 or len(self.deadlines) != 4:
            raise ValueError("Exactly four padded item slots are required")
        if not all(math.isfinite(v) and v >= 0 for v in self.values):
            raise ValueError("Invalid item values")
        if not all(math.isfinite(d) and 0 < d < self.horizon for d in self.deadlines):
            raise ValueError("Initial deadlines must be inside the horizon")
        for amount in (self.budget, self.shock_amount, self.refill_amount):
            if type(amount) is not int or not 0 <= amount <= 8:
                raise ValueError("Resource amounts must be integers from zero to eight")
        if type(self.initial_live) is not int or not 0 <= self.initial_live <= 15:
            raise ValueError("Invalid initial live mask")
        if self.horizon != 4 or self.renewal_period != 2:
            raise ValueError("The frozen task uses horizon four and renewal period two")
        if self.delivery_latency != 0.1 or self.early_penalty != 0.15:
            raise ValueError("The frozen task uses latency .1 and quality penalty .15")
        if self.query_probability != 0.75:
            raise ValueError("The frozen task has public query probability .75")
        if not all(math.isfinite(t) and 0 < t < self.horizon
                   for t in (self.shock_time, self.refill_time)):
            raise ValueError("Invalid announced resource event time")
        self.events()

    def events(self):
        times = {float(t) for t in np.arange(0, self.horizon + .25, .5)}
        times.update((.25, 3.75))
        times.update((self.shock_time, self.refill_time))
        for initial in self.deadlines:
            deadline = initial
            while deadline < self.horizon - EPS:
                times.add(round(deadline, 8))
                deadline += self.renewal_period
        times = tuple(sorted(times))
        if len(times) > MAX_STEPS:
            raise ValueError("Scenario exceeds the declared observation cap")
        return times


def next_deadlines(s, time):
    initial = np.asarray(s.deadlines, dtype=float)
    multiples = np.maximum(np.ceil((time - initial - EPS) / s.renewal_period), 0)
    return initial + multiples * s.renewal_period


def exogenous(s, time, budget):
    removed = min(budget, s.shock_amount) if abs(time - s.shock_time) < EPS else 0
    budget -= removed
    added = s.refill_amount if abs(time - s.refill_time) < EPS else 0
    return budget + added, removed, added


def state_features(s, time, live, budget):
    observation = np.zeros(len(FEATURES), dtype=np.float32)
    alive = np.array([(live >> i) & 1 for i in range(4)], dtype=bool)
    remaining = np.maximum(next_deadlines(s, time) - time, 0) * alive
    if time == 0:
        observation[:4] = np.asarray(s.values) * s.query_probability
        observation[15:19] = [s.shock_amount / 3, s.shock_time / 4,
                              s.refill_amount / 2, s.refill_time / 4]
        observation[20] = 1
    observation[4:7] = [budget / 6, alive.mean(),
                        remaining[alive].mean() / 4 if alive.any() else 0]
    observation[7:11] = remaining / 4
    observation[11:15] = alive
    observation[19] = time / 4
    observation[21] = 1 / 6
    return observation


def legal_actions(s, time, live, budget):
    alive = np.array([(live >> i) & 1 for i in range(4)], dtype=bool)
    due = alive & (np.abs(next_deadlines(s, time) - time) < EPS)
    if time == 0 or time >= s.horizon - EPS:
        valid = np.zeros(N_ACTIONS, dtype=bool)
        valid[0] = True
        return valid, np.zeros(4, dtype=bool)
    can_deliver = time + s.delivery_latency <= s.horizon + EPS
    digit_ok = ((ACTION_DIGITS == 0)
                | ((ACTION_DIGITS == 1) & due[None, :])
                | ((ACTION_DIGITS == 2) & alive[None, :] & can_deliver))
    valid = digit_ok.all(axis=1) & ((ACTION_DIGITS > 0).sum(axis=1) <= budget)
    return valid, due


def transition(s, time, live, budget, action):
    if type(action) is not int or not 0 <= action < N_ACTIONS:
        raise ValueError("Action must be an integer index")
    valid, due = legal_actions(s, time, live, budget)
    if not valid[action]:
        raise ValueError("Invalid output, renewal, or budget overdraft")
    digits = ACTION_DIGITS[action]
    cost = int((digits > 0).sum())
    outputs = []
    renewals = dropped = 0
    for item in range(4):
        if digits[item] == 2:
            live &= ~(1 << item)
            quality = math.exp(-s.early_penalty * (s.horizon - time))
            outputs.append({"pulse_id": f"item:{item}", "item": item,
                            "emitted_at": float(time),
                            "delivered_at": float(time + s.delivery_latency),
                            "quality": quality})
        elif due[item] and digits[item] == 1:
            renewals += 1
        elif due[item]:
            live &= ~(1 << item)
            dropped += 1
    expected = sum(s.query_probability * s.values[pulse["item"]] * pulse["quality"]
                   for pulse in outputs)
    return live, budget - cost, expected, {
        "cost": cost, "renewals": renewals, "emissions": len(outputs),
        "dropped": dropped, "outputs": outputs,
    }


def settle_output_pulses(s, pulses, query_bits):
    """Idempotently settle identified deliveries; reject conflicting duplicates.

    Query bits are observer-only terminal outcomes. No policy is called here.
    A repeated identical delivery receipt has no second reward or cost.
    """
    bits = np.asarray(query_bits)
    if bits.shape != (4,) or not np.isin(bits, [0, 1]).all():
        raise ValueError("Four binary query outcomes are required")
    delivered = {}
    duplicates = 0
    fields = {"pulse_id", "item", "emitted_at", "delivered_at", "quality"}
    for raw in pulses:
        if set(raw) != fields or type(raw["item"]) is not int:
            raise ValueError("Malformed identified output pulse")
        item = raw["item"]
        if not 0 <= item < 4 or raw["pulse_id"] != f"item:{item}":
            raise ValueError("Output identity does not match item")
        if not ((s.initial_live >> item) & 1):
            raise ValueError("Output identifies an absent initial item")
        emitted, arrival, quality = (raw[k] for k in ("emitted_at", "delivered_at", "quality"))
        if not all(type(x) in (int, float) and math.isfinite(x)
                   for x in (emitted, arrival, quality)):
            raise ValueError("Nonfinite pulse field")
        if (emitted < 0 or arrival > s.horizon + EPS
                or abs(arrival - emitted - s.delivery_latency) > EPS
                or abs(quality - math.exp(-s.early_penalty * (s.horizon - emitted))) > 1e-12):
            raise ValueError("Invalid output timing or quality")
        previous = delivered.get(raw["pulse_id"])
        if previous is not None:
            if previous != raw:
                raise ValueError("Conflicting duplicate output identity")
            duplicates += 1
            continue
        delivered[raw["pulse_id"]] = dict(raw)
    ordered = sorted(delivered.values(), key=lambda pulse: (pulse["delivered_at"], pulse["item"]))
    expected = sum(s.query_probability * s.values[pulse["item"]] * pulse["quality"]
                   for pulse in ordered)
    realized = sum(int(bits[pulse["item"]]) * s.values[pulse["item"]] * pulse["quality"]
                   for pulse in ordered)
    return {"expected_utility": expected, "realized_utility": realized,
            "delivered": ordered, "duplicate_receipts": duplicates,
            "query_bits": bits.astype(int).tolist()}


class OutputPulseQueue:
    """Deterministic, bounded delivery queue for the common task communication."""

    def __init__(self, scenario):
        self.scenario = scenario
        self.time = 0.0
        self.pending = []
        self.delivered = []

    def enqueue(self, pulses):
        seen = {p["pulse_id"] for p in self.pending + self.delivered}
        checked = settle_output_pulses(self.scenario, pulses, [0, 0, 0, 0])
        if checked["duplicate_receipts"]:
            raise ValueError("A task action cannot emit duplicate identities")
        for pulse in checked["delivered"]:
            if pulse["pulse_id"] in seen or abs(pulse["emitted_at"] - self.time) > EPS:
                raise ValueError("Repeated output or output from a different task time")
        self.pending.extend(dict(p) for p in checked["delivered"])
        self.pending.sort(key=lambda p: (p["delivered_at"], p["item"]))

    def advance(self, time):
        if not math.isfinite(time) or not self.time <= time <= self.scenario.horizon:
            raise ValueError("Invalid delivery clock advance")
        arrivals = [p for p in self.pending if p["delivered_at"] <= time + EPS]
        self.pending = [p for p in self.pending if p["delivered_at"] > time + EPS]
        self.delivered.extend(arrivals)
        self.time = float(time)
        return [dict(p) for p in arrivals]

    def snapshot(self):
        return {"schema": "rrsnn-v4-output-queue-1", "time": self.time,
                "scenario_digest": scenario_digest(self.scenario),
                "pending": [dict(p) for p in self.pending],
                "delivered": [dict(p) for p in self.delivered]}

    @classmethod
    def restore(cls, scenario, snapshot):
        if (set(snapshot) != {"schema", "time", "scenario_digest", "pending", "delivered"}
                or snapshot["schema"] != "rrsnn-v4-output-queue-1"
                or snapshot["scenario_digest"] != scenario_digest(scenario)):
            raise ValueError("Queue identity or schema mismatch")
        queue = cls(scenario)
        time = snapshot["time"]
        if type(time) not in (int, float) or not math.isfinite(time) or not 0 <= time <= scenario.horizon:
            raise ValueError("Invalid restored queue time")
        all_pulses = snapshot["pending"] + snapshot["delivered"]
        checked = settle_output_pulses(scenario, all_pulses, [0, 0, 0, 0])
        if checked["duplicate_receipts"] or len(all_pulses) > 4:
            raise ValueError("Queue output identities must be unique and bounded")
        pending = [p for p in checked["delivered"] if p["delivered_at"] > time + EPS]
        delivered = [p for p in checked["delivered"] if p["delivered_at"] <= time + EPS]
        if pending != snapshot["pending"] or delivered != snapshot["delivered"]:
            raise ValueError("Queue delivery partition or ordering is invalid")
        if any(p["emitted_at"] > time + EPS for p in all_pulses):
            raise ValueError("Checkpoint contains a future emission")
        queue.time, queue.pending, queue.delivered = float(time), pending, delivered
        return queue


class Oracle:
    """Exact bounded decision DP for expected delivered-query utility.

    Delivery latency is deterministic and late outputs are illegal, so an
    expected output reward can be credited algebraically at the send action.
    This does not give the policy access to realized query bits.
    """

    def __init__(self, scenario):
        self.s = scenario
        self.times = scenario.events()

        @lru_cache(None)
        def value(index, live, budget_before):
            time = self.times[index]
            budget, _, _ = exogenous(scenario, time, budget_before)
            if index == len(self.times) - 1:
                return 0.0
            valid, _ = legal_actions(scenario, time, live, budget)
            best = -math.inf
            for action in np.flatnonzero(valid):
                following, remaining, reward, _ = transition(scenario, time, live, budget, int(action))
                best = max(best, reward + value(index + 1, following, remaining))
            return best

        self.value = value

    def q_values(self, index, live, budget_after):
        time = self.times[index]
        valid, _ = legal_actions(self.s, time, live, budget_after)
        values = np.full(N_ACTIONS, -np.inf)
        if index == len(self.times) - 1:
            values[0] = 0
            return values
        for action in np.flatnonzero(valid):
            following, remaining, reward, _ = transition(self.s, time, live, budget_after, int(action))
            values[action] = reward + self.value(index + 1, following, remaining)
        return values

    def demonstration(self):
        live, budget, last = self.s.initial_live, self.s.budget, 0.0
        rows = []
        actions = []
        for index, time in enumerate(self.times):
            budget, _, _ = exogenous(self.s, time, budget)
            valid, _ = legal_actions(self.s, time, live, budget)
            values = self.q_values(index, live, budget)
            optimal = valid & (values >= values.max() - 1e-9)
            action = int(np.flatnonzero(optimal)[0])
            rows.append((state_features(self.s, time, live, budget), time-last,
                         valid, optimal, bool(valid.sum() > 1)))
            actions.append(action)
            live, budget, _, _ = transition(self.s, time, live, budget, action)
            last = time
        length = len(rows)
        x = np.zeros((MAX_STEPS, 22), dtype=np.float32)
        dt = np.zeros(MAX_STEPS, dtype=np.float32)
        valid = np.zeros((MAX_STEPS, N_ACTIONS), dtype=bool)
        valid[:, 0] = True
        optimal = valid.copy()
        decision = np.zeros(MAX_STEPS, dtype=bool)
        for index, row in enumerate(rows):
            x[index], dt[index], valid[index], optimal[index], decision[index] = row
        return x, dt, valid, optimal, decision, np.asarray(actions), length


def rollout(s, policy=None, *, use_oracle=False, query_seed=901000):
    """Execute observation-only decisions, then draw the independent query.

    Policy receives history, elapsed intervals, and the current legality mask.
    The scenario, oracle values and terminal query bits are never passed to it.
    """
    if use_oracle == (policy is not None):
        raise ValueError("Choose an observation-only policy or explicit oracle mode")
    oracle = Oracle(s)
    live, budget, last = s.initial_live, s.budget, 0.0
    history, dts, pulses, trace = [], [], [], []
    queue = OutputPulseQueue(s)
    spent = removed = added = renewals = dropped = 0
    for index, time in enumerate(oracle.times):
        arrivals = queue.advance(time)
        budget, remove, add = exogenous(s, time, budget)
        removed += remove
        added += add
        history.append(state_features(s, time, live, budget))
        dts.append(time-last)
        last = time
        valid, due = legal_actions(s, time, live, budget)
        if index == len(oracle.times)-1:
            action = 0
        elif use_oracle:
            action = int(np.argmax(oracle.q_values(index, live, budget)))
        else:
            selected = policy(np.asarray(history), np.asarray(dts), valid.copy())
            if not isinstance(selected, (int, np.integer)) or isinstance(selected, bool):
                raise ValueError("Policy action must be an integer index")
            action = int(selected)
        before = budget
        live, budget, expected, info = transition(s, time, live, budget, action)
        pulses.extend(info["outputs"])
        queue.enqueue(info["outputs"])
        spent += info["cost"]
        renewals += info["renewals"]
        dropped += info["dropped"]
        trace.append({"time": time, "due": due.tolist(), "action": action,
                      "digits": ACTION_DIGITS[action].tolist(), "budget_before": before,
                      "budget_after": budget, "deliveries": arrivals,
                      "expected_output_reward": expected, **info})
    # This observer draw happens only after the final policy invocation.
    query = np.random.default_rng(query_seed).random(4) < s.query_probability
    if queue.pending or len(queue.delivered) != len(pulses):
        raise AssertionError("Every accepted task output must be delivered by the query")
    settled = settle_output_pulses(s, queue.delivered, query)
    optimum = oracle.value(0, s.initial_live, s.budget)
    utility = settled["expected_utility"]
    if budget != s.budget + added - removed - spent or budget < 0:
        raise AssertionError("Task resource conservation failed")
    if utility > optimum + 1e-8:
        raise AssertionError("Policy expected utility exceeds its expected oracle")
    return {"utility": utility, "expected_utility": utility,
            "realized_utility": settled["realized_utility"], "oracle_utility": optimum,
            "regret": max(optimum-utility, 0),
            "normalized_utility": utility/optimum if optimum > 1e-12 else 1.0,
            "spent": spent, "shock_removed": removed, "refill_added": added,
            "budget_final": budget, "renewals": renewals, "emissions": len(pulses),
            "dropped": dropped, "live_final": live,
            "retained_value": sum(s.values[i] for i in range(4) if (live >> i) & 1),
            "delivered_value": sum(s.values[p["item"]] for p in settled["delivered"]),
            "budget_violations": 0, "trace": trace, "output_queue": queue.snapshot(), **settled}


def make_scenario(rng, profile=None, split="train"):
    profile = str(rng.choice(["A", "B", "C"])) if profile is None else profile
    shifted = split in ("shift", "future")
    patterns = ({"A": [.75, 1.25, 2.75, 3.25], "B": [1.75, 1.75, 2.25, 2.25],
                 "C": [1., 1.5, 2.5, 3.]} if shifted else
                {"A": [1., 1., 3., 3.], "B": [2., 2., 2., 2.],
                 "C": [1.5, 1.5, 2.5, 2.5]})
    if profile not in patterns:
        raise ValueError("Unknown maturity profile")
    values = tuple(np.round(rng.uniform(.1 if shifted else .25,
                                        1.9 if shifted else 1.5, 4), 6))
    deadlines = np.asarray(patterns[profile])
    rng.shuffle(deadlines)
    return Scenario(values, tuple(deadlines), int(rng.integers(2, 6)),
                    int(rng.integers(1 if shifted else 0, 4 if shifted else 3)),
                    int(rng.integers(0, 3)), 1.25 if shifted else 1.5,
                    2.75 if shifted else 2.5, profile=profile, split=split)


def make_dataset(count, seed, split="train"):
    rng = np.random.default_rng(seed)
    scenarios = [make_scenario(rng, split=split) for _ in range(count)]
    records = [Oracle(s).demonstration() for s in scenarios]
    arrays = {name: np.stack([record[i] for record in records])
              for i, name in enumerate(("x", "dt", "valid", "optimal", "decision"))}
    arrays["lengths"] = np.asarray([record[-1] for record in records])
    arrays["event_mask"] = np.arange(MAX_STEPS)[None, :] < arrays["lengths"][:, None]
    return scenarios, arrays


def scenario_digest(scenario):
    encoded = json.dumps(asdict(scenario), sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()
