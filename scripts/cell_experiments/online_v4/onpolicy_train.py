"""Actual LoRA warm-start with fresh optimizer and verified tensor continuity."""

import copy
import gc
import importlib
from pathlib import Path
import time

from .. import causal_probe_v3 as probe, causal_train_v3 as numeric, chat_protocol, data, repo_execution
from ..coding_sft import file_hash, write_new
from . import onpolicy_contract as contract


def attach_adapter(model, manifest, root, *, trainable):
    """Attach existing weights explicitly; only a native base gets new LoRA tensors."""
    import peft

    if manifest.get("schema") == probe.SCHEMA:
        if not trainable:
            return model
        return peft.get_peft_model(model, peft.LoraConfig(
            r=4, lora_alpha=8, lora_dropout=0.0, target_modules=["q_proj", "v_proj"],
            task_type="CAUSAL_LM", bias="none"))
    return peft.PeftModel.from_pretrained(
        model, str(probe._base(root, manifest["adapter_directory"])),
        is_trainable=trainable, local_files_only=True)


def checked_parameter_hash(model, torch, expected_after):
    parameters = [(name, value) for name, value in model.named_parameters() if value.requires_grad]
    contract.require(bool(parameters) and all("lora_" in name for name, _ in parameters),
                     "only declared LoRA parameters may train")
    before = numeric._parameter_hash(parameters, torch)
    contract.require(expected_after is None or before == expected_after,
                     "loaded adapter tensors differ from previous actual after hash")
    return parameters, before


class Predictor(probe.Predictor):
    """Use the original generation policy with the exact new research candidate."""

    def __init__(self, manifest, root):
        identity = contract.verify_model(manifest, root)
        base = manifest if manifest.get("schema") == probe.SCHEMA else manifest["base_manifest"]
        super().__init__(base, root)
        try:
            self.model = attach_adapter(self.model, manifest, root, trainable=False)
            self.model.eval()
            self.model.requires_grad_(False)
            self.manifest, self.model_digest = copy.deepcopy(manifest), identity
        except BaseException:
            self.close()
            raise


def load_predictor(manifest, root):
    # A previous fit may have left unused allocator blocks after its frame exited.
    # Release only this process's unused memory before the unchanged admission.
    gc.collect()
    torch, _ = probe._libraries()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return Predictor(manifest, root)


def train(records, initial, root, plan, output, context):
    """Keep original selected-token loss, 64-step loop and resource admission."""
    old = contract.legacy()
    io = old.helpers().io
    root, output = Path(root), Path(output)
    io.workspace_guard(root, output)
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "STARTED.json", {
        "plan_digest": data.digest(plan), "started_at_ns": time.time_ns(), **contract.SCOPE})
    started, cpu, usage = time.perf_counter(), time.process_time(), io.usage()
    predictor = torch = None
    try:
        contract.validate_plan(records, initial, root, context, plan)
        repo_execution.load_catalog("open")
        references = [old.recheck_reference(row, output / "references" / str(index))
                      for index, row in enumerate(records)]
        write_new(output / "REFERENCE_RECHECKS.json", references)
        torch, _ = probe._libraries()
        import peft

        settings = plan["training"]
        base = initial if initial.get("schema") == probe.SCHEMA else initial["base_manifest"]
        device = torch.device(base["runtime"]["device"])
        torch.cuda.empty_cache()
        probe.check_device(torch, base["runtime"])
        torch.cuda.set_per_process_memory_fraction(settings["cuda_memory_fraction"], device)
        torch.cuda.reset_peak_memory_stats(device)
        torch.manual_seed(settings["seed"])
        torch.cuda.manual_seed_all(settings["seed"])
        predictor = probe.Predictor(base, root)
        model = attach_adapter(predictor.model, initial, root, trainable=True)
        predictor.model = model
        expected = (plan["previous_training"] or {}).get("parameter_after")
        parameters, before = checked_parameter_hash(model, torch, expected)
        write_new(output / "WARM_START.json", {
            "previous_model_digest": data.digest(initial), "previous_training": plan["previous_training"],
            "actual_loaded_parameter_hash": before, "expected_previous_after": expected,
            "warm_start": expected is not None, "matched": expected is None or before == expected,
            "optimizer_initialization": "fresh_AdamW_each_round", "optimizer_resume": False})
        examples = chat_protocol.native_examples(records, "trajectory")
        encoded = [chat_protocol.encode_native_turns(predictor.tokenizer, example,
                                                     settings["sequence_tokens"])
                   for example in examples]
        contract.require(len(encoded) == len(records) == 6, "all six A groups required")
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        model.enable_input_require_grads()
        model.train()
        optimizer = torch.optim.AdamW(
            [value for _, value in parameters], lr=settings["learning_rate"],
            betas=tuple(settings["optimizer_betas"]), eps=settings["optimizer_eps"],
            weight_decay=settings["weight_decay"])
        original_train = importlib.import_module("research_sft_train_v1")
        losses, consumed, supervised, counts = original_train.fit_steps(
            torch, model, predictor.tokenizer.pad_token_id, encoded, records, settings,
            optimizer, parameters, device, output)
        after = numeric._parameter_hash(parameters, torch)
        adapter = output / "adapter"
        adapter.mkdir(exist_ok=False)
        model.save_pretrained(adapter, safe_serialization=True)
        with (output / "optimizer.pt").open("xb") as stream:
            torch.save(optimizer.state_dict(), stream)
        manifest = {
            "schema": contract.MODEL_SCHEMA, "profile": contract.PROFILE,
            "model_id": probe.MODEL_ID, "previous_model_digest": data.digest(initial),
            "base_model_digest": data.digest(base), "base_manifest": copy.deepcopy(base),
            "runtime": copy.deepcopy(base["runtime"]),
            "backend_versions": copy.deepcopy(base["backend_versions"]),
            "adapter_directory": adapter.relative_to(root).as_posix(),
            "adapter_files": probe._inventory(adapter), "peft_version": peft.__version__,
            "source_inventory": plan["source_inventory"], "training_settings": settings,
            "training_plan_digest": data.digest(plan), "retention": "latest_round_only",
            "optimizer_initialization": "fresh_AdamW_each_round",
            "parameter_before": before, "parameter_after": after, **contract.SCOPE,
        }
        candidate = contract.verify_model(manifest, root)
        contract.validate_plan(records, initial, root, context, plan)
        torch.cuda.synchronize(device)
        receipt = {
            "schema": "hepta.current-policy-sft-training.v1", "status": "COMPLETE",
            "candidate_model_digest": candidate, "previous_model_digest": data.digest(initial),
            "plan_digest": data.digest(plan), "records_digest": data.digest(records),
            "source_inventory": plan["source_inventory"], "steps": settings["steps"],
            "parameter_before": before, "parameter_after": after, "parameter_change": before != after,
            "previous_parameter_after": expected, "warm_start": expected is not None,
            "warm_start_matched": expected is None or before == expected,
            "optimizer_initialization": "fresh_AdamW_each_round", "optimizer_resume": False,
            "losses": losses, "trainable_parameters": sum(v.numel() for _, v in parameters),
            "record_turn_updates": counts, "encoded_supervised_turns": sum(map(len, encoded)),
            "optimizer": {"path": (output / "optimizer.pt").relative_to(root).as_posix(),
                          "sha256": file_hash(output / "optimizer.pt"),
                          "bytes": (output / "optimizer.pt").stat().st_size},
            "cost": {
                "wall_seconds": time.perf_counter() - started, "cpu_seconds": time.process_time() - cpu,
                "completed_child_cpu_seconds": io.cost(usage)["completed_child_cpu_seconds"],
                "input_tokens_consumed": consumed, "supervised_tokens": supervised,
                "padded_training_token_positions": settings["steps"] * settings["sequence_tokens"],
                "cuda_peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
                "cuda_peak_reserved_bytes": torch.cuda.max_memory_reserved(device),
                "scope": "reference/load/encode/train/save; nested scopes are not additive",
                "gpu_active_seconds": None, "energy_joules": None, "monetary_cost": None,
                "complete": False},
            "completed_at_ns": time.time_ns(), **contract.SCOPE,
        }
        write_new(output / "manifest.json", manifest)
        write_new(output / "TRAINING.json", receipt)
        return manifest, receipt
    except BaseException as error:
        write_new(output / "FAILED.json", {
            "status": "FAILED_PRESERVED", "error_type": type(error).__name__, "error": str(error),
            "cost": io.cost(usage), "completed_steps_log": "STEPS.jsonl", "automatic_retry": False,
            **contract.SCOPE})
        raise
    finally:
        if predictor is not None:
            predictor.close()
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
