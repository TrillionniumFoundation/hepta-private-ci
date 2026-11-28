"""Verify complete Windows fleet source custody and the unchanged predecessor controls."""
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
from file_update_oracle import windows_fleet_source_history as fleet


class WindowsFleetDependencySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.history, _ = fleet._history()
        cls.current = {p: (REPO / p).read_bytes() for p in admission.ROOT_FILES}
        cls.original = {p: subprocess.check_output([
            "git", "-C", str(ORIGINAL), "show",
            "a2014bc6bfa1c1c9957edb3f14f8ae7d9ddcc095:" + p])
            for p in admission.ROOT_FILES}

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="windows-fleet-source-controls-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in (epoch.VENDOR, otel.CRATE, *fleet.CRATES):
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
                         [1, 1, 1, 4, 24])
        report = proof["report"]["oauth2_source_history"]["otel_source_history"]["windows_fleet_source_history"]
        self.assertEqual(report["source_variant"], self.history["source_variant"])
        self.assertEqual(report["unchanged_lock_packages"], 1533)
        self.assertEqual({name: len(row["files"]) for name, row in report["crates"].items()},
                         {fleet.CRATES[0]: 21, fleet.CRATES[1]: 14})
        self.assertEqual({p: row["sha256"] for p, row in report["actual_files"].items()},
                         {p: hashlib.sha256(data).hexdigest() for p, data in self.current.items()})
        self.assertFalse(report["dependency_graph_equivalence_claimed"])
        self.assertFalse(report["windows_execution_qualified"])
        admission.verify_workspace_sources(proof)

    def test_complete_predecessor_sources_match_the_independent_immutable_commit(self):
        revision = self.history["predecessor_revision"]
        original_pair = {p: admission._identity(subprocess.check_output([
            "git", "-C", str(PREDECESSOR), "show", revision + ":" + p])) for p in admission.ROOT_FILES}
        self.assertEqual(original_pair, self.history["predecessor_files"])
        for name in fleet.CRATES:
            expected = self.history["crates"][name]
            listing = subprocess.check_output([
                "git", "-C", str(PREDECESSOR), "ls-tree", "-r", "-z", revision, "--", name])
            actual = {}
            for record in listing.split(b"\0"):
                if not record:
                    continue
                header, raw_path = record.split(b"\t", 1)
                mode, kind, blob = header.decode().split()
                self.assertEqual(kind, "blob")
                path = raw_path.decode()
                relative = Path(path).relative_to(name).as_posix()
                data = subprocess.check_output(["git", "-C", str(PREDECESSOR), "show", revision + ":" + path])
                self.assertEqual(hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(), blob)
                self.assertEqual(mode, expected["modes"][relative])
                actual[relative] = admission._identity(data)
            self.assertEqual(actual, expected["original_files"])

    def test_projected_input_cannot_replace_the_physical_current_pair(self):
        proof = fleet.restore_predecessor(self.root, self.current, self.history["predecessor_files"])
        with self.assertRaisesRegex(RuntimeError, "differs from physical"):
            otel.restore_predecessor(self.root, proof["restored"], otel._history()[0]["predecessor_files"])

    def test_unreviewed_dependency_pair_bytes_are_rejected(self):
        for name in admission.ROOT_FILES:
            with self.subTest(path=name):
                for path, data in self.current.items():
                    (self.root / path).write_bytes(data)
                (self.root / name).write_bytes(self.current[name] + b"\n")
                with self.assertRaisesRegex(RuntimeError, "unreviewed or mixed"):
                    self.admit()

    def test_every_source_file_in_both_complete_crates_is_pinned(self):
        for name in fleet.CRATES:
            for relative in self.history["crates"][name]["current_files"]:
                with self.subTest(crate=name, path=relative):
                    path = self.root / name / relative
                    before = path.read_bytes()
                    path.write_bytes(before + b"\n")
                    with self.assertRaisesRegex(RuntimeError, "physical Windows fleet source changed"):
                        self.admit()
                    path.write_bytes(before)

    def test_missing_source_is_rejected(self):
        for name in fleet.CRATES:
            path = self.root / name / "src/lib.rs"
            before = path.read_bytes()
            path.unlink()
            with self.assertRaisesRegex(RuntimeError, "complete Windows fleet source inventory"):
                self.admit()
            path.write_bytes(before)

    def test_extra_source_and_empty_directory_are_rejected(self):
        for name in fleet.CRATES:
            for relative, directory in (("unreviewed.rs", False), ("unreviewed", True)):
                with self.subTest(crate=name, path=relative):
                    path = self.root / name / relative
                    path.mkdir() if directory else path.write_text("// not admitted\n")
                    with self.assertRaisesRegex(RuntimeError, "complete Windows fleet source inventory"):
                        self.admit()
                    path.rmdir() if directory else path.unlink()

    def test_symbolic_source_is_rejected(self):
        for name in fleet.CRATES:
            path = self.root / name / "src/lib.rs"
            target = self.root / "source-target"
            path.rename(target)
            path.symlink_to(target)
            with self.assertRaisesRegex(RuntimeError, "physical regular"):
                self.admit()
            path.unlink()
            target.rename(path)

    def test_symbolic_crate_directory_is_rejected(self):
        for name in fleet.CRATES:
            path = self.root / name
            target = self.root / "directory-target"
            path.rename(target)
            path.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "source directory must be physical"):
                self.admit()
            path.unlink()
            target.rename(path)

    def test_changed_executable_mode_is_rejected(self):
        for name in fleet.CRATES:
            path = self.root / name / "src/lib.rs"
            before = path.stat().st_mode
            path.chmod(before | 0o100)
            with self.assertRaisesRegex(RuntimeError, "physical Windows fleet source changed"):
                self.admit()
            path.chmod(before)

    def test_terminal_source_mutation_is_rejected(self):
        for name in fleet.CRATES:
            proof = self.admit()
            path = self.root / name / "src/lib.rs"
            before = path.read_bytes()
            path.write_bytes(before + b"\n")
            with self.assertRaisesRegex(RuntimeError, "physical Windows fleet source changed"):
                admission.verify_workspace_sources(proof)
            path.write_bytes(before)

    def test_identical_source_bytes_with_replaced_inode_are_rejected(self):
        for name in fleet.CRATES:
            proof = self.admit()
            path = self.root / name / "src/lib.rs"
            target = self.root / "replacement"
            target.write_bytes(path.read_bytes())
            os.replace(target, path)
            with self.assertRaisesRegex(RuntimeError, "captured Windows fleet crate identity"):
                admission.verify_workspace_sources(proof)

    def test_terminal_extra_source_is_rejected(self):
        proof = self.admit()
        (self.root / fleet.CRATES[1] / "after-capture.rs").write_text("// inventory changed\n")
        with self.assertRaisesRegex(RuntimeError, "complete Windows fleet source inventory"):
            admission.verify_workspace_sources(proof)

    def test_rewritten_complete_history_is_rejected(self):
        path = self.root / "history.json"
        path.write_bytes(fleet.HISTORY.read_bytes() + b"\n")
        with self.assertRaisesRegex(RuntimeError, "complete Windows fleet dependency history changed"):
            fleet._history(path)

    def test_wrong_predecessor_cannot_be_selected(self):
        wrong = dict(self.history["predecessor_files"])
        wrong[admission.ROOT_FILES[1]] = {"bytes": 1, "sha256": "0" * 64}
        with self.assertRaisesRegex(RuntimeError, "differs from the complete OTEL pair"):
            fleet.restore_predecessor(self.root, self.current, wrong)

    def test_current_bazel_dependency_lock_is_pinned(self):
        path = self.root / "MODULE.bazel.lock"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(RuntimeError, "current Bazel dependency lock changed"):
            self.admit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--original-root", type=Path, required=True)
    parser.add_argument("--predecessor-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    REPO, ORIGINAL = args.repo.resolve(strict=True), args.original_root.resolve(strict=True)
    PREDECESSOR = args.predecessor_root.resolve(strict=True)
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(WindowsFleetDependencySourceTests))
    physical = admission.admit_workspace_sources(REPO, WindowsFleetDependencySourceTests.original)
    admission.verify_workspace_sources(physical)
    report = {"schema": "codex.hia.windows-fleet-dependency-source-controls.v1",
              "passed": result.wasSuccessful(), "tests": result.testsRun,
              "failures": [(str(case), trace) for case, trace in result.failures],
              "errors": [(str(case), trace) for case, trace in result.errors],
              "physical_source_admission": physical["report"],
              "history_sha256": hashlib.sha256(fleet.HISTORY.read_bytes()).hexdigest(),
              "helper_sha256": hashlib.sha256(Path(fleet.__file__).read_bytes()).hexdigest(),
              "controls_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "dependency_graph_equivalence_claimed": False, "windows_execution_qualified": False}
    with args.report.open("x") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)
