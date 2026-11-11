"""Pinned inputs and exact native modules for one bounded engineering run."""

import hashlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True,
                                ensure_ascii=False, allow_nan=False) + "\n")


def identity(path):
    raw = Path(path).read_bytes()
    return {"bytes": len(raw), "sha256": sha(raw)}


def frozen(run):
    lock = read(run / "LOCK.json")
    for name, expected in lock.items():
        if identity(run / name)["sha256"] != expected:
            raise ValueError("Frozen manifest changed: " + name)
    for name, expected in read(run / "INVENTORY.json").items():
        if identity(run / name) != expected["identity"]:
            raise ValueError("Frozen input changed: " + name)
    return read(run / "PROTOCOL.json")


def runtime(run):
    plan = frozen(run)
    code = run / "EXECUTED_SOURCE"
    sys.path.insert(0, str(code / "validator"))
    modules = {}
    for name in ("adapter", "download_model", "backend", "lifecycle", "tasks"):
        path = (code / "tasks.py" if name == "tasks" else
                code / "validator" / "reference" / (name + ".py.source"))
        loader = importlib.machinery.SourceFileLoader(name, str(path))
        spec = importlib.util.spec_from_loader(name, loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        loader.exec_module(module)
        modules[name] = module
    import verify_closure
    return plan, modules, verify_closure.verify_checkpoint


def report(run, phase):
    return read(run / "phase_results" / (phase + ".json"))["result"]


def model_summary(model):
    groups = {}
    for group in ("params", "m", "v"):
        groups[group] = sha(b"".join(
            name.encode() + array.dtype.str.encode() + canonical(list(array.shape))
            + array.tobytes(order="C")
            for name, array in sorted(getattr(model, group).items())))
    sampler = {k: v for k, v in model.sampler.items() if k != "order"}
    sampler["order"] = model.sampler["order"].tolist()
    return {"state_sha256": model.state_hash(), "step": model.step,
            "groups": groups, "rng_sha256": sha(canonical(model.rng.bit_generator.state)),
            "sampler_sha256": sha(canonical(sampler)), "sampler": sampler,
            "optimizer": dict(model.optimizer), "source_version": model.source_version}
