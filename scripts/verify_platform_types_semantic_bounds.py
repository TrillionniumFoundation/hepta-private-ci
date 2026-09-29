#!/usr/bin/env python3
"""Check the compiled Prompt V2 capacity against schema and frozen HPTC V1."""
import argparse
import hashlib
import json
from pathlib import Path


def verify(catalog, schema):
    protocols = [p for p in catalog["protocols"] if p["id"] == "PromptDeliveryObservationV2"]
    if len(protocols) != 1:
        raise ValueError("exactly one Prompt V2 descriptor required")
    fields = [f for f in protocols[0]["fields"] if f["name"] == "observed_token_positions"]
    if len(fields) != 1 or fields[0]["wireType"] != "required_nullable_u32_array":
        raise ValueError("Prompt positions field descriptor")
    maximum = fields[0].get("maximumEncodedBytes")
    if type(maximum) is not int or maximum != 4096 * 4:
        raise ValueError("Prompt decoded-u32 payload must fit the frozen 4096-item array")
    shapes = schema["properties"]["observed_token_positions"]["oneOf"]
    arrays = [s for s in shapes if s.get("type") == "array"]
    if len(arrays) != 1:
        raise ValueError("one nullable array shape required")
    array = arrays[0]
    if type(array.get("minItems")) is not int or type(array.get("maxItems")) is not int:
        raise ValueError("integer array limits required")
    if array.get("minItems") != 1 or array.get("maxItems") != maximum // 4:
        raise ValueError("schema/native/HPTC capacity mismatch")
    if array.get("items") != {"type": "integer", "minimum": 0, "maximum": 4294967295}:
        raise ValueError("position integer width mismatch")
    if array.get("x-hepta-invariant") != "strictly_increasing":
        raise ValueError("position ordering invariant missing")
    if "observed_token_positions" not in schema["required"]:
        raise ValueError("nullable is not optional")
    return {"maximumPositions": maximum // 4, "maximumDecodedU32Bytes": maximum,
            "hptcContainerMaximum": 4096, "status": "passed"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    path = root / "codex-rs/hepta-types/schemas/prompt-delivery-observation-v2.schema.json"
    result = verify(json.loads(args.catalog.read_text()), json.loads(path.read_text()))
    result.update(schema="hepta.platform-types.semantic-bounds.v1",
                  schemaSha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  catalogSha256=hashlib.sha256(args.catalog.read_bytes()).hexdigest())
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print("Prompt V2 compiled catalog/schema/HPTC capacity parity: passed")


if __name__ == "__main__":
    main()
