"""Current OAuth2 dependency-source controls, separate from the frozen 22 controls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from file_update_oracle import dependencies as admission
from file_update_oracle import oauth2_source_history as epoch


class OAuth2DependencySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.history, _ = epoch._history()
        cls.current = {p: (REPO / p).read_bytes() for p in admission.ROOT_FILES}
        cls.original = {p: subprocess.check_output([
            "git", "-C", str(ORIGINAL), "show",
            "a2014bc6bfa1c1c9957edb3f14f8ae7d9ddcc095:" + p])
            for p in admission.ROOT_FILES}
        cls.predecessor = {p: subprocess.check_output([
            "git", "-C", str(REPO), "show",
            cls.history["predecessor_revision"] + ":" + p])
            for p in admission.ROOT_FILES}

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="oauth2-source-controls-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.vendor = self.root / epoch.VENDOR
        shutil.copytree(REPO / epoch.VENDOR, self.vendor)
        for path, data in self.current.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (self.root / "MODULE.bazel.lock").write_bytes((REPO / "MODULE.bazel.lock").read_bytes())

    def admit(self):
        return admission.admit_workspace_sources(self.root, self.original)

    def test_current_full_pair_and_vendor_recover_actual_originals(self):
        proof = self.admit()
        self.assertEqual(proof["restored"], self.original)
        self.assertEqual([row["complete_package_inverses"] for row in proof["report"]["inverse"]],
                         [1, 4, 24])
        self.assertFalse(proof["report"]["dependency_graph_equivalence_claimed"])
        report = proof["report"]["oauth2_source_history"]
        self.assertFalse(report["dependency_graph_equivalence_claimed"])
        self.assertEqual(len(report["vendor"]["files"]), 39)
        self.assertEqual(report["source_variant"], "oauth2-5.0.0+hepta.epoch.1")
        self.assertEqual({p: row["sha256"] for p, row in report["actual_files"].items()},
                         {p: hashlib.sha256(data).hexdigest() for p, data in self.current.items()})
        admission.verify_workspace_sources(proof)

    def test_mixed_epoch_and_predecessor_pairs_are_rejected(self):
        for path in admission.ROOT_FILES:
            with self.subTest(path=path):
                for name, data in self.current.items():
                    (self.root / name).write_bytes(data)
                (self.root / path).write_bytes(self.predecessor[path])
                with self.assertRaisesRegex(RuntimeError, "unreviewed or mixed"):
                    self.admit()

    def test_unreviewed_epoch_pair_bytes_are_rejected(self):
        for path in admission.ROOT_FILES:
            with self.subTest(path=path):
                for name, data in self.current.items():
                    (self.root / name).write_bytes(data)
                (self.root / path).write_bytes(self.current[path] + b"\n")
                with self.assertRaisesRegex(RuntimeError, "unreviewed or mixed"):
                    self.admit()

    def test_missing_vendor_file_is_rejected(self):
        (self.vendor / "LICENSE-MIT").unlink()
        with self.assertRaisesRegex(RuntimeError, "complete OAuth2 vendor inventory"):
            self.admit()

    def test_unchanged_upstream_source_is_not_exempt(self):
        path = self.vendor / "src/types.rs"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(RuntimeError, "physical OAuth2 source changed"):
            self.admit()

    def test_new_timestamp_source_is_pinned(self):
        path = self.vendor / "src/time_compat.rs"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(RuntimeError, "physical OAuth2 source changed"):
            self.admit()

    def test_extra_vendor_file_is_rejected(self):
        (self.vendor / "unreviewed.rs").write_text("// unexpected source\n")
        with self.assertRaisesRegex(RuntimeError, "complete OAuth2 vendor inventory"):
            self.admit()

    def test_extra_empty_vendor_directory_is_rejected(self):
        (self.vendor / "unreviewed").mkdir()
        with self.assertRaisesRegex(RuntimeError, "complete OAuth2 vendor inventory"):
            self.admit()

    def test_symbolic_vendor_source_is_rejected(self):
        path = self.vendor / "src/time_compat.rs"
        target = self.root / "source-target"
        path.rename(target)
        path.symlink_to(target)
        with self.assertRaisesRegex(RuntimeError, "physical regular"):
            self.admit()

    def test_identical_vendor_bytes_with_replaced_inode_are_rejected(self):
        proof = self.admit()
        path = self.vendor / "src/time_compat.rs"
        replacement = self.root / "replacement"
        replacement.write_bytes(path.read_bytes())
        os.replace(replacement, path)
        with self.assertRaisesRegex(RuntimeError, "captured OAuth2 vendor identity"):
            admission.verify_workspace_sources(proof)

    def test_terminal_vendor_mutation_is_rejected(self):
        proof = self.admit()
        path = self.vendor / "README.md"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(RuntimeError, "physical OAuth2 source changed"):
            admission.verify_workspace_sources(proof)

    def test_terminal_inventory_addition_is_rejected(self):
        proof = self.admit()
        (self.vendor / "after-capture.rs").write_text("// changed inventory\n")
        with self.assertRaisesRegex(RuntimeError, "complete OAuth2 vendor inventory"):
            admission.verify_workspace_sources(proof)

    def test_current_bazel_dependency_lock_is_pinned(self):
        path = self.root / "MODULE.bazel.lock"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(RuntimeError, "current Bazel dependency lock changed"):
            self.admit()

    def test_terminal_bazel_lock_replacement_is_rejected(self):
        proof = self.admit()
        path = self.root / "MODULE.bazel.lock"
        replacement = self.root / "replacement"
        replacement.write_bytes(path.read_bytes())
        os.replace(replacement, path)
        with self.assertRaisesRegex(RuntimeError, "captured OAuth2 source identity"):
            admission.verify_workspace_sources(proof)

    def test_rewritten_complete_history_is_rejected(self):
        path = self.root / "history.json"
        path.write_bytes(epoch.HISTORY.read_bytes() + b"\n")
        with self.assertRaisesRegex(RuntimeError, "complete OAuth2 dependency history changed"):
            epoch._history(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--original-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    REPO, ORIGINAL = args.repo.resolve(strict=True), args.original_root.resolve(strict=True)
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(OAuth2DependencySourceTests))
    physical_admission = admission.admit_workspace_sources(REPO, OAuth2DependencySourceTests.original)
    admission.verify_workspace_sources(physical_admission)
    report = {"schema": "codex.hia.oauth2-dependency-source-controls.v1",
              "passed": result.wasSuccessful(), "tests": result.testsRun,
              "failures": [(str(case), trace) for case, trace in result.failures],
              "errors": [(str(case), trace) for case, trace in result.errors],
              "physical_source_admission": physical_admission["report"],
              "physical_source_sha256": {p: hashlib.sha256((REPO / p).read_bytes()).hexdigest()
                                         for p in admission.ROOT_FILES},
              "history_sha256": hashlib.sha256(epoch.HISTORY.read_bytes()).hexdigest(),
              "helper_sha256": hashlib.sha256(Path(epoch.__file__).read_bytes()).hexdigest(),
              "controls_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with args.report.open("x") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)
