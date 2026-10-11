"""Exercise the REAL existing prequential verifier, not a fabricated PASS report."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from four_gate_common import canonical, digest
from four_gate_review import review_learning
from test_four_gate_fixtures import plan_fixture
import test_prequential_threeway as existing


class ExistingLearningBridgeTests(unittest.TestCase):
    def setUp(self):
        self.old = existing.PrequentialThreeWayTests()
        self.old.setUp()
        self.plan = plan_fixture()
        self.plan.update(preregistered_at="2025-12-01T00:00:00Z",
                         selection_cutoff="2026-01-03T23:59:59Z")
        self.plan["windows"] = {"future_1": ["2026-01-04T00:00:00Z", "2026-01-04T23:59:59Z"],
                                "future_2": ["2026-01-05T00:00:00Z", "2026-01-05T23:59:59Z"]}
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)

    def evidence_refs(self):
        originals = {"dataset": b"".join(canonical(r) + b"\n" for r in self.old.rows),
                     "trial": canonical(self.old.trial), "prelabel_journal": self.old.journal,
                     "no_change": b"".join(canonical(r) + b"\n" for r in self.old.nochange),
                     "ood_receipts": b"".join(canonical(r) + b"\n" for r in self.old.synthetic_threeway_ood_receipts())}
        refs = {}
        for name, raw in originals.items():
            (Path(self.root.name) / name).write_bytes(raw)
            refs[name] = {"path": name, "sha256": hashlib.sha256(raw).hexdigest()}
        return refs

    def test_existing_threeway_plus_raw_ood_is_recomputed(self):
        report = review_learning(self.plan, self.evidence_refs(), self.root.name)
        self.assertEqual(report["status"], "diagnostic_pass")
        self.assertEqual(len(report["metrics"]["family_adjusted_comparisons"]), 10)
        self.assertFalse(report["production_promotion_permitted"])

    def test_success_flag_cannot_hide_broken_head_lineage(self):
        self.old.trial["temporal_receipts"][-1]["preupdate_head_digest"] = digest("forged head")
        self.old.trial["quality_three_way_precheck_passed"] = True
        with self.assertRaises(ValueError):
            review_learning(self.plan, self.evidence_refs(), self.root.name)

    def test_omitted_nochange_is_not_a_learning_claim(self):
        self.old.nochange.pop()
        with self.assertRaises(ValueError):
            review_learning(self.plan, self.evidence_refs(), self.root.name)

    def test_unobserved_calendar_data_cannot_pass(self):
        self.plan["assessment_time"] = "2026-01-04T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "unobserved"):
            review_learning(self.plan, self.evidence_refs(), self.root.name)


if __name__ == "__main__":
    unittest.main()
