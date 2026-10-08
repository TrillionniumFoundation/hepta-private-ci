import json
import tempfile
import unittest
from pathlib import Path

from native import load
from sessions import normalize_sessions, source_id


class NativeSessionTests(unittest.TestCase):
    def test_identical_duplicates_are_one_source_not_more_training_evidence(self):
        turns = [{"role": "user", "content": "known history", "has_answer": True}]
        clean = [{"role": "user", "content": "known history", "has_answer": False}]
        result, audit = normalize_sessions([turns, clean], ["same", "same"], ["day", "day"])
        self.assertEqual(result, [(turns, "same", "day")])
        self.assertEqual(len(audit), 1)

    def test_repeated_filler_at_different_dates_is_preserved_not_independent(self):
        turns = [{"role": "user", "content": "observed"}]
        rows, audit = normalize_sessions([turns, turns], ["same", "same"], ["first", "later"])
        reverse, _ = normalize_sessions([turns, turns], ["same", "same"], ["later", "first"])
        self.assertEqual(rows, list(reversed(reverse)))
        self.assertEqual(len({sid for _, sid, _ in rows}), 2)
        self.assertEqual({source_id(sid) for _, sid, _ in rows}, {"same"})
        self.assertEqual(len(audit), 2)
        sample = dict(question_id="a", question_type="temporal", question="When?",
                      answer="WITHHELD", question_date="2025", haystack_session_ids=["same", "same"],
                      haystack_dates=["first", "later"], haystack_sessions=[turns, turns],
                      answer_session_ids=["same"])
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "data.json"
            path.write_text(json.dumps([sample]))
            benchmark = load(path, "longmemeval")
            self.assertEqual(len(benchmark.documents), 2)
            self.assertEqual(len({doc.root for doc in benchmark.documents}), 1)
            self.assertEqual(benchmark.targets["longmemeval:a"].unresolved_evidence, ())
            self.assertEqual({source_id(doc.identity) for doc in benchmark.documents},
                             set(benchmark.targets["longmemeval:a"].evidence))
            self.assertNotIn("WITHHELD", str(benchmark.documents))

    def test_changed_content_reserved_identity_and_misalignment_reject(self):
        turns = [{"role": "user", "content": "observed"}]
        changed = [{"role": "user", "content": "changed"}]
        for args in (([turns, changed], ["same", "same"], ["first", "later"]),
                     ([turns], ["same"], []), ([turns], ["same#occ:fake"], ["day"]),
                     (None, [], [])):
            with self.assertRaises(ValueError):
                normalize_sessions(*args)
