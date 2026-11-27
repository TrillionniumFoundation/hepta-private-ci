"""V8 endpoint variants, frozen V7 input reuse and support-only diagnostics."""
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time

import torch

from binding_campaign_utils import phase_cost, write
from binding_protocol import _digest, score_binding_probabilities, verify_binding_cases
from bridge_campaign_utils import load_model as load_bridge
from endpoint_reader import build_endpoint_reader, endpoint_identity, load_bridge_warmup
from group_encoder import file_digest
from group_loop import parameter_digest as typed_digest
from reader_features import tensor_digest
from retention_campaign_utils import checked_design as checked_v7, load_bank as v7_bank, source_inventory as v7_inventory
from token_campaign_utils import infer
from token_reader_training import parameter_digest


SEEDS = (41, 47, 53)
ARMS = ("bridge", "endpoint", "broken", "local")
ORDER = {seed: ARMS[i:] + ARMS[:i] for i,seed in enumerate(SEEDS)}
RUNTIME = ("endpoint_reader.py", "endpoint_campaign_utils.py", "endpoint_campaign.py")


def source_inventory():
    code = Path(__file__).parent
    return {**v7_inventory(), **{name:file_digest(code/name) for name in RUNTIME}}


def old_inputs(args):
    previous = copy.copy(args)
    previous.output = args.previous_v7
    design,parts,natural,augmentation = checked_v7(previous)
    completed = json.loads((args.previous_v7/"training-completion.json").read_text())
    if (completed["runtime_source_sha256"] != design["runtime_source_sha256"]
            or set(completed["gates"]) != {str(s) for s in SEEDS}
            or any(set(g) != {"repeat","diverse","anchored","low_lr"} for g in completed["gates"].values())
            or any((args.previous_v7/name).exists() for name in
                   ("feedback-start.json","evaluation-start.json","completion.json"))):
        raise ValueError("complete unchanged V7 training with unused downstream domains required")
    return design,parts,natural,augmentation


def historical_records(args, design):
    observations = {}
    names = ("teacher.json","teacher-logits.bin","start-natural-train.json","training-plan.json",
             "diverse-model.json","diverse-training.json")
    for seed in SEEDS:
        folder = args.previous_v7/f"seed-{seed}"
        observations[str(seed)] = dict(folder=str(folder.resolve()),
            files_sha256={n:file_digest(folder/n) for n in names},
            reused_teacher_neural_calls=0,reused_natural_start_neural_calls=0)
    return dict(warmups=design["historical_warmups"],observations=observations)


def teacher_reference(args, seed, cases, core_record):
    folder = args.previous_v7/f"seed-{seed}"
    record = json.loads((folder/"teacher.json").read_text())
    data = (folder/record["raw_file"]).read_bytes()
    if (record["shape"] != [len(cases),2] or record["dtype"] != "torch.float32"
            or record["case_ids"] != [c.case_id for c in cases]
            or len(data) != len(cases)*8 or hashlib.sha256(data).hexdigest() != record["raw_logits_sha256"]
            or record["raw_file_sha256"] != record["raw_logits_sha256"]
            or record["model_execution_parameter_sha256"] != core_record["execution_parameter_sha256"]
            or record["model_training_parameter_sha256"] != core_record["training_parameter_sha256"]
            or record["warmup_weight_file_sha256"] != core_record["file_sha256"]):
        raise ValueError("actual V7 teacher reference differs from V6 warmup or old row order")
    tensor = torch.frombuffer(bytearray(data),dtype=torch.float32).reshape(len(cases),2).clone()
    if not torch.isfinite(tensor).all() or tensor.tolist() != record["logits"]:
        raise ValueError("teacher raw bytes and saved finite logits disagree")
    return tensor,record


def load_bank(args):
    previous = copy.copy(args)
    previous.output = args.previous_v7
    return v7_bank(previous)


def support_transform(cases):
    verify_binding_cases(cases)
    rows = []
    for case in cases:
        positions = [i for i,s in enumerate(case.sentence_ids) if s in case.evidence_sentence_indices]
        if (len(case.facts) != 4 or len(case.sentence_ids) != 4
                or len(case.evidence_sentence_indices) != 2 or len(set(positions)) != 2):
            raise ValueError("two independently verified binding support sentences required")
        rows.append(dict(case_id=case.case_id,public_source_sha256=case.feature_source_hash,
            support_sentence_ids=list(case.evidence_sentence_indices),
            deleted_fact_positions=positions))
    return dict(schema="hepta.endpoint.support-delete.v8",cases=rows,case_ids=[c.case_id for c in cases],
        transform_sha256=_digest(rows),kind="zero_verified_support_fact_rows_and_masks_keep_positions",
        exactly_two_support_facts=True,labels_unchanged=True,annotations_enter_forward=False,
        missing_evidence_can_make_task_unanswerable=True,diagnostic_only=True)


class SupportDeletedBank:
    """Change only verified support rows, retaining other facts and all public roles."""
    def __init__(self, bank, transform):
        self.bank,self.rows,self.observations = bank,{r["case_id"]:r for r in transform["cases"]},[]

    def _selected(self, case):
        row = self.rows[case.case_id]
        expected = [i for i,s in enumerate(case.sentence_ids) if s in case.evidence_sentence_indices]
        if (case.feature_source_hash != row["public_source_sha256"] or len(case.facts) != 4
                or len(case.sentence_ids) != 4 or len(set(expected)) != 2
                or row["support_sentence_ids"] != list(case.evidence_sentence_indices)
                or row["deleted_fact_positions"] != expected):
            raise ValueError("support-deletion source identity changed")
        layout = [i for i,text in enumerate(case.facts)
                  for _ in range(0,len(self.bank.tokens[text]),self.bank.payload_tokens)]
        selected = [i for i,sentence in enumerate(layout) if sentence in row["deleted_fact_positions"]]
        if layout != list(range(4)) or selected != row["deleted_fact_positions"] or len(selected) != 2:
            raise ValueError("four single-chunk facts and exactly two support rows required")
        return selected

    def batch(self, cases):
        cases = tuple(cases)
        original = self.bank.batch(cases)
        facts,mask = original.facts.clone(),original.fact_mask.clone()
        positions = []
        for index,case in enumerate(cases):
            selected = self._selected(case)
            if facts.shape[1] != 4:
                raise ValueError("four single-chunk facts and exactly two support rows required")
            facts[index,selected],mask[index,selected] = 0,False
            positions.append(selected)
        result = replace(original,facts=facts,fact_mask=mask,evidence_targets=None,evidence_supervision=None)
        self.observations.append(dict(case_ids=[c.case_id for c in cases],deleted_chunk_positions=positions,
            original_feature_sha256=[tensor_digest(v) for v in original.features()],
            transformed_feature_sha256=[tensor_digest(v) for v in result.features()],
            feature_shapes=[list(v.shape) for v in result.features()],labels_and_order_unchanged=True))
        return result


def support_deleted_panel(folder, model, cases, bank, transform):
    wrapper = SupportDeletedBank(bank,transform)
    # Reject a malformed last case before running even the first diagnostic batch.
    for case in cases:
        wrapper._selected(case)
    probabilities,batches = infer(model,cases,wrapper,depth=3,batch_size=16,prefix="diagnostics/deleted3")
    metrics = score_binding_probabilities(cases,probabilities)
    write(folder,"diagnostics/deleted3.json",dict(metrics=metrics,probabilities=probabilities,
        case_ids=[c.case_id for c in cases],batches=batches,transform_observations=wrapper.observations,
        support_transform_sha256=transform["transform_sha256"],deleted_support_only=True,
        all_evidence_deleted=False,reset=False,depth=3,labels_entered_model=False,
        model_execution_parameter_sha256=typed_digest(model),used_for_gate_or_selection=False))
    return metrics


def save_initialization(folder, model, core, seed):
    identity = endpoint_identity(model)
    common = core.state_dict()
    state = model.state_dict()
    if any(name not in state or tensor_digest(value) != tensor_digest(state[name]) for name,value in common.items()):
        raise ValueError("all actual V6 warmup tensors must remain byte-identical")
    folder.mkdir(parents=True,exist_ok=False)
    torch.save(state,folder/"initialization.pt")
    values,chunks,offset = [],[],0
    for name,value in sorted(state.items()):
        if value.dtype != torch.float32 or not torch.isfinite(value).all():
            raise ValueError("finite FP32 initialization required")
        data = value.detach().cpu().contiguous().numpy().tobytes()
        values.append(dict(name=name,shape=list(value.shape),dtype=str(value.dtype),offset=offset,
            nbytes=len(data),sha256=hashlib.sha256(data).hexdigest(),role="common" if name in common else "extra"))
        chunks.append(data)
        offset += len(data)
    (folder/"initialization.bin").write_bytes(b"".join(chunks))
    record = dict(schema="hepta.endpoint.initialization.v8",arm=identity["arm"],seed=seed,
        file="initialization.pt",file_sha256=file_digest(folder/"initialization.pt"),
        raw_file="initialization.bin",raw_file_sha256=file_digest(folder/"initialization.bin"),
        tensors=values,architecture=identity,parameter_count=sum(v.numel() for v in model.parameters()),
        common_parameter_count=sum(v.numel() for v in core.parameters()),
        extra_parameter_count=sum(v.numel() for n,v in state.items() if n not in common),
        training_parameter_sha256=parameter_digest(model),execution_parameter_sha256=typed_digest(model),
        common_training_parameter_sha256=parameter_digest(core),common_execution_parameter_sha256=typed_digest(core))
    record["training_source_groups"] = list(model.training_source_groups)
    write(folder,"initialization.json",record)
    return record


def save_model(folder, model, receipt, *, seed, initial_digest):
    if model.training or any(p.requires_grad for p in model.parameters()):
        raise ValueError("only frozen endpoint-family final models may be selected")
    identity = endpoint_identity(model)
    torch.save(model.state_dict(),folder/"final.pt")
    write(folder,"final-training.json",receipt)
    record = dict(file="final.pt",file_sha256=file_digest(folder/"final.pt"),seed=seed,
        architecture=identity,parameter_count=sum(p.numel() for p in model.parameters()),
        training_receipt_file="final-training.json",training_receipt_sha256=file_digest(folder/"final-training.json"),
        training_parameter_sha256=parameter_digest(model),execution_parameter_sha256=typed_digest(model),
        initial_execution_parameter_sha256=initial_digest,training_source_groups=list(model.training_source_groups),
        frozen_ns=time.time_ns())
    write(folder,"final-model.json",record)
    return record


def load_model(folder, *, expected_arm=None):
    record = json.loads((folder/"final-model.json").read_text())
    if (file_digest(folder/record["file"]) != record["file_sha256"] or
            file_digest(folder/record["training_receipt_file"]) != record["training_receipt_sha256"]):
        raise ValueError("endpoint final weight or training receipt bytes changed")
    arm = record["architecture"]["arm"]
    if expected_arm is not None and arm != expected_arm:
        raise ValueError("endpoint model arm differs from expected selection")
    model = build_endpoint_reader(arm,record["seed"])
    if endpoint_identity(model) != record["architecture"]:
        raise ValueError("endpoint architecture identity changed")
    model.load_state_dict(torch.load(folder/record["file"],map_location="cpu",weights_only=True),strict=True)
    model.eval().requires_grad_(False)
    model.training_source_groups = tuple(record["training_source_groups"])
    if (endpoint_identity(model) != record["architecture"]
            or parameter_digest(model) != record["training_parameter_sha256"]
            or typed_digest(model) != record["execution_parameter_sha256"]):
        raise ValueError("endpoint architecture or named tensor digest changed")
    return model,record


def learning_change(folder, model):
    started = time.perf_counter_ns(),time.process_time_ns()
    record = json.loads((folder/"initialization.json").read_text())
    if file_digest(folder/record["file"]) != record["file_sha256"]:
        raise ValueError("initial weights changed before learning-change measurement")
    initial = torch.load(folder/record["file"],map_location="cpu",weights_only=True)
    final = model.state_dict()
    roles = {r["name"]:r["role"] for r in record["tensors"]}
    if set(initial) != set(final) or set(final) != set(roles):
        raise ValueError("initial/final tensor names changed")
    tensors = []
    for name,value in sorted(final.items()):
        before = initial[name]
        if before.shape != value.shape or before.dtype != value.dtype:
            raise ValueError("initial/final tensor geometry changed")
        delta = value.double()-before.double()
        tensors.append(dict(name=name,role=roles[name],shape=list(value.shape),
            before_sha256=tensor_digest(before),after_sha256=tensor_digest(value),
            l2=delta.norm().item(),maximum_absolute_delta=delta.abs().max().item(),
            before_nonzeros=torch.count_nonzero(before).item(),after_nonzeros=torch.count_nonzero(value).item()))
    groups = {role:dict(tensors=sum(t["role"]==role for t in tensors),
        changed_tensors=sum(t["role"]==role and t["before_sha256"]!=t["after_sha256"] for t in tensors),
        delta_l2=sum(t["l2"]**2 for t in tensors if t["role"]==role)**.5) for role in ("common","extra")}
    output = dict(schema="hepta.endpoint.learning-change.v8",arm=endpoint_identity(model)["arm"],
        initial_weight_sha256=record["file_sha256"],final_weight_sha256=file_digest(folder/"final.pt"),
        initial_training_parameter_sha256=record["training_parameter_sha256"],
        initial_execution_parameter_sha256=record["execution_parameter_sha256"],
        final_training_parameter_sha256=parameter_digest(model),final_execution_parameter_sha256=typed_digest(model),
        tensors=tensors,groups=groups,scope="training_connection_only_not_causal_success",phase_cost=phase_cost(started))
    write(folder,"learning-change.json",output)
    return output


def checked_design(args):
    design = json.loads((args.output/"design.json").read_text())
    previous,parts,natural,augmentation = old_inputs(args)
    if (source_inventory() != design["runtime_source_sha256"]
            or file_digest(Path(__file__).parent/"ENDPOINT_V8_PROTOCOL.md") != design["protocol_sha256"]
            or file_digest(args.previous_v7/"design.json") != design["previous_v7_design_sha256"]
            or file_digest(args.previous_v7/"training-completion.json") != design["previous_v7_training_completion_sha256"]
            or previous["extended_cache_files_sha256"] != design["reused_cache_files_sha256"]):
        raise ValueError("V8 protocol, sources or prior input chain changed")
    for name,wanted in design["prepared_files_sha256"].items():
        if file_digest(args.output/name) != wanted:
            raise ValueError("V8 frozen initialization, data, support transform or plan changed")
    for record in design["historical"]["observations"].values():
        for name,wanted in record["files_sha256"].items():
            if file_digest(Path(record["folder"])/name) != wanted:
                raise ValueError("actual V7 teacher, start or plan bytes changed")
    completed = json.loads((args.output/"preparation-completion.json").read_text())
    expected_panels = {f"seed-{seed}/{arm}/initial-binding-train.json" for seed in SEEDS for arm in ARMS}
    if (completed["design_sha256"] != file_digest(args.output/"design.json")
            or completed["exact_initial_probability_equality"] != {str(s):True for s in SEEDS}
            or completed["actual_initial_candidate_observations"] != 12*128
            or set(completed["initial_panels_sha256"]) != expected_panels):
        raise ValueError("V8 preparation did not bind this exact design")
    for name,wanted in completed["initial_panels_sha256"].items():
        if file_digest(args.output/name) != wanted:
            raise ValueError("actual four-arm initial probability evidence changed")
    case_ids = [c.case_id for c in parts["reader_train"]]
    for seed in SEEDS:
        probabilities = None
        for arm in ARMS:
            folder = args.output/f"seed-{seed}"/arm
            panel = json.loads((folder/"initial-binding-train.json").read_text())
            initial = json.loads((folder/"initialization.json").read_text())
            if (panel["case_ids"] != case_ids or len(panel["probabilities"]) != 128
                    or panel["model_execution_parameter_sha256"] != initial["execution_parameter_sha256"]
                    or probabilities is not None and panel["probabilities"] != probabilities):
                raise ValueError("initial four-arm probabilities, rows or model identity changed")
            probabilities = panel["probabilities"]
    return design,parts,natural,augmentation
