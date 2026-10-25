"""Bounded, label-separated inputs and evidence I/O for the V3 runner."""

from collections import Counter
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import sys

import numpy as np

from cell_field_features import file_hash, load_features
from cell_learning_models import canonical


TRAIN_ROLES = {"old_train", "old_probe", "current_train", "current_probe"}
SOURCE_KEYS = {"index", "source_id", "raw_source_id", "component_id", "month", "role", "timestamp_ms",
               "source_row_sha256", "normalized_title_sha256", "publisher_sha256",
               "component_member_count", "component_members_sha256"}
EXTRA_SOURCE_FILES = ("cell_learning_models.py", "cell_learning_metrics.py", "feature_bundle.py",
    "real_encoder.py", "real_encoder_candidates.json", "real_cell_features.py",
    "shared_feature_contract.py", "shared_feature_extract.py", "teacher_snapshot.py", "prepare_news_cohorts.py")


def _json_value(value):
    if isinstance(value, np.ndarray):
        return _json_value(value.tolist())
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return {"__nonfinite__": "nan" if math.isnan(value) else "+inf" if value > 0 else "-inf"}
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("evidence dictionary keys must be strings")
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(_json_value(value)) + b"\n")


def save_arrays(path, arrays):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    converted = {name: np.asarray(value) for name, value in arrays.items()}
    if any(value.dtype.hasobject for value in converted.values()):
        raise ValueError("evidence arrays cannot require pickle")
    with path.open("wb") as stream:
        np.savez_compressed(stream, **converted)


def source_hashes():
    root = Path(__file__).parent
    names = {path.name for path in root.glob("cell_field*.py")} | set(EXTRA_SOURCE_FILES)
    for name in names:
        if (root / name).is_symlink():
            raise ValueError("source closure contains a symlink")
    return {name: file_hash(root / name) for name in sorted(names)}


def deny_withheld_labels(event, arguments):
    if event == "open" and arguments and isinstance(arguments[0], (str, bytes, os.PathLike)):
        name = os.fsdecode(arguments[0])
        if Path(name).name in {"validation_labels.json", "final_labels.json"}:
            raise PermissionError("withheld validation/final label payload is not a runner input")


def _read_json(path, max_bytes=2 << 20):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
        raise ValueError("invalid or oversized input file: " + str(path))
    return json.loads(path.read_bytes())


def load_inputs(data, features, protocol):
    data, feature_dir, protocol = Path(data), Path(features), Path(protocol)
    input_paths = {**{f"data/{name}": data / name for name in
        ("data_receipt.json", "train_labels.json", "sources.json", "predictors.json")},
        **{f"features/{name}": feature_dir / name for name in ("report.json", "features.npz", "plan.json")},
        "protocol.json": protocol}
    if any(path.is_symlink() or not path.is_file() for path in input_paths.values()):
        raise ValueError("runner inputs must be existing ordinary files")
    input_hashes = {name: file_hash(path) for name, path in input_paths.items()}
    plan = _read_json(protocol)
    protocol_hash = input_hashes["protocol.json"]
    receipt = _read_json(data / "data_receipt.json")
    expected_files = {"train_labels.json", "validation_labels.json", "final_labels.json", "sources.json", "predictors.json"}
    if (set(receipt["files"]) != expected_files or receipt["protocol_sha256"] != protocol_hash
            or receipt["source_archive_sha256"] != plan["source_archive_sha256"]
            or receipt["salt"] != plan["source_split_salt"] or receipt["prior_experiments"] != plan["prior_experiments"]
            or plan["optimizer"]["sampler"] != "full_batch" or plan["classes"] != 4
            or sum(plan["source_counts"].values()) != 624):
        raise ValueError("data and frozen V3 protocol identities disagree")
    for name in ("train_labels.json", "sources.json", "predictors.json"):
        expected = receipt["files"][name]
        if (input_hashes["data/" + name] != expected["sha256"]
                or (data / name).stat().st_size != expected["bytes"]):
            raise ValueError("prepared input differs from receipt: " + name)
    labels = _read_json(data / "train_labels.json")
    source_payload, predictor_payload = _read_json(data / "sources.json"), _read_json(data / "predictors.json")
    sources, predictors = source_payload["rows"], predictor_payload["rows"]
    role_plan = plan["source_role_plan"]
    expected_roles = {row["role"]: {"month": row["month"], "rows": row["rows"],
        "labels_per_class": row["rows"] // 4, "access": row["access"]} for row in role_plan}
    if (receipt["schema"] != "hepta.cell-action-news.v3"
            or any(payload["schema"] != receipt["schema"] for payload in (labels, source_payload, predictor_payload))
            or len(expected_roles) != len(role_plan) or receipt["roles"] != expected_roles
            or plan["source_counts"] != {row["role"]: row["rows"] for row in role_plan}
            or {row["role"] for row in role_plan if row["access"] == "train"} != TRAIN_ROLES
            or set(labels["roles"]) != TRAIN_ROLES or labels["classes"] != 4
            or len(sources) != 624 or len(predictors) != 624
            or [row["index"] for row in sources] != list(range(624))
            or len({row["source_id"] for row in sources}) != 624
            or len({row["raw_source_id"] for row in sources}) != 624
            or len({row["component_id"] for row in sources}) != 624
            or any(set(row) != SOURCE_KEYS for row in sources)
            or any(set(row) != {"source_id", "source_version", "text"} for row in predictors)):
        raise ValueError("source census, schema or label-role boundary differs")
    expected_role_order = [row["role"] for row in role_plan for _ in range(row["rows"])]
    if ([row["role"] for row in sources] != expected_role_order
            or any(row["month"] != expected_roles[row["role"]]["month"]
                or row["source_id"] != "uci-news:" + row["raw_source_id"] for row in sources)
            or any(predictor["source_id"] != row["source_id"]
                or predictor["source_version"] != "sha256:" + row["source_row_sha256"]
                for predictor, row in zip(predictors, sources))):
        raise ValueError("source identities or global role order differ")
    feature_plan = _read_json(feature_dir / "plan.json")
    matrix, feature_report = load_features(feature_dir, protocol_hash)
    if (matrix.shape != (624, 384) or feature_report["plan"] != feature_plan
            or feature_plan["data_receipt_sha256"] != input_hashes["data/data_receipt.json"]
            or feature_plan["predictors_sha256"] != input_hashes["data/predictors.json"]
            or feature_plan["source_ids"] != [row["source_id"] for row in sources]
            or feature_plan["labels_enter_encoder"] is not False
            or feature_report["encoder_identity"]["checkpoint_revision"] != plan["encoder_revision"]
            or feature_report["encoder_updates"] != 0
            or feature_report["encoder_load"]["model"]["trainable_parameter_count"] != 0):
        raise ValueError("frozen features, source order or label boundary differs")
    seen = set()
    for role, values in labels["roles"].items():
        indices, y = np.asarray(values["indices"]), np.asarray(values["labels"])
        amount = plan["source_counts"][role]
        expected_indices = [row["index"] for row in sources if row["role"] == role]
        if (set(values) != {"indices", "labels", "source_ids"}
                or indices.dtype.kind not in "iu" or y.dtype.kind not in "iu"
                or indices.ndim != 1 or y.shape != indices.shape or len(indices) != amount
                or indices.tolist() != expected_indices or seen.intersection(indices.tolist())
                or Counter(y.tolist()) != {c: amount // 4 for c in range(4)}
                or values["source_ids"] != [sources[i]["source_id"] for i in indices]):
            raise ValueError("training labels, classes or source indices disagree")
        seen.update(indices.tolist())
    return {"plan": plan, "protocol_sha256": protocol_hash, "receipt": receipt,
            "labels": labels, "sources": sources, "features": matrix, "feature_report": feature_report,
            "input_paths": input_paths, "input_hashes": input_hashes}


def project(features, plan):
    matrix = np.asarray(features)
    width = plan["projection"]["width"]
    if matrix.ndim != 2 or not np.isfinite(matrix).all() or type(width) is not int or not 1 <= width <= matrix.shape[1]:
        raise ValueError("invalid feature matrix or projection width")
    rng = np.random.default_rng(plan["projection"]["seed"])
    q, r = np.linalg.qr(rng.normal(size=(matrix.shape[1], width)), mode="reduced")
    q *= np.where(np.diag(r) < 0, -1.0, 1.0)
    projected = matrix.astype(np.float64) @ q
    if not np.isfinite(projected).all():
        raise ValueError("projection produced nonfinite features")
    return projected, q


def split_arrays(projected, labels):
    if set(labels["roles"]) != TRAIN_ROLES:
        raise ValueError("only the four training/probe roles may enter training arrays")
    return {role: (projected[np.asarray(values["indices"], dtype=np.int64)],
                   np.asarray(values["labels"], dtype=np.int64)) for role, values in labels["roles"].items()}


def environment():
    result = {"python": platform.python_version(), "platform": platform.platform(),
              "packages": {name: importlib.metadata.version(name) for name in ("numpy", "scipy")}}
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result["peak_rss_bytes"] = peak if sys.platform == "darwin" else peak * 1024
    except ImportError:
        result["peak_rss_bytes"] = None
    return result
