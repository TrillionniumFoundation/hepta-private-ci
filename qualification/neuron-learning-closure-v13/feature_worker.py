"""Real fixed V13 execution. Imported only inside the resource-limited worker."""

import csv
import hashlib
import io
from pathlib import Path
import re
import sys
import tempfile
import types

import numpy as np

from bounded_npz import inspect_npz
from closure_common import (
    ClosureError,
    ClosureLimits,
    REFERENCE_HASHES,
    canonical,
    digest_text,
    integer,
    object_keys,
    read_capped,
    reference,
    sha,
    strict_json,
    text,
)
from closure_inputs import source_snapshot as check_sources
from closure_io import open_regular
from verify_closure import verify_checkpoint


EXTRA_SOURCES = {
    "tasks.py": "b2e9942631aa645b3e9e2d77ecd7bb8092fa4c7a2a3fa96efae0b9e6bbb49b54",
    "provenance_run.py": "7345a8a567d29836e3def7037fc6b97d034efcedfd28af877c2d65632eeb428b",
}


def _modules():
    reference()  # Verify the original four-member reference inventory.
    directory = Path(__file__).parent / "reference"
    modules = {}
    for name in (
        "adapter",
        "download_model",
        "backend",
        "tasks",
        "lifecycle",
        "provenance_run",
    ):
        path = directory / f"{name}.py.source"
        raw = read_capped(path, 32768)
        expected = {**REFERENCE_HASHES, **EXTRA_SOURCES}[f"{name}.py"]
        if sha(raw) != expected:
            raise ClosureError("Fixed executable reference source changed")
        module = types.ModuleType(name)
        module.__file__ = str(path)
        sys.modules[name] = module
        exec(compile(raw, str(path), "exec"), module.__dict__)
        modules[name] = module
    return modules


def _copy(source, target, maximum, limits, progress, *, root=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    count, digest = 0, hashlib.sha256()
    with (
        open_regular(source, maximum, root=root) as stream,
        target.open("xb") as output,
    ):
        while block := stream.read(min(1024**2, maximum - count + 1)):
            count += len(block)
            progress["admitted_source_copy_bytes"] += len(block)
            if (
                count > maximum
                or progress["admitted_source_copy_bytes"] > limits.input_bytes
            ):
                raise ClosureError("Replay material exceeds its admitted byte budget")
            output.write(block)
            progress["staging_copy_bytes"] += len(block)
            digest.update(block)
    return {"sha256": digest.hexdigest(), "bytes": count}


def _array_identity(value):
    array = np.ascontiguousarray(value)
    return {
        "dtype": array.dtype.str,
        "shape": list(array.shape),
        "sha256": sha(array.tobytes()),
    }


class _ObservedSession:
    """Observe the actual feeds passed by the unchanged FrozenEncoder."""

    def __init__(self, session, trace, progress):
        self.session, self.trace, self.progress = session, trace, progress

    def get_inputs(self):
        return self.session.get_inputs()

    def run(self, outputs, feeds):
        self.progress["encoder_batches_attempted"] += 1
        self.trace.append(
            {name: _array_identity(value) for name, value in sorted(feeds.items())}
        )
        result = self.session.run(outputs, feeds)
        self.progress["encoder_batches_completed"] += 1
        return result


class _FrozenSnapshot:
    """Read-only adapter to the original training_snapshot; no source authority."""

    def __init__(self, snapshot):
        self.snapshot_value = snapshot

    def snapshot(self, scope, source_ids):
        value = self.snapshot_value
        if scope != value["cut"]["scope"] or sorted(set(source_ids)) != [
            r["source_id"] for r in value["cut"]["records"]
        ]:
            raise ClosureError("The original producer cannot read this source scope")
        return value["cut"], value["records"]


def _dataset(root, name, limits, closure_limits):
    rows_raw = read_capped(root / f"{name}_rows.json", closure_limits.max_source_bytes)
    rows = strict_json(rows_raw)
    if not isinstance(rows, list) or not 1 <= len(rows) <= limits.max_dataset_rows:
        raise ClosureError("Original dataset row count exceeds the replay profile")
    for row in rows:
        if not isinstance(row, dict) or row.get("split") != "train":
            raise ClosureError("Only original training source rows are accepted")
        text(row.get("text"), closure_limits.max_source_body_bytes, "raw encoder text")
        digest_text(row.get("id"), "original row")
        integer(row.get("label"), 0, 11, "original class")
    raw = read_capped(root / f"{name}_features.npz", closure_limits.max_dataset_bytes)
    headers, _ = inspect_npz(raw, {"X", "y"}, closure_limits)
    if (
        headers["X"]["shape"] != (len(rows), 384)
        or headers["X"]["dtype"] != np.dtype("float32")
        or headers["y"]["shape"] != (len(rows),)
        or headers["y"]["dtype"].kind not in "iu"
    ):
        raise ClosureError("Original prepared feature shape/dtype is not V13")
    with np.load(io.BytesIO(raw), allow_pickle=False) as saved:
        X, y = saved["X"], saved["y"]
        if not np.isfinite(X).all() or y.tolist() != [row["label"] for row in rows]:
            raise ClosureError(
                "Original feature contents or labels differ from their raw rows"
            )
    return rows, X, {"rows_file_sha256": sha(rows_raw), "feature_file_sha256": sha(raw)}


def _same_features(actual, expected):
    if (
        actual.shape != expected.shape
        or np.ascontiguousarray(actual, dtype="<f8").tobytes()
        != np.ascontiguousarray(expected, dtype="<f8").tobytes()
    ):
        raise ClosureError(
            "Recomputed features differ from the exact source-bound NPZ; no tolerance or fallback"
        )


def execute_reference(config, limits, progress):
    bounds = ClosureLimits()
    with tempfile.TemporaryDirectory(prefix="hepta-v13-frozen-") as temporary:
        stage = Path(temporary)
        files = {}
        for key, name, maximum in (
            ("checkpoint_path", "model.npz", bounds.max_checkpoint_bytes),
            ("source_snapshot", "sources.json", bounds.max_source_bytes),
            ("encoder_manifest_path", "encoder.json", bounds.max_metadata_bytes),
            ("dataset_npz_path", "dataset.npz", bounds.max_dataset_bytes),
        ):
            files[name] = _copy(config[key], stage / name, maximum, limits, progress)
        release = None
        if config["release_manifest_path"] is not None:
            release = stage / "release.json"
            files["release.json"] = _copy(
                config["release_manifest_path"],
                release,
                bounds.max_metadata_bytes,
                limits,
                progress,
            )
        snapshot = strict_json(
            read_capped(stage / "sources.json", bounds.max_source_bytes)
        )
        source = check_sources(snapshot, bounds)
        bodies, datasets = [], set()
        for record in sorted(
            snapshot["records"],
            key=lambda item: (item["source_id"] != "skills", item["source_id"]),
        ):
            body = strict_json(record["body"])
            object_keys(
                body,
                {"dataset", "rows", "indices", "event", "feature_file_sha256"},
                "original source body",
            )
            name = body["dataset"]
            if not isinstance(name, str) or not re.fullmatch(
                r"[a-z0-9][a-z0-9-]{0,63}", name
            ):
                raise ClosureError("Invalid original dataset name")
            if (
                not isinstance(body["rows"], list)
                or not isinstance(body["indices"], list)
                or not 1
                <= len(body["rows"])
                == len(body["indices"])
                <= limits.max_dataset_rows
            ):
                raise ClosureError("Original source selection is not bounded")
            digest_text(body["feature_file_sha256"], "source feature archive")
            bodies.append((record, body))
            datasets.add(name)
        if len(datasets) > limits.max_datasets:
            raise ClosureError("Too many source datasets")
        for name in sorted(datasets):
            for suffix, maximum in (
                ("rows.json", bounds.max_source_bytes),
                ("features.npz", bounds.max_dataset_bytes),
            ):
                member = f"{name}_{suffix}"
                files[member] = _copy(
                    member,
                    stage / "inputs" / member,
                    maximum,
                    limits,
                    progress,
                    root=config["inputs_root"],
                )
        _, _, pins = reference()
        for name, (size, _, _) in pins["FILES"].items():
            files["encoder/" + name] = _copy(
                name,
                stage / "encoder" / name,
                size,
                limits,
                progress,
                root=config["encoder_root"],
            )
        closure = verify_checkpoint(
            stage / "model.npz",
            source_snapshot=stage / "sources.json",
            encoder_manifest_path=stage / "encoder.json",
            encoder_root=stage / "encoder",
            dataset_npz_path=stage / "dataset.npz",
            expected_data_id=config["expected_data_id"],
            release_manifest_path=release,
        )
        manifest = closure["encoder"]["manifest"]
        (stage / "encoder/manifest.json").write_bytes(
            canonical(
                {
                    key: manifest[key]
                    for key in ("schema", "model_id", "revision", "files")
                }
            )
        )
        modules = _modules()
        progress["encoder_loads_attempted"] += 1
        encoder = modules["backend"].FrozenEncoder(
            stage / "encoder",
            batch_size=32,
            max_length=manifest["max_length"],
            threads=manifest["intra_op_threads"],
        )
        if canonical(encoder.manifest) != canonical(manifest):
            raise ClosureError(
                "Actual encoder runtime/packages differ from the checkpoint manifest"
            )
        data, recomputed, trace = {}, {}, []
        encoder._session = _ObservedSession(encoder._session, trace, progress)
        for name in sorted(datasets):
            rows, expected, identity = _dataset(stage / "inputs", name, limits, bounds)
            progress["encoder_calls_attempted"] += 1
            first_batch = len(trace)
            actual = encoder.encode([row["text"] for row in rows])
            if actual.dtype != np.dtype("float32") or actual.tobytes(
                order="C"
            ) != expected.tobytes(order="C"):
                raise ClosureError(
                    "Original float32 encoder output is not byte-identical to its prepared dataset"
                )
            _same_features(actual, expected)
            data[name] = {
                **identity,
                "rows": rows,
                "batch_range": [first_batch, len(trace)],
                "features": _array_identity(actual),
            }
            recomputed[name] = actual
        selected, matrices, bindings = [], [], []
        for record, body in bodies:
            name = body["dataset"]
            if files[f"{name}_features.npz"]["sha256"] != body["feature_file_sha256"]:
                raise ClosureError("Original source-bound feature archive changed")
            rows = data[name]["rows"]
            indices = [
                integer(index, 0, len(rows) - 1, "source row index")
                for index in body["indices"]
            ]
            chosen = [rows[index] for index in indices]
            if canonical(chosen) != canonical(body["rows"]):
                raise ClosureError("Raw rows differ from their exact source bodies")
            selected.extend(chosen)
            matrices.append(recomputed[name][indices])
            bindings.append(
                {
                    "source_id": record["source_id"],
                    "revision": record["revision"],
                    "body_sha256": record["body_sha256"],
                    "dataset": name,
                    "indices": indices,
                    "row_ids": [row["id"] for row in chosen],
                }
            )
        cut, expected, labels, row_ids = modules["provenance_run"].training_snapshot(
            _FrozenSnapshot(snapshot),
            stage / "inputs",
            [r["source_id"] for r in snapshot["records"]],
        )
        actual = np.vstack(matrices)
        _same_features(actual, expected)
        if cut != snapshot["cut"] or row_ids != [row["id"] for row in selected]:
            raise ClosureError("Original source reducer order changed")
        with np.load(stage / "dataset.npz", allow_pickle=False) as saved:
            _same_features(actual, saved["X"])
            if not np.array_equal(labels, saved["y"]):
                raise ClosureError(
                    "Aggregate labels differ from the original source reducer"
                )
        model = modules["adapter"].Adapter.load(
            stage / "model.npz",
            expected_encoder_hash=encoder.manifest_hash,
            expected_source_version=source["source_version"],
            expected_data_id=config["expected_data_id"],
        )
        before = model.state_hash()
        progress["adapter_calls_attempted"] += 1
        predictions = model.predict(actual).tolist()
        outputs = []
        for row, prediction in zip(selected, predictions):
            public = modules["tasks"].public_input(row)
            progress["executor_calls_attempted"] += 1
            try:
                output = modules["tasks"].execute(prediction, public["payload"])
                error = None
            except (ValueError, TypeError, ArithmeticError, csv.Error) as failure:
                output, error = None, type(failure).__name__
            outputs.append(
                {
                    "row_id": row["id"],
                    "public_input_sha256": sha(canonical(public)),
                    "predicted_skill": modules["tasks"].SKILLS[prediction],
                    "output": output,
                    "error": error,
                }
            )
        after = model.state_hash()
        if before != after or before != closure["checkpoint"]["legacy_state_sha256"]:
            raise ClosureError("Inference changed the complete checkpoint state")
        return {
            "status": "VERIFIED",
            "scope": "Exact V13 feature derivation and finite pure reference execution; no ordinary runtime, independent quality or adoption qualification",
            "source": source,
            "closure": closure,
            "materials": files,
            "features": {
                "profile": "original-v13-training-snapshot",
                "batch_size": 32,
                "source_order": bindings,
                "datasets": {
                    key: {k: v for k, v in value.items() if k != "rows"}
                    for key, value in data.items()
                },
                "actual_onnx_feeds": trace,
                "aggregate": _array_identity(actual),
                "source_dataset_float32_bytes_equal": True,
                "aggregate_float64_canonical_bytes_equal": True,
                "encoder_stats": encoder.stats,
            },
            "reference_cell": {
                "profile": "frozen-minilm-residual-classifier-pure-skill",
                "outputs": outputs,
                "state_before": before,
                "state_after": after,
                "state_semantics": "Complete frozen Adapter state is unchanged by inference; no recurrent Cell state transition is claimed",
                "external_operations": 0,
                "quality_evaluation_performed": False,
                "adoption_performed": False,
            },
            "executed_source_sha256": {**REFERENCE_HASHES, **EXTRA_SOURCES},
        }
