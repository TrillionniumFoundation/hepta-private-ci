"""Original publisher-literal coverage is never mislabeled evidence sufficiency."""

import copy
import unittest

from locomo_literal_sufficiency_audit import census, literal_span


class AfterSealLiteralAuditTests(unittest.TestCase):
    def test_token_exactness_does_not_accept_discontinuous_fragments(self):
        self.assertTrue(literal_span("August 2024", "In August, 2024 I visited."))
        self.assertFalse(literal_span("August 2024", "August was in 2024."))
        self.assertFalse(literal_span("", "Something"))
        self.assertFalse(literal_span("present", "representation"))

    def test_missing_answer_literal_remains_unverified_semantics(self):
        import hashlib

        root = dict(
            sample_id="test-root",
            qa=[dict(question="Where?", answer="August 2024")],
            conversation={"session_1": [dict(text="I visited in August, 2024")]},
        )
        digest = hashlib.sha256(root["sample_id"].encode()).hexdigest()
        case = dict(qid="q", root_sha256=digest, original_question_index=0)
        plan = dict(fixed_cases=[dict(case, qid=f"q{i}") for i in range(8)])
        values = []
        for i in range(8):
            for arm in ("empty", "bm25_top3", "annotated_witness", "witness_lesion"):
                values.append(
                    dict(
                        qid=f"q{i}",
                        root_sha256=digest,
                        arm=arm,
                        question="Where?",
                        sources=[]
                        if arm == "empty"
                        else [dict(text="It was August 2024")],
                    )
                )
        original = dict(requests=values)
        result = census([root], plan, original)
        self.assertEqual(result["annotated_witness"], 8)
        self.assertEqual(result["empty"], 0)
        self.assertEqual(result["whole_conversation_literal"], 8)

    def test_changed_publisher_question_rejected(self):
        import hashlib

        root = dict(
            sample_id="root",
            qa=[dict(question="Where?", answer="here")],
            conversation={"session_1": [dict(text="here")]},
        )
        digest = hashlib.sha256(b"root").hexdigest()
        plan = dict(
            fixed_cases=[
                dict(qid=f"q{i}", root_sha256=digest, original_question_index=0)
                for i in range(8)
            ]
        )
        sealed = dict(
            requests=[
                dict(
                    qid=f"q{i}",
                    arm=a,
                    root_sha256=digest,
                    question="different",
                    sources=[dict(text="here")],
                )
                for i in range(8)
                for a in ("empty", "bm25_top3", "annotated_witness", "witness_lesion")
            ]
        )
        with self.assertRaisesRegex(ValueError, "question/lineage drift"):
            census([root], plan, sealed)


if __name__ == "__main__":
    unittest.main()
