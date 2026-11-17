"""Local, frozen Qwen coder inference for development readiness only.

This module neither downloads artifacts nor exposes a training operation.
build_manifest binds a completed local snapshot; Predictor verifies it before
importing/loading the inference backend. No model output is repaired or parsed.
"""

import copy
import gc
import hashlib
from importlib import metadata
import os
from pathlib import Path
import re
import time

from . import chat_protocol, data
from .coding_sft import file_hash

SCHEMA = "hepta.causal-probe-model.v3"
FAMILY = "hepta-qwen25-coder-readiness-v3"
MODEL_ID = "Qwen/Qwen2.5-Coder-1.5B-Instruct"
MIN_CUDA_FREE_BYTES = 4 * 1024**3


def _versions():
    return {
        name: metadata.version(name)
        for name in ("torch", "transformers", "tokenizers", "safetensors")
    }


def _base(root, relative):
    if not isinstance(relative, str):
        raise ValueError("relative snapshot directory required")
    path = Path(relative)
    if not path.parts or path.is_absolute():
        raise ValueError("relative snapshot directory required")
    current = Path(root)
    for part in path.parts:
        if part in ("..", "."):
            raise ValueError("snapshot must remain inside the artifact root")
        current /= part
        if current.is_symlink():
            raise ValueError("snapshot symlinks are not immutable artifacts")
    if not current.is_dir():
        raise ValueError("local snapshot directory missing")
    return current


def _inventory(base):
    files = []
    for path in sorted(base.rglob("*")):
        if path.is_symlink():
            raise ValueError("snapshot symlink rejected")
        if path.is_dir():
            continue
        if not path.is_file() or len(files) >= 256:
            raise ValueError("bounded regular snapshot files required")
        files.append(
            {
                "path": path.relative_to(base).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": file_hash(path),
            }
        )
    return files


def _json(path, maximum=32 * 1024**2):
    if path.stat().st_size > maximum:
        raise ValueError("configuration file exceeds its bound")
    value = data._parse(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("configuration must be an object")
    return value


def _snapshot(base, files):
    names = {row["path"] for row in files}
    required = {
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "generation_config.json",
    }
    if not required <= names:
        raise ValueError(
            "complete model, tokenizer and generation configuration required"
        )
    if "adapter_config.json" in names or any(
        name.endswith((".bin", ".pt", ".pth", ".ckpt")) for name in names
    ):
        raise ValueError("only the standalone safetensors base is supported")
    weights = {name for name in names if name.endswith(".safetensors")}
    if "model.safetensors.index.json" in names:
        mapping = _json(base / "model.safetensors.index.json").get("weight_map")
        if (
            not isinstance(mapping, dict)
            or not mapping
            or set(mapping.values()) != weights
        ):
            raise ValueError("safetensors shard index does not bind every weight file")
        if "model.safetensors" in names:
            raise ValueError("ambiguous sharded and unsharded model")
    elif weights != {"model.safetensors"}:
        raise ValueError("one complete safetensors model or exact shard index required")
    config = _json(base / "config.json")
    tokenizer = _json(base / "tokenizer_config.json")
    if config.get("model_type") != "qwen2" or config.get("architectures") != [
        "Qwen2ForCausalLM"
    ]:
        raise ValueError("the pinned Qwen coder architecture is required")
    if config.get("quantization_config") is not None:
        raise ValueError("quantized model loading is outside this readiness profile")
    template = tokenizer.get("chat_template")
    if "chat_template.jinja" in names:
        standalone = (base / "chat_template.jinja").read_text(encoding="utf-8")
        if template is not None and template != standalone:
            raise ValueError("ambiguous native chat templates")
        template = standalone
    if not isinstance(template, str) or not 1 <= len(template.encode()) <= 65536:
        raise ValueError("one bounded native chat template required")
    tokens = _json(base / "tokenizer.json")
    vocab = dict(tokens.get("model", {}).get("vocab", {}))
    for token in tokens.get("added_tokens", []):
        content, identifier = token["content"], token["id"]
        if content in vocab and vocab[content] != identifier:
            raise ValueError("conflicting special token identifiers")
        vocab[content] = identifier
    special = {}
    for name in ("bos", "eos", "pad"):
        token = tokenizer.get(name + "_token")
        if isinstance(token, dict):
            token = token.get("content")
        identifier = vocab.get(token) if isinstance(token, str) else None
        if identifier is None and (name != "bos" or token is not None):
            raise ValueError("tokenizer special token is not bound to the vocabulary")
        special[name + "_token_id"] = identifier
    return config, _json(base / "generation_config.json"), template, special


def _generation(config, source, maximum):
    def token(name, multiple=False):
        value = source.get(name, config.get(name))
        values = value if multiple and isinstance(value, list) else [value]
        if not values or any(
            type(v) is not int or not 0 <= v < config["vocab_size"] for v in values
        ):
            raise ValueError(
                "generation special tokens must be explicit vocabulary IDs"
            )
        return value

    return {
        "do_sample": False,
        "num_beams": 1,
        "num_return_sequences": 1,
        "max_new_tokens": maximum,
        "min_new_tokens": 0,
        "use_cache": True,
        "repetition_penalty": 1.0,
        "no_repeat_ngram_size": 0,
        "temperature": 1.0,
        "top_p": 1.0,
        "top_k": 50,
        "bos_token_id": token("bos_token_id"),
        "eos_token_id": token("eos_token_id", multiple=True),
        "pad_token_id": token("pad_token_id"),
    }


def _runtime(runtime, config):
    cpu = runtime.get("device") == "cpu"
    cuda = isinstance(runtime.get("device"), str) and re.fullmatch(
        r"cuda:(0|[1-9][0-9]*)", runtime["device"]
    )
    if not (
        (cpu and runtime.get("dtype") == "float32")
        or (cuda and runtime.get("dtype") == "bfloat16")
    ):
        raise ValueError("explicit cpu/float32 or cuda:index/bfloat16 required")
    for key, low, high in (
        ("threads", 1, 64),
        ("max_input_tokens", 1, 16384),
        ("max_new_tokens", 1, 1024),
    ):
        if type(runtime.get(key)) is not int or not low <= runtime[key] <= high:
            raise ValueError("invalid frozen runtime bound: " + key)
    minimum = runtime.get("min_cuda_free_bytes")
    if type(minimum) is not int or minimum < MIN_CUDA_FREE_BYTES:
        raise ValueError("CUDA free-memory floor must be at least 4 GiB")
    context = config.get("max_position_embeddings")
    if (
        type(context) is not int
        or runtime["max_input_tokens"] + runtime["max_new_tokens"] > context
    ):
        raise ValueError("token budgets exceed the model context window")
    if (
        runtime.get("attn_implementation") != "eager"
        or runtime.get("message_protocol") != chat_protocol.NATIVE
    ):
        raise ValueError("frozen eager/native-chat runtime required")


def build_manifest(
    root,
    base_directory,
    *,
    revision,
    device,
    dtype,
    max_input_tokens=4096,
    max_new_tokens=256,
    threads=2,
    min_cuda_free_bytes=MIN_CUDA_FREE_BYTES,
):
    """Bind an already downloaded local snapshot; no backend/model is loaded."""
    base = _base(root, base_directory)
    files = _inventory(base)
    config, source, template, special = _snapshot(base, files)
    runtime = {
        "base_directory": base_directory,
        "device": device,
        "dtype": dtype,
        "threads": threads,
        "max_input_tokens": max_input_tokens,
        "max_new_tokens": max_new_tokens,
        "min_cuda_free_bytes": min_cuda_free_bytes,
        "message_protocol": chat_protocol.NATIVE,
        "attn_implementation": "eager",
        "chat_template_sha256": chat_protocol.template_digest(template),
        "tokenizer_special_ids": special,
        "generation": _generation(config, source, max_new_tokens),
    }
    _runtime(runtime, config)
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("one exact source snapshot revision required")
    return {
        "schema": SCHEMA,
        "family": FAMILY,
        "model_id": MODEL_ID,
        "revision": revision,
        "files": files,
        "runtime": runtime,
        "backend_versions": _versions(),
        "evidence_scope": "development_readiness_only",
    }


def verify_model(manifest, root):
    """Verify every snapshot byte and reject additions before backend loading."""
    if (manifest.get("schema"), manifest.get("family"), manifest.get("model_id")) != (
        SCHEMA,
        FAMILY,
        MODEL_ID,
    ):
        raise ValueError("unsupported readiness model identity")
    runtime = manifest["runtime"]
    base = _base(root, runtime["base_directory"])
    files = _inventory(base)
    if files != manifest.get("files"):
        raise ValueError("snapshot file inventory or content changed")
    config, source, template, special = _snapshot(base, files)
    _runtime(runtime, config)
    if (
        runtime.get("chat_template_sha256") != chat_protocol.template_digest(template)
        or runtime.get("tokenizer_special_ids") != special
    ):
        raise ValueError("native tokenizer binding changed")
    if runtime.get("generation") != _generation(
        config, source, runtime["max_new_tokens"]
    ):
        raise ValueError(
            "generation configuration differs from the frozen greedy policy"
        )
    if not re.fullmatch(r"[0-9a-f]{40}", manifest.get("revision", "")):
        raise ValueError("exact source revision missing")
    if manifest.get("backend_versions") != _versions():
        raise ValueError("inference backend versions differ from the frozen manifest")
    return data.digest(manifest)


def _libraries():
    import torch
    import transformers

    return torch, transformers


def check_device(torch, runtime):
    """Check the specifically selected device; never choose a fallback device."""
    device = runtime["device"]
    if device == "cpu":
        if runtime["dtype"] != "float32":
            raise ValueError("CPU readiness requires explicit float32")
        return {"device": "cpu", "dtype": "float32"}
    if (
        not re.fullmatch(r"cuda:(0|[1-9][0-9]*)", device)
        or runtime["dtype"] != "bfloat16"
    ):
        raise ValueError("CUDA readiness requires an explicit index and bfloat16")
    index = int(device.split(":")[1])
    if not torch.cuda.is_available() or index >= torch.cuda.device_count():
        raise ValueError("selected CUDA device is unavailable")
    with torch.cuda.device(index):
        if not torch.cuda.is_bf16_supported():
            raise ValueError("selected CUDA device does not support bfloat16")
        free, total = torch.cuda.mem_get_info(index)
        if free < runtime["min_cuda_free_bytes"]:
            raise ValueError("selected CUDA device has insufficient free memory")
        properties = torch.cuda.get_device_properties(index)
    return {
        "device": device,
        "dtype": "bfloat16",
        "device_name": properties.name,
        "free_bytes_before_load": int(free),
        "total_bytes": int(total),
        "compute_capability": [properties.major, properties.minor],
    }


class Predictor:
    """Read-only local inference, compatible with repo_interaction_v3.attempts."""

    def __init__(self, manifest, artifact_root):
        self.manifest = copy.deepcopy(manifest)
        self.model_digest = verify_model(self.manifest, artifact_root)
        self.torch, transformers = _libraries()
        runtime = self.manifest["runtime"]
        self.device_report = check_device(self.torch, runtime)
        self.device = self.torch.device(runtime["device"])
        self.torch.set_num_threads(runtime["threads"])
        base = str(_base(artifact_root, runtime["base_directory"]))
        self.tokenizer = transformers.AutoTokenizer.from_pretrained(
            base, local_files_only=True, trust_remote_code=False
        )
        if (
            chat_protocol.template_digest(self.tokenizer.get_chat_template())
            != runtime["chat_template_sha256"]
        ):
            raise ValueError("loaded tokenizer chat template differs")
        if {
            name: getattr(self.tokenizer, name)
            for name in runtime["tokenizer_special_ids"]
        } != runtime["tokenizer_special_ids"]:
            raise ValueError("loaded tokenizer special token identifiers differ")
        dtype = getattr(self.torch, runtime["dtype"])
        self.model = transformers.AutoModelForCausalLM.from_pretrained(
            base,
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
            torch_dtype=dtype,
            attn_implementation="eager",
        ).to(self.device)
        for parameter in self.model.parameters():
            if parameter.device != self.device or (
                parameter.is_floating_point() and parameter.dtype != dtype
            ):
                raise ValueError(
                    "loaded parameters differ from the selected device/dtype"
                )
        self.model.eval()
        self.model.requires_grad_(False)
        self.generation = transformers.GenerationConfig(**runtime["generation"])
        self.generation_digest = data.digest(self.generation.to_dict())
        self.closed = False

    def predict(self, record):
        if self.closed or data.digest(self.manifest) != self.model_digest:
            raise ValueError("predictor is closed or its manifest was changed")
        if data.digest(self.generation.to_dict()) != self.generation_digest:
            raise ValueError("loaded generation configuration changed")
        started_at, started = time.time_ns(), time.perf_counter()
        runtime = self.manifest["runtime"]
        # Whitelist only model-visible task input/history. final_answer,
        # trajectory, verifier parameters and reference receipts are never read.
        task = record["task"]
        prompt = task["input"]
        messages = chat_protocol.inference_messages(prompt, task.get("messages"))
        rendered = chat_protocol.render_prompt(self.tokenizer, prompt, messages)
        if len(rendered.encode()) > 131072:
            raise ValueError("rendered prompt exceeds the hard byte bound")
        encoded = self.tokenizer(
            rendered, return_tensors="pt", add_special_tokens=False
        )
        count = encoded["input_ids"].shape[1]
        if not 0 < count <= runtime["max_input_tokens"]:
            raise ValueError(
                "inference context exceeds frozen token budget; no truncation"
            )
        encoded = {key: value.to(self.device) for key, value in encoded.items()}
        with self.torch.inference_mode():
            output = self.model.generate(**encoded, generation_config=self.generation)
        produced = output[0, count:]
        ids = produced.tolist()
        answer = self.tokenizer.decode(
            produced, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )
        eos = runtime["generation"]["eos_token_id"]
        eos = eos if isinstance(eos, list) else [eos]
        stopped = any(identifier in eos for identifier in ids)
        capped = len(ids) >= runtime["max_new_tokens"] and not stopped
        return {
            "answer": answer,
            "output_token_ids": ids,
            "loaded_model_digest": self.model_digest,
            "generation_config_sha256": self.generation_digest,
            "input_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "messages_sha256": data.digest(messages),
            "rendered_input_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
            "rendered_prompt_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
            "message_protocol": chat_protocol.NATIVE,
            "input_tokens": count,
            "output_tokens": len(ids),
            "eos_seen": stopped,
            "hit_output_limit": capped,
            "finish_reason": (
                "eos_token" if stopped else "max_new_tokens" if capped else "other"
            ),
            "max_new_tokens": runtime["max_new_tokens"],
            "started_at_ns": started_at,
            "completed_at_ns": time.time_ns(),
            "wall_seconds": time.perf_counter() - started,
            "time_scope": (
                "render, tokenize, generate and decode; excludes model load and verifier"
            ),
            "device": self.device_report,
            "backend_versions": self.manifest["backend_versions"],
            "pid": os.getpid(),
            "external_effect_executed": False,
        }

    def close(self):
        self.model, self.tokenizer, self.closed = None, None, True
        gc.collect()


def load_predictor(manifest, artifact_root):
    return Predictor(manifest, artifact_root)
