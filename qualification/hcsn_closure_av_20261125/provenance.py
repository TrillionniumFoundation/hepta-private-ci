"""Create-only source/data/checkpoint bindings and the global AV test gate."""

import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform

import numpy as np
import torch

from .models import PairedEncoder


HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def create(path, value):
    with Path(path).open("x") as f:
        json.dump(value, f, sort_keys=True, indent=2, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())


def sources():
    pending = [__package__+"."+name for name in ("campaign", "runner", "prepare", "retime", "acquire", "tests")]
    found = {}
    while pending:
        module = pending.pop()
        if module in found:
            continue
        spec = importlib.util.find_spec(module)
        if spec is None:
            raise ImportError(module)
        if spec.origin is None:
            continue
        path = Path(spec.origin)
        found[module] = digest(path)
        package = module if spec.submodule_search_locations is not None else module.rpartition(".")[0]
        for i in range(1, len(module.split("."))):
            pending.append(".".join(module.split(".")[:i]))
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                name = importlib.util.resolve_name("."*node.level+(node.module or ""), package) if node.level else (node.module or "")
                names = [name] if node.module else [name+"."+item.name for item in node.names]
            else:
                continue
            pending.extend(n for n in names if n == "qualification" or n.startswith("qualification."))
    return dict(sorted(found.items()))


def runtime():
    return {"python": platform.python_version(), "torch": str(torch.__version__),
            "numpy": np.__version__, "threads": torch.get_num_threads(), "device": "cpu"}


def expected_protocol(data):
    p = read(HERE/"protocol.json")
    if len(p["slots"]) != 9 or len({s["id"] for s in p["slots"]}) != 9:
        raise ValueError("complete unique nine-slot roster required")
    fast_path = Path(importlib.util.find_spec("qualification.hcsn_closure_20261124.fast_kernel").origin)
    if digest(fast_path) != "a92d7cc45af0ccf1e1c2629ee9fe8ef1d4b0bc6dba335bbdc53cd909c42d80b3":
        raise ValueError("AV requires the independently qualified fast backend")
    p.update(source_hashes=sources(), runtime=runtime(), base_protocol_sha256=digest(HERE/"protocol.json"),
             data_root=str(data.resolve()), dataset_sha256=digest(data/"DATASET.json"), dataset=read(data/"DATASET.json"))
    for split, expected in p["cohort"].items():
        row = p["dataset"]["splits"][split]
        if sorted(row["actors"]) != sorted(expected["actors"]) or row["examples"] != expected["examples"]:
            raise ValueError("dataset descriptor differs from approved cohort")
    return p


def prepare(root, data):
    root.mkdir(parents=True, exist_ok=False)
    p = expected_protocol(data)
    for row in p["dataset"]["splits"].values():
        if digest(data/row["path"]) != row["sha256"]:
            raise ValueError("prepared data hash mismatch")
    create(root/"PROTOCOL.json", p)
    return p


def load(root):
    p = read(root/"PROTOCOL.json")
    if p != expected_protocol(Path(p["data_root"])):
        raise ValueError("complete protocol object differs from source/runtime/data originals")
    return p


def load_data(p, split):
    row = p["dataset"]["splits"][split]
    path = Path(p["data_root"])/row["path"]
    if digest(path) != row["sha256"]:
        raise ValueError("input cache changed")
    with np.load(path, allow_pickle=False) as f:
        result = {k: f[k].copy() for k in f.files}
    if len(result["y"]) != row["examples"] or sorted(set(result["actor"].tolist())) != row["actors"]:
        raise ValueError("input cohort mismatch")
    expected = np.stack((np.arange(32)/31, np.full(32, 1/32)), -1).astype(np.float32)
    for modality in ("audio", "video"):
        if (result[modality].shape != (len(result["y"]), 32, 130)
                or not np.array_equal(result[modality][..., 128:], np.broadcast_to(expected, (len(result["y"]), 32, 2)))):
            raise ValueError("model inputs contain a noncanonical timing channel")
    return result


def validate(root, p, slot):
    directory = root/slot["id"]
    row, worker, parent = (read(directory/name) for name in ("result.json", "worker_cost.json", "parent_cost.json"))
    if (row["slot"] != slot or row["protocol_sha256"] != identity(p) or row["smoke"] is not False
            or row["status"] not in ("completed", "censored_cpu", "failed")
            or worker["status"] != row["status"] or worker["error"] is not None
            or parent["error"] is not None or parent["returncode"] != (1 if row["status"] == "failed" else 0)):
        raise ValueError("invalid terminal training slot")
    if row["status"] == "failed":
        if not row["error"]:
            raise ValueError("missing failure diagnostic")
        return
    if (row["updates"] > p["training"]["max_updates"]
            or (row["status"] == "completed") != (row["updates"] == p["training"]["max_updates"])
            or digest(directory/"checkpoint.pt") != row["checkpoint_sha256"]):
        raise ValueError("incorrect completed/censored checkpoint")
    checkpoint = torch.load(directory/"checkpoint.pt", map_location="cpu", weights_only=True)
    if any(checkpoint[k] != row[k] for k in ("slot", "protocol_sha256", "smoke", "updates", "selected_step")):
        raise ValueError("checkpoint header mismatch")
    fresh = PairedEncoder(slot["arm"], slot["seed"])
    template = fresh.state_dict()
    history = read(directory/"history.json")
    selected = min(history, key=lambda item: item["development"]["fused"]["cross_entropy"])
    if (not history or history[0]["step"] != 0 or selected["step"] != row["selected_step"]
            or selected["development"] != row["selected_development"]
            or history[0]["development"] != row["initial_development"]
            or row["selected_step"] > row["updates"] or row["parameter_accounting"] != fresh.counts()):
        raise ValueError("development selection or parameter accounting mismatch")
    for name in ("initial_model", "selected_model", "last_model"):
        state = checkpoint[name]
        if state.keys() != template.keys():
            raise ValueError("incomplete model state")
        for key, value in state.items():
            ref = template[key]
            if value.shape != ref.shape or value.dtype != ref.dtype or not bool(torch.isfinite(value).all()):
                raise ValueError("invalid checkpoint tensor")
            if key.endswith(("synaptic_mask", "reset_absolute", "fixed_boundary")) and not torch.equal(value, ref):
                raise ValueError("physical or communication buffer changed")
            if name == "initial_model" and not torch.equal(value, ref):
                raise ValueError("initial model is not the declared seeded initialization")


def seal(root, p):
    slots = {}
    for slot in p["slots"]:
        validate(root, p, slot)
        directory = root/slot["id"]
        names = ("result.json", "history.json", "checkpoint.pt", "worker_cost.json", "parent_cost.json")
        slots[slot["id"]] = {name: digest(directory/name) for name in names if (directory/name).exists()}
    create(root/"SEAL.json", {"protocol_sha256": identity(p), "attempts": slots})


def check_seal(root, p):
    value = read(root/"SEAL.json")
    if value["protocol_sha256"] != identity(p) or set(value["attempts"]) != {s["id"] for s in p["slots"]}:
        raise ValueError("incomplete or foreign seal")
    for slot in p["slots"]:
        for name, expected in value["attempts"][slot["id"]].items():
            if digest(root/slot["id"]/name) != expected:
                raise ValueError("sealed training file changed")
        validate(root, p, slot)
    return digest(root/"SEAL.json")
