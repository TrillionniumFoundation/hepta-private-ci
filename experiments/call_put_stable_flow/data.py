"""Causal selective copy and multi-query associative recall task contracts.

Inputs contain visible role/key/value/selection fields only. Targets are
separate arrays. Copy uses an explicitly shared causal slot-counter prior;
MQAR uses a visible KEY then VALUE binding grammar and includes overwrites.
No value identifier is present in a query token. All data are newly made.
"""

from dataclasses import asdict, dataclass
import hashlib

import numpy as np


DISTRACTOR, COPY_VALUE, CUE, COPY_QUERY, WRITE_KEY, WRITE_VALUE, KEY_QUERY = range(7)
ROLE_COUNT = 7
TASKS = ("selective_copy", "mqar")


@dataclass(frozen=True)
class TaskConfig:
    length: int = 32
    key_vocab: int = 16
    value_vocab: int = 8
    selected: int = 4
    bindings: int = 6
    overwrites: int = 2

    @property
    def key_start(self):
        return ROLE_COUNT

    @property
    def value_start(self):
        return ROLE_COUNT + self.key_vocab

    @property
    def select_index(self):
        return self.value_start + self.value_vocab

    @property
    def input_dim(self):
        return self.select_index + 1


def _token(config, role, key=None, value=None, selected=False):
    token = np.zeros(config.input_dim, dtype=np.float32)
    token[role] = 1
    if key is not None:
        token[config.key_start + key] = 1
    if value is not None:
        token[config.value_start + value] = 1
    token[config.select_index] = selected
    return token


def oracle_targets(inputs: np.ndarray, config: TaskConfig) -> np.ndarray:
    """Independent causal queue/dictionary oracle; takes no target array."""
    labels = np.full(inputs.shape[:2], -100, dtype=np.int64)
    for i, sequence in enumerate(inputs):
        queue, table = [], {}
        pending, read_index, cued = None, 0, False
        for t, token in enumerate(sequence):
            role = int(token[:ROLE_COUNT].argmax())
            key = int(token[config.key_start : config.value_start].argmax())
            value = int(token[config.value_start : config.select_index].argmax())
            if role == COPY_VALUE and token[config.select_index] == 1:
                queue.append(value)
            elif role == CUE:
                cued = True
                read_index = 0
            elif role == COPY_QUERY:
                if not cued or read_index >= len(queue):
                    raise ValueError("Copy query before a valid causal write/cue")
                labels[i, t] = queue[read_index]
                read_index += 1
            elif role == WRITE_KEY:
                pending = key
            elif role == WRITE_VALUE:
                if pending is None:
                    raise ValueError("Value token without a prior unmatched key")
                table[pending] = value
                pending = None
            elif role == KEY_QUERY:
                if key not in table:
                    raise ValueError("Query before the corresponding write")
                labels[i, t] = table[key]
    return labels


def generate(task: str, count: int, seed: int, config=TaskConfig()) -> dict:
    """Generate new episodes without any split-dependent learned choice."""
    if task not in TASKS or count <= 0:
        raise ValueError("Known task and positive episode count required")
    if config.selected > config.key_vocab or config.bindings > config.key_vocab:
        raise ValueError("The causal address vocabulary is too small")
    rng = np.random.default_rng(seed)
    inputs = np.zeros((count, config.length, config.input_dim), dtype=np.float32)
    targets = np.full((count, config.length), -100, dtype=np.int64)
    for i in range(count):
        if task == "selective_copy":
            prefix = config.length - config.selected - 1
            if prefix < config.selected:
                raise ValueError("Copy prefix is too short")
            selected = sorted(
                rng.choice(prefix, config.selected, replace=False).tolist()
            )
            values = rng.integers(config.value_vocab, size=prefix)
            for t, value in enumerate(values):
                inputs[i, t] = _token(
                    config, COPY_VALUE, value=int(value), selected=t in selected
                )
            inputs[i, prefix] = _token(config, CUE)
            for j, source_t in enumerate(selected):
                inputs[i, prefix + 1 + j] = _token(config, COPY_QUERY)
                targets[i, prefix + 1 + j] = values[source_t]
        else:
            keys = rng.choice(config.key_vocab, config.bindings, replace=False)
            values = rng.integers(config.value_vocab, size=config.bindings)
            chosen = rng.choice(config.bindings, config.overwrites, replace=False)
            events = []
            for key, value in zip(keys, values):
                events.extend(
                    [
                        (_token(config, WRITE_KEY, key=int(key)), -100),
                        (_token(config, WRITE_VALUE, value=int(value)), -100),
                    ]
                )
            for j in chosen:
                events.append(
                    (_token(config, KEY_QUERY, key=int(keys[j])), int(values[j]))
                )
            for j in chosen:
                new_value = (
                    int(values[j]) + int(rng.integers(1, config.value_vocab))
                ) % config.value_vocab
                values[j] = new_value
                events.extend(
                    [
                        (_token(config, WRITE_KEY, key=int(keys[j])), -100),
                        (_token(config, WRITE_VALUE, value=new_value), -100),
                    ]
                )
            for j in chosen:
                events.append(
                    (_token(config, KEY_QUERY, key=int(keys[j])), int(values[j]))
                )
            if len(events) > config.length:
                raise ValueError("MQAR sequence cannot fit the registered events")
            positions = sorted(
                rng.choice(config.length, len(events), replace=False).tolist()
            )
            for t in range(config.length):
                inputs[i, t] = _token(
                    config, DISTRACTOR, value=int(rng.integers(config.value_vocab))
                )
            for t, (token, label) in zip(positions, events):
                inputs[i, t], targets[i, t] = token, label
    oracle = oracle_targets(inputs, config)
    if not np.array_equal(targets, oracle):
        raise AssertionError("Generator labels disagree with independent causal oracle")
    query = (inputs[:, :, COPY_QUERY] + inputs[:, :, KEY_QUERY]) > 0
    if np.any(inputs[:, :, config.value_start : config.select_index][query] != 0):
        raise AssertionError("A query exposes a value identifier")
    return {
        "inputs": inputs,
        "targets": targets,
        "dt": np.ones((count, config.length), dtype=np.float32),
    }


def array_digest(data: dict) -> str:
    digest = hashlib.sha256()
    for name in sorted(data):
        value = np.ascontiguousarray(data[name])
        digest.update(name.encode())
        digest.update(str(value.dtype).encode())
        digest.update(str(value.shape).encode())
        digest.update(value.tobytes())
    return digest.hexdigest()


def episode_digests(data: dict) -> set[str]:
    return {hashlib.sha256(x.tobytes()).hexdigest() for x in data["inputs"]}


def contract(config=TaskConfig()) -> dict:
    return {
        "version": "hepta-causal-matrix-tasks-20261029-v1",
        "config": asdict(config),
        "input_fields": ["role_onehot", "key_onehot", "value_onehot", "selection"],
        "query_visible_values": False,
        "labels_are_model_inputs": False,
        "copy_prior": "causal counters driven by observed selection, cue and query roles",
        "mqar_prior": "causal pending-key binder; values cannot enter the query projection",
        "readout": "current M times current projected query; no final-memory replay",
        "dt": "one time unit per distinct token, not duplicate-token resampling",
    }
