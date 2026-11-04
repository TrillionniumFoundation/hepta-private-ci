"""Strict, research-only recovery of a stock ModernBERT MLM *saved* tied weight.

Triggered ONLY if HF leaves exactly the two tied embedding/decoder Parameters on
Meta Device. Reads only byte-verified original safetensors under the already
pinned snapshot. Never calls to_empty, random initialization, resize, or a
pickle/model conversion. The LocalEncoder caller independently proves every
loaded tensor's equality to saved bytes afterward. No production authority.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import torch
from safetensors import safe_open

from multimodal_exact_tied_alias_v11 import (
    DECODER, EMBEDDING, MODEL_CLASS, MODEL_MODULE, same_physical_view,
)


class OriginalTieRecoveryError(ValueError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise OriginalTieRecoveryError(reason)


def meta_names(model) -> set[str]:
    return {name for name, t in [*model.named_parameters(remove_duplicate=False),
                                 *model.named_buffers(remove_duplicate=False)]
            if getattr(t, "is_meta", False)}


def recover_saved_tie(model, info: dict, root: Path, manifest: dict):
    """Return None for complete stock loads; report exactly one saved source otherwise.

    The only exceptional acceptance is both tied names on Meta Device in the
    exact reviewed stock ModernBERTForMaskedLM, after independent file hashes
    match the manifest. It does NOT repair any other missing tensor. The caller
    must perform unmodified strict whole-state/safetensors comparison after.
    """
    pending = meta_names(model)
    if not pending:
        return None
    require(pending == {EMBEDDING, DECODER},
            "unapproved Meta tensors; no speculative materialization")
    cls = type(model)
    config = getattr(model, "config", None)
    require(cls.__name__ == MODEL_CLASS and cls.__module__ == MODEL_MODULE
            and getattr(config, "model_type", None) == "modernbert"
            and getattr(config, "tie_word_embeddings", None) is True,
            "only reviewed stock tied ModernBERT MLM may use source recovery")
    require(type(info) is dict and type(info.get("missing_keys")) in (list, tuple)
            and all(isinstance(s, str) for s in info["missing_keys"])
            and set(info["missing_keys"]) <= {EMBEDDING, DECODER}
            and not any(info.get(key) for key in
                        ("unexpected_keys", "mismatched_keys", "error_msgs")),
            "unreconciled HF loading report")
    require(type(manifest) is dict and manifest.get("kind") == "masked_lm"
            and type(manifest.get("files")) is dict,
            "saved source must be pinned complete MLM material")
    # Public-mmBERT-specific repair: not a generic way for private/mutable
    # models to inject tensors into an apparently loaded checkpoint.
    from public_stem_material_v8 import PINNED_RELEASES
    require(manifest.get("revision") == PINNED_RELEASES["mmbert-small"],
            "source revision not the exact reviewed public mmBERT safetensors")
    require(isinstance(root, Path) and root.is_dir() and not root.is_symlink(),
            "untrusted checkpoint directory")
    embeddings = model.get_input_embeddings()
    decoder = getattr(model, "decoder", None)
    require(isinstance(embeddings, torch.nn.Embedding)
            and isinstance(decoder, torch.nn.Linear)
            and model.model.embeddings.tok_embeddings is embeddings,
            "stock model tied layer topology differs from expected")
    expect_shape = (embeddings.num_embeddings, embeddings.embedding_dim)
    require(decoder.weight.shape == embeddings.weight.shape == expect_shape
            and decoder.out_features == embeddings.num_embeddings
            and decoder.in_features == embeddings.embedding_dim
            and getattr(config, "vocab_size", None) == embeddings.num_embeddings
            and getattr(config, "hidden_size", None) == embeddings.embedding_dim,
            "recovery tensor geometry differs from bound model config")

    files = manifest["files"]
    shards = sorted(n for n in files if type(n) is str and n.endswith('.safetensors'))
    require(1 <= len(shards) <= 16 and all('/' not in s and '\\' not in s and '..' not in s
                                               for s in shards),
            "source shard inventory is unsafe or excessive")
    original = {}
    for name in shards:
        path = root / name
        require(path.is_file() and not path.is_symlink(), "original source shard unavailable")
        h = hashlib.sha256()
        with path.open('rb') as f:
            for block in iter(lambda: f.read(1024*1024), b''):
                h.update(block)
        require(type(files[name]) is str and h.hexdigest() == files[name],
                "source shard bytes differ from pinned checksum")
        with safe_open(str(path), framework='pt', device='cpu') as saved:
            for key in (EMBEDDING, DECODER):
                if key in saved.keys():
                    require(key not in original, "duplicate original tied-weight key")
                    tensor = saved.get_tensor(key)
                    require(tensor.device.type == 'cpu'
                            and tensor.dtype == torch.float32
                            and tensor.is_contiguous()
                            and tuple(tensor.shape) == expect_shape,
                            "original saved tied tensor geometry/dtype mismatch")
                    original[key] = (tensor, name)
    require(original, "no original serialized embedding/decoder source exists")
    if len(original) == 2:
        require(torch.equal(original[EMBEDDING][0], original[DECODER][0]),
                "two saved tied weights disagree in original checkpoint")
    source_key = EMBEDDING if EMBEDDING in original else DECODER
    tensor, source_file = original[source_key]
    # Store a real independent CPU tensor backed solely by the saved archive.
    # No to_empty, torch.empty initialization or optimizer update occurs.
    parameter = torch.nn.Parameter(tensor.detach().contiguous(), requires_grad=False)
    embeddings.weight = parameter
    decoder.weight = parameter
    require(not meta_names(model) and
            same_physical_view(embeddings.weight, decoder.weight),
            "original tied-weight recovery failed to share the physical view")
    return {"status": "source_bytes_bound_not_authoritative",
            "saved_tensor_name": source_key, "saved_source_file": source_file,
            "saved_alias_count": len(original), "source_dtype": "F32",
            "source_shape": list(expect_shape), "production_accepted": False}
