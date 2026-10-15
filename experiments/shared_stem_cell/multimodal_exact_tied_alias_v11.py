"""Strict one-alias reconciliation for complete stock ModernBERT MLM weights.

Only a *physically identical view* of the serialized embedding may account for
ModernBertForMaskedLM.decoder.weight. Matching values in copied storage do not
suffice. The caller must independently compare every serialized tensor before
this provisional loading-report exception can be admitted.
"""
from __future__ import annotations

from collections.abc import Collection


class MissingTensorError(ValueError):
    """A saved model tensor or a claimed physical alias is not fully verified."""


MODEL_CLASS = "ModernBertForMaskedLM"
MODEL_MODULE = "transformers.models.modernbert.modeling_modernbert"
EMBEDDING = "model.embeddings.tok_embeddings.weight"
DECODER = "decoder.weight"


def same_physical_view(first, second) -> bool:
    """Compare entire physical tensor views, not equal numeric copies."""
    import torch

    if not isinstance(first, torch.Tensor) or not isinstance(second, torch.Tensor):
        return False
    if first.device.type != "cpu" or second.device.type != "cpu" or first.is_meta or second.is_meta:
        return False
    try:
        return (
            first.device == second.device
            and first.dtype == second.dtype
            and first.shape == second.shape
            and first.stride() == second.stride()
            and first.storage_offset() == second.storage_offset()
            and first.data_ptr() == second.data_ptr()
            and first.untyped_storage().data_ptr() == second.untyped_storage().data_ptr()
            and first.untyped_storage().nbytes() == second.untyped_storage().nbytes()
        )
    except (RuntimeError, ValueError):
        return False


def reconcile_loading_report(loaded, info: dict, serialized_keys: Collection[str]) -> list[str]:
    """Prove exactly which missing keys correspond to saved tied weights.

    All non-missing loading failures are rejected. This function NEVER permits
    missing generic weights, an omitted *source* embedding or a copied decoder.
    The owner must still verify saved bytes, cover every tensor, and re-hash
    the complete snapshot after running the model.
    """
    if type(info) is not dict:
        raise MissingTensorError("full checkpoint loading report required")
    missing = info.get("missing_keys")
    if type(missing) not in (list, tuple) or any(type(k) is not str for k in missing):
        raise MissingTensorError("explicit missing-key inventory required")
    if any(info.get(name) for name in ("unexpected_keys", "mismatched_keys", "error_msgs")):
        raise MissingTensorError("checkpoint loading report contains unrecognized failure")
    if not missing:
        return []
    model_type = type(loaded)
    config = getattr(loaded, "config", None)
    if (model_type.__name__ != MODEL_CLASS or model_type.__module__ != MODEL_MODULE
            or getattr(config, "model_type", None) != "modernbert"
            or getattr(config, "tie_word_embeddings", None) is not True):
        raise MissingTensorError("only stock tied ModernBERT MLM alias is admissible")
    keys = set(serialized_keys)
    if list(missing) == [DECODER]:
        if EMBEDDING not in keys or DECODER in keys:
            raise MissingTensorError("serialized embedding source or alias inventory mismatched")
        omitted = DECODER
    elif list(missing) == [EMBEDDING]:
        # Reverse tied-key serialization is allowed ONLY if decoder is
        # physically present in the saved checkpoint and both loaded names
        # resolve to the same proven CPU Parameter view.
        if DECODER not in keys or EMBEDDING in keys:
            raise MissingTensorError("serialized decoder source or alias inventory mismatched")
        omitted = EMBEDDING
    else:
        raise MissingTensorError("an unrecognized or duplicate trained tensor is missing")
    state = loaded.state_dict()
    if DECODER not in state or EMBEDDING not in state:
        raise MissingTensorError("loaded full MLM decoder or embedding missing")
    if not same_physical_view(state[DECODER], state[EMBEDDING]):
        raise MissingTensorError("equal bytes are not a physical tied decoder")
    return [omitted]
