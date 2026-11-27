"""Regressions for dangerous scope errors before a branch deletion is considered."""

import unittest

from audit_hia_scope import AncestryIndex, protection_decision


def sha(number):
    return f"{number:040x}"


class ProtectionTests(unittest.TestCase):
    def setUp(self):
        self.index = AncestryIndex(
            [sha(1), f"{sha(2)} {sha(1)}", f"{sha(3)} {sha(1)}", f"{sha(4)} {sha(3)} {sha(2)}"],
            [sha(2)],
        )

    def test_historical_pin_is_preserved_through_non_hia_merge_name(self):
        result = protection_decision("fix/rust-security", sha(4), set(), self.index)
        self.assertEqual(result, {
            "protected": True,
            "reasons": ["protected_pin_or_descendant"],
            "protected_ancestor_pins": [sha(2)],
        })

    def test_common_ancestor_does_not_protect_an_unrelated_sibling(self):
        result = protection_decision("fix/rust-security", sha(3), set(), self.index)
        self.assertEqual(result, {"protected": False, "reasons": [], "protected_ancestor_pins": []})

    def test_previously_protected_name_stays_protected_when_tip_changes(self):
        result = protection_decision("research/support", sha(3), {"research/support"}, self.index)
        self.assertTrue(result["protected"])
        self.assertEqual(result["reasons"], ["previously_protected_name"])

    def test_new_hia_name_is_protected_before_ancestry_is_classified(self):
        result = protection_decision("codex/HIA-new-root", sha(3), set(), self.index)
        self.assertTrue(result["protected"])
        self.assertEqual(result["reasons"], ["hia_branch_name"])

    def test_missing_tip_fails_closed(self):
        with self.assertRaises(KeyError):
            protection_decision("fix/new", sha(99), set(), self.index)

    def test_incomplete_parent_graph_fails_closed(self):
        with self.assertRaises(ValueError):
            AncestryIndex([f"{sha(2)} {sha(1)}"], [sha(2)])

    def test_missing_protected_seed_fails_closed(self):
        with self.assertRaises(ValueError):
            AncestryIndex([sha(1)], [sha(2)])


if __name__ == "__main__":
    unittest.main()
