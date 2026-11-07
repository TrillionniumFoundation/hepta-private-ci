"""Frozen pretrained sentence encoder, not a generative language model."""

import hashlib
import importlib.metadata
import json
from pathlib import Path
import time

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from download_model import FILES, MODEL_ID, REVISION, file_identity


class FrozenEncoder:
    """Official MiniLM ONNX + masked mean pooling + unit normalization.

    Every encode is actual CPU inference. No hash-vector fallback or silent
    truncation: the statistics count pre/post truncation tokens including
    special tokens, padding workload, truncated examples, and elapsed time.
    """

    def __init__(self, model_dir, batch_size=32, max_length=256, threads=1):
        started = time.perf_counter()
        if batch_size < 1 or not 2 <= max_length <= 256 or threads < 1:
            raise ValueError("Invalid encoder batch/sequence/thread limits")
        self.model_dir = Path(model_dir)
        source = json.loads((self.model_dir / "manifest.json").read_text())
        if source.get("model_id") != MODEL_ID or source.get("revision") != REVISION:
            raise ValueError("Unexpected pretrained model identity")
        for name, identity in FILES.items():
            checked = file_identity(self.model_dir / name, *identity)
            if checked != source["files"][name]:
                raise ValueError(f"Encoder manifest mismatch: {name}")
        self.batch_size, self.max_length = batch_size, max_length
        self._counter = Tokenizer.from_file(str(self.model_dir / "tokenizer.json"))
        self._counter.no_padding()
        self._counter.no_truncation()
        self._tokenizer = Tokenizer.from_file(str(self.model_dir / "tokenizer.json"))
        self._tokenizer.enable_truncation(max_length=max_length)
        self._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self._session = ort.InferenceSession(str(self.model_dir / "onnx/model.onnx"), sess_options=options, providers=["CPUExecutionProvider"])
        self.manifest = {
            **source, "backend": "onnxruntime-cpu", "pooling": "attention-masked-mean-then-l2",
            "max_length": max_length, "embedding_dimension": 384,
            "intra_op_threads": threads, "inter_op_threads": 1,
            "packages": {name: importlib.metadata.version(name) for name in ("numpy", "onnxruntime", "tokenizers")},
        }
        self.manifest_hash = hashlib.sha256(json.dumps(self.manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.stats = {"calls": 0, "examples": 0, "input_tokens": 0, "encoded_tokens": 0, "padded_tokens": 0, "truncated_examples": 0, "encode_seconds": 0.0, "load_seconds": time.perf_counter() - started}

    def encode(self, texts):
        texts = list(texts)
        if any(not isinstance(text, str) for text in texts):
            raise TypeError("Encoder inputs must be strings")
        started = time.perf_counter()
        output = []
        counts = {"examples": len(texts), "input_tokens": 0, "encoded_tokens": 0, "padded_tokens": 0, "truncated_examples": 0}
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            untruncated = self._counter.encode_batch(batch)
            counts["input_tokens"] += sum(len(item.ids) for item in untruncated)
            counts["truncated_examples"] += sum(len(item.ids) > self.max_length for item in untruncated)
            encoded = self._tokenizer.encode_batch(batch)
            available = {
                "input_ids": np.asarray([item.ids for item in encoded], dtype=np.int64),
                "attention_mask": np.asarray([item.attention_mask for item in encoded], dtype=np.int64),
                "token_type_ids": np.asarray([item.type_ids for item in encoded], dtype=np.int64),
            }
            feeds = {item.name: available[item.name] for item in self._session.get_inputs()}
            hidden = self._session.run(None, feeds)[0]
            if hidden.ndim != 3 or hidden.shape[2] != 384:
                raise ValueError("Unexpected encoder output contract")
            mask = available["attention_mask"].astype(np.float32)
            pooled = np.sum(hidden * mask[:, :, None], axis=1) / np.maximum(mask.sum(axis=1, keepdims=True), 1)
            pooled /= np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
            if not np.isfinite(pooled).all():
                raise ValueError("Non-finite pretrained embedding")
            output.append(pooled.astype(np.float32))
            counts["encoded_tokens"] += int(mask.sum())
            counts["padded_tokens"] += int(mask.size)
        for key, value in counts.items():
            self.stats[key] += value
        self.stats["calls"] += 1
        self.stats["encode_seconds"] += time.perf_counter() - started
        return np.concatenate(output, axis=0) if output else np.empty((0, 384), dtype=np.float32)
