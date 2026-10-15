"""Original-byte-only stock ModernBERT MLM tied-weight repair, research only.

Only when exactly the Embedding/Decoder parameters are Meta; every saved
source tensor is read from an immutable sha256-pinned safetensors file.
No random fill, to_empty, checkpoint conversion, resize, model substitution,
or production permission. LocalEncoder independently checks all saved tensors.
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

def require(condition, message):
    if not condition:
        raise OriginalTieRecoveryError(message)

def meta_names(model):
    return {name for name, tensor in [
        *model.named_parameters(remove_duplicate=False),
        *model.named_buffers(remove_duplicate=False)
    ] if getattr(tensor, "is_meta", False)}

def recover_saved_tie(model, info: dict, root: Path, manifest: dict):
    """Return None for complete loads or a strictly nonauthorizing source receipt."""
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
            "only stock tied ModernBERT MLM may use original source recovery")
    require(type(info) is dict and type(info.get("missing_keys")) in (list, tuple)
            and all(type(key) is str for key in info["missing_keys"])
            and set(info["missing_keys"]) <= {EMBEDDING, DECODER}
            and not any(info.get(k) for k in
                        ("unexpected_keys", "mismatched_keys", "error_msgs")),
            "unreconciled HF loading report")
    require(type(manifest) is dict and manifest.get("kind") == "masked_lm"
            and type(manifest.get("files")) is dict,
            "source must be a fully pinned MLM material")
    from public_stem_material_v8 import PINNED_RELEASES
    require(manifest.get("revision") == PINNED_RELEASES["mmbert-small"],
            "source revision not the reviewed immutable public mmBERT release")
    require(isinstance(root, Path) and root.is_dir() and not root.is_symlink(),
            "unsafe source model directory")
    embeddings = model.get_input_embeddings()
    decoder = getattr(model, "decoder", None)
    require(isinstance(embeddings, torch.nn.Embedding)
            and isinstance(decoder, torch.nn.Linear)
            and model.model.embeddings.tok_embeddings is embeddings,
            "stock model tied layers do not match expected topology")
    expected = (embeddings.num_embeddings, embeddings.embedding_dim)
    require(decoder.weight.shape == embeddings.weight.shape == expected
            and decoder.out_features == embeddings.num_embeddings
            and decoder.in_features == embeddings.embedding_dim
            and getattr(config, "vocab_size", None) == embeddings.num_embeddings
            and getattr(config, "hidden_size", None) == embeddings.embedding_dim,
            "source tensor geometry differs from stock config")
    files = manifest["files"]
    shards = sorted(n for n in files if type(n) is str and n.endswith(".safetensors"))
    require(1 <= len(shards) <= 16
            and all("/" not in s and "\\" not in s and ".." not in s for s in shards),
            "unsafe or excessive source shards")
    originals = {}
    for name in shards:
        path = root / name
        require(path.is_file() and not path.is_symlink(), "unsafe original shard")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for buf in iter(lambda: stream.read(1024*1024), b""):
                digest.update(buf)
        require(type(files[name]) is str and digest.hexdigest() == files[name],
                "saved source checksum does not match frozen material")
        with safe_open(str(path), framework="pt", device="cpu") as saved:
            for key in (EMBEDDING, DECODER):
                if key in saved.keys():
                    require(key not in originals, "duplicate original tied-weight key")
                    tensor = saved.get_tensor(key)
                    require(tensor.device.type == "cpu"
                            and tensor.dtype == torch.float32
                            and tensor.is_contiguous()
                            and tuple(tensor.shape) == expected,
                            "saved tied-weight geometry/dtype differs from stock model")
                    originals[key] = (tensor, name)
    require(originals, "no original saved tied Embedding/Decoder source")
    if len(originals) == 2:
        require(torch.equal(originals[EMBEDDING][0], originals[DECODER][0]),
                "two original saved tied weights disagree")
    source = EMBEDDING if EMBEDDING in originals else DECODER
    tensor, shard = originals[source]
    parameter = torch.nn.Parameter(tensor.detach().contiguous(),
                                   requires_grad=False)
    embeddings.weight = parameter
    decoder.weight = parameter
    require(not meta_names(model)
            and same_physical_view(embeddings.weight, decoder.weight),
            "recovered original tied weights are not one physical view")
    return {"status": "source_bytes_bound_not_authoritative",
            "saved_tensor_name": source, "saved_source_file": shard,
            "saved_alias_count": len(originals), "source_dtype": "F32",
            "source_shape": list(expected), "production_accepted": False}
