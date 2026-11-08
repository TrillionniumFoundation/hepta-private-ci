"""Optional, bounded Apple MLX Llama hidden-feature provider for engineering probes.

This module loads one already downloaded, hash-verified model. It does not fetch
models, start a network service, recommend a production model, or measure the
memory of hypothetical replicated models. MLX's memory limit is a guideline;
it is not an operating-system RSS limit.
"""

import hashlib
import importlib.metadata
import inspect
import json
import platform
import re
import threading
import time
from pathlib import Path

import numpy as np

from .semantic import CallableFeatureBackend, SemanticBinding


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def package_versions():
    versions = {}
    for name in ("mlx", "mlx-lm", "numpy", "transformers", "tokenizers", "huggingface-hub", "safetensors"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def verified_artifacts(directory, receipt):
    """Rehash the exact bounded local artifact set before loading native code."""
    allowed = {".gitattributes", "README.md", "config.json", "generation_config.json", "merges.txt",
               "model.safetensors", "model.safetensors.index.json", "special_tokens_map.json",
               "tokenizer.json", "tokenizer_config.json", "vocab.json"}
    if (receipt.get("status") != "success" or not re.fullmatch(r"[0-9a-f]{40}", receipt.get("revision", ""))
            or not receipt.get("model_id", "").startswith("mlx-community/")):
        raise ValueError("a completed, pinned public MLX Community download receipt is required")
    records = receipt.get("artifacts", [])
    names = [record.get("name") for record in records]
    if (not 1 <= len(records) <= len(allowed) or len(set(names)) != len(names)
            or not set(names) <= allowed or not {"config.json", "model.safetensors", "tokenizer.json"} <= set(names)):
        raise ValueError("unexpected, duplicate or missing model artifacts")
    total = 0
    for record in records:
        size, expected = record.get("bytes"), record.get("sha256", "")
        if type(size) is not int or size < 0 or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("invalid artifact size or SHA-256")
        total += size
    if not 0 < total <= 300_000_000 or total != receipt.get("total_downloaded_bytes"):
        raise ValueError("model exceeds the fixed 300 MB artifact cap or receipt differs")
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("model path must be a regular local directory")
    if {p.name for p in directory.iterdir()} != set(names):
        raise ValueError("local model directory differs from the verified artifact set")
    for record in records:
        path = directory / record["name"]
        if (path.is_symlink() or not path.is_file() or path.stat().st_size != record["bytes"]
                or file_sha256(path) != record["sha256"]):
            raise ValueError("model artifact checksum differs: " + record["name"])
    return {record["name"]: record["sha256"] for record in records}


class MLXLlamaFeatureProvider:
    """One frozen Llama, serialized callbacks, full transformer plus last-token pool."""

    def __init__(self, model_directory, download_receipt, *, memory_limit_bytes=384 * 1048576,
                 cache_limit_bytes=16 * 1048576, max_batch_items=8, max_sequence_tokens=64,
                 max_batch_tokens=512):
        limits = (memory_limit_bytes, cache_limit_bytes, max_batch_items, max_sequence_tokens, max_batch_tokens)
        caps = (512 * 1048576, 32 * 1048576, 8, 128, 512)
        if any(type(v) is not int or not 1 <= v <= cap for v, cap in zip(limits, caps)):
            raise ValueError("provider resource bounds exceed the engineering envelope")
        receipt = json.loads(Path(download_receipt).read_text())
        artifacts = verified_artifacts(model_directory, receipt)
        config = json.loads((Path(model_directory) / "config.json").read_text())
        if config.get("model_type") != "llama" or config.get("architectures") != ["LlamaForCausalLM"]:
            raise ValueError("this provider only accepts the installed Llama implementation")
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            raise RuntimeError("the optional MLX serving probe requires Apple Silicon macOS")
        import mlx.core as mx
        import mlx_lm
        from mlx.utils import tree_flatten

        self._mx, self._flatten = mx, tree_flatten
        self._lock = threading.RLock()
        self._limits = limits
        self.events, self.fingerprint_measurements = [], []
        self._last_features = None
        self.load_count = 0
        mx.set_default_device(mx.gpu)
        mx.set_memory_limit(memory_limit_bytes)
        mx.set_cache_limit(cache_limit_bytes)
        mx.set_wired_limit(0)
        mx.reset_peak_memory()
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        self._model, self._tokenizer, loaded = mlx_lm.load(
            str(Path(model_directory).resolve()), lazy=False, return_config=True,
            tokenizer_config={"local_files_only": True, "trust_remote_code": False})
        self.load_count += 1
        self._model.freeze()
        self._model.eval()
        mx.synchronize()
        load_cost = dict(wall_ns=time.perf_counter_ns() - wall, process_cpu_ns=time.process_time_ns() - cpu,
                         **self.memory_snapshot())
        if (type(self._model).__module__ != "mlx_lm.models.llama"
                or loaded["model_type"] != "llama" or len(self._model.layers) != config["num_hidden_layers"]
                or tree_flatten(self._model.trainable_parameters())):
            raise ValueError("loaded model implementation, layer count or frozen state differs")
        self.feature_dim = config["hidden_size"]
        self.layer_count = len(self._model.layers)
        self._pad_id = config.get("pad_token_id", config["eos_token_id"])
        self._base_fingerprint = self.fingerprint()
        installed = {name: file_sha256(inspect.getfile(module)) for name, module in
                     (("mlx_lm", mlx_lm), ("llama", inspect.getmodule(type(self._model))),
                      ("load", inspect.getmodule(mlx_lm.load)))}
        policy = dict(forward="model.model(input_ids, cache=None); all transformer layers and final RMSNorm",
                      pooling="last valid token", padding="right; causal suffix cannot change earlier tokens",
                      add_special_tokens=False, normalization="float64 L2; denominator floor 1e-12",
                      maximum_rows=max_batch_items, maximum_sequence_tokens=max_sequence_tokens,
                      maximum_padded_batch_tokens=max_batch_tokens)
        versions = package_versions()
        tokenizer_files = {k: v for k, v in artifacts.items()
                           if k in {"tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "merges.txt", "vocab.json"}}
        self.binding = SemanticBinding(
            self._base_fingerprint,
            json_digest(dict(repository=receipt["model_id"], revision=receipt["revision"], artifacts=artifacts)),
            json_digest(dict(policy=policy, provider_source=file_sha256(__file__), installed_sources=installed)),
            json_digest(tokenizer_files),
            json_digest(dict(packages=versions, quantization=config.get("quantization"),
                             device=mx.device_info(), output_dtype="float64", transformer_device="Metal GPU")))
        parameters = tree_flatten(self._model.parameters())
        self.info = dict(model_id=receipt["model_id"], revision=receipt["revision"], artifacts=artifacts,
                         packages=versions, device=mx.device_info(), load_cost=load_cost,
                         feature_dim=self.feature_dim, transformer_layers=self.layer_count, policy=policy,
                         installed_sources=installed,
                         parameter_logical_bytes=sum(a.nbytes for _, a in parameters),
                         parameter_tensor_count=len(parameters), limits=dict(zip(
                             ("mlx_memory_guideline_bytes", "mlx_cache_limit_bytes", "batch_items", "sequence_tokens", "padded_batch_tokens"), limits)),
                         memory_limit_scope="process-local MLX allocator guideline; not strict RSS enforcement",
                         fingerprint_scope="names, dtype, shape and all loaded parameter values; bf16 cast losslessly to float32")
        self.backend = CallableFeatureBackend(self.binding, self.feature_dim, self.encode_batch, self.fingerprint)

    def memory_snapshot(self):
        """MLX allocator counters, separate from process RSS and host-array accounting."""
        return dict(mlx_peak_active_bytes=self._mx.get_peak_memory(),
                    mlx_active_bytes=self._mx.get_active_memory(), mlx_cached_bytes=self._mx.get_cache_memory(),
                    measurement_scope="MLX Metal allocator; excludes other processes and non-MLX allocations")

    def fingerprint(self):
        with self._lock:
            wall, cpu = time.perf_counter_ns(), time.process_time_ns()
            digest = hashlib.sha256(b"hepta-mlx-parameter-values-v1\0")
            for name, value in sorted(self._flatten(self._model.parameters())):
                header = json.dumps([name, str(value.dtype), list(value.shape)], separators=(",", ":")).encode()
                material = value.astype(self._mx.float32) if "bfloat16" in str(value.dtype) else value
                raw = np.array(material).tobytes(order="C")
                digest.update(len(header).to_bytes(8, "big")); digest.update(header)
                digest.update(len(raw).to_bytes(8, "big")); digest.update(raw)
            if len(self.fingerprint_measurements) >= 256:
                raise ValueError("fingerprint call envelope exhausted")
            self.fingerprint_measurements.append(dict(wall_ns=time.perf_counter_ns() - wall,
                                                      process_cpu_ns=time.process_time_ns() - cpu))
            return digest.hexdigest()

    def last_features(self):
        with self._lock:
            return None if self._last_features is None else self._last_features.copy()

    def encode_batch(self, inputs):
        with self._lock:
            if len(self.events) >= 128:
                raise ValueError("provider call envelope exhausted")
            wall, cpu = time.perf_counter_ns(), time.process_time_ns()
            event = dict(call_index=len(self.events), status="started", batch_items=len(inputs))
            self.events.append(event)
            try:
                if not 1 <= len(inputs) <= self._limits[2] or any(not isinstance(x, str) or len(x.encode()) > 4096 for x in inputs):
                    raise ValueError("provider text/item cap exceeded")
                tokens = [self._tokenizer.encode(value, add_special_tokens=False) for value in inputs]
                lengths = [len(value) for value in tokens]
                if min(lengths) < 1 or max(lengths) > self._limits[3] or len(tokens) * max(lengths) > self._limits[4]:
                    raise ValueError("provider sequence/padded-token cap exceeded")
                padded = np.full((len(tokens), max(lengths)), self._pad_id, dtype=np.int32)
                for row, values in enumerate(tokens):
                    padded[row, :len(values)] = values
                event.update(input_sha256=json_digest(list(inputs)), token_ids_sha256=json_digest(tokens),
                             token_lengths=lengths, padded_tokens=int(padded.size))
                # Calling the inner Llama model executes every transformer block
                # and final RMSNorm; this is deliberately not embed_tokens().
                hidden = self._model.model(self._mx.array(padded), cache=None)
                pooled = self._mx.stack([hidden[row, length - 1] for row, length in enumerate(lengths)])
                pooled = pooled.astype(self._mx.float32)
                self._mx.eval(pooled)
                self._mx.synchronize()
                features = np.asarray(pooled, dtype=np.float64)
                features = features / np.maximum(np.linalg.norm(features, axis=1, keepdims=True), 1e-12)
                if features.shape != (len(inputs), self.feature_dim) or not np.isfinite(features).all():
                    raise ValueError("invalid full-transformer features")
                memory = self.memory_snapshot()
                if memory["mlx_peak_active_bytes"] > self._limits[0]:
                    raise MemoryError("observed MLX active peak exceeded the probe envelope")
                self._last_features = features.copy()
                event.update(status="completed", transformer_forwards=1, transformer_layers=self.layer_count,
                             feature_sha256=hashlib.sha256(features.tobytes()).hexdigest(), **memory)
                return features
            except Exception as exc:
                event.update(status="failed", error_type=type(exc).__name__, error=str(exc))
                raise
            finally:
                event.update(wall_ns=time.perf_counter_ns() - wall, process_cpu_ns=time.process_time_ns() - cpu)
