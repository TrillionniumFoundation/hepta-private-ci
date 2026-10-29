"""Export exact saved residual parameters; never fit or select using outcomes.

An owner source map is an explicit provenance migration input. This exporter
checks its coverage and preserves it in a separate receipt; the native owner
must independently authenticate the cut and current dependencies.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

import numpy as np


DIGEST = re.compile(r"[0-9a-f]{64}")
CAP = 32 * 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def valid_digest(value):
    return isinstance(value, str) and DIGEST.fullmatch(value) and value != "0" * 64


def parameter_digest(arrays):
    result = hashlib.sha256()
    for name, value in sorted(arrays.items()):
        array = np.asarray(value, dtype="<f4")
        result.update(canonical([name, list(array.shape), "float32"]))
        result.update(array.tobytes())
    return result.hexdigest()


def load_original_checkpoint(directory):
    """Decode the frozen Torch checkpoint transport without importing Torch."""
    root = Path(directory)
    raw = (root / "manifest.json").read_bytes()
    if len(raw) > CAP:
        raise ValueError("oversized checkpoint manifest")
    manifest = json.loads(raw)
    if manifest.get("schema") != "memory-adapter.checkpoint.v1" or manifest.get("dtype") != "float32":
        raise ValueError("unsupported original checkpoint")
    dimension, rank = manifest["config"]["input_dim"], manifest["config"]["rank"]
    width = sum(item["size"] for item in manifest["config"]["outputs"])
    expected = {"A": [rank, dimension], "B": [dimension, rank],
                "head.weight": [width, dimension], "head.bias": [width]}
    if dimension != 384 or not 1 <= rank <= 64 or width not in (12, 28):
        raise ValueError("unsupported residual checkpoint shape")
    if set(manifest["tensors"]) != set(expected):
        raise ValueError("unexpected checkpoint tensor")
    arrays = {}
    for name, shape in expected.items():
        entry = manifest["tensors"][name]
        if entry["shape"] != shape or not 1 <= len(entry["parts"]) <= 64:
            raise ValueError("tensor layout mismatch")
        chunks = []
        for index, part in enumerate(entry["parts"]):
            if part["file"] != f"{name}.{index:04d}.npz":
                raise ValueError("invalid original tensor path")
            payload = (root / part["file"]).read_bytes()
            if len(payload) > 512000 or len(payload) != part["bytes"] or sha(payload) != part["sha256"]:
                raise ValueError("original tensor digest mismatch")
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                if archive.namelist() != ["values.npy"] or archive.infolist()[0].file_size > 404096:
                    raise ValueError("unsafe original tensor archive")
            with np.load(io.BytesIO(payload), allow_pickle=False) as archive:
                chunk = archive["values"]
                if chunk.ndim != 1 or chunk.dtype != np.dtype("float32") or len(chunk) > 100000:
                    raise ValueError("original tensor dtype mismatch")
                chunks.append(chunk.copy())
        joined = np.concatenate(chunks)
        if joined.size != int(np.prod(shape)) or not np.isfinite(joined).all():
            raise ValueError("invalid reconstructed parameter")
        arrays[name] = joined.reshape(shape).astype("<f4")
    if parameter_digest(arrays) != manifest["parameter_sha256"]:
        raise ValueError("original parameter identity mismatch")
    return arrays, manifest, sha(raw)


def export(arrays, *, kind, encoder_sha256, owner_cut_sha256, checkpoint_sha256,
           training_history, source_ids, addresses, features, source_map, minimum_margin=0.001):
    if kind not in ("semantic", "procedure"):
        raise ValueError("unsupported native output kind")
    if not all(valid_digest(x) for x in (encoder_sha256, owner_cut_sha256, checkpoint_sha256)):
        raise ValueError("missing immutable artifact identity")
    if not np.isfinite(minimum_margin) or not 0 < minimum_margin <= 1e6:
        raise ValueError("invalid raw-logit selection margin")
    width = 12 if kind == "semantic" else 28
    rank = arrays["A"].shape[0]
    expected = {"A": (rank, 384), "B": (384, rank),
                "head.weight": (width, 384), "head.bias": (width,)}
    if set(arrays) != set(expected) or not 1 <= rank <= 64:
        raise ValueError("invalid parameter layout")
    tensors = {}
    for name, shape in expected.items():
        array = np.asarray(arrays[name], dtype="<f4")
        if array.shape != shape or not np.isfinite(array).all():
            raise ValueError("nonfinite or misshaped tensor")
        tensors[name] = {"shape": list(shape), "f32le_hex": array.tobytes().hex()}
    if not source_ids or set(source_map) != set(source_ids):
        raise ValueError("source migration must exactly cover complete training lineage")
    if not all(valid_digest(value) for value in source_map.values()):
        raise ValueError("canonical owner source identity required")
    if len(set(source_map.values())) != len(source_map):
        raise ValueError("source migration must preserve one-to-one canonical record bindings")
    lineage = sorted(set(source_map.values()))
    if not 1 <= len(lineage) <= 65536 or not 1 <= len(addresses) <= 4096:
        raise ValueError("source or address count exceeds native bounds")
    features = np.asarray(features, dtype="<f4")
    if (features.shape != (len(addresses), 384) or not np.isfinite(features).all()
            or np.any(np.abs(features) > 1)):
        raise ValueError("invalid canonical feature cache")
    supports, cache = {}, {}
    for row, vector in zip(addresses, features, strict=True):
        key, text = row["key"], row["canonical_text"]
        if not isinstance(key, str) or not key or not isinstance(text, str) or not text:
            raise ValueError("canonical address and encoder input required")
        address = sha(key.encode())
        if address in supports or not 1 <= len(row["source_ids"]) <= 128:
            raise ValueError("duplicate address or invalid support")
        ids = sorted({source_map[x] for x in row["source_ids"]})
        raw = vector.tobytes()
        supports[address] = ids
        cache[address] = {"canonical_text_sha256": sha(text.encode()),
                          "feature_sha256": sha(raw), "f32le_hex": raw.hex()}
    envelope = {
        "schema": "hepta.memory.residual-native.v1", "kind": kind,
        "address_profile": "hepta.memory.canonical-minilm-cache.v1",
        "numeric_profile": "hepta.memory.f32-f64-residual.v1",
        "output_profile": "hepta.memory.inventory-policy.bits12.v1" if kind == "semantic"
        else "hepta.memory.inventory-program.ops4x7.v1",
        "dimension": 384, "rank": rank, "minimum_margin": minimum_margin,
        "encoder_sha256": encoder_sha256, "owner_cut_sha256": owner_cut_sha256,
        "parameter_sha256": parameter_digest(arrays), "checkpoint_sha256": checkpoint_sha256,
        "training_receipt_sha256": sha(canonical(training_history)),
        "supports": supports, "lineage_sources": lineage, "features": cache, "arrays": tensors,
    }
    payload = canonical(envelope)
    if len(payload) > CAP:
        raise ValueError("native envelope exceeds 32 MiB")
    receipt = {"schema": "hepta.memory.native-export-receipt.v1", "artifact_sha256": sha(payload),
               "artifact_bytes": len(payload), "parameter_sha256": envelope["parameter_sha256"],
               "original_checkpoint_sha256": checkpoint_sha256,
               "original_source_ids": sorted(source_ids), "owner_source_map": source_map,
               "owner_source_map_sha256": sha(canonical(source_map)),
               "owner_cut_sha256": owner_cut_sha256, "features_sha256": sha(features.tobytes()),
               "canonical_input_texts_sha256": sha(canonical([x["canonical_text"] for x in addresses])),
               "training_performed": False, "held_outcomes_read": False,
               "owner_authentication_claimed_by_exporter": False,
               "cost": {"parameter_bytes": sum(x.nbytes for x in arrays.values()),
                        "feature_bytes": features.nbytes, "serialized_bytes": len(payload)}}
    return payload, receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--kind", choices=("semantic", "procedure"), required=True)
    parser.add_argument("--owner-cut-sha256", required=True)
    parser.add_argument("--source-map", type=Path, required=True)
    parser.add_argument("--addresses", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    arrays, manifest, checkpoint_sha = load_original_checkpoint(args.checkpoint)
    with np.load(args.features, allow_pickle=False) as archive:
        features = archive["features"]
    payload, receipt = export(arrays, kind=args.kind, encoder_sha256=manifest["base_encoder_sha"],
                              owner_cut_sha256=args.owner_cut_sha256, checkpoint_sha256=checkpoint_sha,
                              training_history=manifest["training_history"], source_ids=manifest["source_ids"],
                              addresses=json.loads(args.addresses.read_text()), features=features,
                              source_map=json.loads(args.source_map.read_text()))
    args.output.write_bytes(payload)
    args.receipt.write_bytes(canonical(receipt))


if __name__ == "__main__":
    main()
