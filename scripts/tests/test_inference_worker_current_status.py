from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import tempfile
import unittest


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "inference_worker_current_status.py"
SPEC = importlib.util.spec_from_file_location("inference_worker_current_status", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class InferenceWorkerCurrentStatusTest(unittest.TestCase):
    def test_exact_source_identity_and_external_gates_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = pathlib.Path(temporary)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.email", "ci@example.invalid"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.name", "CI"], check=True
            )
            source = repo / "codex-rs/hepta-infer-worker-host/src/lib.rs"
            source.parent.mkdir(parents=True)
            source.write_text("pub fn candidate() {}\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-q", "-m", "candidate"],
                check=True,
            )
            source_head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True,
                stdout=subprocess.PIPE,
                text=True,
            ).stdout.strip()

            status = MODULE.build_status(
                repository="example/repository",
                repo=repo,
                source_head=source_head,
                exact_head_run_id="17",
                exact_head_run_url="https://example.invalid/runs/17",
                exact_head_result="success",
                merge_candidate_commit=None,
                merge_candidate_result="not_applicable",
                linux_result="success",
                macos_result="success",
                derived_projections_result="success",
                roots=("codex-rs/hepta-infer-worker-host",),
                generated_at="2026-09-28T00:00:00+00:00",
            )

            self.assertEqual(status["source_head"], source_head)
            self.assertEqual(len(status["source_tree"]), 40)
            self.assertEqual(
                list(status["source_blob_digests"]),
                ["codex-rs/hepta-infer-worker-host/src/lib.rs"],
            )
            self.assertTrue(
                status["claim_boundary"]["repository_local_qualification_complete"]
            )
            self.assertFalse(status["claim_boundary"]["production_implementation"])
            self.assertFalse(
                status["claim_boundary"]["independent_acceptance_complete"]
            )
            self.assertEqual(
                status["real_hardware_result"], "not_run_external_gate"
            )
            self.assertEqual(
                status["profiles"]["LocalModelWorker"],
                "experimental-non-production",
            )
            self.assertEqual(
                status["local_model_source"]["signed_resource_grant"],
                "implemented",
            )
            self.assertEqual(
                status["local_model_source"]["real_weights_device_driver"],
                "not_implemented_external_and_product_gate",
            )
            self.assertIn(
                "trusted_terminal_receipt_port_implemented",
                status["provider_reconciliation"]["missing_history_resolution"],
            )
            self.assertIn(
                "deployed_provider_verifier_not_established",
                status["provider_reconciliation"][
                    "trusted_token_usage_reconciliation"
                ],
            )
            self.assertEqual(
                status["operating_runbook"],
                "docs/modules/inference.worker/RECOVERY_AND_OPERATIONS.md",
            )

    def test_mismatched_checkout_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = pathlib.Path(temporary)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.email", "ci@example.invalid"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo), "config", "user.name", "CI"], check=True
            )
            source = repo / "codex-rs/hepta-infer-worker-host/src/lib.rs"
            source.parent.mkdir(parents=True)
            source.write_text("one\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-q", "-m", "one"],
                check=True,
            )
            first = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True,
                stdout=subprocess.PIPE,
                text=True,
            ).stdout.strip()
            source.write_text("two\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-q", "-m", "two"],
                check=True,
            )

            with self.assertRaisesRegex(ValueError, "does not match requested source_head"):
                MODULE.build_status(
                    repository="example/repository",
                    repo=repo,
                    source_head=first,
                    exact_head_run_id="18",
                    exact_head_run_url="https://example.invalid/runs/18",
                    exact_head_result="failure",
                    merge_candidate_commit=None,
                    merge_candidate_result="not_applicable",
                    linux_result="failure",
                    macos_result="failure",
                    derived_projections_result="failure",
                    roots=("codex-rs/hepta-infer-worker-host",),
                )


if __name__ == "__main__":
    unittest.main()
