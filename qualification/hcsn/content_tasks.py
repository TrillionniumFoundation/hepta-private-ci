"""Typed multi-query associative recall and paired content interventions.

This is a synthetic content contract, not a multimodal quality claim. The event
schema is an explicit shared prior for every model. ``oracle_targets`` is an
independent symbolic specification checker; it must never supply model features
or be reported as learned recall. Existing CUDA task identities are unchanged.
"""

from dataclasses import dataclass
import math

import numpy as np


WRITE, QUERY, NOISE, SILENCE = range(4)
IGNORE_TARGET = -100
CONDITIONS = ("base", "query_swap", "overwrite", "silence", "interference", "unknown")


@dataclass(frozen=True)
class ContentBatch:
    """Only x and dt are model inputs; supervision is held in separate arrays.

    x has shape [batch,time,4+keys+values]: one-hot event kind, one-hot key,
    one-hot payload. QUERY has no payload. SILENCE has neither key nor payload.
    Events are observed at interval start and outputs are read after dt seconds.
    Unqueried positions have IGNORE_TARGET; the unknown answer class is values.
    """

    x: np.ndarray
    dt: np.ndarray
    targets: np.ndarray
    query_mask: np.ndarray
    keys: int
    values: int
    condition: str
    seed: int

    def model_inputs(self):
        """Return the complete allowed input boundary, without supervision."""
        return {"x": self.x, "dt": self.dt}

    @property
    def input_contract(self):
        return {"keys": self.keys, "values": self.values,
                "input_size": 4 + self.keys + self.values,
                "unknown_class": self.values, "classes": self.values + 1,
                "kinds": {"write": WRITE, "query": QUERY, "noise": NOISE, "silence": SILENCE},
                "key_slice": [4, 4 + self.keys],
                "value_slice": [4 + self.keys, 4 + self.keys + self.values],
                "time_unit": "seconds", "observation": "interval_start", "readout": "interval_end"}


def make_content_batch(seed, count, *, keys=8, values=16, queries=4,
                       condition="base", delay_steps=16, dt=0.1):
    """Generate paired worlds, with independently planned last-write targets.

    keys-2 keys receive independent random values. Two randomly chosen keys are
    reserved: a nonqueried distractor and a never-written unknown. All queries
    are distinct. An overwrite changes one queried value before recall.

    Every condition consumes the same random draws. Query swap rotates queries;
    silence/base have identical inputs; interference replaces silent intervals
    with alternate distractor WRITEs and typed NOISE. It changes no answer or
    physical deadline. Unknown changes only the last query to the unseen key.
    This known generator and exact typed keys are a controlled research prior.
    """
    integers = {"seed": seed, "count": count, "keys": keys, "values": values,
                "queries": queries, "delay_steps": delay_steps}
    if any(type(v) is not int for v in integers.values()):
        raise ValueError("seed/count/keys/values/queries/delay_steps must be integers")
    if seed < 0 or count < 1 or keys < 4 or values < 2 or not 2 <= queries <= keys - 2 or delay_steps < 0:
        raise ValueError("require seed,delay>=0; count>=1; keys>=4; values>=2; 2<=queries<=keys-2")
    if isinstance(dt, bool) or not isinstance(dt, (int, float)) or not math.isfinite(dt) or dt <= 0:
        raise ValueError("dt must be a finite positive scalar duration")
    if condition not in CONDITIONS:
        raise ValueError(f"unknown content condition: {condition!r}")
    rng = np.random.default_rng(seed)
    memory_count = keys - 2
    query_start = memory_count + 1 + delay_steps
    length = query_start + queries
    x = np.zeros((count, length, 4 + keys + values), dtype=np.float32)
    x[..., SILENCE] = 1
    targets = np.full((count, length), IGNORE_TARGET, dtype=np.int64)

    def event(row, step, kind, key=None, value=None):
        x[row, step] = 0
        x[row, step, kind] = 1
        if key is not None:
            x[row, step, 4 + key] = 1
        if value is not None:
            x[row, step, 4 + keys + value] = 1

    for row in range(count):
        order = rng.permutation(keys)
        known, distractor, unseen = order[:-2], int(order[-2]), int(order[-1])
        payloads = rng.integers(values, size=memory_count)
        queried = rng.choice(known, size=queries, replace=False)
        changed_key = int(queried[0])
        old_value = int(payloads[np.flatnonzero(known == changed_key)[0]])
        replacement = (old_value + int(rng.integers(1, values))) % values
        noise_keys = rng.choice(known, size=delay_steps)
        noise_values = rng.integers(values, size=delay_steps)
        planned = dict(zip(map(int, known), map(int, payloads)))
        for step, (key, value) in enumerate(zip(known, payloads)):
            event(row, step, WRITE, int(key), int(value))
        if condition == "overwrite":
            event(row, memory_count, WRITE, changed_key, replacement)
            planned[changed_key] = replacement
        if condition == "interference":
            for offset in range(delay_steps):
                kind, key = (WRITE, distractor) if offset % 2 == 0 else (NOISE, int(noise_keys[offset]))
                event(row, memory_count + 1 + offset, kind, key, int(noise_values[offset]))
        if condition == "query_swap":
            queried = np.roll(queried, 1)
        elif condition == "unknown":
            queried[-1] = unseen
        for offset, key in enumerate(queried):
            step = query_start + offset
            event(row, step, QUERY, int(key))
            targets[row, step] = planned.get(int(key), values)
    durations = np.full((count, length), dt, dtype=np.float64)
    query_mask = x[..., QUERY].astype(bool)
    return ContentBatch(x, durations, targets, query_mask, keys, values, condition, seed)


def oracle_targets(x, *, keys, values):
    """Interpret only observed typed events, never future events or batch labels.

    Reject malformed input instead of silently guessing a key/type by argmax.
    NOISE may carry a conflicting key/value but has no memory-write authority.
    The dictionary state here is only an acceptance oracle, not a neural model.
    """
    if type(keys) is not int or type(values) is not int or min(keys, values) < 1:
        raise ValueError("keys and values must be positive integers")
    x = np.asarray(x)
    if x.ndim != 3 or x.shape[-1] != 4 + keys + values or min(x.shape[:2]) < 1:
        raise ValueError("expected [positive batch,positive time,4+keys+values]")
    if not np.isfinite(x).all() or not np.isin(x, (0, 1)).all():
        raise ValueError("event fields must contain finite binary values")
    result = np.full(x.shape[:2], IGNORE_TARGET, dtype=np.int64)
    for row, sequence in enumerate(x):
        memory = {}
        for step, token in enumerate(sequence):
            if token[:4].sum() != 1:
                raise ValueError("each token must have exactly one event kind")
            kind = int(np.flatnonzero(token[:4])[0])
            key_fields, value_fields = token[4:4 + keys], token[4 + keys:]
            expected = (0, 0) if kind == SILENCE else (1, 0) if kind == QUERY else (1, 1)
            if (key_fields.sum(), value_fields.sum()) != expected:
                raise ValueError("key/payload cardinality violates event kind")
            if kind == WRITE:
                memory[int(np.flatnonzero(key_fields)[0])] = int(np.flatnonzero(value_fields)[0])
            elif kind == QUERY:
                result[row, step] = memory.get(int(np.flatnonzero(key_fields)[0]), values)
    return result
