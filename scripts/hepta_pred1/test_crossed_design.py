"""Factor attribution, sealed-boundary and information-ablation checks."""

import copy
import unittest

import numpy as np

from .crossed_design import (
    SEALED_OR_EXPOSED_SEEDS,
    decompose,
    design_cells,
    registered_config,
    transform_inputs,
    validate_config,
)
from .simulator import generate_dataset


class CrossedDesignTests(unittest.TestCase):
    def test_complete_grid_retains_interactions_and_is_order_invariant(self):
        levels = np.array([-1.0, 0.0, 1.0])
        d, i, o = levels[:, None, None], levels[None, :, None], levels[None, None, :]
        grid = 2 * d + 3 * i + 0.5 * o + 1.2 * d * i + 0.8 * d * i * o
        report = decompose(grid)
        expected = {
            "data": 8 / 3,
            "init": 6.0,
            "order": 1 / 6,
            "data:init": 0.64,
            "data:order": 0.0,
            "init:order": 0.0,
            "data:init:order": 0.64 * 8 / 27,
        }
        for name, value in expected.items():
            self.assertAlmostEqual(report["mean_squared_components"][name], value)
        self.assertAlmostEqual(sum(expected.values()), report["finite_grid_variance"])
        permuted = decompose(grid[::-1, [2, 0, 1], ::-1])
        for name, value in expected.items():
            self.assertAlmostEqual(permuted["mean_squared_components"][name], value)

    def test_missing_cells_cannot_be_dropped_or_imputed(self):
        for grid in (np.zeros((1, 2, 2)), np.zeros((2, 2)), np.full((2, 2, 2), np.nan)):
            with self.assertRaises(ValueError):
                decompose(grid)
        self.assertTrue(
            all(
                v is None
                for v in decompose(np.zeros((2, 2, 2)))[
                    "fraction_of_grid_variance"
                ].values()
            )
        )

    def test_sealed_seeds_and_confirmation_switches_are_rejected(self):
        original = registered_config()
        for seed in SEALED_OR_EXPOSED_SEEDS:
            config = copy.deepcopy(original)
            config["data_seeds"][0] = seed
            with self.assertRaisesRegex(ValueError, "sealed/exposed"):
                validate_config(config)
        config = copy.deepcopy(original)
        config["confirm_episodes"] = 1
        with self.assertRaisesRegex(ValueError, "train/dev"):
            validate_config(config)
        config = copy.deepcopy(original)
        config["init_seeds"][0] = config["data_seeds"][0]
        with self.assertRaisesRegex(ValueError, "overlap"):
            design_cells(config)

    def test_seed_boolean_duplicate_and_bad_rates_cannot_change_design(self):
        for key, value in (
            ("data_seeds", [True, 2]),
            ("order_seeds", [9991, 9991]),
            ("epochs", True),
            ("learning_rate", np.inf),
        ):
            config = registered_config()
            config[key] = value
            with self.assertRaises(ValueError):
                design_cells(config)
        config = registered_config()
        config["cost_profile"]["head_work"] = -1
        with self.assertRaises(ValueError):
            validate_config(config)

    def test_actions_removed_from_both_history_and_candidates_without_mutation(self):
        data = generate_dataset(8, 11001, "dev", 4)
        original_x, original_q = data.x.copy(), data.query.copy()
        x, q, reset = transform_inputs(data.x, data.query, "gru_no_action")
        self.assertFalse(reset)
        self.assertFalse(x[:, :, :3].any())
        self.assertFalse(q[:, :4].any())
        np.testing.assert_array_equal(q[:, 4:], original_q[:, 4:])
        np.testing.assert_array_equal(data.x, original_x)
        np.testing.assert_array_equal(data.query, original_q)

    def test_no_time_cannot_read_lag_slot_or_explicit_clock(self):
        x = np.zeros((1, 4, 16))
        q = np.zeros((1, 7))
        x[:, :, 5], x[:, :, 6] = -1, 1
        x[:, :, 13:15] = 0.3
        shifted = x.copy()
        shifted[:, :, 5:7] = 0
        shifted[:, :, 11], shifted[:, :, 12] = -1, 1
        shifted[:, :, 13:15] = 0.9
        left = transform_inputs(x, q, "gru_no_time")[0]
        right = transform_inputs(shifted, q, "gru_no_time")[0]
        np.testing.assert_array_equal(left, right)
        self.assertFalse(left[:, :, 7:15].any())
        self.assertTrue(transform_inputs(x, q, "gru_reset")[2])


if __name__ == "__main__":
    unittest.main()
