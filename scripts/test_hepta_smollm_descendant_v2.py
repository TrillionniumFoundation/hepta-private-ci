#!/usr/bin/env python3
"""Admission-boundary unit tests; these do not run or simulate a model."""

from fractions import Fraction
import unittest

from hepta_smollm_three_rounds_v2 import descendant_blockers


class DescendantBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.incumbent = dict(
            generation=1,
            contract="contract",
            adapter="initial",
            file_sha256="initial-bytes",
        )

    def test_positive_scores_do_not_issue_product_qualification(self):
        self.assertEqual(
            descendant_blockers(
                self.incumbent, self.incumbent, Fraction(1, 2), Fraction(1, 2)
            ),
            ["MissingSystemLongitudinalEvidence"],
        )

    def test_better_than_old_controls_still_must_improve_incumbent(self):
        self.assertEqual(
            descendant_blockers(
                self.incumbent, self.incumbent, Fraction(1, 2), Fraction(0)
            ),
            ["NoGain", "MissingSystemLongitudinalEvidence"],
        )

    def test_uninstalled_descendant_cannot_be_reported_as_current_parent(self):
        proposal = dict(
            self.incumbent, generation=2, adapter="trained", file_sha256="trained-bytes"
        )
        self.assertEqual(
            descendant_blockers(
                proposal, self.incumbent, Fraction(1, 2), Fraction(1, 2)
            ),
            ["ParentNotCurrent", "MissingSystemLongitudinalEvidence"],
        )

    def test_relabeling_same_bytes_as_new_generation_does_not_admit_them(self):
        self.assertEqual(
            descendant_blockers(
                dict(self.incumbent, generation=2),
                self.incumbent,
                Fraction(0),
                Fraction(0),
            ),
            ["ParentNotCurrent", "NoGain", "MissingSystemLongitudinalEvidence"],
        )


if __name__ == "__main__":
    unittest.main()
