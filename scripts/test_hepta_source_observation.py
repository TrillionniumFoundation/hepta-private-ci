"""Exercise source observations against real disposable Git histories."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "implementation_maps_under_test",
    Path(__file__).with_name("hepta-implementation-maps.py"),
)
assert SPEC is not None and SPEC.loader is not None
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


class SourceObservationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Source Observation Test")
        self.git("config", "user.email", "source-observation@example.invalid")
        self.write("owner/lib.rs", "pub fn read() {}\n")
        self.write("other/lib.rs", "pub fn other() {}\n")
        self.commit()
        patch = mock.patch.object(subject, "ROOT", self.root)
        patch.start()
        self.addCleanup(patch.stop)
        self.row = {
            "sourceBase": self.identity(),
            "observedAtHead": self.identity(),
            "observedSourcePaths": ["owner"],
            "sourceIdentityPolicy": "candidate_or_exact_observation_v1",
        }

    def git(self, *args):
        return subprocess.run(
            ["git", "--literal-pathspecs", *args],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def commit(self):
        self.git("add", "--all")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "fixture")

    def identity(self):
        return {
            "commit": self.git("rev-parse", "HEAD"),
            "tree": self.git("rev-parse", "HEAD^{tree}"),
        }

    def failures(self):
        failures = []
        subject.validate_observed_source(self.row, "fixture", ["owner"], failures)
        return failures

    def test_accepts_exact_source(self):
        self.assertEqual(self.failures(), [])

    def test_accepts_documentation_only_descendant(self):
        self.write("docs/note.md", "Explanation, not source evidence.\n")
        self.commit()
        self.assertEqual(self.failures(), [])

    def test_unrelated_module_change_does_not_invalidate_owner(self):
        self.write("other/lib.rs", "pub fn successor() {}\n")
        self.commit()
        self.assertEqual(self.failures(), [])

    def test_rejects_committed_owner_drift(self):
        self.write("owner/lib.rs", "pub fn changed() {}\n")
        self.commit()
        self.assertTrue(self.failures())

    def test_rejects_unstaged_owner_drift(self):
        self.write("owner/lib.rs", "pub fn changed() {}\n")
        self.assertTrue(self.failures())

    def test_rejects_staged_owner_drift(self):
        self.write("owner/lib.rs", "pub fn changed() {}\n")
        self.git("add", "owner/lib.rs")
        self.assertTrue(self.failures())

    def test_rejects_untracked_owner_input(self):
        self.write("owner/new.rs", "pub fn untracked() {}\n")
        self.assertTrue(self.failures())

    def test_candidate_identity_without_observation_still_checks_bytes(self):
        del self.row["observedAtHead"]
        self.write("owner/lib.rs", "pub fn changed() {}\n")
        self.assertTrue(self.failures())

    def test_rejects_absolute_observed_path(self):
        self.row["observedSourcePaths"].append(str(self.root / "owner"))
        self.assertTrue(self.failures())

    def test_rejects_noncanonical_observed_path(self):
        self.row["observedSourcePaths"].append("other/../owner")
        self.assertTrue(self.failures())

    def test_rejects_symlink_observation_inside_repository(self):
        (self.root / "alias").symlink_to("owner", target_is_directory=True)
        self.commit()
        self.row.update(sourceBase=self.identity(), observedAtHead=self.identity())
        self.row["observedSourcePaths"].append("alias")
        self.assertTrue(self.failures())

    def test_rejects_pathspec_exclusion_that_hides_owner_drift(self):
        self.write(":(exclude)owner", "A literal filename is not a Git option.\n")
        self.commit()
        self.row.update(sourceBase=self.identity(), observedAtHead=self.identity())
        self.row["observedSourcePaths"].append(":(exclude)owner")
        self.write("owner/lib.rs", "pub fn changed() {}\n")
        self.commit()
        self.assertTrue(self.failures())

    def test_rejects_ignored_path_without_observed_git_object(self):
        self.write(".gitignore", "ignored-input\n")
        self.commit()
        self.write("ignored-input", "Not present in the observed tree.\n")
        self.row.update(sourceBase=self.identity(), observedAtHead=self.identity())
        self.row["observedSourcePaths"].append("ignored-input")
        self.assertTrue(self.failures())

    def test_metacharacter_filename_is_literal_not_glob(self):
        self.write("input[1]", "tracked\n")
        self.commit()
        self.row.update(sourceBase=self.identity(), observedAtHead=self.identity())
        self.row["observedSourcePaths"].append("input[1]")
        self.write("input[1]", "changed\n")
        self.commit()
        self.assertTrue(self.failures())

    def test_rejects_wrong_tree(self):
        self.row["observedAtHead"]["tree"] = "0" * 40
        self.assertTrue(self.failures())

    def test_rejects_nonancestor_observation(self):
        self.git("checkout", "--orphan", "unrelated")
        self.git("rm", "-rf", ".")
        self.write("owner/lib.rs", "pub fn read() {}\n")
        self.commit()
        self.assertTrue(self.failures())

    def test_rejects_omitted_owner_root(self):
        self.row["observedSourcePaths"] = ["other"]
        self.assertTrue(self.failures())

    def install_map(self, mid, root, identity, policy):
        row = {
            "schema": "hepta.module-implementation-map.v3",
            "schemaVersion": 3,
            "module": mid,
            "laneId": "fixture-lane",
            "sourceBase": identity,
            "observedAtHead": identity,
            "sourceIdentityPolicy": policy,
            "observedSourcePaths": [root],
            "declaredRoots": [root],
            "resolvedRoots": [root],
            "sourceRootPresent": True,
            "productionImplementation": False,
            "operations": [
                {
                    "operation": "read",
                    "nativeSymbol": "read",
                    "sourcePath": f"{root}/lib.rs",
                }
            ],
            "claimBoundary": {"productExecutionProved": False},
        }
        self.write(f"docs/modules/{mid}/IMPLEMENTATION_MAP.json", json.dumps(row))
        return {"id": mid, "rootBindings": [{"path": root}]}

    def verify_maps(self, modules):
        def load_fixture(relative):
            if relative == "docs/modules/MODULES.json":
                return {"modules": modules}
            return json.loads((self.root / relative).read_text(encoding="utf-8"))

        with (
            mock.patch.object(subject, "load", side_effect=load_fixture),
            mock.patch.object(
                subject,
                "lane_by_module",
                return_value={module["id"]: "fixture-lane" for module in modules},
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            subject.verify()

    def test_all_migrated_maps_with_different_anchors_are_accepted(self):
        older = self.identity()
        self.write("other/lib.rs", "pub fn read() {}\n")
        self.commit()
        modules = [
            self.install_map(
                "first", "owner", older, "candidate_or_exact_observation_v1"
            ),
            self.install_map(
                "second", "other", self.identity(), "candidate_or_exact_observation_v1"
            ),
        ]
        self.commit()
        self.verify_maps(modules)

    def test_shared_legacy_identity_does_not_hide_committed_source_drift(self):
        modules = [
            self.install_map(mid, root, self.identity(), "legacy_shared_batch")
            for mid, root in [("first", "owner"), ("second", "other")]
        ]
        self.commit()
        self.write("owner/lib.rs", "pub fn changed_after_both_legacy_anchors() {}")
        self.commit()
        with self.assertRaises(SystemExit):
            self.verify_maps(modules)


if __name__ == "__main__":
    unittest.main()
