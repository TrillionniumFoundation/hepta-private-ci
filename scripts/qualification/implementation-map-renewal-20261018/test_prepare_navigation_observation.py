"""Small isolated Git controls for the external preparation tool."""

import copy
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
import prepare_navigation_observation as prep

SOURCE = Path("/workspace/scratch/c176299dbc50/hepta-pon-candidate")


class OriginalOwnerPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(
            prefix="navigation-original-owner-test-"
        )
        cls.repo = Path(cls.temporary.name)
        (cls.repo / "scripts").mkdir()
        for name in ["hepta-implementation-maps.py", "hepta_module_source_roots.py"]:
            shutil.copyfile(SOURCE / "scripts" / name, cls.repo / "scripts" / name)
        (cls.repo / "src").mkdir()
        (cls.repo / "src/lib.rs").write_text("pub fn run() {}\n")
        (cls.repo / "docs").mkdir()
        (cls.repo / "docs/guide.md").write_text("Fixture source navigation only.\n")

        def git(*args):
            return subprocess.run(
                ["git", *args], cwd=cls.repo, check=True, capture_output=True, text=True
            ).stdout.strip()

        cls.git = staticmethod(git)
        git("init", "-q")
        git("config", "user.name", "Isolated Navigation Test")
        git("config", "user.email", "navigation-test@example.invalid")
        git("add", "scripts", "src", "docs")
        git("commit", "-qm", "isolated current source")
        cls.owner = prep.load_owner(cls.repo)
        cls.candidate = cls.owner.current_source_base()
        cls.nonancestor = {
            "commit": git(
                "commit-tree", cls.candidate["tree"], "-m", "separate isolated root"
            ),
            "tree": cls.candidate["tree"],
        }
        cls.module = {
            "id": "utility.ndu",
            "owner": "owner",
            "deputy": "deputy",
            "rootBindings": [{"path": "src"}],
            "technicalDocument": "docs/guide.md",
        }
        cls.lanes = {"utility.ndu": "fixture"}
        cls.row = cls.owner.map_for(cls.module, cls.nonancestor, cls.lanes)
        cls.row["operations"] = [
            {
                "operation": "run",
                "nativeSymbol": "run",
                "sourcePath": "src/lib.rs",
                "sourcePathExists": True,
                "tests": [],
                "authority": "none",
            }
        ]
        cls.row["claimBoundary"]["requestLocalReadOnlyProductExecutionProved"] = True
        cls.row["currentSourceEvidence"] = {
            "commit": cls.nonancestor["commit"],
            "scope": "old only",
        }

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_retains_real_nonancestor_failure_but_refuses_unknown_or_valid_anchor(self):
        failure = prep.original_nonancestor_failure(
            self.owner, self.row, self.candidate
        )
        self.assertEqual(failure["returncode"], 1)
        self.assertEqual(
            failure["command"][-4:],
            [
                "merge-base",
                "--is-ancestor",
                self.nonancestor["commit"],
                self.candidate["commit"],
            ],
        )
        for anchor, message in [
            (self.candidate, "now a valid ancestor"),
            (
                {"commit": "0" * 40, "tree": self.candidate["tree"]},
                "unavailable/malformed",
            ),
        ]:
            row = copy.deepcopy(self.row)
            row["sourceBase"] = anchor
            with self.assertRaisesRegex(ValueError, message):
                prep.original_nonancestor_failure(self.owner, row, self.candidate)

    def test_current_navigation_preserves_old_declaration_without_transferring_execution(
        self,
    ):
        old = copy.deepcopy(self.row)
        fresh, paths = prep.fresh_navigation(
            self.owner,
            self.row,
            self.module,
            self.lanes,
            self.candidate,
            {"archivedBlobPath": "old.json"},
        )
        self.assertEqual(self.row, old)
        self.assertTrue(
            self.row["claimBoundary"]["requestLocalReadOnlyProductExecutionProved"]
        )
        self.assertFalse(
            fresh["claimBoundary"]["requestLocalReadOnlyProductExecutionProved"]
        )
        self.assertEqual(fresh["sourceBase"], self.candidate)
        self.assertEqual(fresh["observedAtHead"], self.candidate)
        self.assertEqual(
            fresh["sourceIdentityPolicy"], "candidate_or_exact_observation_v1"
        )
        self.assertNotIn("currentSourceEvidence", fresh)
        self.assertIn(
            "currentSourceEvidence",
            fresh["sourceNavigationObservation"][
                "historicalMetadataRetainedInOriginalBlob"
            ],
        )
        self.assertEqual(paths, ["docs/guide.md", "src", "src/lib.rs"])
        self.assertFalse(self.owner.validate_claim_types(fresh))
        self.owner.verify_source_identity(fresh, ["src"], self.candidate)

    def test_positive_execution_cannot_be_downgraded_by_generic_navigation(self):
        row = copy.deepcopy(self.row)
        row["claimBoundary"]["productExecutionProved"] = True
        with self.assertRaisesRegex(ValueError, "positive execution claim"):
            prep.fresh_navigation(
                self.owner, row, self.module, self.lanes, self.candidate, {}
            )

    def test_wrong_module_is_not_silently_renamed_by_the_field_renderer(self):
        row = copy.deepcopy(self.row)
        row["module"] = "wrong.module"
        with self.assertRaisesRegex(ValueError, "module identity mismatch"):
            prep.fresh_navigation(
                self.owner, row, self.module, self.lanes, self.candidate, {}
            )

    def test_exact_git_blob_archive_preserves_final_newline_bytes(self):
        blob = self.git("rev-parse", "HEAD:src/lib.rs")
        self.assertEqual(prep.read_git_blob(self.repo, blob), b"pub fn run() {}\n")
        with self.assertRaisesRegex(ValueError, "literal SHA"):
            prep.read_git_blob(self.repo, "HEAD:src/lib.rs")


if __name__ == "__main__":
    unittest.main(verbosity=2)
