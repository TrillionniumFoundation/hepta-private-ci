"""Behavioral checks for shared information and intentional channel ablations."""

from copy import deepcopy
import unittest

import numpy as np

from experiments.continuous_boundary_flow.math_model import (
    TaskSpec,
    build_model,
    solve_dp,
)
from experiments.continuous_boundary_flow.native.adapter import Q
from .common import CANDIDATES
from .features import FeatureMap, native_rows


class Poison(dict):
    def __getitem__(self, key):
        raise AssertionError("A raw boundary arm accessed a DP-derived field")


class FeatureContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = TaskSpec(
            mu=-0.2,
            sigma=0.4,
            dt=0.5,
            horizon=12,
            discount=0.05,
            production_rate=1,
            failure_cost=2.5,
            maintenance_cost=0.35,
            maintenance_reset=1.3,
            failure_reset=0.9,
            initial=1,
        )
        model = build_model(spec, n_grid=64, x_max=4.8)
        cls.context = {"model": model, "dp": solve_dp(model)}

    def values(self, arm, context=None, weights=None):
        mapper = FeatureMap(context or self.context, arm, CANDIDATES[1], weights)
        return mapper.step(
            np.array([2, 14, 25]),
            8,
            np.array([0.0, 1.0, 0.0]),
            np.array([0.1, 0.3, 0.5]),
            np.array([0.0, 0.0, 1.0]),
        )

    def test_raw_boundary_arms_do_not_read_dp(self):
        context = {"model": self.context["model"], "dp": Poison()}
        for arm, weights in (
            ("fixed_margin", None),
            ("learned_margin", np.r_[0.65, np.zeros(19)]),
        ):
            values, _ = self.values(arm, context, weights)
            self.assertTrue(np.isfinite(values).all())
            np.testing.assert_array_equal(values[:, 1], np.full(3, 8 / 16))

    def test_channel_masks_and_common_information(self):
        full, reset = self.values("dual_flow")
        for arm, visible in (
            ("value_margin", ()),
            ("value_call", (12,)),
            ("generic_gru", (12, 13, 14)),
            ("dual_event", (12, 13, 14)),
            ("elman_mlp", (12, 13, 14)),
            ("native_sparse", (12, 13, 14)),
        ):
            values, actual_reset = self.values(arm)
            np.testing.assert_array_equal(values[:, :12], full[:, :12])
            np.testing.assert_array_equal(values[:, 15:], full[:, 15:])
            for index in (12, 13, 14):
                np.testing.assert_array_equal(
                    values[:, index],
                    full[:, index] if index in visible else np.zeros(3),
                )
            expected = (
                np.array([0.0, 1.0, 0.0])
                if arm == "dual_event"
                else np.zeros(3)
                if arm in {"elman_mlp", "native_sparse"}
                else reset
            )
            np.testing.assert_array_equal(actual_reset, expected)

    def test_native_transport_preserves_all_eighteen_inputs(self):
        values, _ = self.values("native_sparse")
        rows = native_rows(values)
        for x, row in zip(values, rows):
            raw = np.asarray(row["raw_q24"]) / Q
            reconstructed = np.r_[raw[:15], row["continuous"]["flow_q24"] / Q, raw[15:]]
            np.testing.assert_array_equal(np.rint(reconstructed * Q), np.rint(x * Q))
            self.assertEqual(row["continuous"]["margin_q24"], round(x[11] * Q))
            self.assertEqual(row["continuous"]["risk_q24"], round(x[14] * Q))

    def test_hidden_current_channel_changes_do_not_leak(self):
        altered = deepcopy(self.context)
        altered["dp"]["q_keep"] += 0.5
        expected, _ = self.values("value_margin")
        actual, _ = self.values("value_margin", altered)
        np.testing.assert_array_equal(actual, expected)
        call_before, _ = self.values("value_call")
        call_after, _ = self.values("value_call", altered)
        self.assertTrue(np.all(call_after[:, 12] > call_before[:, 12]))


if __name__ == "__main__":
    unittest.main()
