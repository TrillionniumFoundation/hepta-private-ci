"""Helpers used only by the separately frozen native003 extension."""

import hashlib
import json
from pathlib import Path

import torch

from .model import HCSNClassifier
from .native003_heads import StopHead
from .training import load_weights


PACKAGE = Path(__file__).resolve().parent
REPOSITORY = PACKAGE.parents[1]
PROTOCOL_PATH = PACKAGE / "NATIVE003_PROTOCOL.json"


def read_json(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def verify_freeze(output):
    record = read_json(Path(output) / "FREEZE.json")
    for name, expected in record["files"].items():
        if sha(REPOSITORY / name) != expected:
            raise ValueError(f"native003 frozen input changed: {name}")
    return record


def load_backbone(protocol):
    run = PACKAGE / protocol["backbone"]["training_run"]
    summary = read_json(run / "summary.json")
    execution = read_json(run / "EXECUTION.json")
    if summary["status"] != "completed" or execution["status"] != "completed" or execution["returncode"] != 0:
        raise ValueError("Backbone training did not complete")
    if sha(run / "selected.npz") != protocol["backbone"]["selected_checkpoint_sha256"]:
        raise ValueError("Fixed backbone checkpoint changed")
    model = HCSNClassifier(**summary["selected_model_config"]).cpu().eval()
    load_weights(run / "selected.npz", model)
    model.requires_grad_(False)
    identity = {"checkpoint_sha256": sha(run / "selected.npz"),
                "config": summary["selected_model_config"],
                "training_execution_sha256": sha(run / "EXECUTION.json"),
                "complete_training_child_cpu_seconds": execution["child_cpu_seconds"],
                "training_execution": execution}
    return model, identity


def load_head(output, family):
    directory = Path(output) / "head_search" / family
    selected = read_json(directory / "selection.json")
    normalization = read_json(Path(output) / "traces" / "NORMALIZATION.json")
    weights = directory / "selected.npz"
    if sha(weights) != selected["selected_checkpoint_sha256"]:
        raise ValueError("Selected native003 head checkpoint changed")
    head = StopHead(family, normalization["mean"], normalization["std"], selected["seed"]).cpu().eval()
    load_weights(weights, head)
    head.requires_grad_(False)
    return head, selected
