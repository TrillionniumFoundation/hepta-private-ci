"""Real artifact substitution, installed-file binding and observed race controls."""

import copy
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import data, paired_loop, runtime_artifacts as artifacts


class RuntimeArtifactTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.package = self.root / "runtime_fixture"
        self.package.mkdir()
        self.source = self.package / "__init__.py"
        self.source.write_bytes(b"value = 1\n")
        metadata = self.root / "runtime_fixture-1.0.dist-info"
        metadata.mkdir()
        (metadata / "METADATA").write_text("Name: runtime-fixture\nVersion: 1.0\n")
        (metadata / "RECORD").write_text(
            "runtime_fixture/__init__.py,,\n"
            "runtime_fixture-1.0.dist-info/METADATA,,\n"
            "runtime_fixture-1.0.dist-info/RECORD,,\n"
        )
        self.roots = [self.package.name, metadata.name]
        self.manifest = artifacts.snapshot(self.root, self.roots)
        self.enterContext(patch.object(sys, "path", [str(self.root), *sys.path]))

    def verify(self, manifest=None):
        return artifacts.verify_installed(
            self.manifest if manifest is None else manifest,
            self.root,
            ("runtime-fixture",),
        )

    def test_snapshot_relocates_but_requires_actual_installed_file_coverage(self):
        self.assertEqual(self.verify(), self.manifest)
        other = self.root / "copied"
        other.mkdir()
        import shutil

        for name in self.roots:
            shutil.copytree(self.root / name, other / name)
        self.assertEqual(artifacts.snapshot(other, self.roots), self.manifest)
        with self.assertRaisesRegex(ValueError, "installed dependency outside"):
            artifacts.verify_installed(self.manifest, other, ("runtime-fixture",))

    def test_same_version_different_dependency_bytes_are_rejected(self):
        version = importlib.metadata.version("runtime-fixture")
        self.source.write_bytes(b"value = 2\n")
        self.assertEqual(importlib.metadata.version("runtime-fixture"), version)
        with self.assertRaisesRegex(ValueError, "bytes or inventory differ"):
            self.verify()
        self.assertNotEqual(artifacts.snapshot(self.root, self.roots), self.manifest)

    def test_unlisted_extra_and_missing_files_are_rejected(self):
        extra = self.package / "injected.py"
        extra.write_bytes(b"unlisted import code")
        with self.assertRaisesRegex(ValueError, "bytes or inventory differ"):
            self.verify()
        extra.unlink()
        self.source.unlink()
        with self.assertRaisesRegex(
            ValueError, "empty runtime root|bytes or inventory differ"
        ):
            self.verify()

    def test_subset_manifest_cannot_omit_installed_distribution_files(self):
        subset = artifacts.snapshot(self.root, [self.package.name])
        with self.assertRaisesRegex(ValueError, "absent from runtime inventory"):
            self.verify(subset)

    def test_portable_paths_and_ambiguous_wire_objects_are_rejected(self):
        for bad in (
            "../secret",
            "/absolute",
            "x//y",
            "x/../y",
            "x\\y",
            "C:/x",
            "x\x00y",
            ".",
        ):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                artifacts.snapshot(self.root, [bad])
        for change in (
            lambda m: m.update(runtime_closure_complete=True),
            lambda m: m.update(total_bytes=True),
            lambda m: m["files"].append(m["files"][0]),
            lambda m: m["roots"].append(m["roots"][0] + "/__init__.py"),
            lambda m: m["files"][0].update(size=True),
        ):
            altered = copy.deepcopy(self.manifest)
            change(altered)
            with self.assertRaises(ValueError):
                artifacts.validate(altered)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_symlink_files_and_ancestors_are_rejected(self):
        link = self.package / "alias.py"
        try:
            link.symlink_to(self.source)
        except OSError as exc:
            self.skipTest(str(exc))
        with self.assertRaisesRegex(ValueError, "symlinked"):
            artifacts.snapshot(self.root, self.roots)
        link.unlink()
        alias = self.root / "alias"
        alias.symlink_to(self.package, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlinked"):
            artifacts.snapshot(self.root, ["alias/__init__.py"])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO unavailable")
    def test_nonregular_file_is_rejected_without_blocking(self):
        os.mkfifo(self.package / "pipe")
        with self.assertRaisesRegex(ValueError, "nonregular"):
            artifacts.snapshot(self.root, self.roots)

    def test_path_replaced_after_open_is_rejected(self):
        original = artifacts.os.open

        def replace(path, flags, *, dir_fd=None):
            descriptor = original(path, flags, dir_fd=dir_fd)
            if path == self.source.name:
                replacement = self.package / "replacement"
                replacement.write_bytes(self.source.read_bytes())
                os.replace(replacement, self.source)
            return descriptor

        with patch.object(artifacts.os, "open", side_effect=replace):
            with self.assertRaisesRegex(ValueError, "runtime artifact.*changed"):
                artifacts.snapshot(self.root, self.roots)

    def test_actual_write_after_open_is_rejected(self):
        original = artifacts.os.open

        def mutate(path, flags, *, dir_fd=None):
            descriptor = original(path, flags, dir_fd=dir_fd)
            if path == self.source.name:
                self.source.write_bytes(b"value = 2\n")
            return descriptor

        with patch.object(artifacts.os, "open", side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "runtime artifact.*changed"):
                artifacts.snapshot(self.root, self.roots)

    def test_parent_swap_is_rejected_before_opening_external_contents(self):
        external = self.root / "external"
        external.mkdir()
        (external / "__init__.py").write_bytes(b"external content must not be read")
        original = artifacts.os.open
        opened = []

        def swap(path, flags, *, dir_fd=None):
            opened.append(str(path))
            if path == self.package.name:
                self.package.rename(self.root / "retained-package")
                self.package.symlink_to(external, target_is_directory=True)
            return original(path, flags, dir_fd=dir_fd)

        with patch.object(artifacts.os, "open", side_effect=swap):
            with self.assertRaises((ValueError, OSError)):
                artifacts.snapshot(self.root, self.roots)
        self.assertNotIn("__init__.py", opened)

    def test_unsupported_safe_directory_io_refuses_before_file_access(self):
        with patch.object(artifacts, "SAFE_DIRECTORY_IO", False):
            with patch.object(artifacts.os, "open") as opened:
                with self.assertRaisesRegex(ValueError, "safe descriptor-relative"):
                    artifacts.snapshot(self.root, self.roots)
                opened.assert_not_called()

    def test_manifest_pin_and_duplicate_keys_are_checked(self):
        path = self.root / "manifest.json"
        path.write_bytes(data.canonical(self.manifest))
        pin = data.digest(self.manifest)
        self.assertEqual(artifacts.load(path, pin), self.manifest)
        with self.assertRaisesRegex(ValueError, "commitment differs"):
            artifacts.load(path, "f" * 64)
        raw = data.canonical(self.manifest)
        path.write_bytes(b'{"schema":"ignored",' + raw[1:])
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            artifacts.load(path, pin)

    def test_loop_implementation_rehashes_installed_bytes_and_keeps_incomplete_status(
        self,
    ):
        path = self.root / "manifest.json"
        path.write_bytes(data.canonical(self.manifest))
        args = SimpleNamespace(
            runtime_artifacts=path,
            runtime_artifacts_root=self.root,
            expected_runtime_artifacts=data.digest(self.manifest),
        )
        with patch.object(paired_loop, "PACKAGES", ("runtime-fixture",)):
            original = paired_loop.implementation_for(args)
            self.assertEqual(original["runtime_artifacts"], self.manifest)
            self.assertEqual(
                original["dependency_identity_kind"], "verified_runtime_artifacts_v1"
            )
            self.assertFalse(original["runtime_closure_complete"])
            self.source.write_bytes(b"value = 2\n")
            with self.assertRaisesRegex(ValueError, "bytes or inventory differ"):
                paired_loop.implementation_for(args)

    def test_partial_cli_configuration_is_refused_before_dispatch(self):
        for args in (
            SimpleNamespace(runtime_artifacts="a"),
            SimpleNamespace(runtime_artifacts_root="b"),
            SimpleNamespace(expected_runtime_artifacts="c"),
        ):
            with (
                self.subTest(args=args),
                self.assertRaisesRegex(ValueError, "required together"),
            ):
                paired_loop.implementation_for(args)


if __name__ == "__main__":
    unittest.main()
