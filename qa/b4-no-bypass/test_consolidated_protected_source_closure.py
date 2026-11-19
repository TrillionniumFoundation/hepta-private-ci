"""Consolidation must preserve every independent guard and authority bit."""

from copy import deepcopy
import unittest

from protected_record_support import require_protected_record


class ConsolidatedProtectedSourceClosureTests(unittest.TestCase):
    def setUp(self):
        self.original = {
            "path": "owner.rs", "required": ["original"], "forbidden": ["bypass"],
            "external_effect": False,
            "required_order": [["before", "effect", "after"]],
            "required_function_order": [{
                "function": "fn commit(", "sequence": ["check", "write", "verify"],
                "top_level": ["check"],
            }],
        }
        self.combined = deepcopy(self.original)
        self.combined["required"].append("other owner")
        self.combined["required_function_order"][0]["sequence"].insert(1, "other check")

    def test_stricter_union_retains_the_complete_independent_contract(self):
        self.assertIs(require_protected_record(self.original, [self.combined]), self.combined)

    def test_omitted_marker_and_reordered_check_are_rejected(self):
        mutations = []
        changed = deepcopy(self.combined)
        changed["forbidden"] = []
        mutations.append(changed)
        changed = deepcopy(self.combined)
        changed["required_order"] = [["effect", "before", "after"]]
        mutations.append(changed)
        for changed in mutations:
            with self.subTest(changed=changed), self.assertRaises(AssertionError):
                require_protected_record(self.original, [changed])

    def test_wrong_scope_nested_guard_and_authority_change_are_rejected(self):
        for field, replacement in (("function", "fn unrelated("), ("top_level", [])):
            changed = deepcopy(self.combined)
            changed["required_function_order"][0][field] = replacement
            with self.subTest(field=field), self.assertRaises(AssertionError):
                require_protected_record(self.original, [changed])
        changed = deepcopy(self.combined)
        changed["external_effect"] = True
        with self.assertRaises(AssertionError):
            require_protected_record(self.original, [changed])

    def test_duplicate_records_cannot_mask_an_incomplete_union(self):
        with self.assertRaises(AssertionError):
            require_protected_record(self.original, [self.combined, self.original])


if __name__ == "__main__":
    unittest.main()
