#!/usr/bin/env python3
"""Host artifact-binding regressions; no kernel build or guest is simulated."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("native_owner_common", Path(__file__).with_name("run-native-owner-qualification.py"))
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)


class BuildReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hepta-build-binding-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / "build"
        self.directory.mkdir()
        self.kernel = self.root / "target-a" / "kernel.elf"
        self.kernel.parent.mkdir()
        self.kernel.write_bytes(b"explicit artifact-binding fixture, not a kernel")
        self.inputs = {"desktop_head": "source-a", "desktop_tree": "tree-a",
                       "owner_sha256": common.digest(b"owner-a"),
                       "target_directory": str(self.kernel.parent), "kernel_path": str(self.kernel)}
        self.original = common.retained_build_kernel(self.directory, self.kernel, self.inputs, fresh_build=True)

    def test_exact_fresh_output_can_be_reused(self):
        self.assertEqual(common.retained_build_kernel(self.directory, self.kernel, self.inputs, fresh_build=False), self.original)

    def test_different_target_with_same_bytes_is_rejected(self):
        other = self.root / "target-b" / "kernel.elf"
        other.parent.mkdir()
        other.write_bytes(self.original)
        binding = dict(self.inputs, target_directory=str(other.parent), kernel_path=str(other))
        with self.assertRaisesRegex(ValueError, "binding differs"):
            common.retained_build_kernel(self.directory, other, binding, fresh_build=False)

    def test_same_target_overwritten_after_build_is_rejected(self):
        self.kernel.write_bytes(self.original[:-1] + b"!")
        with self.assertRaisesRegex(ValueError, "SHA256"):
            common.retained_build_kernel(self.directory, self.kernel, self.inputs, fresh_build=False)

    def test_changed_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "binding differs"):
            common.retained_build_kernel(self.directory, self.kernel, dict(self.inputs, desktop_head="source-b"), fresh_build=False)

    def test_changed_owner_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "binding differs"):
            common.retained_build_kernel(self.directory, self.kernel, dict(self.inputs, owner_sha256=common.digest(b"owner-b")), fresh_build=False)

    def test_missing_receipt_is_never_created_by_reuse(self):
        other = self.root / "unbound-build"
        other.mkdir()
        with self.assertRaises(FileNotFoundError):
            common.retained_build_kernel(other, self.kernel, self.inputs, fresh_build=False)
        self.assertEqual(list(other.iterdir()), [])

    def test_fresh_output_cannot_replace_an_existing_receipt(self):
        with self.assertRaises(FileExistsError):
            common.retained_build_kernel(self.directory, self.kernel, self.inputs, fresh_build=True)

    def test_receipt_symlink_is_rejected(self):
        receipt = self.directory / "native-kernel-build-receipt.json"
        original = self.directory / "retained.json"
        receipt.rename(original)
        receipt.symlink_to(original)
        with self.assertRaisesRegex(ValueError, "invalid retained"):
            common.retained_build_kernel(self.directory, self.kernel, self.inputs, fresh_build=False)


if __name__ == "__main__":
    unittest.main()
