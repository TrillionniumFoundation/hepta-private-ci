"""Export an immutable research task Head for the native zero-state evaluator.

The caller supplies the retained source manifest digest and full feature
identity. This copies only the gate, adapter and task tensors; it does not train,
recalibrate, export policy actions, or grant production admission.
"""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import numpy as np

from cell_head_training import MAX_MANIFEST_BYTES, load_head_artifact
from feature_bundle import FeatureIdentityV1
from research_presence_guard import _validate_head

SCHEMA = "hepta.native-task-head.v1"
NUMERIC_PROFILE = "f32-io-f64-accum-gelu-erf-v1"
FEATURE_LAYOUT = "concat-text-image-product-absolute-difference-cosine-v1"
TENSOR_ORDER = ("gate.weight", "gate.bias", "down.weight", "up.weight",
                "task_head.weight", "task_head.bias")
MAX_NATIVE_PARAMETERS = 262144


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def export_native_head(source, *, expected_manifest_sha256: str,
                       expected_identity: FeatureIdentityV1, output) -> dict:
    """Export the declared text+image fusion contract to bounded LE float32.

    The feature layout is a caller contract, not independent source attestation.
    The replay entry point binds it to the verified original fusion producer.
    A new destination is required, and the retained source remains unchanged.
    """
    head = load_head_artifact(source,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_identity=expected_identity)
    report, config = _validate_head(head)
    with (Path(source) / "manifest.json").open("rb") as stream:
        raw_source = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(raw_source) > MAX_MANIFEST_BYTES or _sha(raw_source) != expected_manifest_sha256:
        raise ValueError("source manifest changed during export")
    source_manifest = json.loads(raw_source)
    width = report["feature_width"]
    if (report.get("local_state_training") != "zero_state_only"
            or width < 5 or (width - 1) % 4
            or expected_identity.generation > 2**64 - 1
            or expected_identity.revocation_epoch > 2**64 - 1):
        raise ValueError("native export requires bounded zero-state fusion inputs")
    shapes = ((1, width + config.state_width), (1,),
              (config.adapter_rank, width), (width, config.adapter_rank),
              (config.task_count, width), (config.task_count,))
    state = head._head.state_dict()
    pieces = []
    for name, shape in zip(TENSOR_ORDER, shapes, strict=True):
        value = state[name].detach().cpu().numpy()
        if (value.shape != shape or value.dtype != np.dtype("float32")
                or not np.isfinite(value).all()):
            raise ValueError("native tensor shape, precision or values differ")
        pieces.append(value.astype("<f4", copy=False).tobytes(order="C"))
    payload = b"".join(pieces)
    if not 0 < len(payload) <= MAX_NATIVE_PARAMETERS * 4:
        raise ValueError("native task Head exceeds its tensor budget")
    manifest = {"schema": SCHEMA, "numeric_profile": NUMERIC_PROFILE,
        "state_contract": "zero_state_only", "mode": "SHADOW_ONLY",
        "authority": "DENY_ALL", "feature_identity": asdict(expected_identity),
        "feature_layout": FEATURE_LAYOUT, "width": width,
        "state_width": config.state_width, "adapter_rank": config.adapter_rank,
        "task_count": config.task_count, "required_present_mask": 3,
        "temperature": report["temperature"],
        "confidence_threshold": config.confidence_threshold,
        "source_head_manifest_sha256": expected_manifest_sha256,
        "source_head_weights_sha256": source_manifest["weights_file_sha256"],
        "weights_sha256": _sha(payload), "weights_bytes": len(payload)}
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                     allow_nan=False).encode() + b"\n"
    if len(raw) > 65536:
        raise ValueError("native task manifest exceeds its byte budget")
    _validate_head(head)
    destination = Path(output).absolute()
    if destination.exists() or destination.is_symlink() or not destination.parent.is_dir():
        raise ValueError("new output directory with an existing parent required")
    destination.mkdir(mode=0o700)
    with (destination / "weights.f32le").open("xb") as stream:
        stream.write(payload)
    with (destination / "manifest.json").open("xb") as stream:
        stream.write(raw)
    return {"schema": "hepta.native-task-export-receipt.v1",
        "manifest_sha256": _sha(raw), "weights_sha256": _sha(payload),
        "weights_bytes": len(payload), "resident_parameters": len(payload) // 4,
        "source_head_manifest_sha256": expected_manifest_sha256,
        "source_head_weights_sha256": source_manifest["weights_file_sha256"],
        "source_trained_tensor_sha256": report["trained_tensor_sha256"],
        "source_mode": config.mode, "mode": "SHADOW_ONLY", "authority": "DENY_ALL",
        "new_training_or_calibration": False, "production_activation_allowed": False,
        "task_admission_allowed": False, "action_execution_allowed": False}
