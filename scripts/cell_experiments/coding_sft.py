"""Real local causal-LM LoRA training and inference for versioned task records.

This separate profile never changes the existing conditional-binary worker.
Models, generated text and measured costs are experimental evidence only.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

try:
    import resource
except ImportError:
    resource = None

from .data import canonical, digest, load_records
from . import chat_protocol

FAMILY = "hepta-smollm2-coding-sft-v1"
MODEL_SCHEMA = "hepta.experimental-model.v1"


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            result.update(block)
    return result.hexdigest()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def bound_file(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("manifest paths must stay inside artifact root")
    current = Path(root)
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("model symlink is not an immutable artifact")
    if not current.is_file():
        raise ValueError("missing model artifact: " + str(relative))
    return current


def verify_model(manifest, root):
    if manifest.get("schema") != MODEL_SCHEMA or manifest.get("family") != FAMILY:
        raise ValueError("unsupported model profile")
    if not isinstance(manifest.get("files"), list) or not manifest["files"]:
        raise ValueError("model files missing")
    paths = set()
    for item in manifest["files"]:
        if item["path"] in paths:
            raise ValueError("duplicate model artifact")
        paths.add(item["path"])
        path = bound_file(root, item["path"])
        if path.stat().st_size != item["bytes"] or file_hash(path) != item["sha256"]:
            raise ValueError("model artifact identity mismatch")
    base_dir = manifest["runtime"]["base_directory"]
    protocol = chat_protocol.protocol_name(manifest["runtime"])
    for required in (
        "model.safetensors",
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
    ):
        if str(Path(base_dir) / required) not in paths:
            raise ValueError("required base artifact is not bound: " + required)
    if protocol == chat_protocol.NATIVE:
        config = json.loads(
            (Path(root) / base_dir / "tokenizer_config.json").read_text()
        )
        if chat_protocol.template_digest(config.get("chat_template")) != manifest[
            "runtime"
        ].get("chat_template_sha256"):
            raise ValueError("chat template differs from frozen runtime")
    adapter = manifest["runtime"].get("adapter_directory")
    if adapter:
        for required in ("adapter_model.safetensors", "adapter_config.json"):
            if str(Path(adapter) / required) not in paths:
                raise ValueError("required adapter artifact is not bound")
    loadable_names = {
        "config.json",
        "generation_config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "added_tokens.json",
        "vocab.json",
        "vocab.txt",
        "merges.txt",
        "tokenizer.model",
        "spiece.model",
        "adapter_config.json",
    }
    for directory in (base_dir, adapter):
        if directory:
            for path in (Path(root) / directory).iterdir():
                loadable = (
                    path.name in loadable_names
                    or path.suffix in (".safetensors", ".bin")
                    or path.name.endswith(".index.json")
                )
                if loadable and str(path.relative_to(root)) not in paths:
                    raise ValueError("unbound loadable file: " + path.name)
    return digest(manifest)


def prompt_text(value, tokenizer=None, protocol=chat_protocol.LEGACY, messages=None):
    if protocol == chat_protocol.NATIVE:
        return chat_protocol.render_prompt(tokenizer, value, messages)
    if protocol != chat_protocol.LEGACY or messages is not None:
        raise ValueError("unsupported legacy chat history")
    return "### User\n" + value + "\n### Assistant\n"


def encode_example(tokenizer, example, limit, protocol=chat_protocol.LEGACY):
    """Preserve all visible observations, mask their loss, reject overflow."""
    if protocol == chat_protocol.NATIVE:
        return chat_protocol.encode_native_example(tokenizer, example, limit)
    if protocol != chat_protocol.LEGACY:
        raise ValueError("unsupported training protocol")
    ids = tokenizer.encode(prompt_text(example["input"]), add_special_tokens=False)
    labels = [-100] * len(ids)
    for number, segment in enumerate(example["segments"]):
        if number:
            prefix = (
                "\n### " + ("Tool" if segment["role"] == "tool" else "Assistant") + "\n"
            )
            prefix_ids = tokenizer.encode(prefix, add_special_tokens=False)
            ids.extend(prefix_ids)
            labels.extend([-100] * len(prefix_ids))
        tokens = tokenizer.encode(segment["content"], add_special_tokens=False)
        ids.extend(tokens)
        labels.extend(tokens if segment["train"] else [-100] * len(tokens))
    if tokenizer.eos_token_id is not None:
        ids.append(tokenizer.eos_token_id)
        labels.append(tokenizer.eos_token_id)
    if len(ids) > limit:
        raise ValueError(
            f"record {example['record_id']} needs {len(ids)} tokens; limit={limit}; no truncation"
        )
    if not any(token != -100 for token in labels[1:]):
        raise ValueError("no causally predicted supervised token")
    return {
        "record_id": example["record_id"],
        "input_ids": ids,
        "labels": labels,
        "supervised_tokens": sum(token != -100 for token in labels[1:]),
    }


def inventory(root, paths, role):
    return [
        {
            "role": role,
            "path": str(path.relative_to(root)),
            "sha256": file_hash(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(paths)
    ]


def prepare_base(materials, output, settings):
    """Copy a pinned local model once; never download or execute remote code."""
    output, materials = Path(output), Path(materials)
    base = output / "base"
    base.mkdir(parents=True, exist_ok=False)
    for source in sorted(materials.iterdir()):
        if source.is_file() and source.suffix in (
            ".json",
            ".safetensors",
            ".txt",
            ".model",
        ):
            shutil.copyfile(source, base / source.name)
    files = inventory(output, list(base.iterdir()), "base")
    for item in files:
        if Path(item["path"]).name.startswith(
            ("tokenizer", "special_tokens", "vocab", "merges")
        ):
            item["role"] = "tokenizer"
    settings = dict(settings)
    if chat_protocol.protocol_name(settings) == chat_protocol.NATIVE:
        config = json.loads((base / "tokenizer_config.json").read_text())
        settings["chat_template_sha256"] = chat_protocol.template_digest(
            config.get("chat_template")
        )
    manifest = {
        "schema": MODEL_SCHEMA,
        "family": FAMILY,
        "parent": None,
        "files": files,
        "runtime": {
            **settings,
            "backend": "transformers_cpu_lora",
            "base_directory": "base",
            "adapter_directory": None,
        },
    }
    verify_model(manifest, output)
    write_new(output / "parent.json", manifest)
    return manifest


def _libraries():
    import torch
    import transformers
    import peft

    return torch, transformers, peft


def _load(manifest, root, trainable=False):
    model_digest = verify_model(manifest, root)
    torch, transformers, peft = _libraries()
    runtime = manifest["runtime"]
    torch.set_num_threads(runtime.get("threads", 2))
    base = str(Path(root) / runtime["base_directory"])
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        base, local_files_only=True, trust_remote_code=False
    )
    if (
        chat_protocol.protocol_name(runtime) == chat_protocol.NATIVE
        and chat_protocol.template_digest(tokenizer.get_chat_template())
        != runtime["chat_template_sha256"]
    ):
        raise ValueError("loaded tokenizer chat template differs from frozen runtime")
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = transformers.AutoModelForCausalLM.from_pretrained(
        base,
        local_files_only=True,
        trust_remote_code=False,
        use_safetensors=True,
        torch_dtype=torch.float32,
        attn_implementation="eager",
    )
    adapter = runtime.get("adapter_directory")
    if adapter:
        model = peft.PeftModel.from_pretrained(
            model,
            str(Path(root) / adapter),
            is_trainable=trainable,
            local_files_only=True,
        )
    return model, tokenizer, model_digest


class Predictor:
    def __init__(self, manifest, artifact_root):
        self.manifest = manifest
        self.model, self.tokenizer, self.model_digest = _load(manifest, artifact_root)
        self.model.eval()

    def predict(self, record, *, retain_encoding=False):
        torch, _, _ = _libraries()
        prompt = record["task"]["input"]
        protocol = chat_protocol.protocol_name(self.manifest["runtime"])
        rendered = prompt_text(
            prompt, self.tokenizer, protocol, record["task"].get("messages")
        )
        encoded = self.tokenizer(
            rendered, return_tensors="pt", add_special_tokens=False
        )
        limit = self.manifest["runtime"]["max_input_tokens"]
        if encoded.input_ids.shape[1] > limit:
            raise ValueError("inference context exceeds frozen token budget")
        started = time.perf_counter()
        with torch.inference_mode():
            output = self.model.generate(
                **encoded,
                do_sample=False,
                max_new_tokens=self.manifest["runtime"]["max_new_tokens"],
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )
        produced = output[0, encoded.input_ids.shape[1] :]
        encoding = {}
        if retain_encoding:
            input_ids = encoded.input_ids[0].tolist()
            encoding = {
                "rendered_input": rendered,
                "input_ids": input_ids,
                "input_ids_sha256": digest(input_ids),
                "output_ids": produced.tolist(),
                "eos_token_id": self.tokenizer.eos_token_id,
            }
        return {
            **encoding,
            "answer": self.tokenizer.decode(produced, skip_special_tokens=True),
            "loaded_model_digest": self.model_digest,
            "input_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "rendered_input_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
            "message_protocol": protocol,
            "input_tokens": encoded.input_ids.shape[1],
            "output_tokens": len(produced),
            "elapsed_seconds": time.perf_counter() - started,
            "time_scope": "generate and decode; excludes load and input tokenization",
            "pid": os.getpid(),
            "external_effect_executed": False,
            **chat_protocol.generation_termination(
                produced,
                self.tokenizer.eos_token_id,
                self.manifest["runtime"]["max_new_tokens"],
            ),
        }

    def encode_features(self, record, dimensions=64):
        torch, _, _ = _libraries()
        encoded = self.tokenizer(
            prompt_text(
                record["task"]["input"],
                self.tokenizer,
                chat_protocol.protocol_name(self.manifest["runtime"]),
                record["task"].get("messages"),
            ),
            return_tensors="pt",
            add_special_tokens=False,
        )
        if encoded.input_ids.shape[1] > self.manifest["runtime"]["max_input_tokens"]:
            raise ValueError("feature context exceeds budget")
        with torch.inference_mode():
            output = self.model(**encoded, output_hidden_states=True)
        vector = output.hidden_states[-1][0].mean(dim=0)[:dimensions]
        return (vector / vector.norm().clamp_min(1e-8)).tolist()

    def close(self):
        del self.model


def load_predictor(manifest, artifact_root):
    return Predictor(manifest, artifact_root)


def train(records, parent, artifact_root, plan, mode, output_name):
    output = Path(artifact_root) / "models" / output_name
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    write_new(
        output / "STARTED.json",
        {
            "plan_digest": digest(plan),
            "records_digest": digest(records),
            "mode": mode,
            "started_at_ns": time.time_ns(),
        },
    )
    try:
        return _train(records, parent, artifact_root, plan, mode, output)
    except BaseException as error:
        write_new(
            output / "FAILED.json",
            {
                "status": "FAILED",
                "error": repr(error),
                "elapsed_seconds": time.perf_counter() - started,
                "completed_steps_log": "STEPS.jsonl",
                "completed_at_ns": time.time_ns(),
                "automatic_retry": False,
            },
        )
        raise


def _train(records, parent, artifact_root, plan, mode, output):
    """Run actual AdamW updates; equal steps and padded sequence positions per arm."""
    if (
        data_sources := sorted({record["source_id"] for record in records})
    ) != plan.get("train_sources"):
        raise ValueError("training sources differ from frozen plan")
    if digest(records) != plan.get("training_records_digest") or mode != plan.get(
        "training_mode"
    ):
        raise ValueError("training records or mode differ from frozen plan")
    if digest(parent) != plan.get("parent_model_digest"):
        raise ValueError("training parent differs from frozen plan")
    observed_source = {
        p.name: file_hash(p) for p in sorted(Path(__file__).parent.glob("*.py"))
    }
    if digest(observed_source) != plan.get("source_digest"):
        raise ValueError("executable source differs from frozen plan")
    torch, transformers, peft = _libraries()
    settings = plan["training"]
    steps, length = settings["steps"], settings["sequence_tokens"]
    if not (type(steps) is int and 1 <= steps <= 4096 and 16 <= length <= 4096):
        raise ValueError("unbounded training plan")
    protocol = chat_protocol.protocol_name(parent["runtime"])
    examples = chat_protocol.training_examples(records, mode, protocol)
    if not examples:
        raise ValueError("no authorized successful training records")
    started_at_ns, started_cpu, started = (
        time.time_ns(),
        time.process_time(),
        time.perf_counter(),
    )
    torch.manual_seed(settings["seed"])
    model, tokenizer, parent_digest = _load(parent, artifact_root)
    if parent["runtime"].get("adapter_directory"):
        raise ValueError("E1 comparison requires the same frozen base, not a prior arm")
    encoded = [
        chat_protocol.encode_native_turns(tokenizer, example, length)
        if protocol == chat_protocol.NATIVE
        else [encode_example(tokenizer, example, length)]
        for example in examples
    ]
    model = peft.get_peft_model(
        model,
        peft.LoraConfig(
            r=settings["rank"],
            lora_alpha=settings["rank"] * 2,
            lora_dropout=0.0,
            target_modules=["q_proj", "v_proj"],
            task_type="CAUSAL_LM",
            bias="none",
        ),
    )
    model.train()
    parameters = [
        (name, value) for name, value in model.named_parameters() if value.requires_grad
    ]

    def parameter_hash():
        result = hashlib.sha256()
        for name, value in parameters:
            result.update(name.encode())
            result.update(value.detach().cpu().contiguous().numpy().tobytes())
        return result.hexdigest()

    before = parameter_hash()
    optimizer = torch.optim.AdamW(
        [value for _, value in parameters], lr=settings["learning_rate"]
    )
    losses, consumed, supervised = [], 0, 0
    turn_updates = [[0] * len(turns) for turns in encoded]
    for step in range(steps):
        record_index = step % len(encoded)
        turn_index = (step // len(encoded)) % len(encoded[record_index])
        row = encoded[record_index][turn_index]
        padding = length - len(row["input_ids"])
        ids = torch.tensor([row["input_ids"] + [tokenizer.pad_token_id] * padding])
        labels = torch.tensor([row["labels"] + [-100] * padding])
        mask = torch.tensor([[1] * len(row["input_ids"]) + [0] * padding])
        optimizer.zero_grad(set_to_none=True)
        loss = model(
            input_ids=ids, attention_mask=mask, labels=labels, use_cache=False
        ).loss
        if not torch.isfinite(loss):
            raise ValueError("nonfinite observed training loss")
        loss.backward()
        torch.nn.utils.clip_grad_norm_([value for _, value in parameters], 1.0)
        optimizer.step()
        turn_updates[record_index][turn_index] += 1
        losses.append(float(loss.detach()))
        consumed += len(row["input_ids"])
        supervised += row["supervised_tokens"]
        with (output / "STEPS.jsonl").open("ab") as stream:
            stream.write(
                canonical(
                    {
                        "step": step + 1,
                        "loss": losses[-1],
                        "input_tokens": consumed,
                        "supervised_tokens": supervised,
                        "record_id": row["record_id"],
                        "record_group_index": record_index,
                        "supervised_turn_index": turn_index,
                        "observed_at_ns": time.time_ns(),
                    }
                )
                + b"\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
    after = parameter_hash()
    model.save_pretrained(output, safe_serialization=True)
    torch.save(optimizer.state_dict(), output / "optimizer.pt")
    artifacts = inventory(
        Path(artifact_root), [output / "adapter_model.safetensors"], "adapter"
    )
    artifacts += inventory(
        Path(artifact_root), [output / "adapter_config.json"], "configuration"
    )
    artifacts += inventory(Path(artifact_root), [output / "optimizer.pt"], "optimizer")
    manifest = {
        "schema": MODEL_SCHEMA,
        "family": FAMILY,
        "parent": parent_digest,
        "files": parent["files"] + artifacts,
        "runtime": {
            **parent["runtime"],
            "adapter_directory": str(output.relative_to(artifact_root)),
        },
    }
    candidate_digest = verify_model(manifest, artifact_root)
    write_new(output / "manifest.json", manifest)
    receipt = {
        "schema": "hepta.coding-sft.training.v1",
        "status": "COMPLETE",
        "owner": plan["training_owner"],
        "started_at_ns": started_at_ns,
        "completed_at_ns": time.time_ns(),
        "plan_digest": digest(plan),
        "parent_model_digest": parent_digest,
        "candidate_model_digest": candidate_digest,
        "parameter_change": before != after,
        "parameter_before": before,
        "parameter_after": after,
        "steps": steps,
        "mode": mode,
        "message_protocol": protocol,
        "chat_template_sha256": parent["runtime"].get("chat_template_sha256"),
        "dropped_terminal_duplicates": sum(
            turns[0].get("dropped_terminal_duplicates", 0) for turns in encoded
        ),
        "supervision_schedule": {
            "rule": "record=step%record_count; turn=(step//record_count)%turn_count",
            "original_record_groups": len(encoded),
            "unique_task_ids": len({record["task_id"] for record in records}),
            "encoded_supervised_turns": sum(len(turns) for turns in encoded),
            "independent_sample_increment_from_turns": 0,
            "record_updates": [
                {
                    "record_id": example["record_id"],
                    "turn_updates": counts,
                    "total_updates": sum(counts),
                }
                for example, counts in zip(examples, turn_updates)
            ],
        },
        "records_digest": digest(records),
        "training_source_ids": data_sources,
        "record_ids": [r["record_id"] for r in records],
        "losses": losses,
        "trainable_parameters": sum(p.numel() for _, p in parameters),
        "cost": {
            "wall_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - started_cpu,
            "scope": "verification/load/preprocessing/train/save; excludes imports and final receipt write",
            "padded_training_token_positions": steps * length,
            "input_tokens_consumed": consumed,
            "supervised_tokens": supervised,
            "process_peak_rss_bytes": (
                resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                * (1 if sys.platform == "darwin" else 1024)
                if resource
                else None
            ),
            "peak_rss_scope": "entire_process_including_prior_arms",
            "energy_joules": None,
            "complete": False,
        },
        "libraries": {
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "peft": peft.__version__,
        },
        "independent_learning_benefit_qualified": False,
        "production_eligible": False,
    }
    write_new(output / "training.json", receipt)
    del model, optimizer
    return manifest, receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "train", "predict"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--materials")
    parser.add_argument("--records")
    parser.add_argument("--manifest")
    parser.add_argument("--mode", choices=("final_answer", "trajectory"))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    plan = json.loads(Path(args.plan).read_text())
    if args.operation == "prepare":
        result = prepare_base(args.materials, args.root, plan["inference"])
    elif args.operation == "train":
        records = [r for r in load_records(args.records) if r["split"] == "train"]
        parent = json.loads(Path(args.manifest).read_text())
        manifest, result = train(
            records, parent, args.root, plan, args.mode, args.output
        )
        print(
            json.dumps({"candidate_model_digest": digest(manifest), "training": result})
        )
        return
    else:
        predictor = load_predictor(
            json.loads(Path(args.manifest).read_text()), args.root
        )
        result = [
            {"record_id": r["record_id"], **predictor.predict(r)}
            for r in load_records(args.records)
        ]
        predictor.close()
    write_new(args.output, result)
    print(json.dumps({"output": args.output, "result_digest": digest(result)}))


if __name__ == "__main__":
    main()
