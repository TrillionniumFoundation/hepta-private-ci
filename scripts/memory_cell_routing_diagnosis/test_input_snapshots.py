"""Small path-replacement controls for routing input snapshots; no model loads."""

import ast
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np


HERE = Path(__file__).resolve().parent
OBSERVATIONS = []


def selected_functions(path, names, namespace):
    tree = ast.parse(path.read_text())
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    ]
    found = {node.name for node in selected}
    if found != set(names):
        raise ValueError(f"missing selected functions: {set(names) - found}")
    module = ast.Module(body=selected, type_ignores=[])
    exec(compile(module, str(path), "exec"), namespace)
    return namespace


def function_namespace():
    common_path = HERE / "diagnosis_common.py"
    tree = ast.parse(common_path.read_text())
    names = {"canonical", "file_sha", "retain"}
    if any(
        isinstance(node, ast.FunctionDef) and node.name == "pinned_bytes"
        for node in tree.body
    ):
        names.add("pinned_bytes")
    namespace = {"hashlib": hashlib, "json": json, "os": os, "Path": Path, "stat": stat}
    return selected_functions(common_path, names, namespace)


@contextmanager
def replace_after_first_read(target, replacement, observations):
    """Use the same actual inode/path swap against original and repaired readers."""
    original_open = Path.open
    triggered = False

    class CapturedFile:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def read(self, size=-1):
            nonlocal triggered
            payload = self.stream.read(size)
            observations.append(size)
            if not triggered:
                triggered = True
                other = target.with_name(target.name + ".replacement")
                with original_open(other, "wb") as out:
                    out.write(replacement)
                os.replace(other, target)
            return payload

    def observed_open(path, mode="r", *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        if path == target and mode == "rb" and not triggered:
            return CapturedFile(stream)
        return stream

    with patch.object(Path, "open", observed_open):
        yield
    if not triggered:
        raise AssertionError("the actual authenticated file read was not observed")


class SnapshotTests(unittest.TestCase):
    def prepared(self, output):
        values = {
            "protocol": {
                "repo": "/fixed-repo",
                "historical": "/fixed-history",
                "model": "/fixed-model",
            },
            "input-pins": {"fixed": "source"},
            "source-identity": {"diagnosis_sources": {}},
            "cohort-pins": {"bound": "original"},
        }
        names = {
            "protocol": "protocol_sha256",
            "input-pins": "input_pins_sha256",
            "source-identity": "source_identity_sha256",
            "cohort-pins": "cohort_pins_sha256",
        }
        receipt = {}
        for name, key in names.items():
            payload = json.dumps(values[name], sort_keys=True).encode()
            (output / (name + ".json")).write_bytes(payload)
            receipt[key] = hashlib.sha256(payload).hexdigest()
        (output / "prepared.json").write_text(json.dumps(receipt))
        namespace = function_namespace()
        namespace.update(
            configure=lambda _: None,
            protocol=lambda *_: values["protocol"],
            identity=lambda _: values["source-identity"],
            inputs=lambda _: values["input-pins"],
        )
        selected_functions(
            HERE / "diagnosis_trial.py", {"validate_prepared"}, namespace
        )
        return namespace, values

    def features(self, output, *, bad_pin=False, wrong_path=False):
        namespace = function_namespace()
        questions = [f"question-{number}" for number in range(424)]
        expected = np.arange(424, dtype=np.float32).reshape(424, 1)
        source = io.BytesIO()
        np.save(source, expected, allow_pickle=False)
        content = source.getvalue()
        target = output / "worker" / "parent-features.npy"

        def worker(*args, **kwargs):
            self.assertEqual(kwargs["timeout"], 600)
            self.assertEqual(kwargs["capture_output"], True)
            self.assertEqual(kwargs["check"], False)
            request = json.loads(kwargs["input"])
            self.assertEqual(request["questions"], questions)
            self.assertEqual(len(request["questions"]), 424)
            target.parent.mkdir(parents=True)
            target.write_bytes(content)
            receipt = {
                "model_forwards": 424,
                "optimizer_updates": 0,
                "version": "fixed",
                "adapter_enabled": True,
                "path": str(target.with_name("other.npy") if wrong_path else target),
                "sha256": "0" * 64 if bad_pin else hashlib.sha256(content).hexdigest(),
                "prompts": [{"question": value} for value in questions],
                "shape": [424, 1],
                "wall_seconds": 0.01,
                "parent_cpu_seconds": 0.0,
                "child_cpu_seconds": 0.0,
            }
            return SimpleNamespace(
                returncode=0, stdout=json.dumps(receipt).encode(), stderr=b""
            )

        namespace.update(
            __file__=str(HERE / "diagnosis_execution.py"),
            io=io,
            np=np,
            sys=sys,
            time=time,
            subprocess=SimpleNamespace(
                run=worker, TimeoutExpired=subprocess.TimeoutExpired
            ),
            cpu_snapshot=lambda: {},
            cpu_delta=lambda _: {"parent_cpu_seconds": 0.0, "child_cpu_seconds": 0.0},
            retain_timeout=lambda *_: self.fail("unexpected timeout"),
        )
        selected_functions(
            HERE / "diagnosis_execution.py", {"parent_features"}, namespace
        )
        return namespace, questions, expected, target, content

    def test_prepared_json_path_swap_never_loads_unpinned_document(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            namespace, original = self.prepared(output)
            target = output / "cohort-pins.json"
            replacement = json.dumps({"bound": "replacement"}).encode()
            reads = []
            with replace_after_first_read(target, replacement, reads):
                try:
                    loaded = namespace["validate_prepared"](output)
                except ValueError as error:
                    self.assertEqual(str(error), "prepared evidence pin changed")
                    result = "rejected"
                else:
                    result = loaded["cohort-pins"]["bound"]
                    self.assertEqual(loaded["cohort-pins"], original["cohort-pins"])
            self.assertEqual(target.read_bytes(), replacement)
            OBSERVATIONS.append(
                {
                    "case": "prepared-json-path-swap",
                    "result": result,
                    "read_sizes": reads,
                }
            )

    def test_parent_feature_path_swap_never_loads_unpinned_matrix(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "features"
            namespace, questions, expected, target, _ = self.features(output)
            replacement_stream = io.BytesIO()
            np.save(
                replacement_stream,
                np.full((424, 1), 7, dtype=np.float32),
                allow_pickle=False,
            )
            replacement = replacement_stream.getvalue()
            reads = []
            with replace_after_first_read(target, replacement, reads):
                try:
                    vectors, _ = namespace["parent_features"](
                        "/fixed-repo",
                        "/fixed-model",
                        "fixed",
                        questions,
                        output,
                        "fixed-scope",
                    )
                except ValueError as error:
                    self.assertEqual(
                        str(error),
                        "parent worker request, feature file or model receipt mismatch",
                    )
                    result = "rejected"
                else:
                    result = float(vectors[0, 0])
                    np.testing.assert_array_equal(vectors, expected)
            self.assertEqual(target.read_bytes(), replacement)
            OBSERVATIONS.append(
                {"case": "feature-npy-path-swap", "result": result, "read_sizes": reads}
            )

    def test_unchanged_inputs_preserve_prepared_values_and_features(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            namespace, original = self.prepared(root)
            self.assertEqual(namespace["validate_prepared"](root), original)
            output = root / "features"
            namespace, questions, expected, _, _ = self.features(output)
            vectors, receipt = namespace["parent_features"](
                "/fixed-repo", "/fixed-model", "fixed", questions, output, "fixed-scope"
            )
            np.testing.assert_array_equal(vectors, expected)
            self.assertEqual(receipt["model_forwards"], 424)
            self.assertEqual(receipt["optimizer_updates"], 0)
            self.assertTrue(receipt["worker_process_exited"])

    def test_wrong_prepared_pin_is_rejected_before_json_parse(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            namespace, _ = self.prepared(output)
            (output / "cohort-pins.json").write_bytes(b"not valid json")
            with self.assertRaisesRegex(ValueError, "^prepared evidence pin changed$"):
                namespace["validate_prepared"](output)

    def test_wrong_feature_pin_is_rejected_before_numpy_load(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "features"
            namespace, questions, _, _, _ = self.features(output, bad_pin=True)
            with patch.object(
                np, "load", side_effect=AssertionError("unverified load")
            ):
                with self.assertRaisesRegex(
                    ValueError, "feature file or model receipt"
                ):
                    namespace["parent_features"](
                        "/fixed-repo",
                        "/fixed-model",
                        "fixed",
                        questions,
                        output,
                        "fixed-scope",
                    )

    def test_feature_path_identity_precedes_snapshot_open(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "features"
            namespace, questions, _, _, _ = self.features(output, wrong_path=True)
            if "pinned_bytes" in namespace:
                namespace["pinned_bytes"] = lambda *_: self.fail(
                    "unvalidated file open"
                )
            namespace["file_sha"] = lambda *_: self.fail("unvalidated file open")
            with self.assertRaisesRegex(ValueError, "feature file or model receipt"):
                namespace["parent_features"](
                    "/fixed-repo",
                    "/fixed-model",
                    "fixed",
                    questions,
                    output,
                    "fixed-scope",
                )

    def test_snapshot_rejects_growth_with_observed_size_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "input.json"
            raw = b'{"value":1}'
            target.write_bytes(raw)
            namespace = function_namespace()
            original_open = Path.open
            reads = []

            class GrowingFile:
                def __init__(self, stream):
                    self.stream = stream

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return self.stream.__exit__(*args)

                def __getattr__(self, name):
                    return getattr(self.stream, name)

                def read(self, size=-1):
                    reads.append(size)
                    value = self.stream.read(size)
                    with original_open(target, "ab") as out:
                        out.write(b" ")
                    return value

            def growing_open(path, mode="r", *args, **kwargs):
                stream = original_open(path, mode, *args, **kwargs)
                return (
                    GrowingFile(stream) if path == target and mode == "rb" else stream
                )

            with patch.object(Path, "open", growing_open):
                with self.assertRaisesRegex(ValueError, "^changed$"):
                    namespace["pinned_bytes"](
                        target, hashlib.sha256(raw).hexdigest(), "changed"
                    )
            self.assertEqual(reads, [len(raw) + 1])


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        print(
            json.dumps(
                {
                    "snapshot_observations": OBSERVATIONS,
                    "models_or_original_children_executed": False,
                },
                sort_keys=True,
            )
        )
