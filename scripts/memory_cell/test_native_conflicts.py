import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from native import load


class ConflictingNativeTests(unittest.TestCase):
    def test_native_adapter_keeps_variants_but_cannot_claim_ambiguous_support(self):
        sample = {
            "question_id": "a",
            "question_type": "knowledge-update",
            "question": "Where?",
            "answer": "GOLD_ANSWER_SENTINEL",
            "question_date": "2025/01/01",
            "haystack_session_ids": ["same", "same", "other"],
            "haystack_dates": ["2024/01/01"] * 3,
            "haystack_sessions": [
                [{"role": "user", "content": v}]
                for v in ("Berlin", "Tokyo", "elsewhere")
            ],
            "answer_session_ids": ["same"],
        }
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / "data.json"
            file.write_text(json.dumps([sample]))
            with self.assertRaises(ValueError):
                load(file, "longmemeval")
            b = load(
                file,
                "longmemeval",
                session_conflicts="retain-versioned",
                allow_unresolved_evidence=True,
            )
            self.assertEqual(len(b.documents), 3)
            target = b.targets[b.questions[0].identity]
            self.assertEqual(target.unresolved_evidence, ("longmemeval:a/same",))
            self.assertEqual(target.evidence, target.unresolved_evidence)
            self.assertTrue(
                set(target.evidence).isdisjoint(d.identity for d in b.documents)
            )
            self.assertNotEqual(b.documents[0].root, b.documents[1].root)
            self.assertEqual(b.documents[0].session, b.documents[1].session)
            self.assertEqual(b.documents[0].session, "same")
            self.assertNotIn(
                "GOLD_ANSWER", json.dumps([asdict(d) for d in b.documents])
            )
            self.assertIn("versioned_identities", b.ingress_issues[0])
            # Another question containing only one of the versions is the same
            # root-connected family, not fresh independent training support.
            second = dict(
                sample,
                question_id="b",
                haystack_session_ids=["same"],
                haystack_dates=["2024/01/01"],
                haystack_sessions=sample["haystack_sessions"][:1],
            )
            file.write_text(json.dumps([sample, second]))
            b = load(
                file,
                "longmemeval",
                session_conflicts="retain-versioned",
                allow_unresolved_evidence=True,
            )
            self.assertEqual(len(set(b.families.values())), 1)
