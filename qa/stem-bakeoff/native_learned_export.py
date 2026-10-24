"""Lossless bounded export of the fixed NumPy Heads for actual native inference."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import time

import numpy as np

from cell_learning_models import NumpyCellHead, canonical
from cell_runtime_bundle import load_serving_inputs, load_states, sha_file


FEATURE_MAGIC = b"HEPTA-CELL-FEATURES-770-F64-V1\0"
HEAD_MAGIC = b"HEPTA-CELL-HEAD-770-F64-V1\0"
MODES = ("linear", "gated", "residual")
CODE = ("native_learned_export.py", "cell_runtime_bundle.py", "cell_learning_models.py",
        "cell_learning_metrics.py", "CELL_NATIVE_RESUME_PROTOCOL.md")


def digest_bytes(value):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value) or value == "0"*64:
        raise ValueError("nonzero canonical SHA256 required")
    return bytes.fromhex(value)


def generation_bytes(value):
    if type(value) is not int or not 1 <= value < 2**64:
        raise ValueError("nonzero bounded generation required")
    return struct.pack("<Q", value)


def encode_features(features, source_digests, feature_identity, generation):
    """Validate bounds before copying the existing raw feature matrix."""
    if (type(features) is not np.ndarray or features.ndim != 2
            or not 1 <= features.shape[0] <= 64 or features.shape[1] != 770
            or features.dtype not in (np.dtype("float32"), np.dtype("float64"))
            or not np.isfinite(features).all()):
        raise ValueError("finite bounded 770D source features required")
    if (type(source_digests) not in (list, tuple) or len(source_digests) != len(features)
            or len(set(source_digests)) != len(source_digests)):
        raise ValueError("one distinct ordered source identity per row required")
    sources = b"".join(digest_bytes(value) for value in source_digests)
    raw = features.astype("<f8", copy=True)
    if not np.isfinite(np.square(raw).sum(axis=1)).all():
        raise ValueError("normalization would overflow")
    return (FEATURE_MAGIC+digest_bytes(feature_identity)+generation_bytes(generation)
            + struct.pack("<Q", len(features))+sources+raw.tobytes(order="C"))


def encode_head(head, feature_identity, generation, task_id):
    """Preserve every original FP64 parameter and the original predictor digest."""
    if (type(head) is not NumpyCellHead or (head.width, head.classes, head.rank) != (770, 2, 4)
            or head.mode not in MODES or task_id != "action_usefulness"
            or head.feature_identity != feature_identity):
        raise ValueError("fixed 770D binary action Head required")
    shapes = {"W": (770, 2), "b": (2,)}
    if head.mode != "linear":
        shapes.update(a=(770,), g=(770,))
    if head.mode == "residual":
        shapes.update(U=(4, 770), V=(770, 4))
    if set(head.params) != set(shapes):
        raise ValueError("exact parameter set required")
    arrays = []
    for name in sorted(shapes):
        value = head.params[name]
        if (type(value) is not np.ndarray or value.shape != shapes[name]
                or value.dtype.str != "<f8" or not np.isfinite(value).all()):
            raise ValueError("exact finite little-endian FP64 arrays required")
        arrays.append(value.tobytes(order="C"))
    return (HEAD_MAGIC+bytes([MODES.index(head.mode)])+digest_bytes(feature_identity)
            + generation_bytes(generation)+hashlib.sha256(task_id.encode()).digest()
            + digest_bytes(head.digest())+b"".join(arrays))


def write(path, data):
    with Path(path).open("xb") as stream:
        stream.write(data)
    return {"path": Path(path).name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def export(bundle, expected_manifest_sha256, output):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    output = Path(output)
    if output.exists() or any(p.is_symlink() for p in (output.absolute(), *output.absolute().parents)):
        raise ValueError("new ordinary export directory required")
    code = {name: sha_file(Path(__file__).with_name(name)) for name in CODE}
    meta, x, rows = load_serving_inputs(bundle, expected_manifest_sha256=expected_manifest_sha256)
    if meta["task_id"] != "action_usefulness" or meta["generation"] != 1 or len(rows) != 64:
        raise ValueError("fixed source-bound 64-row bundle required")
    sources = [row["source_record_digest"] for row in rows]
    output.mkdir(parents=True)
    files, heads, reference = {}, [], {}
    try:
        feature = write(output/"features.f770", encode_features(x, sources, meta["feature_identity"], 1))
        files[feature["path"]] = feature
        for mode in MODES:
            frozen, _ = load_states(bundle, meta, mode)
            for index, head in enumerate(frozen):
                key = f"{mode}-{index}"
                record = write(output/(key+".h770"), encode_head(head, meta["feature_identity"], 1, meta["task_id"]))
                files[record["path"]] = record
                heads.append({"id": key, "path": record["path"], "artifact_digest": record["sha256"],
                    "predictor_digest": head.digest()})
                logits = head.predict_logits(x)
                reference[key] = {"mode": mode, "predictor_digest": head.digest(),
                    "raw_logits": logits.tolist(), "argmax": np.argmax(logits, axis=1).tolist(),
                    "logits_f64_sha256": hashlib.sha256(logits.astype("<f8").tobytes()).hexdigest()}
        request = {"schema": "hepta.native-learned-replay-request.v1", "feature_identity": meta["feature_identity"],
            "generation": 1, "task_digest": hashlib.sha256(meta["task_id"].encode()).hexdigest(),
            "features": {"path": feature["path"], "artifact_digest": feature["sha256"]}, "heads": heads}
        for name, value in (("request.json", request), ("reference.json", reference)):
            files[name] = write(output/name, canonical(value)+b"\n")
        load_serving_inputs(bundle, expected_manifest_sha256=expected_manifest_sha256)
        if any(sha_file(Path(__file__).with_name(name)) != pin for name, pin in code.items()):
            raise ValueError("native exporter implementation changed")
        manifest = {"schema": "hepta.native-learned-export.v1", "bundle_manifest_sha256": expected_manifest_sha256,
            "feature_identity": meta["feature_identity"], "source_record_digests": sources,
            "source_ids": [row["source_id"] for row in rows], "source_code_sha256": code,
            "files": files, "request_sha256": files["request.json"]["sha256"], "rows": 64, "heads": len(heads),
            "task_count": 1, "width": 770, "numpy_scalar_reference_head_row_evaluations": 64*len(heads),
            "native_logit_absolute_tolerance": 1e-9, "native_argmax_must_match": True,
            "parameter_updates": 0, "encoder_calls": 0, "quality_scoring": False,
            "native_calibration": None, "mode": "SHADOW_ONLY", "authority": "DENY_ALL",
            "quality_qualified": False, "wall_ns_before_manifest": time.perf_counter_ns()-began,
            "cpu_ns_before_manifest": time.process_time_ns()-cpu}
        write(output/"manifest.json", canonical(manifest)+b"\n")
        return manifest
    except Exception as error:
        write(output/"failed.json", canonical({"error": repr(error), "partial_files_retained": True,
            "wall_ns": time.perf_counter_ns()-began, "cpu_ns": time.process_time_ns()-cpu})+b"\n")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("bundle", "manifest-sha256", "output"):
        parser.add_argument("--"+name, required=True)
    args = parser.parse_args()
    result = export(args.bundle, args.manifest_sha256, args.output)
    print(json.dumps({key: result[key] for key in ("heads", "rows", "request_sha256", "parameter_updates")}))
