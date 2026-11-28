"""Independent controls for exact dependency history and physical current captures."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from file_update_oracle import dependencies as admission


class DependencySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.current = {p: (REPO / p).read_bytes() for p in admission.ROOT_FILES}
        cls.original = {p: subprocess.check_output(
            ["git", "-C", str(ORIGINAL), "show",
             "a2014bc6bfa1c1c9957edb3f14f8ae7d9ddcc095:" + p]) for p in admission.ROOT_FILES}
        cls.intermediate = {p: subprocess.check_output(
            ["git", "-C", str(REPO), "show",
             "a05499eb5d2b2088de6a192d0c42ce9ba0249882:" + p]) for p in admission.ROOT_FILES}
        for p in admission.ROOT_FILES:
            aeb = subprocess.check_output(["git", "-C", str(ORIGINAL), "show",
                "aeb88f596b83186456caac577080bcb2f253ad32:" + p])
            if aeb != cls.original[p]:
                raise RuntimeError("the two immutable original dependency pairs differ")

        cls.oauth2_fixture = None
        history, _ = admission._history()
        if admission._pair_identity(cls.current) != history["identities"]["sqlx"]:
            from file_update_oracle.oauth2_source_history import restore_predecessor
            cls.oauth2_fixture = restore_predecessor(REPO, cls.current, history["identities"]["sqlx"])
            cls.current = cls.oauth2_fixture["restored"]

    @classmethod
    def tearDownClass(cls):
        from file_update_oracle.oauth2_source_history import verify_predecessor
        verify_predecessor(cls.oauth2_fixture)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dependency-source-controls-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.write(self.current)

    def write(self, files):
        for name, data in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def test_identical_originals_keep_original_path(self):
        self.write(self.original)
        self.assertIsNone(admission.admit_workspace_sources(self.root, self.original))

    def test_complete_current_pair_recovers_actual_original_bytes(self):
        result = admission.admit_workspace_sources(self.root, self.original)
        self.assertEqual(result["restored"], self.original)
        self.assertFalse(result["report"]["dependency_graph_equivalence_claimed"])
        self.assertEqual([x["complete_package_inverses"] for x in result["report"]["inverse"]],
                         [4, 24])
        self.assertEqual({p: x["sha256"] for p, x in result["report"]["actual_files"].items()},
                         {p: hashlib.sha256(data).hexdigest() for p, data in self.current.items()})
        admission.verify_workspace_sources(result)

    def test_mixed_generation_pairs_are_rejected(self):
        pairs = (self.original, self.intermediate, self.current)
        for left in range(3):
            for right in range(3):
                if left == right:
                    continue
                with self.subTest(manifest=left, lock=right):
                    self.write({admission.ROOT_FILES[0]: pairs[left][admission.ROOT_FILES[0]],
                                admission.ROOT_FILES[1]: pairs[right][admission.ROOT_FILES[1]]})
                    with self.assertRaisesRegex(RuntimeError, "unreviewed or mixed"):
                        admission.admit_workspace_sources(self.root, self.original)

    def test_intermediate_is_provenance_only_not_admission(self):
        self.write(self.intermediate)
        with self.assertRaisesRegex(RuntimeError, "unreviewed or mixed"):
            admission.admit_workspace_sources(self.root, self.original)

    def test_unknown_unchanged_region_bytes_are_rejected(self):
        for name in admission.ROOT_FILES:
            with self.subTest(path=name):
                self.write(self.current)
                (self.root / name).write_bytes(b"# unreviewed byte change\n" + self.current[name])
                with self.assertRaisesRegex(RuntimeError, "unreviewed or mixed"):
                    admission.admit_workspace_sources(self.root, self.original)

    def test_altered_original_pair_is_rejected(self):
        for name in admission.ROOT_FILES:
            with self.subTest(path=name):
                original = dict(self.original)
                original[name] += b"\n"
                with self.assertRaisesRegex(RuntimeError, "unchanged a201/aeb original"):
                    admission.admit_workspace_sources(self.root, original)

    def test_missing_member_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "both complete"):
            admission.admit_workspace_sources(self.root, {admission.ROOT_FILES[0]: b""})

    def test_symbolic_link_is_rejected(self):
        name = admission.ROOT_FILES[0]
        path = self.root / name
        target = self.root / "other-manifest"
        path.rename(target)
        path.symlink_to(target)
        with self.assertRaisesRegex(RuntimeError, "physical regular"):
            admission.admit_workspace_sources(self.root, self.original)

    def test_identical_bytes_replaced_inode_is_rejected(self):
        result = admission.admit_workspace_sources(self.root, self.original)
        path = self.root / admission.ROOT_FILES[0]
        replacement = self.root / "replacement"
        replacement.write_bytes(path.read_bytes())
        os.replace(replacement, path)
        with self.assertRaisesRegex(RuntimeError, "captured dependency source identity changed"):
            admission.verify_workspace_sources(result)

    def test_captured_source_mutation_is_rejected(self):
        result = admission.admit_workspace_sources(self.root, self.original)
        path = self.root / admission.ROOT_FILES[1]
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(RuntimeError, "captured dependency source identity changed"):
            admission.verify_workspace_sources(result)

    def test_rewritten_history_is_rejected(self):
        path = self.root / "history.json"
        path.write_bytes(admission.HISTORY.read_bytes() + b"\n")
        with self.assertRaisesRegex(RuntimeError, "complete dependency source history changed"):
            admission._history(path)

    def test_inverse_missing_package_rejected_without_partial_acceptance(self):
        history, _ = admission._history()
        transition = copy.deepcopy(history["inverse"][0])
        transition["changes"][0]["after"] += "\n"
        with self.assertRaisesRegex(RuntimeError, "exactly one complete package"):
            admission._reverse(self.current, transition, history["identities"])


class PlatformSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from file_update_oracle import exec_server_source_history
        cls.module = exec_server_source_history
        cls.listing = subprocess.check_output(
            ["git", "-C", str(REPO), "ls-tree", "-r", "-z", cls.module.CURRENT_TREE])
        cls.original = subprocess.check_output(
            ["git", "-C", str(ORIGINAL), "show",
             "a2014bc6bfa1c1c9957edb3f14f8ae7d9ddcc095:" + cls.module.LOCAL_FILE])
        cls.sources = {name: (REPO / cls.module.DEPENDENCY / name).read_bytes()
                       for name in cls.module.LEAVES}

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="platform-source-controls-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.restore_sources()

    def restore_sources(self):
        for name, data in self.sources.items():
            path = self.root / self.module.DEPENDENCY / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def project(self, listing=None):
        m = self.module
        return m.reverse_platform_tree(self.root, m.DEPENDENCY, m.ORIGINAL_TREE,
                                       m.CURRENT_TREE, self.listing if listing is None else listing)

    def test_complete_platform_inverse_retains_existing_wine_leg(self):
        proof = self.project()
        self.assertEqual(proof["actual_leaf_count"], 144)
        self.assertEqual(proof["intermediate_tree"], self.module.PREVIOUS_TREE)
        self.assertEqual(proof["previous_projection"]["projected_original_tree"], self.module.ORIGINAL_TREE)
        self.assertEqual(proof["previous_projection"]["leaf_count"], 143)
        self.assertFalse(proof["platform_behavior_equivalence_claimed"])

    def test_local_source_recovers_the_whole_actual_original(self):
        proof = self.module.reverse_local_file_source(self.root, self.original)
        self.assertEqual(proof["restored_sha256"], hashlib.sha256(self.original).hexdigest())
        self.assertEqual(proof["restored_git_blob"], self.module.LEAVES["src/local_file_system.rs"][0])

    def test_untouched_tree_leaf_is_not_exempt(self):
        rows = self.listing[:-1].split(b"\0")
        index = next(i for i, row in enumerate(rows)
                     if row.split(b"\t")[1].decode() not in self.module.LEAVES)
        header, path = rows[index].split(b"\t")
        rows[index] = header.rsplit(b" ", 1)[0] + b" " + b"0" * 40 + b"\t" + path
        with self.assertRaisesRegex(RuntimeError, "complete current platform dependency tree changed"):
            self.project(b"\0".join(rows) + b"\0")

    def test_missing_tree_leaf_is_rejected(self):
        rows = self.listing[:-1].split(b"\0")
        with self.assertRaisesRegex(RuntimeError, "complete current platform dependency tree changed"):
            self.project(b"\0".join(rows[:-1]) + b"\0")

    def test_duplicate_tree_leaf_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "duplicate platform dependency leaf"):
            self.project(self.listing + self.listing.split(b"\0")[0] + b"\0")

    def test_actual_platform_sources_must_match_git_leaves(self):
        for name in self.sources:
            with self.subTest(path=name):
                self.restore_sources()
                (self.root / self.module.DEPENDENCY / name).write_bytes(self.sources[name] + b"\n")
                with self.assertRaisesRegex(RuntimeError, "physical platform source differs"):
                    self.project()

    def test_unknown_local_source_is_rejected(self):
        path = self.root / self.module.LOCAL_FILE
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(RuntimeError, "unreviewed current local filesystem source"):
            self.module.reverse_local_file_source(self.root, self.original)

    def test_changed_original_source_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "original complete local filesystem source changed"):
            self.module.reverse_local_file_source(self.root, self.original + b"\n")

    def test_replaced_source_identity_is_visible_to_terminal_comparison(self):
        before = self.project()
        path = self.root / self.module.LOCAL_FILE
        replacement = self.root / "replacement"
        replacement.write_bytes(path.read_bytes())
        os.replace(replacement, path)
        after = self.project()
        self.assertNotEqual(before, after)
        self.assertEqual(before["actual_tree"], after["actual_tree"])

    def test_symlink_platform_source_is_rejected(self):
        path = self.root / self.module.LOCAL_FILE
        target = self.root / "other-local-file"
        path.rename(target)
        path.symlink_to(target)
        with self.assertRaisesRegex(RuntimeError, "physical regular"):
            self.project()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--original-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    REPO, ORIGINAL = args.repo.resolve(strict=True), args.original_root.resolve(strict=True)
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls)
                               for cls in (DependencySourceTests, PlatformSourceTests))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {"schema": "codex.hia.workspace-dependency-source-controls.v1",
              "passed": result.wasSuccessful(), "tests": result.testsRun,
              "failures": [(str(case), trace) for case, trace in result.failures],
              "errors": [(str(case), trace) for case, trace in result.errors],
              "producer_head": subprocess.check_output(
                  ["git", "-C", str(REPO), "rev-parse", "HEAD"]).decode().strip(),
              "physical_source_sha256": {p: hashlib.sha256((REPO / p).read_bytes()).hexdigest()
                                         for p in admission.ROOT_FILES},
              "current_fixture_admission": (None if DependencySourceTests.oauth2_fixture is None
                  else DependencySourceTests.oauth2_fixture["report"]),
              "historical_fixture_source_sha256": {p: hashlib.sha256(data).hexdigest()
                  for p, data in DependencySourceTests.current.items()},
              "history_sha256": hashlib.sha256(admission.HISTORY.read_bytes()).hexdigest(),
              "helper_sha256": hashlib.sha256(Path(admission.__file__).read_bytes()).hexdigest(),
              "controls_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with args.report.open("x") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)
