"""Verifier unit contracts in temporary Git fixtures, not product qualification."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "verify_channel_matrix_candidate.py"
spec = importlib.util.spec_from_file_location("matrix_candidate_guard_under_test", SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class CandidateGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.original_root = guard.ROOT
        self.addCleanup(setattr, guard, "ROOT", self.original_root)
        guard.ROOT = Path(self.temp.name) / "repo"
        guard.ROOT.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Verifier fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (guard.ROOT / "sample.txt").write_text("original\n")
        self.git("add", "sample.txt")
        self.git("commit", "-qm", "fixture")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=guard.ROOT, check=True,
                              text=True, capture_output=True).stdout.strip()

    def test_explicit_false_claims_are_accepted(self):
        guard.require_false_claims({name: False for name in guard.DENIED_CLAIMS})

    def test_missing_and_non_boolean_false_claims_are_rejected(self):
        for value in (None, True, 0, "false", []):
            row = {name: False for name in guard.DENIED_CLAIMS}
            row["activation"] = value
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                guard.require_false_claims(row)
        with self.assertRaises(RuntimeError):
            guard.require_false_claims({})

    def test_clean_file_receipt_matches_the_committed_blob(self):
        receipt = guard.file_receipt(guard.ROOT / "sample.txt")
        self.assertEqual(receipt["gitBlob"], self.git("rev-parse", "HEAD:sample.txt"))
        self.assertEqual(receipt["bytes"], 9)

    def test_dirty_file_cannot_receive_a_candidate_receipt(self):
        (guard.ROOT / "sample.txt").write_text("uncommitted\n")
        with self.assertRaises(RuntimeError):
            guard.file_receipt(guard.ROOT / "sample.txt")

    def test_parent_paths_are_rejected(self):
        with self.assertRaises(RuntimeError):
            guard.local_path("../outside")

    def test_symlink_escape_is_rejected(self):
        target = Path(self.temp.name) / "outside.txt"
        target.write_text("outside\n")
        (guard.ROOT / "escape").symlink_to(target)
        with self.assertRaises(RuntimeError):
            guard.local_path("escape")

    def test_observation_requires_the_actual_commit_tree(self):
        head = self.git("rev-parse", "HEAD")
        tree = self.git("rev-parse", "HEAD^{tree}")
        self.assertEqual(guard.checked_observation({"commit": head, "tree": tree}, head, "fixture"), (head, tree))
        with self.assertRaises(RuntimeError):
            guard.checked_observation({"commit": head, "tree": "0" * 40}, head, "fixture")

    def test_operation_inventory_requires_every_owner_operation_once(self):
        names = ("admit_event", "prepare_send", "observe_send")
        rows = [{"operation": name, "designOperation": name} for name in names]
        guard.require_operation_inventory(rows)
        for invalid in (None, {}, [], rows[:2], rows + [rows[0]],
                        [rows[0], rows[0], rows[2]], [None],
                        [{"operation": "admit_event", "designOperation": "observe_send"}]):
            with self.subTest(invalid=invalid), self.assertRaises(RuntimeError):
                guard.require_operation_inventory(invalid)

    def test_duplicate_map_fields_are_rejected_at_every_depth(self):
        prefix = '{"schema":"hepta.module-implementation-map.v3","schemaVersion":3,'
        for tail in ('"activation":true,"activation":false}',
                     '"claimBoundary":{"activation":true,"activation":false}}'):
            with self.subTest(tail=tail), self.assertRaises(RuntimeError):
                guard.load_implementation_map(prefix + tail)

    def test_map_schema_identity_requires_exact_types(self):
        row = {"schema": "hepta.module-implementation-map.v3", "schemaVersion": 3}
        self.assertEqual(guard.load_implementation_map(json.dumps(row)), row)
        for invalid in (None, [], {**row, "schemaVersion": True},
                        {**row, "schemaVersion": 3.0}, {**row, "schemaVersion": "3"},
                        {**row, "schema": "hepta.module-implementation-map.v2"}):
            with self.subTest(invalid=invalid), self.assertRaises(RuntimeError):
                guard.load_implementation_map(json.dumps(invalid))

    def test_registered_source_markers_match_the_actual_files(self):
        # Catch source-navigation drift before it blocks all native tests.
        root = Path(__file__).resolve().parents[2]
        for path, markers in guard.SOURCE_MARKERS.items():
            text = (root / path).read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertEqual([marker for marker in markers if marker not in text], [])

    def test_expected_sha_mismatch_fails_before_any_map_claim(self):
        with self.assertRaises(RuntimeError):
            guard.verify("0" * 40)


if __name__ == "__main__":
    unittest.main()
