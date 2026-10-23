"""Small hand-only observation, service and fixed call-grid checks."""

import base64
import hashlib
import json
import os
from pathlib import Path
import unittest

import numpy as np

from content_joint.native_model import Native12
from content_joint.observe import evaluate
from content_joint.run import FAMILIES, call_plan
from content_joint.service import execute
from data import DecodedObserver
from independent.accounting import WorkLedger
from model import JointModel


OUT = Path(os.environ.get("CONTENT_JOINT_FLOW_UNIT_DIR", "runs/content-joint-flow-unit-v1-20261023"))
HAND = WorkLedger("hand-flow-checks")


def setUpModule():
    OUT.mkdir(parents=True, exist_ok=False)


def tearDownModule():
    (OUT / "hand-ledger.json").write_text(json.dumps(HAND.snapshot(), indent=2, sort_keys=True) + "\n")


class FlowChecks(unittest.TestCase):
    def test_fixed_slot_and_call_denominators(self):
        plan = call_plan()
        self.assertEqual(len(plan["slots"]), 24)
        self.assertEqual(len(plan["service_calls"]), 36)
        self.assertEqual(len({(s["family"], s["recipe"], s["seed"]) for s in plan["slots"]}), 24)
        for family in FAMILIES:
            self.assertEqual(sum(s["family"] == family for s in plan["slots"]), 6)
            self.assertEqual(sum(s["rows"] for s in plan["service_calls"] if s["family"] == family), 576)
        self.assertEqual(plan["aliases_add_calls"], 0)

    def test_observation_capture_and_checkpoint_envelope(self):
        rng = np.random.default_rng(801)
        base = JointModel(202, 12, 192, 32, seed=803)
        native = Native12(base)
        x, labels, sources = rng.normal(size=(3, 202)), np.array([0, 4, 11]), ["hand:0", "hand:1", "hand:2"]
        r, distances = rng.uniform(-.35, 1., (12, 12, 12)), rng.uniform(0, .1, (12, 12))
        observer = DecodedObserver((np.arange(12), np.arange(12), None, distances), r)
        for recipe, model in (("native", native), ("independent", base)):
            before = HAND.consumed_units
            arrays, summary = evaluate(model, recipe, x, labels, sources, HAND,
                                        observer, full_audit=True, stage="hand")
            np.testing.assert_array_equal(arrays["source_ids"], sources)
            np.testing.assert_array_equal(arrays["labels"], labels)
            self.assertIn("h", arrays)
            self.assertLess(HAND.consumed_units - before, 3 * 100_000)
            if recipe == "native":
                self.assertTrue(summary["native"]["sparse_full_audit_performed"])
                np.testing.assert_allclose(arrays["native/Q"].sum((1, 2)), 1, atol=1e-15)
            else:
                self.assertIn("p", arrays)
                self.assertIn("q", arrays)
                self.assertIn("log2/actions", arrays)

    def test_service_saves_runtime_laws_and_real_outputs(self):
        rng = np.random.default_rng(811)
        base = JointModel(202, 12, 192, 32, seed=813)
        native = Native12(base)
        x, labels, sources = rng.normal(size=(3, 202)), np.array([0, 4, 11]), ["hand:0", "hand:1", "hand:2"]
        for recipe, profile, model in (("independent", "KEEP", base),
                                        ("independent", "log2", base), ("native", "native", native)):
            path = OUT / (recipe + "-" + profile + ".json")
            receipt, elapsed = execute(model, recipe, profile, x, labels, sources, 817, path)
            self.assertGreater(elapsed, 0)
            self.assertEqual(json.loads(path.read_text()), receipt)
            self.assertEqual(receipt["source_ids"], sources)
            self.assertEqual(receipt["rows"], 3)
            self.assertLessEqual(receipt["work_units"], 3 * 2 * 19236)
            for entry in receipt["outputs"]:
                self.assertEqual(hashlib.sha256(base64.b64decode(entry["png_base64"])).hexdigest(), entry["png_sha256"])
            if recipe == "native":
                self.assertIn("s", receipt["probabilities"])
                self.assertIsNone(receipt["original_pairs"])
                self.assertEqual(receipt["aliases_add_calls"], 0)
            else:
                self.assertIn("p", receipt["probabilities"])
                self.assertIn("q", receipt["probabilities"])
                self.assertEqual(len(receipt["original_pairs"]), 3)
            HAND.record("hand", units=receipt["work_units"], actual_hand_renders=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
