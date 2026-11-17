"""Bounded Qwen LoRA development fits, with exact selected-token causal loss.

Run training in a dedicated process: Torch RNG, threads and CUDA allocator limits
are process settings. This module never downloads a model or opens a new C set.
Qwen2 v4.57.3 supports tensor logits_to_keep before its language-model head:
https://github.com/huggingface/transformers/blob/v4.57.3/src/transformers/models/qwen2/modeling_qwen2.py
The reviewed upstream blob is 262e03cb1568dad0c9b2d027fa8ebdc36301b88b.
"""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import time

from . import causal_probe_v3 as probe, chat_protocol, data, repo_execution
from .coding_sft import file_hash, write_new
from .causal_training_contract_v3 import SCHEMA, FAMILY, validate_plan, verify_candidate
from .causal_training_contract_v3 import make_plan as make_plan


def selected_token_loss(model, input_ids, attention_mask, labels):
    """Exactly the batch-one dense causal objective, without unused head logits."""
    import torch

    if (
        input_ids.ndim != 2
        or input_ids.shape[0] != 1
        or labels.shape != input_ids.shape
        or attention_mask.shape != input_ids.shape
    ):
        raise ValueError("one aligned sequence required")
    positions = torch.nonzero(labels[0, 1:] != -100, as_tuple=False).flatten()
    if positions.numel() == 0 or bool((attention_mask[0, positions + 1] != 1).any()):
        raise ValueError("nonempty unmasked next-token supervision required")
    logits = model(
        input_ids=input_ids,
        attention_mask=attention_mask,
        use_cache=False,
        logits_to_keep=positions,
    ).logits
    if logits.shape[:2] != (1, positions.numel()):
        raise ValueError("backend did not select the declared causal positions")
    return torch.nn.functional.cross_entropy(
        logits[0].float(), labels[0, positions + 1]
    ), int(positions.numel())


class Predictor(probe.Predictor):
    """Cold-load the exact candidate while retaining the parent's greedy policy."""

    def __init__(self, manifest, artifact_root):
        identity = verify_candidate(manifest, artifact_root)
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


def _parameter_hash(parameters, torch):
    result = hashlib.sha256()
    for name, value in parameters:
        result.update(
            data.canonical(
                {"name": name, "dtype": str(value.dtype), "shape": list(value.shape)}
            )
        )
        result.update(
            value.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes()
        )
    return result.hexdigest()


def train(records, parent, root, plan, output, readiness):
    """Create one immutable candidate; failures and completed steps are retained."""
    root, output = Path(root).resolve(), Path(output).resolve()
    output.relative_to(root)
    output.mkdir(parents=True, exist_ok=False)
    write_new(
        output / "STARTED.json",
        {"plan_digest": data.digest(plan), "started_at_ns": time.time_ns()},
    )
    started, cpu, predictor = time.perf_counter(), time.process_time(), None
    torch = None
    try:
        validate_plan(records, parent, readiness, plan)
        probe.verify_model(parent, root)
        repo_execution.load_catalog()
        references = [data.verify_answer(row, row["final_answer"]) for row in records]
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
        losses, consumed, supervised = [], 0, 0
        counts = [[0] * len(turns) for turns in encoded]
        for index in range(settings["steps"]):
            group = index % len(encoded)
            turn = (index // len(encoded)) % len(encoded[group])
            row = encoded[group][turn]
            padding = settings["sequence_tokens"] - len(row["input_ids"])
            ids = torch.tensor(
                [row["input_ids"] + [predictor.tokenizer.pad_token_id] * padding],
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
        after = _parameter_hash(parameters, torch)
        adapter = output / "adapter"
        adapter.mkdir(exist_ok=False)
        model.save_pretrained(adapter, safe_serialization=True)
        with (output / "optimizer.pt").open("xb") as stream:
            torch.save(optimizer.state_dict(), stream)
        manifest = {
            "schema": SCHEMA,
            "family": FAMILY,
            "model_id": probe.MODEL_ID,
            "parent_model_digest": data.digest(parent),
            "base_manifest": copy.deepcopy(parent),
            "runtime": copy.deepcopy(parent["runtime"]),
            "adapter_directory": adapter.relative_to(root).as_posix(),
            "backend_versions": copy.deepcopy(parent["backend_versions"]),
            "adapter_files": probe._inventory(adapter),
            "peft_version": peft.__version__,
            "training_plan_digest": data.digest(plan),
            "evidence_scope": "development_only",
        }
        candidate = verify_candidate(manifest, root)
        validate_plan(records, parent, readiness, plan)
        torch.cuda.synchronize(device)
        receipt = {
            "schema": "hepta.causal-lora-training.v3",
            "status": "COMPLETE",
            "plan_digest": data.digest(plan),
            "parent_model_digest": data.digest(parent),
            "candidate_model_digest": candidate,
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
                "scope": "verification/load/encode/train/save; CPU excludes verifier subprocesses",
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
            },
        )
        raise
    finally:
        if predictor is not None:
            predictor.close()
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("records", "parent", "readiness", "plan", "root", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()

    def read(path):
        return json.loads(path.read_text())

    _, result = train(
        read(args.records),
        read(args.parent),
        args.root,
        read(args.plan),
        args.output,
        read(args.readiness),
    )
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in ("source_inventory", "losses")}
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
