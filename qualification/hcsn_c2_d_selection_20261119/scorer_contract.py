"""Metadata-only content bindings; this module never opens feature or label data."""

import hashlib
import json
import re


FEATURE_ROLES = {"features", "delta_ticks", "lengths", "valid_mask", "episode_order", "row_order"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def content_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def sha(value):
    require(type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None, "SHA256 identity")


def identity(row):
    require(type(row) is dict and set(row) == {"sha256", "bytes"}, "artifact identity keyset")
    sha(row["sha256"])
    require(type(row["bytes"]) is int and row["bytes"] > 0, "positive artifact bytes")


def freeze_prediction_metadata(roster, feature_manifest, predictions):
    """Bind complete prediction receipts without granting admission or opening labels."""
    require(type(roster) is list and len(roster) == 21, "fixed 21-model roster")
    names = {r["name"] for r in roster}
    require(len(names) == 21, "unique selected models")
    expected_keys = {"schema", "subject", "rows", "order_sha256", "artifacts", "contains_activity_labels"}
    require(type(feature_manifest) is dict and set(feature_manifest) == expected_keys, "feature manifest keyset")
    require(feature_manifest["schema"] == "isolated-confirmation-features-v1"
            and feature_manifest["subject"] == "E" and feature_manifest["contains_activity_labels"] is False,
            "label-free feature metadata")
    require(type(feature_manifest["rows"]) is int and feature_manifest["rows"] > 0, "positive event count")
    sha(feature_manifest["order_sha256"])
    artifacts = feature_manifest["artifacts"]
    require(type(artifacts) is dict and set(artifacts) == FEATURE_ROLES, "only six allowed feature roles")
    for row in artifacts.values():
        identity(row)
    require(artifacts["row_order"]["sha256"] == feature_manifest["order_sha256"], "one exact feature row order")
    require(type(predictions) is list and len(predictions) == 21
            and {r["name"] for r in predictions} == names, "all 21 distinct prediction receipts")
    selected = {r["name"]: r["model_binding_sha256"] for r in roster}
    feature_sha = content_hash(feature_manifest)
    for r in predictions:
        require(type(r) is dict and set(r) == {"name", "model_binding_sha256", "feature_manifest_sha256",
                "order_sha256", "logits", "rows", "classes", "dtype", "completed_before_label_access"},
                "prediction receipt keyset")
        require(r["model_binding_sha256"] == selected[r["name"]], "exact selected model binding")
        require(r["feature_manifest_sha256"] == feature_sha and r["order_sha256"] == feature_manifest["order_sha256"],
                "same feature and row-order binding")
        require(type(r["rows"]) is int and r["rows"] == feature_manifest["rows"]
                and type(r["classes"]) is int and r["classes"] == 11 and r["dtype"] == "float64"
                and r["completed_before_label_access"] is True, "complete prior prediction contract")
        identity(r["logits"])
    return {"schema": "complete-prediction-metadata-content-binding-v1",
            "roster_sha256": content_hash(roster), "feature_manifest_sha256": feature_sha,
            "prediction_receipts_sha256": content_hash(sorted(predictions, key=lambda x: x["name"])),
            "model_count": 21, "label_data_opened": False, "execution_authorization": False,
            "scope": "Content hash of metadata only, not a digital author signature or proof of payload bytes/custody."}
