"""Pinned V6 model families and byte-auditable initialization, reusing V5 inputs."""
import copy
import hashlib
import json
from pathlib import Path
import time

import torch

from binding_campaign_utils import (checked_design as checked_v5, load_bank,
    load_model as load_v5_model, load_verifier, phase_cost, source_inventory as v5_inventory,
    write)
from bridge_reader import build_reader, reader_identity
from group_encoder import file_digest
from group_loop import parameter_digest as typed_digest
from token_reader_training import parameter_digest

SEEDS = (41, 47, 53)
VARIANTS = ("bridge", "wide")
RUNTIME = ("bridge_reader.py", "bridge_campaign_utils.py", "bridge_campaign.py", "bridge_evaluation.py")


def selected_model_paths():
    """The complete selected V6 family; historical base files are bound separately."""
    result = {}
    for seed in SEEDS:
        for arm, names in (("wide", ("warmup",)), ("bridge", (
                "warmup", "natural_only", "replay", "contrastive", "revision-real", "revision-zero"))):
            for name in names:
                result[f"seed-{seed}/{arm}/{name}-model.json"] = dict(arm=arm, name=name)
    return result


def source_inventory():
    root = Path(__file__).parent
    return {**v5_inventory(), **{name: file_digest(root / name) for name in RUNTIME}}


def old_inputs(args):
    previous = copy.copy(args)
    previous.output = args.previous_v5
    design, parts, natural = checked_v5(previous)
    if (args.previous_v5 / "evaluation-start.json").exists():
        raise ValueError("the reused V5 controlled holdout has already been scored")
    return design, parts, natural


def save_initialization(folder, model, seed):
    """Save sorted FP32 state bytes so a stdlib auditor can reconstruct digests."""
    identity = reader_identity(model)
    common = set(build_reader("base", seed).state_dict())
    folder.mkdir(parents=True, exist_ok=False)
    values, chunks, offset = [], [], 0
    for name, value in sorted(model.state_dict().items()):
        if value.dtype != torch.float32 or not torch.isfinite(value).all():
            raise ValueError("finite FP32 initialization required")
        data = value.detach().cpu().contiguous().numpy().tobytes()
        values.append(dict(name=name, shape=list(value.shape), dtype=str(value.dtype),
            offset=offset, nbytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
            role="common" if name in common else "extra"))
        chunks.append(data)
        offset += len(data)
    path = folder / "initialization.bin"
    path.write_bytes(b"".join(chunks))
    record = dict(schema="hepta.bridge.initialization.v1", arm=identity["arm"], seed=seed,
        file=path.name, file_sha256=file_digest(path), parameter_count=identity["parameter_count"],
        common_parameter_count=identity["base_parameter_count"],
        extra_parameter_count=identity["added_parameter_count"],
        training_parameter_sha256=parameter_digest(model), execution_parameter_sha256=typed_digest(model),
        tensors=values, architecture=identity)
    write(folder, "initialization.json", record)
    return record


def baseline_records(args):
    result = {}
    for seed in SEEDS:
        folder = args.previous_v5 / f"seed-{seed}"
        model, manifest = load_v5_model(folder, "warmup")
        receipt = json.loads((folder / "warmup-training.json").read_text())
        initial = build_reader("base", seed)
        if parameter_digest(initial) != receipt["initial_model_sha256"]:
            raise ValueError("historical base does not have the same actual initialization")
        files = {name: file_digest(folder / name) for name in (
            "warmup.pt", "warmup-model.json", "warmup-training.json", "warmup-binding-train.json",
            "warmup-natural-internal.json", "warmup-gate.json")}
        result[str(seed)] = dict(folder=str(folder.resolve()), files_sha256=files,
            initial_training_parameter_sha256=parameter_digest(initial),
            trained_execution_parameter_sha256=typed_digest(model),
            reused_historical_training=True, newly_performed_training=False,
            historical_fit_cpu_ns=receipt["cpu_ns"], historical_fit_wall_ns=receipt["wall_ns"])
    return result


def checked_design(args):
    design = json.loads((args.output / "design.json").read_text())
    _, parts, natural = old_inputs(args)
    if source_inventory() != design["runtime_source_sha256"]:
        raise ValueError("V6 runtime changed after preparation")
    if file_digest(args.previous_v5 / "design.json") != design["previous_v5_design_sha256"]:
        raise ValueError("previous V5 input selection changed")
    for name, expected in design["initialization_files_sha256"].items():
        if file_digest(args.output / name) != expected:
            raise ValueError("initialization evidence changed")
    for record in design["historical_baselines"].values():
        for name, expected in record["files_sha256"].items():
            if file_digest(Path(record["folder"]) / name) != expected:
                raise ValueError("historical baseline evidence changed")
    return design, parts, natural


def save_model(folder, name, model, receipt, *, seed, initial_digest=None):
    if model.training or any(p.requires_grad for p in model.parameters()):
        raise ValueError("only frozen selected variants can be saved")
    identity = reader_identity(model)
    folder.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), folder / (name + ".pt"))
    write(folder, name + "-training.json", receipt)
    manifest = dict(file=name + ".pt", file_sha256=file_digest(folder / (name + ".pt")),
        seed=seed, architecture=identity, parameter_count=identity["parameter_count"],
        training_receipt_file=name + "-training.json",
        training_receipt_sha256=file_digest(folder / (name + "-training.json")),
        training_parameter_sha256=parameter_digest(model), execution_parameter_sha256=typed_digest(model),
        initial_execution_parameter_sha256=initial_digest,
        training_source_groups=list(model.training_source_groups), frozen_ns=time.time_ns())
    write(folder, name + "-model.json", manifest)
    return manifest


def load_model(folder, name, *, expected_arm=None):
    record = json.loads((folder / (name + "-model.json")).read_text())
    path = folder / record["file"]
    if (file_digest(path) != record["file_sha256"] or
            file_digest(folder / record["training_receipt_file"]) != record["training_receipt_sha256"]):
        raise ValueError("selected variant weight or training receipt bytes changed")
    arm = record["architecture"]["arm"]
    if expected_arm is not None and arm != expected_arm:
        raise ValueError("selected Reader variant differs from admitted arm")
    model = build_reader(arm, record["seed"])
    if reader_identity(model) != record["architecture"]:
        raise ValueError("selected architecture contract changed")
    model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True), strict=True)
    model.eval().requires_grad_(False)
    model.training_source_groups = tuple(record["training_source_groups"])
    if (reader_identity(model) != record["architecture"] or
            parameter_digest(model) != record["training_parameter_sha256"] or
            typed_digest(model) != record["execution_parameter_sha256"]):
        raise ValueError("selected architecture or named parameter digests changed")
    return model, record
