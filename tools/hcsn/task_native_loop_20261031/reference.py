"""Independent NumPy task replay; labels are opened only after termination."""
import time

import numpy as np

from ..task_value_factorial_20261030.dataset import state_record
from ..task_value_factorial_20261030.task import ACTIONS, Bellman, ContentAdapter, Owner, score_terminal
from .model import infer, identity, validate


def play_episode(folder, policy, adapter=None, fitted_dp=False):
    """Execute model or strong fitted-law DP; return complete causal trace.

    This Python implementation is a comparison reference, never a host selector
    for native execution. Native experiments send only continue requests.
    """
    validate(policy)
    adapter = ContentAdapter() if adapter is None else adapter
    start, cpu = time.perf_counter(), time.process_time()
    owner = Owner(folder, adapter, policy["confusion"], policy["multiplier"], policy["latency_price"])
    oracle = Bellman(owner.meta, policy["confusion"], policy["multiplier"], policy["latency_price"])
    history, decisions = [], []
    controller_cpu, controller_wall, regret = 0., 0., 0.
    while not owner.terminal:
        record = state_record(owner, history)
        before, before_cpu = time.perf_counter(), time.process_time()
        if fitted_dp:
            targets = np.asarray(oracle.q(owner.job, owner.tick, owner.budget, owner.posterior))
            choice = int(np.argmax(targets))
            decision = dict(action=ACTIONS[choice], action_index=choice,
                            q=np.where(record["feasible"], targets, 0.).tolist())
        else:
            decision = infer(policy, record)
        controller_cpu += time.process_time()-before_cpu
        controller_wall += time.perf_counter()-before
        targets = np.asarray(oracle.q(owner.job, owner.tick, owner.budget, owner.posterior))
        decision_regret = float(np.max(targets)-targets[decision["action_index"]])
        regret += decision_regret
        event = owner.act(decision["action"])
        decisions.append(dict(record=record, inference=decision, fitted_law_regret=decision_regret,
                              oracle_q=np.where(record["feasible"], targets, 0.).tolist()))
        history.append(dict(driver=record["driver"], duration=event["duration"], reset=decision["action"] == "FIRE"))
    return dict(policy_sha256=identity(policy), fitted_dp=fitted_dp, events=owner.events,
                decisions=decisions, score=score_terminal(owner), counts=owner.counts,
                task_elapsed=owner.task_elapsed, fitted_law_regret=regret,
                content_times=owner.times, controller_cpu_seconds=controller_cpu,
                controller_wall_seconds=controller_wall, cpu_seconds=time.process_time()-cpu,
                wall_seconds=time.perf_counter()-start, snapshot=owner.snapshot())
