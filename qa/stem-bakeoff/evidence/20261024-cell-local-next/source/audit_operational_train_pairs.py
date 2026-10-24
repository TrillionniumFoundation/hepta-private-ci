"""Exploratory input-support audit of sealed TRAIN-only regression pairs."""

import time

START_WALL = time.perf_counter_ns()
START_CPU = time.process_time_ns()

import argparse
from collections import defaultdict
import hashlib
import io
import json
from pathlib import Path
import platform
import unicodedata

import numpy as np


def digest(data):
    return hashlib.sha256(data).hexdigest()


def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def audit(dataset, features, output, expected_dataset_sha256, expected_report_sha256):
    dataset, features, output = Path(dataset), Path(features), Path(output)
    if output.exists():
        raise ValueError("a new exploratory output file is required")
    paths = [dataset, features / "report.json", features / "manifest.json", features / "features.npz"]
    raw = {str(path): path.read_bytes() for path in paths}
    pins = {path: digest(content) for path, content in raw.items()}
    if (pins[str(dataset)] != expected_dataset_sha256
            or pins[str(features / "report.json")] != expected_report_sha256):
        raise ValueError("dataset or feature report differs from the supplied immutable pin")
    data = json.loads(raw[str(dataset)])
    report = json.loads(raw[str(features / "report.json")])
    manifest = json.loads(raw[str(features / "manifest.json")])
    rows = data["rows"]
    for name in ("report.json", "features.npz"):
        if manifest[name]["sha256"] != pins[str(features / name)]:
            raise ValueError("feature manifest differs")
    if (report["plan"]["dataset_sha256"] != expected_dataset_sha256
            or report["plan"]["source_ids"] != [row["source_id"] for row in rows]
            or report["feature_archive_sha256"] != pins[str(features / "features.npz")]):
        raise ValueError("feature source order or archive differs")
    with np.load(io.BytesIO(raw[str(features / "features.npz")]), allow_pickle=False) as archive:
        if archive.files != ["features"]:
            raise ValueError("unexpected feature archive contents")
        matrix = archive["features"]
    if (matrix.dtype != np.float32 or list(matrix.shape) != report["feature_shape"]
            or len(matrix) != len(rows) or not np.isfinite(matrix).all()
            or digest(matrix.tobytes()) != report["feature_tensor_sha256"]):
        raise ValueError("feature precision, shape or tensor differs")
    groups = defaultdict(list)
    for index, row in enumerate(rows):
        if row["split"] != "train" or "regression_outcome" not in row.get("labels", {}):
            continue
        text = row["text"].encode()
        if (len(text) > 128 * 1024 or digest(text) != row["text_utf8_sha256"]
                or len(text) != row["text_utf8_bytes"]):
            raise ValueError("complete training predictor differs from its source receipt")
        groups[row["group_id"]].append((index, row))
    pairs, unavailable = [], []
    for group_id, members in sorted(groups.items()):
        if len(members) != 2 or sorted(row["labels"]["regression_outcome"] for _, row in members) != [0, 1]:
            unavailable.append({"group_id": group_id, "rows": len(members),
                                "reason": "requires exactly two rows with opposite binary labels"})
            continue
        (i, left), (j, right) = sorted(members, key=lambda item: item[1]["source_id"])
        x, y = matrix[i].astype(np.float64), matrix[j].astype(np.float64)
        denominator = float(np.linalg.norm(x) * np.linalg.norm(y))
        distance = None if denominator == 0 else float(np.clip(1 - np.dot(x, y) / denominator, 0, 2))
        pairs.append({"group_id": group_id, "source_ids": [left["source_id"], right["source_id"]],
            "opposite_labels": True, "exact_predictor_equal": left["text"] == right["text"],
            "normalized_predictor_equal": normalized(left["text"]) == normalized(right["text"]),
            "granite_global_bytes_equal": matrix[i].tobytes() == matrix[j].tobytes(),
            "cosine_distance_float64": distance})
    distances = np.asarray([p["cosine_distance_float64"] for p in pairs
                            if p["cosine_distance_float64"] is not None], dtype=np.float64)
    thresholds = [0, 1e-12, 1e-9, 1e-6, 1e-4, 1e-3, 1e-2, .1, .5, 1]
    quantiles = [0, .01, .05, .25, .5, .75, .95, .99, 1]
    if any(digest(Path(path).read_bytes()) != pin for path, pin in pins.items()):
        raise ValueError("an immutable input changed during the audit")
    result = {"schema": "hepta.exploratory-train-regression-pair-audit.v1",
        "scope": "post-hoc TRAIN-only input-support diagnostic; no model fit or evaluated condition",
        "task_id": "regression_outcome", "split": "train", "source_artifact_sha256": pins,
        "source_code_sha256": digest(Path(__file__).read_bytes()),
        "feature_identity": report["feature_identity"],
        "analysis_uses_complete_predictor_text": True,
        "normalization": "NFKC, Unicode casefold, collapse all whitespace",
        "container_integrity_scope": "complete dataset/array containers checked; only selected train rows analyzed",
        "heldout_prediction_files_opened": False, "nontraining_statistics_computed": False,
        "training_rows": sum(len(members) for members in groups.values()),
        "training_bug_groups": len(groups), "opposite_label_pairs": len(pairs),
        "unavailable_groups": unavailable,
        "exact_predictor_equal_pairs": sum(p["exact_predictor_equal"] for p in pairs),
        "normalized_predictor_equal_pairs": sum(p["normalized_predictor_equal"] for p in pairs),
        "bitwise_equal_global_pairs": sum(p["granite_global_bytes_equal"] for p in pairs),
        "distinct_predictors_with_bitwise_equal_globals": sum(not p["exact_predictor_equal"]
            and p["granite_global_bytes_equal"] for p in pairs),
        "cosine_distance": {"formula": "clip(1-dot(x,y)/(norm(x)*norm(y)),0,2), float64 accumulation",
            "defined_pairs": len(distances), "zero_norm_pairs": len(pairs) - len(distances),
            "mean": float(distances.mean()) if len(distances) else None,
            "quantiles": {str(q): float(np.quantile(distances, q)) for q in quantiles} if len(distances) else {},
            "counts_at_or_below": {str(t): int(np.sum(distances <= t)) for t in thresholds}},
        "interpretation_limit": "Exact input/global collisions can show missing distinctions; their absence or small cosine distances alone cannot identify encoder capacity as the bottleneck or establish operational predictability.",
        "encoder_forward_calls": 0, "gradient_updates": 0, "quality_promotion": False,
        "runtime": {"python": platform.python_version(), "numpy": np.__version__},
        "cost": {"wall_ns": time.perf_counter_ns() - START_WALL,
                 "cpu_ns": time.process_time_ns() - START_CPU,
                 "scope": "script imports through final input recheck; excludes interpreter startup and output serialization"},
        "pairs": pairs}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "features", "output", "expected-dataset-sha256", "expected-report-sha256"):
        parser.add_argument("--" + name, required=True)
    result = audit(**vars(parser.parse_args()))
    print(json.dumps({key: value for key, value in result.items() if key != "pairs"}, sort_keys=True))
