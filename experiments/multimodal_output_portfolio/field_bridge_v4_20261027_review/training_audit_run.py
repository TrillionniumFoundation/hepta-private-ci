"""Read-only orchestration of the 108-path independent training audit."""
import ast
from collections import Counter
import gzip
import json
from pathlib import Path
import re
import sys
import numpy as np

if __package__:
    from .training_audit_common import (SEEDS, METHODS, SCHEDULES, PANEL, ROLES, OLD_PROTOCOL_SHA, need, object_sha, valid_hash, near)
else:
    from training_audit_common import (SEEDS, METHODS, SCHEDULES, PANEL, ROLES, OLD_PROTOCOL_SHA, need, object_sha, valid_hash, near)

if __package__:
    from .training_audit_trace import (fit_initial, base_policy, trace_audit, counters, hard_cost)
else:
    from training_audit_trace import (fit_initial, base_policy, trace_audit, counters, hard_cost)

if __package__:
    from .training_audit_checkpoints import (checkpoint_audit)
else:
    from training_audit_checkpoints import (checkpoint_audit)

def required_sources(portfolio):
    science = portfolio/"field_bridge_v4_20261027"
    result = set(science.glob("*.py"))
    result.update(science/name for name in ("PROTOCOL.json","SOURCE_ALLOCATION.json","SOURCE_IDENTITIES.json.gz"))
    result.add(portfolio/"field_bridge_v4_20261027_review/training_panel_origin.py")
    result.update(portfolio/"field_bridge_v3_20261027"/name for name in (
        "__init__.py","PROTOCOL.json","training_common.py","assets.py","learning.py","training_features.py",
        "training_bank.py","training_policy.py","source_roles.py"))
    for directory in ("field_bridge_20261027","v6"):
        result.update((portfolio/directory).glob("*.py"))
    result.add(portfolio/"field_bridge_20261027/PROTOCOL.json")
    return sorted(result)

def full_audit(run,old_run,protocol_path,freeze_path,inputs):
    run,old_run,protocol_path,freeze_path = map(lambda p:Path(p).resolve(),(run,old_run,protocol_path,freeze_path))
    need(not (run/"evaluate").exists(),"This is a pre-endpoint audit; endpoint execution already exists")
    protocol = inputs.json(protocol_path)
    p,q = protocol["training"],protocol["qualification"]
    need(protocol["schema"]=="hepta.field-bridge.v4.panel-origin-protocol.1" and protocol["seeds"]==list(SEEDS)
         and q["methods"]==list(METHODS) and q["schedule_ids"]==list(SCHEDULES)
         and p["steps"]==288 and p["macro_steps"]==48 and p["multipliers"]==[0.,.25,1.,2.],"Registered study inventory differs")
    need(protocol["panel_origin"]["translated_indices"]==list(PANEL),"Panel intervention changed")
    freeze = inputs.json(freeze_path)
    need(freeze["study_id"]==protocol["study_id"] and "train" in freeze["allowed_phases"]
         and re.fullmatch(r"[0-9a-f]{40}",freeze["registered_commit"])
         and freeze["protocol_sha256"]==inputs.identities[str(protocol_path)]["sha256"],"Training source freeze identity differs")
    source_map = {}
    for path in required_sources(protocol_path.parent.parent):
        relative = str(path.relative_to(protocol_path.parent.parent))
        inputs.data(path,freeze["source_files"].get(relative))
        digest = inputs.identities[str(path.resolve())]["sha256"]
        need(freeze["source_files"].get(relative)==digest,"Missing mandatory frozen dependency: "+relative)
        source_map[relative] = digest
    for relative,digest in freeze["source_files"].items():
        path = (protocol_path.parent.parent/relative).resolve()
        need(path.is_relative_to(protocol_path.parent.parent),"Unsafe frozen source path")
        inputs.data(path,digest)
    old_protocol = inputs.json(protocol_path.parent.parent/"field_bridge_v3_20261027/PROTOCOL.json",OLD_PROTOCOL_SHA)
    need(old_protocol["training"]==p and protocol["old_training_protocol_sha256"]==OLD_PROTOCOL_SHA,"V3 numerics were edited")
    allocation = inputs.json(protocol_path.parent/"SOURCE_ALLOCATION.json",protocol["source_allocation_sha256"])
    need(allocation["manifest_sha256"]==protocol["source_manifest_sha256"],"Source allocation identity differs")
    scope = {"study_id":protocol["study_id"],"protocol_sha256":inputs.identities[str(protocol_path)]["sha256"],
        "source_allocation_sha256":protocol["source_allocation_sha256"],"source_manifest_sha256":protocol["source_manifest_sha256"],
        "source_files_sha256":object_sha(source_map),"registered_commit":freeze["registered_commit"],
        "freeze_sha256":inputs.identities[str(freeze_path)]["sha256"],"old_training_protocol_sha256":OLD_PROTOCOL_SHA}
    selection = inputs.json(old_run/"DEVELOPMENT_SELECTION.json",freeze["old_artifacts"]["DEVELOPMENT_SELECTION.json"])
    need(selection["passed"] is False and selection["ordinary_action_indices"]==q["ordinary_action_indices"]
         and selection["selected_adaptive"]=="richer","Old failed gate or comparators changed")
    seal = inputs.json(run/"TRAINING_SEAL.json")
    need(seal["schema"]=="hepta.field-bridge.v4.training-seal.1" and seal["study_id"]==protocol["study_id"]
         and seal["paths"]==108 and seal["gradient_microsteps"]==31104 and seal["gradient_examples"]==2985984
         and seal["all_training_completed_before_any_endpoint"] is True and seal["observer_names_during_training"]==["reward"],
         "Missing complete pre-endpoint training seal")
    cost_paths = {f"PHASE_RECEIPTS/train-{seed}.json" for seed in SEEDS}
    need({name for name in seal["files"] if not name.startswith("train/")}==cost_paths,
         "Seal must bind exactly three training phase-cost receipts")
    inputs.files(run/"train",{name.removeprefix("train/"):v for name,v in seal["files"].items() if name.startswith("train/")})
    for name in cost_paths:
        inputs.data(run/name,seal["files"][name])
    asset_source = inputs.data(protocol_path.parent.parent/"field_bridge_v3_20261027/assets.py").decode()
    literals = {node.targets[0].id:ast.literal_eval(node.value) for node in ast.parse(asset_source).body
                if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name)
                and node.targets[0].id in {"PINNED","ORIGINAL_ARCHIVE"}}
    path_results,seed_results,total = [],[],Counter()
    for seed in SEEDS:
        old = {}
        for category,filename in (("bank","BANK.json"),("fit","CONTROLLERS.json"),("reference","REFERENCE.json")):
            for name in (filename,"COMPLETE.json"):
                relative = f"{category}/{seed}/{name}"
                old[category+":"+name] = inputs.json(old_run/relative,freeze["old_artifacts"][relative])
                if name==filename:
                    pin = protocol["frozen_v3_learning_artifacts"][str(seed)][relative]
                    need(inputs.identities[str((old_run/relative).resolve())]==pin,"Protocol-pinned V3 artifact differs")
        bank,fitted,reference = old["bank:BANK.json"],old["fit:CONTROLLERS.json"],old["reference:REFERENCE.json"]
        bank_sha = inputs.identities[str(old_run/f"bank/{seed}/BANK.json")]["sha256"]
        head_sha = inputs.identities[str(old_run/f"fit/{seed}/CONTROLLERS.json")]["sha256"]
        ref_sha = inputs.identities[str(old_run/f"reference/{seed}/REFERENCE.json")]["sha256"]
        need(bank["seed"]==fitted["seed"]==reference["seed"]==seed
             and bank["training_configuration_sha256"]==fitted["training_configuration_sha256"]==reference["training_configuration_sha256"]==object_sha(p)
             and fitted["bank_sha256"]==bank_sha and fitted["reference_sha256"]==bank["reference_sha256"]==ref_sha
             and reference["selected_action_index"]==bank["reference_action_index"],"Frozen head/bank/reference chain differs")
        for category,filename,digest in (("bank","BANK.json",bank_sha),("fit","CONTROLLERS.json",head_sha),("reference","REFERENCE.json",ref_sha)):
            need(old[category+":COMPLETE.json"]["files"][filename]==digest,"Old COMPLETE does not bind its artifact")
        origin,initial = fit_initial(bank)
        zero = next(row for row in reference["candidates"] if row["action_index"]==0)
        zero_info = checkpoint_audit(inputs,old_run/f"reference/{seed}/constant-0.pt",
            old["reference:COMPLETE.json"]["files"]["constant-0.pt"],protocol,seed,zero["checkpoint"]["metadata"],old=True)
        need(zero_info["identity"]==initial=={k:zero["checkpoint"][k] for k in initial}
             and zero_info["momentum_state_parameters"]==0 and zero_info["learning_rate"]==p["learning_rate"],"Old zero-action checkpoint is not the initial parameter/SGD state")
        old_assets = inputs.json(old_run/f"reference/{seed}/ASSET_IDENTITIES.json",
            old["reference:COMPLETE.json"]["files"]["ASSET_IDENTITIES.json"])
        directory = run/"train"/str(seed)
        need(not (directory/"FAILED.json").exists(),"Training phase has a recorded failure")
        start = inputs.json(directory/"START.json")
        done = inputs.json(directory/"COMPLETE.json",seal["model_seed_complete_sha256"][str(seed)])
        assets = inputs.json(directory/"ASSET_IDENTITIES.json")
        seed_scope = {**scope,"bank_sha256":bank_sha,"controller_file_sha256":head_sha,"reference_file_sha256":ref_sha}
        need(start["schema"]=="hepta.field-bridge.v4.phase-start.1" and start["phase"]=="train"
             and start["study_id"]==protocol["study_id"] and start["seed"]==seed and start["scope"]==seed_scope
             and start["source_files"]==source_map and start["requested_roles"]==list(ROLES)
             and start["loaded_observer_names"]==["reward"] and start["training_seal_sha256"] is None
             and start["started_unix_ns"]<seal["sealed_unix_ns"],"Training start/source/observer/timing identity differs")
        asset = assets["identities"]
        need(assets["schema"]=="hepta.field-bridge.v4.asset-identities.1" and assets["study_id"]==protocol["study_id"]
             and asset==old_assets and asset["loaded_observers"]==["reward"]
             and asset["pinned_files"]==literals["PINNED"] and asset["original_archive_sha256"]==literals["ORIGINAL_ARCHIVE"]
             and set(asset["models"])=={str(seed)},"Historical generator/observer asset identity differs")
        need(done["schema"]=="hepta.field-bridge.v4.trained-seed.1" and done["study_id"]==protocol["study_id"]
             and done["seed"]==seed and done["scope"]==seed_scope and done["methods"]==list(METHODS)
             and done["schedule_ids"]==list(SCHEDULES) and done["source_roles"]==list(ROLES)
             and done["observer_names"]==["reward"] and done["endpoint_accessed"] is False,"Seed inventory/scope differs")
        inputs.files(directory,done["files"],exclude=("COMPLETE.json",))
        expected_paths = {f"{m}/schedule-{s}" for m in METHODS for s in SCHEDULES}
        need(set(done["paths"])==expected_paths,"Not all 36 paths are retained")
        guard = done["baseline_guard"]
        nguard = allocation["roles"]["qualification_guard"]["pairs"]
        need(len(guard["source_ids"])==len(guard["values"])==len(guard["output_sha256"])==nguard
             and len({tuple(x) for x in guard["source_ids"]})==nguard
             and all(valid_hash(x) for x in guard["output_sha256"]),"Original guard baseline is incomplete")
        near(guard["mean"],np.mean(guard["values"]),"Original guard mean")
        summed = Counter()
        for method in METHODS:
            mode = None if method.startswith("ordinary_") else "field" if method=="raw_field" else method.removeprefix("origin_")
            head = None if mode is None else fitted["controllers"][mode]
            policy = base_policy(protocol,seed,method,seed_scope,head,origin)
            for sid in SCHEDULES:
                relative = f"{method}/schedule-{sid}"
                path = directory/relative
                record = inputs.json(path/"COMPLETE.json",done["paths"][relative]["complete_sha256"])
                need(set(record["files"])=={"checkpoint.pt","decisions-and-outcomes.jsonl.gz"},"Training path contains unexpected media/endpoint work")
                inputs.files(path,record["files"],exclude=("COMPLETE.json",))
                trace = inputs.data(path/"decisions-and-outcomes.jsonl.gz",record["files"]["decisions-and-outcomes.jsonl.gz"])
                rows = [json.loads(row) for row in gzip.decompress(trace).splitlines()]
                checkpoint = checkpoint_audit(inputs,path/"checkpoint.pt",record["files"]["checkpoint.pt"],protocol,seed,record["checkpoint"]["metadata"])
                need(checkpoint["file_sha256"]==record["checkpoint"]["file_sha256"]
                     and checkpoint["identity"]==record["final_identity"]=={k:record["checkpoint"][k] for k in initial}
                     and checkpoint["frozen_base_sha256"]==zero_info["frozen_base_sha256"]
                     and checkpoint["parameter_shapes"]==zero_info["parameter_shapes"],"Checkpoint tensor/base/architecture binding differs")
                expected_metadata = {"study_id":protocol["study_id"],"seed":seed,"method":method,"schedule_id":sid,
                    "policy_sha256":record["policy_sha256"],"base_policy_sha256":record["base_policy_sha256"],
                    "source_roles":list(ROLES),"endpoint_accessed":False}
                need(record["checkpoint"]["metadata"]==expected_metadata
                     and record["policy_sha256"]==done["paths"][relative]["policy_sha256"],"Checkpoint policy/role provenance differs")
                result = trace_audit(rows,record,protocol,allocation,seed,sid,method,head,policy,initial,guard,
                                     checkpoint["parameter_count"],len(trace),checkpoint["bytes"])
                near(checkpoint["learning_rate"],result["expected_final_learning_rate"],"Final SGD learning rate",atol=0.)
                if method=="ordinary_0":
                    need(checkpoint["identity"]==zero_info["identity"] and checkpoint["momentum_state_parameters"]==0,
                         "Complete zero path changed actual saved parameters/momentum")
                result["checkpoint"] = checkpoint
                path_results.append(result)
                summed.update(result["resources"])
        original_cost = hard_cost("original_guard",nguard,int(np.ceil(nguard/p["panel_batch_size"])),p["fixed_actions"][str(seed)])
        summed.update(original_cost)
        need(counters(done["resources"],"seed costs")==dict(summed),"Seed ledger does not equal all paths plus original guard")
        phase = inputs.json(run/f"PHASE_RECEIPTS/train-{seed}.json",seal["files"][f"PHASE_RECEIPTS/train-{seed}.json"])
        need(phase["schema"]=="hepta.field-bridge.v4.phase-cost-receipt.1" and phase["study_id"]==protocol["study_id"]
             and phase["phase"]=="train" and phase["seed"]==seed and phase["scope"]==seed_scope
             and phase["complete_sha256"]==seal["model_seed_complete_sha256"][str(seed)],"Unbound training phase cost receipt")
        for key in ("preflight_verification_wall_ns","preflight_verification_cpu_ns","postflight_verification_wall_ns",
                    "postflight_verification_cpu_ns","phase_wall_ns","phase_cpu_ns"):
            need(type(phase[key]) is int and phase[key]>=0,"Invalid complete training phase timing")
        need(phase["preflight_verification_wall_ns"]==start["preflight_verification_wall_ns"]
             and phase["preflight_verification_cpu_ns"]==start["preflight_verification_cpu_ns"],"Preflight timing changed after training")
        seed_paths = [path for path in path_results if path["seed"]==seed]
        for clock in ("wall","cpu"):
            contained = sum(path[f"path_{clock}_ns"] for path in seed_paths)
            contained += phase[f"preflight_verification_{clock}_ns"]+phase[f"postflight_verification_{clock}_ns"]
            need(phase[f"phase_{clock}_ns"]>=contained,"Training phase time is shorter than its disjoint recorded components")
        total.update(summed)
        seed_results.append({"seed":seed,"paths":36,"resources":dict(summed),"original_guard_resources":original_cost,
                             "parameter_count":zero_info["parameter_count"],"initial_identity":initial,
                             "seed_wall_ns":done["wall_ns"],"scope":seed_scope,"phase_cost":phase})
        print(f"independent training audit seed={seed}: 36 paths verified",file=sys.stderr,flush=True)
    need(len(path_results)==108 and total["scheduled_gradient_microsteps"]==31104
         and total["gradient_backward_examples"]==2985984 and total["directional_gradient_measurements"]==648
         and total["accepted_blocks"]+total["rejected_blocks"]==648,"All-path work totals differ")
    inputs.unchanged()
    return {"study_id":protocol["study_id"],"paths":path_results,"seeds":seed_results,"resources":dict(total),
        "training_seal_sha256":inputs.identities[str(run/"TRAINING_SEAL.json")]["sha256"],
        "declared_training_audit_observer_work":0,"declared_training_endpoint_work":0,
        "old_zero_checkpoint_reads":3,"new_checkpoint_reads":108,"independent_head_predictions":360,
        "control_context_scope":"14 retained float64 calibration values (112B) plus frozen fit context and full raw30 audit metadata; not a 112B total-memory claim.",
        "time_scope":"Path CPU/wall includes model/optimizer initialization, feature/block work, journals and checkpoint I/O. Three separately sealed phase-cost receipts include source verification and asset/corpus/context setup. Their explicit exclusions are retained; interpreter startup is not claimed to be timed.",
        "audit_limits":[
            "SHA and causal ordering checks establish consistency of retained records, not independent OS/process isolation or exclusion of unlogged I/O.",
            "No model forward, observer evaluation, gradient computation, optimization step, source tensor load, or training replay is performed by this auditor.",
            "Every final checkpoint parameter and SGD tensor is independently hashed. Intermediate zero/rejected restorations are checked against committed before/candidate/after identities, not intermediate full tensor snapshots.",
            "Raw loss/derivative observations are checked for recorded arithmetic consistency where possible; they are not recomputed from data and models.",
            "Source-disjointness, endpoint outputs, bootstrap intervals and substantive qualification gates are handled by separate independent review."]}
