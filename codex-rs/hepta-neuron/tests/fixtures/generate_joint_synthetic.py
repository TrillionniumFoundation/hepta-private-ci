#!/usr/bin/env python3
"""Encode synthetic legal HPS tensors; never train, load or execute a model.

The inventory matches joint_generation/proposal_test_support.rs. Zero weights,
unit normalization and an explicit STOP bias are artificial test values, not a
trained checkpoint. The JSON fixes every expanded byte and its SHA-256.
"""

import hashlib
import json
from pathlib import Path
import re
import struct


def packet(metadata, tensors):
    data = bytearray(b"HEPTAPK3")

    def integer(value):
        data.extend(struct.pack("<I", value))

    def text(value):
        encoded = value.encode("utf-8")
        integer(len(encoded))
        data.extend(encoded)

    integer(len(metadata))
    for key, value in sorted(metadata.items()):
        text(key)
        text(value)
    integer(len(tensors))
    for key, (shape, values) in sorted(tensors.items()):
        text(key)
        integer(len(shape))
        for dimension in shape:
            integer(dimension)
        integer(len(values))
        for value in values:
            data.extend(struct.pack("<d", value))
    data.extend(hashlib.sha256(data).hexdigest().encode("ascii"))
    return bytes(data)


def compressed(data, tensor_count):
    runs = []
    offset = 0
    zeros = 0
    for match in re.finditer(b"\x00{16,}", data):
        if match.start() > offset:
            runs.append([zeros, data[offset:match.start()].hex()])
        zeros = match.end() - match.start()
        offset = match.end()
    runs.append([zeros, data[offset:].hex()])
    rebuilt = b"".join(bytes(count) + bytes.fromhex(literal) for count, literal in runs)
    assert rebuilt == data
    return {
        "expanded_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "tensor_count": tensor_count,
        "runs": runs,
    }


def tensors():
    weights = {}

    def add(name, shape, value=0.0):
        size = 1
        for dimension in shape:
            size *= dimension
        weights[name] = (shape, [value] * size)

    for name, output, width in [
        ("image_encoder.0", 32, 1536),
        ("audio_encoder.0", 32, 2048),
        ("video_encoder.0", 32, 128),
        ("encoder_fusion.0", 32, 128),
        ("initial_slots", 128, 32),
        ("feedback_projection", 32, 3),
        ("transition_input", 32, 96),
        ("emissions.text", 80, 64),
    ]:
        add(f"{name}.weight", [output, width])
        add(f"{name}.bias", [output])
    add("token_encoder.weight", [128, 32])
    add("action_embedding.weight", [5, 32])
    for modality in ["image", "audio", "video", "text"]:
        add(f"adapters.{modality}.0.weight", [32, 96])
        add(f"adapters.{modality}.0.bias", [32])
    for modality, hidden, output in [("image", 64, 768), ("audio", 64, 1024), ("video", 96, 3072)]:
        for layer, height, width in [(0, hidden, 64), (2, output, hidden)]:
            add(f"emissions.{modality}.{layer}.weight", [height, width])
            add(f"emissions.{modality}.{layer}.bias", [height])
    for name in ["actor", "critic", "delivery_critic"]:
        add(f"{name}.0.weight", [32, 69])
        add(f"{name}.0.bias", [32])
        add(f"{name}.2.weight", [7 if name == "actor" else 1, 32])
        add(f"{name}.2.bias", [7 if name == "actor" else 1])
    weights["actor.2.bias"] = ([7], [0.0] * 6 + [4.0])
    for name in ["drift_bias", "raw_diffusion", "raw_recovery", "raw_regeneration", "raw_adaptation", "raw_adaptation_decay", "raw_content_rate", "raw_boundary"]:
        add(f"core.layers.0.{name}", [32])
    for name in ["drift_input", "content_state", "output", "content_input"]:
        add(f"core.layers.0.{name}.weight", [32, 32])
    for name, shape, value in [("content_input.bias", [32], 0.0), ("channel_gates.weight", [64, 64], 0.0), ("channel_gates.bias", [64], 0.0), ("norm.weight", [32], 1.0), ("norm.bias", [32], 0.0)]:
        add(f"core.layers.0.{name}", shape, value)
    assert len(weights) == 67
    assert sum(len(values) for _, values in weights.values()) == 596985
    return weights


def main():
    weights = packet({
        "kind": "joint-generator-weights-v3", "width": "32", "depth": "1",
        "mode": "dual", "boundary": "direct", "numeric_profile": "fp64-linux-libm-v1",
        "allow_initial_stop": "false", "suppress_redundant_verify": "false",
    }, tensors())
    public_tensors = {}
    for name, shape in [
        ("image", [1, 3, 16, 16]), ("image_mask", [1, 3, 16, 16]),
        ("audio", [1, 1024]), ("audio_mask", [1, 1024]),
        ("video", [1, 4, 3, 16, 16]), ("video_mask", [1, 4, 3, 16, 16]),
        ("tokens", [1, 1]),
    ]:
        size = 1
        for dimension in shape:
            size *= dimension
        public_tensors[name] = (shape, [0.0] * size)
    public = packet({"kind": "joint-generator-public-v3"}, public_tensors)
    document = {
        "schema_version": 1,
        "synthetic": True,
        "source_fixture": "hepta-infer-worker-host/src/joint_generation/proposal_test_support.rs",
        "description": "Artificial 67-tensor zero model with unit normalization and STOP bias; no training or trained-checkpoint qualification.",
        "weights": compressed(weights, 67),
        "public": compressed(public, 7),
    }
    destination = Path(__file__).with_name("joint-synthetic-v1.json")
    destination.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: {key: value for key, value in document[name].items() if key != "runs"} for name in ["weights", "public"]}))


if __name__ == "__main__":
    main()
