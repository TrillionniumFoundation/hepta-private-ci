"""Read-only MiniLM-BERT weight execution without the Transformers runtime.

Research reference for the *pinned* all-MiniLM-L6-v2 snapshot. It supports an
explicit printable-ASCII/whitespace subset, and must pass HF byte/token/vector
parity in the hosted pinned environment before substituting for pretrained.Encoder.
No model is trained, installed or promoted here. Output has no fact authority.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re

import numpy as np
import torch
import torch.nn.functional as F
from safetensors.torch import load_file


REGISTERED_ENCODER_IDENTITY = "5afecdd6098fec07380bc10a30fd8debcffcd147274b3ffd18143f1fa86dc12a"

MODEL_FILES = frozenset({
    "config.json", "model.safetensors", "tokenizer.json",
    "tokenizer_config.json", "special_tokens_map.json", "vocab.txt",
})
# Restricted closed-world architecture; reject incompatible weights rather than
# silently running an incorrectly interpreted Transformer.
LAYERS, HIDDEN, HEADS, INTERMEDIATE, VOCAB = 6, 384, 12, 1536, 30522
MAX_BATCH, MAX_TOKENS = 16, 256
MAX_TEXT_BYTES = 4096
SPECIAL_TOKENS = ("[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]")


def _json_bytes(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate metadata key")
            result[key] = value
        return result

    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite metadata")))


def _digest_json(data):
    return hashlib.sha256(json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def inventory(folder, *, expected=None):
    """Reject symlinks/extra weights; identity matches pretrained.file_inventory.

    An expected closed-world sha256 inventory may be passed by a trusted caller.
    The computed digest alone attests bytes, not the trusted publisher identity.
    """
    folder = Path(folder)
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError("regular pinned encoder directory required")
    files = {p.name for p in folder.iterdir()}
    if files != MODEL_FILES:
        raise ValueError("unexpected or missing pretrained files")
    info = {}
    for name in sorted(files):
        path = folder / name
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 120_000_000:
            raise ValueError("unsafe or unbounded pretrained file")
        h = hashlib.sha256()
        with path.open("rb") as reader:
            for block in iter(lambda: reader.read(1024 * 1024), b""):
                h.update(block)
        info[name] = {"sha256": h.hexdigest(), "bytes": path.stat().st_size}
    if expected is not None and info != expected:
        raise ValueError("pretrained file inventory mismatch")
    return info, _digest_json(info)



def stage_native_view(publisher_directory, native_directory):
    """Create a byte-pinned six-file native view of an already-verified publisher.

    The publisher is allowed to contain ancillary model-card/config files, but
    only the six registered bytes are copied into a *new* closed-world directory.
    The original publisher remains available for the Transformers reference.
    No changed weights, unknown tokenizer files, symlinks or partial source
    copies may acquire the registered encoder identity.
    """
    publisher, native = Path(publisher_directory), Path(native_directory)
    if not publisher.is_dir() or publisher.is_symlink():
        raise ValueError("regular publisher directory required")
    info = {}
    for name in sorted(MODEL_FILES):
        path = publisher / name
        if not path.is_file() or path.is_symlink():
            raise ValueError("missing or symlinked registered pretrained file")
        size = path.stat().st_size
        if not 0 < size <= 120_000_000:
            raise ValueError("unbounded registered pretrained file")
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        info[name] = {"sha256": h.hexdigest(), "bytes": size}
    if _digest_json(info) != REGISTERED_ENCODER_IDENTITY:
        raise ValueError("unregistered pretrained encoder bytes")
    native.mkdir(exist_ok=False)
    for name in sorted(MODEL_FILES):
        source = publisher / name
        if source.is_symlink() or not source.is_file():
            raise ValueError("registered source changed during staging")
        copied = hashlib.sha256()
        length = 0
        with source.open("rb") as reader, (native / name).open("xb") as writer:
            for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                length += len(chunk)
                if length > info[name]["bytes"]:
                    raise ValueError("registered source grew during staging")
                copied.update(chunk)
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        if length != info[name]["bytes"] or copied.hexdigest() != info[name]["sha256"]:
            raise ValueError("registered source mutated during staging")
    staged, identity = inventory(native, expected=info)
    if identity != REGISTERED_ENCODER_IDENTITY:
        raise ValueError("native view lost registered model identity")
    return {"encoder_identity": identity, "files": len(staged),
            "source_files_allowed_to_exceed_native_view": True,
            "publisher_model_unchanged": True, "production_accepted": False}

def _printable_ascii(text):
    return isinstance(text, str) and 0 < len(text.encode("utf-8")) <= MAX_TEXT_BYTES and all(
        ch in "\n\r\t" or " " <= ch <= "~" for ch in text
    ) and bool(text.strip()) and not any(token in text for token in SPECIAL_TOKENS)


class AsciiWordPiece:
    """BertNormalizer+BertPreTokenizer+WordPiece on the declared ASCII subset.

    ASCII-only is intentional. Reject rather than approximate Chinese, accents,
    custom tokenization or altered special-token policies. Hosted parity compares
    token IDs from the genuine AutoTokenizer on this exact admitted subset.
    """
    def __init__(self, folder):
        folder = Path(folder)
        obj = _json_bytes((folder / "tokenizer.json").read_bytes())
        normal = obj.get("normalizer")
        pre = obj.get("pre_tokenizer")
        model = obj.get("model")
        post = obj.get("post_processor")
        if (normal != {"type": "BertNormalizer", "clean_text": True,
                       "handle_chinese_chars": True, "strip_accents": None,
                       "lowercase": True}
            or pre != {"type": "BertPreTokenizer"}
            or not isinstance(model, dict)
            or model.get("type") != "WordPiece"
            or model.get("unk_token") != "[UNK]"
            or model.get("continuing_subword_prefix") != "##"
            or model.get("max_input_chars_per_word") != 100
            or not isinstance(model.get("vocab"), dict)
            or not isinstance(post, dict)
            or post.get("type") != "TemplateProcessing"
            or set(post.get("special_tokens", {})) != {"[CLS]", "[SEP]"}):
            raise ValueError("unregistered tokenizer profile")
        added = obj.get("added_tokens")
        if (not isinstance(added, list)
            or {(x.get("id"), x.get("content")) for x in added}
               != {(0, "[PAD]"), (100, "[UNK]"), (101, "[CLS]"),
                   (102, "[SEP]"), (103, "[MASK]")}
            or any(x.get("special") is not True or x.get("normalized") is not False
                   for x in added)):
            raise ValueError("unknown registered special token semantics")
        self.vocab = model["vocab"]
        if (len(self.vocab) != VOCAB or len(set(self.vocab.values())) != VOCAB
            or self.vocab.get("[PAD]") != 0
            or self.vocab.get("[UNK]") != 100
            or self.vocab.get("[CLS]") != 101
            or self.vocab.get("[SEP]") != 102):
            raise ValueError("tokenizer vocabulary incompatible with model")

    def encode(self, text, *, add_special_tokens=True):
        if not _printable_ascii(text) or type(add_special_tokens) is not bool:
            raise ValueError("nonempty printable ASCII input required")
        result = []
        # The BERT basic tokenizer treats ASCII punctuation, including underscore,
        # as a separate piece, then longest-matches WordPiece segments.
        for word in re.findall(r"[A-Za-z0-9]+|[^A-Za-z0-9\s]", text.lower()):
            if len(word) > 100:
                result.append(100)
                continue
            start = 0
            pieces = []
            while start < len(word):
                end = len(word)
                token_id = None
                while start < end:
                    part = word[start:end] if start == 0 else "##" + word[start:end]
                    token_id = self.vocab.get(part)
                    if token_id is not None:
                        break
                    end -= 1
                if token_id is None:
                    pieces = [100]
                    break
                pieces.append(token_id)
                start = end
            result.extend(pieces)
        if add_special_tokens:
            result = [101, *result, 102]
        return result


class MiniLMOfflineEncoder:
    """Actual 6-layer BERT weight inference, mean-pool + L2 normalize.

    Avoids any downloaded code, external requests or model mutation; only the
    already present safetensors are evaluated. Functional parity with the pinned
    AutoModel remains a separate independently executable mandatory test.
    """
    def __init__(self, directory, *, expected_inventory=None, threads=2):
        folder = Path(directory)
        self.files, self.identity = inventory(folder, expected=expected_inventory)
        if self.identity != REGISTERED_ENCODER_IDENTITY:
            raise ValueError("unregistered pretrained encoder inventory")
        cfg = _json_bytes((folder / "config.json").read_bytes())
        if (cfg.get("architectures") != ["BertModel"]
            or cfg.get("model_type") != "bert"
            or cfg.get("hidden_size") != HIDDEN
            or cfg.get("num_hidden_layers") != LAYERS
            or cfg.get("num_attention_heads") != HEADS
            or cfg.get("intermediate_size") != INTERMEDIATE
            or cfg.get("vocab_size") != VOCAB
            or cfg.get("hidden_act") != "gelu"
            or cfg.get("max_position_embeddings") != 512
            or cfg.get("position_embedding_type") != "absolute"
            or cfg.get("type_vocab_size") != 2
            or cfg.get("layer_norm_eps") != 1e-12
            or cfg.get("pad_token_id") != 0):
            raise ValueError("unsupported BERT runtime configuration")
        if type(threads) is not int or not 1 <= threads <= 16:
            raise ValueError("bounded compute thread count required")
        self.tokenizer = AsciiWordPiece(folder)
        tensors = load_file(str(folder / "model.safetensors"), device="cpu")
        required = {
            "embeddings.word_embeddings.weight", "embeddings.position_embeddings.weight",
            "embeddings.token_type_embeddings.weight", "embeddings.position_ids",
            "embeddings.LayerNorm.weight", "embeddings.LayerNorm.bias",
            "pooler.dense.weight", "pooler.dense.bias",
        }
        for i in range(LAYERS):
            p = f"encoder.layer.{i}."
            for sub in ("attention.self.query", "attention.self.key", "attention.self.value",
                        "attention.output.dense", "attention.output.LayerNorm",
                        "intermediate.dense", "output.dense", "output.LayerNorm"):
                required |= {p + sub + ".weight", p + sub + ".bias"}
        if set(tensors) != required:
            raise ValueError("missing or unrecognized pretrained tensor names")
        if (tensors["embeddings.word_embeddings.weight"].shape != (VOCAB, HIDDEN)
            or tensors["embeddings.position_embeddings.weight"].shape != (512, HIDDEN)
            or tensors["embeddings.token_type_embeddings.weight"].shape != (2, HIDDEN)
            or tensors["embeddings.position_ids"].shape not in ((1, 512), (512,))):
            raise ValueError("embedding tensor layout mismatch")
        for i in range(LAYERS):
            p = f"encoder.layer.{i}."
            for sub, out, width in (
                ("attention.self.query", HIDDEN, HIDDEN),
                ("attention.self.key", HIDDEN, HIDDEN),
                ("attention.self.value", HIDDEN, HIDDEN),
                ("attention.output.dense", HIDDEN, HIDDEN),
                ("attention.output.LayerNorm", HIDDEN, None),
                ("intermediate.dense", INTERMEDIATE, HIDDEN),
                ("output.dense", HIDDEN, INTERMEDIATE),
                ("output.LayerNorm", HIDDEN, None),
            ):
                if (tensors[p + sub + ".weight"].shape !=
                    ((out,) if width is None else (out, width))
                    or tensors[p + sub + ".bias"].shape != (out,)):
                    raise ValueError("encoder tensor layout mismatch")
        if any(not torch.isfinite(t).all().item() for k,t in tensors.items()
               if k != "embeddings.position_ids"):
            raise ValueError("nonfinite pretrained weights")
        self._t = tensors
        self.truncated_inputs = 0
        self.calls = 0
        self.threads = threads

    def _linear(self, x, key):
        return F.linear(x, self._t[key + ".weight"], self._t[key + ".bias"])

    def _norm(self, x, key):
        return F.layer_norm(x, (HIDDEN,), self._t[key + ".weight"],
                            self._t[key + ".bias"], eps=1e-12)

    @torch.no_grad()
    def encode(self, texts):
        if (not isinstance(texts, (list, tuple)) or not 1 <= len(texts) <= MAX_BATCH
            or any(not _printable_ascii(v) for v in texts)):
            raise ValueError("bounded nonempty ASCII text batch required")
        seqs = [self.tokenizer.encode(text) for text in texts]
        if any(len(ids) > MAX_TOKENS for ids in seqs):
            # Never silently imitate a truncated HF encoder request.
            raise ValueError("encoder token limit exceeded")
        length = max(len(ids) for ids in seqs)
        ids = torch.zeros((len(seqs), length), dtype=torch.long)
        mask = torch.zeros((len(seqs), length), dtype=torch.float32)
        for i,seq in enumerate(seqs):
            ids[i, :len(seq)] = torch.tensor(seq, dtype=torch.long)
            mask[i, :len(seq)] = 1.0
        t = self._t
        prev_threads = torch.get_num_threads()
        try:
            # Torch's per-process thread setting is owned by the research runner.
            # Restoring it avoids silently changing other consumers.
            if prev_threads != self.threads:
                torch.set_num_threads(self.threads)
            with torch.inference_mode():
                positions = torch.arange(length).unsqueeze(0)
                x = (t["embeddings.word_embeddings.weight"][ids]
                     + t["embeddings.position_embeddings.weight"][positions]
                     + t["embeddings.token_type_embeddings.weight"][0])
                x = self._norm(x, "embeddings.LayerNorm")
                attention_mask = (1.0 - mask[:, None, None, :]) * torch.finfo(x.dtype).min
                for i in range(LAYERS):
                    p = f"encoder.layer.{i}."
                    def heads(v):
                        return v.reshape(len(seqs), length, HEADS, HIDDEN // HEADS).transpose(1, 2)
                    q = heads(self._linear(x, p + "attention.self.query"))
                    k = heads(self._linear(x, p + "attention.self.key"))
                    v = heads(self._linear(x, p + "attention.self.value"))
                    attn = torch.softmax((q @ k.transpose(-1, -2)) / math.sqrt(HIDDEN // HEADS)
                                         + attention_mask, dim=-1)
                    context = (attn @ v).transpose(1, 2).contiguous().reshape(
                        len(seqs), length, HIDDEN)
                    x = self._norm(x + self._linear(context, p + "attention.output.dense"),
                                   p + "attention.output.LayerNorm")
                    intermediate = F.gelu(self._linear(x, p + "intermediate.dense"))
                    x = self._norm(x + self._linear(intermediate, p + "output.dense"),
                                   p + "output.LayerNorm")
                pooled = (x * mask.unsqueeze(-1)).sum(1) / mask.sum(1, keepdim=True)
                encoded = F.normalize(pooled, dim=-1).cpu().numpy().astype(np.float32)
        finally:
            if prev_threads != self.threads:
                torch.set_num_threads(prev_threads)
        if not np.isfinite(encoded).all():
            raise ValueError("nonfinite pretrained encoder output")
        self.calls += 1
        return encoded


def compare_with_transformers(directory, texts, *, max_abs_tolerance=2e-5,
                              min_cosine=0.999999):
    """No synthetic parity claim: execute both real encoders on identical texts.

    Fails without an installed reference environment. Downstream equivalence
    MUST NOT be claimed from native-only smoke or unrelated model snapshots.
    """
    from pretrained import Encoder
    from native import digest
    if (not isinstance(texts, (list, tuple)) or not texts or len(texts) > MAX_BATCH):
        raise ValueError("registered parity queries required")
    reference = Encoder(Path(directory))
    candidate = MiniLMOfflineEncoder(directory)
    if reference.identity != candidate.identity or digest(candidate.files) != candidate.identity:
        raise ValueError("pretrained inventory identity mismatch")
    for text in texts:
        expected_ids = reference.tokenizer.encode(text, add_special_tokens=True)
        actual_ids = candidate.tokenizer.encode(text, add_special_tokens=True)
        if expected_ids != actual_ids:
            raise ValueError("tokenization parity mismatch")
    actual, reference_vectors = candidate.encode(texts), reference.encode(texts)
    errors = np.abs(actual - reference_vectors)
    norm = np.linalg.norm(actual, axis=1) * np.linalg.norm(reference_vectors, axis=1)
    cosines = np.sum(actual * reference_vectors, axis=1) / norm
    good = bool((errors.max() <= max_abs_tolerance) and (cosines.min() >= min_cosine))
    if not good:
        raise ValueError(f"pretrained inference parity failure: abs={errors.max()} cos={cosines.min()}")
    return {"schema": "hepta.minilm-native-parity.research.v1",
            "encoder_identity": candidate.identity, "pairs": len(texts),
            "maximum_absolute_error": float(errors.max()),
            "minimum_cosine": float(cosines.min()),
            "tokens_exact": True, "weights_exact_inventory": True,
            "parity_verified": True, "production_accepted": False}


PARITY_TEXTS = (
    "A short memory about location and ownership.",
    "At logical revision 2, what is the recorded status identifier?",
    "Observed 2026-10-01T10:00:00+00:00. Source: {\"entity\": \"build_7\", \"attribute\": \"successful_mode\"}.",
    "This was corrected by a later event; do not repeat stale versions.",
    "Option A is safer than option B before the build step.",
)
