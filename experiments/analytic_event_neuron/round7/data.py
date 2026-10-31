"""Public-prefix data; the learner never receives Episode or its private record."""

from dataclasses import replace
import hashlib
import json

import numpy as np
import torch

from . import oracle
from .task import ACTIONS, FEATURE_NAMES, TaskParameters, features
from .task import generate_episode, initial_state, legal_actions, step


def task_configuration(index, regime="nominal"):
    """Predeclared public configurations; stress labels are never used to fit."""
    p = TaskParameters()
    presets = (
        {}, {"horizon": 3, "budget": 2}, {"horizon": 4, "budget": 4},
        {"horizon": 6, "budget": 1}, {"horizon": 2, "budget": 0},
        {"read_cost": 0.04, "repair_cost": 0.05},
        {"read_cost": 0.004, "wait_cost": 0.012},
        {"ordinary_reliability": 0.8, "delayed_reliability": 0.85},
    )
    p = replace(p, **presets[index % len(presets)])
    if regime == "drift":
        p = replace(p, ordinary_reliability=0.57, delayed_reliability=0.72,
                    prior_probability=0.65)
    elif regime == "missing":
        p = replace(p, corruption_probability=0.8, arrival_tick=3)
    elif regime == "cost_shift":
        p = replace(p, read_cost=0.08, repair_cost=0.12, latency_cost=0.02)
    elif regime != "nominal":
        raise ValueError(regime)
    return p


def make_data(start_seed, count):
    records = []
    for index in range(count):
        seed = start_seed + index
        episode = generate_episode(seed, task_configuration(index))
        state = initial_state(episode)
        rng = np.random.default_rng(seed + 80000000)
        prefixes = []
        while not state.terminated:
            allowed = legal_actions(state)
            optimal = oracle.action_values(state)
            myopic = oracle.myopic_action_values(state)
            prefixes.append({"features": features(state).tolist(),
                             "targets": [[myopic[a] for a in ACTIONS],
                                         [optimal[a] for a in ACTIONS]],
                             "legal": [a in allowed for a in ACTIONS],
                             "state_digest": state.digest()})
            choices = tuple(a for a in allowed if a != "STOP")
            action = "STOP" if not choices or rng.random() < 0.12 else str(rng.choice(choices))
            state = step(state, action, episode).state
        records.append({"seed": seed, "prefixes": prefixes})
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":"), allow_nan=False)
    length = max(len(r["prefixes"]) for r in records)
    x = np.zeros((count, length, len(FEATURE_NAMES)), dtype=np.float64)
    y = np.zeros((count, length, 2, len(ACTIONS)), dtype=np.float64)
    legal = np.zeros((count, length, len(ACTIONS)), dtype=bool)
    active = np.zeros((count, length), dtype=bool)
    for i, record in enumerate(records):
        for t, prefix in enumerate(record["prefixes"]):
            x[i, t], y[i, t] = prefix["features"], prefix["targets"]
            legal[i, t], active[i, t] = prefix["legal"], True
    arrays = {"x": torch.from_numpy(x), "y": torch.from_numpy(y),
              "legal": torch.from_numpy(legal), "active": torch.from_numpy(active)}
    return arrays, {"seed_start": start_seed, "episodes": count,
                    "prefixes": int(active.sum()), "sha256": hashlib.sha256(encoded.encode()).hexdigest(),
                    "records": records}
