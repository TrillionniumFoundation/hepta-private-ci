"""First checkpoint reads and pin ordering; no model runtime or weights needed."""

import builtins
from contextlib import redirect_stdout
import io
import json
import multiprocessing
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

import native_backend as backend
import native_worker as worker
import checkpoint_io


def fifo_probe(request, path, replace, queue):
    path = Path(path)
    original = os.open

    def opened(candidate, flags, *args, **kwargs):
        if Path(candidate) == path:
            path.unlink()
            os.mkfifo(path)
        return original(candidate, flags, *args, **kwargs)

    try:
        with patch("importlib.metadata.version", return_value="test-runtime"):
            if replace:
                with patch("checkpoint_io.os.open", side_effect=opened):
                    worker.run(request)
            else:
                worker.run(request)
    except (ValueError, OSError) as error:
        queue.put(("rejected", str(error)))
    else:
        queue.put(("accepted", ""))


class NativePreflightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = Path(__file__).resolve().parents[2]
        self.model = self.root / "model"
        self.checkpoint = self.root / "checkpoint"
        self.model.mkdir()
        self.checkpoint.mkdir()
        (self.model / "model.safetensors").write_bytes(b"base inventory fixture")
        (self.model / "tokenizer.json").write_bytes(b"tokenizer inventory fixture")
        self.adapter = self.checkpoint / "adapter_model.safetensors"
        self.adapter.write_bytes(b"adapter inspection fixture, not a model")
        self.manifest = self.checkpoint / "lineage.json"
        self.lineage = {
            "base_identity": backend.sha(
                backend.canonical(backend.file_set(self.model, self.model.iterdir()))
            ),
            "adapter_sha256": backend.sha(self.adapter.read_bytes()),
            "roots": ["source-root"],
            "scope": "scope",
        }
        self.manifest.write_bytes(backend.canonical(self.lineage))
        versions = patch("importlib.metadata.version", return_value="test-runtime")
        versions.start()
        self.addCleanup(versions.stop)

    def inspect(self):
        return backend.inspect(self.repo, self.model, self.checkpoint)

    def request(self, pins):
        return json.dumps(
            {
                "schema": "hepta.memory-cell.native-request.v1",
                "repo": str(self.repo),
                "model": str(self.model),
                "checkpoint": str(self.checkpoint),
                "scope": "scope",
                "source_root": "source-root",
                "rank": 8,
                "seed": 2718,
                "pins": pins,
                "question": "question",
                "query_digest": "query",
                "source_binding_digest": "binding",
                "neuron_request": {
                    "request_id": "request",
                    "config_id": "config",
                    "generation": 1,
                    "model_id": "model",
                    "encoder_digest": backend.sha(backend.ENCODER),
                    "head_digest": backend.sha(backend.HEAD),
                    "weights_digest": pins["weights_digest"],
                    "input_digest": "binding",
                    "feature_vector_q24": backend.features("question"),
                    "expected_output_width": 4,
                },
            }
        ).encode()

    def test_same_bytes_produce_same_pins_and_equal_pins_reach_model_boundary(self):
        pins, evidence = self.inspect()
        self.assertEqual(self.inspect(), (pins, evidence))
        self.assertEqual(evidence["lineage"], self.lineage)
        self.assertEqual(
            pins["manifest_sha256"], backend.sha(self.manifest.read_bytes())
        )
        self.assertEqual(pins["adapter_sha256"], backend.sha(self.adapter.read_bytes()))
        original = builtins.__import__

        class ModelBoundaryReached(Exception):
            pass

        def imported(name, *args, **kwargs):
            if name == "torch":
                raise ModelBoundaryReached
            return original(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=imported):
            with self.assertRaises(ModelBoundaryReached):
                worker.run(self.request(pins))
            for field in ("manifest_sha256", "adapter_sha256", "weights_digest"):
                with (
                    self.subTest(field=field),
                    self.assertRaisesRegex(ValueError, "pins differ"),
                ):
                    worker.run(self.request(pins | {field: "0" * 64}))

    def test_changed_bytes_cannot_reuse_expected_pins(self):
        pins, _ = self.inspect()
        self.manifest.write_bytes(self.manifest.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "pins differ"):
            worker.run(self.request(pins))
        self.manifest.write_bytes(backend.canonical(self.lineage))
        self.adapter.write_bytes(b"different adapter")
        with self.assertRaisesRegex(ValueError, "adapter bytes changed"):
            worker.run(self.request(pins))

    def test_inspection_and_configuration_cli_use_the_same_bounded_reads(self):
        pins, evidence = self.inspect()
        (self.root / "protocol.json").write_text(
            json.dumps({"scope": "scope", "rank": 8, "seed": 2718})
        )
        entrypoints = (
            ("native_backend.py", ["--checkpoint", str(self.checkpoint)]),
            ("native_trial.py", ["configure", "--run", str(self.root)]),
        )
        for filename, arguments in entrypoints:
            script = Path(__file__).resolve().parent / filename
            arguments = [
                str(script),
                *arguments,
                "--repo",
                str(self.repo),
                "--model",
                str(self.model),
            ]
            output = io.StringIO()
            with patch.object(sys, "argv", arguments), redirect_stdout(output):
                runpy.run_path(str(script), run_name="__main__")
            result = json.loads(output.getvalue())
            self.assertEqual(result["pins"], pins)
            if filename == "native_backend.py":
                self.assertEqual(result["inspection"], evidence)
            else:
                self.assertEqual(
                    json.loads((self.root / "native_inspection.json").read_text()),
                    evidence,
                )
            for path, limit in (
                (self.manifest, checkpoint_io.MAX_MANIFEST_BYTES),
                (self.adapter, checkpoint_io.MAX_ADAPTER_BYTES),
            ):
                original = path.read_bytes()
                with path.open("wb") as stream:
                    stream.truncate(limit + 1)
                with (
                    self.subTest(entrypoint=filename, file=path.name),
                    patch.object(sys, "argv", arguments),
                    self.assertRaisesRegex(ValueError, "candidate byte bound"),
                ):
                    runpy.run_path(str(script), run_name="__main__")
                path.write_bytes(original)

    def test_checkpoint_bounds_before_parsing_hashing_or_pin_comparison(self):
        pins, _ = self.inspect()
        for path, limit in (
            (self.manifest, checkpoint_io.MAX_MANIFEST_BYTES),
            (self.adapter, checkpoint_io.MAX_ADAPTER_BYTES),
        ):
            original = path.read_bytes()
            for size in (0, limit + 1):
                with self.subTest(file=path.name, size=size):
                    with path.open("wb") as stream:
                        stream.truncate(size)
                    with self.assertRaisesRegex(ValueError, "candidate byte bound"):
                        worker.run(self.request(pins))
            path.write_bytes(original)

    def test_manifest_exact_bound_and_fixed_filenames(self):
        content = self.manifest.read_bytes()
        self.manifest.write_bytes(
            content + b" " * (checkpoint_io.MAX_MANIFEST_BYTES - len(content))
        )
        pins, _ = self.inspect()
        self.assertEqual(
            pins["manifest_sha256"], backend.sha(self.manifest.read_bytes())
        )
        for path in (self.manifest, self.adapter):
            moved = path.with_suffix(".other")
            path.rename(moved)
            with self.subTest(file=path.name), self.assertRaises(FileNotFoundError):
                self.inspect()
            moved.rename(path)

    def test_overlapping_model_checkpoint_bounds_precede_any_inventory_read(self):
        nested = self.model / "checkpoint"
        self.checkpoint.rename(nested)
        self.checkpoint = nested
        for name, limit in (
            ("lineage.json", checkpoint_io.MAX_MANIFEST_BYTES),
            ("adapter_model.safetensors", checkpoint_io.MAX_ADAPTER_BYTES),
        ):
            path = nested / name
            original = path.read_bytes()
            with path.open("wb") as stream:
                stream.truncate(limit + 1)
            with (
                self.subTest(file=name),
                patch.object(
                    backend,
                    "file_set",
                    side_effect=AssertionError("inventory read first"),
                ),
                self.assertRaisesRegex(ValueError, "candidate byte bound"),
            ):
                self.inspect()
            path.write_bytes(original)

    def test_base_inventory_is_not_capped_at_adapter_limit(self):
        path = self.model / "model.safetensors"
        with path.open("wb") as stream:
            stream.truncate(checkpoint_io.MAX_ADAPTER_BYTES + 1)
        self.lineage["base_identity"] = backend.sha(
            backend.canonical(backend.file_set(self.model, self.model.iterdir()))
        )
        self.manifest.write_bytes(backend.canonical(self.lineage))
        _, evidence = self.inspect()
        self.assertEqual(evidence["model"][path.name]["bytes"], path.stat().st_size)

    def test_checkpoint_directories_and_leaf_symlinks_are_rejected(self):
        for path in (self.manifest, self.adapter):
            original = path.read_bytes()
            path.unlink()
            path.mkdir()
            with (
                self.subTest(file=path.name),
                self.assertRaisesRegex(ValueError, "regular file"),
            ):
                self.inspect()
            path.rmdir()
            target = self.root / path.name
            target.write_bytes(original)
            try:
                path.symlink_to(target)
            except OSError as error:
                self.skipTest(f"symlink creation unavailable: {error}")
            with (
                self.subTest(file=path.name),
                self.assertRaisesRegex(ValueError, "symlink"),
            ):
                self.inspect()
            path.unlink()
            path.write_bytes(original)

    @unittest.skipUnless(os.name == "posix" and hasattr(os, "mkfifo"), "POSIX FIFO")
    def test_worker_fifo_and_fifo_replacement_reject_without_blocking(self):
        pins, _ = self.inspect()
        context = multiprocessing.get_context("spawn")
        for path in (self.manifest, self.adapter):
            original = path.read_bytes()
            for replace in (False, True):
                with self.subTest(file=path.name, replace=replace):
                    if not replace:
                        path.unlink()
                        os.mkfifo(path)
                    queue = context.Queue()
                    process = context.Process(
                        target=fifo_probe,
                        args=(self.request(pins), str(path), replace, queue),
                    )
                    process.start()
                    process.join(10)
                    blocked = process.is_alive()
                    if blocked:
                        process.terminate()
                        process.join(5)
                    self.assertFalse(
                        blocked, "checkpoint FIFO blocked first inspection"
                    )
                    self.assertEqual(process.exitcode, 0)
                    status, reason = queue.get(timeout=5)
                    self.assertEqual(status, "rejected", reason)
                    queue.close()
                    queue.join_thread()
                    path.unlink()
                    path.write_bytes(original)

    def test_regular_inode_replacement_during_checkpoint_open_is_rejected(self):
        original_open = os.open
        for path in (self.manifest, self.adapter):
            replacement = self.root / path.name
            replacement.write_bytes(path.read_bytes())

            def opened(candidate, flags, *args, **kwargs):
                if Path(candidate) == path:
                    replacement.replace(path)
                return original_open(candidate, flags, *args, **kwargs)

            with (
                self.subTest(file=path.name),
                patch("checkpoint_io.os.open", side_effect=opened),
                self.assertRaisesRegex(ValueError, "identity changed"),
            ):
                self.inspect()

    def test_mutation_during_each_checkpoint_read_is_rejected(self):
        original_fstat = os.fstat
        for path, mutation_call in ((self.manifest, 2), (self.adapter, 4)):
            content = path.read_bytes()
            calls = 0

            def mutated(descriptor):
                nonlocal calls
                calls += 1
                if calls == mutation_call:
                    before = path.stat()
                    path.write_bytes(b"x" * len(content))
                    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1))
                return original_fstat(descriptor)

            with (
                self.subTest(file=path.name),
                patch("checkpoint_io.os.fstat", side_effect=mutated),
                self.assertRaisesRegex(ValueError, "changed during bounded read"),
            ):
                self.inspect()
            path.write_bytes(content)


if __name__ == "__main__":
    unittest.main()
