"""Published empty strings are observations, not malformed or missing values."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from native import digest, load
from sessions import normalize_sessions


class NativeEmptyTurnTests(unittest.TestCase):
    def sample(self):
        return dict(
            question_id="q",
            question_type="multi-session",
            question="Where?",
            question_date="2026/01/02",
            answer="GOLD_SENTINEL",
            answer_session_ids=["s"],
            haystack_session_ids=["s"],
            haystack_dates=["2026/01/01"],
            haystack_sessions=[
                [
                    {"role": "user", "content": ""},
                    {"role": "assistant", "content": "Actual response"},
                    {"role": "user", "content": " \n\t"},
                ]
            ],
        )

    def read(self, sample, **kwargs):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "native.json"
            raw = json.dumps([sample]).encode()
            path.write_bytes(raw)
            result = load(
                path, "longmemeval", hashlib.sha256(raw).hexdigest(), **kwargs
            )
            self.assertEqual(path.read_bytes(), raw)
            return result

    def test_preserves_empty_bytes_positions_roles_and_complete_history(self):
        sample = self.sample()
        original = copy.deepcopy(sample)
        result = self.read(sample)
        self.assertEqual(sample, original)
        self.assertEqual(result.ingress_failures, {})
        self.assertEqual(
            result.documents[0].content,
            "user: \nassistant: Actual response\nuser:  \n\t",
        )
        self.assertEqual(
            result.documents[0].root,
            "session:"
            + digest(
                [
                    ("user", ""),
                    ("assistant", "Actual response"),
                    ("user", " \n\t"),
                ]
            ),
        )
        self.assertEqual([x["turn_position"] for x in result.ingress_issues], [0, 2])
        self.assertNotIn("GOLD_SENTINEL", str(result.documents))
        self.assertEqual(result.targets["longmemeval:q"].unresolved_evidence, ())

    def test_legacy_profile_reproduces_failure_without_relabelling_old_runs(self):
        sample = self.sample()
        with self.assertRaises(ValueError):
            self.read(sample, empty_turns="reject")
        legacy = self.read(
            sample,
            empty_turns="reject",
            invalid_history="quarantine-question",
            allow_unresolved_evidence=True,
        )
        self.assertEqual(len(legacy.questions), 1)
        self.assertEqual(legacy.documents, ())
        self.assertEqual(set(legacy.ingress_failures), {"longmemeval:q"})
        self.assertEqual(
            legacy.ingress_failures["longmemeval:q"]["history_digest"],
            digest(
                (
                    sample["haystack_sessions"],
                    sample["haystack_session_ids"],
                    sample["haystack_dates"],
                )
            ),
        )

    def test_null_wrong_types_and_missing_content_remain_invalid(self):
        for value in (None, [], {}, 0, False):
            with self.subTest(value=value):
                sample = self.sample()
                sample["haystack_sessions"][0][0]["content"] = value
                with self.assertRaises(ValueError):
                    self.read(sample)
        sample = self.sample()
        del sample["haystack_sessions"][0][0]["content"]
        with self.assertRaises(ValueError):
            self.read(sample)

    def test_empty_policy_does_not_relax_roles_lengths_or_query_validation(self):
        for change in ("role", "long", "question", "policy"):
            sample = self.sample()
            kwargs = {}
            if change == "role":
                sample["haystack_sessions"][0][0]["role"] = "unknown"
            elif change == "long":
                sample["haystack_sessions"][0][0]["content"] = " " * 1000001
            elif change == "question":
                sample["question"] = ""
            else:
                kwargs["empty_turns"] = "impute"
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.read(sample, **kwargs)

    def test_empty_turn_changes_identity_and_cannot_merge_with_missing_turn(self):
        turns = self.sample()["haystack_sessions"][0]
        with self.assertRaises(ValueError):
            normalize_sessions(
                [turns, turns[1:]], ["s", "s"], ["day", "day"], empty_turns="preserve"
            )
        rows, _ = normalize_sessions(
            [turns, turns[1:]],
            ["s", "s"],
            ["day", "day"],
            empty_turns="preserve",
            conflict_policy="retain-versioned",
        )
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0][1], rows[1][1])

    def test_gold_annotation_does_not_choose_or_fill_an_empty_message(self):
        sample = self.sample()
        first = self.read(sample)
        sample["answer"] = "POISONED_GOLD"
        sample["haystack_sessions"][0][0]["has_answer"] = True
        second = self.read(sample)
        self.assertEqual(first.documents, second.documents)
        self.assertEqual(first.ingress_issues, second.ingress_issues)


if __name__ == "__main__":
    unittest.main()
