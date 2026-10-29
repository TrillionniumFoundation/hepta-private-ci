"""Export existing inventory TensorCell weights without training or changing values.

The result is a numeric artifact, not an Agentd publication or an authenticated
owner snapshot. Native admission and feature provenance remain separate owners.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

import numpy as np


SCHEMA = "hepta.memory.residual-native.v1"
NUMERIC_PROFILE = "hepta.memory.f32-factored-residual.v1"
MAX_BYTES = 4 * 1024 * 1024
BLOB_CAP = 512000
CHUNK_ELEMENTS = 100000


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def valid_digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) and value != "0" * 64


def read_regular(path, limit):
    if any(item.is_symlink() for item in (path, *path.parents)) or not path.is_file():
        raise ValueError("regular nonsymlink checkpoint file required")
    if not 1 <= path.stat().st_size <= limit:
        raise ValueError("checkpoint file size outside bound")
    raw = path.read_bytes()
    if not 1 <= len(raw) <= limit:
        raise ValueError("checkpoint changed size")
    return raw


def export_checkpoint(directory):
    root = Path(directory).absolute()
    manifest_raw = read_regular(root / "manifest.json", BLOB_CAP)
    manifest = json.loads(manifest_raw)
    if (manifest["schema"] != "memory-adapter.checkpoint.v1"
            or manifest["dtype"] != "float32" or manifest["base_operator"] != "identity"):
        raise ValueError("unsupported TensorCell checkpoint")
    config = manifest["config"]
    dimension, rank = config["input_dim"], config["rank"]
    if type(dimension) is not int or dimension != 384 or type(rank) is not int or not 1 <= rank <= 384:
        raise ValueError("unsupported residual shape")
    specifications = config["outputs"]
    semantic = [{"name": "bits", "kind": "binary", "size": 12, "weight": 1.0}]
    skill = [{"name": f"op{i}", "kind": "multiclass", "size": 7, "weight": 1.0} for i in range(4)]
    if specifications == semantic:
        profile, width = "inventory_semantic", 12
    elif specifications == skill:
        profile, width = "inventory_skill", 28
    else:
        raise ValueError("checkpoint is not the registered inventory output profile")
    sources = manifest["source_ids"]
    if (not valid_digest(manifest["base_encoder_sha"]) or not valid_digest(manifest["parameter_sha256"])
            or not isinstance(sources, list) or not 1 <= len(sources) <= 4096
            or not all(valid_digest(source) for source in sources) or sources != sorted(set(sources))):
        raise ValueError("invalid encoder, parameter or source identity")
    shapes = {"A": [rank, dimension], "B": [dimension, rank],
              "head.bias": [width], "head.weight": [width, dimension]}
    if set(manifest["tensors"]) != set(shapes):
        raise ValueError("unexpected tensor inventory")
    parameters, tensors = bytearray(), {}
    for name, shape in shapes.items():
        descriptor = manifest["tensors"][name]
        if descriptor["shape"] != shape or not isinstance(descriptor["parts"], list):
            raise ValueError("tensor shape mismatch")
        count = int(np.prod(shape))
        if len(descriptor["parts"]) != (count + CHUNK_ELEMENTS - 1) // CHUNK_ELEMENTS:
            raise ValueError("tensor chunk count mismatch")
        chunks = []
        for index, part in enumerate(descriptor["parts"]):
            if part["file"] != f"{name}.{index:04d}.npz":
                raise ValueError("invalid tensor chunk path")
            raw = read_regular(root / part["file"], BLOB_CAP)
            if len(raw) != part["bytes"] or digest(raw) != part["sha256"]:
                raise ValueError("tensor chunk identity mismatch")
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if archive.namelist() != ["values.npy"] or archive.infolist()[0].file_size > 4 * CHUNK_ELEMENTS + 4096:
                    raise ValueError("unbounded tensor archive")
            with np.load(io.BytesIO(raw), allow_pickle=False) as archive:
                values = archive["values"]
                expected = min(CHUNK_ELEMENTS, count - index * CHUNK_ELEMENTS)
                if values.dtype != np.dtype("<f4") or values.shape != (expected,) or not np.isfinite(values).all():
                    raise ValueError("invalid float32 tensor chunk")
                chunks.append(values.astype("<f4", copy=False).tobytes())
        tensor_raw = b"".join(chunks)
        parameters.extend(canonical([name, shape, "float32"]))
        parameters.extend(tensor_raw)
        tensors[name] = {"shape": shape, "f32le_hex": tensor_raw.hex()}
    if digest(parameters) != manifest["parameter_sha256"]:
        raise ValueError("original parameter digest mismatch")
    history = manifest["training_history"]
    if not isinstance(history, list) or not history or history[-1]["final_parameter_sha256"] != digest(parameters):
        raise ValueError("no matching completed training receipt")
    result = {"schema": SCHEMA, "numeric_profile": NUMERIC_PROFILE,
              "output_profile": profile, "dimension": dimension, "rank": rank,
              "encoder_sha256": manifest["base_encoder_sha"],
              "checkpoint_manifest_sha256": digest(manifest_raw),
              "training_history_sha256": digest(canonical(history)),
              "parameter_sha256": digest(parameters), "lineage_sources": sources, "tensors": tensors}
    if len(canonical(result)) > MAX_BYTES:
        raise ValueError("native artifact exceeds size bound")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    payload = canonical(export_checkpoint(args.checkpoint))
    with args.output.open("xb") as output:
        output.write(payload)
    print(json.dumps({"bytes": len(payload), "sha256": digest(payload), "fitting_performed": False}))


if __name__ == "__main__":
    main()
