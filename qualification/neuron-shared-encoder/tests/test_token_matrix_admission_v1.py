"""Focused no-authority token matrix evidence admission tests."""
from copy import deepcopy

import pytest

from neuron_shared_encoder.token_matrix_admission_v1 import audit_token_matrix_receipt


def sample():
    digest = "a" * 64
    return {
        "encoder": "modernbert-joint",
        "tokenizer_sha256": digest,
        "weights_sha256": digest,
        "bundle_sha256": digest,
        "source_dataset_sha256": digest,
        "full_joint_input_sha256": digest,
        "feature_sha256": digest,
        "tokens_shape": [32, 128, 768],
        "mask_shape": [32, 128],
        "head_arms": ["pooled_cached", "token_query_prepared"],
        "per_cell_parameters": 16132,
        "training_seed_ids": [11, 23, 47],
        "train_row_ids_sha256": digest,
        "heldout_row_ids_sha256": digest,
        "encoder_forward_attempts": 4,
        "encoder_forward_completions": 4,
        "source_type": "actual_pretrained_token_hidden_states",
        "scope": {
            "principal": "scope-a", "purpose": "research",
            "organ_id": "organ-a", "cell_id": "cell-a",
        },
        "generation": 1,
        "authority_epoch": 1,
    }


def test_shape_acceptance_never_selects_or_authorizes():
    result = audit_token_matrix_receipt(sample())
    assert result["production_admission"] == "BLOCKED"
    assert result["quality_winner_selected"] is False
    assert result["real_model_execution_independently_verified"] is False
    assert result["signed_NDU_verified"] is False
    assert len(result["receipt_sha256"]) == 64


@pytest.mark.parametrize("field,value", [
    ("tokens_shape", [32, 768]),
    ("tokens_shape", [32, 300, 768]),
    ("tokens_shape", [4096, 128, 768]),
    ("tokens_shape", [32, 128, True]),
    ("mask_shape", [32, 127]),
    ("head_arms", ["token_query_prepared"]),
    ("head_arms", ["token_query_prepared", "pooled_cached"]),
    ("source_type", "pooled_pretrained_features"),
    ("source_type", "synthetic_repeated_pooled"),
    ("training_seed_ids", [11, 11]),
    ("per_cell_parameters", 0),
    ("encoder_forward_completions", 0),
    ("encoder_forward_completions", 5),
    ("tokenizer_sha256", "not-a-digest"),
    ("generation", 0),
    ("encoder", "unknown"),
])
def test_bad_or_untrusted_evidence_fails_closed(field, value):
    receipt = sample()
    receipt[field] = value
    with pytest.raises(ValueError):
        audit_token_matrix_receipt(receipt)


def test_cross_scope_and_unknown_fields_denied():
    receipt = sample()
    receipt["scope"] = {"principal": "a"}
    with pytest.raises(ValueError):
        audit_token_matrix_receipt(receipt)
    receipt = sample()
    receipt["future_ndu_accepted"] = True
    with pytest.raises(ValueError):
        audit_token_matrix_receipt(receipt)


def test_digest_changes_with_scope_and_content():
    first = sample()
    second = deepcopy(first)
    second["scope"]["cell_id"] = "cell-b"
    a = audit_token_matrix_receipt(first)
    b = audit_token_matrix_receipt(second)
    assert a["receipt_sha256"] != b["receipt_sha256"]
