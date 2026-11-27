"""Development-only task validation with a separately coded explicit-state DP."""

from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
from itertools import product
import json
import math
from pathlib import Path
import time

import numpy as np

from .task import (ACTION_DIGITS, MAX_STEPS, Oracle, OutputPulseQueue, Scenario,
                   legal_actions, make_scenario, rollout, settle_output_pulses,
                   state_features, transition)


def independent_oracle(s):
    """Explicit absolute deadlines; no environment transition/mask helpers."""
    times = {0., .25, .5, 1., 1.5, 2., 2.5, 3., 3.5, 3.75, 4.,
             s.shock_time, s.refill_time}
    for initial in s.deadlines:
        due = initial
        while due < 4 - 1e-9:
            times.add(round(due, 8))
            due += 2
    times = tuple(sorted(times))
    assert times == s.events()
    initial_deadlines = tuple(d if (s.initial_live >> i) & 1 else -1
                              for i, d in enumerate(s.deadlines))

    @lru_cache(None)
    def value(index, deadlines, budget):
        now = times[index]
        if abs(now-s.shock_time) < 1e-9:
            budget = max(0, budget-s.shock_amount)
        if abs(now-s.refill_time) < 1e-9:
            budget += s.refill_amount
        if now == 4:
            return 0.
        if now == 0:
            return value(index+1, deadlines, budget)
        choices = []
        for deadline in deadlines:
            if deadline < 0:
                choices.append((0,))
            elif abs(deadline-now) < 1e-9:
                choices.append((0, 1, 2) if now+.1 <= 4+1e-9 else (0, 1))
            else:
                assert deadline > now
                choices.append((0, 2) if now+.1 <= 4+1e-9 else (0,))
        best = -math.inf
        for digits in product(*choices):
            cost = sum(digit != 0 for digit in digits)
            if cost > budget:
                continue
            changed = list(deadlines)
            reward = 0.
            for item, digit in enumerate(digits):
                if digit == 2:
                    reward += .75*s.values[item]*math.exp(-.15*(4-now))
                    changed[item] = -1
                elif digit == 1:
                    changed[item] += 2
                elif abs(changed[item]-now) < 1e-9:
                    changed[item] = -1
            best = max(best, reward + value(index+1, tuple(changed), budget-cost))
        return best

    result = value(0, initial_deadlines, s.budget)
    return result, value.cache_info().currsize


def action_for(digits):
    return int(np.flatnonzero((ACTION_DIGITS == digits).all(axis=1))[0])


def run_validation():
    started = time.perf_counter()
    checks = []
    rejections = []

    def record(name, condition, **data):
        if not condition:
            raise AssertionError(name)
        checks.append({"name": name, "passed": True, **data})

    def reject(name, callback):
        try:
            callback()
        except (ValueError, AssertionError, TypeError) as error:
            rejections.append({"name": name, "error": str(error)})
        else:
            raise AssertionError("Invalid input accepted: " + name)

    base = Scenario((1.2, .8, .4, .2), (1., 1., 3., 3.), 3, 2, 1)
    record("initial cue-only observation", legal_actions(base, 0, 15, 3)[0].sum() == 1)
    record("zero initial elapsed time", Oracle(base).demonstration()[1][0] == 0)
    record("full expected-value cue", np.allclose(state_features(base, 0, 15, 3)[:4],
                                                  np.asarray(base.values)*.75))
    record("later value cue is absent", not state_features(base, .25, 15, 3)[:4].any())
    demonstration = Oracle(base).demonstration()
    record("padding and event cap", demonstration[0].shape == (MAX_STEPS, 22)
           and demonstration[2].shape == (MAX_STEPS, 81)
           and not demonstration[4][demonstration[-1]:].any())

    silent = rollout(base, lambda history, dt, valid: 0, query_seed=901001)
    record("silent policy has zero expected and realized reward",
           silent["expected_utility"] == silent["realized_utility"] == silent["emissions"] == 0)

    def renew_only(history, dt, valid):
        candidates = np.flatnonzero(valid & (ACTION_DIGITS < 2).all(axis=1))
        return int(max(candidates, key=lambda index: int((ACTION_DIGITS[index] == 1).sum())))

    renewal = rollout(base, renew_only, query_seed=901001)
    record("retained unsent items have no free query reward",
           renewal["expected_utility"] == renewal["realized_utility"] == 0)
    optimum = rollout(base, use_oracle=True, query_seed=901001)
    record("feasible physical outputs have positive query utility",
           optimum["expected_utility"] > 0 and optimum["emissions"] > 0)
    record("actual identified deliveries occur after emission",
           all(p["delivered_at"] > p["emitted_at"] and p["delivered_at"] <= 4
               for p in optimum["delivered"]))
    record("budget conservation", optimum["budget_final"] == base.budget
           + optimum["refill_added"]-optimum["shock_removed"]-optimum["spent"])
    record("output IDs settle once", len({p["pulse_id"] for p in optimum["delivered"]})
           == optimum["emissions"] <= 4)

    outputs = transition(base, .25, 15, 3, action_for([2, 0, 0, 0]))[3]["outputs"]
    queue = OutputPulseQueue(base)
    queue.advance(.25)
    queue.enqueue(outputs)
    queue.advance(.3)
    restored = OutputPulseQueue.restore(base, queue.snapshot())
    record("checkpoint contains a genuinely pending output", len(restored.pending) == 1
           and not restored.delivered)
    queue.advance(.4)
    restored.advance(.4)
    record("pending delivery replay is identical", queue.snapshot() == restored.snapshot())
    duplicate = settle_output_pulses(base, outputs+outputs, [1, 1, 1, 1])
    original = settle_output_pulses(base, outputs, [1, 1, 1, 1])
    record("identical delivery replay does not double reward",
           duplicate["expected_utility"] == original["expected_utility"]
           and duplicate["realized_utility"] == original["realized_utility"]
           and duplicate["duplicate_receipts"] == 1)

    observations = []
    def fixed_policy(history, dt, valid):
        observations.append((history.copy(), dt.copy(), valid.copy()))
        choices = np.flatnonzero(valid)
        return int(choices[-1])
    first = rollout(base, fixed_policy, query_seed=901002)
    first_observations = observations.copy()
    observations.clear()
    second = rollout(base, fixed_policy, query_seed=901003)
    record("future query bits do not affect policy observations or actions",
           len(first_observations) == len(observations)
           and all(all(np.array_equal(a, b) for a, b in zip(left, right))
                   for left, right in zip(first_observations, observations))
           and first["trace"] == second["trace"])
    record("expected score is independent of realized query bits",
           first["expected_utility"] == second["expected_utility"])
    again = rollout(base, fixed_policy, query_seed=901002)
    record("observer seed makes query outcomes replayable", first["query_bits"] == again["query_bits"])

    rows = []
    development_rng = np.random.default_rng(901000)
    scenarios = [base, replace(base, deadlines=(2., 2., 2., 2.), profile="B"),
                 replace(base, budget=0, shock_amount=0, refill_amount=0),
                 replace(base, shock_time=1., refill_time=1., shock_amount=3, refill_amount=1)]
    scenarios += [make_scenario(development_rng, split="development") for _ in range(8)]
    scenarios += [make_scenario(development_rng, split="shift") for _ in range(8)]
    for index, scenario in enumerate(scenarios):
        expected, states = independent_oracle(scenario)
        actual = Oracle(scenario).value(0, scenario.initial_live, scenario.budget)
        forward = rollout(scenario, use_oracle=True, query_seed=901100+index)
        if abs(expected-actual) > 1e-10 or abs(forward["expected_utility"]-expected) > 1e-10:
            raise AssertionError("Independent explicit-deadline oracle disagreement")
        rows.append({"case": index, "expected": expected, "actual": actual,
                     "forward": forward["expected_utility"], "states": states})
    record("independent explicit-deadline DP and forward oracle agree", True,
           cases=len(rows), maximum_error=max(abs(r["expected"]-r["actual"]) for r in rows))

    a = replace(base, deadlines=(1., 3., 1., 3.), initial_live=3)
    b = replace(a, deadlines=(2., 2., 1., 3.))
    xa, xb = state_features(a, 0, 3, a.budget), state_features(b, 0, 3, b.budget)
    keep = [i for i in range(22) if not 7 <= i <= 10]
    record("strict A/B differs only in full maturity observations",
           np.array_equal(xa[keep], xb[keep]) and not np.array_equal(xa[7:11], xb[7:11]))

    reject("non-due renewal", lambda: transition(base, .25, 15, 3, action_for([1, 0, 0, 0])))
    reject("resource overdraft", lambda: transition(base, .25, 15, 0, action_for([2, 0, 0, 0])))
    reject("output absent item", lambda: transition(base, .25, 14, 3, action_for([2, 0, 0, 0])))
    reject("late output", lambda: transition(base, 3.95, 15, 3, action_for([2, 0, 0, 0])))
    reject("fractional action index", lambda: rollout(base, lambda *_: 1.5))
    reject("re-emitting settled output", lambda: queue.enqueue(outputs))
    conflicting = deepcopy(outputs)
    conflicting[0]["emitted_at"] = .5
    conflicting[0]["delivered_at"] = .6
    conflicting[0]["quality"] = math.exp(-.15*3.5)
    reject("conflicting duplicate delivery", lambda: settle_output_pulses(base, outputs+conflicting, [1]*4))
    invalid_quality = deepcopy(outputs)
    invalid_quality[0]["quality"] = 100
    reject("tampered delivery quality", lambda: settle_output_pulses(base, invalid_quality, [1]*4))
    reject("nonbinary terminal query", lambda: settle_output_pulses(base, outputs, [2, 0, 0, 0]))
    checkpoint = restored.snapshot()
    wrong_partition = deepcopy(checkpoint)
    wrong_partition["pending"] = wrong_partition["delivered"]
    wrong_partition["delivered"] = []
    reject("restored delivery partition drift", lambda: OutputPulseQueue.restore(base, wrong_partition))
    reject("changed scenario on restore", lambda: OutputPulseQueue.restore(replace(base, budget=4), checkpoint))
    return {"schema": "rrsnn-v4-task-validation-1", "all_passed": True,
            "checks": checks, "rejections": rejections, "oracle_rows": rows,
            "development_seeds_only": True, "training_or_holdout_generated": False,
            "real_future_window": False, "runtime_seconds": time.perf_counter()-started}


def main():
    result = run_validation()
    destination = Path(__file__).parent / "task_validation.json"
    destination.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"all_passed": result["all_passed"], "checks": len(result["checks"]),
                      "rejections": len(result["rejections"]), "oracle_cases": len(result["oracle_rows"]),
                      "runtime_seconds": result["runtime_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
