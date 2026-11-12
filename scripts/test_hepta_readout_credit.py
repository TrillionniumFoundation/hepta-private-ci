"""Actual delayed linear updates, causal controls and fresh-process recovery."""

import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from hepta_cells.readout_credit import ARMS, ReadoutCredit
from hepta_cells.semantic import LocalHead, LocalObjective


def learner(arm="routed", **kwargs):
    return ReadoutCredit(
        LocalHead(np.array([[0.2, -0.1, 0.3], [0.1, 0.2, -0.2]]), np.zeros(3)),
        LocalObjective("mse", 3, "three-known-cell-outcomes"),
        cell_ids=("a", "b", "c"), owner_id="owner", version="v1",
        clock_id="monotonic:boot1", arm=arm, tau_us=10, learning_rate=0.1,
        **kwargs,
    )


def decision(model, name="one", at=2, x=(1.0, 2.0), mask=(True, True, True)):
    return model.decide(name, x, reference_logits=(0.1, -0.2, 0.3), mask=mask, at_us=at)


def request(model, row, now=12):
    return dict(decision_sha256=row["decision_sha256"], binding=model.binding,
                outcome_us=now-1, available_us=now, now_us=now)


class ReadoutCreditTests(unittest.TestCase):
    def test_trace_is_prelabel_feature_sensitivity_and_manual_update_matches(self):
        parent = learner()
        original = parent.record()
        queued, row = decision(parent)
        targets = np.array([1.0, 0.0, -1.0])
        child, receipt = queued.feedback("one", targets, **request(queued, row))
        gradient = 2 * (np.array([0.1, -0.2, 0.3]) - targets) / 3
        expected = parent.head.first - 0.1 * np.outer([1, 2], gradient) / math.e
        np.testing.assert_allclose(child.head.first, expected, rtol=0, atol=1e-16)
        np.testing.assert_allclose(child.head.bias, -0.1 * gradient / math.e)
        self.assertEqual(parent.record(), original)
        self.assertEqual(queued.updates, 0)
        self.assertFalse(queued.head.first.flags.writeable)
        self.assertFalse(child.head.first.flags.writeable)
        self.assertEqual(receipt["feature_trace_scalars"], 3)
        self.assertEqual(receipt["delay_us"], 10)
        self.assertEqual(row["features"], [1.0, 2.0])
        self.assertNotIn("targets", row)

    def test_routed_and_deranged_receive_identical_vector_and_mask(self):
        reports = {}
        for arm in ("routed", "shuffled", "scalar"):
            queued, row = decision(learner(arm), mask=(True, False, True))
            _, reports[arm] = queued.feedback("one", [1, 0, -1], **request(queued, row))
        a, b, scalar = (reports[k] for k in ("routed", "shuffled", "scalar"))
        self.assertEqual(a["teaching_sha256"], b["teaching_sha256"])
        self.assertEqual(a["teaching_vector"], b["teaching_vector"])
        self.assertEqual(a["delay_us"], b["delay_us"])
        self.assertEqual(sorted(a["applied_vector"]), sorted(b["applied_vector"]))
        self.assertEqual(b["permutation"], [2, 1, 0])
        self.assertEqual(b["applied_vector"][1], 0)
        self.assertNotEqual(scalar["applied_vector"], a["applied_vector"])
        self.assertEqual(scalar["applied_vector"][0], scalar["applied_vector"][2])

    def test_replay_sgd_recomputes_current_logits_on_same_pending_features(self):
        model, first = decision(learner("replay_sgd"))
        model, second = decision(model, name="two", at=3, x=(2, -1))
        model, _ = model.feedback("one", [1, 0, -1], **request(model, first))
        x, target = np.array([[2, -1]]), np.array([[0, 1, 2]])
        _, grad = model.objective.loss_and_gradient(model.head.predict(x), target)
        expected = model.head.gradient_step(x, grad, 0.1)
        updated, report = model.feedback("two", target[0], **request(model, second, now=15))
        self.assertEqual(updated.head.digest, expected.digest)
        self.assertEqual(report["work"]["replay_forward_mac"], 6)

    def test_frozen_consumes_feedback_without_parameter_or_optimizer_update(self):
        model, row = decision(learner("frozen"))
        child, report = model.feedback("one", [1, 0, -1], **request(model, row))
        self.assertEqual(child.head.digest, model.head.digest)
        self.assertEqual(child.updates, 0)
        self.assertEqual(report["applied_vector"], [0.0, 0.0, 0.0])
        self.assertEqual(len(child.record()["pending"]), 0)

    def test_future_payload_is_not_read_and_failure_preserves_original(self):
        model, row = decision(learner())
        before = model.record()
        kwargs = request(model, row)
        kwargs["now_us"] = 11
        with self.assertRaisesRegex(ValueError, "future"):
            model.feedback("one", object(), **kwargs)
        self.assertEqual(model.record(), before)

    def test_binding_and_decision_tampering_fail_before_any_update(self):
        model, row = decision(learner())
        before = model.record()
        for key in ("owner_id", "version", "clock_id"):
            kwargs = request(model, row)
            kwargs["binding"][key] = "other"
            with self.assertRaisesRegex(ValueError, "mismatch"):
                model.feedback("one", [1, 2, 3], **kwargs)
        kwargs = request(model, row)
        kwargs["decision_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "binding"):
            model.feedback("one", [1, 2, 3], **kwargs)
        self.assertEqual(model.record(), before)

    def test_exact_retry_replays_receipt_and_conflicting_feedback_is_refused(self):
        queued, row = decision(learner("shuffled"))
        kwargs = request(queued, row)
        child, receipt = queued.feedback("one", [1, 2, 3], **kwargs)
        original = child.record()
        retried, replay = child.feedback("one", [1, 2, 3], **kwargs)
        self.assertIs(retried, child)
        self.assertEqual(replay, receipt)
        self.assertEqual(child.record(), original)
        with self.assertRaisesRegex(ValueError, "differs"):
            child.feedback("one", [1, 2, 4], **kwargs)
        with self.assertRaisesRegex(ValueError, "reused"):
            decision(child, at=13)

    def test_queue_total_ledger_and_regression_bounds(self):
        model, row = decision(learner(max_pending=1, max_decisions=1))
        with self.assertRaisesRegex(ValueError, "capacity"):
            decision(model, name="two", at=3)
        child, _ = model.feedback("one", [1, 2, 3], **request(model, row))
        with self.assertRaisesRegex(ValueError, "capacity"):
            decision(child, name="two", at=13)
        with self.assertRaisesRegex(ValueError, "regressed"):
            decision(child, name="two", at=1)

    def test_long_idle_underflows_trace_without_nan_and_zero_delay_keeps_it(self):
        model, row = decision(learner())
        updated, report = model.feedback("one", [1, 2, 3], **request(model, row, now=10**9))
        self.assertEqual(report["decay"], 0.0)
        self.assertEqual(updated.head.digest, model.head.digest)
        kwargs = dict(decision_sha256=row["decision_sha256"], binding=model.binding,
                      outcome_us=2, available_us=2, now_us=2)
        _, report = model.feedback("one", [1, 2, 3], **kwargs)
        self.assertEqual(report["decay"], 1.0)

    def test_every_arm_checkpoint_restores_exact_pending_training_state(self):
        with tempfile.TemporaryDirectory() as directory:
            for arm in ARMS:
                model, first = decision(learner(arm))
                model, second = decision(model, name="two", at=3)
                model, _ = model.feedback("one", [1, 2, 3], **request(model, first))
                path = Path(directory) / f"{arm}.json"
                pin = model.checkpoint(path)
                restored = ReadoutCredit.restore_checkpoint(
                    path, expected_sha256=pin, expected_contract=model.contract)
                self.assertEqual(restored.record(), model.record())
                expected, _ = model.feedback("two", [2, 1, 0], **request(model, second, 15))
                actual, _ = restored.feedback("two", [2, 1, 0], **request(restored, second, 15))
                self.assertEqual((actual.head.digest, actual.updates, actual.record()["rng"]),
                                 (expected.head.digest, expected.updates, expected.record()["rng"]))

    def test_fresh_process_preserves_rng_and_next_update(self):
        model, first = decision(learner("shuffled"))
        model, second = decision(model, name="two", at=3)
        model, _ = model.feedback("one", [1, 2, 3], **request(model, first))
        kwargs = request(model, second, 15)
        expected, report = model.feedback("two", [2, 1, 0], **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            pin = model.checkpoint(path)
            script = """
import json, sys
from hepta_cells.readout_credit import ReadoutCredit
v=json.loads(sys.stdin.read())
m=ReadoutCredit.restore_checkpoint(v['path'], expected_sha256=v['pin'], expected_contract=v['contract'])
c,r=m.feedback('two',[2,1,0],**v['kwargs'])
print(json.dumps({'head':c.head.digest,'rng':c.record()['rng'],'permutation':r['permutation']}))
"""
            result = subprocess.run([sys.executable, "-c", script], text=True,
                                    cwd=Path(__file__).resolve().parent,
                                    input=json.dumps(dict(path=str(path), pin=pin, contract=model.contract, kwargs=kwargs)),
                                    capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), dict(head=expected.head.digest,
                          rng=expected.record()["rng"], permutation=report["permutation"]))

    def test_corrupt_bytes_and_cross_version_checkpoint_refused(self):
        model, _ = decision(learner())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            pin = model.checkpoint(path)
            changed = model.contract
            changed["version"] = "v2"
            with self.assertRaisesRegex(ValueError, "migration unsupported"):
                ReadoutCredit.restore_checkpoint(path, expected_sha256=pin, expected_contract=changed)
            path.write_bytes(path.read_bytes()+b" ")
            with self.assertRaisesRegex(ValueError, "pin mismatch"):
                ReadoutCredit.restore_checkpoint(path, expected_sha256=pin, expected_contract=model.contract)
            self.assertNotEqual(hashlib.sha256(path.read_bytes()).hexdigest(), pin)


if __name__ == "__main__":
    unittest.main()
