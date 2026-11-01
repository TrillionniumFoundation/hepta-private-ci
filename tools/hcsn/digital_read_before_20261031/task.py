"""Causal partial-observation task and exact DP under a fitted observation law.

No policy API accepts private labels or unread packet contents. Every elapsed
interval uses its pre-action symbol as the cell driver. Completion occurs after
that interval. Task time costs and measured host costs are distinct quantities.
"""
import copy
from functools import lru_cache
from pathlib import Path
import time

import numpy as np

from ..task_value_factorial_20261030.task import ContentAdapter, packet, save, sha

ACTIONS = ("STOP", "WAIT", "READ", "REPAIR", "SUBMIT_0", "SUBMIT_1")
PUBLIC_NAMES = ["tick_fraction", "budget_fraction", "elapsed_over_9", "charges",
                "broken", "pending", "pending_slots_over_2", "last_symbol",
                "last_reliability", "latency_price", "repair_price", "failure_probability"]
PUBLIC_NAMES += [f"slot_{i}_{name}" for i in range(6)
                 for name in ("duration_over_2", "reliability", "read_price", "delay_over_2")]


def validate_public(p):
    if p["schema"] != "digital-read-before-public-v1" or p["deadline"] != 6 or p["initial_budget"] != 3:
        raise ValueError("incompatible task schema or dimensions")
    for key in ("duration", "reliability", "read_price", "read_delay", "packets", "packet_sha256"):
        if len(p[key]) != 6:
            raise ValueError((key, "requires six entries"))
    if not all(0 < x <= 2 for x in p["duration"]):
        raise ValueError("duration outside kernel domain")
    if not all(0.5 <= x <= 1 for x in p["reliability"]) or not all(x in (1, 2) for x in p["read_delay"]):
        raise ValueError("invalid observation law")
    if not all(np.isfinite(x) and x >= 0 for x in p["read_price"] + [p["latency_price"], p["repair_price"]]):
        raise ValueError("fees must be finite and nonnegative")
    if not 0 <= p["failure_probability"] <= 1:
        raise ValueError("invalid failure probability")
    if not all(Path(x).name == x and x not in ("", ".", "..") for x in p["packets"]):
        raise ValueError("packet paths must be local names")
    if not all(len(x) == 64 and set(x) <= set("0123456789abcdef") for x in p["packet_sha256"]):
        raise ValueError("packet digest must be lowercase SHA256")
    return p


def initial(public):
    validate_public(public)
    return dict(tick=0, budget=3, pending=None, broken=False, last_symbol=0,
                last_reliability=0.5, history=[], elapsed=0., charges=0.,
                terminal=False, submitted=None)


def legal(public, state):
    if state["terminal"]:
        return [False] * 6
    tick = state["tick"]
    before = tick < public["deadline"]
    read = (before and state["budget"] > 0 and not state["broken"]
            and state["pending"] is None and tick + public["read_delay"][tick] <= 6)
    return [True, before, read, before and state["broken"], True, True]


def due_request(public, state, action):
    """Return the source slot whose content becomes available after this action."""
    if not isinstance(action, int) or not 0 <= action < 6 or not legal(public, state)[action]:
        raise ValueError("illegal action (state remains unchanged)")
    if action in (0, 4, 5):
        return None
    pending = state["pending"]
    if action == 2:
        pending = dict(source_tick=state["tick"], due_tick=state["tick"] + public["read_delay"][state["tick"]])
    return pending["source_tick"] if pending and pending["due_tick"] == state["tick"] + 1 else None


def successor(public, state, action, completion=None):
    """Pure full successor. A due read requires {observation:0/1} or {failure:True}."""
    source = due_request(public, state, action)
    if source is None and completion is not None:
        raise ValueError("unsolicited content completion")
    if source is not None and completion is None:
        raise ValueError("due read requires a complete outcome")
    s = copy.deepcopy(state)
    if action in (0, 4, 5):
        s.update(terminal=True, submitted=None if action == 0 else action - 4, pending=None)
        return s
    t = s["tick"]
    if action == 2:
        s["budget"] -= 1
        s["charges"] += public["read_price"][t]
        s["pending"] = dict(source_tick=t, due_tick=t + public["read_delay"][t])
    elif action == 3:
        s["broken"] = False
        s["charges"] += public["repair_price"]
    s["tick"] += 1
    s["elapsed"] += public["duration"][t]
    s["charges"] += public["latency_price"] * public["duration"][t]
    if source is not None:
        s["pending"] = None
        if completion.get("failure", False):
            s["broken"] = True
        else:
            y = completion.get("observation")
            if y not in (0, 1):
                raise ValueError("completion must contain binary observation")
            reliability = public["reliability"][source]
            s["history"].append(dict(source_tick=source, observation=y, reliability=reliability))
            s.update(last_symbol=2*y-1, last_reliability=reliability)
    return s


def public_features(public, state):
    pending = state["pending"]
    v = [state["tick"]/6, state["budget"]/3, state["elapsed"]/9, state["charges"],
         float(state["broken"]), float(pending is not None),
         (pending["due_tick"]-state["tick"])/2 if pending else 0.,
         state["last_symbol"], state["last_reliability"], public["latency_price"],
         public["repair_price"], public["failure_probability"]]
    for i in range(6):
        v += [public["duration"][i]/2, public["reliability"][i],
              public["read_price"][i], public["read_delay"][i]/2]
    return np.asarray(v, dtype=np.float64)


def history_features(state):
    result = np.zeros(12, dtype=np.float64)
    for observation in state["history"]:
        i = observation["source_tick"]
        result[i] = 2*observation["observation"]-1
        result[6+i] = 2*observation["reliability"]-1
    return result


def posterior(public, state, confusion):
    """Teacher/reference-only sufficient statistic from completed observations."""
    p = 0.5
    confusion = np.asarray(confusion)
    for item in state["history"]:
        r = public["reliability"][item["source_tick"]]
        law = r*confusion + (1-r)*confusion[::-1]
        y = item["observation"]
        denominator = (1-p)*law[0, y] + p*law[1, y]
        if denominator <= 0:
            raise ValueError("observation impossible under fitted law")
        p = p*law[1, y]/denominator
    return float(p)


class Oracle:
    """Finite-horizon Bellman oracle under TRAIN-fitted confusion, gamma=1.

    This is not knowledge of unread packets and not an optimum under an unknown
    true FullHX law. Cached state keys contain only completed observations.
    """
    def __init__(self, public, confusion):
        self.public = validate_public(public)
        self.confusion = np.asarray(confusion, dtype=np.float64)
        if self.confusion.shape != (2, 2) or np.any(self.confusion <= 0) or not np.allclose(self.confusion.sum(1), 1):
            raise ValueError("positive row-stochastic fitted confusion required")
        self._value = lru_cache(None)(self._uncached_value)

    def key(self, s):
        pending = s["pending"]
        return (s["tick"], s["budget"], None if pending is None else
                (pending["source_tick"], pending["due_tick"]), s["broken"],
                tuple((x["source_tick"], x["observation"]) for x in s["history"]))

    def _state(self, key):
        tick, budget, pending, broken, history = key
        s = initial(self.public)
        s.update(tick=tick, budget=budget, broken=broken,
                 pending=None if pending is None else dict(source_tick=pending[0], due_tick=pending[1]),
                 elapsed=sum(self.public["duration"][:tick]),
                 history=[dict(source_tick=t, observation=y, reliability=self.public["reliability"][t]) for t, y in history])
        if history:
            t, y = history[-1]
            s.update(last_symbol=2*y-1, last_reliability=self.public["reliability"][t])
        return s

    def _uncached_value(self, key):
        return float(np.max(self.q(self._state(key))))

    def q(self, state):
        if state["terminal"]:
            raise ValueError("no actions after termination")
        p = posterior(self.public, state, self.confusion)
        result = np.full(6, -np.inf)
        for action, allowed in enumerate(legal(self.public, state)):
            if not allowed:
                continue
            if action in (0, 4, 5):
                result[action] = 0 if action == 0 else (1-2*p if action == 4 else 2*p-1)
                continue
            source = due_request(self.public, state, action)
            outcomes = [(1., None)]
            if source is not None:
                r, failure = self.public["reliability"][source], self.public["failure_probability"]
                law = r*self.confusion+(1-r)*self.confusion[::-1]
                predictive = (1-p)*law[0]+p*law[1]
                outcomes = [(failure, {"failure": True})] + [((1-failure)*float(predictive[y]), {"observation": y}) for y in (0, 1)]
            value = 0.
            for probability, outcome in outcomes:
                if probability == 0:
                    continue
                s = successor(self.public, state, action, outcome)
                fee = s["charges"]-state["charges"]
                value += probability*(self._value(self.key(s))-fee)
            result[action] = value
        return result


def fixed_action(state, mask, belief):
    submit = 5 if belief > 0.5 else 4
    if max(belief, 1-belief) >= 0.8 or state["tick"] == 6 or (state["budget"] == 0 and state["pending"] is None):
        return submit
    if mask[3]:
        return 3
    if mask[2]:
        return 2
    return 1 if mask[1] else submit


class Owner:
    """Python actual-content executor for behavior data and reference evaluation."""
    def __init__(self, public, folder, adapter):
        self.public, self.folder, self.adapter = validate_public(public), Path(folder), adapter
        self.state, self.receipts = initial(public), []

    def step(self, action):
        before = copy.deepcopy(self.state)
        source = due_request(self.public, before, action)
        completion, content = None, None
        wall, cpu = time.perf_counter(), time.process_time()
        if source is not None:
            try:
                content = self.adapter.read(self.folder / self.public["packets"][source])
                if content["payload_sha256"] != self.public["packet_sha256"][source]:
                    raise ValueError("packet digest mismatch")
                completion = dict(observation=content["observation"])
            except (OSError, ValueError, FloatingPointError, KeyError, TypeError,
                    OverflowError, IndexError, np.linalg.LinAlgError) as error:
                completion = dict(failure=True)
                content = dict(failure=type(error).__name__, error=str(error))
        self.state = successor(self.public, before, action, completion)
        row = dict(before=before, action=action, after=copy.deepcopy(self.state),
                   source_opened=source, completion=completion, content=content,
                   wall_seconds=time.perf_counter()-wall, cpu_seconds=time.process_time()-cpu)
        self.receipts.append(row)
        return row


def evaluate_terminal(state, label):
    if not state["terminal"] or label not in (0, 1):
        raise ValueError("terminal state and evaluator-only label required")
    reward = 0 if state["submitted"] is None else (1 if state["submitted"] == label else -1)
    return dict(reward=reward, utility=reward-state["charges"], charges=state["charges"],
                correct=float(state["submitted"] == label), submitted=state["submitted"] is not None,
                reads_requested=3-state["budget"], reads_completed=len(state["history"]), elapsed=state["elapsed"])
