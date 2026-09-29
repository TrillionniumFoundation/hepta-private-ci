"""Binary contract and real process rejection tests; predictors are synthetic."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from hepta_retrieval_wire import decode_reply, encode_request, WireError
from laya_binary import BinaryRetrievalDriver, OwnerDeadline, probability_ppm
from laya_retrieval import EnteredFailure, Rejected, digest
from test_laya_retrieval import Tokenizer


class Clock:
    mono = 10.0
    wall = 1000.0

    def deadline(self, unix_ms=1060000):
        return OwnerDeadline.start(unix_ms, wall_clock=lambda: self.wall, monotonic_clock=lambda: self.mono)


class Predictor:
    tok = Tokenizer()
    cfg = {"max_len": 512, "head_max_len": 192}

    def __init__(self):
        self.calls = 0
        self.change = lambda result, questions: result
        self.questions = None

    def predict(self, state, questions, **kwargs):
        self.calls += 1
        self.questions = copy.deepcopy(questions)
        keys = list(questions["source"]["criteria"])
        probabilities = {key: (0.7 if key == keys[1] else 0.3 / (len(keys) - 1)) for key in keys}
        result = {"answers": {"source": {"choice": keys[1], "probabilities": probabilities}},
                  "usage": {"input_tokens": 37, "output_tokens": 0}}
        return self.change(result, questions)


def request():
    return {"operation_id": "op.1", "workspace_id": "workspace/1", "generation": 3,
            "objective_digest": "1" * 64, "observation_digest": "2" * 64,
            "bundle_digest": "3" * 64, "deadline_ms": 1060000, "query": "find alpha",
            "sources": [{"source_id": name, "revision": index + 1, "content_sha256": hashlib.sha256(text.encode()).hexdigest(), "text": text}
                        for index, (name, text) in enumerate([("source.z", "beta"), ("source.a", "alpha")])]}


class BinaryTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.model = Predictor()
        self.driver = BinaryRetrievalDriver(self.model, "3" * 64)
        self.patch = patch("laya_retrieval.time.monotonic", lambda: self.clock.mono)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def predict(self, value=None, deadline=None):
        return self.driver.predict(encode_request(request() if value is None else value),
                                   self.clock.deadline() if deadline is None else deadline)

    def test_real_codec_complete_binding_and_canonical_probability_order(self):
        result = self.predict()
        reply = decode_reply(result.wire, encode_request(request()))
        self.assertEqual(reply["prediction_ppm"], [150000, 700000, 150000])
        self.assertEqual(reply["input_tokens"], 37)
        self.assertEqual(result.observation["candidate_order"], ["source.a", "source.z"])
        self.assertEqual(result.observation["source_revisions"], [2, 1])
        self.assertFalse(result.observation["authority"])
        self.assertFalse(result.observation["source_currentness_verified"])
        self.assertIsNone(result.observation["task_success"])
        self.assertEqual(self.model.calls, 1)
        self.assertEqual(self.model.questions["source"]["criteria"]["source-000"], "alpha")
        observed = dict(result.observation)
        receipt = observed.pop("receipt_digest")
        self.assertEqual(receipt, digest(observed))

    def test_source_order_and_revision_remain_in_original_wire_binding(self):
        original = self.predict()
        changed = request(); changed["sources"].reverse()
        replay = self.predict(changed)
        self.assertNotEqual(original.observation["request_sha256"], replay.observation["request_sha256"])
        self.assertEqual(decode_reply(original.wire, encode_request(request()))["prediction_ppm"],
                         decode_reply(replay.wire, encode_request(changed))["prediction_ppm"])
        changed["sources"][0]["revision"] += 1
        with self.assertRaises(WireError):
            decode_reply(replay.wire, encode_request(changed))

    def test_wrong_bundle_and_expired_or_rebound_deadline_never_infer(self):
        value = request(); value["bundle_digest"] = "4" * 64
        with self.assertRaises(Rejected): self.predict(value)
        budget = self.clock.deadline(); self.clock.mono += 61
        with self.assertRaises(Rejected): self.predict(deadline=budget)
        self.clock.mono = 10
        value = request(); value["deadline_ms"] += 1
        with self.assertRaises(Rejected): self.predict(value, self.clock.deadline())
        self.assertEqual(self.model.calls, 0)

    def test_loading_uses_original_budget_and_clock_changes_cannot_extend_it(self):
        for clock, delta in [("mono", 61), ("wall", 61), ("wall", -1), ("mono", -1)]:
            self.clock.mono, self.clock.wall = 10, 1000
            budget = self.clock.deadline()
            setattr(self.clock, clock, getattr(self.clock, clock) + delta)
            with self.subTest(clock=clock, delta=delta), self.assertRaises(Rejected):
                self.predict(deadline=budget)
        self.assertEqual(self.model.calls, 0)

    def test_wall_expiry_after_inference_is_entered_failure(self):
        def late(result, questions):
            self.clock.wall += 61
            return result
        self.model.change = late
        with self.assertRaises(EnteredFailure): self.predict()
        self.assertEqual(self.model.calls, 1)

    def test_missing_or_false_usage_is_not_fabricated_zero_cost(self):
        for usage in [None, {}, {"input_tokens": True, "output_tokens": 0},
                      {"input_tokens": 600, "output_tokens": 0}, {"input_tokens": 37, "output_tokens": 1}]:
            def altered(result, questions):
                result["usage"] = usage
                return result
            self.model.change = altered
            with self.subTest(usage=usage), self.assertRaises(EnteredFailure): self.predict()
        self.assertEqual(self.model.calls, 5)

    def test_input_mutation_after_model_entry_is_rejected(self):
        def altered(result, questions):
            questions["source"]["criteria"]["source-000"] = "changed evidence"
            return result
        self.model.change = altered
        with self.assertRaises(EnteredFailure): self.predict()
        self.assertEqual(self.model.calls, 1)

    def test_binary_capacity_rejects_before_model_and_recovers(self):
        self.driver._lock.acquire()
        with self.assertRaises(Rejected): self.predict()
        self.assertEqual(self.model.calls, 0)
        self.driver._lock.release()
        self.predict()
        self.assertEqual(self.model.calls, 1)

    def test_ppm_rounding_normalizes_sdk_rounding_without_changing_tie_order(self):
        self.assertEqual(probability_ppm([0.3333, 0.3333, 0.3333]), [333334, 333333, 333333])
        for bad in [[0, 0], [True, 0], [float("nan"), 1], [-0.1, 1.1], [0.1, 0.1]]:
            with self.subTest(bad=bad), self.assertRaises(Rejected): probability_ppm(bad)


class ProcessRejectionTests(unittest.TestCase):
    def run_leaf(self, raw, pins="/nonexistent/pins"):
        return subprocess.run([sys.executable, str(Path(__file__).with_name("laya_binary.py")),
                               "--checkpoint", "/nonexistent/model", "--pins", pins],
                              input=raw, capture_output=True, timeout=5, check=False)

    def test_real_process_malformed_and_expired_never_access_model_or_emit_reply(self):
        for raw in [b"not a model request", encode_request({**request(), "deadline_ms": 1})]:
            result = self.run_leaf(raw)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b"")
            self.assertNotIn(b"ModuleNotFoundError", result.stderr)
            self.assertNotIn(b"FileNotFoundError", result.stderr)

    def test_real_process_wrong_bundle_rejects_before_model_import(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pins.json"
            path.write_text(json.dumps({"not": "the admitted bundle"}))
            raw = encode_request({**request(), "deadline_ms": int(time.time() * 1000) + 60000})
            result = self.run_leaf(raw, str(path))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b"")
            self.assertIn(b"wrong pinned bundle before load", result.stderr)
            self.assertNotIn(b"ModuleNotFoundError", result.stderr)


if __name__ == "__main__":
    unittest.main()
