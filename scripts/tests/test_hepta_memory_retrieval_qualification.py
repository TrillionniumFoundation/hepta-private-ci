"""Synthetic fixtures test the verifier, never production or performance evidence."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts import hepta_memory_retrieval_qualification as q


def execute(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


class SourceBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        execute(self.root, "init", "-q")
        execute(self.root, "config", "user.email", "fixture@example.invalid")
        execute(self.root, "config", "user.name", "Verifier fixture")
        self.source = self.root / q.ROOT / "src/lib.rs"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("pub fn fixture() {}\n")
        self.commit()
        observed = execute(self.root, "rev-parse", "HEAD")
        self.mapping = {
            "module": "memory.retrieval",
            "sourceBase": {"commit": observed},
            "observedAtHead": {
                "commit": observed,
                "tree": execute(self.root, "rev-parse", "HEAD^{tree}"),
            },
            "observedSourcePaths": list(q.INPUTS),
            "sourceObjects": [
                {
                    "path": q.ROOT,
                    "object": execute(self.root, "rev-parse", f"HEAD:{q.ROOT}"),
                }
            ],
            "productionImplementation": False,
            "claimBoundary": {claim: False for claim in q.CLAIMS},
        }
        self.save_map()

    def commit(self):
        execute(self.root, "add", "-A")
        execute(self.root, "commit", "-q", "-m", "fixture")
        self.head = execute(self.root, "rev-parse", "HEAD")

    def save_map(self):
        path = self.root / q.MAP
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.mapping))
        self.commit()

    def test_metadata_commit_has_exact_observation_not_fabricated_test_result(self):
        result = q.source_observation(self.root, self.head)
        self.assertEqual(result["testedHead"], self.head)
        self.assertFalse(result["testExecutionProved"])
        self.assertFalse(result["productionImplementation"])
        self.assertEqual(result["observedAtHead"], self.mapping["observedAtHead"])

    def test_wrong_head_fails(self):
        with self.assertRaises(q.QualificationError):
            q.source_observation(self.root, "1" * 40)

    def test_dirty_worktree_fails(self):
        self.source.write_text("changed")
        with self.assertRaises(q.QualificationError):
            q.source_observation(self.root, self.head)

    def test_untracked_source_fails(self):
        (self.source.parent / "untracked.rs").write_text("changed")
        with self.assertRaises(q.QualificationError):
            q.source_observation(self.root, self.head)

    def test_committed_source_drift_fails(self):
        self.source.write_text("changed")
        self.commit()
        with self.assertRaises(q.QualificationError):
            q.source_observation(self.root, self.head)

    def test_new_dependency_path_invalidates_old_observation(self):
        path = self.root / "codex-rs/hepta-types/src/lib.rs"
        path.parent.mkdir(parents=True)
        path.write_text("changed")
        self.commit()
        with self.assertRaises(q.QualificationError):
            q.source_observation(self.root, self.head)

    def test_missing_dependency_input_fails(self):
        self.mapping["observedSourcePaths"].remove("codex-rs")
        self.save_map()
        with self.assertRaises(q.QualificationError):
            q.source_observation(self.root, self.head)

    def test_extra_dependency_input_fails(self):
        self.mapping["observedSourcePaths"].append("legacy/safe/path")
        self.save_map()
        with self.assertRaises(q.QualificationError):
            q.source_observation(self.root, self.head)

    def test_stale_object_fails(self):
        self.mapping["sourceObjects"][0]["object"] = "1" * 40
        self.save_map()
        with self.assertRaises(q.QualificationError):
            q.source_observation(self.root, self.head)

    def test_full_tree_binding_cannot_be_omitted(self):
        self.mapping["sourceObjects"] = []
        self.save_map()
        with self.assertRaises(q.QualificationError):
            q.source_observation(self.root, self.head)

    def test_duplicate_source_object_fails(self):
        self.mapping["sourceObjects"].append(deepcopy(self.mapping["sourceObjects"][0]))
        self.save_map()
        with self.assertRaises(q.QualificationError):
            q.source_observation(self.root, self.head)


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.head, self.qualified = "a" * 40, "b" * 40
        self.pr = {
            "draft": False,
            "head": {"sha": self.head},
            "user": {"login": "author"},
        }
        self.reviews = [
            {
                "id": 1,
                "user": {"login": "reviewer", "type": "User"},
                "author_association": "MEMBER",
                "state": "APPROVED",
                "commit_id": self.head,
            }
        ]
        self.checks = [
            {
                "id": index,
                "name": name,
                "head_sha": self.qualified,
                "status": "completed",
                "conclusion": "success",
                "app": {"slug": "github-actions"},
                "verified_workflow_path": workflow,
                "verified_run_head": self.qualified,
            }
            for index, (name, workflow) in enumerate(q.REQUIRED_CHECKS.items(), start=1)
        ]
        self.checks.extend(
            {
                "id": 100 + index,
                "name": name,
                "head_sha": self.qualified,
                "status": "completed",
                "conclusion": conclusion,
                "app": {"slug": "github-advanced-security"},
            }
            for index, (name, conclusion) in enumerate(q.SECURITY_CHECKS.items())
        )

    def approve(self):
        return q.independent_approval(
            self.pr,
            self.reviews,
            self.checks,
            self.head,
            self.qualified,
            {"author"},
        )

    def test_independent_approval_is_only_a_necessary_source_gate(self):
        self.assertEqual(self.approve(), "reviewer")

    def test_draft_fails(self):
        self.pr["draft"] = True
        with self.assertRaises(q.QualificationError):
            self.approve()

    def test_author_cannot_self_approve(self):
        self.reviews[0]["user"]["login"] = "author"
        with self.assertRaises(q.QualificationError):
            self.approve()

    def test_bot_cannot_supply_independent_human_review(self):
        self.reviews[0]["user"]["type"] = "Bot"
        with self.assertRaises(q.QualificationError):
            self.approve()

    def test_stale_approval_fails(self):
        self.reviews[0]["commit_id"] = self.qualified
        with self.assertRaises(q.QualificationError):
            self.approve()

    def test_dismissed_approval_fails(self):
        self.reviews.append({**self.reviews[0], "id": 2, "state": "DISMISSED"})
        with self.assertRaises(q.QualificationError):
            self.approve()

    def test_skipped_check_is_not_success(self):
        self.checks[0]["conclusion"] = "skipped"
        with self.assertRaises(q.QualificationError):
            self.approve()

    def test_failed_security_check_blocks_promotion(self):
        codeql = next(row for row in self.checks if row["name"] == "CodeQL")
        codeql["conclusion"] = "failure"
        with self.assertRaises(q.QualificationError):
            self.approve()

    def test_same_name_from_wrong_workflow_fails(self):
        self.checks[0]["verified_workflow_path"] = ".github/workflows/fake.yml"
        with self.assertRaises(q.QualificationError):
            self.approve()

    def test_latest_failed_rerun_invalidates_old_success(self):
        self.checks.append({**self.checks[0], "id": 1000, "conclusion": "failure"})
        with self.assertRaises(q.QualificationError):
            self.approve()

    def test_string_false_is_not_a_boolean_claim(self):
        with self.assertRaises(q.QualificationError):
            q.requested_claims({"productionImplementation": "false"})

    def test_duplicate_json_key_fails(self):
        with self.assertRaises(q.QualificationError):
            json.loads(
                '{"activation":true,"activation":false}',
                object_pairs_hook=q.unique_object,
            )


if __name__ == "__main__":
    unittest.main()
