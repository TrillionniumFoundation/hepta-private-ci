"""Bounded continuation of retained current adapters using the qualified SFT engine."""

import argparse
import copy
import gc
import importlib.util
import inspect
import json
import os
from pathlib import Path
import sys
import time

import corrections as contract

LAYOUT_SHA = "a3331738cf460f3e484d4d75c28fc78427b523bd27cbe5a2cbddfe792b282005"


def update_bounds(path, cap):
    """Recover conservative update counts after an interrupted optimizer or write."""
    started, completed = [], []
    try:
        raw = Path(path).read_bytes() if Path(path).exists() else b""
        for line in raw.splitlines(keepends=True):
            contract.require(line.endswith(b"\n"), "partial update journal")
            event = json.loads(line)
            step = event["step"]
            contract.require(type(step) is int, "noninteger update step")
            if event["event"] == "UPDATE_STARTED":
                contract.require(step == len(started) + 1 and len(started) == len(completed)
                                 and step <= cap, "unordered update start")
                started.append(step)
            else:
                contract.require(event["event"] == "UPDATE_COMPLETED" and step == len(completed) + 1
                                 and step in started, "unordered update completion")
                completed.append(step)
        return {"durably_completed_updates": len(completed), "possible_actual_update_upper_bound": len(started),
                "update_completion_uncertain": len(started) != len(completed), "journal_complete": True}
    except (ValueError, KeyError, TypeError, OSError):
        return {"durably_completed_updates": len(completed), "possible_actual_update_upper_bound": cap,
                "update_completion_uncertain": True, "journal_complete": False}


def inputs(prepared):
    prepared = Path(prepared)
    bundle = json.loads((prepared / "CORRECTIONS.json").read_bytes())
    protocol = json.loads((prepared / "PROTOCOL.json").read_bytes())
    contract.verify_bundle(bundle)
    identity = protocol.pop("candidate_digest")
    contract.require(contract.digest(protocol) == identity, "candidate protocol changed")
    protocol["candidate_digest"] = identity
    contract.require(contract.digest(bundle) == protocol["corrections_digest"],
                     "candidate correction records changed")
    for name, expected in protocol["source_files"].items():
        contract.require(contract.sha(Path(__file__).parent / name) == expected,
                         "candidate source changed: " + name)
    return bundle, protocol


def load_engine(bundle, framework_root, engine_directory):
    framework_root, engine_directory = Path(framework_root), Path(engine_directory)
    inventory = bundle["parents"]["native_feedback"]["manifest"]["parent_manifest"]["source_inventory"]
    for relative, expected in inventory.items():
        contract.require(contract.sha(framework_root / relative) == expected,
                         "qualified framework source changed: " + relative)
    path = engine_directory / "layout_sft.py"
    contract.require(contract.sha(path) == LAYOUT_SHA, "qualified layout engine changed")
    contract.require(contract.sha(engine_directory / "checkpoint_softmax.py") ==
                     bundle["training_engine_identity"]["module_sha256"],
                     "qualified checkpointed attention changed")
    sys.path[:0] = [str(framework_root / "scripts"), str(engine_directory)]
    spec = importlib.util.spec_from_file_location("qualified_layout_sft", path)
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    for name, module in list(sys.modules.items()):
        if name.startswith(("cell_experiments", "hepta_cells")) and getattr(module, "__file__", None):
            relative = Path(module.__file__).resolve().relative_to(framework_root.resolve()).as_posix()
            contract.require(relative in inventory and contract.sha(module.__file__) == inventory[relative],
                             "imported framework module is outside the qualified source closure")
    contract.require(Path(engine.checkpoint_softmax.__file__).resolve() ==
                     (engine_directory / "checkpoint_softmax.py").resolve(),
                     "another attention module shadowed the qualified engine")
    return engine


def encode_groups(engine, tokenizer, records, settings, variant="final_only"):
    contract.require(variant in ("final_only", "all_actions"), "unknown trainable learner")
    groups = []
    for record in records:
        contract.require(record["verified_positive_intermediate_actions"] == 0,
                         "new trajectory supervision needs a separate frozen protocol")
        example = {
            "record_id": record["record_id"], "input": record["initial_messages"][0]["content"],
            "initial_messages": copy.deepcopy(record["initial_messages"]),
            "segments": [{"role": "assistant", "actor": "upstream_maintainer",
                          "kind": "final_answer", "train": True, "trainable": True,
                          "content": record["final_answer"]}],
        }
        turns = engine.chat_protocol.encode_native_turns(tokenizer, example, settings["sequence_tokens"])
        contract.require(len(turns) == 1, "only the verified final correction may be labeled")
        turn = turns[0]
        contract.require(all(x == -100 for x in turn["labels"][:turn["prefix_tokens"]]),
                         "own failed action or feedback became a positive label")
        groups.append(engine.partition_target(turn, settings["head_chunk_positions"]))
    return groups


def prepare_runtime(prepared, artifact_root, framework_root, engine_directory):
    bundle, protocol = inputs(prepared)
    engine = load_engine(bundle, framework_root, engine_directory)
    torch, transformers = engine.probe._libraries()
    contract.require(not torch.cuda.is_initialized(), "encoding preparation cannot initialize CUDA")
    parent = bundle["parents"]["native_feedback"]["manifest"]
    engine.probe.verify_model(parent["base_manifest"], artifact_root)
    for binding in bundle["parents"].values():
        manifest = binding["manifest"]
        contract.require(manifest["base_manifest"] == parent["base_manifest"], "parent bases differ")
        adapter = engine.probe._base(artifact_root, manifest["adapter_directory"])
        contract.require(engine.probe._inventory(adapter) == manifest["adapter_files"],
                         "retained parent adapter is absent or changed")
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        str(engine.probe._base(artifact_root, parent["runtime"]["base_directory"])),
        local_files_only=True, trust_remote_code=False)
    groups = {mode: encode_groups(engine, tokenizer, bundle["records"][mode], protocol["training_settings"])
              for mode in contract.MODES}
    for mode in contract.MODES:
        other = encode_groups(engine, tokenizer, bundle["records"][mode], protocol["training_settings"], "all_actions")
        contract.require(groups[mode] == other, "single-target objective equivalence changed")
    from torch.utils import checkpoint
    from transformers import masking_utils
    from transformers.models.qwen2 import modeling_qwen2

    identity = copy.deepcopy(bundle["training_engine_identity"])
    actual = {str(Path(inspect.getfile(m)).resolve()): contract.sha(inspect.getfile(m))
              for m in (checkpoint, masking_utils, modeling_qwen2)}
    contract.require(sorted(actual.values()) == sorted(identity["runtime_files"].values()),
                     "relocated attention runtime bytes differ from qualified originals")
    identity["runtime_files"] = actual
    budgets = {}
    for mode, values in groups.items():
        schedule = [values[i % len(values)] for i in range(protocol["training_settings"]["steps"])]
        budgets[mode] = {
            "optimizer_updates": len(schedule),
            "outer_model_forwards": sum(len(group) for group in schedule),
            "outer_model_backwards": sum(len(group) for group in schedule),
            "supervised_target_positions": sum(sum(x != -100 for x in row["labels"][1:])
                                               for group in schedule for row in group),
            "padded_positions": sum(len(group) for group in schedule) * protocol["training_settings"]["sequence_tokens"],
            "unpadded_positions": sum(len(row["input_ids"]) for group in schedule for row in group),
        }
    contract.require(not torch.cuda.is_initialized(), "CPU preparation initialized CUDA")
    result = {"candidate_digest": protocol["candidate_digest"], "groups": groups,
              "groups_digest": contract.digest(groups), "training_engine_identity": identity,
              "planned_compute_per_parent": budgets,
              "equal_optimizer_updates_do_not_imply_equal_physical_compute": True,
              "all_actions_equals_final_only": True, "new_model_calls": 0,
              "new_optimizer_updates": 0, "new_native_execution": 0}
    contract.write_new(Path(prepared) / "ENCODING.json", result)
    return result


def load_model(manifest, expected_digest, artifact_root, engine):
    contract.require(contract.digest(manifest) == expected_digest, "model identity changed")
    adapter = engine.probe._base(artifact_root, manifest["adapter_directory"])
    contract.require(engine.probe._inventory(adapter) == manifest["adapter_files"],
                     "retained adapter bytes changed or are incomplete")
    import peft

    contract.require(peft.__version__ == manifest["peft_version"], "PEFT runtime changed")
    predictor = engine.probe.Predictor(manifest["base_manifest"], artifact_root)
    try:
        predictor.model = peft.PeftModel.from_pretrained(
            predictor.model, str(adapter), is_trainable=False, local_files_only=True)
        parameters = [(name, value) for name, value in predictor.model.named_parameters() if "lora_" in name]
        contract.require(engine.numeric._parameter_hash(parameters, predictor.torch) == manifest["parameter_after"],
                         "loaded adapter is not the current retained student")
        predictor.model.eval().requires_grad_(False)
        predictor.manifest, predictor.model_digest = copy.deepcopy(manifest), expected_digest
        return predictor
    except BaseException:
        predictor.close()
        raise


def train(prepared, mode, artifact_root, framework_root, engine_directory):
    import fcntl

    with (Path(prepared) / "TRAINING.lock").open("a+b") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _train(prepared, mode, artifact_root, framework_root, engine_directory)


def _train(prepared, mode, artifact_root, framework_root, engine_directory):
    prepared, artifact_root = Path(prepared), Path(artifact_root)
    bundle, protocol = inputs(prepared)
    contract.require(mode in contract.MODES, "unknown current student")
    settings = protocol["training_settings"]
    encoding = json.loads((prepared / "ENCODING.json").read_bytes())
    contract.require(encoding["candidate_digest"] == protocol["candidate_digest"] and
                     contract.digest(encoding["groups"]) == encoding["groups_digest"],
                     "encoding receipt changed")
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", settings["cuda_allocator"])
    contract.require(os.environ["PYTORCH_CUDA_ALLOC_CONF"] == settings["cuda_allocator"],
                     "allocator differs from the frozen training recipe")
    engine = load_engine(bundle, framework_root, engine_directory)
    expected_settings = {**engine.SETTINGS, "steps": 8}
    contract.require(settings == expected_settings, "bounded continuation recipe changed")
    parent = bundle["parents"][mode]["manifest"]
    contract.require(contract.digest(parent) == bundle["parents"][mode]["model_digest"], "parent changed")
    torch, _ = engine.probe._libraries()
    device = torch.device(parent["runtime"]["device"])
    contract.require(device.type == "cuda", "qualified continuation requires its CUDA engine")
    output = artifact_root / "research-current-student-correction-20261121" / protocol["candidate_digest"] / mode
    contract.write_new(prepared / ("CLAIM-" + mode + ".json"),
                       {"candidate_digest": protocol["candidate_digest"], "parent": bundle["parents"][mode]["model_digest"],
                        "reserved_optimizer_updates": 8, "automatic_retry": False, "output": str(output)})
    output.mkdir(parents=True, exist_ok=False)
    started, cpu, predictor, steps = time.perf_counter(), time.process_time(), None, []
    try:
        torch.cuda.set_device(device)
        torch.cuda.set_per_process_memory_fraction(settings["cuda_memory_fraction"], device)
        torch.manual_seed(settings["seed"])
        torch.cuda.manual_seed_all(settings["seed"])
        predictor = load_model(parent, bundle["parents"][mode]["model_digest"], artifact_root, engine)
        contract.write_new(output / "ALLOCATOR.json", engine.allocator_admission(torch, device))
        groups = encode_groups(engine, predictor.tokenizer, bundle["records"][mode], settings)
        contract.require(groups == encoding["groups"][mode], "cold tokenizer encoding changed")
        model = predictor.model
        engine.configure_training_attention(model, output, encoding)
        for name, value in model.named_parameters():
            value.requires_grad_("lora_" in name)
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        model.enable_input_require_grads()
        model.train()
        parameters = [(name, value) for name, value in model.named_parameters() if value.requires_grad]
        contract.require(parameters and all("lora_" in name for name, _ in parameters), "only existing LoRA may train")
        before = engine.numeric._parameter_hash(parameters, torch)
        contract.require(before == parent["parameter_after"], "training did not resume the current student")
        optimizer = torch.optim.AdamW([p for _, p in parameters], lr=settings["learning_rate"],
                                     betas=tuple(settings["optimizer_betas"]), eps=settings["optimizer_eps"],
                                     weight_decay=settings["weight_decay"])
        contract.require(not optimizer.state, "fresh optimizer must have no inherited synthetic state")
        contract.write_new(output / "INITIALIZATION.json", {"parent_model_digest": predictor.model_digest,
                           "parameter_before": before, "resumed_existing_adapter": True,
                           "new_lora_initialization": False, "optimizer_state_entries": 0,
                           "cold_load_wall_seconds": time.perf_counter() - started})
        with (output / "STEPS.jsonl").open("xb") as log, (output / "UPDATES.jsonl").open("xb") as updates:
            for index in range(settings["steps"]):
                group = index % len(groups)
                optimizer.zero_grad(set_to_none=True)
                row = engine.backward_group(torch, model, groups[group], "native_feedback",
                         predictor.tokenizer.pad_token_id, settings["sequence_tokens"], device,
                         trace_path=output / "COMPUTE.jsonl", trace_context={"step": index + 1, "parent": mode})
                norm = torch.nn.utils.clip_grad_norm_([p for _, p in parameters], settings["max_grad_norm"], error_if_nonfinite=True)
                updates.write(contract.canonical({"event": "UPDATE_STARTED", "step": index + 1,
                                                   "candidate_digest": protocol["candidate_digest"]}) + b"\n")
                updates.flush()
                os.fsync(updates.fileno())
                optimizer.step()
                torch.cuda.synchronize(device)
                updates.write(contract.canonical({"event": "UPDATE_COMPLETED", "step": index + 1}) + b"\n")
                updates.flush()
                os.fsync(updates.fileno())
                row.update(step=index + 1, group=group, record_digest=bundle["records"][mode][group]["record_digest"],
                           gradient_norm_before_clip=float(norm))
                log.write(contract.canonical(row) + b"\n")
                log.flush()
                os.fsync(log.fileno())
                steps.append(row)
        after = engine.numeric._parameter_hash(parameters, torch)
        contract.require(after != before, "complete fit did not change the adapter")
        adapter = output / "adapter"
        model.save_pretrained(adapter, safe_serialization=True)
        retained = engine.probe._base(artifact_root, parent["adapter_directory"])
        contract.require(engine.probe._inventory(retained) == parent["adapter_files"], "parent bytes were mutated")
        manifest = {"schema": "hepta.current-student-correction-model.v1", "candidate_digest": protocol["candidate_digest"],
                    "parent_manifest": parent, "parent_model_digest": predictor.model_digest,
                    "base_manifest": parent["base_manifest"], "runtime": parent["runtime"],
                    "backend_versions": parent["backend_versions"], "peft_version": parent["peft_version"],
                    "adapter_directory": adapter.relative_to(artifact_root).as_posix(), "adapter_files": engine.probe._inventory(adapter),
                    "parameter_before": before, "parameter_after": after, "training_settings": settings,
                    "train_records_digest": contract.digest(bundle["records"][mode]), "groups_digest": contract.digest(groups),
                    "scientific_confirmation_qualified": False, "native_adoption": False}
        torch.cuda.synchronize(device)
        result = {"status": "COMPLETE", "model_digest": contract.digest(manifest), "steps": len(steps),
                  **update_bounds(output / "UPDATES.jsonl", settings["steps"]),
                  "wall_seconds": time.perf_counter() - started, "self_cpu_seconds": time.process_time() - cpu,
                  "new_model_calls": 0, "new_native_execution": 0, "energy_joules": None,
                  "cuda_peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
                  "cuda_peak_reserved_bytes": torch.cuda.max_memory_reserved(device),
                  "cost_scopes_not_additive": True, "outer_counts_exclude_inner_recomputation": True,
                  "scientific_confirmation_qualified": False, "native_adoption": False}
        contract.write_new(output / "manifest.json", manifest)
        contract.write_new(output / "TRAINING.json", result)
        return result
    except BaseException as error:
        contract.write_new(output / "FAILED.json", {"error_type": type(error).__name__, "error": str(error),
                           "durably_recorded_full_step_rows": len(steps),
                           **update_bounds(output / "UPDATES.jsonl", settings["steps"]),
                           "reserved_update_cap": settings["steps"], "wall_seconds": time.perf_counter() - started,
                           "automatic_retry": False, "candidate_budget_claim_retained": True})
        raise
    finally:
        if predictor is not None:
            predictor.close()
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("encode", "train"))
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--framework-root", type=Path, required=True)
    parser.add_argument("--engine-directory", type=Path, required=True)
    parser.add_argument("--mode", choices=contract.MODES)
    args = parser.parse_args()
    common = (args.prepared, args.artifact_root, args.framework_root, args.engine_directory)
    result = prepare_runtime(*common) if args.action == "encode" else train(args.prepared, args.mode, *common[1:])
    print(json.dumps({k: v for k, v in result.items() if k != "groups"}, indent=2))
