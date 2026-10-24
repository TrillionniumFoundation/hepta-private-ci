"""Export frozen source-only baselines or one clean shared Granite field owner."""

import argparse
import json
from pathlib import Path
import resource
import time

import numpy as np

from long_document_sources import canonical, sha
from operational_feature_availability import availability_record, validate_matrix
from operational_field_features import SourceFeatureUnavailable, baseline_definition, clean_fields, source_only_features
from operational_field_plan import source_hashes, verify_plan, write_json
from operational_region_evidence import arrays, capture, verify_pins
from operational_source_regions import readout_features


def finish(root, values, data, field_plan, mapping, definition, costs, pins, *, extra=None, reasons=None):
    identity = sha(canonical(definition))
    reasons = [None] * len(data["rows"]) if reasons is None else reasons
    availability = availability_record(field_plan["source_ids"], [r is None for r in reasons], reasons)
    mask = validate_matrix(values, availability)
    if source_hashes() != field_plan["source_code_sha256"]:
        raise ValueError("row features or frozen implementation differ")
    with (root / "features.npz").open("xb") as stream:
        np.savez_compressed(stream, features=values)
    plan = {"schema": "hepta.operational-field-row-features.v1", "dataset_sha256": field_plan["dataset_sha256"],
        "source_ids": field_plan["source_ids"], "feature_identity": identity, "feature_definition": definition,
        "row_mapping_sha256": field_plan["row_mapping_sha256"], "predictor_fields": ["text", "input_regions"],
        "source_code_sha256": field_plan["source_code_sha256"], "label_fields_enter_features": False}
    write_json(root / "plan.json", plan)
    write_json(root / "source-bindings.json", mapping)
    write_json(root / "feature-availability.json", availability)
    verify_pins(pins)
    cost = {"wall_ns": time.perf_counter_ns() - costs[0], "cpu_ns": time.process_time_ns() - costs[1],
        "scope": "inclusive plan/source validation, extraction, assembly, feature writes and final input recheck; excludes report/manifest self-writes and initial module imports",
        "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}
    report = {"plan": plan, "feature_identity": identity, "feature_shape": list(values.shape),
        "feature_tensor_sha256": sha(values.tobytes()), "feature_archive_sha256": sha((root / "features.npz").read_bytes()),
        "feature_archive_bytes": (root / "features.npz").stat().st_size, "retained_global_bytes": values.nbytes,
        "source_record_digests": [sha(canonical(row)) for row in mapping], "cost": cost,
        "source_bindings_sha256": sha((root / "source-bindings.json").read_bytes()),
        "feature_availability_sha256": sha((root / "feature-availability.json").read_bytes()),
        "available_feature_rows": int(mask.sum()), "unavailable_feature_rows": int((~mask).sum()),
        "mode": "SHADOW_ONLY", "authority": "DENY_ALL", "quality_qualified": False,
        "gradient_updates": 0, "old_curated_features_reused": False, **(extra or {})}
    write_json(root / "report.json", report)
    write_json(root / "manifest.json", {str(p.relative_to(root)): {"sha256": sha(p.read_bytes()), "bytes": p.stat().st_size}
        for p in sorted(root.rglob("*")) if p.is_file() and p != root / "manifest.json"})
    return report


def export_baseline(dataset, field_plan, output, *, expected_plan_sha256, kind):
    started = time.perf_counter_ns(), time.process_time_ns()
    root = Path(output)
    if root.exists():
        raise ValueError("new baseline output directory required")
    data, plan, mapping, pins = verify_plan(dataset, field_plan, expected_plan_sha256)
    definition, _ = baseline_definition(kind)
    selected, receipts, reasons = [], [], []
    for row in data["rows"]:
        try:
            hashed, scalars, receipt = source_only_features(row["text"], row["input_regions"])
            selected.append(hashed if kind == "identifier_hash770" else scalars)
            reasons.append(None)
        except SourceFeatureUnavailable as error:
            selected.append(np.full(770 if kind == "identifier_hash770" else 3, np.nan, np.float32))
            receipt = {"source_sha256": row["text_utf8_sha256"], "unavailable_reason": str(error)}
            reasons.append(str(error))
        receipts.append(receipt)
    root.mkdir(parents=True)
    write_json(root / "identifier-receipts.json", receipts)
    return finish(root, np.stack(selected), data, plan, mapping, definition, started, pins, reasons=reasons,
        extra={"condition": kind, "encoder_forward_calls": 0, "encoder_instances": 0,
               "source_extraction_plan_sha256": expected_plan_sha256})


def export_native(dataset, field_plan, snapshot, acquisition, output, *, expected_plan_sha256):
    started = time.perf_counter_ns(), time.process_time_ns()
    root, source_plan = Path(output), Path(field_plan)
    if root.exists():
        raise ValueError("new clean native field output required")
    data, plan, mapping, pins = verify_plan(dataset, source_plan, expected_plan_sha256)
    acquisition_raw = capture(acquisition, pins, 1024**2)
    if sha(acquisition_raw) != plan["checkpoint_acquisition_sha256"]:
        raise ValueError("checkpoint acquisition changed after the field plan")
    for name, expected in plan["tokenizer_file_sha256"].items():
        if sha(capture(Path(snapshot) / name, pins)) != expected:
            raise ValueError("native tokenizer changed after field planning")
    import transformers
    if transformers.__version__ != plan["transformers_version"]:
        raise ValueError("native tokenizer runtime differs from the frozen plan")
    from generic_dataset_features import export_generic_features
    root.mkdir(parents=True)
    parent = export_generic_features(source_plan / "field-dataset.json", snapshot, acquisition,
        root / "field-encoder", candidate="granite97m", batch_size=plan["batch_size"], threads=plan["threads"])
    if (parent["plan"]["document_plan_sha256"] != plan["document_plan_sha256"]
            or parent["plan"]["source_ids"] != plan["field_source_ids"]
            or parent["feature_shape"] != [plan["unique_fields"], 384]
            or parent["encoding"]["physical_forward_calls"] != plan["planned_physical_forwards"]
            or parent["checkpoint_inventory_sha256"] != plan["checkpoint_inventory_sha256"]):
        raise ValueError("actual clean native inputs, shape, checkpoint or forward count differ from plan")
    parent_raw = capture(root / "field-encoder/report.json", pins)
    feature_raw = capture(root / "field-encoder/features.npz", pins)
    if sha(feature_raw) != parent["feature_archive_sha256"]:
        raise ValueError("new parent field tensor archive changed")
    field_values, = arrays(feature_raw, ["features"])
    if sha(field_values.tobytes()) != parent["feature_tensor_sha256"]:
        raise ValueError("new parent field numeric tensor changed")
    field_index = {source: index for index, source in enumerate(plan["field_source_ids"])}
    values, origins = [], []
    for row, bound in zip(data["rows"], mapping, strict=True):
        regions, _, _ = clean_fields(row["text"], row["input_regions"])
        selected = {name: field_index[key] for name, key in bound["field_ids"].items()}
        values.append(readout_features(regions, {name: field_values[index] for name, index in selected.items()}, row["text"]))
        origins.append({**bound, "field_tensor_origins": {name: {"field_row": index,
            "parent_source_record_digest": parent["source_record_digests"][index],
            "field_row_sha256": sha(field_values[index].tobytes())} for name, index in selected.items()},
            "parent_report_sha256": sha(parent_raw)})
    definition = {"schema": "hepta.operational-clean-native-field-interaction.v1", "width": 770,
        "parent_feature_identity": parent["feature_identity"],
        "field_selection": "explicit supplied source spans; changed +/- code lines and test/fixture bodies",
        "field_join": "exact selected slices joined with constant LF", "source_metadata_features": False,
        "field_pooling": parent["plan"]["pooling"], "policy": plan["policy"],
        "readout": "concat(c*a,abs(c-a),dot(c,a),source_identifier_Jaccard)",
        "boundary_scope": "each native field contains only selected source slices and constant separators; no other action",
        "source_code_sha256": plan["source_code_sha256"]}
    return finish(root, np.stack(values), data, plan, origins, definition, started, pins,
        extra={"condition": "granite_clean_field770", "encoder_forward_calls": parent["encoding"]["physical_forward_calls"],
            "encoder_instances": 1, "shared_owner_load": parent["load"], "native_encoding": parent["encoding"],
            "logical_fields": plan["logical_fields"], "unique_fields": plan["unique_fields"],
            "exact_field_cache_hits": plan["exact_field_cache_hits"],
            "source_extraction_plan_sha256": expected_plan_sha256, "parent_report_sha256": sha(parent_raw),
            "nested_timings_are_already_in_inclusive_cost": True})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("identifier_hash770", "identifier_overlap3", "granite_clean_field770"))
    for name in ("dataset", "field-plan", "output", "expected-plan-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--snapshot")
    parser.add_argument("--acquisition")
    args = vars(parser.parse_args())
    if args["kind"] == "granite_clean_field770":
        args.pop("kind")
        if not args["snapshot"] or not args["acquisition"]:
            parser.error("native extraction requires snapshot and acquisition")
        result = export_native(**args)
    else:
        args.pop("snapshot")
        args.pop("acquisition")
        result = export_baseline(**args)
    print(json.dumps({key: result[key] for key in ("feature_identity", "feature_shape", "encoder_forward_calls")}))
