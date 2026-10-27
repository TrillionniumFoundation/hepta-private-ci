"""Checked frozen MiniLM features with explicit pooling and full base cost."""

import hashlib
import json
from pathlib import Path
import time

import numpy as np


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


class MiniLMEncoder:
    """Frozen pretrained transformer; cell adapters are trained separately.

    ONNX exports token features. This class applies attention-mask mean pooling
    and L2 normalization, as specified by the upstream Sentence Transformers model.
    It has no query cache and never consumes memory targets or source events.
    Each text is tokenized and inferred independently: quantized activations must
    not acquire a different scale merely because other requests share a batch.
    """

    def __init__(self, directory, *, expected_source_digest=None, threads=1):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        started = time.perf_counter()
        requested_directory = Path(directory).absolute()
        if requested_directory.is_symlink():
            raise ValueError("symlinked pretrained directory")
        directory = requested_directory.resolve(strict=True)
        source_path = directory / "source.json"
        if source_path.is_symlink() or source_path.stat().st_size > 65536:
            raise ValueError("invalid encoder source manifest")
        self.source = json.loads(source_path.read_bytes())
        if self.source.get("schema") != "memory-cell-v2.pretrained-source.v1":
            raise ValueError("unknown pretrained source format")
        model_file = self.source.get("model_file")
        files = self.source.get("files")
        if (
            not isinstance(files, dict)
            or not 2 <= len(files) <= 32
            or not isinstance(model_file, str)
            or model_file not in files
            or "tokenizer.json" not in files
            or self.source.get("dimension") != 384
            or self.source.get("base_is_frozen") is not True
        ):
            raise ValueError("incomplete pretrained file bindings")
        self.source_digest = sha(canonical(self.source))
        if (
            expected_source_digest is not None
            and self.source_digest != expected_source_digest
        ):
            raise ValueError("pretrained source identity mismatch")
        if type(threads) is not int or not 1 <= threads <= 16:
            raise ValueError("invalid CPU thread bound")
        self.base_bytes = source_path.stat().st_size
        payloads = {}
        for relative, info in files.items():
            relative_path = Path(relative)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise ValueError("invalid pretrained relative path")
            path = directory / relative
            if any(
                (directory / part).is_symlink()
                for part in (relative_path, *relative_path.parents)
            ) or not path.resolve(strict=True).is_relative_to(directory):
                raise ValueError("pretrained file escapes base directory")
            if (
                type(info["bytes"]) is not int
                or not 0 < info["bytes"] <= 128 * 1024 * 1024
            ):
                raise ValueError("invalid pretrained file bound")
            if not path.is_file() or path.stat().st_size != info["bytes"]:
                raise ValueError("pretrained file size differs from its binding")
            payload = path.read_bytes()
            if len(payload) != info["bytes"] or sha(payload) != info["sha256"]:
                raise ValueError("pretrained file identity mismatch")
            if relative in {model_file, "tokenizer.json"}:
                payloads[relative] = payload
            self.base_bytes += info["bytes"]
        # Native runtimes receive the exact bytes just checked, avoiding a second
        # unobserved path read and a hash/load race.
        self.tokenizer = Tokenizer.from_str(payloads["tokenizer.json"].decode("utf-8"))
        self.tokenizer.enable_truncation(max_length=128)
        self.tokenizer.no_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            payloads[model_file],
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self.inputs = tuple(value.name for value in self.session.get_inputs())
        if set(self.inputs) != {"input_ids", "attention_mask", "token_type_ids"}:
            raise ValueError("unexpected pretrained input contract")
        self.dim = 384
        self.load_seconds = time.perf_counter() - started

    def manifest(self):
        return {
            "schema": "memory-cell-v2.encoder.v1",
            "source_digest": self.source_digest,
            "dimension": self.dim,
            "max_wordpieces": 128,
            "pooling": "masked-mean-l2",
            "model_file": self.source["model_file"],
            "base_frozen": True,
            "native_batch_size": 1,
            "inference_batch_contract": "per-text-tokenization-and-native-batch1;caller-grouping-invariant",
        }

    @property
    def digest(self):
        return sha(canonical(self.manifest()))

    def encode(self, texts, batch_size=32):
        """Accept caller batching for compatibility; native execution is per text."""
        if not isinstance(texts, (list, tuple)) or len(texts) > 65536:
            raise ValueError("bounded text sequence required")
        if type(batch_size) is not int or not 1 <= batch_size <= 128:
            raise ValueError("invalid batch size")
        if any(
            not isinstance(t, str) or not t.strip() or len(t) > 16384 for t in texts
        ):
            raise ValueError("invalid bounded text")
        result = []
        for text in texts:
            encoded = self.tokenizer.encode(text)
            feed = {
                "input_ids": np.asarray([encoded.ids], dtype=np.int64),
                "attention_mask": np.asarray([encoded.attention_mask], dtype=np.int64),
                "token_type_ids": np.asarray([encoded.type_ids], dtype=np.int64),
            }
            tokens = self.session.run(None, feed)[0]
            if (
                tokens.ndim != 3
                or tokens.shape[:2] != feed["input_ids"].shape
                or tokens.shape[2] != self.dim
            ):
                raise ValueError("unexpected pretrained output contract")
            mask = feed["attention_mask"][..., None]
            pooled = (tokens * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1)
            pooled /= np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
            if not np.isfinite(pooled).all():
                raise ValueError("nonfinite pretrained features")
            result.append(pooled.astype(np.float64))
        return (
            np.concatenate(result)
            if result
            else np.empty((0, self.dim), dtype=np.float64)
        )
