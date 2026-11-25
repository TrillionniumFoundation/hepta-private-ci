"""Create-only receipts and executable-source bindings for this campaign."""

import hashlib
import json
import os
from pathlib import Path

import torch

from qualification.hcsn_smallnet_20261124.train import runtime_identity, source_hashes
from .models import make_model


HERE = Path(__file__).resolve().parent
OWN_FILES = ("__init__.py", "data.py", "models.py", "provenance.py", "runner.py", "campaign.py")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def create(path, value):
    path = Path(path)
    temp = path.with_name(path.name + ".publish.tmp")
    with temp.open("x") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.link(temp, path)
    temp.unlink()


def sources():
    return {**source_hashes(), **{__package__ + "." + p: digest(HERE / p) for p in OWN_FILES}}


def prepare(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    p = read(HERE / "protocol.json")
    p.update(source_hashes=sources(), runtime=runtime_identity())
    create(root / "PROTOCOL.json", p)
    return p


def load(root):
    p = read(Path(root) / "PROTOCOL.json")
    if p["source_hashes"] != sources() or p["runtime"] != runtime_identity():
        raise ValueError("frozen executable source or runtime has changed")
    return p


def seal(root, p):
    root = Path(root)
    rows = {}
    for slot in p["slots"]:
        directory = root / slot["id"]
        validate_record(directory, p, slot)
        files = ("result.json", "worker_cost.json", "history.json", "checkpoint.pt", "parent_cost.json")
        rows[slot["id"]] = {name: digest(directory / name) for name in files if (directory / name).exists()}
        if "worker_cost.json" not in rows[slot["id"]] or "parent_cost.json" not in rows[slot["id"]]:
            raise ValueError("missing authoritative worker/parent terminal receipt")
    value = {"schema": "hcsn-prospective-seal-v1", "protocol_sha256": identity(p), "attempts": rows}
    create(root / "SEAL.json", value)
    return value


def validate_record(directory, p, slot):
    result = read(directory / "result.json")
    worker = read(directory / "worker_cost.json")
    parent = read(directory / "parent_cost.json")
    if (result["slot"] != slot or result["protocol_sha256"] != identity(p)
            or result["smoke"] is not False
            or result["status"] not in ("completed", "censored_cpu", "failed")
            or worker["status"] != result["status"] or worker["error"] is not None
            or parent["error"] is not None
            or parent["returncode"] != (1 if result["status"] == "failed" else 0)):
        raise ValueError("invalid terminal record, smoke, identity or process status")
    history = read(directory / "history.json")
    if not isinstance(history, list):
        raise ValueError("missing development history")
    if result["status"] == "failed":
        if not result["error"]:
            raise ValueError("failure requires preserved diagnostic")
        if result["checkpoint_sha256"] is not None and digest(directory / "checkpoint.pt") != result["checkpoint_sha256"]:
            raise ValueError("failed checkpoint identity changed")
        return
    if (result["checkpoint_sha256"] is None
            or digest(directory / "checkpoint.pt") != result["checkpoint_sha256"]):
        raise ValueError("successful or censored attempt lacks its exact checkpoint")
    saved = torch.load(directory / "checkpoint.pt", map_location="cpu", weights_only=True)
    if (saved["slot"] != slot or saved["protocol_sha256"] != identity(p) or saved["smoke"] is not False
            or saved["selected_step"] != result["selected_step"]
            or saved["cpu_prefix_step"] != result["cpu_prefix_step"]
            or saved["updates"] != result["updates"]
            or not 0 <= saved["selected_step"] <= saved["updates"]
            or not 0 <= saved["cpu_prefix_step"] <= saved["updates"]
            or result["cpu_prefix_training_cpu_seconds"] > p["training"]["cpu_prefix"]
            or (result["status"] == "completed" and saved["updates"] != p["training"]["max_updates"])):
        raise ValueError("checkpoint selected/prefix/terminal header mismatch")
    expected = make_model(slot).state_dict()
    for key in ("initial_model", "selected_model", "last_model", "cpu_prefix_model"):
        state = saved[key]
        if not isinstance(state, dict) or set(state) != set(expected):
            raise ValueError("checkpoint model state is incomplete")
        for name, value in state.items():
            if (not isinstance(value, torch.Tensor) or value.shape != expected[name].shape
                    or value.dtype != expected[name].dtype or not bool(torch.isfinite(value).all())):
                raise ValueError("checkpoint tensor is invalid: " + key + "/" + name)
        for name in ("synaptic_mask", "reset_absolute", "fixed_boundary"):
            if not torch.equal(state[name], expected[name]):
                raise ValueError("signed mask or physical buffer changed")


def check_seal(root, p):
    root = Path(root)
    value = read(root / "SEAL.json")
    if value["protocol_sha256"] != identity(p) or set(value["attempts"]) != {s["id"] for s in p["slots"]}:
        raise ValueError("incomplete or foreign seal")
    for name, files in value["attempts"].items():
        for relative, expected in files.items():
            if digest(root / name / relative) != expected:
                raise ValueError("sealed artifact changed: " + name + "/" + relative)
    for slot in p["slots"]:
        validate_record(root / slot["id"], p, slot)
    return value
