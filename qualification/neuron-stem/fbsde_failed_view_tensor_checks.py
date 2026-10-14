"""Exact historic request-chain mutation checks; no model outcome evidence."""
import unittest
from four_gate_common import canonical, digest
from fbsde_failed_view_fusion import journal_last, quantiles


class FailedViewReplayTests(unittest.TestCase):
    def good(self):
        last={"sequence":0,"split":"test","previous_sha256":None,
              "status":"budget_exceeded","prediction_returned":False,
              "cpu_ns":108513446,"head_sha256":"a"*64}
        identity=digest(last)
        return canonical({**last,"attempt_sha256":identity})+b"\n",identity

    def test_correct_original_like_attempt_admitted_without_a_success_claim(self):
        raw,identity=self.good()
        replay=journal_last(raw,expected_count=1,expected_last_sha=identity)
        self.assertEqual(replay["status"],"budget_exceeded")
        self.assertFalse(replay["prediction_returned"])

    def test_tampered_attempt_chain_or_budget_status_rejects(self):
        raw,identity=self.good()
        for invalid in (raw[:-2]+b"x\n", raw+b"\n",raw[:-1],raw*2):
            with self.subTest(invalid=invalid[:30]),self.assertRaises(ValueError):
                journal_last(invalid,expected_count=1,expected_last_sha=identity)
        with self.assertRaises(ValueError):
            journal_last(raw,expected_count=1,expected_last_sha="0"*64)
        with self.assertRaises(ValueError):
            journal_last(raw,expected_count=2,expected_last_sha=identity)

    def test_measured_quantiles_never_hide_cpu_tail(self):
        samples=[1]*100+[120_000_000]
        report=quantiles(samples)
        self.assertEqual(report["max"],120_000_000)
        self.assertEqual(report["p99"],1)
        with self.assertRaises(ValueError): quantiles(samples[:-2])


if __name__=="__main__":
    unittest.main()
