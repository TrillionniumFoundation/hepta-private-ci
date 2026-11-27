"""Bounded numerical evidence and exact source identities for CPU-budget runs."""

import json
from pathlib import Path

import numpy as np

from experiments.continuous_spiking_network.records import digest_bytes, write_json


def write_arrays(directory, arrays, raw_chunk_bytes=300000):
    """Save all array bytes losslessly in independently hashed bounded shards."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    metadata, buffers, offset = {}, [], 0
    for name, values in sorted(arrays.items()):
        array = np.asarray(values)
        if array.dtype.hasobject:
            raise ValueError("object arrays cannot be numerical evidence")
        raw = array.tobytes(order="C")
        metadata[name] = {
            "dtype": array.dtype.str,
            "shape": list(array.shape),
            "offset": offset,
            "nbytes": len(raw),
            "sha256": digest_bytes(raw),
        }
        buffers.append(raw)
        offset += len(raw)
    packed, parts = b"".join(buffers), []
    for number, start in enumerate(range(0, len(packed), raw_chunk_bytes)):
        filename = f"arrays_{number:03d}.npz"
        path = directory / filename
        np.savez_compressed(
            path,
            bytes=np.frombuffer(packed[start : start + raw_chunk_bytes], np.uint8),
        )
        parts.append({"file": filename, "sha256": digest_bytes(path.read_bytes())})
    manifest = {
        "format": "hcsn_followup_arrays_v1",
        "arrays": metadata,
        "parts": parts,
        "nbytes": len(packed),
    }
    write_json(directory / "manifest.json", manifest)
    return digest_bytes((directory / "manifest.json").read_bytes())


def load_arrays(directory):
    """Reject changed shard bytes, metadata ranges and array hashes on read."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest["format"] != "hcsn_followup_arrays_v1":
        raise ValueError("unknown numerical evidence format")
    pieces = []
    for part in manifest["parts"]:
        path = directory / part["file"]
        if digest_bytes(path.read_bytes()) != part["sha256"]:
            raise ValueError("numerical evidence shard hash mismatch")
        with np.load(path, allow_pickle=False) as archive:
            pieces.append(archive["bytes"].tobytes())
    packed, result, expected_offset = b"".join(pieces), {}, 0
    if len(packed) != manifest["nbytes"]:
        raise ValueError("numerical evidence length mismatch")
    for name, item in sorted(manifest["arrays"].items()):
        dtype = np.dtype(item["dtype"])
        if dtype.hasobject or item["offset"] != expected_offset:
            raise ValueError("invalid array dtype or byte range")
        expected_bytes = int(np.prod(item["shape"], dtype=np.int64)) * dtype.itemsize
        if expected_bytes != item["nbytes"]:
            raise ValueError("array shape and byte count disagree")
        raw = packed[item["offset"] : item["offset"] + item["nbytes"]]
        if digest_bytes(raw) != item["sha256"]:
            raise ValueError("numerical array hash mismatch")
        result[name] = np.frombuffer(raw, dtype=dtype).reshape(item["shape"]).copy()
        expected_offset += item["nbytes"]
    if expected_offset != len(packed):
        raise ValueError("unaccounted numerical evidence bytes")
    return result


def source_arrays(bundle):
    arrays = {}
    for split_name in ("train", "val", "test"):
        split = getattr(bundle, split_name)
        arrays[f"{split_name}_sample_ids"] = split.sample_ids
        arrays[f"{split_name}_group_ids"] = split.group_ids
        for key in (
            "image_source_ids",
            "audio_source_ids",
            "query_modalities",
            "image_labels",
            "audio_labels",
        ):
            if key in split.metadata:
                arrays[f"{split_name}_{key}"] = np.asarray(split.metadata[key])
    return arrays
