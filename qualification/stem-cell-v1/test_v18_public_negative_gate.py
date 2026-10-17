"""Verify exact archived public negative evidence is never silently promoted."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import unittest
import v18_public_negative_gate as g

HERE=Path(__file__).parent


class Gate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data,cls.sha=g.read(HERE/"STEM_V18_SOURCE_FIRST_20261016.json")
        cls.hold,_=g.read(HERE/"STEM_V18_FUTURE_SOURCE_HOLD_20261016.json")
        cls.meter,_=g.read(HERE/"STEM_V18_READONLY_REPLAY_METER_20261016.json")

    def actual(self):
        return g.review(self.data,self.hold,self.meter,self.sha)

    def test_original_receipt_and_hold_agree(self):
        result=self.actual()
        self.assertEqual(result["verdict"],"COUNTS_CONSISTENT_NOT_FUTURE_MODEL_SUPERIORITY")
        self.assertEqual(result["genuine_new_source_roots"],0)
        self.assertFalse(result["production_authorized"])

    def test_rehashed_public_numerical_change_is_not_same_original(self):
        x=deepcopy(self.data)
        x["arms"]["geo_aligned_oof"]["case_mean"]=.8
        with self.assertRaises(ValueError):g.review(x,self.hold,self.meter,self.sha)

    def test_rehashed_false_future_claim_fails(self):
        x=deepcopy(self.hold)
        x["new_signed_window_count"]=2
        with self.assertRaises(ValueError):g.review(self.data,x,self.meter,self.sha)

    def test_wrong_original_receipt_sha_fails(self):
        with self.assertRaises(ValueError):g.review(self.data,self.hold,self.meter,"0"*64)

    def test_single_fake_meter_repetition_fails(self):
        x=deepcopy(self.meter)
        x["runs"].pop()
        with self.assertRaises(ValueError):g.review(self.data,self.hold,x,self.sha)

    def test_fake_research_promotion_fails(self):
        x=deepcopy(self.data)
        x["scientific_promotion_authorized"]=True
        with self.assertRaises(ValueError):g.review(x,self.hold,self.meter,self.sha)

    def test_false_original_case_count_fails(self):
        x=deepcopy(self.data)
        x["distinct_original_calibration_cases"]=96
        with self.assertRaises(ValueError):g.review(x,self.hold,self.meter,self.sha)

    def test_cost_claim_cannot_be_invented(self):
        x=deepcopy(self.meter)
        x["target_host_qualified"]=True
        with self.assertRaises(ValueError):g.review(self.data,self.hold,x,self.sha)


if __name__=="__main__":unittest.main()
