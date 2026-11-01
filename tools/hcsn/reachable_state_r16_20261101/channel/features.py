"""Compute only the frozen policy's actual feature set, with no owner inputs."""

import time

import numpy as np


KINDS = ("state_confidence", "stop_value", "value_risk", "ordinary_dual")
DURATIONS = {"iid": (.25, .50, .75), "ood": (.35, .65, .95)}


def actual_features(law, belief, dt, remaining, read_cost, refresh_cost, kind):
    if kind not in KINDS:
        raise ValueError("Unknown frozen feature set")
    p = np.asarray(belief)
    classes = p.reshape(10, 4).sum(axis=0)
    ordered = np.sort(classes)
    mean_phase = float(p.reshape(10, 4).sum(axis=1) @ np.arange(10)) / 9
    remaining_time = float(dt * remaining)
    entropy = -float(np.sum(classes * np.log(np.maximum(classes, 1e-300))))
    row = [1., mean_phase, ordered[-1], ordered[-1] - ordered[-2],
           remaining_time, read_cost, refresh_cost, entropy]
    if kind in ("stop_value", "value_risk"):
        # Same operation order as R15 preserves the frozen policy's numerics.
        row.append(float(np.max(p @ law.transition(remaining_time) @ law.reward)))
    if kind == "value_risk":
        row.append(float(law.first_hit(p, remaining_time)))
    elif kind == "ordinary_dual":
        row.extend((row[2] ** 2, 1 / (1 + np.exp(-8 * (row[1] - .5)))))
    return np.array(row)


def prepare(law, kind, domain):
    """Public duration bank; risk's augmented matrix exponentials are charged.

    No history or future token selects the bank. Each arm owns a fresh law and
    cache. Answer propagation is shared mandatory work. Only value_risk pays
    the cold first-hit bank; the later episode timer is genuinely warm.
    """
    if law._transition_cache or law._event_cache:
        raise ValueError("Cold preparation requires empty caches")
    started = time.process_time()
    for dt in DURATIONS[domain]:
        for remaining in range(4):
            law.transition(remaining * dt)
    propagation_cpu = time.process_time() - started
    started = time.process_time()
    if kind == "value_risk":
        for dt in DURATIONS[domain]:
            law.first_hit(law.prior, 3 * dt)
    risk_cpu = time.process_time() - started
    return dict(common_transition_preparation_cpu_seconds=propagation_cpu,
                channel_preparation_cpu_seconds=risk_cpu,
                transition_matrices=len(law._transition_cache),
                risk_matrices=len(law._event_cache),
                scope="Fresh restored law and public domain durations; all expm bank creation included, imports and restoration separate.")
