"""Frozen, identity-bound MiniLM features; each native call has batch size one."""

import hashlib
import json
from pathlib import Path
import re
import time
import unicodedata

import numpy as np


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def multilingual_source():
    repo = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    revision = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
    bindings = {
        "1_Pooling/config.json": (190, "4be450dde3b0273bb9787637cfbd28fe04a7ba6ab9d36ac48e92b11e350ffc23"),
        "config.json": (645, "6300193cb75e01cf80c96decef7187dfb33094d97cc1490b7ead6ff134476e4e"),
        "onnx/model_quint8_avx2.onnx": (118453870, "98a01d88b7de996cdea58c32ca71208c09968d143798814b2ea09d3439dc334f"),
        "special_tokens_map.json": (239, "378eb3bf733eb16e65792d7e3fda5b8a4631387ca04d2015199c4d4f22ae554d"),
        "tokenizer.json": (9081518, "2c3387be76557bd40970cec13153b3bbf80407865484b209e655e5e4729076b8"),
        "tokenizer_config.json": (526, "5036ea374ffedd706e3bef33e2e0d6953cb868ef8a490e76e32ba0faa37a6b9b"),
    }
    return {
        "schema": "memory-cell-v6.pretrained-source.v1",
        "repo": repo,
        "revision": revision,
        "base_is_frozen": True,
        "dimension": 384,
        "model_file": "onnx/model_quint8_avx2.onnx",
        "pooling": "attention-mask mean pooling then L2 normalization",
        "files": {
            name: {"bytes": count, "sha256": sha, "url": f"https://huggingface.co/{repo}/resolve/{revision}/{name}"}
            for name, (count, sha) in bindings.items()
        },
    }


def normalize_request(text, entity=None, at=None, since=None):
    if not isinstance(text, str) or not text.strip() or len(text) > 4096:
        raise ValueError("request text must contain 1..4096 characters")
    text = unicodedata.normalize("NFKC", text).casefold()
    if entity:
        entity_text = unicodedata.normalize("NFKC", str(entity)).casefold()
        left = r"(?<![a-z0-9_])" if re.match(r"[a-z0-9_]", entity_text) else ""
        right = r"(?![a-z0-9_])" if re.search(r"[a-z0-9_]$", entity_text) else ""
        text = re.sub(left + re.escape(entity_text) + right, "entity", text)
    # Only declared slots and syntactic dates are removed; no target intent enters.
    for slot in (at, since):
        if slot is not None:
            text = text.replace(str(slot).casefold(), "date")
    text = re.sub(r"\b\d{4}-\d{2}(?:-\d{2})?\b", "date", text)
    return " ".join(text.split())


class MiniLMEncoder:
    """Inference-only shared base, verified against the repository's pinned source."""

    def __init__(self, directory, threads=1):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        started = time.perf_counter()
        root = Path(directory).absolute()
        if any(p.is_symlink() for p in (root, *root.parents)):
            raise ValueError("symlinked encoder directory")
        expected_path = Path(__file__).resolve().parents[2] / "memory-cell-v2" / "MODEL_SOURCE.json"
        english = json.loads(expected_path.read_bytes())
        source_path = root / "source.json"
        if source_path.is_symlink() or not source_path.is_file() or source_path.stat().st_size > 65536:
            raise ValueError("invalid bounded encoder source")
        source = json.loads(source_path.read_bytes())
        expected = multilingual_source() if source == multilingual_source() else english
        if source != expected:
            raise ValueError("base differs from the pinned MiniLM source")
        if type(threads) is not int or not 1 <= threads <= 16:
            raise ValueError("CPU threads outside 1..16")
        payloads = {}
        self.base_bytes = (root / "source.json").stat().st_size
        for name, binding in expected["files"].items():
            path = root / name
            if any(p.is_symlink() for p in (path, *path.parents)):
                raise ValueError("symlinked encoder artifact")
            raw = path.read_bytes()
            if len(raw) != binding["bytes"] or digest(raw) != binding["sha256"]:
                raise ValueError("encoder bytes fail pinned identity")
            self.base_bytes += len(raw)
            if name in {"tokenizer.json", expected["model_file"]}:
                payloads[name] = raw
        self.tokenizer = Tokenizer.from_str(payloads["tokenizer.json"].decode())
        self.tokenizer.enable_truncation(max_length=128)
        self.tokenizer.no_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            payloads[expected["model_file"]], sess_options=options, providers=["CPUExecutionProvider"]
        )
        if {x.name for x in self.session.get_inputs()} != {"input_ids", "attention_mask", "token_type_ids"}:
            raise ValueError("unexpected model inputs")
        self.identity = {
            "source_sha256": digest(canonical(expected)),
            "dimension": 384,
            "pooling": "masked-mean-l2",
            "native_batch": 1,
            "max_tokens": 128,
        }
        self.digest = digest(canonical(self.identity))
        self.load_seconds = time.perf_counter() - started
        self.calls = 0
        self.seconds = 0.0

    def encode(self, texts):
        if not isinstance(texts, (list, tuple)) or len(texts) > 16384:
            raise ValueError("bounded text list required")
        start = time.perf_counter()
        result = []
        for text in texts:
            item = self.tokenizer.encode(normalize_request(text))
            feed = {
                "input_ids": np.asarray([item.ids], dtype=np.int64),
                "attention_mask": np.asarray([item.attention_mask], dtype=np.int64),
                "token_type_ids": np.asarray([item.type_ids], dtype=np.int64),
            }
            tokens = self.session.run(None, feed)[0]
            if tokens.shape != (1, len(item.ids), 384):
                raise ValueError("unexpected model output")
            mask = feed["attention_mask"][..., None]
            pooled = (tokens * mask).sum(1) / np.maximum(mask.sum(1), 1)
            pooled /= np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
            if not np.isfinite(pooled).all():
                raise ValueError("nonfinite embedding")
            result.append(pooled[0])
            self.calls += 1
        self.seconds += time.perf_counter() - start
        return np.asarray(result, dtype=np.float64).reshape(-1, 384)
