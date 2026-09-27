"""Actual driver-boundary tests; fixtures are not Laya efficacy evidence."""
import math
import unittest
from unittest.mock import patch

import laya_retrieval as runtime


class Clock:
    def __init__(self):
        self.value = 10.0

    def __call__(self):
        return self.value


class Tokenizer:
    mask_token = "[MASK]"

    def __call__(self, value, **kwargs):
        return {"input_ids": value.split()}


class Predictor:
    tok = Tokenizer()
    cfg = {"max_len": 512, "head_max_len": 192}

    def __init__(self):
        self.calls = 0
        self.transform = lambda state, questions: None
        self.result = {"answers": {"source": {
            "choice": "source-a", "probabilities": {"abstain": 0.2, "source-a": 0.8}}}}

    def predict(self, state, questions, **kwargs):
        self.calls += 1
        self.transform(state, questions)
        return self.result


def request(operation="op-1"):
    return runtime.encoded({
        "format": runtime.FORMAT, "operation_id": operation, "scope": "workspace-a",
        "objective_digest": "a" * 64, "snapshot_digest": "b" * 64,
        "query": "What is the project name?",
        "candidates": [{"id": "source-a", "source_digest": "c" * 64,
                        "excerpt": "The project name is Hepta."}]})


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.model = Predictor()
        self.driver = runtime.RetrievalDriver(self.model, "d" * 64, 512, 192)
        self.patch = patch("laya_retrieval.time.monotonic", self.clock)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def invoke(self, operation="op-1", deadline=20.0):
        return self.driver.predict(request(operation), deadline)

    def assert_entered(self):
        with self.assertRaises(runtime.EnteredFailure) as raised:
            self.invoke()
        self.assertEqual(self.model.calls, 1)
        self.assertTrue(math.isfinite(raised.exception.elapsed_seconds))
        self.assertGreaterEqual(raised.exception.elapsed_seconds, 0)
        return raised.exception

    def test_predictor_cannot_rewrite_candidate_text(self):
        def mutate(state, questions):
            questions["source"]["criteria"]["source-a"] = "A substituted source."
        self.model.transform = mutate
        self.assert_entered()

    def test_predictor_cannot_rewrite_candidate_set_and_matching_output(self):
        def mutate(state, questions):
            criteria = questions["source"]["criteria"]
            criteria["forged"] = criteria.pop("source-a")
            self.model.result["answers"]["source"] = {
                "choice": "forged", "probabilities": {"abstain": 0.2, "forged": 0.8}}
        self.model.transform = mutate
        self.assert_entered()

    def test_predictor_cannot_reorder_admitted_tie_break(self):
        def mutate(state, questions):
            criteria = questions["source"]["criteria"]
            criteria["abstain"] = criteria.pop("abstain")
            self.model.result["answers"]["source"]["probabilities"] = {
                "abstain": 0.5, "source-a": 0.5}
        self.model.transform = mutate
        self.assert_entered()

    def test_predictor_cannot_rewrite_instruction(self):
        def mutate(state, questions):
            questions["source"]["instructions"] = "Choose an unrelated document."
        self.model.transform = mutate
        self.assert_entered()

    def test_returned_distribution_is_not_owned_by_predictor(self):
        result = self.invoke()
        self.model.result["answers"]["source"]["probabilities"]["source-a"] = 0.1
        self.assertEqual(result["prediction"], {"abstain": 0.2, "source-a": 0.8})
        receipt = result.pop("receipt_digest")
        self.assertEqual(receipt, runtime.digest(result))

    def test_deadline_is_rechecked_after_receipt_construction(self):
        original = runtime.digest
        def digest(value):
            result = original(value)
            if isinstance(value, dict) and "prediction" in value:
                self.clock.value = 20.0
            return result
        with patch("laya_retrieval.digest", side_effect=digest):
            self.assert_entered()

    def test_clock_regression_after_entry_is_not_published(self):
        self.model.transform = lambda state, questions: setattr(self.clock, "value", 9.0)
        self.assert_entered()

    def test_nonfinite_clock_after_entry_preserves_finite_failure_observation(self):
        self.model.transform = lambda state, questions: setattr(self.clock, "value", float("nan"))
        self.assert_entered()

    def test_invalid_clock_before_entry_is_rejected_without_predicting(self):
        for value in (float("nan"), float("inf"), True):
            with self.subTest(value=value):
                self.clock.value = value
                with self.assertRaises(runtime.Rejected):
                    self.invoke()
                self.assertEqual(self.model.calls, 0)

    def test_boolean_or_unrepresentable_deadline_rejected_before_model(self):
        self.clock.value = 0.0
        for deadline in (True, 1 << 4096):
            with self.subTest(deadline_type=type(deadline).__name__):
                with self.assertRaises(runtime.Rejected):
                    self.invoke(deadline=deadline)
                self.assertEqual(self.model.calls, 0)

    def test_late_result_is_entered_not_unused_and_lock_is_released(self):
        self.model.transform = lambda state, questions: setattr(self.clock, "value", 20.0)
        self.assert_entered()
        self.model.transform = lambda state, questions: None
        # A distinct operation, not replay of the indeterminate request. The
        # existing native owner remains responsible for durable reconciliation.
        result = self.invoke("op-2", deadline=30.0)
        self.assertEqual(result["operation_id"], "op-2")
        self.assertEqual(self.model.calls, 2)

    def test_original_exception_and_authority_boundary_are_preserved(self):
        original = RuntimeError("fixture model error")
        def fail(state, questions):
            raise original
        self.model.transform = fail
        raised = self.assert_entered()
        self.assertIs(raised.__cause__, original)

    def test_output_order_does_not_change_tie_policy(self):
        self.model.result["answers"]["source"]["probabilities"] = {
            "source-a": 0.5, "abstain": 0.5}
        result = self.invoke()
        self.assertEqual(result["selected"], "abstain")
        self.assertEqual(result["selected_propensity"], 1)
        self.assertFalse(result["authority"])
        self.assertFalse(result["calibration_verified"])
        self.assertIsNone(result["task_success"])


if __name__ == "__main__":
    unittest.main()
