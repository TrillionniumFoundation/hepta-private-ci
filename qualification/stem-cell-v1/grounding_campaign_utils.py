"""V9 immutable starts and lineage over the unchanged V8/V7 public inputs."""
import hashlib
import json
from pathlib import Path
import time

import torch

from binding_campaign_utils import phase_cost, write
from endpoint_campaign_utils import (historical_records, load_bank, old_inputs as old_v8_inputs,
    source_inventory as v8_inventory)
from bridge_campaign_utils import load_model as load_bridge
from group_encoder import file_digest
from group_loop import parameter_digest as typed_digest
from grounding_reader import ARMS, build_grounding_reader, grounding_identity
from reader_features import tensor_digest
from token_reader_training import parameter_digest


SEEDS = (41, 47, 53)
ORDER = {seed: ARMS[i:] + ARMS[:i] for i, seed in enumerate(SEEDS)}
RUNTIME = ("grounding_reader.py", "grounding_spans.py", "grounding_protocol.py",
           "grounding_training.py", "grounding_campaign_utils.py", "grounding_campaign.py",
           "grounding_evaluation.py")


def source_inventory():
    code = Path(__file__).parent
    return {**v8_inventory(), **{name: file_digest(code/name) for name in RUNTIME}}


def old_inputs(args):
    previous, parts, natural, augmentation = old_v8_inputs(args)
    design = json.loads((args.previous_v8/"design.json").read_text())
    complete = json.loads((args.previous_v8/"training-completion.json").read_text())
    frozen = json.loads((args.previous_v8/"all-models-frozen.json").read_text())
    if (design["runtime_source_sha256"] != v8_inventory()
            or complete["runtime_source_sha256"] != v8_inventory()
            or len(frozen["manifests"]) != 12
            or complete["actual_optimizer_updates"] != 18000
            or complete["actual_training_exposures"] != 288000
            or any((args.previous_v8/n).exists() for n in
                   ("feedback-start.json", "evaluation-start.json", "completion.json"))):
        raise ValueError("complete unchanged V8 with unused downstream domains required")
    for name, wanted in frozen["manifests"].items():
        if file_digest(args.previous_v8/name) != wanted:
            raise ValueError("historical V8 selection changed")
    return previous, parts, natural, augmentation


def save_initialization(folder, model, core, seed):
    identity = grounding_identity(model)
    common, state = core.state_dict(), model.state_dict()
    if any(n not in state or tensor_digest(v) != tensor_digest(state[n]) for n, v in common.items()):
        raise ValueError("every actual V6 warmup tensor must be copied exactly")
    folder.mkdir(parents=True, exist_ok=False)
    torch.save(state, folder/"initialization.pt")
    values, chunks, offset = [], [], 0
    for name, value in sorted(state.items()):
        if value.dtype != torch.float32 or value.device.type != "cpu" or not torch.isfinite(value).all():
            raise ValueError("finite CPU FP32 initialization required")
        data = value.detach().contiguous().numpy().tobytes()
        values.append(dict(name=name, shape=list(value.shape), dtype=str(value.dtype), offset=offset,
            nbytes=len(data), sha256=hashlib.sha256(data).hexdigest(), role="common" if name in common else "extra"))
        chunks.append(data)
        offset += len(data)
    (folder/"initialization.bin").write_bytes(b"".join(chunks))
    record = dict(schema="hepta.grounding.initialization.v9", seed=seed, arm=identity["arm"],
        file="initialization.pt", file_sha256=file_digest(folder/"initialization.pt"),
        raw_file="initialization.bin", raw_file_sha256=file_digest(folder/"initialization.bin"),
        tensors=values, architecture=identity, parameter_count=sum(p.numel() for p in model.parameters()),
        common_parameter_count=sum(p.numel() for p in core.parameters()),
        training_parameter_sha256=parameter_digest(model), execution_parameter_sha256=typed_digest(model),
        common_training_parameter_sha256=parameter_digest(core), common_execution_parameter_sha256=typed_digest(core),
        training_source_groups=list(model.training_source_groups))
    write(folder, "initialization.json", record)
    return record


def load_initialization(folder):
    record = json.loads((folder/"initialization.json").read_text())
    if file_digest(folder/record["file"]) != record["file_sha256"]:
        raise ValueError("initial model bytes changed")
    model = build_grounding_reader(record["arm"], record["seed"])
    model.load_state_dict(torch.load(folder/record["file"], map_location="cpu", weights_only=True), strict=True)
    model.eval().requires_grad_(False)
    model.training_source_groups = tuple(record["training_source_groups"])
    if (grounding_identity(model) != record["architecture"]
            or parameter_digest(model) != record["training_parameter_sha256"]
            or typed_digest(model) != record["execution_parameter_sha256"]):
        raise ValueError("initial model geometry or named tensor digest changed")
    return model, record


def save_model(folder, model, receipt, *, seed, initial_digest):
    if model.training or any(p.requires_grad for p in model.parameters()):
        raise ValueError("only frozen V9 final models may be selected")
    identity = grounding_identity(model)
    torch.save(model.state_dict(), folder/"final.pt")
    write(folder, "final-training.json", receipt)
    record = dict(file="final.pt", file_sha256=file_digest(folder/"final.pt"), seed=seed,
        architecture=identity, parameter_count=sum(p.numel() for p in model.parameters()),
        training_receipt_file="final-training.json", training_receipt_sha256=file_digest(folder/"final-training.json"),
        training_parameter_sha256=parameter_digest(model), execution_parameter_sha256=typed_digest(model),
        initial_execution_parameter_sha256=initial_digest, training_source_groups=list(model.training_source_groups),
        frozen_ns=time.time_ns())
    write(folder, "final-model.json", record)
    return record


def load_model(folder):
    record = json.loads((folder/"final-model.json").read_text())
    if (file_digest(folder/record["file"]) != record["file_sha256"]
            or file_digest(folder/record["training_receipt_file"]) != record["training_receipt_sha256"]):
        raise ValueError("final model or training receipt bytes changed")
    model = build_grounding_reader(record["architecture"]["arm"], record["seed"])
    model.load_state_dict(torch.load(folder/record["file"], map_location="cpu", weights_only=True), strict=True)
    model.eval().requires_grad_(False)
    model.training_source_groups = tuple(record["training_source_groups"])
    if (grounding_identity(model) != record["architecture"]
            or parameter_digest(model) != record["training_parameter_sha256"]
            or typed_digest(model) != record["execution_parameter_sha256"]):
        raise ValueError("final model geometry or named tensor digest changed")
    return model, record


def learning_change(folder, model):
    started = time.perf_counter_ns(), time.process_time_ns()
    initial, record = load_initialization(folder)
    roles = {r["name"]: r["role"] for r in record["tensors"]}
    tensors = []
    for name, value in sorted(model.state_dict().items()):
        before = initial.state_dict()[name]
        delta = value.double()-before.double()
        tensors.append(dict(name=name, role=roles[name], shape=list(value.shape),
            before_sha256=tensor_digest(before), after_sha256=tensor_digest(value),
            l2=delta.norm().item(), maximum_absolute_delta=delta.abs().max().item(),
            before_nonzeros=torch.count_nonzero(before).item(), after_nonzeros=torch.count_nonzero(value).item()))
    write(folder, "learning-change.json", dict(schema="hepta.grounding.learning-change.v9", tensors=tensors,
        initial_execution_parameter_sha256=record["execution_parameter_sha256"],
        final_execution_parameter_sha256=typed_digest(model), phase_cost=phase_cost(started)))


def checked_design(args):
    design = json.loads((args.output/"design.json").read_text())
    previous, parts, natural, augmentation = old_inputs(args)
    code = Path(__file__).parent
    if (source_inventory() != design["runtime_source_sha256"]
            or file_digest(code/"GROUNDING_V9_PROTOCOL.md") != design["protocol_sha256"]
            or file_digest(args.previous_v8/"design.json") != design["previous_v8_design_sha256"]
            or file_digest(args.previous_v8/"training-completion.json") != design["previous_v8_completion_sha256"]
            or previous["extended_cache_files_sha256"] != design["reused_cache_files_sha256"]):
        raise ValueError("frozen V9 source, protocol, lineage or input cache changed")
    for name, wanted in design["prepared_files_sha256"].items():
        if file_digest(args.output/name) != wanted:
            raise ValueError("prepared cases, auxiliary targets, plans or initial weights changed")
    complete = json.loads((args.output/"preparation-completion.json").read_text())
    expected = {f"seed-{seed}/{arm}/initial-binding-train.json" for seed in SEEDS for arm in ARMS}
    if (complete["design_sha256"] != file_digest(args.output/"design.json")
            or complete["exact_initial_probability_equality"] != {str(s): True for s in SEEDS}
            or set(complete["initial_panels_sha256"]) != expected):
        raise ValueError("complete V9 actual initial probability evidence required")
    for name, wanted in complete["initial_panels_sha256"].items():
        if file_digest(args.output/name) != wanted:
            raise ValueError("actual initial panel changed")
    for seed in SEEDS:
        reference = None
        tensor_reference = None
        for arm in ARMS:
            folder = args.output/f"seed-{seed}"/arm
            panel = json.loads((folder/"initial-binding-train.json").read_text())
            model, record = load_initialization(folder)
            if (panel["case_ids"] != [c.case_id for c in parts["reader_train"]]
                    or panel["model_execution_parameter_sha256"] != record["execution_parameter_sha256"]
                    or reference is not None and panel["probabilities"] != reference
                    or tensor_reference is not None and typed_digest(model) != tensor_reference):
                raise ValueError("four-arm initial predictions, complete tensors or rows differ")
            reference, tensor_reference = panel["probabilities"], typed_digest(model)
    return design, parts, natural, augmentation


def frozen_selections(args, design):
    frozen = json.loads((args.output/"all-models-frozen.json").read_text())
    complete = json.loads((args.output/"training-completion.json").read_text())
    expected = {f"seed-{seed}/{arm}/final-model.json" for seed in SEEDS for arm in ARMS}
    if (set(frozen["manifests"]) != expected or frozen["runtime_source_sha256"] != design["runtime_source_sha256"]
            or complete["actual_optimizer_updates"] != 18000 or complete["actual_training_exposures"] != 288000):
        raise ValueError("all twelve fixed V9 models must freeze before any new-domain encoding")
    for name, wanted in frozen["manifests"].items():
        if file_digest(args.output/name) != wanted:
            raise ValueError("a frozen model selection changed")
        load_model((args.output/name).parent)
    return frozen
