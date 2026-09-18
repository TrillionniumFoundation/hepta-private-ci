"""Product-caller regressions for the repository engineering gate."""

from pathlib import Path
import unittest
from unittest import mock

from control_engineering_v2 import product_gate


class ProductGateTests(unittest.TestCase):
    def test_source_head_binds_real_source_and_grants_no_authority(self):
        values = iter(("a" * 40, "b" * 40))
        with mock.patch.object(product_gate, "_git", side_effect=lambda *_: next(values)):
            receipt = product_gate.build_product_receipt(
                Path("."),
                mode="source-head",
                source_sha="a" * 40,
            )
        self.assertEqual(
            receipt["schedulerAssigned"], ["control.engineering.ci-product-gate"]
        )
        self.assertFalse(receipt["eligibleForIndependentReview"])
        for field in (
            "runtimeAuthority",
            "mergeAuthority",
            "promotionAuthority",
            "releaseAuthority",
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
                )


if __name__ == "__main__":
    unittest.main()
