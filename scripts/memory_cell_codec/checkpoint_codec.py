"""Lossy checkpoint derivation with exact inherited source ancestry.

Storage encoding never grants authority. Current readers require materialized
float32 tensors; packed storage savings are not quantized-execution savings.
"""

import json
import math
from pathlib import Path
import re

from safetensors.torch import save

from quantized_adapter import (
    MAX_PACKED_BYTES,
    canonical_bytes,
    decode_tensors,
    encode_tensors,
    state_digest,
)
from tensor_contract import (
    MAX_ADAPTER_BYTES,
    bounded_read,
    read_candidate,
    sha256,
    strict_json,
)

PARENT_FIELDS = {
    "schema",
    "base_identity",
    "scope",
    "roots",
    "tensor_layout",
    "adapter_sha256",
    "config_sha256",
    "training",
    "model_install_authority",
    "production_accepted",
}
CODEC_FIELDS = {
    "schema",
    "bits",
    "parent_manifest_sha256",
    "parent_adapter_sha256",
    "base_identity",
    "scope",
    "roots",
    "config_sha256",
    "payload_sha256",
    "payload_bytes",
    "metrics",
    "decoded_safetensors_sha256",
    "decoded_safetensors_bytes",
    "lossy_derivation",
    "model_install_authority",
    "production_accepted",
}


def _roots(values):
    if (
        not isinstance(values, (list, tuple, set, frozenset))
        or len(values) > 4096
        or any(
            type(x) is not str or re.fullmatch(r"[0-9a-f]{64}", x) is None
            for x in values
        )
        or len(set(values)) != len(values)
    ):
        raise ValueError("bounded unique source digests required")
    return set(values)


def _admit(parent, allowed, revoked):
    json.dumps(parent, allow_nan=False)
    if (
        set(parent) != PARENT_FIELDS
        or parent["schema"] != "hepta.memory-lora-candidate.v2"
        or parent["model_install_authority"] is not False
        or parent["production_accepted"] is not False
        or type(parent["training"]) is not dict
        or type(parent["base_identity"]) is not str
        or re.fullmatch(r"[0-9a-f]{64}", parent["base_identity"]) is None
        or type(parent["scope"]) is not str
        or not 1 <= len(parent["scope"].encode()) <= 128
    ):
        raise ValueError("parent research/lineage contract")
    roots = _roots(parent["roots"])
    if not roots or not roots <= _roots(allowed) or roots & _roots(revoked):
        raise ValueError("parent source not admitted or revoked")


def _source(directory, expected):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("real checkpoint directory required")
    payload = bounded_read(directory / "lineage.json", 256 * 1024)
    if sha256(payload) != expected:
        raise ValueError("parent manifest identity mismatch")
    return payload, strict_json(payload)


def _write_new(destination, files):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    for name, payload in files.items():
        with (destination / name).open("xb") as stream:
            stream.write(payload)
    return sum(len(value) for value in files.values())


def encode_checkpoint(
    parent,
    destination,
    *,
    expected_manifest_sha256,
    allowed_roots,
    revoked_roots,
    bits=8,
):
    """Derive a separately identified packed artifact from a verified parent."""
    parent = Path(parent)
    original, lineage = _source(parent, expected_manifest_sha256)
    _admit(lineage, allowed_roots, revoked_roots)
    config_bytes = bounded_read(parent / "adapter_config.json", 64 * 1024)
    state, _, _ = read_candidate(
        parent,
        expected_manifest_sha256=expected_manifest_sha256,
        base_identity=lineage["base_identity"],
        scope=lineage["scope"],
        expected_layout=lineage["tensor_layout"],
        expected_config=strict_json(config_bytes),
        allowed_roots=_roots(allowed_roots),
        revoked_roots=_roots(revoked_roots),
    )
    source_adapter = bounded_read(
        parent / "adapter_model.safetensors", MAX_ADAPTER_BYTES
    )
    if sha256(source_adapter) != lineage["adapter_sha256"]:
        raise ValueError("source adapter changed before derivation")
    packed, metrics = encode_tensors(state, bits)
    decoded = decode_tensors(
        packed, expected_layout=lineage["tensor_layout"], expected_bits=bits
    )
    decoded_bytes = save(decoded, metadata={"format": "pt"})
    manifest = dict(
        schema="hepta.memory-adapter-codec.v1",
        bits=bits,
        parent_manifest_sha256=expected_manifest_sha256,
        parent_adapter_sha256=lineage["adapter_sha256"],
        base_identity=lineage["base_identity"],
        scope=lineage["scope"],
        roots=lineage["roots"],
        config_sha256=lineage["config_sha256"],
        payload_sha256=sha256(packed),
        payload_bytes=len(packed),
        metrics=metrics,
        decoded_safetensors_sha256=sha256(decoded_bytes),
        decoded_safetensors_bytes=len(decoded_bytes),
        lossy_derivation=True,
        model_install_authority=False,
        production_accepted=False,
    )
    manifest_bytes = canonical_bytes(manifest)
    files = {
        "adapter.quantized": packed,
        "adapter_config.json": config_bytes,
        "source-lineage.json": original,
        "codec.json": manifest_bytes,
    }
    total = _write_new(destination, files)
    return dict(
        codec_manifest_sha256=sha256(manifest_bytes),
        packed_artifact_bytes=total,
        payload_bytes=len(packed),
        original_tensor_bytes=metrics["decoded_tensor_bytes"],
        original_adapter_file_bytes=len(source_adapter),
        parent_manifest_sha256=expected_manifest_sha256,
        metrics=metrics,
        retained_lineage_bytes=len(original),
        quantized_execution=False,
        production_accepted=False,
    )


def decode_checkpoint(
    packed_directory,
    destination,
    *,
    expected_codec_sha256,
    allowed_roots,
    revoked_roots,
):
    """Materialize a new v2 candidate; inherited roots and old identity stay exact."""
    packed_directory = Path(packed_directory)
    if packed_directory.is_symlink() or not packed_directory.is_dir():
        raise ValueError("real packed directory required")
    codec_bytes = bounded_read(packed_directory / "codec.json", 256 * 1024)
    if sha256(codec_bytes) != expected_codec_sha256:
        raise ValueError("codec manifest identity mismatch")
    codec = strict_json(codec_bytes)
    if (
        set(codec) != CODEC_FIELDS
        or codec["schema"] != "hepta.memory-adapter-codec.v1"
        or type(codec["bits"]) is not int
        or codec["bits"] not in (4, 8)
        or codec["lossy_derivation"] is not True
        or codec["model_install_authority"] is not False
        or codec["production_accepted"] is not False
    ):
        raise ValueError("codec research contract")
    original = bounded_read(packed_directory / "source-lineage.json", 256 * 1024)
    if sha256(original) != codec["parent_manifest_sha256"]:
        raise ValueError("inherited source manifest binding")
    parent = strict_json(original)
    _admit(parent, allowed_roots, revoked_roots)
    if (
        any(
            codec[k] != parent[k]
            for k in ("base_identity", "scope", "roots", "config_sha256")
        )
        or codec["parent_adapter_sha256"] != parent["adapter_sha256"]
    ):
        raise ValueError("codec changed inherited identity")
    config_bytes = bounded_read(packed_directory / "adapter_config.json", 64 * 1024)
    strict_json(config_bytes)
    if sha256(config_bytes) != parent["config_sha256"]:
        raise ValueError("codec configuration binding")
    payload = bounded_read(packed_directory / "adapter.quantized", MAX_PACKED_BYTES)
    if (
        sha256(payload) != codec["payload_sha256"]
        or len(payload) != codec["payload_bytes"]
    ):
        raise ValueError("packed tensor content binding")
    state = decode_tensors(
        payload, expected_layout=parent["tensor_layout"], expected_bits=codec["bits"]
    )
    actual_state = state_digest(state)
    metrics = codec["metrics"]
    count = sum(t.numel() for t in state.values())
    expected_metrics = {
        "bits",
        "scalar_count",
        "decoded_tensor_bytes",
        "packed_bytes",
        "max_absolute_error",
        "mean_squared_error",
        "source_state_sha256",
        "decoded_state_sha256",
    }
    measured = dict(
        bits=codec["bits"],
        scalar_count=count,
        decoded_tensor_bytes=count * 4,
        packed_bytes=len(payload),
    )
    if (
        type(metrics) is not dict
        or set(metrics) != expected_metrics
        or any(
            type(metrics[k]) is not int or metrics[k] != v for k, v in measured.items()
        )
        or any(
            type(metrics[k]) not in (int, float)
            or not math.isfinite(metrics[k])
            or metrics[k] < 0
            for k in ("max_absolute_error", "mean_squared_error")
        )
        or any(
            type(metrics[k]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", metrics[k]) is None
            for k in ("source_state_sha256", "decoded_state_sha256")
        )
        or (
            "adapter_state_sha256" in parent["training"]
            and parent["training"]["adapter_state_sha256"]
            != metrics["source_state_sha256"]
        )
    ):
        raise ValueError("codec metric bounds or inherited state identity")
    state_bytes = save(state, metadata={"format": "pt"})
    if (
        actual_state != codec["metrics"]["decoded_state_sha256"]
        or sha256(state_bytes) != codec["decoded_safetensors_sha256"]
        or len(state_bytes) != codec["decoded_safetensors_bytes"]
    ):
        raise ValueError("decoded tensor identity mismatch")
    derivation = dict(
        schema="hepta.memory-lossy-derivation.v1",
        operation="symmetric_tensor_quantization",
        bits=codec["bits"],
        optimizer_steps=0,
        lossy_derivation=True,
        learned_parent_manifest_sha256=codec["parent_manifest_sha256"],
        parent_training_receipt_sha256=sha256(canonical_bytes(parent["training"])),
        source_adapter_sha256=parent["adapter_sha256"],
        codec_manifest_sha256=expected_codec_sha256,
        adapter_state_sha256=actual_state,
        inherited_roots=parent["roots"],
        roots=parent["roots"],
        source_training_receipt_retained="source-lineage.json",
        production_accepted=False,
    )
    lineage = parent | dict(adapter_sha256=sha256(state_bytes), training=derivation)
    lineage_bytes = canonical_bytes(lineage)
    files = {
        "adapter_model.safetensors": state_bytes,
        "adapter_config.json": config_bytes,
        "source-lineage.json": original,
        "codec-receipt.json": codec_bytes,
        "lineage.json": lineage_bytes,
    }
    total = _write_new(destination, files)
    return dict(
        manifest_sha256=sha256(lineage_bytes),
        adapter_sha256=sha256(state_bytes),
        adapter_state_sha256=actual_state,
        parent_manifest_sha256=codec["parent_manifest_sha256"],
        roots=parent["roots"],
        materialized_checkpoint_bytes=total,
        decoded_tensor_bytes=count * 4,
        quantized_execution=False,
        production_accepted=False,
    )
