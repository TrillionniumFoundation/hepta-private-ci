from pathlib import Path
import unittest
from unittest import mock

from control_engineering_v2 import product_gate


class ProductGateV2Tests(unittest.TestCase):
    def identity(self, event="push", pr=0):
        return {
            "repository_full_name": product_gate.EXPECTED_REPOSITORY,
            "repository_id": product_gate.EXPECTED_REPOSITORY_ID,
            "workflow_ref": (
                product_gate.EXPECTED_REPOSITORY
                + "/"
                + product_gate.EXPECTED_WORKFLOW
                + "@refs/heads/main"
            ),
            "job_name": product_gate.EXPECTED_JOB,
            "run_id": 1,
            "run_attempt": 1,
            "event_name": event,
            "pull_request_number": pr,
        }

    def test_push_exercises_v2_orchestration_and_durable_scheduler(self):
        calls = {
            ("rev-parse", "HEAD"): "a" * 40,
            ("rev-parse", "HEAD^{tree}"): "b" * 40,
            ("show", "-s", "--format=%P", "HEAD"): "c" * 40,
            ("rev-parse", ("a" * 40) + "^{tree}"): "b" * 40,
        }
        with mock.patch.object(
            product_gate, "_git", side_effect=lambda _repository, *args: calls[args]
        ):
            receipt = product_gate.build_product_receipt(
                Path("."),
                source_sha="a" * 40,
                **self.identity(),
            )
        self.assertEqual(
            receipt["mergeQueueProposal"], ["control.engineering.product-caller"]
        )
        self.assertEqual(receipt["workerAssignment"]["worker_id"], "github-actions")
        self.assertFalse(receipt["mergeAuthority"])
        self.assertFalse(receipt["independentAcceptance"])

    def test_pr_requires_exact_ordered_synthetic_merge_parents(self):
        source = "a" * 40
        base = "b" * 40
        head = "c" * 40
        calls = {
            ("rev-parse", "HEAD"): head,
            ("rev-parse", "HEAD^{tree}"): "d" * 40,
            ("show", "-s", "--format=%P", "HEAD"): f"{base} {source}",
            ("rev-parse", source + "^{tree}"): "e" * 40,
        }
        identity = self.identity("pull_request", 123)
        identity["workflow_ref"] = (
            product_gate.EXPECTED_REPOSITORY
            + "/"
            + product_gate.EXPECTED_WORKFLOW
            + "@refs/pull/123/merge"
        )
        with mock.patch.object(
            product_gate, "_git", side_effect=lambda _repository, *args: calls[args]
        ):
            receipt = product_gate.build_product_receipt(
                Path("."),
                source_sha=source,
                base_sha=base,
                **identity,
            )
        self.assertEqual(receipt["orderedParents"], [base, source])

    def test_wrong_parent_order_fails_closed(self):
        source = "a" * 40
        base = "b" * 40
        calls = {
            ("rev-parse", "HEAD"): "c" * 40,
            ("rev-parse", "HEAD^{tree}"): "d" * 40,
            ("show", "-s", "--format=%P", "HEAD"): f"{source} {base}",
        }
        identity = self.identity("pull_request", 123)
        identity["workflow_ref"] = (
            product_gate.EXPECTED_REPOSITORY
            + "/"
            + product_gate.EXPECTED_WORKFLOW
            + "@refs/pull/123/merge"
        )
        with mock.patch.object(
            product_gate, "_git", side_effect=lambda _repository, *args: calls[args]
        ):
            with self.assertRaisesRegex(ValueError, "ordered_merge_parent_mismatch"):
                product_gate.build_product_receipt(
                    Path("."),
                    source_sha=source,
                    base_sha=base,
                    **identity,
                )

    def test_ci_identity_mismatch_fails_closed(self):
        identity = self.identity()
        identity["repository_id"] = 0
        with self.assertRaisesRegex(ValueError, "repository_id_mismatch"):
            product_gate.build_product_receipt(
                Path("."),
                source_sha="a" * 40,
                **identity,
            )


if __name__ == "__main__":
    unittest.main()
