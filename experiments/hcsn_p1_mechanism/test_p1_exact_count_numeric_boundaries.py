"""Reject nonfinite reported means without altering frozen count evidence."""
from copy import deepcopy
from pathlib import Path
import unittest

from .p1_confirm_exact_count_audit import IncompleteEvidence, load_evidence, verify


class ReportedMeanBoundaryTests(unittest.TestCase):
    def test_nonfinite_means_cannot_match_exact_counts(self):
        original = load_evidence(Path(__file__).parent / "P1_CONFIRM_COMPACT_12SEEDS_20261031.json.gz.b64")
        for field in ("mean_ood_gain", "mean_id_acc"):
            for value in (float("nan"), float("inf"), -float("inf")):
                with self.subTest(field=field, value=value):
                    changed = deepcopy(original)
                    changed["rows"][0][field] = value
                    with self.assertRaises(IncompleteEvidence):
                        verify(changed)


if __name__ == "__main__":
    unittest.main()
