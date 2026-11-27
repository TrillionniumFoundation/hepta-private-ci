"""Independently reconstruct fixed quantized checkpoints and their answer quality."""

import json
import math
from pathlib import Path
import struct

from population_audit_artifacts import _checkpoint, _hash, _json, _read, _require, _same
from population_audit_generation import _assessment, _journal, _metrics


def _codecs(directory, data, training, original, report):
    root = directory / "codec"
    _same(_json(root / "result.json"), report, "raw codec report")
    _require(
        report["fixed_candidate"] == "single"
        and report["primary_bits"] == 8
        and report["secondary_bits"] == 4
        and set(report["variants"]) == {"8", "4"},
        "precommitted codec candidates preserved",
    )
    probes = data["retention_final"] + data["transfer_final"] + data["ood_final"]
    original_version = training["versions"]["single"][0]
    original_checkpoint = _checkpoint(original_version)
    original_bytes = sum(
        p.stat().st_size
        for p in Path(original_version["directory"]).iterdir()
        if p.is_file()
    )
    for bits in (8, 4):
        variant = report["variants"][str(bits)]
        packed = root / f"int{bits}-packed"
        codec = _json(packed / "codec.json")
        _require(
            codec["bits"] == bits
            and codec["parent_manifest_sha256"] == original_version["manifest_sha256"]
            and codec["payload_sha256"] == _hash(_read(packed / "adapter.quantized")),
            "bound quantized source and payload",
        )
        _require(
            variant["encoding"]["codec_manifest_sha256"]
            == _hash(_read(packed / "codec.json")),
            "codec manifest receipt",
        )
        checkpoint = _checkpoint(variant["version"])
        _quantized_payload(
            _read(packed / "adapter.quantized"), bits, original_checkpoint, checkpoint
        )
        _require(
            codec["decoded_safetensors_sha256"]
            == _hash(
                _read(
                    Path(variant["version"]["directory"]) / "adapter_model.safetensors"
                )
            )
            and codec["metrics"]["source_state_sha256"] == original_checkpoint["state"]
            and codec["metrics"]["decoded_state_sha256"] == checkpoint["state"],
            "actual encoded and materialized tensor identity",
        )
        lineage = checkpoint["manifest"]["training"]
        _require(
            lineage["optimizer_steps"] == 0
            and lineage["bits"] == bits
            and lineage["learned_parent_manifest_sha256"]
            == original_version["manifest_sha256"],
            "codec zero-update derivation lineage",
        )
        journal = _journal(root, f"codec-{bits}", variant["version"], probes, {})
        rows = [
            _assessment(p, r, variant["version"], data["sources"])
            for p, r in zip(probes, journal["rows"], strict=True)
        ]
        metrics = _metrics(rows)
        _same(
            _json(root / f"int{bits}-assessments.json"),
            {"rows": rows, "metrics": metrics},
            "codec raw-answer assessment",
        )
        _same(variant["metrics"], metrics, "codec metrics")
        losses = {
            name: original["metrics"][name]["accuracy"] - metrics[name]["accuracy"]
            for name in ("retention", "transfer")
        }
        _same(variant["quality_loss"], losses, "codec measured quality losses")
        packed_bytes = sum(p.stat().st_size for p in packed.iterdir() if p.is_file())
        _require(
            variant["encoding"]["packed_artifact_bytes"] == packed_bytes,
            "complete encoded artifact bytes",
        )
        ratio = packed_bytes / original_bytes
        _same(variant["packed_complete_ratio"], ratio, "complete codec ratio")
        for key, value in (
            ("storage_ratio_gate", ratio <= 0.35),
            ("retention_loss_gate", losses["retention"] <= 0.02 + 1e-12),
            ("transfer_loss_gate", losses["transfer"] <= 0.02 + 1e-12),
            ("primary", bits == 8),
        ):
            _same(variant[key], value, "fixed codec gate")
        _require(
            variant["posthoc_selection"] is False
            and variant["quantized_execution"] is False,
            "no post-hoc codec or quantized execution claim",
        )
    primary = report["variants"]["8"]
    _same(
        report["primary_gate_passed"],
        all(
            primary[k]
            for k in (
                "storage_ratio_gate",
                "retention_loss_gate",
                "transfer_loss_gate",
                "owner_admitted_before_and_after",
            )
        ),
        "primary int8 failure cannot be replaced",
    )


def _quantized_payload(payload, bits, original, decoded):
    _require(payload[:8] == b"HEPTAQ01", "registered quantized payload")
    length = struct.unpack("<Q", payload[8:16])[0]
    _require(0 < length <= 2 * 1024 * 1024, "bounded codec header")
    header, body = json.loads(payload[16 : 16 + length]), payload[16 + length :]
    _require(
        header["bits"] == bits and header["decoded_dtype"] == "torch.float32",
        "actual quantization width",
    )
    _require(
        [r["name"] for r in header["tensors"]]
        == sorted(original["tensors"])
        == sorted(decoded["tensors"]),
        "quantized tensor inventory",
    )
    offset, bound = 0, (1 << (bits - 1)) - 1
    for row in header["tensors"]:
        shape, source = original["tensors"][row["name"]]
        count = math.prod(shape)
        size = count if bits == 8 else (count + 1) // 2
        _require(
            row["shape"] == shape and row["offset"] == offset and row["bytes"] == size,
            "contiguous codec tensor layout",
        )
        chunk = body[offset : offset + size]
        _require(len(chunk) == size, "complete quantized tensor")
        offset += size
        values = [v[0] for v in struct.iter_unpack("<f", source)]
        maximum = max(abs(v) for v in values)
        scale = maximum / bound if maximum else 1.0
        _same(row["scale"], scale, "source-derived symmetric quantization scale")
        if bits == 8:
            codes = [v[0] for v in struct.iter_unpack("<b", chunk)]
            _require(-128 not in codes, "no reserved int8 code")
        else:
            unsigned = [n for b in chunk for n in (b & 15, b >> 4)]
            _require(
                all(v <= 14 for v in unsigned[:count])
                and (count % 2 == 0 or unsigned[-1] == 0),
                "valid int4 code and padding",
            )
            codes = [v - bound for v in unsigned[:count]]
        _require(
            codes == [min(bound, max(-bound, round(v / scale))) for v in values],
            "quantization actually derived from retained source weights",
        )
        materialized = b"".join(struct.pack("<f", v * scale) for v in codes)
        _require(
            decoded["tensors"][row["name"]] == (shape, materialized),
            "independent packed-to-float32 reconstruction",
        )
    _require(offset == len(body), "no unclaimed packed tensor bytes")
