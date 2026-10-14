"""No-authority validator for offline Token Matrix experiment evidence.

It never authorizes model use, NDU selection, artifact promotion or effects.
A self-reported JSON receipt is NOT an independently signed observation.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def _sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def audit_token_matrix_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Fail closed on claimed token/pooled mixups and incomparable experiment arms."""
    if not isinstance(receipt, dict):
        raise ValueError("receipt must be an object")
    required = {
        "encoder", "tokenizer_sha256", "weights_sha256", "bundle_sha256",
        "source_dataset_sha256", "full_joint_input_sha256", "feature_sha256",
        "tokens_shape", "mask_shape", "head_arms", "per_cell_parameters",
        "training_seed_ids", "train_row_ids_sha256", "heldout_row_ids_sha256",
        "encoder_forward_attempts", "encoder_forward_completions",
        "source_type", "scope", "generation", "authority_epoch",
    }
    if set(receipt) != required:
        raise ValueError("incomplete or extra critical receipt fields")
    for key in ("tokenizer_sha256", "weights_sha256", "bundle_sha256",
                "source_dataset_sha256", "full_joint_input_sha256",
                "feature_sha256", "train_row_ids_sha256", "heldout_row_ids_sha256"):
        if not _sha(receipt[key]):
            raise ValueError(f"invalid bound digest: {key}")
    if receipt["source_type"] != "actual_pretrained_token_hidden_states":
        raise ValueError("pooled/repeated/synthetic features are not token matrices")
    dims, mask = receipt["tokens_shape"], receipt["mask_shape"]
    if (not isinstance(dims, list) or len(dims) != 3
            or any(type(v) is not int for v in dims)
            or not 1 <= dims[0] <= 4096 or not 2 <= dims[1] <= 256
            or not 16 <= dims[2] <= 2048 or dims[0] * dims[1] * dims[2] > 8_388_608
            or type(mask) is not list or mask != dims[:2]):
        raise ValueError("a bounded three-dimensional token matrix and mask are required")
    if receipt["head_arms"] != ["pooled_cached", "token_query_prepared"]:
        raise ValueError("complete ordered paired readout arms required")
    if (type(receipt["per_cell_parameters"]) is not int
            or not 1 <= receipt["per_cell_parameters"] <= 262144):
        raise ValueError("invalid matched Head parameter count")
    seeds = receipt["training_seed_ids"]
    if (not isinstance(seeds, list) or not 2 <= len(seeds) <= 8
            or any(type(s) is not int or not 0 <= s < 2**31 for s in seeds)
            or len(seeds) != len(set(seeds))):
        raise ValueError("independent bounded training seeds required")
    scope = receipt["scope"]
    if (not isinstance(scope, dict)
            or set(scope) != {"principal", "purpose", "organ_id", "cell_id"}
            or any(not isinstance(v, str) or not v or len(v) > 128 for v in scope.values())):
        raise ValueError("complete isolated Cell scope required")
    for key in ("generation", "authority_epoch", "encoder_forward_attempts",
                "encoder_forward_completions"):
        if type(receipt[key]) is not int or receipt[key] < (0 if key.startswith("encoder_forward") else 1):
            raise ValueError(f"invalid {key}")
    if not 0 < receipt["encoder_forward_completions"] <= receipt["encoder_forward_attempts"]:
        raise ValueError("no observed successful model forward")
    if receipt["encoder"] not in ("mmbert-joint", "modernbert-joint", "granite-joint", "laya-joint"):
        raise ValueError("unregistered Encoder profile")
    canonical = json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                           allow_nan=False, separators=(",", ":")).encode()
    return {
        "schema": "hepta.neuron.token-matrix-shadow-audit.v1",
        "receipt_sha256": hashlib.sha256(canonical).hexdigest(),
        "shape_bound": True,
        "paired_metadata_shape_valid": True,
        "real_model_execution_independently_verified": False,
        "source_use_entitlement_verified": False,
        "train_vs_future_independently_verified": False,
        "quality_winner_selected": False,
        "signed_NDU_verified": False,
        "production_admission": "BLOCKED",
        "warning": "Self-reported byte and geometry checks are not model execution attestation.",
    }
