"""Function-preserving rank expansion of an independently verified parent.

Expansion is an explicit derived artifact with zero optimizer updates. It is
not a source write, does not drop ancestry, and cannot authorize installation.
"""

from pathlib import Path

import torch
from peft import get_peft_model_state_dict, set_peft_model_state_dict

from parametric_model import adapter_digest
from pretrained import frozen_digest


def expand_verified_parent(parent, target, destination, *, parent_manifest_sha256):
    parent._available()
    target._available()
    if (
        parent._parent != parent_manifest_sha256
        or parent._receipt is not None
        or parent._initialization != "verified_adapter"
        or not parent.reader.roots
        or parent.reader.identity != target.reader.identity
        or parent.reader.scope != target.reader.scope
        or target.reader.roots
        or target._receipt is not None
        or target._parent is not None
        or target._initialization != "frozen_base"
    ):
        raise ValueError(
            "verified same-base scoped parent and pristine target required"
        )
    source_config = parent.reader.model.peft_config["default"]
    target_config = target.reader.model.peft_config["default"]
    if (
        target_config.r != 2 * source_config.r
        or source_config.lora_alpha / source_config.r
        != target_config.lora_alpha / target_config.r
    ):
        raise ValueError("double rank with unchanged LoRA scaling required")
    before = adapter_digest(parent.reader.model)
    source = get_peft_model_state_dict(parent.reader.model)
    expanded = {
        key: value.detach().clone()
        for key, value in get_peft_model_state_dict(target.reader.model).items()
    }
    if set(source) != set(expanded):
        raise ValueError("identical target-module inventory required")
    products = []
    for name, tensor in source.items():
        dest = expanded[name]
        if ".lora_A." in name:
            if dest.shape != (2 * tensor.shape[0], tensor.shape[1]):
                raise ValueError("unexpected rank-expansion A layout")
            dest[: tensor.shape[0], :] = tensor
        elif ".lora_B." in name:
            if dest.shape != (tensor.shape[0], 2 * tensor.shape[1]):
                raise ValueError("unexpected rank-expansion B layout")
            dest.zero_()
            dest[:, : tensor.shape[1]] = tensor
            a_name = name.replace(".lora_B.", ".lora_A.")
            # Check after both A/B copies below; dictionary order is irrelevant.
            products.append((name, a_name))
        else:
            raise ValueError("only registered LoRA A/B matrices may expand")
    error = max(
        float((expanded[b] @ expanded[a] - source[b] @ source[a]).abs().max())
        for b, a in products
    )
    if error > 1e-7 or any(not torch.isfinite(v).all() for v in expanded.values()):
        raise ValueError("expansion changed a learned low-rank product")
    set_peft_model_state_dict(target.reader.model, expanded)
    target.reader.roots = set(parent.reader.roots)
    target._expected_adapter = adapter_digest(target.reader.model)
    target._freeze()
    if (
        adapter_digest(parent.reader.model) != before
        or frozen_digest(target.reader.model) != target.reader.base_digest
    ):
        raise ValueError("parent or frozen base changed during expansion")
    receipt = {
        "schema": "hepta.parametric-memory.rank-expansion.v1",
        "operation": "copy_parent_columns_zero_new_B_keep_initialized_new_A",
        "parent_manifest_sha256": parent_manifest_sha256,
        "parent_adapter_state_sha256": before,
        "adapter_state_sha256": target._expected_adapter,
        "source_rank": source_config.r,
        "target_rank": target_config.r,
        "max_low_rank_product_absolute_error": error,
        "optimizer_updates": 0,
        "roots": sorted(target.reader.roots),
        "base_unchanged": True,
        "production_accepted": False,
    }
    manifest = target.reader.save(Path(destination), receipt)
    # Subsequent writes must use the ordinary verified loader, which establishes
    # the expanded checkpoint as the explicit immediate parent.
    return {"manifest_sha256": manifest, "derivation": receipt}
