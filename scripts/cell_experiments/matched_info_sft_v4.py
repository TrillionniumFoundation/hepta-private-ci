"""Research LoRA comparison with identical transcript inputs and compute shapes.

Both objectives execute every native trajectory turn. Final-only supervision
weights nonfinal losses by zero after the same forward and backward operations.
The only treatment is which observed assistant tokens contribute to the loss.
"""

import copy
import gc
import os
from pathlib import Path
import time

from . import (
    causal_probe_v3 as probe,
    causal_train_v3 as numeric,
    chat_protocol,
    data,
    repo_execution,
)
from .coding_sft import file_hash, write_new

SCHEMA = "hepta.matched-information-sft-model.v1"
SETTINGS = {
    "steps": 64,
    "sequence_tokens": 1536,
    "learning_rate": 0.0003,
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
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encode_groups(tokenizer, records, limit):
    """Tokenize full trajectories once; objective selection never edits inputs."""
    groups = []
    for record, example in zip(
        records, chat_protocol.native_examples(records, "trajectory")
    ):
        messages, _ = chat_protocol.training_messages(example)
        supervised = [message for message in messages if message["train"]]
        require(
            supervised and supervised[-1]["content"] == record["final_answer"],
            "last supervised action must be the verified final answer",
        )
        turns = chat_protocol.encode_native_turns(tokenizer, example, limit)
        require(
            len(turns) == len(supervised), "all assistant targets must survive encoding"
        )
        for index, turn in enumerate(turns):
            turn["final_target"] = index == len(turns) - 1
        groups.append(turns)
    require(len(groups) == len(records) and groups, "complete training groups required")
    return groups


def backward_group(torch, model, turns, mode, pad_token_id, limit, device):
    """Use equal model/head positions for both objectives and one group update."""
    require(mode in ("final_only", "all_actions"), "unknown matched objective")
    counts = [sum(value != -100 for value in row["labels"][1:]) for row in turns]
    selected = [
        count if mode == "all_actions" or row["final_target"] else 0
        for count, row in zip(counts, turns)
    ]
    denominator = sum(selected)
    require(denominator > 0, "nonempty objective required")
    observed_loss, positions, inputs = 0.0, 0, 0
    for row, count, selected_count in zip(turns, counts, selected):
        padding = limit - len(row["input_ids"])
        require(padding >= 0, "matched transcript exceeds frozen context")
        ids = torch.tensor([row["input_ids"] + [pad_token_id] * padding], device=device)
        labels = torch.tensor([row["labels"] + [-100] * padding], device=device)
        mask = torch.tensor(
            [[1] * len(row["input_ids"]) + [0] * padding], device=device
        )
        loss, actual_count = numeric.selected_token_loss(model, ids, mask, labels)
        require(
            actual_count == count and bool(torch.isfinite(loss)), "invalid matched loss"
        )
        weighted = loss * (selected_count / denominator)
        # The zero-weight branch still traverses the same backward graph.
        weighted.backward()
        observed_loss += float(weighted.detach())
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


def source_inventory(root):
    root = Path(root)
    return {
        str(path.relative_to(root)): file_hash(path)
        for directory in ("scripts/cell_experiments", "scripts/hepta_cells")
        for path in sorted((root / directory).rglob("*.py"))
    }


def verify_manifest(manifest, artifact_root, code_root):
    require(manifest.get("schema") == SCHEMA, "matched model schema required")
    require(
        manifest["source_inventory"] == source_inventory(code_root),
        "matched model source changed",
    )
    base = manifest["base_manifest"]
    require(
        probe.verify_model(base, artifact_root) == manifest["base_model_digest"],
        "matched base differs",
    )
    require(
        manifest["runtime"] == base["runtime"]
        and manifest["backend_versions"] == base["backend_versions"],
        "matched inference policy differs",
    )
    require(
        manifest["training_settings"] == SETTINGS
        and manifest["objective"] in ("final_only", "all_actions"),
        "matched fit settings differ",
    )
    adapter = probe._base(artifact_root, manifest["adapter_directory"])
    require(
        probe._inventory(adapter) == manifest["adapter_files"],
        "matched adapter bytes differ",
    )
    import peft

    require(
        peft.__version__ == manifest["peft_version"], "matched adapter backend differs"
    )
    return data.digest(manifest)


class Predictor(probe.Predictor):
    """Cold-load and hash the exact new adapter before any evaluation call."""

    def __init__(self, manifest, artifact_root, code_root):
        identity = verify_manifest(manifest, artifact_root, code_root)
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
                "cold adapter does not preserve saved tensors",
            )
            self.model.eval()
            self.model.requires_grad_(False)
            self.manifest, self.model_digest = copy.deepcopy(manifest), identity
        except BaseException:
            self.close()
            raise


def train(records, parent, artifact_root, code_root, freeze, mode, output):
    """Train one arm on A only; observations, failures and costs remain durable."""
    output, artifact_root, code_root = map(Path, (output, artifact_root, code_root))
    output.relative_to(artifact_root)
    require(mode in ("final_only", "all_actions"), "unknown matched objective")
    require(
        data.digest(records) == freeze["train_records_digest"] and len(records) == 6,
        "frozen six-A input differs",
    )
    require(
        all(
            row["split"] == "train" and row["authorization"]["training_allowed"]
            for row in records
        ),
        "training is restricted to authorized A",
    )
    require(
        data.digest(parent) == freeze["base_model_digest"]
        and source_inventory(code_root) == freeze["source_inventory"],
        "source or base changed after freeze",
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
        repo_execution.load_catalog("open")
        references = [data.verify_answer(row, row["final_answer"]) for row in records]
        write_new(output / "REFERENCE_RECHECKS.json", references)
        require(
            all(row["success"] for row in references),
            "real A reference verification failed",
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
        predictor = probe.Predictor(parent, artifact_root)
        groups = encode_groups(
            predictor.tokenizer, records, SETTINGS["sequence_tokens"]
        )
        write_new(output / "ENCODED_GROUPS.json", groups)
        model = peft.get_peft_model(
            predictor.model,
            peft.LoraConfig(
                r=SETTINGS["rank"],
                lora_alpha=SETTINGS["lora_alpha"],
                lora_dropout=0.0,
                target_modules=SETTINGS["target_modules"],
                task_type="CAUSAL_LM",
                bias="none",
            ),
        )
        predictor.model = model
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
        optimizer = torch.optim.AdamW(
            [value for _, value in parameters],
            lr=SETTINGS["learning_rate"],
            betas=tuple(SETTINGS["optimizer_betas"]),
            eps=SETTINGS["optimizer_eps"],
            weight_decay=SETTINGS["weight_decay"],
        )
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
                "gradient_norm_before_clip": float(norm),
                **measured,
            }
            with (output / "STEPS.jsonl").open("ab") as stream:
                stream.write(data.canonical(row) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            steps.append(row)
        after = numeric._parameter_hash(parameters, torch)
        adapter = output / "adapter"
        adapter.mkdir(exist_ok=False)
        model.save_pretrained(adapter, safe_serialization=True)
        manifest = {
            "schema": SCHEMA,
            "base_manifest": copy.deepcopy(parent),
            "base_model_digest": data.digest(parent),
            "runtime": copy.deepcopy(parent["runtime"]),
            "backend_versions": copy.deepcopy(parent["backend_versions"]),
            "adapter_directory": adapter.relative_to(artifact_root).as_posix(),
            "adapter_files": probe._inventory(adapter),
            "peft_version": peft.__version__,
            "source_inventory": freeze["source_inventory"],
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
        identity = verify_manifest(manifest, artifact_root, code_root)
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
