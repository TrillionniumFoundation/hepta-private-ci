"""Verify portable, externally pinned action-runtime inputs without an Encoder.

The manifest is a caller-supplied trust anchor, not a self-issued certificate.
Serving verifies file hashes without decoding or using training target labels.
"""

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import zipfile

import numpy as np

from cell_calibration_bounded import validate_bounded_calibrator
from cell_learning_models import NumpyCellHead, canonical


SCHEMA = "hepta.action-runtime-input-bundle.v1"
MANIFEST_SCHEMA = "hepta.action-runtime-input-manifest.v1"
MODES = ("linear", "gated", "residual")


def sha_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def array_digest(array):
    value = np.ascontiguousarray(array)
    return hashlib.sha256(canonical([list(value.shape), value.dtype.str]) + value.tobytes()).hexdigest()


def digest(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("exact SHA256 digest required")
    return value


def member(root, relative):
    if type(relative) is not str or not 1 <= len(relative) <= 512:
        raise ValueError("bounded relative bundle member required")
    parts = PurePosixPath(relative)
    if (parts.is_absolute() or not parts.parts or str(parts) != relative
            or any(p in (".", "..") or ":" in p for p in parts.parts) or "\\" in relative):
        raise ValueError("unsafe bundle member path")
    path = Path(root).absolute().joinpath(*parts.parts)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("bundle members and ancestors cannot be symlinks")
    return path


def _files(root):
    result = {}
    for count, path in enumerate(Path(root).rglob("*"), 1):
        if count > 512 or path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError("bounded ordinary bundle files and directories required")
        if path.is_file() and path != Path(root)/"manifest.json":
            result[str(path.relative_to(root))] = path
    return result


def inventory(root):
    return {name: {"bytes": path.stat().st_size, "sha256": sha_file(path)}
            for name, path in sorted(_files(root).items())}


def check_npz(path, expected):
    """Inspect bounded NPY headers and ZIP sizes before any numeric allocation."""
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if (len(entries) != len(expected)
                or {entry.filename for entry in entries} != {name+".npy" for name in expected}):
            raise ValueError("unexpected or duplicate NPZ members")
        for entry in entries:
            shape, dtype = expected[entry.filename[:-4]]
            dtype = np.dtype(dtype)
            payload = int(np.prod(shape))*dtype.itemsize
            if entry.flag_bits & 1 or entry.file_size > payload+4096:
                raise ValueError("NPZ member exceeds its uncompressed byte bound")
            with archive.open(entry) as stream:
                version = np.lib.format.read_magic(stream)
                if version not in ((1, 0), (2, 0)):
                    raise ValueError("unsupported bounded NPY format")
                reader = (np.lib.format.read_array_header_1_0 if version == (1, 0)
                          else np.lib.format.read_array_header_2_0)
                actual_shape, fortran, actual_dtype = reader(stream, max_header_size=4096)
                if (actual_shape != shape or fortran or actual_dtype != dtype
                        or stream.tell()+payload != entry.file_size):
                    raise ValueError("NPY dtype, shape or payload size differs before allocation")


def verify_bundle(root, *, expected_manifest_sha256):
    root = Path(root).absolute()
    path = member(root, "manifest.json")
    if (not root.is_dir() or path.stat().st_size > 1024**2
            or sha_file(path) != digest(expected_manifest_sha256)):
        raise ValueError("external bundle manifest digest differs")
    manifest = json.loads(path.read_bytes())
    if (set(manifest) != {"schema", "files"} or manifest["schema"] != MANIFEST_SCHEMA
            or type(manifest["files"]) is not dict or not 1 <= len(manifest["files"]) <= 128
            or "bundle.json" not in manifest["files"] or "manifest.json" in manifest["files"]):
        raise ValueError("bounded complete bundle manifest required")
    if set(_files(root)) != set(manifest["files"]):
        raise ValueError("bundle inventory contains omitted or unexpected members")
    total = 0
    for name, record in manifest["files"].items():
        path = member(root, name)
        if (type(record) is not dict or set(record) != {"bytes", "sha256"}
                or type(record["bytes"]) is not int or not 0 <= record["bytes"] <= 16*1024**2):
            raise ValueError("invalid bundle member receipt")
        total += record["bytes"]
        if total > 64*1024**2:
            raise ValueError("bundle exceeds the retained input byte cap")
        if (not path.is_file() or path.stat().st_size != record["bytes"]
                or sha_file(path) != digest(record["sha256"])):
            raise ValueError("bundle member differs from external manifest")
    meta = json.loads(member(root, "bundle.json").read_bytes())
    if (meta.get("schema") != SCHEMA or meta.get("width") != 770 or meta.get("classes") != 2
            or type(meta.get("generation")) is not int or meta["generation"] != 1
            or meta.get("task_id") != "action_usefulness" or meta.get("authority") != "DENY_ALL"
            or meta.get("mode") != "SHADOW_ONLY" or meta.get("quality_qualified") is not False):
        raise ValueError("unexpected action-runtime bundle contract")
    digest(meta["feature_identity"])
    digest(meta["calibration_context_sha256"])
    expected = {(s, n, mode) for s in (7, 17, 29) for n in (8, 32, 64) for mode in MODES}
    states = meta.get("states", [])
    if (len(states) != 27 or {(s["seed"], s["budget"], s["mode"]) for s in states} != expected
            or len({s["artifact"] for s in states}) != 27):
        raise ValueError("exactly all 27 predeclared frozen states required")
    for state in states:
        for relative in (state["artifact"]+"/manifest.json", state["artifact"]+"/weights.npz", state["calibration"]):
            if relative not in manifest["files"]:
                raise ValueError("state member missing from complete inventory")
            member(root, relative)
        digest(state["predictor_sha256"])
        digest(state["calibration_sha256"])
    return meta


def _read_arrays(root, spec, expected_fields):
    size = 32 if "labels" in expected_fields else 64
    shapes = {"features": ((size, 770), np.float32)}
    if "labels" in expected_fields:
        shapes["labels"] = ((size,), np.int64)
    check_npz(member(root, spec["archive"]), shapes)
    with np.load(member(root, spec["archive"]), allow_pickle=False) as archive:
        if set(archive.files) != set(expected_fields):
            raise ValueError("unexpected numeric input fields")
        arrays = {key: archive[key] for key in expected_fields}
    rows = json.loads(member(root, spec["rows"]).read_bytes())
    x = arrays["features"]
    if (x.dtype != np.float32 or x.ndim != 2 or x.shape[1] != 770
            or not np.isfinite(x).all() or array_digest(x) != spec["feature_array_sha256"]
            or type(rows) is not list or len(rows) != len(x)):
        raise ValueError("feature tensor or source row count differs")
    preserved = json.loads(member(root, "sources.json").read_bytes())
    sources, groups = [], []
    for row, vector in zip(rows, x, strict=True):
        if any(type(row.get(key)) is not str or not 1 <= len(row[key].encode()) <= 512
               for key in ("source_id", "group_id")):
            raise ValueError("bounded source and group identities required")
        for key in ("source_record_digest", "text_utf8_sha256", "feature_row_sha256"):
            digest(row[key])
        if hashlib.sha256(vector.tobytes()).hexdigest() != row["feature_row_sha256"]:
            raise ValueError("source feature-row binding differs")
        source = preserved[row["source_id"]]
        original, binding = source["input"], source["binding"]
        if (original["source_id"] != row["source_id"] or binding["source_id"] != row["source_id"]
                or original["group_id"] != row["group_id"]
                or ("labels" in expected_fields and original.get("split") != "train")
                or hashlib.sha256(original["text"].encode()).hexdigest() != row["text_utf8_sha256"]
                or original["text_utf8_sha256"] != row["text_utf8_sha256"]
                or any(value is not None for value in original["labels"].values())
                or hashlib.sha256(canonical(binding)).hexdigest() != row["source_record_digest"]):
            raise ValueError("preserved pre-outcome source bytes or record identity differ")
        sources.append(row["source_id"])
        groups.append(row["group_id"])
    if len(set(sources)) != len(sources):
        raise ValueError("duplicate input source")
    return arrays, rows, groups


def load_training_inputs(root, *, expected_manifest_sha256):
    meta = verify_bundle(root, expected_manifest_sha256=expected_manifest_sha256)
    spec = meta["training"]
    if (spec.get("role") != "train" or spec.get("seed") != 7 or spec.get("budget") != 32
            or spec.get("archive") != "training.npz" or spec.get("rows") != "training-rows.json"):
        raise ValueError("exact frozen seed7/n32 TRAIN bank required")
    arrays, rows, groups = _read_arrays(root, spec, ("features", "labels"))
    y = arrays["labels"]
    if (arrays["features"].shape != (32, 770) or y.shape != (32,) or y.dtype != np.int64
            or np.any((y < 0) | (y > 1)) or np.bincount(y, minlength=2).tolist() != [16, 16]
            or len(set(groups)) != 32 or array_digest(y) != spec["label_array_sha256"]
            or [r["source_id"] for r in rows] != spec["source_ids"]):
        raise ValueError("balanced distinct TRAIN groups or exact labels differ")
    return meta, arrays["features"], y, rows


def load_serving_inputs(root, *, expected_manifest_sha256):
    meta = verify_bundle(root, expected_manifest_sha256=expected_manifest_sha256)
    spec = meta["serving"]
    if (spec.get("archive") != "serving.npz" or spec.get("rows") != "serving-rows.json"
            or spec.get("labels_included") is not False):
        raise ValueError("serving feature-only input contract required")
    arrays, rows, _ = _read_arrays(root, spec, ("features",))
    if (arrays["features"].shape != (64, 770)
            or len({r["source_record_digest"] for r in rows}) != 64):
        raise ValueError("exactly 64 source-bound regression inputs required")
    return meta, arrays["features"], rows


def load_states(root, meta, mode):
    if mode not in MODES:
        raise ValueError("unknown frozen Head architecture")
    states = sorted((s for s in meta["states"] if s["mode"] == mode), key=lambda s: (s["seed"], s["budget"]))
    heads, calibrators = [], []
    for state in states:
        shapes = {"W": ((770, 2), np.float64), "b": ((2,), np.float64)}
        if mode != "linear":
            shapes.update(a=((770,), np.float64), g=((770,), np.float64))
        if mode == "residual":
            shapes.update(V=((770, 4), np.float64), U=((4, 770), np.float64))
        check_npz(member(root, state["artifact"]+"/weights.npz"), shapes)
        head = NumpyCellHead.load(member(root, state["artifact"]), meta["feature_identity"])
        if (head.mode != mode or head.width != 770 or head.classes != 2 or head.rank != 4
                or head.digest() != state["predictor_sha256"]):
            raise ValueError("frozen predictor state differs")
        fitted = json.loads(member(root, state["calibration"]).read_bytes())
        if hashlib.sha256(canonical(fitted)).hexdigest() != state["calibration_sha256"]:
            raise ValueError("complete calibration record differs")
        validate_bounded_calibrator(fitted, expected_bindings={"feature_identity": meta["feature_identity"],
            "predictor_sha256": head.digest(), "calibration_context_sha256": meta["calibration_context_sha256"]})
        heads.append(head)
        calibrators.append(fitted)
    return heads, calibrators
