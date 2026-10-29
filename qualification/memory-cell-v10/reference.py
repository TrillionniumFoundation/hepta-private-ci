"""Independent saved-byte reader: no trainer, corpus, targets or Torch import."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def identity(arrays):
    hasher = hashlib.sha256()
    for name in sorted(arrays):
        array = arrays[name].astype("<f4")
        hasher.update(canonical([name, list(array.shape), "float32"]))
        hasher.update(array.tobytes())
    return hasher.hexdigest()


def load_checkpoint(directory):
    root = Path(directory)
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest["schema"] != "hepta.memory.v10.numpy-checkpoint.v1":
        raise ValueError("unsupported checkpoint schema")
    arrays = {}
    for name, entry in manifest["arrays"].items():
        if entry["file"] != f"{name}.f32" or "/" in name or "\\" in name:
            raise ValueError("invalid tensor path")
        raw = (root / entry["file"]).read_bytes()
        if len(raw) != entry["bytes"] or digest(raw) != entry["sha256"] or len(raw) > 32 * 1024 * 1024:
            raise ValueError("parameter byte identity mismatch")
        array = np.frombuffer(raw, dtype="<f4").reshape(entry["shape"])
        if not np.isfinite(array).all():
            raise ValueError("nonfinite checkpoint")
        arrays[name] = array.copy()
    if identity(arrays) != manifest["parameter_sha256"]:
        raise ValueError("combined parameter digest mismatch")
    return arrays, manifest


def forward(arrays, features, *, operator="residual"):
    """Separate float64 implementation for research fresh-process reads."""
    x = np.asarray(features, dtype=np.float64)
    a = {name: value.astype(np.float64) for name, value in arrays.items()}
    z = x if "A" not in a else x + (x @ a["A"].T) @ a["B"].T
    if operator == "joint_block_head":
        left = z[:, :384] @ a["head.semantic.weight"].T + a["head.semantic.bias"]
        right = z[:, 384:] @ a["head.procedure.weight"].T + a["head.procedure.bias"]
        return np.concatenate((left, right), axis=1)
    return z @ a["head.weight"].T + a["head.bias"]


def scalar_forward(arrays, features):
    """Native parity uses explicit left-to-right float64 reductions, no FMA."""
    outputs = []
    for row in features:
        x = [float(value) for value in row]
        u = []
        for weights in arrays["A"]:
            value = 0.0
            for weight, coordinate in zip(weights, x, strict=True):
                value = value + float(weight) * coordinate
            u.append(value)
        z = []
        for coordinate, weights in zip(x, arrays["B"], strict=True):
            value = 0.0
            for weight, hidden in zip(weights, u, strict=True):
                value = value + float(weight) * hidden
            z.append(coordinate + value)
        logits = []
        for bias, weights in zip(arrays["head.bias"], arrays["head.weight"], strict=True):
            value = float(bias)
            for weight, hidden in zip(weights, z, strict=True):
                value = value + float(weight) * hidden
            logits.append(value)
        outputs.append(logits)
    return np.asarray(outputs, dtype=np.float64)


def decode(raw, kind, minimum_margin=0.001):
    raw = np.asarray(raw)
    rows = []
    for logits in raw:
        if kind == "semantic":
            margin = float(np.min(np.abs(logits)))
            bits = logits >= 0
            value = [sum(int(bits[i * 4 + j]) << j for j in range(4)) for i in range(3)]
        elif kind == "procedure":
            groups = logits.reshape(4, 7)
            ordered = np.sort(groups, axis=1)
            margin = float(np.min(ordered[:, -1] - ordered[:, -2]))
            value = np.argmax(groups, axis=1).tolist()
        else:
            raise ValueError("unsupported typed output")
        rows.append({"value": value if margin >= minimum_margin and margin > 0 else None,
                     "minimum_margin": margin, "accepted": margin >= minimum_margin and margin > 0})
    return rows


def native_read(path):
    raw = Path(path).read_bytes()
    model = json.loads(raw)
    if model["schema"] != "hepta.memory.residual-native.v1":
        raise ValueError("native profile mismatch")
    arrays = {name: np.frombuffer(bytes.fromhex(entry["f32le_hex"]), dtype="<f4").reshape(entry["shape"])
              for name, entry in model["arrays"].items()}
    if identity(arrays) != model["parameter_sha256"]:
        raise ValueError("native parameter hash mismatch")
    keys = sorted(model["features"])
    vectors = []
    for key in keys:
        entry = model["features"][key]
        payload = bytes.fromhex(entry["f32le_hex"])
        if digest(payload) != entry["feature_sha256"]:
            raise ValueError("feature digest mismatch")
        vectors.append(np.frombuffer(payload, dtype="<f4"))
    raw64 = scalar_forward(arrays, vectors)
    x = np.asarray(vectors, dtype=np.float32)
    raw32 = (x + (x @ arrays["A"].T) @ arrays["B"].T) @ arrays["head.weight"].T + arrays["head.bias"]
    typed = decode(raw64, model["kind"], model["minimum_margin"])
    return {"artifact_sha256": digest(raw), "parameter_sha256": identity(arrays), "kind": model["kind"],
            "rows": [{"address_sha256": key, "raw_logits": logits.tolist(),
                      "source_ids": model["supports"][key], **value}
                     for key, logits, value in zip(keys, raw64, typed, strict=True)],
            "numpy_f32_max_absolute_error": float(np.max(np.abs(raw32.astype(np.float64) - raw64))),
            "numpy_f32_within_declared_tolerance": bool(np.allclose(raw32, raw64, rtol=1e-5, atol=1e-4)),
            "numpy_f32_typed_outputs_equal": [x["value"] for x in decode(raw32, model["kind"], model["minimum_margin"])]
            == [x["value"] for x in typed],
            "reference": "independent scalar f64 factored reduction", "torch_executed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--features", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.native:
        result = native_read(args.native)
    else:
        arrays, manifest = load_checkpoint(args.checkpoint)
        with np.load(args.features, allow_pickle=False) as archive:
            features = archive["features"]
        raw = forward(arrays, features, operator=manifest["operator"])
        result = {"parameter_sha256": manifest["parameter_sha256"], "raw_logits": raw.tolist()}
    args.output.write_bytes(canonical(result))


if __name__ == "__main__":
    main()
