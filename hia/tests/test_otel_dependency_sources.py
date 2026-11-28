"""Actual current OTEL source custody; original dependency test bodies stay frozen."""
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
from file_update_oracle import otel_source_history as otel


class OtelDependencySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.history, _ = otel._history()
        cls.current = {p: (REPO / p).read_bytes() for p in admission.ROOT_FILES}
        cls.original = {p: subprocess.check_output([
            "git", "-C", str(ORIGINAL), "show",
            "a2014bc6bfa1c1c9957edb3f14f8ae7d9ddcc095:" + p])
            for p in admission.ROOT_FILES}

        cls.fleet_fixture = None
        if admission._pair_identity(cls.current) != cls.history["current_files"]:
            from file_update_oracle.windows_fleet_source_history import restore_predecessor
            cls.fleet_fixture = restore_predecessor(REPO, cls.current, cls.history["current_files"])
            cls.current = cls.fleet_fixture["restored"]

    @classmethod
    def tearDownClass(cls):
        from file_update_oracle.windows_fleet_source_history import verify_predecessor
        verify_predecessor(cls.fleet_fixture)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="otel-source-controls-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in (epoch.VENDOR, otel.CRATE):
            shutil.copytree(REPO / name, self.root / name)
        for path, data in self.current.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (self.root / "MODULE.bazel.lock").write_bytes((REPO / "MODULE.bazel.lock").read_bytes())

    def admit(self):
        return admission.admit_workspace_sources(self.root, self.original)

    def test_complete_current_tree_recovers_all_original_pairs(self):
        proof = self.admit()
        self.assertEqual(proof["restored"], self.original)
        self.assertEqual([r["complete_package_inverses"] for r in proof["report"]["inverse"]],
                         [1, 1, 4, 24])
        report = proof["report"]["oauth2_source_history"]["otel_source_history"]
        self.assertEqual(report["source_variant"], self.history["source_variant"])
        self.assertEqual(report["unchanged_lock_packages"], 1533)
        self.assertEqual(set(report["crate"]["files"]), set(self.history["crate"]["current_files"]))
        self.assertEqual({p: row["sha256"] for p, row in report["actual_files"].items()},
                         {p: hashlib.sha256(data).hexdigest() for p, data in self.current.items()})
        self.assertFalse(report["dependency_graph_equivalence_claimed"])
        admission.verify_workspace_sources(proof)

    def test_projected_input_cannot_replace_the_physical_current_pair(self):
        proof = otel.restore_predecessor(self.root, self.current, self.history["predecessor_files"])
        with self.assertRaisesRegex(RuntimeError, "differs from physical"):
            epoch.restore_predecessor(self.root, proof["restored"], epoch._history()[0]["predecessor_files"])

    def test_unreviewed_dependency_pair_bytes_are_rejected(self):
        for name in admission.ROOT_FILES:
            with self.subTest(path=name):
                for path, data in self.current.items():
                    (self.root / path).write_bytes(data)
                (self.root / name).write_bytes(self.current[name] + b"\n")
                with self.assertRaisesRegex(RuntimeError, "unreviewed or mixed"):
                    self.admit()

    def test_every_changed_source_and_retained_library_is_pinned(self):
        for name in (*self.history["crate"]["inverse"], "src/lib.rs"):
            with self.subTest(path=name):
                path = self.root / otel.CRATE / name
                before = path.read_bytes()
                path.write_bytes(before + b"\n")
                with self.assertRaisesRegex(RuntimeError, "physical OTEL source changed"):
                    self.admit()
                path.write_bytes(before)

    def test_missing_source_is_rejected(self):
        (self.root / otel.CRATE / "src/events/shared_tests.rs").unlink()
        with self.assertRaisesRegex(RuntimeError, "complete OTEL source inventory"):
            self.admit()

    def test_extra_source_and_empty_directory_are_rejected(self):
        for name, directory in (("unreviewed.rs", False), ("unreviewed", True)):
            with self.subTest(path=name):
                path = self.root / otel.CRATE / name
                path.mkdir() if directory else path.write_text("// not admitted\n")
                with self.assertRaisesRegex(RuntimeError, "complete OTEL source inventory"):
                    self.admit()
                path.rmdir() if directory else path.unlink()

    def test_symbolic_source_is_rejected(self):
        path = self.root / otel.CRATE / "src/events/shared.rs"
        target = self.root / "source-target"
        path.rename(target)
        path.symlink_to(target)
        with self.assertRaisesRegex(RuntimeError, "physical regular"):
            self.admit()

    def test_changed_executable_mode_is_rejected(self):
        path = self.root / otel.CRATE / "src/events/shared.rs"
        path.chmod(path.stat().st_mode | 0o100)
        with self.assertRaisesRegex(RuntimeError, "physical OTEL source changed"):
            self.admit()

    def test_terminal_source_mutation_is_rejected(self):
        proof = self.admit()
        path = self.root / otel.CRATE / "src/events/shared.rs"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(RuntimeError, "physical OTEL source changed"):
            admission.verify_workspace_sources(proof)

    def test_identical_source_bytes_with_replaced_inode_are_rejected(self):
        proof = self.admit()
        path = self.root / otel.CRATE / "src/events/shared.rs"
        target = self.root / "replacement"
        target.write_bytes(path.read_bytes())
        os.replace(target, path)
        with self.assertRaisesRegex(RuntimeError, "captured OTEL crate identity"):
            admission.verify_workspace_sources(proof)

    def test_terminal_extra_source_is_rejected(self):
        proof = self.admit()
        (self.root / otel.CRATE / "after-capture.rs").write_text("// inventory changed\n")
        with self.assertRaisesRegex(RuntimeError, "complete OTEL source inventory"):
            admission.verify_workspace_sources(proof)

    def test_rewritten_complete_history_is_rejected(self):
        path = self.root / "history.json"
        path.write_bytes(otel.HISTORY.read_bytes() + b"\n")
        with self.assertRaisesRegex(RuntimeError, "complete OTEL dependency history changed"):
            otel._history(path)

    def test_wrong_predecessor_cannot_be_selected(self):
        wrong = dict(self.history["predecessor_files"])
        wrong[admission.ROOT_FILES[1]] = {"bytes": 1, "sha256": "0" * 64}
        with self.assertRaisesRegex(RuntimeError, "differs from the complete OAuth2 pair"):
            otel.restore_predecessor(self.root, self.current, wrong)

    def test_current_bazel_dependency_lock_is_pinned(self):
        path = self.root / "MODULE.bazel.lock"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(RuntimeError, "current Bazel dependency lock changed"):
            self.admit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--original-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    REPO, ORIGINAL = args.repo.resolve(strict=True), args.original_root.resolve(strict=True)
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(OtelDependencySourceTests))
    physical_admission = admission.admit_workspace_sources(REPO, OtelDependencySourceTests.original)
    admission.verify_workspace_sources(physical_admission)
    report = {"schema": "codex.hia.otel-dependency-source-controls.v1",
              "passed": result.wasSuccessful(), "tests": result.testsRun,
              "failures": [(str(case), trace) for case, trace in result.failures],
              "errors": [(str(case), trace) for case, trace in result.errors],
              "physical_source_admission": physical_admission["report"],
              "physical_source_sha256": {p: hashlib.sha256((REPO / p).read_bytes()).hexdigest()
                                         for p in admission.ROOT_FILES},
              "history_sha256": hashlib.sha256(otel.HISTORY.read_bytes()).hexdigest(),
              "helper_sha256": hashlib.sha256(Path(otel.__file__).read_bytes()).hexdigest(),
              "current_fixture_admission": (None if OtelDependencySourceTests.fleet_fixture is None
                  else OtelDependencySourceTests.fleet_fixture["report"]),
              "controls_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with args.report.open("x") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)
