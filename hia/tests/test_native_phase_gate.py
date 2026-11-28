"""Independent conservation, physical source and skipped-gate negative controls."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "native_phase_gate", Path(__file__).resolve().parents[1] / "ci/native_phase_gate.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class NativePhaseConservationTests(unittest.TestCase):
    def setUp(self):
        self.original = gate.baseline()
        self.current = gate.render(self.original)
        self.rows = gate.validate_workflow(self.current)

    def test_complete_original_population_and_unrelated_jobs_are_retained(self):
        self.assertEqual(len(self.rows), 114)
        before, _, after = gate.split_workflow(self.original)
        current_before, current, current_after = gate.split_workflow(self.current)
        self.assertEqual(before, current_before)
        self.assertEqual(after, current_after)
        self.assertEqual(current.count("    timeout-minutes: 60\n"), 1)
        owned = [set(row["original_number"] for row in self.rows if row["phase"] == phase)
                 for phase in gate.PHASES]
        self.assertFalse(any(a.intersection(b) for i, a in enumerate(owned) for b in owned[i + 1:]))
        self.assertEqual(set.union(*owned, set(gate.COMMON)), set(range(2, 116)))

    def test_tail_gate_omission_and_changed_native_profile_are_refused(self):
        _, original, _ = gate.split_workflow(self.original)
        _, blocks = gate.step_blocks(original)
        tail = gate.transformed_step(114, blocks[112])
        self.assertIn(tail, self.current)
        with self.assertRaises(ValueError):
            gate.validate_workflow(self.current.replace(tail, "", 1))
        self.assertIn("--build-profile full-native38", self.current)
        with self.assertRaises(ValueError):
            gate.validate_workflow(self.current.replace("--build-profile full-native38",
                                                        "--build-profile native37", 1))

    def test_budget_phase_omission_and_artifact_collision_are_refused(self):
        for old, new in (
            ("    timeout-minutes: 60\n", "    timeout-minutes: 61\n"),
            ("phase: [abi, owners, installed]", "phase: [abi, owners]"),
            ("matrix.phase == 'abi'", "matrix.phase == 'owners'"),
            ("codex-hia-current38-results-" + gate.expression("matrix.phase"),
             "codex-hia-current38-results"),
        ):
            with self.subTest(old=old):
                self.assertIn(old, self.current)
                with self.assertRaises(ValueError):
                    gate.validate_workflow(self.current.replace(old, new, 1))

    def test_capture_removal_and_other_job_changes_are_refused(self):
        with self.assertRaises(ValueError):
            gate.validate_workflow(self.current.replace(gate.source_before_step(), "", 1))
        before, current, after = gate.split_workflow(self.current)
        self.assertIn("timeout-minutes:", after)
        with self.assertRaises(ValueError):
            gate.validate_workflow(before + current + after.replace("timeout-minutes:", "timeout-minutes: 120 #", 1))

    def test_each_assigned_original_gate_must_have_actual_success(self):
        for phase in gate.PHASES:
            observations = {row["id"]: {"outcome": "success", "conclusion": "success"}
                            for row in self.rows}
            observations["native_source_before"] = {"outcome": "success", "conclusion": "success"}
            expected = gate.verify_outcomes(observations, phase, self.rows)
            chosen = next(row["id"] for row in self.rows if row["phase"] == phase)
            self.assertIn(chosen, expected)
            for outcome in ("skipped", "failure", "cancelled", None, True):
                bad = deepcopy(observations)
                bad[chosen]["outcome"] = outcome
                with self.subTest(phase=phase, outcome=outcome), self.assertRaises(ValueError):
                    gate.verify_outcomes(bad, phase, self.rows)
            del observations[chosen]
            with self.assertRaises(ValueError):
                gate.verify_outcomes(observations, phase, self.rows)

    def test_missing_source_capture_and_changed_conclusion_refuse(self):
        observed = {row["id"]: {"outcome": "success", "conclusion": "success"} for row in self.rows}
        with self.assertRaises(ValueError):
            gate.verify_outcomes(observed, "owners", self.rows)
        observed["native_source_before"] = {"outcome": "success", "conclusion": "failure"}
        with self.assertRaises(ValueError):
            gate.verify_outcomes(observed, "owners", self.rows)


class NativePhasePhysicalSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="native-phase-capture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Source Fixture")
        self.git("config", "user.email", "source-fixture@example.invalid")
        (self.root / "data").mkdir()
        (self.root / "data/file").write_bytes(b"original bytes\n")
        (self.root / "empty").write_bytes(b"")
        (self.root / "run").write_bytes(b"#!/bin/sh\nexit 0\n")
        (self.root / "run").chmod(0o755)
        os.symlink("data/file", self.root / "link")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "exact original fixture")
        self.head = self.git("rev-parse", "HEAD").decode().strip()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args])

    def test_real_git_source_capture_and_terminal_readback(self):
        before = gate.capture_repo(self.root, self.head)
        after = gate.capture_repo(self.root, self.head)
        gate.compare_source(before, after)
        self.assertEqual(len(before["files"]), 4)
        self.assertEqual(before["files"]["link"]["mode"], "120000")
        self.assertEqual(before["files"]["run"]["mode"], "100755")

    def test_changed_physical_bytes_and_executable_mode_refuse(self):
        path = self.root / "data/file"
        raw = path.read_bytes()
        path.write_bytes(b"changed bytes\n")
        with self.assertRaises(ValueError):
            gate.capture_repo(self.root, self.head)
        path.write_bytes(raw)
        (self.root / "run").chmod(0o644)
        with self.assertRaises(ValueError):
            gate.capture_repo(self.root, self.head)

    def test_same_bytes_in_an_external_symlinked_parent_refuse(self):
        original = self.root / "data"
        external = Path(self.temp.name) / "external"
        original.rename(external)
        original.symlink_to(external, target_is_directory=True)
        with self.assertRaises(ValueError):
            gate.capture_repo(self.root, self.head)

    def test_unchanged_worktree_with_a_different_commit_is_refused(self):
        self.git("commit", "-q", "--allow-empty", "-m", "different source identity")
        with self.assertRaises(ValueError):
            gate.capture_repo(self.root, self.head)

    def test_late_change_after_a_file_capture_is_refused(self):
        original = gate.file_observation
        touched = False
        def mutate(path, mode, blob):
            nonlocal touched
            result = original(path, mode, blob)
            if path.name == "file" and not touched:
                touched = True
                path.write_bytes(b"late physical change\n")
            return result
        with patch.object(gate, "file_observation", side_effect=mutate), self.assertRaises(ValueError):
            gate.capture_repo(self.root, self.head)
        self.assertTrue(touched)

    def test_boolean_size_rebinding_and_duplicate_evidence_are_refused(self):
        before = gate.capture_repo(self.root, self.head)
        changed = deepcopy(before)
        changed["files"]["empty"]["bytes"] = False
        with self.assertRaises(ValueError):
            gate.compare_source(changed, before)
        with self.assertRaises(ValueError):
            gate.decode('{"passed":true,"passed":false}')


if __name__ == "__main__":
    unittest.main(verbosity=2)
