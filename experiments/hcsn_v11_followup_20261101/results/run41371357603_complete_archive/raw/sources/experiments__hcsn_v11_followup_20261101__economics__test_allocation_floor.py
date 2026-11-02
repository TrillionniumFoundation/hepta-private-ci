"""Negative audit constraints; no synthetic successful hardware receipt."""

import unittest

from experiments.hcsn_v11_followup_20261101.economics.audit_ci import allocation_floor_holds


class AllocationFloorRefusals(unittest.TestCase):
    def test_zero_charge_rejects_touched_payload(self):
        nodes = {role: {"allocated_touched_bytes": size * 1024 * 1024}
                 for role, size in (("root", 8), ("child", 12), ("grandchild", 16), ("short_leaf", 48))}
        self.assertFalse(allocation_floor_holds(0, nodes))

    def test_one_byte_below_leaf_rejects(self):
        leaf_bytes = 48 * 1024 * 1024
        self.assertFalse(allocation_floor_holds(leaf_bytes - 1, {"short_leaf": {"allocated_touched_bytes": leaf_bytes}}))

    def test_missing_or_invalid_allocation_rejects(self):
        for nodes in ({}, {"leaf": {"allocated_touched_bytes": 0}}, {"leaf": {"allocated_touched_bytes": -1}},
                      {"leaf": {"allocated_touched_bytes": True}}):
            with self.subTest(nodes=nodes):
                self.assertFalse(allocation_floor_holds(0, nodes))

    def test_boolean_counter_rejects(self):
        self.assertFalse(allocation_floor_holds(True, {"leaf": {"allocated_touched_bytes": 1}}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
