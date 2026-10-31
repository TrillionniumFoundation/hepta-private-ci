"""Numeric streaming state, without importing an unrelated training package.

The field contract and copy semantics match the sealed v2 runtime serializer:
elapsed plus content, full active/refractory probability, and boundary per layer.
"""

import numpy as np
import torch


def numeric_state(state):
    result = {"elapsed": state["elapsed"].detach().cpu().numpy().copy()}
    for index, layer in enumerate(state["layers"]):
        for key, value in layer.items():
            if not isinstance(value, torch.Tensor):
                raise ValueError("Checkpoint must follow at least one observation")
            result[f"layer_{index}.{key}"] = value.detach().cpu().numpy().copy()
    return result


def read_state(path, depth):
    with np.load(path, allow_pickle=False) as stored:
        arrays = {key: torch.from_numpy(np.array(stored[key], copy=True))
                  for key in stored.files}
    state = dict(elapsed=arrays.pop("elapsed"), layers=[])
    for index in range(depth):
        prefix = f"layer_{index}."
        layer = {key[len(prefix):]: arrays.pop(key) for key in list(arrays)
                 if key.startswith(prefix)}
        if set(layer) != {"content", "probability", "boundary"}:
            raise ValueError("Incomplete or unknown distributional layer state")
        state["layers"].append(layer)
    if arrays:
        raise ValueError("Unknown checkpoint fields")
    return state
