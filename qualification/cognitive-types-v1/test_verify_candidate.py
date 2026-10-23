import unittest

from verify_candidate import verify_identity


class CandidateIdentityTests(unittest.TestCase):
    def test_actual_merge_uses_fetched_current_base_not_stale_trigger_metadata(self):
        verify_identity("synthetic-merge", "a" * 40, ["b" * 40, "c" * 40], "c" * 40, "b" * 40)

    def test_stale_base_and_wrong_head_are_not_accepted(self):
        for parents in (["d" * 40, "c" * 40], ["b" * 40, "d" * 40]):
            with self.assertRaises(ValueError):
                verify_identity("synthetic-merge", "a" * 40, parents, "c" * 40, "b" * 40)

    def test_exact_head_cannot_be_replaced_by_merge(self):
        with self.assertRaises(ValueError):
            verify_identity("exact-head", "a" * 40, [], "c" * 40, "b" * 40)
        verify_identity("exact-head", "c" * 40, [], "c" * 40, "b" * 40)


if __name__ == "__main__":
    unittest.main()
