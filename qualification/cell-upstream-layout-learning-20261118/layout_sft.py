"""Resume one actual parent on identical verified repair targets and two evidence layouts."""

import copy
import gc
import importlib.util
import os
from pathlib import Path
import time

from cell_experiments import causal_probe_v3 as probe
from cell_experiments import causal_train_v3 as numeric
from cell_experiments import chat_protocol, data, matched_info_sft_v4 as matched
from cell_experiments.coding_sft import file_hash, write_new

SCHEMA = "hepta.upstream-layout-sft-model.v1"
MODES = ("document_evidence", "native_feedback")
PARENT = "430f4051d47672d121a5d790aca0e489804b0d8419c101e3c1171b3d17157786"
PARENT_PARAMETERS = "e5da16c3256c27f06f42ecac69880ce8802a0eb3a87c05830d11c09477aa817f"
SETTINGS = {
    "steps": 32,
    "sequence_tokens": 3584,
    "head_chunk_positions": 256,
    "learning_rate": 0.0001,
    "rank": 4,
    "lora_alpha": 8,
    "lora_dropout": 0.0,
    "target_modules": ["q_proj", "v_proj"],
    "seed": 1729,
    "optimizer_betas": [0.9, 0.999],
    "optimizer_eps": 1e-8,
    "weight_decay": 0.01,
    "max_grad_norm": 1.0,
    "cuda_memory_fraction": 0.70,
    "optimizer_state": "fresh identical empty AdamW",
}
require = matched.require


def information(record):
    return data.digest(
        {
            "task": record["task"]["input"],
            "answer": record["observed_answer"],
            "feedback": record["observed_feedback"],
            "target": record["final_answer"],
        }
    )


def evidence_messages(record, mode):
    require(mode in MODES, "unknown layout")
    prompt, answer, feedback = (
        record["task"]["input"],
        record["observed_answer"],
        record["observed_feedback"],
    )
    if mode == "document_evidence":
        return [
            {
                "role": "user",
                "content": prompt
                + "\n\nPrevious assistant message:\n"
                + answer
                + "\n\nActual tool observation:\n"
                + feedback,
            }
        ]
    return [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": answer},
        {"role": "tool", "content": feedback},
    ]


def partition_target(turn, maximum=256):
    positions = [i for i, value in enumerate(turn["labels"]) if value != -100]
    require(positions and positions[0] > 0 and maximum > 0, "nonempty causal target")
    require(len(turn["labels"]) == len(turn["input_ids"]), "aligned target")
    parts = []
    for start in range(0, len(positions), maximum):
        labels = [-100] * len(turn["labels"])
        for i in positions[start : start + maximum]:
            labels[i] = turn["labels"][i]
        parts.append({**turn, "labels": labels, "final_target": True})
    require(
        [i for part in parts for i, value in enumerate(part["labels"]) if value != -100]
        == positions,
        "target positions must be partitioned exactly once",
    )
    return parts


def encode_groups(tokenizer, records, limit, mode):
    groups = []
    for record in records:
        require(
            record["information_digest"] == information(record), "raw evidence changed"
        )
        messages = evidence_messages(record, mode)
        example = {
            "record_id": record["record_id"],
            "input": messages[0]["content"],
            "initial_messages": messages,
            "segments": [
                {
                    "role": "assistant",
                    "actor": "upstream_maintainer",
                    "kind": "final_answer",
                    "train": True,
                    "trainable": True,
                    "content": record["final_answer"],
                }
            ],
        }
        turns = chat_protocol.encode_native_turns(tokenizer, example, limit)
        require(len(turns) == 1, "one maintainer target required")
        turn = turns[0]
        require(
            all(value == -100 for value in turn["labels"][: turn["prefix_tokens"]]),
            "failed observations cannot be positive targets",
        )
        groups.append(partition_target(turn, SETTINGS["head_chunk_positions"]))
    return groups


def backward_group(
    torch,
    model,
    turns,
    mode,
    pad_token_id,
    limit,
    device,
    trace_path=None,
    trace_context=None,
):
    """The inherited mean-target objective with durable partial-compute events."""
    require(mode in MODES, "unknown evidence layout")
    counts = [sum(value != -100 for value in row["labels"][1:]) for row in turns]
    denominator = sum(counts)
    require(denominator > 0, "nonempty objective required")
    observed_loss, positions, inputs = 0.0, 0, 0

    def emit(event, chunk, count):
        if trace_path is not None:
            record = {
                **(trace_context or {}),
                "event": event,
                "chunk": chunk,
                "target_positions": count,
                "padded_positions": limit,
                "at_ns": time.time_ns(),
                "monotonic_ns": time.monotonic_ns(),
                "optimizer_update_in_this_chunk": False,
            }
            if torch.cuda.is_available() and str(device).startswith("cuda"):
                record["cuda_allocated_bytes"] = torch.cuda.memory_allocated(device)
                record["cuda_reserved_bytes"] = torch.cuda.memory_reserved(device)
            with Path(trace_path).open("ab") as stream:
                stream.write(data.canonical(record) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())

    for chunk, (row, count) in enumerate(zip(turns, counts)):
        padding = limit - len(row["input_ids"])
        require(padding >= 0, "complete transcript exceeds frozen context")
        ids = torch.tensor([row["input_ids"] + [pad_token_id] * padding], device=device)
        labels = torch.tensor([row["labels"] + [-100] * padding], device=device)
        mask = torch.tensor(
            [[1] * len(row["input_ids"]) + [0] * padding], device=device
        )
        emit("forward_started", chunk, count)
        loss, actual_count = numeric.selected_token_loss(model, ids, mask, labels)
        require(
            actual_count == count and bool(torch.isfinite(loss)), "invalid matched loss"
        )
        emit("forward_completed", chunk, actual_count)
        weighted = loss * (count / denominator)
        emit("backward_started", chunk, count)
        weighted.backward()
        observed_loss += float(weighted.detach())
        emit("backward_completed", chunk, actual_count)
        positions += actual_count
        inputs += len(row["input_ids"])
    return {
        "loss": observed_loss,
        "model_forwards": len(turns),
        "model_backwards": len(turns),
        "head_positions": positions,
        "supervised_positions": denominator,
        "input_tokens": inputs,
        "padded_positions": limit * len(turns),
    }


def verified_references(records):
    source = Path(
        "/home/qian-qi/work/hepta-upstream-current-policy-20261118-2e9b/execution-code/native_sandbox.py"
    )
    require(
        file_hash(source)
        == "49cced4d3eb61ee86b1f55a11ca097be7618a0fc9b59e515f1b1d7676bec671c",
        "original native verifier changed",
    )
    spec = importlib.util.spec_from_file_location("layout_native_reference", source)
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    receipts = []
    for record in records:
        candidate, admission = native.admit(
            record["project_id"], record["final_answer"]
        )
        _, folder = native.source(record["project_id"])
        require(
            candidate == (folder / "after" / record["source_path"]).read_bytes(),
            "target must equal exact original maintainer revision",
        )
        proof_path = (
            source.parent.parent
            / "preparation-1/sandbox-preflight"
            / str(record["source_index"])
            / "after/RESULT.json"
        )
        require(
            file_hash(proof_path) == record["reference_receipt_sha256"],
            "original reference receipt changed",
        )
        proof = data._parse(proof_path.read_bytes())
        require(
            proof["success"]
            and proof["patched_source_sha256"] == native.sha(candidate)
            and proof["original_test_sha256"] == record["original_tests_sha256"],
            "target lacks the original real native pass",
        )
        receipts.append(
            {
                "project_id": record["project_id"],
                "success": True,
                "admission": admission,
                "original_native_receipt_sha256": file_hash(proof_path),
                "new_native_test_executions": 0,
            }
        )
    return receipts


def verify_manifest(manifest, artifact_root, old_code_root, candidate_root):
    require(manifest.get("schema") == SCHEMA, "current-policy model required")
    parent = manifest["parent_manifest"]
    require(
        matched.verify_manifest(parent, artifact_root, old_code_root) == PARENT,
        "frozen parent identity differs",
    )
    require(
        parent["parameter_after"] == PARENT_PARAMETERS,
        "actual parent parameter identity differs",
    )
    require(
        manifest["parameter_before"] == PARENT_PARAMETERS,
        "candidate did not resume the exact parent",
    )
    require(
        manifest["training_settings"] == SETTINGS and manifest["objective"] in MODES,
        "candidate treatment changed",
    )
    require(
        manifest["base_manifest"] == parent["base_manifest"]
        and manifest["runtime"] == parent["runtime"],
        "inference policy changed",
    )
    for name, expected in manifest["candidate_files"].items():
        require(
            file_hash(Path(candidate_root) / name) == expected,
            "candidate source or A data changed: " + name,
        )
    require(
        probe._inventory(probe._base(artifact_root, manifest["adapter_directory"]))
        == manifest["adapter_files"],
        "candidate adapter bytes changed",
    )
    import peft

    require(peft.__version__ == manifest["peft_version"], "adapter backend differs")
    return data.digest(manifest)


class Predictor(probe.Predictor):
    def __init__(self, manifest, artifact_root, old_code_root, candidate_root):
        identity = verify_manifest(
            manifest, artifact_root, old_code_root, candidate_root
        )
        super().__init__(manifest["base_manifest"], artifact_root)
        import peft

        try:
            self.model = peft.PeftModel.from_pretrained(
                self.model,
                str(probe._base(artifact_root, manifest["adapter_directory"])),
                is_trainable=False,
                local_files_only=True,
            )
            parameters = [
                (name, value)
                for name, value in self.model.named_parameters()
                if "lora_" in name
            ]
            require(
                numeric._parameter_hash(parameters, self.torch)
                == manifest["parameter_after"],
                "saved candidate tensors changed on cold load",
            )
            self.model.eval()
            self.model.requires_grad_(False)
            self.manifest, self.model_digest = copy.deepcopy(manifest), identity
        except BaseException:
            self.close()
            raise


def train(
    records, parent, artifact_root, old_code_root, candidate_root, freeze, mode, output
):
    output, artifact_root = Path(output), Path(artifact_root)
    output.relative_to(artifact_root)
    require(mode in MODES, "unknown current-policy objective")
    require(
        len(records) == 8 and data.digest(records) == freeze["train_records_digest"],
        "frozen eight A first-prefix records differ",
    )
    require(
        all(
            record["split"] == "train" and record["authorization"]["training_allowed"]
            for record in records
        ),
        "authorized A only",
    )
    require(
        matched.verify_manifest(parent, artifact_root, old_code_root) == PARENT,
        "parent source or artifact changed",
    )
    require(parent["parameter_after"] == PARENT_PARAMETERS, "parent tensors differ")
    for name, expected in freeze["candidate_files"].items():
        require(
            file_hash(Path(candidate_root) / name) == expected,
            "new candidate changed: " + name,
        )
    output.mkdir(parents=True, exist_ok=False)
    write_new(
        output / "STARTED.json",
        {
            "objective": mode,
            "freeze_digest": data.digest(freeze),
            "started_at_ns": time.time_ns(),
        },
    )
    started, cpu, predictor, torch = (
        time.perf_counter(),
        time.process_time(),
        None,
        None,
    )
    try:
        receipts = verified_references(records)
        write_new(output / "REFERENCE_RECHECKS.json", receipts)
        require(
            all(receipt["success"] for receipt in receipts),
            "A correction failed strict recheck",
        )
        torch, _ = probe._libraries()
        import peft

        device = torch.device(parent["runtime"]["device"])
        torch.cuda.empty_cache()
        probe.check_device(torch, parent["runtime"])
        torch.cuda.set_per_process_memory_fraction(
            SETTINGS["cuda_memory_fraction"], device
        )
        torch.cuda.reset_peak_memory_stats(device)
        torch.manual_seed(SETTINGS["seed"])
        torch.cuda.manual_seed_all(SETTINGS["seed"])
        predictor = matched.Predictor(parent, artifact_root, old_code_root)
        write_new(
            output / "MODEL_LOADED.json",
            {
                "actual_parent_model_digest": predictor.model_digest,
                "parameter_digest_verified_by_loader": PARENT_PARAMETERS,
                "at_ns": time.time_ns(),
                "wall_seconds_since_stage_entry": time.perf_counter() - started,
                "device": predictor.device_report,
                "optimizer_updates": 0,
                "scope": "stage entry through actual cold load, including imports and byte verification",
            },
        )
        groups = encode_groups(
            predictor.tokenizer, records, SETTINGS["sequence_tokens"], mode
        )
        require(
            data.digest(groups) == freeze["encoded_groups_digest"][mode],
            "actual encoding differs",
        )
        write_new(output / "ENCODED_GROUPS.json", groups)
        model = predictor.model
        # The parent loader validates FP32 adapter bytes before enabling gradients.
        # No adapter is reinitialized and no parent optimizer state is invented.
        for name, value in model.named_parameters():
            value.requires_grad_("lora_" in name)
        model.gradient_checkpointing_enable(
            gradient_checkpointing_kwargs={"use_reentrant": False}
        )
        model.enable_input_require_grads()
        model.train()
        parameters = [
            (name, value)
            for name, value in model.named_parameters()
            if value.requires_grad
        ]
        require(
            parameters and all("lora_" in name for name, _ in parameters),
            "only LoRA may train",
        )
        before = numeric._parameter_hash(parameters, torch)
        require(before == PARENT_PARAMETERS, "resumed parameters differ before update")
        write_new(
            output / "INITIALIZATION.json",
            {
                "parent_model_digest": PARENT,
                "parameter_before": before,
                "optimizer_state_entries": 0,
                "resumed_existing_adapter": True,
                "new_lora_initialization": False,
            },
        )
        optimizer = torch.optim.AdamW(
            [value for _, value in parameters],
            lr=SETTINGS["learning_rate"],
            betas=tuple(SETTINGS["optimizer_betas"]),
            eps=SETTINGS["optimizer_eps"],
            weight_decay=SETTINGS["weight_decay"],
        )
        require(not optimizer.state, "fresh optimizer must start empty")
        steps = []
        for index in range(SETTINGS["steps"]):
            group = index % len(groups)
            optimizer.zero_grad(set_to_none=True)
            measured = backward_group(
                torch,
                model,
                groups[group],
                mode,
                predictor.tokenizer.pad_token_id,
                SETTINGS["sequence_tokens"],
                device,
                trace_path=output / "COMPUTE.jsonl",
                trace_context={
                    "phase": "training",
                    "mode": mode,
                    "step": index + 1,
                    "group": group,
                },
            )
            norm = torch.nn.utils.clip_grad_norm_(
                [value for _, value in parameters],
                SETTINGS["max_grad_norm"],
                error_if_nonfinite=True,
            )
            optimizer.step()
            row = {
                "step": index + 1,
                "task_id": records[group]["task_id"],
                "group": group,
                "input_group_digest": data.digest(groups[group]),
                "information_digest": records[group]["information_digest"],
                "target_ids_digest": data.digest(
                    [x for part in groups[group] for x in part["labels"] if x != -100]
                ),
                "gradient_norm_before_clip": float(norm),
                **measured,
            }
            with (output / "STEPS.jsonl").open("ab") as stream:
                stream.write(data.canonical(row) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            steps.append(row)
        after = numeric._parameter_hash(parameters, torch)
        require(after != before, "complete fit must actually update parameters")
        adapter = output / "adapter"
        adapter.mkdir(exist_ok=False)
        model.save_pretrained(adapter, safe_serialization=True)
        manifest = {
            "schema": SCHEMA,
            "parent_manifest": copy.deepcopy(parent),
            "parent_model_digest": PARENT,
            "base_manifest": copy.deepcopy(parent["base_manifest"]),
            "runtime": copy.deepcopy(parent["runtime"]),
            "backend_versions": copy.deepcopy(parent["backend_versions"]),
            "adapter_directory": adapter.relative_to(artifact_root).as_posix(),
            "adapter_files": probe._inventory(adapter),
            "peft_version": peft.__version__,
            "candidate_files": copy.deepcopy(freeze["candidate_files"]),
            "objective": mode,
            "training_settings": SETTINGS,
            "freeze_digest": data.digest(freeze),
            "train_records_digest": data.digest(records),
            "encoded_groups_digest": data.digest(groups),
            "parameter_before": before,
            "parameter_after": after,
            "scientific_confirmation_qualified": False,
            "native_adoption": False,
        }
        identity = verify_manifest(
            manifest, artifact_root, old_code_root, candidate_root
        )
        torch.cuda.synchronize(device)
        result = {
            "status": "COMPLETE",
            "model_digest": identity,
            "objective": mode,
            "steps": len(steps),
            "parameter_before": before,
            "parameter_after": after,
            "encoded_groups_digest": data.digest(groups),
            "train_records_digest": data.digest(records),
            "cost": {
                "wall_seconds": time.perf_counter() - started,
                "self_cpu_seconds": time.process_time() - cpu,
                **{
                    key: sum(row[key] for row in steps)
                    for key in (
                        "model_forwards",
                        "model_backwards",
                        "head_positions",
                        "supervised_positions",
                        "input_tokens",
                        "padded_positions",
                    )
                },
                "cuda_peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
                "cuda_peak_reserved_bytes": torch.cuda.max_memory_reserved(device),
                "energy_joules": None,
                "full_system_cost_known": False,
                "nested_scopes_are_not_additive": True,
            },
            "scientific_confirmation_qualified": False,
            "native_adoption": False,
        }
        write_new(output / "manifest.json", manifest)
        write_new(output / "TRAINING.json", result)
        return result
    except BaseException as error:
        write_new(
            output / "FAILED.json",
            {
                "error_type": type(error).__name__,
                "error": str(error),
                "wall_seconds": time.perf_counter() - started,
                "self_cpu_seconds": time.process_time() - cpu,
                "automatic_retry": False,
                "completed_steps": "STEPS.jsonl",
            },
        )
        raise
    finally:
        if predictor is not None:
            predictor.close()
        gc.collect()
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()


def audit(output, artifact_root, old_code_root, candidate_root, freeze):
    output = Path(output)
    arms = {}
    keys = (
        "step",
        "task_id",
        "group",
        "information_digest",
        "target_ids_digest",
        "model_forwards",
        "model_backwards",
        "head_positions",
        "supervised_positions",
        "padded_positions",
    )
    for mode in MODES:
        folder = output / "training" / mode
        manifest = data._parse((folder / "manifest.json").read_bytes())
        fit = data._parse((folder / "TRAINING.json").read_bytes())
        steps = [
            data._parse(line)
            for line in (folder / "STEPS.jsonl").read_bytes().splitlines()
        ]
        identity = verify_manifest(
            manifest, artifact_root, old_code_root, candidate_root
        )
        require(
            fit["status"] == "COMPLETE"
            and fit["model_digest"] == identity
            and fit["steps"] == len(steps) == SETTINGS["steps"],
            "complete actual fits required",
        )
        require(
            manifest["freeze_digest"] == data.digest(freeze)
            and manifest["encoded_groups_digest"]
            == freeze["encoded_groups_digest"][mode],
            "freeze or encoded evidence changed",
        )
        arms[mode] = {
            "model_digest": identity,
            "parameter_before": manifest["parameter_before"],
            "parameter_after": manifest["parameter_after"],
            "manifest_sha256": file_hash(folder / "manifest.json"),
            "training_sha256": file_hash(folder / "TRAINING.json"),
            "cost": fit["cost"],
            "step_shapes": [{key: row[key] for key in keys} for row in steps],
        }
    require(
        arms[MODES[0]]["step_shapes"] == arms[MODES[1]]["step_shapes"],
        "actual target/compute schedules differ",
    )
    require(
        arms[MODES[0]]["parameter_before"]
        == arms[MODES[1]]["parameter_before"]
        == PARENT_PARAMETERS,
        "initial parameter states differ",
    )
    result = {
        "status": "MATCHED_AND_WEIGHTS_FROZEN",
        "freeze_digest": data.digest(freeze),
        "created_at_ns": time.time_ns(),
        "arms": arms,
        "NoUpdate_parent": PARENT,
        "designated_candidate": "native_feedback",
        "control": "document_evidence",
        "B3_material_read_before_weights_frozen": False,
        "authenticated_external_custody": False,
        "physical_wall_energy_equality_claim": False,
        "unpadded_input_length_difference_reported": True,
        "scientific_gain_claim": False,
        "native_adoption": False,
    }
    write_new(output / "WEIGHTS_FROZEN.json", result)
    return result


def calibrate(records, parent, artifact_root, old_code_root, freeze, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started, cpu, predictor, torch = (
        time.perf_counter(),
        time.process_time(),
        None,
        None,
    )
    write_new(
        output / "STARTED.json",
        {"at_ns": time.time_ns(), "freeze_digest": data.digest(freeze)},
    )
    try:
        torch, _ = probe._libraries()
        device = torch.device(parent["runtime"]["device"])
        torch.cuda.empty_cache()
        torch.cuda.set_per_process_memory_fraction(
            SETTINGS["cuda_memory_fraction"], device
        )
        torch.cuda.reset_peak_memory_stats(device)
        torch.manual_seed(SETTINGS["seed"])
        predictor = matched.Predictor(parent, artifact_root, old_code_root)
        write_new(
            output / "MODEL_LOADED.json",
            {
                "actual_parent_model_digest": predictor.model_digest,
                "parameter_digest_verified_by_loader": PARENT_PARAMETERS,
                "at_ns": time.time_ns(),
                "wall_seconds_since_stage_entry": time.perf_counter() - started,
                "device": predictor.device_report,
                "optimizer_updates": 0,
                "scope": "stage entry through actual cold load, including imports and byte verification",
            },
        )
        model = predictor.model
        for name, value in model.named_parameters():
            value.requires_grad_("lora_" in name)
        model.gradient_checkpointing_enable(
            gradient_checkpointing_kwargs={"use_reentrant": False}
        )
        model.enable_input_require_grads()
        model.train()
        require(
            float(getattr(model.config, "attention_dropout", 0.0)) == 0.0,
            "dropout-free split loss required",
        )
        parameters = [
            (name, value)
            for name, value in model.named_parameters()
            if value.requires_grad
        ]
        require(
            numeric._parameter_hash(parameters, torch) == PARENT_PARAMETERS,
            "calibration parent differs",
        )
        rows = []
        for mode in MODES:
            for _, value in parameters:
                value.grad = None
            groups = encode_groups(
                predictor.tokenizer, records, SETTINGS["sequence_tokens"], mode
            )
            require(
                data.digest(groups) == freeze["encoded_groups_digest"][mode],
                "calibration encoding differs",
            )
            tick = time.perf_counter()
            measured = backward_group(
                torch,
                model,
                groups[freeze["calibration_index"]],
                mode,
                predictor.tokenizer.pad_token_id,
                SETTINGS["sequence_tokens"],
                device,
                trace_path=output / "COMPUTE.jsonl",
                trace_context={
                    "phase": "calibration",
                    "mode": mode,
                    "optimizer_updates": 0,
                },
            )
            require(
                all(
                    value.grad is not None and bool(torch.isfinite(value.grad).all())
                    for _, value in parameters
                ),
                "finite real gradients required",
            )
            torch.cuda.synchronize(device)
            rows.append(
                {"mode": mode, "wall_seconds": time.perf_counter() - tick, **measured}
            )
        after = numeric._parameter_hash(parameters, torch)
        require(after == PARENT_PARAMETERS, "calibration must not update any weight")
        result = {
            "status": "PASS",
            "rows": rows,
            "optimizer_updates": 0,
            "model_generation_calls": 0,
            "parameter_before": PARENT_PARAMETERS,
            "parameter_after": after,
            "wall_seconds": time.perf_counter() - started,
            "self_cpu_seconds": time.process_time() - cpu,
            "cuda_peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
            "cuda_peak_reserved_bytes": torch.cuda.max_memory_reserved(device),
            "full_system_cost_known": False,
        }
        write_new(output / "RESULT.json", result)
        return result
    except BaseException as error:
        write_new(
            output / "FAILED.json",
            {
                "error_type": type(error).__name__,
                "error": str(error),
                "wall_seconds": time.perf_counter() - started,
                "optimizer_updates": 0,
                "automatic_retry": False,
            },
        )
        raise
    finally:
        if predictor is not None:
            predictor.close()
        gc.collect()
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
