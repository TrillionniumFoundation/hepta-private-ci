import json
import tempfile
from pathlib import Path
from native import load
import unittest
from sessions import normalize_sessions, source_id


class NativeSessionTests(unittest.TestCase):
    def test_identical_duplicates_are_one_source_not_more_training_evidence(self):
        turns = [{"role": "user", "content": "known history", "has_answer": True}]
        clean = [{"role": "user", "content": "known history", "has_answer": False}]
        result, audit = normalize_sessions(
            [turns, clean], ["same", "same"], ["day", "day"]
        )
        self.assertEqual(result, [(turns, "same", "day")])
        self.assertEqual(len(audit), 1)

    def test_conflicting_duplicate_or_misaligned_arrays_are_not_silently_repaired(self):
        turns = [{"role": "user", "content": "observed"}]
        with self.assertRaises(ValueError):
            normalize_sessions(
                [turns, [{"role": "user", "content": "changed"}]],
                ["same", "same"],
                ["first", "later"],
            )
        with self.assertRaises(ValueError):
            normalize_sessions([turns], ["same"], [])

    def test_conflicting_versions_are_preserved_and_never_chosen_by_answer_flag(self):
        first = [{"role": "user", "content": "Berlin", "has_answer": True}]
        second = [{"role": "user", "content": "Tokyo", "has_answer": False}]
        rows, audit = normalize_sessions(
            [first, second, first],
            ["s", "s", "s"],
            ["day", "day", "day"],
            conflict_policy="retain-versioned",
        )
        self.assertEqual(len(rows), 2)
        self.assertTrue(
            all(identity.startswith("s~version:") for _, identity, _ in rows)
        )
        self.assertEqual({r[0][0]["content"] for r in rows}, {"Berlin", "Tokyo"})
        self.assertEqual(len(audit), 2)
        first[0]["has_answer"] = False
        second[0]["has_answer"] = True
        changed, _ = normalize_sessions(
            [first, second, first],
            ["s", "s", "s"],
            ["day", "day", "day"],
            conflict_policy="retain-versioned",
        )
        self.assertEqual([r[1] for r in rows], [r[1] for r in changed])

    def test_versioned_identities_do_not_depend_on_transport_order(self):
        a = [{"role": "user", "content": "first"}]
        b = [{"role": "user", "content": "second"}]
        x, _ = normalize_sessions(
            [a, b], ["s", "s"], ["day", "later"], conflict_policy="retain-versioned"
        )
        y, _ = normalize_sessions(
            [b, a], ["s", "s"], ["later", "day"], conflict_policy="retain-versioned"
        )
        self.assertEqual(
            sorted((r[1], r[2]) for r in x), sorted((r[1], r[2]) for r in y)
        )

    def test_type_and_role_validation_are_explicit(self):
        for sessions, ids, dates in [
            (None, [], []),
            ([[{}]], ["s"], ["day"]),
            ([], [], []),
        ]:
            with self.assertRaises(ValueError):
                normalize_sessions(sessions, ids, dates)

    def test_repeated_filler_at_different_dates_is_preserved_not_independent(self):
        turns = [{"role": "user", "content": "observed"}]
        rows, audit = normalize_sessions(
            [turns, turns], ["same", "same"], ["first", "later"]
        )
        reverse, _ = normalize_sessions(
            [turns, turns], ["same", "same"], ["later", "first"]
        )
        self.assertEqual(rows, list(reversed(reverse)))
        self.assertEqual(len({sid for _, sid, _ in rows}), 2)
        self.assertEqual({source_id(sid) for _, sid, _ in rows}, {"same"})
        self.assertEqual(len(audit), 2)
        sample = dict(
            question_id="a",
            question_type="temporal",
            question="When?",
            answer="WITHHELD",
            question_date="2025",
            haystack_session_ids=["same", "same"],
            haystack_dates=["first", "later"],
            haystack_sessions=[turns, turns],
            answer_session_ids=["same"],
        )
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "data.json"
            path.write_text(json.dumps([sample]))
            benchmark = load(path, "longmemeval")
            self.assertEqual(len(benchmark.documents), 2)
            self.assertEqual(len({doc.root for doc in benchmark.documents}), 1)
            self.assertEqual(benchmark.targets["longmemeval:a"].unresolved_evidence, ())
            self.assertEqual(
                {source_id(doc.identity) for doc in benchmark.documents},
                set(benchmark.targets["longmemeval:a"].evidence),
            )
            self.assertNotIn("WITHHELD", str(benchmark.documents))
