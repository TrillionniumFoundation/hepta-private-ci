"""Causal current-at-due sensing and a fixed deadline-six target.

READ observes the hidden sign at its *completion* boundary. This is a new task
schema, not the archived static-label/source-time observation semantics. The
target is always sign(X_6), including when a policy submits earlier. Public
future drives and initial prior are common information. Teacher belief/Q never
enter the Owner or its policy-facing state.
"""
import copy
from functools import lru_cache
from pathlib import Path
import time

import numpy as np

from ..task_value_factorial_20261030.task import ContentAdapter, packet, save, sha
from ..digital_read_before_20261031.task import fixed_action
from ..digital_read_before_20261031.task import public_features as legacy_public_features

ACTIONS = ("STOP", "WAIT", "READ", "REPAIR", "SUBMIT_0", "SUBMIT_1")
SCHEMA = "joint-current-at-due-fixed-deadline-v1"


def validate_public(public):
    if (public.get("schema") != SCHEMA or public.get("deadline") != 6
            or public.get("initial_budget") != 3 or public.get("target_tick") != 6):
        raise ValueError("incompatible dynamic-task schema")
    if not isinstance(public["id"], str) or not 0 < len(public["id"]) <= 256:
        raise ValueError("bounded world id required")
    for key in ("duration", "drive", "reliability", "read_price", "read_delay",
                "packets", "packet_sha256"):
        if len(public[key]) != 6:
            raise ValueError((key, "six entries required"))
    if (not all(np.isfinite(x) and 0 < x <= 2 for x in public["duration"])
            or not all(x in (-1, 0, 1) for x in public["drive"])
            or not all(np.isfinite(x) and .5 <= x <= 1 for x in public["reliability"])
            or not all(x in (1, 2) for x in public["read_delay"])):
        raise ValueError("invalid public time, drive or observation law")
    fees = public["read_price"]+[public["latency_price"], public["repair_price"]]
    if not all(np.isfinite(x) and x >= 0 for x in fees):
        raise ValueError("nonnegative finite fees required")
    if not 0 <= public["failure_probability"] <= 1 or public["prior_distance"] not in (.125, .375, .75):
        raise ValueError("invalid missing probability or public initial prior")
    if not all(Path(x).name == x and x not in ("", ".", "..") for x in public["packets"]):
        raise ValueError("local packet names required")
    if not all(len(x) == 64 and set(x) <= set("0123456789abcdef") for x in public["packet_sha256"]):
        raise ValueError("canonical SHA256 required")
    return public


def initial(public):
    validate_public(public)
    return dict(tick=0, budget=3, pending=None, broken=False, last_symbol=0,
                last_reliability=.5, history=[], elapsed=0., charges=0.,
                terminal=False, submitted=None)


def legal(public, state):
    if state["terminal"]:
        return [False]*6
    t = state["tick"]; before = t < 6
    read = (before and state["budget"] > 0 and not state["broken"]
            and state["pending"] is None and t+public["read_delay"][t] <= 6)
    return [True, before, read, before and state["broken"], True, True]


def due_request(public, state, action):
    """Return the observation boundary 1..6; never the old request-time slot."""
    if not isinstance(action, (int, np.integer)) or not 0 <= action < 6 or not legal(public, state)[action]:
        raise ValueError("illegal action; no state or content effects")
    if action in (0, 4, 5):
        return None
    pending = state["pending"]
    if action == 2:
        pending = dict(source_tick=state["tick"], due_tick=state["tick"]+public["read_delay"][state["tick"]])
    return pending["due_tick"] if pending and pending["due_tick"] == state["tick"]+1 else None


def successor(public, state, action, completion=None):
    due = due_request(public, state, action)
    if (due is None) != (completion is None):
        raise ValueError("completion must occur exactly at a due boundary")
    if completion is not None:
        if completion.get("observation_tick") != due:
            raise ValueError("current-at-due observation time mismatch")
        if completion.get("failure", False):
            if completion.get("observation") is not None:
                raise ValueError("conflicting completion")
        elif completion.get("observation") not in (0, 1):
            raise ValueError("binary observation required")
    s = copy.deepcopy(state)
    if action in (0, 4, 5):
        s.update(terminal=True, submitted=None if action == 0 else action-4, pending=None)
        return s
    t = s["tick"]
    if action == 2:
        s["budget"] -= 1; s["charges"] += public["read_price"][t]
        s["pending"] = dict(source_tick=t, due_tick=t+public["read_delay"][t])
    elif action == 3:
        s["broken"] = False; s["charges"] += public["repair_price"]
    s["tick"] += 1; s["elapsed"] += public["duration"][t]
    s["charges"] += public["latency_price"]*public["duration"][t]
    if due is not None:
        request = s["pending"]; s["pending"] = None
        if completion.get("failure", False):
            s["broken"] = True
        else:
            y, r = int(completion["observation"]), public["reliability"][due-1]
            s["history"].append(dict(source_tick=request["source_tick"], observation_tick=due,
                                     observation=y, reliability=r))
            s.update(last_symbol=2*y-1, last_reliability=r)
    return s


def public_features(public, state):
    """43 shared features: archived public36, six exogenous drives, prior width."""
    return np.r_[legacy_public_features(public, state), public["drive"], public["prior_distance"]]


def history_features(state):
    result = np.zeros(12, dtype=np.float64)
    for item in state["history"]:
        i = item["observation_tick"]-1
        result[i] = 2*item["observation"]-1
        result[6+i] = 2*item["reliability"]-1
    return result


class Owner:
    def __init__(self, public, folder, adapter):
        self.public, self.folder, self.adapter = validate_public(public), Path(folder), adapter
        self.state, self.receipts = initial(public), []

    def step(self, action):
        before = copy.deepcopy(self.state); due = due_request(self.public, before, action)
        wall, cpu = time.perf_counter(), time.process_time()
        completion, content = None, None
        if due is not None:
            try:
                content = self.adapter.read(self.folder/self.public["packets"][due-1])
                if content["payload_sha256"] != self.public["packet_sha256"][due-1]:
                    raise ValueError("packet digest mismatch")
                if content["observation"] not in (0, 1):
                    raise ValueError("binary decoder observation required")
                completion = dict(observation=int(content["observation"]), observation_tick=due)
            except (OSError, ValueError, FloatingPointError, KeyError, TypeError,
                    OverflowError, IndexError, np.linalg.LinAlgError) as error:
                completion = dict(failure=True, observation_tick=due)
                content = dict(failure=type(error).__name__, error=str(error))
        after = successor(self.public, before, action, completion)
        row = dict(before=before, action=int(action), after=copy.deepcopy(after),
                   source_opened=None if due is None else due-1, observation_tick=due,
                   completion=completion, content=content,
                   wall_seconds=time.perf_counter()-wall, cpu_seconds=time.process_time()-cpu)
        self.state = after; self.receipts.append(row)
        return row


class Oracle:
    """DP under supplied CTMC and decoder law, not an unknown-true-law claim.

    The environment generator can be known exactly while decoder confusion is
    TRAIN-fitted. This oracle is then optimal only for that declared model.
    It is reference/target code and is never invoked by Owner or learned heads.
    """
    def __init__(self, public, law, confusion):
        self.public, self.law = validate_public(public), law
        self.confusion = np.asarray(confusion, dtype=np.float64)
        self.emissions = [law.emission(r, self.confusion) for r in public["reliability"]]
        self.transitions = [law.transition(dt, drive) for dt, drive in zip(public["duration"], public["drive"])]
        self._mass = lru_cache(None)(self._uncached_mass)
        self._value = lru_cache(None)(self._uncached_value)

    def key(self, s):
        p = s["pending"]
        return (s["tick"], s["budget"], s["broken"], None if p is None else (p["source_tick"], p["due_tick"]),
                tuple((r["source_tick"], r["observation_tick"], r["observation"]) for r in s["history"]))

    def _state(self, key):
        tick, budget, broken, pending, history = key; s = initial(self.public)
        records = [dict(source_tick=a, observation_tick=t, observation=y, reliability=self.public["reliability"][t-1]) for a, t, y in history]
        s.update(tick=tick, budget=budget, broken=broken, elapsed=sum(self.public["duration"][:tick]),
                 pending=None if pending is None else dict(source_tick=pending[0], due_tick=pending[1]), history=records)
        if records:
            s.update(last_symbol=2*records[-1]["observation"]-1, last_reliability=records[-1]["reliability"])
        return s

    def _uncached_mass(self, tick, history):
        if any(not 1 <= t <= tick or y not in (0, 1) for t, y in history) or len({t for t, _ in history}) != len(history):
            raise ValueError("noncausal observation history")
        observations = dict(history); p = self.law.initial_mass(self.public["prior_distance"])
        for t in range(tick):
            p = p @ self.transitions[t]
            if t+1 in observations:
                p = p*self.emissions[t][:, observations[t+1]]
                if p.sum() <= 0:
                    raise ArithmeticError("impossible fitted-law observation")
                p = p/p.sum()
        p.setflags(write=False)
        return p

    def belief(self, state):
        return self._mass(state["tick"], tuple((r["observation_tick"], r["observation"]) for r in state["history"]))

    def future_mass(self, state, target_tick=6):
        if not state["tick"] <= target_tick <= 6:
            raise ValueError("future boundary required")
        p = self.belief(state)
        for t in range(state["tick"], target_tick):
            p = p @ self.transitions[t]
        return p

    def posterior(self, state):
        return float(self.future_mass(state)[self.law.positive].sum())

    def bank(self, state):
        horizons = (min(6, state["tick"]+1), min(6, state["tick"]+2), 6)
        return np.array([self.future_mass(state, h)[self.law.u > k].sum()
                         for h in horizons for k in (-.5, 0., .5)])

    def _uncached_value(self, key):
        return float(np.max(self.q(self._state(key))))

    def q(self, state):
        if state["terminal"]:
            raise ValueError("no action after termination")
        p = self.posterior(state); values = np.full(6, -np.inf)
        for action, good in enumerate(legal(self.public, state)):
            if not good:
                continue
            if action in (0, 4, 5):
                values[action] = 0. if action == 0 else (1-2*p if action == 4 else 2*p-1)
                continue
            due = due_request(self.public, state, action); outcomes = [(1., None)]
            if due is not None:
                predictive = self.belief(state) @ self.transitions[state["tick"]] @ self.emissions[due-1]
                f = self.public["failure_probability"]
                outcomes = [(f, dict(failure=True, observation_tick=due))]
                outcomes += [((1-f)*float(predictive[y]), dict(observation=y, observation_tick=due)) for y in (0, 1)]
            total = 0.
            for probability, completion in outcomes:
                if probability:
                    after = successor(self.public, state, action, completion)
                    total += probability*(self._value(self.key(after))-(after["charges"]-state["charges"]))
            values[action] = total
        return values


def evaluate_terminal(state, fixed_deadline_label):
    if not state["terminal"] or fixed_deadline_label not in (0, 1):
        raise ValueError("terminal state and evaluator-only deadline-six label required")
    reward = 0 if state["submitted"] is None else (1 if state["submitted"] == fixed_deadline_label else -1)
    return dict(reward=reward, utility=reward-state["charges"], charges=state["charges"],
                correct=float(state["submitted"] == fixed_deadline_label), submitted=state["submitted"] is not None,
                reads_requested=3-state["budget"], reads_completed=len(state["history"]), elapsed=state["elapsed"])
