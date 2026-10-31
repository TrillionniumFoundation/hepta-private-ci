"""Causal decision rows from actual local-owner trajectories.

The 62 input coordinates reversibly encode the complete control state and both
jobs' public schedules. Session names, paths, evaluator labels and unread packet
contents are excluded. Standardization belongs to TRAIN-only model fitting.
"""
import copy
from pathlib import Path
import time

import numpy as np

from .task import ACTIONS, Bellman, Owner, build_cohort, feasible, save, score_terminal, sha

MAX_DEADLINE = 10
FEATURE_NAMES = tuple(
    ["job", "tick", "budget", "posterior", "deadline", "initial_budget", "multiplier", "latency_price"]
    + [f"reliability_{j}_{t}" for j in range(2) for t in range(MAX_DEADLINE)]
    + [f"price_{j}_{t}" for j in range(2) for t in range(MAX_DEADLINE)]
    + [f"duration_{t}" for t in range(MAX_DEADLINE)]
    + [f"confusion_{i}_{j}" for i in range(2) for j in range(2)]
)


def feature_vector(owner):
    """No information gathering, model evaluation, or owner-state advancement."""
    meta = owner.meta
    n = int(meta["deadline"])
    if n != meta["deadline"] or not 2 <= n <= MAX_DEADLINE:
        raise ValueError("Public deadline outside the frozen feature domain")
    reliability, price = np.zeros((2, MAX_DEADLINE)), np.zeros((2, MAX_DEADLINE))
    duration = np.zeros(MAX_DEADLINE)
    reliability[:, :n] = np.asarray(meta["reliability"], np.float64)
    price[:, :n] = np.asarray(meta["price"], np.float64)
    duration[:n] = np.asarray(meta["duration"], np.float64)
    value = np.concatenate([
        [owner.job, owner.tick, owner.budget, owner.posterior, n, meta["budget"],
         owner.multiplier, owner.latency_price],
        reliability.ravel(), price.ravel(), duration, owner.confusion.ravel(),
    ])
    if not np.all(np.isfinite(value)):
        raise ValueError("Nonfinite public features")
    return value


def decode_features(value):
    """Recover the control state, public observation law, prices and schedules."""
    value = np.asarray(value, np.float64)
    if value.shape != (len(FEATURE_NAMES),) or not np.all(np.isfinite(value)):
        raise ValueError("Invalid feature vector")
    n = int(value[4])
    if n != value[4] or not 2 <= n <= MAX_DEADLINE:
        raise ValueError("Invalid encoded deadline")
    for index in (0, 1, 2, 5):
        if value[index] != int(value[index]):
            raise ValueError("Nonintegral discrete state")
    return dict(
        state=dict(job=int(value[0]), tick=int(value[1]), budget=int(value[2]), posterior=float(value[3])),
        meta=dict(deadline=n, budget=int(value[5]),
                  reliability=value[8:28].reshape(2, MAX_DEADLINE)[:, :n].tolist(),
                  price=value[28:48].reshape(2, MAX_DEADLINE)[:, :n].tolist(),
                  duration=value[48:58][:n].tolist()),
        multiplier=float(value[6]), latency_price=float(value[7]),
        confusion=value[58:62].reshape(2, 2).tolist(),
    )


def state_record(owner, history, oracle=None, myopic_oracle=None):
    """Return pre-action features; test execution needs no oracle or labels.

    History entries carry the driver available BEFORE their respective action.
    A newly observed symbol never replaces the driver of the elapsed interval.
    Invalid Q targets are zero placeholders and must be masked by feasible.
    """
    if owner.terminal:
        raise RuntimeError("A terminal owner has no further decision row")
    recorded_history = []
    for item in history:
        if set(item) != {"driver", "duration", "reset"}:
            raise ValueError("History schema mismatch")
        driver, duration = float(item["driver"]), float(item["duration"])
        if not np.isfinite(driver+duration) or duration < 0 or not isinstance(item["reset"], bool):
            raise ValueError("Invalid causal history")
        recorded_history.append(dict(driver=driver, duration=duration, reset=item["reset"]))
    reliability = owner.meta["reliability"][owner.job][owner.tick]
    driver = .8*(2*owner.posterior-1)+.2*(2*reliability-1)
    result = dict(features=feature_vector(owner).tolist(),
                  feasible=feasible(owner.meta, owner.job, owner.tick, owner.budget).tolist(),
                  history=recorded_history, driver=float(driver),
                  horizon=float(owner.meta["duration"][owner.tick]))
    for name, teacher in (("q", oracle), ("q_myopic", myopic_oracle)):
        if teacher is not None:
            q = np.asarray(teacher.q(owner.job, owner.tick, owner.budget, owner.posterior))
            mask = np.asarray(result["feasible"])
            if q.shape != (len(ACTIONS),) or not np.all(np.isfinite(q[mask])):
                raise FloatingPointError("Invalid feasible Bellman target")
            result[name] = np.where(mask, q, 0.).tolist()
    return result


def collect(root, split, seed, count, protocol, adapter, confusion, multiplier, latency_price=0.):
    """Generate a new cohort and execute a frozen random legal behavior policy.

    `rows` are causal pre-action states, with full and per-job fitted-law Q
    targets sharing the same feasibility mask and calibrated observation law. Only
    TRAIN READ rows expose `next_observation` for fitting physical parameters.
    Episode traces retain actual read receipts, labels accessed after terminal,
    and measured cost. The driver is frozen before owner.act for each interval.
    """
    if split not in ("train", "validation"):
        raise ValueError("collect is development-only; test runner uses state_record")
    root = Path(root)
    cohort = build_cohort(root, split, seed, count, protocol)
    split_index = {"train": 0, "validation": 1}[split]
    rng = np.random.default_rng(protocol["data_seed_base"] + seed*1000000 + split_index*100000 + 50000)
    weights = np.asarray(protocol.get("behavior_action_weights", [.06, .12, .56, .26]), np.float64)
    if weights.shape != (4,) or not np.all(np.isfinite(weights)) or np.any(weights < 0) or weights.sum() <= 0:
        raise ValueError("Invalid behavior action weights")
    rows, episodes = [], []
    total_wall, total_cpu = time.perf_counter(), time.process_time()
    for session in cohort["records"]:
        wall, cpu = time.perf_counter(), time.process_time()
        owner = Owner(session["folder"], adapter, confusion, multiplier, latency_price)
        oracle = Bellman(owner.meta, confusion, multiplier, latency_price)
        myopic_oracle = Bellman(owner.meta, confusion, multiplier, latency_price, future=False)
        history, teacher_wall, teacher_cpu = [], 0., 0.
        first_row = len(rows)
        while not owner.terminal:
            begin, begin_cpu = time.perf_counter(), time.process_time()
            row = state_record(owner, history, oracle, myopic_oracle)
            teacher_wall += time.perf_counter()-begin
            teacher_cpu += time.process_time()-begin_cpu
            probability = weights*np.asarray(row["feasible"], np.float64)
            if probability.sum() == 0:
                probability = np.asarray(row["feasible"], np.float64)
            probability /= probability.sum()
            choice = int(rng.choice(len(ACTIONS), p=probability))
            action = ACTIONS[choice]
            row.update(session=session["id"], seed=seed, split=split,
                       decision_index=len(history), chosen_action=action,
                       behavior_probability=float(probability[choice]))
            event = owner.act(action)
            if split == "train" and action == "READ":
                row["next_observation"] = int(event["observation"])
            rows.append(row)
            history.append(dict(driver=row["driver"], duration=float(event["duration"]), reset=action == "FIRE"))
        score_start, score_cpu = time.perf_counter(), time.process_time()
        score = score_terminal(owner)
        scoring_wall, scoring_cpu = time.perf_counter()-score_start, time.process_time()-score_cpu
        trace_path = root / "trajectories" / f"{session['id']}.json"
        save(trace_path, owner.snapshot())
        episodes.append(dict(
            session=session["id"], seed=seed, split=split, first_row=first_row,
            row_count=len(rows)-first_row, score=score, events=copy.deepcopy(owner.events),
            counts=copy.deepcopy(owner.counts), content_times=copy.deepcopy(owner.times),
            task_elapsed=owner.task_elapsed, metadata_wall_seconds=owner.metadata_wall_seconds,
            teacher_wall_seconds=teacher_wall, teacher_cpu_seconds=teacher_cpu,
            scoring_wall_seconds=scoring_wall, scoring_cpu_seconds=scoring_cpu,
            total_wall_seconds=time.perf_counter()-wall, total_cpu_seconds=time.process_time()-cpu,
            trace=str(trace_path), trace_sha256=sha(trace_path),
        ))
    return dict(schema="hcsn.factorial.dataset.v1", split=split, seed=seed,
                feature_names=list(FEATURE_NAMES), rows=rows, episodes=episodes, cohort=cohort,
                behavior_action_weights=weights.tolist(),
                costs=dict(generation_wall_seconds=cohort["generation_wall_seconds"],
                           generation_cpu_seconds=cohort["generation_cpu_seconds"],
                           collection_wall_seconds=time.perf_counter()-total_wall,
                           collection_cpu_seconds=time.process_time()-total_cpu,
                           teacher_is_nested_in_collection=True,
                           content_is_nested_in_collection=True,
                           adapter_setup_excluded_and_measured_separately=True))
