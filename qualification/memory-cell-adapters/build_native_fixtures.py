"""Create numeric regression fixtures from the preserved formal-01 checkpoints.

Uses only canonical features and trained parameters; no held questions, labels,
training or model selection. NumPy is an independent float32 operator reference.
"""

import argparse
import json
from pathlib import Path

import numpy as np

from export_native import canonical, digest, export_checkpoint


def build(restored, archive_index, destination):
    index = json.loads(archive_index.read_bytes())
    required = ["canonical.npz"]
    for seed in (731, 732, 733):
        for kind in ("semantic", "skill"):
            prefix = f"models/seed-{seed}/{kind}/"
            required.extend(path for path in index["files"] if path.startswith(prefix))
    for relative in required:
        raw = (restored / relative).read_bytes()
        if {"bytes": len(raw), "sha256": digest(raw)} != index["files"][relative]:
            raise ValueError(f"original archive member differs: {relative}")
    with np.load(restored / "canonical.npz", allow_pickle=False) as cached:
        features = {kind: cached[kind].copy() for kind in ("semantic", "skill")}
    destination.mkdir(parents=True, exist_ok=False)
    for seed in (731, 732, 733):
        for kind in ("semantic", "skill"):
            artifact = export_checkpoint(restored / "models" / f"seed-{seed}" / kind)
            arrays = {name: np.frombuffer(bytes.fromhex(item["f32le_hex"]), dtype="<f4").reshape(item["shape"])
                      for name, item in artifact["tensors"].items()}
            x = features[kind]
            if x.shape != (8, 384) or x.dtype != np.dtype("float32") or not np.isfinite(x).all():
                raise ValueError("canonical encoder feature contract differs")
            logits = (x + (x @ arrays["A"].T) @ arrays["B"].T) @ arrays["head.weight"].T + arrays["head.bias"]
            cases = []
            for vector, raw in zip(x, logits, strict=True):
                if kind == "semantic":
                    bits = (1 / (1 + np.exp(-raw))) >= 0.5
                    values = [sum(int(bits[4 * field + bit]) << bit for bit in range(4)) for field in range(3)]
                    value = dict(kind="semantic", reserve=values[0], pack=values[1], limit=values[2])
                else:
                    value = dict(kind="skill", program=[int(raw[step * 7:(step + 1) * 7].argmax()) for step in range(4)])
                cases.append(dict(features=vector.tolist(), logits=raw.tolist(), value=value))
            payload = canonical(artifact)
            fixture = {"schema": "hepta.memory.residual-numeric-fixture.v1", "seed": seed,
                       "original_archive_sha256": index["archive"]["sha256"],
                       "canonical_feature_file_sha256": index["files"]["canonical.npz"]["sha256"],
                       "reference": "NumPy float32, original factored operator, canonical inputs only",
                       "artifact_json": payload.decode(), "artifact_sha256": digest(payload),
                       "parameter_sha256": artifact["parameter_sha256"],
                       "encoder_sha256": artifact["encoder_sha256"], "cases": cases}
            encoded = canonical(fixture)
            if len(encoded) >= 512000:
                raise ValueError("fixture exceeds repository blob limit")
            (destination / f"seed-{seed}-{kind}.json").write_bytes(encoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("restored", type=Path)
    parser.add_argument("archive_index", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    build(args.restored, args.archive_index, args.destination)


if __name__ == "__main__":
    main()
