import unittest
from sessions import normalize_sessions

class NativeSessionTests(unittest.TestCase):
    def test_identical_duplicates_are_one_source_not_more_training_evidence(self):
        turns = [{"role": "user", "content": "known history", "has_answer": True}]
        clean = [{"role": "user", "content": "known history", "has_answer": False}]
        result, audit = normalize_sessions([turns, clean], ["same", "same"], ["day", "day"])
        self.assertEqual(result, [(turns, "same", "day")])
        self.assertEqual(len(audit), 1)

    def test_conflicting_duplicate_or_misaligned_arrays_are_not_silently_repaired(self):
        turns = [{"role": "user", "content": "observed"}]
        with self.assertRaises(ValueError):
            normalize_sessions([turns, turns], ["same", "same"], ["first", "later"])
        with self.assertRaises(ValueError):
            normalize_sessions([turns], ["same"], [])
