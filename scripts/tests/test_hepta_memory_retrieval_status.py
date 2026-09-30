import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts import hepta_memory_retrieval_status as status


def git(root, *args, input_text=None):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        input=input_text,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class StatusManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "Status fixture")
        git(self.root, "config", "user.email", "fixture@example.invalid")

        marker = self.root / "codex-rs/hepta-memory-retrieval/src/lib.rs"
        marker.parent.mkdir(parents=True)
        marker.write_text("// base\n")
        (self.root / "codex-rs/Cargo.lock").write_text("# lock\n")
        docs = self.root / "docs/modules/memory.retrieval"
        docs.mkdir(parents=True)
        (docs / "QUALIFICATION_IDENTITY.md").write_text("# identity\n")
        qualification = self.root / "qualification/memory-retrieval"
        qualification.mkdir(parents=True)
        (qualification / "qualification-policy.json").write_text("{}\n")
        (qualification / "product-composition.json").write_text("{}\n")
        (qualification / "production-qualification.json").write_text("{}\n")
        for workflow in sorted(set(status.REQUIRED_CHECKS.values())):
            path = self.root / workflow
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"name: {Path(workflow).stem}\n")

        mapping = {
            "module": "memory.retrieval",
            "productionImplementation": False,
            "claimBoundary": {claim: False for claim in status.CLAIMS},
        }
        path = self.root / status.MAP
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(mapping))
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "base")
        self.base = git(self.root, "rev-parse", "HEAD")

        marker.write_text("// source\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "source")
        self.source = git(self.root, "rev-parse", "HEAD")
        self.main = self.base
        tree = git(self.root, "rev-parse", "HEAD^{tree}")
        self.synthetic = git(
            self.root,
            "commit-tree",
            tree,
            "-p",
            self.base,
            "-p",
            self.source,
            input_text="synthetic\n",
        )
        self.github_merge = git(
            self.root,
            "commit-tree",
            tree,
            "-p",
            self.base,
            "-p",
            self.source,
            input_text="github merge\n",
        )

        workflow_ids = {
            workflow: 900 + index
            for index, workflow in enumerate(
                sorted(set(status.REQUIRED_CHECKS.values()))
            )
        }
        self.workflow_runs = [
            {
                "id": run_id,
                "name": Path(workflow).stem,
                "path": workflow,
                "head_sha": self.source,
                "run_attempt": 1,
                "event": "pull_request",
                "status": "in_progress",
                "conclusion": None,
            }
            for workflow, run_id in workflow_ids.items()
        ]
        self.checks = []
        self.jobs = []
        for index, (name, workflow) in enumerate(
            status.REQUIRED_CHECKS.items(), start=1
        ):
            check_id = 1000 + index
            run_id = workflow_ids[workflow]
            self.checks.append(
                {
                    "id": check_id,
                    "name": name,
                    "head_sha": self.source,
                    "status": "completed",
                    "conclusion": "success",
                    "app": {"slug": "github-actions"},
                    "details_url": (
                        "https://github.com/example/hepta/actions/runs/"
                        f"{run_id}/job/{check_id}"
                    ),
                }
            )
            self.jobs.append(
                {
                    "id": check_id,
                    "run_id": run_id,
                    "run_attempt": 1,
                    "head_sha": self.source,
                    "check_run_url": (
                        "https://api.github.com/repos/example/hepta/"
                        f"check-runs/{check_id}"
                    ),
                }
            )
        self.checks.extend(
            {
                "id": 2000 + index,
                "name": name,
                "head_sha": self.source,
                "status": "completed",
                "conclusion": conclusion,
                "app": {"slug": "github-advanced-security"},
                "details_url": f"https://example.invalid/security/{index}",
            }
            for index, (name, conclusion) in enumerate(
                status.SECURITY_CHECKS.items()
            )
        )
        convergence = ".github/workflows/hepta-memory-retrieval-convergence.yml"
        self.producer_run_id = workflow_ids[convergence]

    def build(self):
        return status.build_manifest(
            self.root,
            self.source,
            self.base,
            self.main,
            self.synthetic,
            self.checks,
            repository="example/hepta",
            workflow_runs=self.workflow_runs,
            jobs=self.jobs,
            github_merge=self.github_merge,
            final_merge=None,
            producer_run_id=self.producer_run_id,
            producer_run_attempt=1,
            producer_workflow=(
                ".github/workflows/hepta-memory-retrieval-convergence.yml"
            ),
            producer_job="manifest",
            event_name="pull_request",
            runner_image="ubuntu24/20260930.1",
            target_triple="x86_64-unknown-linux-gnu",
        )

    def test_manifest_binds_candidate_and_coherent_workflow_attempts(self):
        manifest = self.build()
        self.assertEqual(
            manifest["schema"],
            "hepta.memory-retrieval.qualification-manifest.v2",
        )
        self.assertEqual(manifest["source_head_sha"], self.source)
        self.assertEqual(manifest["frozen_source_sha"], self.source)
        self.assertEqual(manifest["main_sha"], self.main)
        self.assertEqual(manifest["base_sha"], self.base)
        self.assertEqual(manifest["deterministic_merge_sha"], self.synthetic)
        self.assertEqual(manifest["github_merge_sha"], self.github_merge)
        self.assertTrue(manifest["candidate_identity_satisfied"])
        self.assertTrue(manifest["repository_checks_satisfied"])
        self.assertTrue(manifest["security_checks_satisfied"])
        self.assertTrue(manifest["mergeReady"])
        self.assertFalse(manifest["external_gates_satisfied"])
        self.assertFalse(manifest["productionQualified"])
        self.assertFalse(manifest["production_ready"])
        self.assertFalse(manifest["independent_acceptance"])
        self.assertEqual(manifest["activation_mode"], "compatibility")
        self.assertEqual(manifest["check_identity_errors"], [])
        self.assertTrue(manifest["cargo_lock_hash"])
        self.assertTrue(manifest["qualification_profile_hash"])
        self.assertTrue(manifest["product_composition_hash"])
        self.assertTrue(manifest["production_qualification_hash"])
        self.assertTrue(manifest["test_set_hash"])

    def test_latest_failed_check_in_same_cohort_wins(self):
        original = self.checks[0]
        failed_id = 9000
        self.checks.append(
            {
                **original,
                "id": failed_id,
                "conclusion": "failure",
                "details_url": (
                    "https://github.com/example/hepta/actions/runs/"
                    f"{self.producer_run_id}/job/{failed_id}"
                ),
            }
        )
        self.jobs.append(
            {
                **self.jobs[0],
                "id": failed_id,
                "check_run_url": (
                    "https://api.github.com/repos/example/hepta/"
                    f"check-runs/{failed_id}"
                ),
            }
        )
        manifest = self.build()
        self.assertFalse(manifest["repository_checks_satisfied"])
        self.assertFalse(manifest["mergeReady"])
        self.assertFalse(manifest["productionQualified"])

    def test_newer_attempt_cannot_reuse_green_jobs_from_prior_attempt(self):
        convergence = ".github/workflows/hepta-memory-retrieval-convergence.yml"
        run = next(row for row in self.workflow_runs if row["path"] == convergence)
        run["run_attempt"] = 2
        original = self.checks[0]
        rerun_id = 9100
        self.checks.append(
            {
                **original,
                "id": rerun_id,
                "details_url": (
                    "https://github.com/example/hepta/actions/runs/"
                    f"{self.producer_run_id}/job/{rerun_id}"
                ),
            }
        )
        self.jobs.append(
            {
                **self.jobs[0],
                "id": rerun_id,
                "run_attempt": 2,
                "check_run_url": (
                    "https://api.github.com/repos/example/hepta/"
                    f"check-runs/{rerun_id}"
                ),
            }
        )
        manifest = status.build_manifest(
            self.root,
            self.source,
            self.base,
            self.main,
            self.synthetic,
            self.checks,
            repository="example/hepta",
            workflow_runs=self.workflow_runs,
            jobs=self.jobs,
            github_merge=self.github_merge,
            final_merge=None,
            producer_run_id=self.producer_run_id,
            producer_run_attempt=2,
            producer_workflow=convergence,
            producer_job="manifest",
            event_name="pull_request",
            runner_image="ubuntu24/20260930.1",
            target_triple="x86_64-unknown-linux-gnu",
        )
        cohort = manifest["workflow_cohorts"][convergence]
        self.assertEqual(cohort["run_attempt"], 2)
        self.assertFalse(cohort["complete"])
        self.assertFalse(manifest["repository_checks_satisfied"])
        self.assertFalse(manifest["mergeReady"])

    def test_producer_attempt_must_equal_selected_convergence_cohort(self):
        manifest = status.build_manifest(
            self.root,
            self.source,
            self.base,
            self.main,
            self.synthetic,
            self.checks,
            repository="example/hepta",
            workflow_runs=self.workflow_runs,
            jobs=self.jobs,
            github_merge=self.github_merge,
            final_merge=None,
            producer_run_id=self.producer_run_id,
            producer_run_attempt=2,
            producer_workflow=(
                ".github/workflows/hepta-memory-retrieval-convergence.yml"
            ),
            producer_job="manifest",
            event_name="pull_request",
            runner_image="ubuntu24/20260930.1",
            target_triple="x86_64-unknown-linux-gnu",
        )
        self.assertFalse(manifest["candidate_identity_satisfied"])
        self.assertFalse(manifest["mergeReady"])

    def test_wrong_workflow_path_fails_closed(self):
        convergence = ".github/workflows/hepta-memory-retrieval-convergence.yml"
        run = next(row for row in self.workflow_runs if row["path"] == convergence)
        run["path"] = ".github/workflows/not-the-policy-workflow.yml"
        manifest = self.build()
        self.assertFalse(
            manifest["workflow_cohorts"][convergence]["path_matches_policy"]
        )
        self.assertFalse(manifest["repository_checks_satisfied"])
        self.assertFalse(manifest["mergeReady"])

    def test_missing_action_metadata_is_explicit(self):
        missing = self.jobs.pop(0)
        manifest = self.build()
        self.assertTrue(
            any(
                row.get("check_id") == missing["id"]
                and row["reason"] == "missing_action_metadata"
                for row in manifest["check_identity_errors"]
            )
        )
        self.assertFalse(manifest["repository_checks_satisfied"])
        self.assertFalse(manifest["mergeReady"])

    def test_missing_security_check_is_explicit(self):
        self.checks = [
            row for row in self.checks if row["name"] != "CodeQL"
        ]
        manifest = self.build()
        self.assertEqual(
            manifest["security_checks"]["CodeQL"]["status"],
            "not_observed",
        )
        self.assertFalse(manifest["security_checks_satisfied"])
        self.assertFalse(manifest["mergeReady"])

    def test_wrong_synthetic_parent_order_fails(self):
        tree = git(self.root, "rev-parse", "HEAD^{tree}")
        reversed_merge = git(
            self.root,
            "commit-tree",
            tree,
            "-p",
            self.source,
            "-p",
            self.base,
            input_text="reversed\n",
        )
        with self.assertRaises(status.StatusError):
            status.build_manifest(
                self.root,
                self.source,
                self.base,
                self.main,
                reversed_merge,
                self.checks,
                repository="example/hepta",
                workflow_runs=self.workflow_runs,
                jobs=self.jobs,
                github_merge=self.github_merge,
                final_merge=None,
                producer_run_id=self.producer_run_id,
                producer_run_attempt=1,
                producer_workflow=(
                    ".github/workflows/"
                    "hepta-memory-retrieval-convergence.yml"
                ),
                producer_job="manifest",
                event_name="pull_request",
                runner_image="ubuntu24/20260930.1",
                target_triple="x86_64-unknown-linux-gnu",
            )

    def test_github_merge_tree_must_match_deterministic_merge(self):
        marker = self.root / "codex-rs/hepta-memory-retrieval/src/lib.rs"
        marker.write_text("// different tree\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "different")
        different_tree = git(self.root, "rev-parse", "HEAD^{tree}")
        wrong_github_merge = git(
            self.root,
            "commit-tree",
            different_tree,
            "-p",
            self.base,
            "-p",
            self.source,
            input_text="wrong github merge\n",
        )
        git(self.root, "checkout", "-q", self.source)
        with self.assertRaises(status.StatusError):
            status.build_manifest(
                self.root,
                self.source,
                self.base,
                self.main,
                self.synthetic,
                self.checks,
                repository="example/hepta",
                workflow_runs=self.workflow_runs,
                jobs=self.jobs,
                github_merge=wrong_github_merge,
                final_merge=None,
                producer_run_id=self.producer_run_id,
                producer_run_attempt=1,
                producer_workflow=(
                    ".github/workflows/"
                    "hepta-memory-retrieval-convergence.yml"
                ),
                producer_job="manifest",
                event_name="pull_request",
                runner_image="ubuntu24/20260930.1",
                target_triple="x86_64-unknown-linux-gnu",
            )

    def test_promoted_claim_is_refused(self):
        path = self.root / status.MAP
        mapping = json.loads(path.read_text())
        mapping["claimBoundary"]["activation"] = True
        path.write_text(json.dumps(mapping))
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "bad claim")
        self.source = git(self.root, "rev-parse", "HEAD")
        tree = git(self.root, "rev-parse", "HEAD^{tree}")
        self.synthetic = git(
            self.root,
            "commit-tree",
            tree,
            "-p",
            self.base,
            "-p",
            self.source,
            input_text="bad synthetic\n",
        )
        self.github_merge = git(
            self.root,
            "commit-tree",
            tree,
            "-p",
            self.base,
            "-p",
            self.source,
            input_text="bad github merge\n",
        )
        for row in self.checks:
            row["head_sha"] = self.source
        for row in self.jobs:
            row["head_sha"] = self.source
        for row in self.workflow_runs:
            row["head_sha"] = self.source
        with self.assertRaises(status.StatusError):
            self.build()


if __name__ == "__main__":
    unittest.main()
