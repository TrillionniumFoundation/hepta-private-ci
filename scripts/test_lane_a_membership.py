"""Order-independent Lane A ownership without accepting missing or duplicate rows."""

import itertools
import unittest

from lane_a_foundation_core import EXPECTED_MODULES, has_exact_module_membership


class ModuleMembershipTests(unittest.TestCase):
    def test_all_registered_owner_permutations_are_equivalent(self):
        for permutation in itertools.permutations(EXPECTED_MODULES):
            self.assertTrue(has_exact_module_membership(list(permutation)))

    def test_missing_unknown_duplicate_and_malformed_owners_are_rejected(self):
        for invalid in (
            EXPECTED_MODULES[:-1],
            [*EXPECTED_MODULES, "unregistered.owner"],
            [*EXPECTED_MODULES[:-1], EXPECTED_MODULES[0]],
            [*EXPECTED_MODULES[:-1], None],
            [*EXPECTED_MODULES[:-1], {}],
            {"modules": EXPECTED_MODULES},
            None,
        ):
            with self.subTest(invalid=invalid):
                self.assertFalse(has_exact_module_membership(invalid))


if __name__ == "__main__":
    unittest.main()
