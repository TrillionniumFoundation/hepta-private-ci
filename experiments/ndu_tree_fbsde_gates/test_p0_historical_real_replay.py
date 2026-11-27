"""Synthetic numeric/negative controls only; no real checkpoint executed."""
import unittest
from p0_historical_real_replay import metrics,require

class HistoricalRealReplayTests(unittest.TestCase):
    def test_all_correct_confidence_ece(self):
        x=metrics([.10,.81],[0,1])
        self.assertEqual(x["correct"],2)
        self.assertAlmostEqual(x["confidence_ece8"],.145)
    def test_wrong_probability_brier(self):
        x=metrics([.8,.2],[0,1])
        self.assertEqual(x["correct"],0)
        self.assertAlmostEqual(x["brier"],.64)
    def test_categorical_score_not_finite(self):
        for p in ([float("nan")],[float("inf")],[-1.],[2.]):
            with self.assertRaises(ValueError): metrics(p,[0])
    def test_boolean_label_rejected(self):
        with self.assertRaises(ValueError):metrics([.2],[False])
    def test_empty_refused(self):
        with self.assertRaises(ValueError):metrics([],[])
    def test_reject_invalid_contract(self):
        with self.assertRaises(ValueError):require(False,"not admissible")
if __name__=="__main__":
    unittest.main()
