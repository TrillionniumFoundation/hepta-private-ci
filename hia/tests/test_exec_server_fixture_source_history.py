"""Reject drift while preserving every original platform and Wine source pin."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from file_update_oracle import exec_server_fixture_source_history as admission


class FixtureSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.listing = subprocess.check_output(
            ["git", "-C", str(REPO), "ls-tree", "-r", "-z", admission.CURRENT_TREE])
        cls.sources = {name: (REPO / admission.DEPENDENCY / name).read_bytes()
                       for name in set(admission.LEAVES) | set(admission.previous.LEAVES)}

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="exec-server-fixture-source-controls-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.restore_sources()

    def restore_sources(self):
        for name, data in self.sources.items():
            path = self.root / admission.DEPENDENCY / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def project(self, listing=None, binding=None):
        relative, expected, actual = binding or (
            admission.DEPENDENCY, admission.ORIGINAL_TREE, admission.CURRENT_TREE)
        return admission.reverse_fixture_tree(
            self.root, relative, expected, actual, self.listing if listing is None else listing)

    def test_complete_fixture_inverse_keeps_both_unchanged_predecessor_legs(self):
        proof = self.project()
        self.assertEqual(proof["actual_leaf_count"], 144)
        self.assertEqual(proof["changed_source_leaves"], 2)
        self.assertEqual(set(proof["actual_changed_files"]), set(admission.LEAVES))
        self.assertEqual(proof["intermediate_tree"], "4ded82432f79ba4191223cb2f88448dd560a31d0")
        platform = proof["previous_projection"]
        self.assertEqual(platform["actual_tree"], admission.PREVIOUS_TREE)
        self.assertEqual(platform["intermediate_tree"], "040d2b09f7f1ed6dcf930c0c6032868e32b52764")
        self.assertEqual(platform["previous_projection"]["projected_original_tree"],
                         "6e7fb23cad63c4d9cd0c7ae24faae16c16def394")
        self.assertFalse(proof["platform_behavior_equivalence_claimed"])

    def test_record_order_does_not_change_the_canonical_tree(self):
        reverse = b"\0".join(reversed(self.listing[:-1].split(b"\0"))) + b"\0"
        self.assertEqual(self.project(reverse), self.project())

    def test_unknown_or_mixed_dependency_tree_bindings_are_rejected(self):
        for binding in [("codex-rs/utils/path-uri", admission.ORIGINAL_TREE, admission.CURRENT_TREE),
                        (admission.DEPENDENCY, "0" * 40, admission.CURRENT_TREE),
                        (admission.DEPENDENCY, admission.ORIGINAL_TREE, admission.PREVIOUS_TREE),
                        (admission.DEPENDENCY, admission.ORIGINAL_TREE, "0" * 40)]:
            with self.subTest(binding=binding), self.assertRaisesRegex(RuntimeError, "unreviewed"):
                self.project(binding=binding)

    def test_missing_extra_duplicate_and_incomplete_leaves_are_rejected(self):
        rows = self.listing[:-1].split(b"\0")
        extra = b"100644 blob " + b"0" * 40 + b"\textra.txt"
        for listing in [b"\0".join(rows[:-1]) + b"\0", self.listing + extra + b"\0",
                        self.listing + rows[0] + b"\0", self.listing[:-1], self.listing + b"\0", b""]:
            with self.subTest(listing=listing[:80]), self.assertRaises(RuntimeError):
                self.project(listing)

    def test_untouched_leaf_drift_is_not_exempt(self):
        rows = self.listing[:-1].split(b"\0")
        index = next(i for i, row in enumerate(rows)
                     if row.split(b"\t")[1].decode() not in self.sources)
        header, path = rows[index].split(b"\t")
        rows[index] = header.rsplit(b" ", 1)[0] + b" " + b"0" * 40 + b"\t" + path
        with self.assertRaisesRegex(RuntimeError, "complete current testing fixture dependency tree changed"):
            self.project(b"\0".join(rows) + b"\0")

    def test_changed_fixture_git_leaves_are_rejected(self):
        for name, (_, blob) in admission.LEAVES.items():
            changed = self.listing.replace(blob.encode() + b"\t" + name.encode(),
                                           b"0" * 40 + b"\t" + name.encode(), 1)
            self.assertNotEqual(changed, self.listing)
            with self.subTest(path=name), self.assertRaises(RuntimeError):
                self.project(changed)

    def test_invalid_modes_kinds_encodings_and_paths_are_rejected(self):
        first = self.listing.split(b"\0")[0]
        header, path = first.split(b"\t")
        for changed in [first.replace(b"100644", b"100755", 1),
                        first.replace(b"100644", b"120000", 1), first.replace(b"blob", b"commit", 1),
                        header + b"\t../" + path, header + b"\t/" + path,
                        header + b"\tsrc//file", header + b"\tsrc\\file", header + b"\t\xff"]:
            with self.subTest(row=changed), self.assertRaises(RuntimeError):
                self.project(self.listing.replace(first, changed, 1))

    def test_actual_fixture_sources_must_match_each_current_git_leaf(self):
        for name in admission.LEAVES:
            self.restore_sources()
            (self.root / admission.DEPENDENCY / name).write_bytes(self.sources[name] + b"\n")
            with self.subTest(path=name), self.assertRaisesRegex(RuntimeError, "physical testing fixture source"):
                self.project()

    def test_preceding_platform_physical_sources_are_still_checked(self):
        for name in admission.previous.LEAVES:
            self.restore_sources()
            (self.root / admission.DEPENDENCY / name).write_bytes(self.sources[name] + b"\n")
            with self.subTest(path=name), self.assertRaisesRegex(RuntimeError, "physical platform source"):
                self.project()

    def test_symlink_fixture_sources_are_rejected(self):
        name = next(iter(admission.LEAVES))
        path = self.root / admission.DEPENDENCY / name
        target = self.root / "other-file"
        path.rename(target)
        path.symlink_to(target)
        with self.assertRaisesRegex(RuntimeError, "physical regular"):
            self.project()

    def test_source_replacement_is_visible_to_terminal_comparison(self):
        before = self.project()
        path = self.root / admission.DEPENDENCY / next(iter(admission.LEAVES))
        replacement = self.root / "replacement"
        replacement.write_bytes(path.read_bytes())
        os.replace(replacement, path)
        after = self.project()
        self.assertNotEqual(before, after)
        self.assertEqual(before["actual_tree"], after["actual_tree"])

    def test_metadata_only_admission_cannot_hide_missing_physical_sources(self):
        path = self.root / admission.DEPENDENCY / next(iter(admission.LEAVES))
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.project()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    REPO = args.repo.resolve(strict=True)
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(FixtureSourceTests))
    report = {"schema": "codex.hia.exec-server-fixture-source-controls.v1",
              "passed": result.wasSuccessful(), "tests": result.testsRun,
              "failures": [(str(case), trace) for case, trace in result.failures],
              "errors": [(str(case), trace) for case, trace in result.errors],
              "helper_sha256": hashlib.sha256(Path(admission.__file__).read_bytes()).hexdigest(),
              "controls_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "actual_tree": admission.CURRENT_TREE, "preceding_tree": admission.PREVIOUS_TREE,
              "original_tree": admission.ORIGINAL_TREE}
    with args.report.open("x") as file:
        file.write(json.dumps(report, indent=2) + "\n")
    raise SystemExit(0 if report["passed"] and report["tests"] == 12 else 1)
