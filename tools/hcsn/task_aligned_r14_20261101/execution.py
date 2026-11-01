"""Causal common data and actual fee-paying execution on paired random tapes."""

import copy
import hashlib
import time

import numpy as np

from ..unified_cell_r12_20261031.task_value import ACTIONS, ExactBeliefDP, choose_values
from .qpi import cost_sensitive_weights, encode, policy_alpha


def array_hash(data):
    digest = hashlib.sha256()
    for key in sorted(data):
        value = np.ascontiguousarray(data[key])
        digest.update(key.encode())
        digest.update(str((value.shape, value.dtype.str)).encode())
        digest.update(value.tobytes())
    return digest.hexdigest()


def generate_data(world, seed, count, durations=(.15, .45, 1.05), horizon=3, budget=2):
    """Common exploratory histories, including a zero-input initial STOP row.

    Latent states and exact causal posteriors belong only to supervised training.
    All methods receive the identical raw records. Exploration never uses the
    hidden state when selecting READ, WAIT or RESET.
    """
    rng = np.random.default_rng(seed)
    inputs = np.zeros((count, horizon + 1, 11))
    teacher = np.zeros((count, horizon + 1, world.state_count))
    schedules = rng.choice(durations, size=(count, horizon))
    budgets = np.empty((count, horizon + 1), dtype=int)
    states = np.empty((count, horizon + 1), dtype=int)
    for i in range(count):
        state = int(rng.choice(world.state_count, p=world.prior))
        history, reads = [], budget
        teacher[i, 0], budgets[i, 0], states[i, 0] = world.prior, reads, state
        for t, dt in enumerate(schedules[i]):
            actions = ("READ", "WAIT", "RESET") if reads else ("WAIT", "RESET")
            action = str(rng.choice(actions))
            state, token, _, _ = world.sample_step(state, action, float(dt), rng)
            history.append((action, float(dt), token))
            reads -= int(action == "READ")
            inputs[i, t + 1] = encode(token, dt, action == "RESET")
            teacher[i, t + 1] = world.posterior(history)
            budgets[i, t + 1], states[i, t + 1] = reads, state
    return dict(inputs=inputs, teacher=teacher, schedules=schedules, budgets=budgets, states=states)


def collect_targets(world, actor, planner, data, temperature=.1):
    """Evaluate actual frozen policy on each common training prefix.

    Exact finite-world action trees use all future observations with their true
    probabilities. The actor receives only the raw history at each node. These
    are full Q-pi values with actual fees, not planner Q-star targets.
    """
    start = time.process_time()
    count, length = data["inputs"].shape[:2]
    alpha = np.zeros((count, length, len(ACTIONS), world.state_count))
    legal = np.zeros((count, length, len(ACTIONS)), dtype=bool)
    for i in range(count):
        actor.start()
        for t in range(length):
            if t:
                actor.step(data["inputs"][i, t])
            vectors = policy_alpha(world, actor, planner, data["schedules"][i, t:], int(data["budgets"][i, t]))
            for action, vector in vectors.items():
                index = ACTIONS.index(action)
                alpha[i, t, index], legal[i, t, index] = vector, True
    values = np.einsum("bts,btas->bta", data["teacher"], alpha)
    weights = cost_sensitive_weights(values, legal, temperature)
    return dict(alpha=alpha, legal=legal, weights=weights, cpu_seconds=time.process_time() - start,
                target_count=int(legal.sum()), world_identity=world.identity,
                planner_identity=planner.model_identity)


def make_tapes(seed, count, durations=(.15, .45, 1.05), horizon=3):
    rng = np.random.default_rng(seed)
    return dict(schedule=rng.choice(durations, size=(count, horizon)),
                initial=rng.random(count), uniforms=rng.random((count, horizon, 3)))


def sample(probabilities, uniform):
    cumulative = np.cumsum(probabilities)
    if abs(cumulative[-1] - 1.) > 2e-10 or np.min(probabilities) < -2e-12:
        raise ArithmeticError("Owner received invalid transition probabilities")
    # Only the final roundoff-sized open endpoint is repaired.
    cumulative[-1] = 1.
    return int(np.searchsorted(cumulative, uniform, side="right"))


def execute(world, actor, planner, tapes, control="value", read_budget=2, retain=True):
    """Execute actual owner trajectories; no hidden information enters actions.

    The random tape has one uniform per possible reset/transition/read at each
    time slot. The same episode tape is used for all arms, even when actions
    diverge. This is common-noise pairing, not equality of their latent paths.
    """
    if control not in ("value", "fixed_read", "no_reset"):
        raise ValueError("Unknown control")
    started, wall = time.process_time(), time.perf_counter()
    # Copy arrays into a new planner, not its cached bound-method closures.
    # Every arm pays for a cold controller under the same construction rule.
    planner = type(planner)(planner, reset_cost=planner.reset_cost,
                            latency_price=planner.latency_price, read_multiplier=planner.read_multiplier)
    planner_construction_cpu = time.process_time() - started
    model = copy.deepcopy(actor)
    inference_cpu, control_cpu, owner_cpu = 0., 0., 0.
    records = []
    for i, schedule in enumerate(tapes["schedule"]):
        tick = time.process_time()
        state = sample(world.prior, tapes["initial"][i])
        owner_cpu += time.process_time() - tick
        tick = time.process_time()
        model.start()
        inference_cpu += time.process_time() - tick
        reads, reset_count, read_count, elapsed, paid = read_budget, 0, 0, 0., 0.
        trace, t = [], 0
        while True:
            remaining = tuple(float(dt) for dt in schedule[t:])
            tick = time.process_time()
            if control == "fixed_read":
                action = "READ" if remaining and reads else "STOP" + str(int(np.argmax(model.current @ planner.reward)))
            elif control == "no_reset":
                q = planner.action_values(model.current, remaining, reads)
                # This is an actual permanently constrained controller. The
                # caller supplies a planner whose future recursion also bans it.
                if "RESET" in q:
                    raise ValueError("No-reset execution requires NoResetDP")
                action = choose_values(q)
            else:
                action = planner.choose(model.current, remaining, reads)
            control_cpu += time.process_time() - tick
            if action not in planner.legal_actions(remaining, reads):
                raise ValueError("Policy selected an infeasible action")
            tick = time.process_time()
            if action.startswith("STOP"):
                reward = float(world.reward[state, int(action[-1])])
                trace.append(dict(action=action, t=t))
                owner_cpu += time.process_time() - tick
                break
            dt = float(schedule[t])
            uniforms = tapes["uniforms"][i, t]
            if action == "RESET":
                state = sample(world.R[state], uniforms[0])
                paid += world.reset_cost
                reset_count += 1
            state = sample(world.transition(dt)[state], uniforms[1])
            token = sample(world.E[state], uniforms[2]) if action == "READ" else None
            if action == "READ":
                paid += float(world.read_cost[state])
                reads -= 1
                read_count += 1
            paid += world.latency_price * dt
            elapsed += dt
            trace.append(dict(action=action, dt=dt, token=token))
            owner_cpu += time.process_time() - tick
            tick = time.process_time()
            model.step(encode(token, dt, action == "RESET"))
            inference_cpu += time.process_time() - tick
            t += 1
        records.append(dict(episode=i, utility=reward - paid, reward=reward, fee=paid,
                            reads=read_count, resets=reset_count, elapsed=elapsed, trace=trace))
    costs = dict(cpu_seconds=time.process_time() - started, wall_seconds=time.perf_counter() - wall,
                 planner_construction_cpu_seconds=planner_construction_cpu,
                 inference_cpu_seconds=inference_cpu, control_cpu_seconds=control_cpu,
                 owner_cpu_seconds=owner_cpu)
    result = dict(count=len(records), control=control, model=actor.kind,
                  world_identity=world.identity, planner_identity=planner.model_identity,
                  tape_hash=array_hash(tapes), costs=costs,
                  mean={key: float(np.mean([r[key] for r in records]))
                        for key in ("utility", "reward", "fee", "reads", "resets", "elapsed")},
                  initial_stop_count=sum(r["trace"][0]["action"].startswith("STOP") for r in records),
                  reset_episode_count=sum(r["resets"] > 0 for r in records))
    result["episode_values"] = {key: [r[key] for r in records] for key in ("utility", "reward", "fee", "reads", "resets")}
    if retain:
        result["records"] = records
    return result


class NoResetDP(ExactBeliefDP):
    @staticmethod
    def legal_actions(schedule, budget):
        return tuple(a for a in ExactBeliefDP.legal_actions(schedule, budget) if a != "RESET")
