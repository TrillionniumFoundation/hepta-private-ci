"""Replay sealed field features from exact sources and retained tensors, without an Encoder."""

import argparse
import json
from pathlib import Path
import time

import numpy as np

from long_document_sources import canonical, sha
from operational_feature_availability import capture_feature_bundle
from operational_field_features import SourceFeatureUnavailable, clean_fields, source_only_features
from operational_field_plan import verify_plan
from operational_region_evidence import capture, verify_pins
from operational_source_regions import identifiers


def verify_export(dataset, field_plan, features, output, *, expected_plan_sha256, expected_report_sha256):
    started, cpu, root = time.perf_counter_ns(), time.process_time_ns(), Path(features)
    target = Path(output)
    if target.exists():
        raise ValueError("new artifact-replay receipt required")
    data, plan, mapping, plan_pins = verify_plan(dataset, field_plan, expected_plan_sha256)
    _, report, values, mask, _, captured, pins = capture_feature_bundle(root, dataset, expected_report_sha256)
    if "label_binding" in report:
        raise ValueError("replay the original pre-label export; label aliases have separate exact-copy proofs")
    pins.update(plan_pins)
    manifest = json.loads(captured["manifest.json"])
    members = list(root.rglob("*"))
    if any(path.is_symlink() for path in members) or {str(p.relative_to(root)) for p in members if p.is_file()} != set(manifest) | {"manifest.json"}:
        raise ValueError("complete ordinary artifact inventory differs")
    artifact_bytes = 0
    for name, record in manifest.items():
        relative = Path(name)
        if relative.is_absolute() or any(part in (".", "..") for part in relative.parts) or str(relative) != name:
            raise ValueError("unsafe artifact manifest member")
        content = capture(root / relative, pins)
        if record != {"sha256": sha(content), "bytes": len(content)}:
            raise ValueError("artifact manifest member changed")
        artifact_bytes += len(content)
    verifier_sha256 = sha(capture(Path(__file__), pins))
    rebuilt, cache = [], None
    if report["condition"] == "granite_clean_field770":
        from document_feature_cache import verify_prior
        parent_root = root / "field-encoder"
        parent_raw = capture(parent_root / "report.json", pins)
        parent = json.loads(parent_raw)
        if (sha(parent_raw) != report["parent_report_sha256"]
                or parent["plan"]["document_plan_sha256"] != plan["document_plan_sha256"]
                or parent["plan"]["source_ids"] != plan["field_source_ids"]
                or parent["encoding"]["physical_forward_calls"] != plan["planned_physical_forwards"]
                or report["encoder_forward_calls"] != plan["planned_physical_forwards"]
                or report["encoder_instances"] != 1 or not mask.all()):
            raise ValueError("actual parent field plan/forward count/owner differs")
        cache = verify_prior(parent_root, Path(field_plan) / "field-dataset.json", sha(parent_raw))
        parent_records = cache.metadata()["records"]
        index = {record["source_id"]: i for i, record in enumerate(parent_records)}
        origins = json.loads((root / "source-bindings.json").read_bytes())
        for row, bound, origin in zip(data["rows"], mapping, origins, strict=True):
            regions, selected, _ = clean_fields(row["text"], row["input_regions"])
            pools = {}
            for name, field_id in bound["field_ids"].items():
                i = index[field_id]
                if selected[name] != parent_records[i]["text"]:
                    raise ValueError("original source slices differ from actual encoded clean field")
                expected = {"field_row": i, "parent_source_record_digest": parent["source_record_digests"][i],
                            "field_row_sha256": sha(cache.features()[i].tobytes())}
                if origin["field_tensor_origins"][name] != expected or origin["parent_report_sha256"] != sha(parent_raw):
                    raise ValueError("per-action retained tensor origin differs")
                pools[name] = cache.features()[i].astype(np.float64)
            c, a = pools["change"], pools["test"]
            ci, ai = (identifiers(row["text"], regions.spans(name)) for name in ("change", "test"))
            overlap = len(ci & ai) / len(ci | ai) if ci or ai else 0.0
            rebuilt.append(np.r_[c * a, np.abs(c - a), np.dot(c, a), overlap].astype(np.float32))
    elif report["condition"] in ("identifier_hash770", "identifier_overlap3"):
        if report["encoder_forward_calls"] != 0 or report["encoder_instances"] != 0:
            raise ValueError("source-only baseline reports an Encoder")
        for i, row in enumerate(data["rows"]):
            try:
                hashed, scalar, _ = source_only_features(row["text"], row["input_regions"])
                if not mask[i]:
                    raise ValueError("available source-only feature was marked unavailable")
                rebuilt.append(hashed if values.shape[1] == 770 else scalar)
            except SourceFeatureUnavailable:
                if mask[i]:
                    raise ValueError("undefined source-only feature was marked usable")
                rebuilt.append(np.full(values.shape[1], np.nan, np.float32))
    else:
        raise ValueError("unknown frozen field feature condition")
    expected = np.stack(rebuilt)
    if expected.shape != values.shape or expected.tobytes() != values.tobytes():
        raise ValueError("saved per-action features do not replay bitwise from their declared source/field inputs")
    if cache is not None:
        cache.verify_files()
    verify_pins(pins)
    result = {"schema": "hepta.operational-field-artifact-replay.v1", "feature_report_sha256": expected_report_sha256,
        "field_plan_sha256": expected_plan_sha256, "feature_identity": report["feature_identity"],
        "dataset_sha256": plan["dataset_sha256"], "verifier_sha256": verifier_sha256,
        "source_ordered_rows": len(values), "available_rows": int(mask.sum()),
        "all_manifest_members_verified": True, "artifact_files_excluding_manifest": len(manifest),
        "artifact_bytes_excluding_manifest": artifact_bytes,
        "full_numeric_payload_bitwise_equal": True, "source_slices_and_versions_replayed": True,
        "parent_native_chunks_and_global_pooling_replayed": cache is not None,
        "verified_prior_physical_forwards": report["encoder_forward_calls"],
        "actual_encoder_forward_calls_during_replay": 0, "gradient_updates": 0,
        "input_pins": pins, "quality_qualified": False,
        "cost": {"wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
            "scope": "inclusive artifact capture, source/tensor reconstruction and final pin checks; excludes initial imports and receipt serialization"}}
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(canonical(result) + b"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "field-plan", "features", "output", "expected-plan-sha256", "expected-report-sha256"):
        parser.add_argument("--" + name, required=True)
    value = verify_export(**vars(parser.parse_args()))
    print(json.dumps({key: value[key] for key in ("source_ordered_rows", "available_rows",
        "full_numeric_payload_bitwise_equal", "actual_encoder_forward_calls_during_replay", "cost")}))
