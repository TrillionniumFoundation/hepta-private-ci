"""Pinned multilingual MiniLM ONNX features, with unchanged entity/date content.

This is an inference-only base.  Training happens in tensor_cell.py, after the
384-dimensional representation.  Every native call uses batch one so dynamic
quantization cannot make a query representation depend on its batch companions.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np


MODEL_SHA256 = "98a01d88b7de996cdea58c32ca71208c09968d143798814b2ea09d3439dc334f"
REPOSITORY = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
PINNED_FILES = {
    "1_Pooling/config.json": (190, "4be450dde3b0273bb9787637cfbd28fe04a7ba6ab9d36ac48e92b11e350ffc23"),
    "config.json": (645, "6300193cb75e01cf80c96decef7187dfb33094d97cc1490b7ead6ff134476e4e"),
    "onnx/model_quint8_avx2.onnx": (118453870, MODEL_SHA256),
    "special_tokens_map.json": (239, "378eb3bf733eb16e65792d7e3fda5b8a4631387ca04d2015199c4d4f22ae554d"),
    "tokenizer.json": (9081518, "2c3387be76557bd40970cec13153b3bbf80407865484b209e655e5e4729076b8"),
    "tokenizer_config.json": (526, "5036ea374ffedd706e3bef33e2e0d6953cb868ef8a490e76e32ba0faa37a6b9b"),
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class PinnedMiniLMEncoder:
    """Verify all preprocessing/model bytes before creating the ONNX session."""

    def __init__(self, model_dir, *, max_tokens=128, threads=1, expected_sha=MODEL_SHA256):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        started, cpu_started = time.perf_counter(), time.process_time()
        if expected_sha != MODEL_SHA256:
            raise ValueError("requested model does not match the pinned encoder")
        if type(max_tokens) is not int or not 8 <= max_tokens <= 512:
            raise ValueError("max_tokens must be in 8..512")
        if type(threads) is not int or not 1 <= threads <= 16:
            raise ValueError("CPU threads must be in 1..16")
        root = Path(model_dir).absolute()
        self.base_bytes = 0
        for relative, (count, sha) in PINNED_FILES.items():
            path = root / relative
            if any(p.is_symlink() for p in (path, *path.parents)):
                raise ValueError("symlinked pretrained artifact")
            if path.stat().st_size != count:
                raise ValueError(f"pretrained artifact length mismatch: {relative}")
            with path.open("rb") as source:
                observed = hashlib.file_digest(source, "sha256").hexdigest()
            if observed != sha:
                raise ValueError(f"pretrained artifact digest mismatch: {relative}")
            self.base_bytes += count
        self.tokenizer = Tokenizer.from_file(str(root / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=max_tokens)
        self.tokenizer.no_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(root / "onnx/model_quint8_avx2.onnx"),
                                            sess_options=options, providers=["CPUExecutionProvider"])
        if {entry.name for entry in self.session.get_inputs()} != {"input_ids", "attention_mask", "token_type_ids"}:
            raise ValueError("unexpected pretrained model input contract")
        self.identity = {
            "schema": "memory-adapter.encoder.v1", "repo": REPOSITORY, "revision": REVISION,
            "files": {name: {"bytes": size, "sha256": sha} for name, (size, sha) in PINNED_FILES.items()},
            "dimension": 384, "max_tokens": max_tokens, "native_batch": 1,
            "normalization": "pinned tokenizer only; no entity/date masking",
            "pooling": "attention-mask mean then L2", "dtype": "float32", "frozen": True,
        }
        self.base_encoder_sha = hashlib.sha256(canonical(self.identity)).hexdigest()
        self.digest = self.base_encoder_sha
        self.load_seconds = time.perf_counter() - started
        self.load_cpu_seconds = time.process_time() - cpu_started
        self.calls = self.tokens = self.truncated_texts = 0
        self.seconds = self.cpu_seconds = 0.0

    def encode(self, texts, batch_size=1):
        if self.session is None:
            raise RuntimeError("encoder has been released")
        if batch_size != 1:
            raise ValueError("pinned inference requires native batch one")
        if not isinstance(texts, (list, tuple)) or len(texts) > 16384:
            raise ValueError("a bounded text sequence is required")
        started, cpu_started = time.perf_counter(), time.process_time()
        vectors = []
        for text in texts:
            if not isinstance(text, str) or not text.strip() or len(text) > 65536:
                raise ValueError("input text must contain 1..65536 characters")
            encoded = self.tokenizer.encode(text)
            feed = {"input_ids": np.asarray([encoded.ids], dtype=np.int64),
                    "attention_mask": np.asarray([encoded.attention_mask], dtype=np.int64),
                    "token_type_ids": np.asarray([encoded.type_ids], dtype=np.int64)}
            hidden = self.session.run(None, feed)[0]
            if hidden.shape != (1, len(encoded.ids), 384):
                raise ValueError("unexpected pretrained hidden-state shape")
            mask = feed["attention_mask"][..., None].astype(np.float32)
            pooled = (hidden.astype(np.float32) * mask).sum(1) / np.maximum(mask.sum(1), 1.0)
            pooled /= np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
            if not np.isfinite(pooled).all():
                raise ValueError("nonfinite pretrained embedding")
            vectors.append(pooled[0])
            self.calls += 1
            self.tokens += len(encoded.ids)
            self.truncated_texts += bool(encoded.overflowing)
        self.seconds += time.perf_counter() - started
        self.cpu_seconds += time.process_time() - cpu_started
        return np.asarray(vectors, dtype=np.float32).reshape(-1, 384)

    def receipt(self):
        return {"identity": self.identity, "base_encoder_sha": self.base_encoder_sha,
                "model_sha256": MODEL_SHA256, "base_bytes": self.base_bytes,
                "load_wall_seconds": self.load_seconds, "load_cpu_seconds": self.load_cpu_seconds,
                "inference_calls": self.calls, "tokens": self.tokens, "truncated_texts": self.truncated_texts,
                "inference_wall_seconds": self.seconds, "inference_cpu_seconds": self.cpu_seconds}

    def close(self):
        self.session = None
        self.tokenizer = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--input", type=Path, required=True, help="JSON array of texts")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    encoder = PinnedMiniLMEncoder(args.model_dir)
    vectors = encoder.encode(json.loads(args.input.read_text()))
    np.savez_compressed(args.output, features=vectors)
    args.receipt.write_bytes(canonical(encoder.receipt()))


if __name__ == "__main__":
    main()
