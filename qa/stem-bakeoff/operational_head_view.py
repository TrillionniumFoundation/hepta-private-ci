"""Bound lexical metadata while preserving complete-source feature vectors.

This explicit compatibility view is not an encoder input. Original datasets,
source bytes and encoder receipts remain immutable and independently bound.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import unicodedata

import numpy as np

from cell_calibrated_curve import sha_file, write_json
from cell_calibration_v2 import calibration_partition
from cell_learning_baselines import normalized_text


def full_normalized_text(text):
    if type(text) is not str or not text.strip() or len(text.encode()) > 131072:
        raise ValueError("nonempty complete source text bounded to 128 KiB required")
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def project_dataset(dataset):
    path = Path(dataset)
    if path.stat().st_size > 256*1024**2:
        raise ValueError("source dataset exceeds bounded manifest size")
    source_bytes = path.read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    original = json.loads(source_bytes)
    if (not isinstance(original.get("rows"), list) or not 1 <= len(original["rows"]) <= 16384
            or len({r["source_id"] for r in original["rows"]}) != len(original["rows"])):
        raise ValueError("bounded dataset with unique original source IDs required")
    viewed, receipts, maps = [], [], ({}, {})
    full_identity, seen_groups, seen_text = {}, {}, {}
    for row in original["rows"]:
        if row.get("modality", "text") != "text" or row["split"] not in ("train", "calibration", "holdout"):
            raise ValueError("explicit text-only source roles required")
        raw = row["text"].encode()
        prefix = raw[:32768].decode("utf-8", errors="ignore")
        kept = prefix.encode()
        full, short = full_normalized_text(row["text"]), normalized_text(prefix)
        for mapping, key, value in ((maps[0], full, short), (maps[1], short, full)):
            if key in mapping and mapping[key] != value:
                raise ValueError("lexical view changes predictor duplicate equivalence classes")
            mapping[key] = value
        for seen, identity in ((seen_groups, row["group_id"]), (seen_text, full)):
            if identity in seen and seen[identity] != row["split"]:
                raise ValueError("complete-source group or normalized predictor crosses splits")
            seen[identity] = row["split"]
        full_identity[row["source_id"]] = hashlib.sha256(full.encode()).hexdigest()
        viewed.append({**row, "text": prefix})
        receipts.append({"source_id": row["source_id"], "split": row["split"],
            "full_utf8_bytes": len(raw), "prefix_utf8_bytes": len(kept),
            "discarded_utf8_bytes": len(raw)-len(kept),
            "full_sha256": hashlib.sha256(raw).hexdigest(),
            "prefix_sha256": hashlib.sha256(kept).hexdigest(),
            "discarded_sha256": hashlib.sha256(raw[len(kept):]).hexdigest(),
            "truncated": len(raw) != len(kept)})
    calibration_equivalence = {}
    for task in original["selected_tasks"]:
        rows = [{k: r[k] for k in ("source_id", "group_id", "text")} for r in viewed
                if r["split"] == "calibration" and r.get("labels", {}).get(task) is not None]
        full_partition = calibration_partition(rows, input_content_sha256=full_identity)
        prefix_partition = calibration_partition(rows)
        if any(not np.array_equal(a, b) for a, b in zip(full_partition, prefix_partition)):
            raise ValueError("lexical view changes frozen calibration component membership")
        calibration_equivalence[task] = {
            role: [rows[i]["source_id"] for i in indices]
            for role, indices in zip(("tuning", "calibration"), full_partition)}
    binding = {"schema": "hepta.operational-lexical-head-view.v1",
        "source_dataset_sha256": source_sha, "lexical_prefix_limit_utf8_bytes": 32768,
        "complete_source_limit_utf8_bytes": 131072,
        "prefix_rule": "first32768UTF8bytes, drop only an incomplete terminal codepoint",
        "encoder_inputs_changed": False, "source_ids_groups_labels_splits_changed": False,
        "predictor_duplicate_equivalence_preserved": True,
        "training_draws_preserved": "same source/group IDs and predictor equivalence; sampler depends only on these and fixed labels/seed",
        "calibration_partitions": calibration_equivalence,
        "lexical_scope": "exact/BM25 use prefix view; separately sealed full-text companion required"}
    if sha_file(path) != source_sha:
        raise ValueError("source dataset changed during lexical view projection")
    return {**original, "rows": viewed, "head_predictor_view": binding}, {
        **binding, "rows": receipts, "truncated_rows": sum(r["truncated"] for r in receipts),
        "source_code_sha256": sha_file(__file__)}


def build_view(dataset, output):
    data, receipt = project_dataset(dataset)
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    write_json(root/"dataset.json", data)
    receipt["head_view_dataset_sha256"] = sha_file(root/"dataset.json")
    write_json(root/"receipt.json", receipt)
    return verify_view(dataset, root)


def verify_view(source_dataset, view):
    root = Path(view)
    data, receipt = project_dataset(source_dataset)
    blobs = {name: (root/name).read_bytes() for name in ("dataset.json", "receipt.json")}
    pins = {name: hashlib.sha256(value).hexdigest() for name, value in blobs.items()}
    receipt["head_view_dataset_sha256"] = pins["dataset.json"]
    if (json.loads(blobs["dataset.json"]) != data or json.loads(blobs["receipt.json"]) != receipt
            or any(sha_file(root/name) != digest for name, digest in pins.items())
            or sha_file(source_dataset) != receipt["source_dataset_sha256"]):
        raise ValueError("head view or its complete/prefix/discarded source receipts changed")
    return {**receipt, "verified_file_sha256": pins}


def bind_features(source_dataset, view, original_features, output):
    view_receipt = verify_view(source_dataset, view)
    source, root = Path(original_features), Path(output)
    report_path, archive = source/"report.json", source/"features.npz"
    report_blob, archive_blob = report_path.read_bytes(), archive.read_bytes()
    report_sha, archive_sha = hashlib.sha256(report_blob).hexdigest(), hashlib.sha256(archive_blob).hexdigest()
    original_blob = Path(source_dataset).read_bytes()
    original_sha = hashlib.sha256(original_blob).hexdigest()
    report, original = json.loads(report_blob), json.loads(original_blob)
    if (original_sha != view_receipt["source_dataset_sha256"]
            or report["plan"]["dataset_sha256"] != original_sha
            or report["plan"]["source_ids"] != [r["source_id"] for r in original["rows"]]
            or report["feature_archive_sha256"] != archive_sha):
        raise ValueError("complete-source encoder receipt does not bind original dataset and order")
    with np.load(io.BytesIO(archive_blob), allow_pickle=False) as arrays:
        if arrays.files != ["features"]:
            raise ValueError("one complete-source feature matrix required")
        features = arrays["features"]
    if (features.dtype != np.float32 or features.ndim != 2 or not np.isfinite(features).all()
            or list(features.shape) != report["feature_shape"]
            or len(features) != len(original["rows"])
            or hashlib.sha256(features.tobytes()).hexdigest() != report["feature_tensor_sha256"]):
        raise ValueError("complete-source feature tensor differs from encoder receipt")
    root.mkdir(parents=True, exist_ok=False)
    with (root/"features.npz").open("xb") as stream:
        stream.write(archive_blob)
    with np.load(root/"features.npz", allow_pickle=False) as copied:
        identical = np.array_equal(features.view(np.uint8), copied["features"].view(np.uint8))
    if (not identical or sha_file(root/"features.npz") != archive_sha
            or sha_file(report_path) != report_sha or sha_file(archive) != archive_sha
            or sha_file(source_dataset) != original_sha
            or any(sha_file(Path(view)/name) != digest
                   for name, digest in view_receipt["verified_file_sha256"].items())):
        raise ValueError("source changed or feature alias is not bitwise identical")
    alias = {**report, "plan": {**report["plan"],
        "dataset_sha256": view_receipt["head_view_dataset_sha256"]},
        "head_predictor_view": {"source_dataset_sha256": view_receipt["source_dataset_sha256"],
            "head_view_dataset_sha256": view_receipt["head_view_dataset_sha256"],
            "view_receipt_sha256": view_receipt["verified_file_sha256"]["receipt.json"],
            "original_encoder_receipt_sha256": report_sha,
            "original_feature_archive_sha256": archive_sha,
            "feature_tensor_bitwise_unchanged": identical,
            "feature_identity_unchanged": True,
            "encoder_input": "complete original source",
            "lexical_input": "explicit UTF8-safe32768-byte prefix compatibility view",
            "source_code_sha256": sha_file(__file__)}}
    write_json(root/"report.json", alias)
    write_json(root/"binding-receipt.json", {"schema": "hepta.complete-feature-lexical-view-binding.v1",
        **alias["head_predictor_view"], "alias_report_sha256": sha_file(root/"report.json")})
    return alias


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dataset", required=True)
    parser.add_argument("--view", required=True)
    parser.add_argument("--original-features")
    parser.add_argument("--output-features")
    args = parser.parse_args()
    if bool(args.original_features) != bool(args.output_features):
        parser.error("both feature arguments are required for a feature binding")
    if args.original_features:
        bind_features(args.source_dataset, args.view, args.original_features, args.output_features)
    else:
        build_view(args.source_dataset, args.view)


if __name__ == "__main__":
    main()
