"""Fault and tampering tests for the durable confirmation boundary."""
import copy
import sqlite3
from pathlib import Path
import tempfile
import unittest

import numpy as np

from guard import ARMS, Ledger, dual_norm_random, quality_gate


class ConfirmationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.sqlite"
        self.ledger = Ledger(self.path)
        self.samples = [{"sha256": "new", "fit": 11, "domain": "iid"}]
        self.ledger.freeze("protocol", "cohort", ["old-test"])

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def test_crash_consumes_all_arms_before_first_score(self):
        self.ledger.reserve("protocol", "cohort", self.samples)
        self.ledger.close()
        self.ledger = Ledger(self.path)
        self.assertEqual(self.ledger.counts("protocol"), {"RESERVED": len(ARMS)})
        with self.assertRaises(ValueError):
            self.ledger.reserve("protocol", "cohort", self.samples)

    def test_failed_attempt_cannot_be_retried(self):
        self.ledger.reserve("protocol", "cohort", self.samples)
        self.ledger.record("protocol", "new", 11, "E", {"failure": "timeout"}, .1, .2, failed=True)
        with self.assertRaises(ValueError):
            self.ledger.record("protocol", "new", 11, "E", {"gain": 10}, .1, .2)
        self.assertEqual(self.ledger.counts("protocol"), {"FAILED": 1, "RESERVED": len(ARMS) - 1})

    def test_historical_collision_rolls_back_complete_reservation(self):
        samples = copy.deepcopy(self.samples) + [{"sha256": "old-test", "fit": 11, "domain": "ood"}]
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger.reserve("protocol", "cohort", samples)
        self.assertEqual(self.ledger.counts("protocol"), {})

    def test_changed_candidate_and_missing_arm_are_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.reserve("protocol", "other", self.samples)
        with self.assertRaises(ValueError):
            self.ledger.reserve("protocol", "cohort", self.samples, ARMS[:-1])

    def test_new_protocol_cannot_reuse_consumed_sample(self):
        self.ledger.reserve("protocol", "cohort", self.samples)
        self.ledger.freeze("another", "cohort2", [])
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger.reserve("another", "cohort2", self.samples)

    def test_unmeasured_energy_cannot_qualify_production(self):
        gate = quality_gate([{"familywise_interval": [.1, .3]}], {"task": True}, ["energy_joules"])
        self.assertTrue(gate["task_benefit_pass"])
        self.assertFalse(gate["production_eligible"])

    def test_random_control_matches_two_norms_and_is_seeded(self):
        delta = np.arange(147, dtype=float).reshape(3, 49) / 147
        draw = dual_norm_random(delta, np.random.default_rng(11))
        np.testing.assert_array_equal(draw, dual_norm_random(delta, np.random.default_rng(11)))
        np.testing.assert_array_equal(np.sort(abs(draw).ravel()), np.sort(delta.ravel()))
        self.assertAlmostEqual(np.linalg.norm(draw), np.linalg.norm(delta))
        self.assertEqual(abs(draw).max(), abs(delta).max())


if __name__ == "__main__":
    unittest.main()
