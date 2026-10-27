"""Evidence semantics tested against independently specified probability laws."""

import copy
import unittest

import numpy as np

from .blocks import Capture, EvidenceState, JointLaw
from .models import fit_prior


ASSUMPTION = "conditional independence only between declared blocks"


class EvidenceBlockTests(unittest.TestCase):
    def setUp(self):
        self.capture = Capture("trusted source", "opaque acquisition 17", "a"*64)
        self.law = JointLaw(np.array([[[.44, .01], [.06, .09]],
                                     [[.06, .09], [.44, .81]]]), ("a", "b"))
        self.prior = np.array([.5, .5])

    def state(self):
        event = self.capture.event_id
        return EvidenceState(self.prior, {"recording": (self.law, {"a": event, "b": event})},
                             {event: self.capture}, ASSUMPTION)

    def receipt(self, view, value, alias=None):
        return {"block": "recording", "view": view, "alias": alias or self.capture.event_id,
                "content_sha256": self.capture.content_sha256, "value": value}

    def test_partial_arrival_and_reverse_order_use_one_joint_factor(self):
        state = self.state()
        partial = state.ingest(self.receipt("a", 0))
        np.testing.assert_allclose(partial["posterior"], [5/6, 1/6])
        complete = state.ingest(self.receipt("b", 0))
        np.testing.assert_allclose(complete["posterior"], [44/45, 1/45])
        reverse = self.state()
        reverse.ingest(self.receipt("b", 0))
        reverse.ingest(self.receipt("a", 0))
        self.assertEqual(state.snapshot(), reverse.snapshot())
        self.assertEqual((complete["factor_count"], complete["physical_event_count"]), (1, 1))
        self.assertGreater(abs(state.posterior[0]-(.25/.26)), .01)

    def test_alias_retry_and_conflicts_preserve_full_state(self):
        state = self.state()
        state.register_alias("renamed file", self.capture)
        state.ingest(self.receipt("a", 0))
        before = state.checkpoint()
        result = state.ingest(self.receipt("a", 0, "renamed file"))
        self.assertTrue(result["duplicate"])
        self.assertEqual(before, state.checkpoint())
        conflicts = [self.receipt("a", 1), {**self.receipt("b", 0), "content_sha256": "b"*64},
                     {**self.receipt("b", 0), "target": 0}]
        for receipt in conflicts:
            with self.assertRaises(ValueError):
                state.ingest(receipt)
            self.assertEqual(before, state.checkpoint())

    def test_duplicate_acquisition_cannot_be_split_into_independent_blocks(self):
        event = self.capture.event_id
        blocks = {"first": (self.law, {"a": event, "b": event}),
                  "second": (self.law, {"a": event, "b": event})}
        with self.assertRaises(ValueError):
            EvidenceState(self.prior, blocks, {event: self.capture}, ASSUMPTION)

    def test_equal_payload_different_acquisitions_remain_two_events(self):
        second = Capture(self.capture.source, "different acquisition", self.capture.content_sha256)
        first, other = self.capture.event_id, second.event_id
        state = EvidenceState(self.prior, {"recording": (self.law, {"a": first, "b": other})},
                              {first: self.capture, other: second}, ASSUMPTION)
        state.ingest(self.receipt("a", 0))
        state.ingest(self.receipt("b", 0, other))
        self.assertEqual(state.snapshot()["physical_event_count"], 2)

    def test_unknown_target_support_cannot_be_filled_by_marginals(self):
        table = self.law.table.copy()
        table[..., 1] = np.nan
        law = JointLaw(table, ("a", "b"))
        event = self.capture.event_id
        with self.assertRaises(ValueError):
            EvidenceState(self.prior, {"x": (law, {"a": event, "b": event})},
                          {event: self.capture}, ASSUMPTION)
        table[..., 1] = np.inf
        with self.assertRaises(ValueError):
            JointLaw(table, ("a", "b"))

    def test_checkpoint_replay_and_tamper_fail_closed(self):
        state = self.state()
        state.register_alias("retry", self.capture)
        state.ingest(self.receipt("a", 0))
        checkpoint = state.checkpoint()
        restored = self.state()
        restored.restore(checkpoint)
        restored.ingest(self.receipt("b", 0, "retry"))
        state.ingest(self.receipt("b", 0))
        self.assertEqual(state.checkpoint(), restored.checkpoint())
        broken = copy.deepcopy(checkpoint)
        broken["state"]["posterior"] = [.5, .5]
        empty = self.state()
        before = empty.checkpoint()
        with self.assertRaises(ValueError):
            empty.restore(broken)
        self.assertEqual(before, empty.checkpoint())

    def test_target_prior_fitting_rejects_observation_fields(self):
        rows = [{"sample_id": "s", "speaker": "fit", "cue": "x", "target": 0}]
        self.assertAlmostEqual(float(fit_prior(rows, "x", "joint", 1).sum()), 1.)
        rows[0]["observation"] = 0
        with self.assertRaises(ValueError):
            fit_prior(rows, "x", "joint", 1)


if __name__ == "__main__":
    unittest.main()
