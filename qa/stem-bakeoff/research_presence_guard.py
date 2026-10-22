"""Task-only research inference requiring both text and image presence.

This separate caller contract does not alter the frozen scientific experiment.
Presence comes from an integrity-checked FeatureBundle and its trusted producer;
it is not source attestation, semantic matching, or missing-modality robustness.
No task admission or action execution authority is granted, even for confident
predictions. No labels, interventions, Encoder, training, or policy API is used.
"""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import torch

from cell_head_training import (HeadTrainingConfigV1, TEMPERATURES,
                                TrainedCellHeadV1, _state_digest)
from feature_bundle import FeatureBundleV1, MODALITIES
from native_latent import LightCellHead

REQUIRED_MODALITIES = ("text", "image")


class PresenceGuardError(ValueError):
    pass


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _contract():
    return {"schema": "hepta.research-presence-contract.v1",
        "required_modalities": list(REQUIRED_MODALITIES),
        "missing_row_policy": "reject_before_task_prediction",
        "confidence_policy": "unchanged_head_temperature_and_threshold",
        "acceptance_meaning": "presence_and_confidence_for_research_only",
        "source_presence_independently_attested": False,
        "incorrect_pair_detection_claimed": False,
        "missing_modality_robustness_claimed": False,
        "authority": "DENY_ALL", "mode": "SHADOW_ONLY",
        "production_activation_allowed": False,
        "task_admission_allowed": False, "action_execution_allowed": False}


def _validate_head(head):
    if type(head) is not TrainedCellHeadV1 or type(head._head) is not LightCellHead:
        raise PresenceGuardError("a frozen typed research task Head is required")
    report = head.report
    if (report.get("schema") != "hepta.trained-cell-task-head.v1"
            or report.get("authority") != "DENY_ALL"
            or report.get("mode") != "SHADOW_ONLY"
            or report.get("production_activation_allowed") is not False
            or report.get("feature_identity") != asdict(head.identity)):
        raise PresenceGuardError("Head research posture or feature identity differs")
    config = HeadTrainingConfigV1(**report["config"])
    config.validate()
    if (type(report.get("feature_width")) is not int
            or not 1 <= report["feature_width"] <= 4096
            or report["feature_width"] != head._head.width
            or config.task_count != head._head.task_head.out_features
            or type(report.get("temperature")) not in (int, float)
            or report["temperature"] not in TEMPERATURES
            or any(module.training for module in head._head.modules())
            or any(p.requires_grad or p.device.type != "cpu" or p.dtype != torch.float32
                   or not bool(torch.isfinite(p).all()) for p in head._head.parameters())
            or _state_digest(head._head) != report.get("trained_tensor_sha256")):
        raise PresenceGuardError("immutable task Head parameters or calibration differ")
    return report, config


def predict_text_image_required(head: TrainedCellHeadV1, bundle: FeatureBundleV1) -> dict:
    """Score only rows whose declared text and image channels are both present.

    Missing rows get null predictions, never a default negative class. Invalid
    identity/integrity rejects the entire request before a Head forward. The
    returned ``accepted`` is only the existing confidence decision after the
    presence check; task/action admission remains false for every row.
    """
    report, config = _validate_head(head)
    if type(bundle) is not FeatureBundleV1:
        raise PresenceGuardError("a bounded immutable FeatureBundle is required")
    bundle.require_identity(head.identity)
    views = bundle.snapshot()
    if views["global_features"].shape[1] != report["feature_width"]:
        raise PresenceGuardError("Head feature width mismatch")
    columns = [MODALITIES.index(name) for name in REQUIRED_MODALITIES]
    required_missing = views["missing_mask"][:, columns]
    eligible = ~required_missing.any(dim=1)
    indices = torch.nonzero(eligible, as_tuple=False).flatten().tolist()
    sources = bundle.source_record_digests
    rows = [{"row_index": index, "source_record_digest": source,
        "status": "REJECTED_MISSING_REQUIRED_MODALITY",
        "missing_required_modalities": [name for offset, name in enumerate(REQUIRED_MODALITIES)
                                        if bool(required_missing[index, offset])],
        "task_logits": None, "task_probabilities": None, "prediction": None,
        "accepted": False, "authority": "DENY_ALL",
        "task_admission_allowed": False, "action_execution_allowed": False}
        for index, source in enumerate(sources)]
    scored = None
    if indices:
        # Keep complete batches unchanged. Subsets retain every available view
        # and the original source ordering; excluded rows never enter the Head.
        scored = bundle if bool(eligible.all()) else FeatureBundleV1.from_tensors(
            **{name: tensor[indices] for name, tensor in views.items()},
            source_record_digests=tuple(sources[index] for index in indices),
            identity=bundle.identity)
        prediction = head.predict_task(scored)
        logits, probabilities, accepted = (prediction[name]
            for name in ("task_logits", "task_probabilities", "accepted"))
        shape = (len(indices), config.task_count)
        if (prediction.get("authority") != "DENY_ALL"
                or prediction.get("feature_bundle_sha256") != scored.bundle_digest
                or prediction.get("temperature") != report["temperature"]
                or any(not isinstance(value, torch.Tensor) or value.device.type != "cpu"
                       or value.shape != shape or not bool(torch.isfinite(value).all())
                       for value in (logits, probabilities))
                or not isinstance(accepted, torch.Tensor) or accepted.dtype != torch.bool
                or accepted.shape != (len(indices),)
                or not torch.equal(accepted, probabilities.max(dim=-1).values >= config.confidence_threshold)):
            raise PresenceGuardError("task prediction contract differs")
        for offset, index in enumerate(indices):
            passed = bool(accepted[offset])
            rows[index].update({"status": "SCORED_RESEARCH_ONLY" if passed else "ABSTAINED_LOW_CONFIDENCE",
                "task_logits": logits[offset].tolist(),
                "task_probabilities": probabilities[offset].tolist(),
                "prediction": int(probabilities[offset].argmax()), "accepted": passed})
    bundle.verify_integrity()
    if _state_digest(head._head) != report["trained_tensor_sha256"]:
        raise PresenceGuardError("immutable Head changed during task prediction")
    contract = _contract()
    contract_bytes = json.dumps(contract, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {**contract, "schema": "hepta.research-presence-guard.v1", "contract": contract,
        "contract_sha256": _sha(contract_bytes),
        "guard_source_sha256": _sha(Path(__file__).read_bytes()),
        "head_tensor_sha256": report["trained_tensor_sha256"],
        "parent_feature_bundle_sha256": bundle.bundle_digest,
        "parent_source_record_digests": list(sources),
        "scored_feature_bundle_sha256": None if scored is None else scored.bundle_digest,
        "scored_row_indices": indices, "input_rows": len(rows),
        "scored_rows": len(indices), "rejected_missing_rows": len(rows) - len(indices),
        "head_prediction_calls": int(bool(indices)), "encoder_calls": 0,
        "temperature": report["temperature"],
        "confidence_threshold": config.confidence_threshold, "rows": rows}
