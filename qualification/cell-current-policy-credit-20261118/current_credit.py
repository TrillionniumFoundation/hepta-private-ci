"""Resume the actual A student with matched work and different verified credit."""

import copy
import gc
import os
from pathlib import Path
import time

from cell_experiments import causal_probe_v3 as probe
from cell_experiments import causal_train_v3 as numeric
from cell_experiments import chat_protocol, data, matched_info_sft_v4 as matched
from cell_experiments import repo_execution
from cell_experiments.coding_sft import file_hash, write_new

SCHEMA = "hepta.current-policy-credit-model.v1"
MODES = ("all_observed", "verified_credit")
PARENT = "430f4051d47672d121a5d790aca0e489804b0d8419c101e3c1171b3d17157786"
PARENT_PARAMETERS = "e5da16c3256c27f06f42ecac69880ce8802a0eb3a87c05830d11c09477aa817f"
CORPUS = "780f0e8158f59985ad7c27827fb210dd5b273ccff53c2120f26ac036a06259ff"
SETTINGS = {
    "steps": 64, "sequence_tokens": 2048, "learning_rate": 0.0001,
    "rank": 4, "lora_alpha": 8, "lora_dropout": 0.0,
    "target_modules": ["q_proj", "v_proj"], "seed": 1729,
    "optimizer_betas": [0.9, 0.999], "optimizer_eps": 1e-8,
    "weight_decay": 0.01, "max_grad_norm": 1.0,
    "cuda_memory_fraction": 0.70, "optimizer_state": "fresh identical empty AdamW",
}
require = matched.require


def encode_groups(tokenizer, records, limit):
    groups = matched.encode_groups(tokenizer, records, limit)
    for record, turns in zip(records, groups):
        targets = [event for event in record["trajectory"] if event.get("trainable")]
        require(len(targets) == len(turns) == 3, "three complete targets required")
        require([event["actor"] for event in targets] == ["student", "student", "curator"],
                "actual student history and explicit correction required")
        require(targets[-1]["content"] == record["final_answer"], "correction differs")
        require(targets[-1]["target_verified"] is True, "verified correction required")
        for event, turn in zip(targets, turns):
            require(type(event["target_verified"]) is bool, "explicit verification label required")
            turn["target_verified"] = event["target_verified"]
            turn["target_actor"] = event["actor"]
    return groups


def backward_group(torch, model, turns, mode, pad_token_id, limit, device):
    require(mode in MODES, "unknown current-policy objective")
    # Reuse the independently tested numeric engine. The semantic credit flag is
    # explicitly translated; input IDs, all labels and executed graphs are equal.
    mapped = [{**turn, "final_target": turn["target_verified"]} for turn in turns]
    return matched.backward_group(torch, model, mapped,
                                  "all_actions" if mode == "all_observed" else "final_only",
                                  pad_token_id, limit, device)


def verify_manifest(manifest, artifact_root, old_code_root, candidate_root):
    require(manifest.get("schema") == SCHEMA, "current-policy model required")
    parent = manifest["parent_manifest"]
    require(matched.verify_manifest(parent, artifact_root, old_code_root) == PARENT,
            "frozen parent identity differs")
    require(parent["parameter_after"] == PARENT_PARAMETERS,
            "actual parent parameter identity differs")
    require(manifest["parameter_before"] == PARENT_PARAMETERS,
            "candidate did not resume the exact parent")
    require(manifest["training_settings"] == SETTINGS and manifest["objective"] in MODES,
            "candidate treatment changed")
    require(manifest["base_manifest"] == parent["base_manifest"] and
            manifest["runtime"] == parent["runtime"], "inference policy changed")
    for name, expected in manifest["candidate_files"].items():
        require(file_hash(Path(candidate_root) / name) == expected,
                "candidate source or A data changed: " + name)
    require(probe._inventory(probe._base(artifact_root, manifest["adapter_directory"]))
            == manifest["adapter_files"], "candidate adapter bytes changed")
    import peft
    require(peft.__version__ == manifest["peft_version"], "adapter backend differs")
    return data.digest(manifest)


class Predictor(probe.Predictor):
    def __init__(self, manifest, artifact_root, old_code_root, candidate_root):
        identity = verify_manifest(manifest, artifact_root, old_code_root, candidate_root)
        super().__init__(manifest["base_manifest"], artifact_root)
        import peft
        try:
            self.model = peft.PeftModel.from_pretrained(
                self.model, str(probe._base(artifact_root, manifest["adapter_directory"])),
                is_trainable=False, local_files_only=True)
            parameters = [(name, value) for name, value in self.model.named_parameters()
                          if "lora_" in name]
            require(numeric._parameter_hash(parameters, self.torch) == manifest["parameter_after"],
                    "saved candidate tensors changed on cold load")
            self.model.eval()
            self.model.requires_grad_(False)
            self.manifest, self.model_digest = copy.deepcopy(manifest), identity
        except BaseException:
            self.close()
            raise


def train(records, parent, artifact_root, old_code_root, candidate_root, freeze, mode, output):
    output, artifact_root = Path(output), Path(artifact_root)
    output.relative_to(artifact_root)
    require(mode in MODES, "unknown current-policy objective")
    require(len(records) == 6 and data.digest(records) == freeze["train_records_digest"] == CORPUS,
            "frozen six-A current-policy corpus differs")
    require(all(record["split"] == "train" and record["authorization"]["training_allowed"]
                for record in records), "authorized A only")
    require(matched.verify_manifest(parent, artifact_root, old_code_root) == PARENT,
            "parent source or artifact changed")
    require(parent["parameter_after"] == PARENT_PARAMETERS, "parent tensors differ")
    for name, expected in freeze["candidate_files"].items():
        require(file_hash(Path(candidate_root) / name) == expected, "new candidate changed: " + name)
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "STARTED.json", {"objective": mode, "freeze_digest": data.digest(freeze),
                                       "started_at_ns": time.time_ns()})
    started, cpu, predictor, torch = time.perf_counter(), time.process_time(), None, None
    try:
        repo_execution.load_catalog("open")
        receipts = [data.verify_answer(record, record["final_answer"]) for record in records]
        write_new(output / "REFERENCE_RECHECKS.json", receipts)
        require(all(receipt["success"] for receipt in receipts), "A correction failed strict recheck")
        torch, _ = probe._libraries()
        import peft
        device = torch.device(parent["runtime"]["device"])
        torch.cuda.empty_cache()
        probe.check_device(torch, parent["runtime"])
        torch.cuda.set_per_process_memory_fraction(SETTINGS["cuda_memory_fraction"], device)
        torch.cuda.reset_peak_memory_stats(device)
        torch.manual_seed(SETTINGS["seed"])
        torch.cuda.manual_seed_all(SETTINGS["seed"])
        predictor = matched.Predictor(parent, artifact_root, old_code_root)
        groups = encode_groups(predictor.tokenizer, records, SETTINGS["sequence_tokens"])
        write_new(output / "ENCODED_GROUPS.json", groups)
        model = predictor.model
        # The parent loader validates FP32 adapter bytes before enabling gradients.
        # No adapter is reinitialized and no parent optimizer state is invented.
        for name, value in model.named_parameters():
            value.requires_grad_("lora_" in name)
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        model.enable_input_require_grads()
        model.train()
        parameters = [(name, value) for name, value in model.named_parameters() if value.requires_grad]
        require(parameters and all("lora_" in name for name, _ in parameters), "only LoRA may train")
        before = numeric._parameter_hash(parameters, torch)
        require(before == PARENT_PARAMETERS, "resumed parameters differ before update")
        write_new(output / "INITIALIZATION.json", {"parent_model_digest": PARENT,
                  "parameter_before": before, "optimizer_state_entries": 0,
                  "resumed_existing_adapter": True, "new_lora_initialization": False})
        optimizer = torch.optim.AdamW([value for _, value in parameters],
            lr=SETTINGS["learning_rate"], betas=tuple(SETTINGS["optimizer_betas"]),
            eps=SETTINGS["optimizer_eps"], weight_decay=SETTINGS["weight_decay"])
        require(not optimizer.state, "fresh optimizer must start empty")
        steps = []
        for index in range(SETTINGS["steps"]):
            group = index % len(groups)
            optimizer.zero_grad(set_to_none=True)
            measured = backward_group(torch, model, groups[group], mode,
                predictor.tokenizer.pad_token_id, SETTINGS["sequence_tokens"], device)
            norm = torch.nn.utils.clip_grad_norm_([value for _, value in parameters],
                SETTINGS["max_grad_norm"], error_if_nonfinite=True)
            optimizer.step()
            row = {"step": index + 1, "task_id": records[group]["task_id"], "group": group,
                   "input_group_digest": data.digest(groups[group]),
                   "gradient_norm_before_clip": float(norm), **measured}
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
        manifest = {"schema": SCHEMA, "parent_manifest": copy.deepcopy(parent),
            "parent_model_digest": PARENT, "base_manifest": copy.deepcopy(parent["base_manifest"]),
            "runtime": copy.deepcopy(parent["runtime"]),
            "backend_versions": copy.deepcopy(parent["backend_versions"]),
            "adapter_directory": adapter.relative_to(artifact_root).as_posix(),
            "adapter_files": probe._inventory(adapter), "peft_version": peft.__version__,
            "candidate_files": copy.deepcopy(freeze["candidate_files"]),
            "objective": mode, "training_settings": SETTINGS,
            "freeze_digest": data.digest(freeze), "train_records_digest": data.digest(records),
            "encoded_groups_digest": data.digest(groups), "parameter_before": before,
            "parameter_after": after, "scientific_confirmation_qualified": False,
            "native_adoption": False}
        identity = verify_manifest(manifest, artifact_root, old_code_root, candidate_root)
        torch.cuda.synchronize(device)
        result = {"status": "COMPLETE", "model_digest": identity, "objective": mode,
            "steps": len(steps), "parameter_before": before, "parameter_after": after,
            "encoded_groups_digest": data.digest(groups), "train_records_digest": data.digest(records),
            "cost": {"wall_seconds": time.perf_counter() - started,
                "self_cpu_seconds": time.process_time() - cpu,
                **{key: sum(row[key] for row in steps) for key in (
                    "model_forwards", "model_backwards", "head_positions", "supervised_positions",
                    "input_tokens", "padded_positions")},
                "cuda_peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
                "cuda_peak_reserved_bytes": torch.cuda.max_memory_reserved(device),
                "energy_joules": None, "full_system_cost_known": False,
                "nested_scopes_are_not_additive": True},
            "scientific_confirmation_qualified": False, "native_adoption": False}
        write_new(output / "manifest.json", manifest)
        write_new(output / "TRAINING.json", result)
        return result
    except BaseException as error:
        write_new(output / "FAILED.json", {"error_type": type(error).__name__, "error": str(error),
            "wall_seconds": time.perf_counter() - started, "self_cpu_seconds": time.process_time() - cpu,
            "automatic_retry": False, "completed_steps": "STEPS.jsonl"})
        raise
    finally:
        if predictor is not None:
            predictor.close()
        gc.collect()
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()


def audit(output, artifact_root, old_code_root, candidate_root, freeze):
    arms = {}
    for mode in MODES:
        folder = output / "training" / mode
        manifest = data._parse((folder / "manifest.json").read_bytes())
        fit = data._parse((folder / "TRAINING.json").read_bytes())
        groups = data._parse((folder / "ENCODED_GROUPS.json").read_bytes())
        steps = [data._parse(line) for line in (folder / "STEPS.jsonl").read_bytes().splitlines()]
        identity = verify_manifest(manifest, artifact_root, old_code_root, candidate_root)
        require(fit["status"] == "COMPLETE" and fit["model_digest"] == identity and
                fit["steps"] == len(steps) == SETTINGS["steps"], "complete original fit required")
        require(manifest["freeze_digest"] == data.digest(freeze) and
                data.digest(groups) == fit["encoded_groups_digest"] == manifest["encoded_groups_digest"],
                "candidate or encoded groups changed")
        arms[mode] = {"model_digest": identity, "parameter_before": manifest["parameter_before"],
            "parameter_after": manifest["parameter_after"], "encoded_groups_digest": data.digest(groups),
            "manifest_sha256": file_hash(folder / "manifest.json"),
            "training_sha256": file_hash(folder / "TRAINING.json"),
            "step_shapes": [{key: row[key] for key in ("step", "task_id", "group",
                "input_group_digest", "model_forwards", "model_backwards", "head_positions",
                "input_tokens", "padded_positions")} for row in steps]}
    require(all(arms[MODES[0]][key] == arms[MODES[1]][key] for key in (
        "parameter_before", "encoded_groups_digest", "step_shapes")), "matched work or initial state differs")
    result = {"status": "MATCHED_AND_WEIGHTS_FROZEN", "freeze_digest": data.digest(freeze),
              "created_at_ns": time.time_ns(), "arms": arms, "NoUpdate_parent": PARENT,
              "B2_material_read_before_weights_frozen": False,
              "physical_wall_energy_equality_claim": False, "scientific_gain_claim": False}
    write_new(output / "WEIGHTS_FROZEN.json", result)
    return result
