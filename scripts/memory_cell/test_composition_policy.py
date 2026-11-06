"""Explicit mechanism fixtures for conditional learning and immutable consumption."""

import json
import unittest

from composition_evidence import make_case, sha
from composition_policy import GATE, choose, fit, load, readiness
from native import Document, Question, digest
from test_composition_evidence import row


class CompositionPolicyTests(unittest.TestCase):
    def fixture(self):
        case, label = make_case(
            row(),
            ["A different irrelevant statement."],
            "2026-10-10T00:00:00Z",
            "train",
        )
        plan = digest(case)
        gate = dict(
            development_ready=True,
            profile=GATE,
            plan_digest=plan,
            rows_digest=digest("fixture-not-model-execution"),
            reader_identity="a" * 64,
        )
        return case, label, plan, gate

    def test_gate_requires_complete_predeclared_census_and_real_reader_identity(self):
        questions = [str(i) for i in range(8)]
        arms = (
            "publisher_pair",
            "without_fact1",
            "without_fact2",
            "pair_reversed",
            "noise_before",
            "noise_after",
            "empty",
            "retrieved1",
            "retrieved2",
        )
        rows = [
            dict(
                question_id=q,
                arm=a,
                phase="capability",
                status="succeeded",
                f1=0.0 if a == "empty" else 1.0,
                receipt=dict(reader_identity="a" * 64),
            )
            for q in questions
            for a in arms
        ]
        self.assertTrue(
            readiness(rows, questions, "a" * 64, "b" * 64)["development_ready"]
        )
        with self.assertRaises(ValueError):
            readiness(rows[:-1], questions, "a" * 64, "b" * 64)
        rows[0]["f1"] = None
        with self.assertRaises(ValueError):
            readiness(rows, questions, "a" * 64, "b" * 64)
        rows[0]["f1"] = 1.0
        rows[0]["status"] = "failed"
        with self.assertRaises(ValueError):
            readiness(rows, questions, "a" * 64, "b" * 64)
        rows[0]["f1"] = None
        self.assertFalse(
            readiness(rows, questions, "a" * 64, "b" * 64)["development_ready"]
        )

    def test_actual_gradient_frozen_reload_and_revocation(self):
        case, label, plan, gate = self.fixture()
        artifact = fit(
            [case],
            {case["question"]["identity"]: label},
            gate=gate,
            plan_digest=plan,
            forbidden_roots=set(),
            steps=12,
        )
        self.assertGreater(artifact["parameter_delta_squared_norm"], 0)
        self.assertEqual(artifact["updates"], 12)
        raw = json.dumps(artifact, allow_nan=False).encode()
        weights = load(
            raw,
            expected_sha=sha(raw),
            plan_digest=plan,
            reader_identity="a" * 64,
            revoked=set(),
        )
        q = Question(**case["question"])
        docs = tuple(
            Document(**(d | {"assets": tuple(d["assets"])})) for d in case["originals"]
        )
        self.assertEqual(
            choose(q, docs, weights), choose(q, tuple(reversed(docs)), weights)
        )
        with self.assertRaises(ValueError):
            load(
                raw,
                expected_sha=sha(raw),
                plan_digest=plan,
                reader_identity="a" * 64,
                revoked={docs[0].root},
            )
        with self.assertRaises(ValueError):
            load(
                raw + b" ",
                expected_sha=sha(raw),
                plan_digest=plan,
                reader_identity="a" * 64,
                revoked=set(),
            )

    def test_no_learning_when_reader_fails_or_holdout_source_leaks(self):
        case, label, plan, gate = self.fixture()
        labels = {case["question"]["identity"]: label}
        with self.assertRaises(ValueError):
            fit(
                [case],
                labels,
                gate=gate | {"development_ready": False},
                plan_digest=plan,
                forbidden_roots=set(),
                steps=1,
            )
        with self.assertRaises(ValueError):
            fit(
                [case],
                labels,
                gate=gate,
                plan_digest=plan,
                forbidden_roots={case["originals"][0]["root"]},
                steps=1,
            )
        with self.assertRaises(ValueError):
            fit(
                [case | {"phase": "transfer"}],
                labels,
                gate=gate,
                plan_digest=plan,
                forbidden_roots=set(),
                steps=1,
            )

    def test_gold_answer_does_not_enter_policy_training(self):
        case, label, plan, gate = self.fixture()
        qid = case["question"]["identity"]
        a = fit(
            [case],
            {qid: label},
            gate=gate,
            plan_digest=plan,
            forbidden_roots=set(),
            steps=2,
        )
        b = fit(
            [case],
            {qid: label | {"answer": "changed", "combinedfact": "changed"}},
            gate=gate,
            plan_digest=plan,
            forbidden_roots=set(),
            steps=2,
        )
        self.assertEqual(a["weights"], b["weights"])
        self.assertEqual(a["losses"], b["losses"])


if __name__ == "__main__":
    unittest.main()
