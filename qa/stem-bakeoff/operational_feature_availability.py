"""Explicit unavailable features; only finite, source-indexed rows leave the loader."""

import json
from pathlib import Path

import numpy as np

from long_document_sources import canonical, sha
from operational_region_evidence import arrays, capture, verify_pins


def availability_record(source_ids, available, reasons):
    if (not 1 <= len(source_ids) <= 4096 or len(set(source_ids)) != len(source_ids)
            or len(available) != len(source_ids) or len(reasons) != len(source_ids)
            or any(type(v) is not str or not 1 <= len(v) <= 256 for v in source_ids)
            or any(type(v) is not bool for v in available)
            or any((flag and reason is not None) or (not flag and
                (type(reason) is not str or not 1 <= len(reason) <= 512))
                for flag, reason in zip(available, reasons, strict=True))):
        raise ValueError("explicit source-ordered feature availability and reasons required")
    return {"schema": "hepta.operational-feature-availability.v1", "source_ids": list(source_ids),
        "available": list(available), "unavailable_reasons": list(reasons),
        "sentinel": "entire unavailable row is FP32 NaN; it must never reach normalization/training/scoring",
        "proposal_denominator_preserved": True}


def validate_matrix(values, record):
    expected = availability_record(record["source_ids"], record["available"], record["unavailable_reasons"])
    if record != expected:
        raise ValueError("availability schema or sentinel contract differs")
    mask = np.asarray(record["available"], np.bool_)
    if (values.dtype != np.float32 or values.ndim != 2 or values.shape[0] != len(mask)
            or not 1 <= values.shape[1] <= 2048 or not np.isfinite(values[mask]).all()
            or not np.isnan(values[~mask]).all()):
        raise ValueError("finite available rows and NaN-only unavailable rows required")
    return mask


def capture_feature_bundle(directory, dataset, expected_report_sha256):
    root, pins = Path(directory), {}
    raw = {name: capture(root / name, pins) for name in ("report.json", "plan.json", "manifest.json",
        "features.npz", "feature-availability.json", "source-bindings.json")}
    if sha(raw["report.json"]) != expected_report_sha256:
        raise ValueError("independent feature report pin differs")
    report, manifest = json.loads(raw["report.json"]), json.loads(raw["manifest.json"])
    for name, blob in raw.items():
        if name != "manifest.json" and manifest.get(name) != {"sha256": sha(blob), "bytes": len(blob)}:
            raise ValueError("feature inventory differs from captured files")
    data_raw = capture(dataset, pins, 64 * 1024**2)
    data, plan = json.loads(data_raw), report["plan"]
    if (sha(data_raw) != plan["dataset_sha256"] or json.loads(raw["plan.json"]) != plan
            or [r["source_id"] for r in data["rows"]] != plan["source_ids"]
            or sha(canonical(plan["feature_definition"])) != report["feature_identity"]
            or report["feature_identity"] != plan["feature_identity"]):
        raise ValueError("feature dataset, source order or semantic identity differs")
    for key, name in (("feature_archive_sha256", "features.npz"),
        ("feature_availability_sha256", "feature-availability.json"), ("source_bindings_sha256", "source-bindings.json")):
        if report[key] != sha(raw[name]):
            raise ValueError("feature report does not bind the captured payload")
    values, = arrays(raw["features.npz"], ["features"])
    availability = json.loads(raw["feature-availability.json"])
    if (availability["source_ids"] != plan["source_ids"] or list(values.shape) != report["feature_shape"]
            or sha(values.tobytes()) != report["feature_tensor_sha256"]):
        raise ValueError("numeric tensor/availability source mapping differs")
    mask = validate_matrix(values, availability)
    bindings = json.loads(raw["source-bindings.json"])
    if ([item["source_id"] for item in bindings] != plan["source_ids"]
            or [sha(canonical(item)) for item in bindings] != report["source_record_digests"]
            or report["available_feature_rows"] != int(mask.sum())
            or report["unavailable_feature_rows"] != int((~mask).sum())):
        raise ValueError("feature row source origins differ")
    for row, binding in zip(data["rows"], bindings, strict=True):
        text = row["text"]
        digest = sha(text.encode())
        receipt = binding["source_slice_receipt"]
        if (digest != row["text_utf8_sha256"] or len(text.encode()) != row["text_utf8_bytes"]
                or binding["source_utf8_sha256"] != digest or binding["source_utf8_bytes"] != len(text.encode())
                or binding["source_version"] != "sha256:" + sha(canonical(row["source_version"]))
                or binding["input_regions"] != row["input_regions"] or receipt["source_sha256"] != digest
                or set(receipt["fields"]) != {"change", "test"} or set(binding["field_ids"]) != {"change", "test"}):
            raise ValueError("feature source text/version/spans differ from its current dataset row")
        for name, field in receipt["fields"].items():
            parts, previous = [], 0
            for span in field["source_spans"]:
                a, b = span["char_span"]
                if (type(a) is not int or type(b) is not int or not previous <= a < b <= len(text)
                        or span["utf8_span"] != [len(text[:a].encode()), len(text[:b].encode())]
                        or span["sha256"] != sha(text[a:b].encode())):
                    raise ValueError("selected source slice no longer replays exactly")
                parts.append(text[a:b])
                previous = b
            clean = "\n".join(parts)
            if (not parts or field["clean_utf8_sha256"] != sha(clean.encode())
                    or field["clean_utf8_bytes"] != len(clean.encode())
                    or field["selected_source_characters"] != sum(len(part) for part in parts)
                    or binding["field_ids"][name] != "source-field:" + sha(clean.encode())):
                raise ValueError("selected clean field differs from its source slices")
    verify_pins(pins)
    return data, report, values, mask, availability, raw, pins


def load_available_features(directory, dataset, *, expected_report_sha256):
    _, report, values, mask, availability, _, pins = capture_feature_bundle(directory, dataset, expected_report_sha256)
    indices = np.frombuffer(np.flatnonzero(mask).astype(np.int32).tobytes(), np.int32)
    finite = np.frombuffer(values[mask].tobytes(), np.float32).reshape(len(indices), values.shape[1])
    verify_pins(pins)
    return finite, indices, report, availability
