"""Freeze clean, exact-deduplicated source fields before native feature extraction."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re
import time

from long_document_chunks import ChunkPolicy, tokenize_documents
from long_document_sources import canonical, sha
from operational_field_features import clean_fields
from operational_region_evidence import capture, verify_pins


SOURCE_FILES = ("operational_field_plan.py", "operational_field_features.py", "operational_source_regions.py",
    "operational_region_evidence.py", "operational_feature_availability.py",
    "export_operational_fields.py", "generic_dataset_features.py",
    "full_source_features.py", "long_document_encoder.py", "long_document_chunks.py", "long_document_sources.py",
    "shared_feature_extract.py", "shared_feature_contract.py", "real_encoder.py", "real_encoder_candidates.json",
    "feature_bundle.py", "teacher_snapshot.py", "requirements-real.txt")
TOKENIZER_FILES = ("config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json")


def source_hashes():
    return {name: sha(Path(__file__).with_name(name).read_bytes()) for name in SOURCE_FILES}


def write_json(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def field_inputs(data):
    rows = data.get("rows")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 4096:
        raise ValueError("bounded complete prospective input rows required")
    mapping, fields, seen = [], {}, set()
    for row in rows:
        source, text = row["source_id"], row["text"]
        if (type(source) is not str or not 0 < len(source) <= 256 or source in seen
                or row.get("input_template") != "operational_single_action_v1"
                or type(text) is not str or row["text_utf8_sha256"] != sha(text.encode())
                or type(row["text_utf8_bytes"]) is not int or row["text_utf8_bytes"] != len(text.encode())
                or type(row["source_version"]) not in (str, dict) or not row["source_version"]
                or len(canonical(row["source_version"])) > 4096):
            raise ValueError("unique source identity, explicit template and complete text/version pins required")
        seen.add(source)
        _, selected, receipt = clean_fields(text, row["input_regions"])
        field_ids = {}
        for name, value in selected.items():
            key = "source-field:" + sha(value.encode())
            if key in fields and fields[key] != value:
                raise ValueError("field digest collision has different exact source bytes")
            fields[key] = value
            field_ids[name] = key
        mapping.append({"source_id": source, "source_version": "sha256:" + sha(canonical(row["source_version"])),
            "source_utf8_sha256": row["text_utf8_sha256"], "source_utf8_bytes": row["text_utf8_bytes"],
            "input_regions": row["input_regions"], "field_ids": field_ids, "source_slice_receipt": receipt})
    if sum(len(value.encode()) for value in fields.values()) > 64 * 1024**2:
        raise ValueError("unique clean fields exceed corpus byte budget")
    field_rows = [{"source_id": key, "source_version": {"schema": "hepta.clean-source-field.v1",
        "clean_utf8_sha256": sha(value.encode())}, "text": value,
        "text_utf8_sha256": sha(value.encode()), "text_utf8_bytes": len(value.encode())}
        for key, value in sorted(fields.items())]
    return mapping, {"schema": "hepta.operational-clean-fields.v1", "rows": field_rows}


def create_plan(dataset, tokenizer, acquisition, output, *, dataset_sha256):
    started, cpu, pins = time.perf_counter_ns(), time.process_time_ns(), {}
    root, tokenizer = Path(output), Path(tokenizer)
    if root.exists() or re.fullmatch(r"[0-9a-f]{64}", dataset_sha256) is None:
        raise ValueError("new plan directory and independent dataset pin required")
    raw = capture(dataset, pins, 64 * 1024**2)
    if sha(raw) != dataset_sha256:
        raise ValueError("prospective dataset pin differs")
    implementation = source_hashes()
    mapping, field_data = field_inputs(json.loads(raw))
    acquired_raw = capture(acquisition, pins, 1024**2)
    acquired = json.loads(acquired_raw)
    candidate = json.loads(Path(__file__).with_name("real_encoder_candidates.json").read_bytes())["granite97m"]
    if (acquired["candidate"] != "granite97m" or acquired["revision"] != candidate["revision"]
            or acquired["repository"] != candidate["repository"]):
        raise ValueError("pinned Granite acquisition differs from the fixed candidate")
    tokenizer_pins = {name: sha(capture(tokenizer / name, pins)) for name in TOKENIZER_FILES}
    import transformers
    from transformers import AutoTokenizer
    native = AutoTokenizer.from_pretrained(tokenizer, local_files_only=True, trust_remote_code=False)
    plans = tokenize_documents(native, [row["text"] for row in field_data["rows"]], prefix="", policy=ChunkPolicy())
    counts = {row["source_id"]: len(document.chunks) for row, document in zip(field_data["rows"], plans, strict=True)}
    unique_windows = sum(counts.values())
    logical_windows = sum(counts[key] for row in mapping for key in row["field_ids"].values())
    plan = {"schema": "hepta.operational-clean-field-plan.v1", "candidate": "granite97m",
        "dataset_sha256": dataset_sha256, "dataset_bytes": len(raw), "source_code_sha256": implementation,
        "checkpoint": candidate, "checkpoint_acquisition_sha256": sha(acquired_raw),
        "checkpoint_inventory_sha256": acquired["inventory_sha256"],
        "source_ids": [row["source_id"] for row in mapping], "row_count": len(mapping),
        "field_source_ids": [row["source_id"] for row in field_data["rows"]],
        "field_dataset_sha256": sha(canonical(field_data) + b"\n"),
        "row_mapping_sha256": sha(canonical(mapping) + b"\n"),
        "tokenizer_file_sha256": tokenizer_pins, "transformers_version": transformers.__version__,
        "policy": asdict(ChunkPolicy()), "task": "classification", "prefix": "", "profile": "text",
        "batch_size": 16, "threads": 4, "retention": "chunks", "logical_fields": len(mapping) * 2,
        "unique_fields": len(plans), "exact_field_cache_hits": len(mapping) * 2 - len(plans),
        "unique_field_utf8_bytes": sum(row["text_utf8_bytes"] for row in field_data["rows"]),
        "logical_windows_without_field_reuse": logical_windows, "unique_field_windows": unique_windows,
        "planned_physical_forwards": (unique_windows + 15) // 16,
        "uncached_forward_equivalent_is_measured": False,
        "document_plan_sha256": [document.seal_sha256 for document in plans],
        "native_content_tokens": sum(document.content_tokens for document in plans),
        "field_encoder_feature_width": 384, "row_feature_width": 770,
        "predictor_fields": ["text", "input_regions"], "label_fields_used": False,
        "source_metadata_enters_numeric_features": False, "unprovided_counterpart_inputs_used": False,
        "old_curated_chunk_vectors_reused": False, "encoder_calls_during_planning": 0,
        "cost": {"wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
                 "scope": "input capture, field selection and tokenizer-only planning; excludes final validation/writes"}}
    verify_pins(pins)
    if source_hashes() != implementation:
        raise ValueError("field extraction implementation changed during planning")
    root.mkdir(parents=True)
    write_json(root / "field-dataset.json", field_data)
    write_json(root / "row-mapping.json", mapping)
    write_json(root / "plan.json", plan)
    write_json(root / "manifest.json", {p.name: {"sha256": sha(p.read_bytes()), "bytes": p.stat().st_size}
                                       for p in sorted(root.iterdir())})
    return plan


def verify_plan(dataset, directory, expected_plan_sha256):
    pins, root = {}, Path(directory)
    raw = {name: capture(root / name, pins) for name in
           ("plan.json", "manifest.json", "field-dataset.json", "row-mapping.json")}
    if sha(raw["plan.json"]) != expected_plan_sha256:
        raise ValueError("frozen field plan pin differs")
    manifest, plan = json.loads(raw["manifest.json"]), json.loads(raw["plan.json"])
    if (root.is_symlink() or {p.name for p in root.iterdir()} != set(raw)
            or set(manifest) != set(raw) - {"manifest.json"}
            or any(manifest[name] != {"sha256": sha(raw[name]), "bytes": len(raw[name])} for name in manifest)
            or plan["source_code_sha256"] != source_hashes()):
        raise ValueError("field plan inventory or implementation differs")
    pins.update({str(Path(__file__).with_name(name)): expected
                 for name, expected in plan["source_code_sha256"].items()})
    dataset_raw = capture(dataset, pins, 64 * 1024**2)
    if sha(dataset_raw) != plan["dataset_sha256"]:
        raise ValueError("source dataset changed after the field plan")
    data = json.loads(dataset_raw)
    mapping, fields = field_inputs(data)
    if (canonical(mapping) + b"\n" != raw["row-mapping.json"]
            or canonical(fields) + b"\n" != raw["field-dataset.json"]
            or sha(raw["row-mapping.json"]) != plan["row_mapping_sha256"]
            or sha(raw["field-dataset.json"]) != plan["field_dataset_sha256"]):
        raise ValueError("frozen clean fields do not reproduce source-only selection")
    verify_pins(pins)
    return data, plan, mapping, pins


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "tokenizer", "acquisition", "output", "dataset-sha256"):
        parser.add_argument("--" + name, required=True)
    value = create_plan(**vars(parser.parse_args()))
    print(json.dumps({key: value[key] for key in
        ("row_count", "logical_fields", "unique_fields", "unique_field_windows", "planned_physical_forwards")}))
