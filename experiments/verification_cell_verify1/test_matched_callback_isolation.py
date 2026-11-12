"""Detached aliases must not fabricate independent VERIFY source clusters."""

from copy import deepcopy
import unittest

from .matched_qualification import analyze_matched
from .test_matched_qualification import (
    canonical,
    design_receipt,
    example,
    verify_fixture_design,
)


class MatchedCallbackIsolationTests(unittest.TestCase):
    def analyze(self, manifest, rows, **changes):
        arguments = dict(
            design=design_receipt(manifest),
            verify_design=verify_fixture_design,
            verify_label=lambda *args: True,
            verify_cost=lambda *args: True,
        )
        arguments.update(changes)
        return analyze_matched(manifest, rows, **arguments)

    def test_design_alias_rebinding_cannot_turn_one_cluster_into_eight(self):
        manifest, rows = example(8, clusters=[0] * 8)
        original = canonical([manifest, rows])
        ordinary = self.analyze(manifest, rows)
        self.assertEqual(
            (
                ordinary["cluster_count"],
                ordinary["paired_group_signflip_one_sided_p"],
                ordinary["gates"]["externally_reviewable"],
            ),
            (1, 0.5, False),
        )

        def rebind(m, receipt):
            detached = m["pairs"]
            m["pairs"] = deepcopy(detached)
            for index, pair in enumerate(detached):
                pair["cluster_id"] = f"forged-independent-{index}"
            return verify_fixture_design(m, receipt)

        with self.assertRaisesRegex(ValueError, "inputs changed"):
            self.analyze(manifest, rows, verify_design=rebind)
        self.assertEqual(canonical([manifest, rows]), original)

    def test_identical_nested_replacements_refuse_every_callback_boundary(self):
        for boundary in ("verify_design", "verify_label", "verify_cost"):
            manifest, rows = example()

            def replace(m, evidence):
                m["criteria"] = deepcopy(m["criteria"])
                return True

            with (
                self.subTest(boundary=boundary),
                self.assertRaisesRegex(ValueError, "inputs changed"),
            ):
                self.analyze(manifest, rows, **{boundary: replace})

    def test_label_and_cost_row_mutations_refuse_without_touching_originals(self):
        for boundary in ("verify_label", "verify_cost"):
            manifest, rows = example()
            original = canonical([manifest, rows])

            def mutate(m, row):
                row["cost_units"] = 0.123
                return True

            with (
                self.subTest(boundary=boundary),
                self.assertRaisesRegex(ValueError, "inputs changed"),
            ):
                self.analyze(manifest, rows, **{boundary: mutate})
            self.assertEqual(canonical([manifest, rows]), original)

    def test_retained_caller_aliases_cannot_change_frozen_scorer_objects(self):
        for boundary in ("verify_design", "verify_label", "verify_cost"):
            manifest, rows = example(8, clusters=[0] * 8)
            expected = self.analyze(manifest, rows)
            original = canonical([manifest, rows])

            def external_alias(m, evidence):
                pairs_before = manifest["pairs"]
                manifest["pairs"] = deepcopy(pairs_before)
                rows_before = list(rows)
                rows[:] = deepcopy(rows_before)
                for index, pair in enumerate(pairs_before):
                    pair["cluster_id"] = f"detached-{index}"
                for row in rows_before:
                    row["cost_units"] = 999
                return True

            with self.subTest(boundary=boundary):
                actual = self.analyze(manifest, rows, **{boundary: external_alias})
                self.assertEqual(actual, expected)
                self.assertEqual(canonical([manifest, rows]), original)

    def test_exceptions_and_truthy_results_still_fail_authentication(self):
        def unavailable(*args):
            raise RuntimeError("unavailable evaluator")

        for callback in (unavailable, lambda *args: 1, lambda *args: "True"):
            manifest, rows = example()
            report = self.analyze(manifest, rows, verify_label=callback)
            self.assertFalse(
                report["gates"]["independent_labels_receipt_authenticated"]
            )
            self.assertFalse(report["gates"]["externally_reviewable"])
