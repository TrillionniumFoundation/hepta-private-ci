"""V8 fixed-budget endpoint comparison: prepare and twelve complete training fits."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

import torch

from binding_campaign_utils import binding_panel
from endpoint_campaign_utils import (ARMS,ORDER,SEEDS,checked_design,endpoint_identity,
    historical_records,learning_change,load_bank,load_bridge,load_bridge_warmup,load_model,
    old_inputs,phase_cost,save_initialization,save_model,source_inventory,support_deleted_panel,
    support_transform,teacher_reference,typed_digest,write)
from group_encoder import file_digest
from reader_features import tensor_digest
from retention_campaign import natural_panel
from retention_data import joint_gate
from retention_v7_training import continue_retention,make_retention_plan


def prepare(args):
    started = time.perf_counter_ns(),time.process_time_ns()
    args.output.mkdir(parents=True,exist_ok=False)
    previous,parts,natural,augmentation = old_inputs(args)
    historical = historical_records(args,previous)
    write(args.output,"all-cases.json",{name:[asdict(c) for c in cases] for name,cases in dict(
        reader_train=parts["reader_train"],internal_tune=parts["internal_tune"],augmentation=augmentation,
        natural_train=natural["train"],natural_internal=natural["tune"]).items()})
    write(args.output,"support-transform.json",support_transform(parts["reader_train"]))
    models = {}
    for seed in SEEDS:
        core,record = load_bridge(args.previous_v6/f"seed-{seed}"/"bridge","warmup",expected_arm="bridge")
        teacher_reference(args,seed,parts["reader_train"],record)
        start = json.loads((args.previous_v7/f"seed-{seed}"/"start-natural-train.json").read_text())
        if (start["model_execution_parameter_sha256"] != record["execution_parameter_sha256"]
                or start["case_ids"] != [c.case_id for c in natural["train"]]):
            raise ValueError("reused complete natural start differs from actual V6 warmup")
        plan = make_retention_plan(natural["train"],parts["reader_train"],augmentation,seed=seed)
        if plan != json.loads((args.previous_v7/f"seed-{seed}"/"training-plan.json").read_text()):
            raise ValueError("V8 streams differ from the actual V7 diverse schedule")
        write(args.output,f"seed-{seed}/training-plan.json",plan)
        for arm in ARMS:
            model = load_bridge_warmup(core,arm,seed=seed)
            if tuple(model.training_source_groups) != tuple(core.training_source_groups):
                raise ValueError("warmup training provenance was not preserved")
            save_initialization(args.output/f"seed-{seed}"/arm,model,core,seed)
            models[(seed,arm)] = model
    frozen_names = ("all-cases.json","support-transform.json","seed-*/training-plan.json",
                    "seed-*/*/initialization.json","seed-*/*/initialization.pt","seed-*/*/initialization.bin")
    prepared = {str(path.relative_to(args.output)):file_digest(path)
                for pattern in frozen_names for path in args.output.glob(pattern)}
    design = dict(schema="hepta.endpoint.campaign.v8",created_ns=time.time_ns(),
        runtime_source_sha256=source_inventory(),protocol_sha256=file_digest(Path(__file__).parent/"ENDPOINT_V8_PROTOCOL.md"),
        previous_v7_design_sha256=file_digest(args.previous_v7/"design.json"),
        previous_v7_training_completion_sha256=file_digest(args.previous_v7/"training-completion.json"),
        reused_cache_files_sha256=previous["extended_cache_files_sha256"],historical=historical,
        prepared_files_sha256=prepared,natural_case_ids=previous["natural_case_ids"],
        natural_constants=previous["natural_constants"],gates=previous["gates"],primary="endpoint",arms=list(ARMS),
        order={str(s):list(v) for s,v in ORDER.items()},training=dict(recipe="diverse",logical_updates=500,
            streams=["natural","transfer","retention"],batch_size=16,depth=3,learning_rate=.001,
            pair_weight=.5,anchor_weight=0.,diagnostic_interval=100,wall_time_ns=1_800_000_000_000,
            optimizer_updates=1500,candidate_exposures=24000,stop_rule="fixed_final_no_selection"),
        initial_panel=dict(role="reader_train",candidate_observations=12*128,steps=3,
            four_arms_actually_executed=True,probability_equality="exact_same_seed"),
        teacher=dict(source="actual_V7_cache",role="unused_compatibility_reference",new_forward_calls=0,
            active_distillation=False,cost_is_historical=True),
        natural_start=dict(source="actual_V7_full_natural_start",new_forward_calls=0,cost_is_historical=True),
        encoder_new_forward_authorized=False,diagnostics=["verified_support_deleted3","reset3","full1"],
        full3_reused_from_final_panel=True,diagnostics_select_models=False,
        feedback_authorized=False,fresh_authorized=False,automatic_downstream_opening=False,
        official_validation_read=False,hosted_ci_consulted=False,production_authorized=False)
    write(args.output,"design.json",design)
    # The protocol, sources, inputs, weights and plans are frozen before these model observations.
    bank = load_bank(args)
    before = bank.forward_batches,bank.encoded_sequences,bank.cpu_ns,bank.wall_ns
    panel_files,equality = {},{}
    for seed in SEEDS:
        reference = None
        for arm in ARMS:
            folder = args.output/f"seed-{seed}"/arm
            binding_panel(folder,"initial-binding-train",models[(seed,arm)],parts["reader_train"],bank)
            panel = json.loads((folder/"initial-binding-train.json").read_text())
            if reference is not None and panel["probabilities"] != reference:
                raise ValueError("zero-output endpoint variants changed initial predictions")
            reference = panel["probabilities"]
            relative = str((folder/"initial-binding-train.json").relative_to(args.output))
            panel_files[relative] = file_digest(folder/"initial-binding-train.json")
        equality[str(seed)] = True
    if before != (bank.forward_batches,bank.encoded_sequences,bank.cpu_ns,bank.wall_ns):
        raise ValueError("V8 preparation unexpectedly encoded new input")
    if source_inventory() != design["runtime_source_sha256"]:
        raise ValueError("V8 runtime changed during preparation")
    write(args.output,"preparation-completion.json",dict(completed_ns=time.time_ns(),
        design_sha256=file_digest(args.output/"design.json"),initial_panels_sha256=panel_files,
        exact_initial_probability_equality=equality,actual_initial_candidate_observations=12*128,
        encoder_new_forward_batches=0,encoder_new_sequences=0,reused_encoder_report=bank.report(),
        reused_cache_generation_cost_not_additive=True,phase_cost=phase_cost(started)))


def train(args):
    started = time.perf_counter_ns(),time.process_time_ns()
    design,parts,natural,augmentation = checked_design(args)
    with (args.output/"training-start.json").open("x") as stream:
        json.dump(dict(started_ns=time.time_ns(),retries_authorized=False),stream)
    bank = load_bank(args)
    before = bank.forward_batches,bank.encoded_sequences,bank.cpu_ns,bank.wall_ns
    old_data,new_data,natural_data = bank.dataset(parts["reader_train"]),bank.dataset(augmentation),bank.dataset(natural["train"])
    transform = json.loads((args.output/"support-transform.json").read_text())
    gates = {}
    for seed in SEEDS:
        seed_folder = args.output/f"seed-{seed}"
        historical = args.previous_v6/f"seed-{seed}"/"bridge"
        _,core_record = load_bridge(historical,"warmup",expected_arm="bridge")
        teacher,_ = teacher_reference(args,seed,parts["reader_train"],core_record)
        start = json.loads((args.previous_v7/f"seed-{seed}"/"start-natural-train.json").read_text())["metrics"]
        baseline = json.loads((historical/"warmup-binding-train.json").read_text())["metrics"]
        plan = json.loads((seed_folder/"training-plan.json").read_text())
        gates[str(seed)] = {}
        for arm in ORDER[seed]:
            folder = seed_folder/arm
            initial = json.loads((folder/"initialization.json").read_text())
            from endpoint_reader import build_endpoint_reader
            model = build_endpoint_reader(arm,seed)
            model.load_state_dict(torch.load(folder/"initialization.pt",map_location="cpu",weights_only=True),strict=True)
            model.eval().requires_grad_(False)
            model.training_source_groups = tuple(initial["training_source_groups"])
            if typed_digest(model) != initial["execution_parameter_sha256"]:
                raise ValueError("actual training initialization changed")
            trained,receipt = continue_retention(model,natural_data,old_data,new_data,parts["reader_train"],augmentation,
                arm="diverse",plan=plan,teacher_logits=teacher,teacher_logits_sha256=tensor_digest(teacher),
                natural_cases=natural["train"],depth=3,diagnostic_interval=100,wall_time_ns=1_800_000_000_000,
                failure_receipt_fn=lambda r:write(folder,"final-failed.json",dict(r,model_arm=arm,recipe="diverse")))
            if receipt["status"] != "completed" or receipt["completed_steps"] != 500:
                raise RuntimeError("incomplete fixed V8 training budget")
            receipt.update(model_arm=arm,recipe="diverse",campaign_schema="hepta.endpoint.campaign.v8",
                teacher_reference_reused=True,active_teacher_distillation=False,new_teacher_forward_calls=0,
                teacher_preparation_scope="historical_V7_cache_reuse_no_V8_teacher_forward")
            save_model(folder,trained,receipt,seed=seed,initial_digest=initial["execution_parameter_sha256"])
            learning_change(folder,trained)
            qualification_started = time.perf_counter_ns(),time.process_time_ns()
            old = binding_panel(folder,"final-binding-train",trained,parts["reader_train"],bank)
            relation = binding_panel(folder,"final-binding-internal",trained,parts["internal_tune"],bank)
            binding_panel(folder,"final-augmentation-train",trained,augmentation,bank)
            learned = natural_panel(folder,"final-natural-train",trained,natural["train"],bank,scope="complete_natural_training_partition")
            natural_panel(folder,"final-natural-internal",trained,natural["tune"],bank,scope="previously_exposed_descriptive_not_fresh")
            gate = joint_gate(old,baseline,relation,learned,start,design["natural_constants"])
            write(folder,"final-gate.json",gate)
            write(folder,"qualification-cost.json",phase_cost(qualification_started))
            gates[str(seed)][arm] = gate
            diagnostic_started = time.perf_counter_ns(),time.process_time_ns()
            support_deleted_panel(folder,trained,parts["reader_train"],bank,transform)
            binding_panel(folder,"diagnostics/reset3",trained,parts["reader_train"],bank,reset=True)
            binding_panel(folder,"diagnostics/full1",trained,parts["reader_train"],bank,depth=1)
            write(folder,"diagnostics/receipt.json",dict(full3_reused_file="../final-binding-train.json",
                full3_reused_sha256=file_digest(folder/"final-binding-train.json"),new_candidate_observations=3*128,
                diagnostics_used_for_gate_or_selection=False,phase_cost=phase_cost(diagnostic_started)))
            print(json.dumps(dict(seed=seed,arm=arm,phase="training",gate=gate)),flush=True)
    if before != (bank.forward_batches,bank.encoded_sequences,bank.cpu_ns,bank.wall_ns):
        raise ValueError("V8 training unexpectedly performed new Encoder forward work")
    if source_inventory() != design["runtime_source_sha256"]:
        raise ValueError("V8 runtime changed during training")
    manifests = {str(p.relative_to(args.output)):file_digest(p) for p in args.output.glob("seed-*/*/final-model.json")}
    if len(manifests) != 12:
        raise ValueError("all twelve final weight selections must exist")
    for seed in SEEDS:
        for arm in ARMS:
            load_model(args.output/f"seed-{seed}"/arm,expected_arm=arm)
    write(args.output,"all-models-frozen.json",dict(frozen_ns=time.time_ns(),manifests=manifests,
        runtime_source_sha256=source_inventory(),feedback_authorized=False,fresh_authorized=False))
    write(args.output,"training-completion.json",dict(completed_ns=time.time_ns(),gates=gates,
        primary_all_passed=all(g["endpoint"]["passed"] for g in gates.values()),runtime_source_sha256=source_inventory(),
        phase_cost=phase_cost(started),new_encoder_forward_batches=0,new_teacher_forward_calls=0,
        actual_optimizer_updates=12*1500,actual_training_exposures=12*24000,
        feedback_authorized=False,fresh_authorized=False,automatic_downstream_opening=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase",choices=("prepare","train"))
    for name in ("source","snapshot","prepared","previous-main","previous-native","previous-v5","previous-v6","previous-v7","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    {"prepare":prepare,"train":train}[args.phase](args)


if __name__ == "__main__":
    main()
