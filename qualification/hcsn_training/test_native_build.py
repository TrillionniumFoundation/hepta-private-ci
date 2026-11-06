"""Cargo artifact selection rejects incomplete, ambiguous, or escaped receipts."""

import json
from pathlib import Path
import tempfile
import unittest

from .native_build import native_libraries


class NativeBuildTests(unittest.TestCase):
    def test_selected_target_uses_reported_metadata_and_ignores_host_variant(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            deps = root/"deps"
            deps.mkdir()
            primary = root/"libexample.rlib"
            library, metadata = deps/"libexample-current.rlib", deps/"libexample-current.rmeta"
            host = deps/"libexample-host.rlib"
            primary.write_bytes(b"actual target fixture")
            library.write_bytes(primary.read_bytes())
            metadata.write_bytes(b"reported metadata fixture")
            host.write_bytes(b"different host feature set")
            records = [dict(reason="compiler-artifact", target=dict(name="example"),
                            profile=dict(test=False), filenames=[str(host)]),
                       dict(reason="compiler-artifact", target=dict(name="example"),
                            profile=dict(test=False), filenames=[str(primary),str(metadata)]),
                       dict(reason="build-finished", success=True)]
            receipt = root/"cargo.jsonl"
            receipt.write_text("".join(json.dumps(record)+"\n" for record in records))
            self.assertEqual(native_libraries(deps, ("example",), receipt), {"example": library})
            primary.write_bytes(b"alias replaced by a later build")
            with self.assertRaisesRegex(ValueError, "alias changed"):
                native_libraries(deps, ("example",), receipt)

    def test_selected_target_without_one_reported_metadata_rejects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            deps = root/"deps"
            deps.mkdir()
            primary = root/"libexample.rlib"
            primary.write_bytes(b"fixture")
            record = dict(reason="compiler-artifact", target=dict(name="example"),
                          profile=dict(test=False), filenames=[str(primary)])
            receipt = root/"cargo.jsonl"
            receipt.write_text(json.dumps(record)+"\n"+json.dumps(dict(reason="build-finished", success=True))+"\n")
            with self.assertRaisesRegex(ValueError, "metadata is ambiguous"):
                native_libraries(deps, ("example",), receipt)

    def test_exact_build_ignores_unselected_stale_library(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            deps = root/"deps"
            deps.mkdir()
            current, stale = deps/"libexample-current.rlib", deps/"libexample-stale.rlib"
            current.write_bytes(b"current fixture")
            stale.write_bytes(b"old fixture")
            primary, metadata = root/"libexample.rlib", deps/"libexample-current.rmeta"
            primary.write_bytes(current.read_bytes())
            metadata.write_bytes(b"reported metadata fixture")
            receipt = root/"cargo.jsonl"
            record = dict(reason="compiler-artifact", target=dict(name="example"),
                          profile=dict(test=False), filenames=[str(primary),str(metadata)])
            receipt.write_text(json.dumps(record)+"\n"+json.dumps(dict(reason="build-finished", success=True))+"\n")
            self.assertEqual(native_libraries(deps, ("example",), receipt), {"example": current})
            with self.assertRaises(ValueError):
                native_libraries(deps, ("example",))

    def test_host_only_record_cannot_substitute_for_explicit_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            host = root/"libexample-host.rlib"
            host.write_bytes(b"host fixture")
            receipt = root/"cargo.jsonl"
            record = dict(reason="compiler-artifact", target=dict(name="example"),
                          profile=dict(test=False), filenames=[str(host)])
            receipt.write_text(json.dumps(record)+"\n"+json.dumps(dict(reason="build-finished", success=True))+"\n")
            with self.assertRaisesRegex(ValueError, "explicit target record is missing"):
                native_libraries(root, ("example",), receipt)

    def test_incomplete_failed_ambiguous_and_wrong_directory_receipts_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            deps = root/"deps"
            deps.mkdir()
            paths = [deps/"libexample-a.rlib", deps/"libexample-b.rlib", root/"libexample-c.rlib"]
            for path in paths:
                path.write_bytes(b"library fixture")
            primary = root/"libexample.rlib"
            primary.write_bytes(b"library fixture")
            complete = dict(reason="build-finished", success=True)
            def artifact(path):
                return dict(reason="compiler-artifact", target=dict(name="example"),
                            profile=dict(test=False), filenames=[str(path)])
            def selected(metadata):
                return dict(reason="compiler-artifact", target=dict(name="example"),
                            profile=dict(test=False), filenames=[str(primary), str(metadata)])
            invalid = ([artifact(paths[0])],
                       [artifact(paths[0]), dict(reason="build-finished", success=False)],
                       [artifact(paths[0]), artifact(paths[1]), complete],
                       [artifact(paths[2]), complete],
                       [selected(paths[0].with_suffix(".rmeta")),
                        selected(paths[1].with_suffix(".rmeta")), complete],
                       [selected(paths[2].with_suffix(".rmeta")), complete],
                       [complete, artifact(paths[0])],
                       [artifact(paths[0]), complete, complete])
            receipt = root/"cargo.jsonl"
            for records in invalid:
                with self.subTest(records=records):
                    receipt.write_text("".join(json.dumps(record)+"\n" for record in records))
                    with self.assertRaises(ValueError):
                        native_libraries(deps, ("example",), receipt)
