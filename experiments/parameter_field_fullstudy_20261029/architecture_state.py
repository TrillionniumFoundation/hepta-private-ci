"""Complete CPU training state for the declared stage-C generator and plain SGD.

Captures occur between steps with no pending graph. Work counters, logical
clock, paired tapes and immutable teacher/context are held by the caller.
"""

from copy import deepcopy
import gzip
import hashlib
import io
import random

import numpy as np
import torch


def digest(value):
    result = hashlib.sha256()

    def add(item):
        if torch.is_tensor(item):
            tensor = item.detach().cpu().contiguous()
            result.update(str((tuple(tensor.shape), str(tensor.dtype))).encode())
            result.update(tensor.numpy().tobytes())
        elif isinstance(item, np.ndarray):
            result.update(str((item.shape, item.dtype.str)).encode())
            result.update(item.tobytes())
        elif isinstance(item, dict):
            result.update(b"dict{")
            for key in sorted(item, key=lambda x: (type(x).__name__, repr(x))):
                add(key)
                add(item[key])
            result.update(b"}")
        elif isinstance(item, (list, tuple)):
            result.update(type(item).__name__.encode() + b"[")
            for part in item:
                add(part)
            result.update(b"]")
        elif item is None or type(item) in (bool, int, float, str):
            result.update(type(item).__name__.encode() + b":" + repr(item).encode() + b";")
        else:
            raise TypeError(f"Unsupported stage-C state value: {type(item).__name__}")

    add(value)
    return result.hexdigest()


def capture(model, optimizer):
    if type(optimizer) is not torch.optim.SGD:
        raise TypeError("Stage C supports stock CPU SGD only")
    if any(parameter.device.type != "cpu" for parameter in model.parameters()):
        raise ValueError("Stage C is a CPU experiment")
    numpy_state = np.random.get_state()
    return {
        "schema": "hepta.fullstudy.C.training-state.1",
        "model_config": deepcopy(model.config),
        "model": {name: tensor.detach().clone() for name, tensor in model.state_dict().items()},
        "optimizer": deepcopy(optimizer.state_dict()),
        "parameter_names": [name for name, _ in model.named_parameters()],
        "requires_grad": [parameter.requires_grad for parameter in model.parameters()],
        "gradients": {name: None if parameter.grad is None else parameter.grad.detach().clone()
                      for name, parameter in model.named_parameters()},
        "modes": {name: module.training for name, module in model.named_modules()},
        "torch_rng": torch.get_rng_state().clone(),
        "python_rng": random.getstate(),
        "numpy_rng": [numpy_state[0], numpy_state[1].tolist(), *numpy_state[2:]],
    }


def restore(model, optimizer, state):
    if state["schema"] != "hepta.fullstudy.C.training-state.1":
        raise ValueError("Unexpected stage-C checkpoint schema")
    if model.config != state["model_config"]:
        raise ValueError("Checkpoint architecture configuration differs")
    names = [name for name, _ in model.named_parameters()]
    if names != state["parameter_names"] or [p.requires_grad for p in model.parameters()] != state["requires_grad"]:
        raise ValueError("Checkpoint parameter identity differs")
    model.load_state_dict(state["model"], strict=True)
    optimizer.load_state_dict(deepcopy(state["optimizer"]))
    for name, parameter in model.named_parameters():
        gradient = state["gradients"][name]
        parameter.grad = None if gradient is None else gradient.clone()
    for name, module in model.named_modules():
        module.train(state["modes"][name])
    torch.set_rng_state(state["torch_rng"])
    random.setstate(state["python_rng"])
    numpy_state = state["numpy_rng"]
    np.random.set_state((numpy_state[0], np.asarray(numpy_state[1], dtype=np.uint32), *numpy_state[2:]))
    if digest(capture(model, optimizer)) != digest(state):
        raise AssertionError("Complete training-state restoration differs")


def checkpoint_bytes(state, metadata):
    """Lossless serialization; None gradients are actual cleared step-boundary state."""
    record = {"state": state, "state_sha256": digest(state), "metadata": metadata}
    raw = io.BytesIO()
    torch.save(record, raw)
    compressed = gzip.compress(raw.getvalue(), mtime=0)
    reread = torch.load(io.BytesIO(gzip.decompress(compressed)), weights_only=True, map_location="cpu")
    if digest(reread["state"]) != record["state_sha256"]:
        raise AssertionError("Literal checkpoint serialization changed state")
    return compressed


def read_checkpoint(path):
    with gzip.open(path, "rb") as source:
        record = torch.load(io.BytesIO(source.read()), weights_only=True, map_location="cpu")
    if digest(record["state"]) != record["state_sha256"]:
        raise ValueError("Stage-C checkpoint identity differs")
    return record
