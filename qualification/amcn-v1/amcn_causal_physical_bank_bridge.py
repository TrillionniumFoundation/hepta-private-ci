"""Physically bind existing #1968 two-type trained Head bank to #2085 arms.

No second trainer, no synthetic alternative loader, no Reader invocation and no
model selection. The original #1968 safetensors loader and actual PyTorch
forward-parity check are required; SHA/material integrity is not source trust.
"""
from __future__ import annotations

from amcn_causal_task_audit import ALLOWED_TYPES, digest, is_sha, require


def replay_and_bind_original_bank(matrix, type_by_row, training_receipt,
                                  original_predictions, bank_directory, *,
                                  expected_manifest_sha256,
                                  expected_source_binding_sha256,
                                  expected_predictions_sha256):
    """Reload six physical FP32 Heads and replay every original prediction.

    A bridge result may populate only provenance fields of a future nine-arm
    plan. It does NOT manufacture graph routes, an independent strong RAG arm,
    new Reader outputs or prospective labels.
    """
    require(all(is_sha(p) for p in (expected_manifest_sha256,
                                    expected_source_binding_sha256,
                                    expected_predictions_sha256)),
            "independently supplied exact original model/Head pins required")
    # Import the repository's existing physical trainer/loader, not a parallel
    # math implementation. The production source path never permits a mock.
    from amcn_typed_budget import (  # noqa: PLC0415
        reload_pinned_typed_bank, type_inventory_digest,
        verify_reloaded_typed_predictions,
    )

    require(isinstance(training_receipt, dict)
            and training_receipt.get("production_accepted") is False
            and isinstance(training_receipt.get("metrics"), dict),
            "original training receipt missing or claiming authority")
    m = training_receipt["metrics"]
    types = sorted(set(type_by_row.values())) if isinstance(type_by_row, dict) else []
    require(len(types) == 2 and set(types) <= ALLOWED_TYPES
            and m.get("functional_types") == types
            and m.get("actual_model_update") is True
            and m.get("future_labels_opened_during_training") is False,
            "original train-only two-type physical Head experiment missing")
    inventory_digest = type_inventory_digest(matrix, type_by_row)
    require(m.get("frozen_feature_sha256") == matrix.identity
            and m.get("precommitted_type_inventory_sha256") == inventory_digest
            and m.get("prediction_sha256") == expected_predictions_sha256,
            "original source-first feature/type/heldout prediction lineage changed")
    loaded = reload_pinned_typed_bank(
        bank_directory, expected_manifest_sha256=expected_manifest_sha256,
        expected_feature_sha256=matrix.identity,
        expected_source_binding_sha256=expected_source_binding_sha256)
    require(loaded.get("physical_head_bytes_verified") is True
            and loaded.get("production_accepted") is False,
            "physical Head bytes not actually reloaded")
    manifest = loaded["manifest"]
    require(manifest.get("types") == types
            and manifest.get("type_inventory_sha256") == inventory_digest
            and manifest.get("stem_sha256") == matrix.encoder_sha256
            and manifest.get("trained_sampling") == m.get("training_sampling"),
            "original saved Head types/stem/sampler changed")
    replay = verify_reloaded_typed_predictions(
        loaded, matrix, type_by_row, original_predictions,
        expected_prediction_sha256=expected_predictions_sha256)
    require(replay.get("physical_model_forward_calls") == 5 * len(original_predictions)
            and replay.get("verified_predictions") == len(original_predictions)
            and replay.get("no_label_scores_opened") is True,
            "original sealed probabilities not reproduced by six real tensors")
    capacity = {}
    for arm, source_arm in (("shared", "untyped_equal_budget"),
                            ("typed", "typed_equal_budget")):
        budget = m.get("untyped_budget" if arm == "shared" else "typed_budget")
        require(isinstance(budget, dict)
                and set(budget) == {"parameters", "parameter_bytes",
                                    "optimizer_steps", "examples_processed", "head_sha256"}
                and isinstance(budget["head_sha256"], dict)
                and set(budget["head_sha256"]) == set(types),
                "original complete two-Head training resource census absent")
        for metric in ("parameters", "parameter_bytes", "optimizer_steps",
                       "examples_processed"):
            require(type(budget[metric]) is int and budget[metric] > 0,
                    "original physically metered Head work invalid")
        original_heads = {}
        observed_parameters = 0
        for typ in types:
            entry = manifest["entries"][source_arm + "__" + typ]
            require(entry["parameters"]["sha256"] == budget["head_sha256"][typ]
                    and is_sha(entry["sha256"]),
                    "trained Head SHA differs from reloaded physical tensors")
            observed_parameters += entry["parameters"]["parameters"]
            original_heads[typ] = entry["parameters"]["sha256"]
        require(observed_parameters == budget["parameters"],
                "actual two-Head parameter sum changed")
        capacity[arm] = {
            "total_trainable_parameters": budget["parameters"],
            "optimizer_steps": budget["optimizer_steps"],
            "minibatch_examples": budget["examples_processed"],
            "artifact_sha256": expected_manifest_sha256,
            "training_receipt_sha256": digest(training_receipt),
            "head_sha256_by_type": original_heads,
            "trainable_head_count": 2,
            "active_heads_per_query": 1,
        }
    require(all(capacity["shared"][k] == capacity["typed"][k] for k in (
        "total_trainable_parameters", "optimizer_steps", "minibatch_examples")),
        "typed model bank used extra capacity or training budget")
    require(manifest["entries"]["frozen"]["parameters"]["sha256"] ==
            m["baseline_head"]["sha256"],
            "original immutable frozen Head changed")
    return {
        "profile": "hepta.amcn.original-typed-six-head-bridge.shadow.v1",
        "original_bank_manifest_sha256": expected_manifest_sha256,
        "original_source_binding_sha256": expected_source_binding_sha256,
        "original_predictions_sha256": expected_predictions_sha256,
        "original_training_receipt_sha256": digest(training_receipt),
        "types": types, "capacity": capacity,
        "frozen_head_sha256": m["baseline_head"]["sha256"],
        "single_head_sha256": m["single_head"]["sha256"],
        "physical_head_forward_replay": replay,
        "real_pretrained_encoder_origin_independently_authenticated": False,
        "future_reader_answers_generated": 0,
        "original_rag_and_graph_routes_verified": False,
        "original_publisher_truth_or_entailment_verified": False,
        "real_future_calendar_windows": 0,
        "production_accepted": False, "superiority_claim": False,
    }
