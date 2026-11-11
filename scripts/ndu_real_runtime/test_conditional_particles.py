"""Behavioral checks for empirical conditioning and its admission boundary."""

import copy
import json
import math
import unittest

from .conditional_particles import ConditionalResidualBank, UnsupportedCondition
from .objective import canonical_sha

BINDING = {
    name + "_sha256": digit * 64
    for name, digit in (
        ("weights", "a"),
        ("source", "b"),
        ("profile", "c"),
    )
}


def observation(group, context, residual, *, action="READ_ROI"):
    return {
        "public_features": [context, 0.0],
        "action": action,
        "predicted_next_features": [0.0, 0.0],
        "observed_next_features": [residual, -residual],
        "predicted_duration_seconds": 2.0,
        "observed_duration_seconds": 2.0 * math.exp(residual),
        "predicted_utility": 0.5,
        "observed_utility": 0.5 + residual / 2,
        "source_group": group,
        "split": "calibration",
    }


def fitted(rows, **kwargs):
    return ConditionalResidualBank.fit(
        rows,
        binding=BINDING,
        fit_source_groups=["fit-independent"],
        feature_scale=[1.0, 1.0],
        **kwargs,
    )


class ConditionalParticleTests(unittest.TestCase):
    def test_joint_state_time_and_utility_correlation_survives(self):
        bank = fitted([observation("c1", 0, -0.4), observation("c2", 0, 0.4)])
        rows, info = bank.sample([0, 0], "READ_ROI", particles=7, seed=42)
        self.assertAlmostEqual(sum(x.probability for x in rows), 1)
        for row in rows:
            value = row.state_residual[0]
            self.assertEqual(row.state_residual[1], -value)
            self.assertAlmostEqual(row.log_duration_residual, value)
            self.assertAlmostEqual(row.utility_residual, value / 2)
        self.assertTrue(info["risk_sensitive_support"])
        self.assertFalse(info["conditional_coverage_established"])

    def test_public_context_changes_empirical_tail(self):
        rows = [
            observation("l1", 0, -0.1),
            observation("l2", 0, 0.1),
            observation("h1", 1, -0.8),
            observation("h2", 1, 0.8),
        ]
        bank = fitted(rows, neighbor_groups=2)
        low, _ = bank.sample([0, 0], "READ_ROI", particles=2, seed=5)
        high, _ = bank.sample([1, 0], "READ_ROI", particles=2, seed=5)
        self.assertEqual({x.state_residual[0] for x in low}, {-0.1, 0.1})
        self.assertEqual({x.state_residual[0] for x in high}, {-0.8, 0.8})

    def test_long_episode_gets_equal_group_mass(self):
        rows = [observation("long", 0, -0.6) for _ in range(31)]
        rows.append(observation("short", 0, 0.6))
        draws, _ = fitted(rows).sample([0, 0], "READ_ROI", particles=7, seed=1)
        self.assertAlmostEqual(
            sum(x.probability for x in draws if x.utility_residual < 0), 0.5
        )
        self.assertAlmostEqual(
            sum(x.probability for x in draws if x.utility_residual > 0), 0.5
        )
        rows.append(observation("long", 0, -0.6))
        rows.append(observation("long", 0, -0.6))
        with self.assertRaisesRegex(ValueError, "capacity"):
            fitted(rows)

    def test_source_overlap_and_noncalibration_records_refused(self):
        rows = [observation("c1", 0, -0.1), observation("c2", 0, 0.1)]
        for split in ("train", "development", "confirmation", "test"):
            changed = copy.deepcopy(rows)
            changed[0]["split"] = split
            with self.assertRaisesRegex(ValueError, "calibration"):
                fitted(changed)
        rows[0]["source_group"] = "fit-independent"
        with self.assertRaisesRegex(ValueError, "overlap"):
            fitted(rows)

    def test_cold_roundtrip_and_external_identity_pins(self):
        bank = fitted([observation("c1", 0, -0.4), observation("c2", 0, 0.4)])
        document = json.loads(json.dumps(bank.to_dict()))
        restored = ConditionalResidualBank.from_dict(
            document,
            expected_sha256=bank.sha256,
            expected_binding=BINDING,
        )
        query = ([0, 0], "READ_ROI")
        self.assertEqual(
            bank.sample(*query, particles=5, seed=14),
            restored.sample(*query, particles=5, seed=14),
        )
        document["rows"][0]["utility_residual"] = 0.1
        with self.assertRaisesRegex(ValueError, "digest"):
            ConditionalResidualBank.from_dict(
                document,
                expected_sha256=bank.sha256,
                expected_binding=BINDING,
            )
        wrong = dict(BINDING, weights_sha256="d" * 64)
        with self.assertRaisesRegex(ValueError, "binding"):
            ConditionalResidualBank.from_dict(
                bank.to_dict(),
                expected_sha256=bank.sha256,
                expected_binding=wrong,
            )
        self.assertEqual(bank.sha256, canonical_sha(bank.to_dict()))
        with self.assertRaises(TypeError):
            bank.binding["weights_sha256"] = "e" * 64
        with self.assertRaises(AttributeError):
            bank.sha256 = "e" * 64
        with self.assertRaises(AttributeError):
            bank.scale = (2.0, 2.0)
        with self.assertRaises(TypeError):
            bank._by_action["READ_ROI"]["c1"] = ()

    def test_cold_loading_rechecks_split_even_with_matching_digest(self):
        bank = fitted([observation("c1", 0, -0.1), observation("c2", 0, 0.1)])
        document = bank.to_dict()
        document["rows"][0]["split"] = "confirmation"
        with self.assertRaisesRegex(ValueError, "calibration"):
            ConditionalResidualBank.from_dict(
                document,
                expected_sha256=canonical_sha(document),
                expected_binding=BINDING,
            )

    def test_sparse_singleton_unsupported_and_distant_queries_refused(self):
        bank = fitted(
            [observation("c1", 0, -0.1), observation("c2", 0, 0.1)], max_distance=0.2
        )
        for args in (
            ([0, 0], "WRITE_TEXT", 2),
            ([3, 0], "READ_ROI", 2),
            ([0, 0], "ABSENT", 2),
        ):
            with self.assertRaises(UnsupportedCondition):
                bank.sample(args[0], args[1], particles=args[2], seed=0)
        with self.assertRaises(ValueError) as invalid:
            bank.sample([0, 0], "READ_ROI", particles=1, seed=0)
        self.assertNotIsInstance(invalid.exception, UnsupportedCondition)
        singleton = fitted([observation("only", 0, 0.3)])
        with self.assertRaisesRegex(UnsupportedCondition, "Insufficient"):
            singleton.sample([0, 0], "READ_ROI", particles=8, seed=0)

    def test_degenerate_data_does_not_acquire_fake_noise(self):
        bank = fitted([observation("c1", 0, 0.0), observation("c2", 0, 0.0)])
        rows, info = bank.sample([0, 0], "READ_ROI", particles=8, seed=0)
        self.assertFalse(info["risk_sensitive_support"])
        self.assertEqual(info["distinct_joint_residuals"], 1)
        self.assertEqual({row.log_duration_residual for row in rows}, {0.0})

    def test_numeric_shape_and_range_checks(self):
        rows = [observation("c1", 0, -0.1), observation("c2", 0, 0.1)]
        for key, value in (
            ("public_features", [float("nan"), 0]),
            ("public_features", [10**400, 0]),
            ("observed_next_features", [0]),
            ("observed_duration_seconds", 0),
            ("observed_utility", 2),
            ("predicted_utility", True),
        ):
            changed = copy.deepcopy(rows)
            changed[0][key] = value
            with self.assertRaises(ValueError):
                fitted(changed)
        bank = fitted(rows)
        for features in ([float("inf"), 0], [0], [False, 0]):
            with self.assertRaises(ValueError):
                bank.sample(features, "READ_ROI", particles=2, seed=0)
        with self.assertRaisesRegex(ValueError, "roster"):
            ConditionalResidualBank.fit(
                rows,
                binding=BINDING,
                fit_source_groups="fit-as-a-string",
                feature_scale=[1, 1],
            )


if __name__ == "__main__":
    unittest.main()
