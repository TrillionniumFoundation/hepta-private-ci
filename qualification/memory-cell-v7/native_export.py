"""Deterministically export trained V6 float32 parameters for the native reader.

The original model remains the training/calibration evidence. All parameter bits,
catalog values, support IDs and training lineage are retained. This performs no
training, quantization, source remapping or threshold selection.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT.parent / "memory-cell-v6"))

from v6.cells import AssociativeCell
from v6.cells import canonical
from v6.values import validate_typed_value


def export_cell(raw):
    cell = AssociativeCell.from_bytes(raw)
    for value in cell.catalog:
        validate_typed_value(cell.kind, value)
    all_sources = set(cell.lineage_sources)
    all_sources.update(source for sources in cell.supports.values() for source in sources)
    for source in all_sources:
        if len(source) != 64 or any(character not in "0123456789abcdef" for character in source) or int(source, 16) == 0:
            raise ValueError("native source identities must be nonzero lowercase SHA-256 digests")
    if any(sources != sorted(set(sources)) for sources in cell.supports.values()):
        raise ValueError("source support must already be canonical; exporter does not rewrite lineage")
    result = {
        "schema": "hepta.memory.associative-native.v1",
        "kind": cell.kind,
        "address_profile": "hepta.memory.sha256-shake256-f64.v1",
        "numeric_profile": "hepta.memory.f32-weights-f64-tanh-softmax.v1",
        "dimension": cell.dimension,
        "hidden": cell.hidden,
        "catalog": cell.catalog,
        "supports": cell.supports,
        "lineage_sources": cell.lineage_sources,
        "threshold": cell.threshold,
        "acceptance_enabled": cell.acceptance_enabled,
        "parameter_sha256": cell.parameters_digest(),
        "original_artifact_sha256": hashlib.sha256(raw).hexdigest(),
        "training_receipt_sha256": hashlib.sha256(canonical(cell.training_receipt)).hexdigest(),
        "arrays": {
            label: getattr(cell, name).reshape(-1).tolist()
            for label, name in (("input_weights", "A"), ("hidden_bias", "a"), ("output_weights", "B"), ("output_bias", "b"))
        },
    }
    encoded = canonical(result) + b"\n"
    if len(encoded) > 32_000_000:
        raise ValueError("native artifact exceeds the reader byte limit")
    return encoded


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    native = export_cell(args.cell.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as stream:
        stream.write(native)
    print(json.dumps({"native_sha256": hashlib.sha256(native).hexdigest(), "native_bytes": len(native)}))
