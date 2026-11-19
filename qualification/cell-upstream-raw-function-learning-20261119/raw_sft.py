"""Fit two matched layouts using the unchanged qualified numerical implementation."""

import copy
import gc
import os
from pathlib import Path
import time

import raw_context as ctx

legacy = ctx.legacy()
probe, numeric, matched, data = (
    legacy.probe,
    legacy.numeric,
    legacy.matched,
    legacy.data,
)
file_hash, write_new = legacy.file_hash, legacy.write_new
require = ctx.require
MODES = legacy.MODES
PARENT, PARENT_PARAMETERS = legacy.PARENT, legacy.PARENT_PARAMETERS
SETTINGS = copy.deepcopy(legacy.SETTINGS)
SCHEMA = "hepta.upstream-raw-function-sft-model.v1"
information = legacy.information
encode_groups = legacy.encode_groups
backward_group = legacy.backward_group
configure_training_attention = legacy.configure_training_attention
allocator_admission = legacy.allocator_admission


def verified_references(records):
    codec, _, _, _ = ctx.originals()
    qualification = ctx.read(
        ctx.COLLECTION / "cpu-attempt-1/cpu-controls-1/RESULT.json"
    )
    proofs = {
        row["project_id"]: row["after"]["original_verification"]
        for row in qualification["native_pairs"]
    }
    native = codec.native_module()
    receipts = []
    for record in records:
        action, conversion, binding = codec.convert(
            record["project_id"], record["final_answer"]
        )
        candidate, admission = native.admit(record["project_id"], action)
        proof = proofs[record["project_id"]]
        require(
            conversion["raw_answer_sha256"] == record["reference_payload_sha256"]
            and native.sha(candidate) == record["reference_exact_after_sha256"]
            and proof["success"]
            and proof["actual_native_child"]
            and proof["patched_source_sha256"] == native.sha(candidate)
            and proof["original_test_sha256"] == record["original_tests_sha256"]
            and binding["original_source_sha256"] == record["original_source_sha256"],
            "raw-function target lacks exact original maintainer bytes and actual native reference proof",
        )
        receipts.append(
            {
                "project_id": record["project_id"],
                "success": True,
                "admission": admission,
                "conversion": conversion,
                "original_reference_receipt_sha256": ctx.digest(proof),
                "new_native_test_executions": 0,
            }
        )
    return receipts


def verify_manifest(manifest, artifact_root, old_code_root, candidate_root):
    require(manifest.get("schema") == SCHEMA, "raw-function candidate schema required")
    parent = manifest["parent_manifest"]
    require(
        matched.verify_manifest(parent, artifact_root, old_code_root) == PARENT,
        "frozen parent identity differs",
    )
    require(
        parent["parameter_after"] == manifest["parameter_before"] == PARENT_PARAMETERS,
        "actual common parent parameters differ",
    )
    require(
        manifest["training_settings"] == SETTINGS and manifest["objective"] in MODES,
        "fixed common treatment differs",
    )
    require(
        manifest["base_manifest"] == parent["base_manifest"]
        and manifest["runtime"] == parent["runtime"],
        "inference runtime differs",
    )
    for name, expected in manifest["candidate_files"].items():
        require(
            file_hash(Path(candidate_root) / name) == expected,
            "new frozen training source/data changed: " + name,
        )
    freeze = ctx.admitted()
    require(
        data.digest(freeze) == manifest["freeze_digest"],
        "model belongs to another frozen protocol",
    )
    require(
        manifest["previous_engine_qualification_sha256"]
        == freeze["previous_engine_qualification_sha256"],
        "prior numerical engine qualification differs",
    )
    require(
        probe._inventory(probe._base(artifact_root, manifest["adapter_directory"]))
        == manifest["adapter_files"],
        "actual adapter bytes changed",
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
        len(records) == 4 and data.digest(records) == freeze["train_records_digest"],
        "frozen four actual P first-prefix records differ",
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
    training_admission_sha = ctx.previous_engine_qualification()
    output.mkdir(parents=True, exist_ok=False)
    write_new(
        output / "STARTED.json",
        {
            "objective": mode,
            "freeze_digest": data.digest(freeze),
            "started_at_ns": str(time.time_ns()),
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
        write_new(output / "ALLOCATOR.json", allocator_admission(torch, device))
        write_new(
            output / "MODEL_LOADED.json",
            {
                "actual_parent_model_digest": predictor.model_digest,
                "parameter_digest_verified_by_loader": PARENT_PARAMETERS,
                "at_ns": str(time.time_ns()),
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
        configure_training_attention(model, output, freeze)
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
            "previous_engine_qualification_sha256": training_admission_sha,
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
                "inner_checkpoint_counts": {
                    key: sum(
                        row["inner_checkpoint_counts"].get(key, 0) for row in steps
                    )
                    for key in sorted(
                        {key for row in steps for key in row["inner_checkpoint_counts"]}
                    )
                },
                "model_F_B_counts_are_outer_calls_not_total_recomputed_work": True,
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
        "inner_checkpoint_counts",
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
        "created_at_ns": str(time.time_ns()),
        "arms": arms,
        "NoUpdate_parent": PARENT,
        "designated_candidate": "native_feedback",
        "control": "document_evidence",
        "future_confirmation_material_read_before_weights_frozen": False,
        "authenticated_external_custody": False,
        "physical_wall_energy_equality_claim": False,
        "unpadded_input_length_difference_reported": True,
        "scientific_gain_claim": False,
        "native_adoption": False,
    }
    write_new(output / "WEIGHTS_FROZEN.json", result)
    return result
