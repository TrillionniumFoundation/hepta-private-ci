"""Pinned inputs and measured model material for the V5 learning experiment."""
import json
from pathlib import Path
import time

import torch

from binding_protocol import build_binding_protocol, score_binding_probabilities
from group_encoder import digest_json, file_digest
from group_loop import parameter_digest as typed_digest
from multirc_data import load_jsonl, score_multirc
from token_campaign import inventory as original_inventory
from token_campaign_utils import infer
from token_features import TokenBank
from token_reader import TokenReader
from token_reader_training import parameter_digest

SEEDS = (41, 47, 53)
NEW_RUNTIME = ("binding_protocol.py", "binding_training.py", "binding_continuation.py",
    "revision_execution.py", "revision_training.py", "binding_campaign_utils.py",
    "binding_campaign.py", "binding_evaluation.py", "binding_process.py")


def write(root, name, value):
    path = Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def source_inventory():
    code = Path(__file__).parent
    return {**original_inventory(), **{name: file_digest(code / name) for name in NEW_RUNTIME}}


def inputs(args):
    previous = json.loads((args.previous_main / "design.json").read_text())
    if original_inventory() != previous["source_sha256"]:
        raise ValueError("original V4 runtime changed")
    train = load_jsonl(args.source / "train.jsonl", "train")
    if train.sha256 != previous["dataset_files_sha256"]["train.jsonl"]:
        raise ValueError("official training bytes changed")
    natural = {}
    for role in ("train", "tune"):
        groups = set(previous["partitions"][role])
        natural[role] = tuple(c for c in train.cases if c.source_hash in groups)
        if {c.source_hash for c in natural[role]} != groups:
            raise ValueError("incomplete original natural training partition")
    return build_binding_protocol(seed=41), natural, train.sha256


def checked_design(args):
    design = json.loads((args.output / "design.json").read_text())
    if source_inventory() != design["runtime_source_sha256"]:
        raise ValueError("V5 runtime changed after preparation")
    parts, natural, dataset_sha = inputs(args)
    if dataset_sha != design["train_file_sha256"]:
        raise ValueError("training data changed")
    if (file_digest(args.previous_main / "design.json")
            != design["membership"]["source_files_sha256"]["v4-design"]
            or file_digest(args.previous_native / "all-artifacts-frozen.json")
            != design["previous_native_freeze_sha256"]
            or file_digest(args.snapshot / "material.json") != design["snapshot_material_sha256"]
            or any(file_digest(args.prepared / "features" / name) != expected
                   for name, expected in design["prepared_cache_files_sha256"].items())
            or {k: [c.case_id for c in v] for k, v in natural.items()} != design["natural_case_ids"]):
        raise ValueError("pinned earlier selection, cache, model material or row identities changed")
    return design, parts, natural


def load_bank(args):
    bank = TokenBank.from_snapshot(args.snapshot, batch_size=16, chunk_tokens=64)
    bank.restore_local(args.prepared / "features")
    return bank


def save_model(folder, name, model, receipt, *, initial_digest=None):
    if model.training or any(p.requires_grad for p in model.parameters()):
        raise ValueError("only frozen models can be selected")
    folder.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), folder / (name + ".pt"))
    write(folder, name + "-training.json", receipt)
    record = dict(file=name + ".pt", file_sha256=file_digest(folder / (name + ".pt")),
        training_receipt_file=name + "-training.json",
        training_receipt_sha256=file_digest(folder / (name + "-training.json")),
        training_parameter_sha256=parameter_digest(model), execution_parameter_sha256=typed_digest(model),
        parameter_count=sum(p.numel() for p in model.parameters()),
        training_source_groups=list(model.training_source_groups), initial_execution_parameter_sha256=initial_digest,
        frozen_ns=time.time_ns())
    write(folder, name + "-model.json", record)
    return record


def load_model(folder, name):
    record = json.loads((folder / (name + "-model.json")).read_text())
    path = folder / record["file"]
    if file_digest(path) != record["file_sha256"]:
        raise ValueError("selected weight bytes changed")
    if file_digest(folder / record["training_receipt_file"]) != record["training_receipt_sha256"]:
        raise ValueError("selected training receipt changed")
    model = TokenReader(384, 32)
    model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True), strict=True)
    model.eval().requires_grad_(False)
    model.training_source_groups = tuple(record["training_source_groups"])
    if (parameter_digest(model) != record["training_parameter_sha256"]
            or typed_digest(model) != record["execution_parameter_sha256"]):
        raise ValueError("named weight digest changed")
    return model, record


def load_verifier(args, seed, natural_cases, binding_cases):
    folder = args.previous_native / f"seed-{seed}"
    frozen = json.loads((args.previous_native / "all-artifacts-frozen.json").read_text())
    if file_digest(folder / "artifacts.json") != frozen["artifact_manifests_sha256"][str(seed)]:
        raise ValueError("original verifier selection manifest changed")
    artifact = json.loads((folder / "artifacts.json").read_text())["verifier"]
    path = folder / artifact["file"]
    if file_digest(path) != artifact["file_sha256"]:
        raise ValueError("original independent verifier weight bytes changed")
    model = TokenReader(384, 32)
    model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True), strict=True)
    model.eval().requires_grad_(False)
    model.training_source_groups = tuple(artifact["training_source_groups"])
    if (set(model.training_source_groups) & {c.source_hash for c in (*natural_cases, *binding_cases)}
            or parameter_digest(model) != artifact["model_sha256"]):
        raise ValueError("verifier source overlap or wrong weights")
    provenance = dict(file_path=str(path.resolve()), file_sha256=artifact["file_sha256"],
        model_sha256=typed_digest(model), training_source_groups=list(model.training_source_groups),
        synthetic_trained=False, original_training_reused_not_recharged=True)
    return model, provenance


def binding_panel(root, name, model, cases, bank, *, depth=3, deleted=False, reset=False):
    probabilities, batches = infer(model, cases, bank, depth=depth, deleted=deleted, reset=reset,
                                  batch_size=16, prefix=name)
    metrics = score_binding_probabilities(cases, probabilities)
    write(root, name + ".json", dict(metrics=metrics, probabilities=probabilities,
        case_ids=[c.case_id for c in cases], batches=batches, labels_entered_model=False,
        model_execution_parameter_sha256=typed_digest(model), depth=depth, deleted=deleted, reset=reset))
    return metrics


def natural_panel(root, name, model, cases, bank):
    probabilities, batches = infer(model, cases, bank, depth=3, batch_size=16, prefix=name)
    metrics = score_multirc(cases, [int(p > .5) for p in probabilities])
    write(root, name + ".json", dict(metrics=metrics, probabilities=probabilities,
        case_ids=[c.case_id for c in cases], batches=batches, threshold_selected=False,
        scope="old_training_source_internal_tune_not_fresh", model_execution_parameter_sha256=typed_digest(model)))
    return metrics


def phase_cost(started):
    return dict(cpu_ns=time.process_time_ns() - started[1], wall_ns=time.perf_counter_ns() - started[0],
        includes="setup_restore_training_diagnostics_hashing_serialization", nested_costs_additive=False,
        complete_process_startup_and_exit_included=False, formula_flops=None,
        formula_reason="training_backward_and_python_overheads_not_completely_instrumented")
