import unittest

from control_engineering_v2.capacity_policy import (
    SQLiteCapacityObservation,
    SQLiteCapacityPolicy,
)
from control_engineering_v2.production_composition import EngineeringControlProductionProduct


class ProductionCompositionTests(unittest.TestCase):
    def test_capacity_projection_does_not_grant_authority(self):
        decision = EngineeringControlProductionProduct.evaluate_capacity(
            SQLiteCapacityPolicy("target", 100, 100, 100, 10, 10, 10, 10, 80),
            SQLiteCapacityObservation(1, 1, 1, 1, 1, 1, 1),
        )
        self.assertTrue(decision.within_hard_limits)
        self.assertFalse(decision.runtime_authority)
        self.assertFalse(decision.release_authority)


if __name__ == "__main__":
    unittest.main()
