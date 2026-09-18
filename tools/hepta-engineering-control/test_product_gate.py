"""Product-caller regressions for the repository engineering gate."""

from pathlib import Path
import unittest
from unittest import mock

from control_engineering_v2 import product_gate


class ProductGateTests(unittest.TestCase):
    def _identity(self, *, event_name="pull_request", pull_request_number=697):
        return {
            "repository_full_name": product_gate.EXPECTED_REPOSITORY,
            "repository_id": product_gate.EXPECTED_REPOSITORY_ID,
            "workflow_ref": (
                product_gate.EXPECTED_WORKFLOW_PREFIX + "refs/pull/697/merge"
            ),
            "job_name": product_gate.EXPECTED_JOB,
            "run_id": 1,
            "run_attempt": 1,
            "event_name": event_name,
            "pull_request_number": pull_request_number,
        }

    def test_source_head_binds_real_source_and_grants_no_authority(self):
        values = iter(("a" * 40, "b" * 40))
        with mock.patch.object(product_gate, "_git", side_effect=lambda *_: next(values)):
            receipt = product_gate.build_product_receipt(
                Path("."),
                mode="source-head",
                source_sha="a" * 40,
                **self._identity(event_name="push", pull_request_number=0),
            )
        self.assertEqual(
            receipt["schedulerAssigned"], ["control.engineering.ci-product-gate"]
        )
        self.assertFalse(receipt["eligibleForIndependentReview"])
        for field in (
            "runtimeAuthority",
            "mergeAuthority",
            "activationAuthority",
            "promotionAuthority",
            "releaseAuthority",
            "externalEffectAuthority",
        ):
            self.assertFalse(receipt[field])

    def test_base_merge_calls_integration_eligibility_with_ordered_parents(self):
        source = "a" * 40
        base = "b" * 40
        calls = {
            ("rev-parse", "HEAD"): "c" * 40,
            ("rev-parse", "HEAD^{tree}"): "d" * 40,
            ("show", "-s", "--format=%P", "HEAD"): f"{base} {source}",
            ("rev-parse", f"{source}^{{tree}}"): "e" * 40,
        }
        with mock.patch.object(
            product_gate,
            "_git",
            side_effect=lambda _repository, *args: calls[args],
        ):
            receipt = product_gate.build_product_receipt(
                Path("."),
                mode="base-merge",
                source_sha=source,
                base_sha=base,
                **self._identity(),
            )
        self.assertTrue(receipt["eligibleForIndependentReview"])
        self.assertEqual(receipt["mergeParents"], [base, source])
        self.assertFalse(receipt["mergeAuthority"])
        self.assertFalse(receipt["releaseAuthority"])

    def test_base_merge_rejects_wrong_parent_order(self):
        source = "a" * 40
        base = "b" * 40
        calls = {
            ("rev-parse", "HEAD"): "c" * 40,
            ("rev-parse", "HEAD^{tree}"): "d" * 40,
            ("show", "-s", "--format=%P", "HEAD"): f"{source} {base}",
        }
        with mock.patch.object(
            product_gate,
            "_git",
            side_effect=lambda _repository, *args: calls[args],
        ):
            with self.assertRaisesRegex(ValueError, "ordered_merge_parent_mismatch"):
                product_gate.build_product_receipt(
                    Path("."),
                    mode="base-merge",
                    source_sha=source,
                    base_sha=base,
                    **self._identity(),
                )


    def test_ci_identity_mismatch_fails_closed(self):
        values = iter(("a" * 40, "b" * 40))
        identity = self._identity(event_name="push", pull_request_number=0)
        identity["repository_id"] = 0
        with mock.patch.object(product_gate, "_git", side_effect=lambda *_: next(values)):
            with self.assertRaisesRegex(ValueError, "repository_id_mismatch"):
                product_gate.build_product_receipt(
                    Path("."),
                    mode="source-head",
                    source_sha="a" * 40,
                    **identity,
                )

if __name__ == "__main__":
    unittest.main()
