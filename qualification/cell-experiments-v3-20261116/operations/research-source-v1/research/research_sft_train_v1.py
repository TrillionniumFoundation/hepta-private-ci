"""Research-only LoRA training with the original numeric loss and fixed loop.

No original contract is monkeypatched. The separate research schema cannot be
loaded through the native candidate validator. Import only after source binding.
"""

import copy
import os
from pathlib import Path
import time

import research_sft_contract_v1 as contract
from cell_experiments import causal_probe_v3 as probe, chat_protocol, data, repo_execution
from cell_experiments import causal_train_v3 as original
from cell_experiments.coding_sft import file_hash, write_new

io = contract.helpers().io
selected_token_loss = original.selected_token_loss
_parameter_hash = original._parameter_hash


class Predictor(probe.Predictor):
    """Cold-load the exact research artifact while retaining the parent's greedy policy."""

    def __init__(self, manifest, artifact_root):
        identity = contract.verify_model(manifest, artifact_root)
        super().__init__(manifest["base_manifest"], artifact_root)
        import peft

        try:
            self.model = peft.PeftModel.from_pretrained(
                self.model,
                str(probe._base(artifact_root, manifest["adapter_directory"])),
                is_trainable=False,
                local_files_only=True,
            )
            self.model.eval()
            self.model.requires_grad_(False)
            self.manifest, self.model_digest = copy.deepcopy(manifest), identity
        except BaseException:
            self.close()
            raise


def load_predictor(manifest, root):
    return (
        probe.Predictor(manifest, root)
        if manifest.get("schema") == probe.SCHEMA
        else Predictor(manifest, root)
    )


def fit_steps(torch, model, pad_token_id, encoded, records, settings, optimizer, parameters, device, output):
    """The production numeric loop; also exercised by a separate tiny CPU test."""
    io.require(settings == contract.TRAINING and len(encoded) == len(records) == 6,
               "fixed research settings and all six record groups required")
    losses, consumed, supervised = [], 0, 0
    counts = [[0] * len(turns) for turns in encoded]
    for index in range(settings["steps"]):
        group = index % len(encoded)
        turn = (index // len(encoded)) % len(encoded[group])
        row = encoded[group][turn]
        padding = settings["sequence_tokens"] - len(row["input_ids"])
        ids = torch.tensor(
            [row["input_ids"] + [pad_token_id] * padding],
            device=device,
        )
        labels = torch.tensor([row["labels"] + [-100] * padding], device=device)
        mask = torch.tensor(
            [[1] * len(row["input_ids"]) + [0] * padding], device=device
        )
        optimizer.zero_grad(set_to_none=True)
        loss, selected = selected_token_loss(model, ids, mask, labels)
        if not bool(torch.isfinite(loss)):
            raise ValueError("nonfinite observed training loss")
        loss.backward()
        norm = torch.nn.utils.clip_grad_norm_(
            [value for _, value in parameters],
            settings["max_grad_norm"],
            error_if_nonfinite=True,
        )
        optimizer.step()
        losses.append(float(loss.detach()))
        consumed += len(row["input_ids"])
        supervised += selected
        counts[group][turn] += 1
        step = {
            "step": index + 1,
            "task_id": records[group]["task_id"],
            "record_id": row["record_id"],
            "turn": turn,
            "loss": losses[-1],
            "gradient_norm_before_clip": float(norm),
            "input_tokens": len(row["input_ids"]),
            "supervised_tokens": selected,
            "padded_positions": settings["sequence_tokens"],
            "observed_at_ns": time.time_ns(),
        }
        with (output / "STEPS.jsonl").open("ab") as stream:
            stream.write(data.canonical(step) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    return losses, consumed, supervised, counts


def train(records, parent, root, plan, output, context):
    """Create one research-only artifact; failures and completed steps are retained."""
    root, output = Path(root), Path(output)
    io.workspace_guard(root, output)
    io.require(parent == context["parent"], "research parent differs from bound baseline")
    output.mkdir(parents=True, exist_ok=False)
    write_new(
        output / "STARTED.json",
        {"plan_digest": data.digest(plan), "started_at_ns": time.time_ns(), **contract.SCOPE},
    )
    usage_before = io.usage()
    started, cpu, predictor = time.perf_counter(), time.process_time(), None
    torch = None
    try:
        contract.validate_plan(records, context, plan)
        probe.verify_model(parent, root)
        repo_execution.load_catalog()
        references = []
        for index, row in enumerate(records):
            references.append(contract.recheck_reference(row, output / "references" / str(index)))
        write_new(output / "REFERENCE_RECHECKS.json", references)
        if not all(row["success"] for row in references):
            raise ValueError("an actual A reference execution failed")
        torch, _ = probe._libraries()
        import peft

        settings = plan["training"]
        device = torch.device(parent["runtime"]["device"])
        torch.cuda.empty_cache()
        probe.check_device(torch, parent["runtime"])
        torch.cuda.set_per_process_memory_fraction(
            settings["cuda_memory_fraction"], device
        )
        torch.cuda.reset_peak_memory_stats(device)
        torch.manual_seed(settings["seed"])
        torch.cuda.manual_seed_all(settings["seed"])
        predictor = probe.Predictor(parent, root)
        examples = chat_protocol.native_examples(records, plan["mode"])
        encoded = [
            chat_protocol.encode_native_turns(
                predictor.tokenizer, example, settings["sequence_tokens"]
            )
            for example in examples
        ]
        if len(encoded) != len(records):
            raise ValueError("training examples dropped an A record")
        model = peft.get_peft_model(
            predictor.model,
            peft.LoraConfig(
                r=4,
                lora_alpha=8,
                lora_dropout=0.0,
                target_modules=settings["target_modules"],
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
        if not parameters or any("lora_" not in name for name, _ in parameters):
            raise ValueError("only declared LoRA parameters may train")
        before = _parameter_hash(parameters, torch)
        optimizer = torch.optim.AdamW(
            [value for _, value in parameters],
            lr=settings["learning_rate"],
            betas=tuple(settings["optimizer_betas"]),
            eps=settings["optimizer_eps"],
            weight_decay=settings["weight_decay"],
        )
        losses, consumed, supervised, counts = fit_steps(
            torch, model, predictor.tokenizer.pad_token_id, encoded, records,
            settings, optimizer, parameters, device, output)
        after = _parameter_hash(parameters, torch)
        adapter = output / "adapter"
        adapter.mkdir(exist_ok=False)
        model.save_pretrained(adapter, safe_serialization=True)
        with (output / "optimizer.pt").open("xb") as stream:
            torch.save(optimizer.state_dict(), stream)
        manifest = {
            "schema": contract.MODEL_SCHEMA,
            "profile": contract.PROFILE,
            "admission_policy": contract.ADMISSION,
            "family": contract.FAMILY,
            "model_id": probe.MODEL_ID,
            "parent_model_digest": data.digest(parent),
            "base_manifest": copy.deepcopy(parent),
            "runtime": copy.deepcopy(parent["runtime"]),
            "adapter_directory": adapter.relative_to(root).as_posix(),
            "backend_versions": copy.deepcopy(parent["backend_versions"]),
            "adapter_files": probe._inventory(adapter),
            "peft_version": peft.__version__,
            "training_plan_digest": data.digest(plan),
            "evidence_scope": "research_only_post_failure_exploration",
            "research_source_inventory": plan["source_inventory"],
            "reference_admission_digest": data.digest(plan["reference_admission"]),
            "parent_successful_A_tasks": plan["reference_admission"]["parent_successful_A_tasks"],
            **contract.SCOPE,
        }
        candidate = contract.verify_model(manifest, root)
        contract.validate_plan(records, context, plan)
        torch.cuda.synchronize(device)
        receipt = {
            "schema": "hepta.research-authored-sft-training.v1",
            "status": "COMPLETE",
            "plan_digest": data.digest(plan),
            "parent_model_digest": data.digest(parent),
            "research_model_digest": candidate,
            "records_digest": data.digest(records),
            "source_inventory": plan["source_inventory"],
            "mode": plan["mode"],
            "steps": settings["steps"],
            "losses": losses,
            "parameter_before": before,
            "parameter_after": after,
            "parameter_change": before != after,
            "trainable_parameters": sum(value.numel() for _, value in parameters),
            "record_turn_updates": counts,
            "original_record_groups": len(records),
            "encoded_supervised_turns": sum(map(len, encoded)),
            "dropped_terminal_duplicates": sum(
                turns[0].get("dropped_terminal_duplicates", 0) for turns in encoded
            ),
            "device": predictor.device_report,
            "optimizer": {
                "path": (output / "optimizer.pt").relative_to(root).as_posix(),
                "sha256": file_hash(output / "optimizer.pt"),
                "bytes": (output / "optimizer.pt").stat().st_size,
            },
            "cost": {
                "wall_seconds": time.perf_counter() - started,
                "cpu_seconds": time.process_time() - cpu,
                "padded_training_token_positions": settings["steps"]
                * settings["sequence_tokens"],
                "input_tokens_consumed": consumed,
                "supervised_tokens": supervised,
                "cuda_peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
                "cuda_peak_reserved_bytes": torch.cuda.max_memory_reserved(device),
                "cuda_memory_fraction": settings["cuda_memory_fraction"],
                "scope": "research verification/load/encode/train/save; self CPU and completed verifier-child CPU are separate",
                "completed_child_cpu_seconds": io.cost(usage_before)["completed_child_cpu_seconds"],
                "monetary_cost": None, "gpu_active_seconds": None,
                "nested_scopes_are_not_additive": True,
                "energy_joules": None,
                "complete": False,
            },
            "seed": settings["seed"],
            "bitwise_cross_host_determinism_qualified": False,
            "completed_at_ns": time.time_ns(),
            "independent_sample_increment": 0,
            "external_teacher_count_added": 0,
            "scientific_confirmation_qualified": False,
            "native_cell_adoption": False,
            **contract.SCOPE,
        }
        write_new(output / "manifest.json", manifest)
        write_new(output / "TRAINING.json", receipt)
        return manifest, receipt
    except BaseException as error:
        write_new(
            output / "FAILED.json",
            {
                "status": "FAILED_PRESERVED",
                "error": repr(error),
                "wall_seconds": time.perf_counter() - started,
                "automatic_retry": False,
                "completed_steps_log": "STEPS.jsonl",
                "completed_at_ns": time.time_ns(),
                "cost": io.cost(usage_before), **contract.SCOPE,
            },
        )
        raise
    finally:
        if predictor is not None:
            predictor.close()
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()


