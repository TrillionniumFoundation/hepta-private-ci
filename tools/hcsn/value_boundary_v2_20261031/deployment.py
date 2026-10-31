"""Measured serialization and validation of a single deployable policy table."""
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .model import Contract, Model
from .owner import save, sha


def load_policy(root, descriptor):
    wall, cpu = time.perf_counter(), time.process_time()
    raw = (Path(root)/descriptor["path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != descriptor["sha256"]:
        raise ValueError("Deployable policy artifact changed")
    artifact = json.loads(raw)
    if artifact["schema"] != "hcsn.regenerative-evidence.deployable-policy.v1":
        raise ValueError("Unknown deployable policy schema")
    model = Model(Contract(**artifact["contract"]))
    if artifact["states"] != [list(state) for state in model.states]:
        raise ValueError("Deployable policy state ordering changed")
    if artifact["kind"] == "hard":
        model.deterministic(artifact["actions"])
    elif artifact["kind"] == "soft":
        model.checked_policy(np.asarray(artifact["probabilities"]))
    else:
        raise ValueError("Unknown policy deployment kind")
    timing = dict(cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall,
                  bytes=len(raw), scope="One policy file read, digest, JSON decode, model/state/guard validation")
    return artifact, timing


def write_policy(root, name, model, actions=None, probabilities=None):
    if (actions is None) == (probabilities is None):
        raise ValueError("Exactly one deployment representation is required")
    wall, cpu = time.perf_counter(), time.process_time()
    relative = f"deployment/{name}.json"
    artifact = dict(schema="hcsn.regenerative-evidence.deployable-policy.v1",
                    contract=model.contract.serializable(), states=[list(state) for state in model.states])
    if actions is not None:
        model.deterministic(actions)
        artifact.update(kind="hard", actions=np.asarray(actions, int).tolist())
    else:
        probabilities = model.checked_policy(probabilities)
        artifact.update(kind="soft", probabilities=probabilities.tolist())
    save(Path(root)/relative, artifact)
    descriptor = dict(path=relative, sha256=sha(Path(root)/relative),
        serialization_cpu_seconds=time.process_time()-cpu,
        serialization_wall_seconds=time.perf_counter()-wall)
    _, timing = load_policy(root, descriptor)
    descriptor["prepare_load_validation"] = timing
    return descriptor


def preparation_io_cpu(descriptor):
    return descriptor["serialization_cpu_seconds"]+descriptor["prepare_load_validation"]["cpu_seconds"]
