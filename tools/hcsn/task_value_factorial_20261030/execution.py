"""Actual policy rollouts, including an unretuned sampled-cell migration probe."""
import time

import numpy as np
from scipy.linalg import expm
from scipy.special import expit

from .cells import augmented_features, initial, physical
from .controller import ARMS, forward
from .dataset import state_record
from .propagation import flow, generator
from .task import ACTIONS, Bellman, Owner, score_terminal


def sampled_features(theta, index, driver, horizon):
    cell = physical(theta, driver)
    q, rates, _, _ = generator((cell,))
    _, expected, _, _ = flow((cell,), horizon)
    killed = q.copy()
    killed[cell.active-1, cell.active+cell.phases-1] -= rates[cell.active-1, 0]
    count = expected[index, 0]
    hit = 1-float(expm(horizon*killed)[index].sum())
    raw = np.array([(index+.5)/cell.active if index < cell.active else 0.,
                    float(index >= cell.active), count/(1+count), hit])
    return np.r_[raw, float(expit(raw@theta[6:10]+theta[10]))]


def sample_interval(theta, index, driver, duration, reset, rng):
    q, rates, _, _ = generator((physical(theta, driver),))
    elapsed, events, jumps = 0., 0, []
    while True:
        holding = rng.exponential(1/(-q[index, index]))
        if elapsed+holding > duration:
            break
        elapsed += holding
        probabilities = q[index].copy()
        probabilities[index] = 0.
        probabilities /= probabilities.sum()
        successor = int(rng.choice(len(q), p=probabilities))
        firing = bool(index == 2 and successor == 4 and rates[index, 0] > 0)
        events += int(firing)
        jumps.append(dict(time=elapsed, before=index, after=successor, fired=firing))
        index = successor
    before_reset = index
    if reset:
        index = int(rng.choice(5, p=initial(physical(theta, 0.))))
    return index, dict(jumps=jumps, count=events, before_task_reset=before_reset,
                       after=index, task_reset=reset)


def boundary_action(record, threshold):
    """A task-confidence boundary, not an intrinsic neural threshold claim."""
    posterior = record["features"][3]
    legal = record["feasible"]
    if legal[3] and (max(posterior, 1-posterior) >= threshold or not legal[2]):
        return 3
    if legal[2]:
        return 2
    return 0


def execute(session, policy, model, adapter, protocol, threshold=None, rng_seed=0):
    wall, cpu = time.perf_counter(), time.process_time()
    owner = Owner(session["folder"], adapter, model["confusion"], protocol["multiplier"], protocol["latency_price"])
    history, decisions = [], []
    controller_cpu, controller_wall = 0., 0.
    oracle = Bellman(owner.meta, model["confusion"], protocol["multiplier"], protocol["latency_price"],
                     future=policy != "myopic_dp") if policy in ("fitted_dp", "myopic_dp") else None
    rng = np.random.default_rng(rng_seed)
    sampled = policy == "analytic_value_sampled"
    arm = "analytic_value" if sampled else policy
    if arm in ARMS:
        family = arm.split("_")[0]
        cell_parameters = np.asarray(model["cellfits"][family]["parameters"])
        weights = {k:np.asarray(v) for k,v in model["controllers"][arm]["weights"].items()}
        norm = model["norm"]
        if sampled:
            index = int(rng.choice(5, p=initial(physical(cell_parameters, 0.))))
    error = None
    while not owner.terminal:
        begin, begin_cpu = time.perf_counter(), time.process_time()
        record = state_record(owner, history)
        features, q = None, None
        if arm in ARMS:
            features = (sampled_features(cell_parameters, index, record["driver"], record["horizon"])
                        if sampled else augmented_features(family, cell_parameters, [record])[0])
            public = (np.asarray(record["features"])-norm["mean"])/norm["scale"]
            x = np.r_[public, (features-.5)*2][None]
            predicted, _ = forward(weights, x)
            q = predicted[0].tolist()
            choice = int(np.argmax(np.where(record["feasible"], predicted[0], -np.inf)))
        elif oracle is not None:
            raw = np.asarray(oracle.q(owner.job, owner.tick, owner.budget, owner.posterior))
            choice = int(np.argmax(raw))
            q = np.where(record["feasible"], raw, 0.).tolist()
        elif policy in ("fixed_boundary", "learned_boundary"):
            choice = boundary_action(record, threshold)
        else:
            raise ValueError(("Unregistered execution policy", policy))
        controller_cpu += time.process_time()-begin_cpu
        controller_wall += time.perf_counter()-begin
        decision = dict(record=record, q=q, picked_action=ACTIONS[choice],
                        cell_features=None if features is None else features.tolist())
        if sampled:
            decision["sampled_state_before"] = index
        decisions.append(decision)
        try:
            event = owner.act(ACTIONS[choice])
        except Exception as exc:
            error = dict(type=type(exc).__name__, message=str(exc))
            break
        history.append(dict(driver=record["driver"], duration=event["duration"], reset=choice == 3))
        if sampled:
            begin, begin_cpu = time.perf_counter(), time.process_time()
            index, latent = sample_interval(cell_parameters, index, record["driver"], event["duration"], choice == 3, rng)
            decision["latent_transition"] = latent
            controller_cpu += time.process_time()-begin_cpu
            controller_wall += time.perf_counter()-begin
    score = score_terminal(owner) if owner.terminal else None
    return dict(seed=session["seed"], split=session["split"], policy=policy,
                session_id=session["id"], score=score, status="complete" if error is None else "failed",
                error=error, cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall,
                controller_cpu_seconds=controller_cpu, controller_wall_seconds=controller_wall,
                content_times=owner.times, counts=owner.counts, events=owner.events,
                task_elapsed=owner.task_elapsed, decision_trace=decisions,
                public_sha256=owner.public_sha256, rng_seed=rng_seed)
