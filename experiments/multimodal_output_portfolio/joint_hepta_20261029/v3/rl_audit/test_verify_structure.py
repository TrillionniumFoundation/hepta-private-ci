from copy import deepcopy
import unittest
from unittest.mock import patch

from . import structure as s
from .verify_structure import verify_case


class RetainedReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = {**s.protocol(), "train_n": 16, "test_n": 8, "neural_updates": 4}
        cls.case = s.run_case(s.Panel(), 31, cls.cfg)

    def test_all_checkpoints_replay_without_refitting(self):
        rows, count = verify_case(self.case, self.cfg)
        self.assertEqual((len(rows), count), (12, 72))

    def test_repeated_arm_cannot_replace_a_missing_baseline(self):
        case = deepcopy(self.case)
        case["records"][-1] = deepcopy(case["records"][0])
        with self.assertRaisesRegex(ValueError, "arm roster"):
            verify_case(case, self.cfg)

    def test_observation_tampering_rejects(self):
        case = deepcopy(self.case)
        case["training_observations"]["outcomes"][0][0][0] += 1
        with self.assertRaises(AssertionError):
            verify_case(case, self.cfg)

    def test_retained_action_and_cost_must_match_model(self):
        for field in ("choices", "fees", "expected_net", "observed_quality"):
            case = deepcopy(self.case)
            case["records"][0]["raw"][field][0] += 1
            with self.subTest(field=field), self.assertRaises((AssertionError, ValueError)):
                verify_case(case, self.cfg)

    def test_checkpoint_and_inference_cost_substitution_reject(self):
        case = deepcopy(self.case)
        case["records"][0]["model"]["parameters"][0][0][0] += 1
        with self.assertRaisesRegex(ValueError, "checkpoint identity"):
            verify_case(case, self.cfg)
        case = deepcopy(self.case)
        case["records"][0]["raw"]["cpu_ns"][0] += 1
        with self.assertRaisesRegex(ValueError, "CPU total"):
            verify_case(case, self.cfg)

    def test_zero_diffusion_has_no_imputed_gradient(self):
        panel = next(p for p in s.panels() if p.name == "noise_zero")
        case = s.run_case(panel, 37, self.cfg)
        rows, count = verify_case(case, self.cfg)
        self.assertEqual((len(rows), count), (9, 48))
        case["records"][2]["status"] = "complete"
        with self.assertRaisesRegex(ValueError, "silently imputed"):
            verify_case(case, self.cfg)

    def test_fit_metadata_and_work_cannot_be_invented(self):
        for field in (
            "trainable_parameters",
            "normalization_statistics",
            "observations_used",
            "outputs",
            "updates",
        ):
            case = deepcopy(self.case)
            case["records"][0]["training"][field] += 1
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "fit metadata"):
                verify_case(case, self.cfg)
        for index in (0, 9):
            for axis in ("cpu_ns", "wall_ns"):
                case = deepcopy(self.case)
                case["records"][index]["training"][axis] = -1
                with (
                    self.subTest(index=index, axis=axis),
                    self.assertRaisesRegex(ValueError, "invalid training"),
                ):
                    verify_case(case, self.cfg)

    def test_actual_checkpoint_shapes_and_finite_values_are_checked(self):
        case = deepcopy(self.case)
        case["records"][0]["model"]["parameters"][0].pop()
        with self.assertRaisesRegex(ValueError, "checkpoint shape"):
            verify_case(case, self.cfg)
        for value in (0, -1, float("nan"), float("inf")):
            case = deepcopy(self.case)
            case["records"][0]["model"]["scale"][0] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "checkpoint numeric"):
                verify_case(case, self.cfg)

    def test_quality_fees_stop_rate_and_latency_metrics_are_recomputed(self):
        for field in (
            "expected_quality",
            "observed_quality",
            "mean_fee",
            "observed_net_p05",
            "stop_no_update_fraction",
            "wall_p95_ns",
            "wall_p99_ns",
        ):
            case = deepcopy(self.case)
            case["records"][0]["metrics"][field] += 1
            with self.subTest(field=field), self.assertRaises(AssertionError):
                verify_case(case, self.cfg)

    def test_same_test_diagnostics_recompute_without_refitting(self):
        with patch.object(s, "fit", side_effect=AssertionError("must not refit")):
            verify_case(self.case, self.cfg)
            for field in ("gradient_mse", "mean_abs_curl", "value_mse"):
                case = deepcopy(self.case)
                case["records"][0]["calibration"][field] += 1
                with self.subTest(field=field), self.assertRaises(AssertionError):
                    verify_case(case, self.cfg)

    def test_panel_name_does_not_authorize_changed_conditions(self):
        case = deepcopy(self.case)
        case["panel"]["noise"] = 0.3
        with self.assertRaisesRegex(ValueError, "panel contract"):
            verify_case(case, self.cfg)

    def test_fractional_actions_and_boolean_timings_are_not_valid_records(self):
        case = deepcopy(self.case)
        case["records"][0]["raw"]["choices"][0] += 1e-14
        with self.assertRaisesRegex(ValueError, "action roster"):
            verify_case(case, self.cfg)
        case = deepcopy(self.case)
        case["records"][0]["raw"]["wall_ns"][0] = False
        with self.assertRaisesRegex(ValueError, "timing roster"):
            verify_case(case, self.cfg)


if __name__ == "__main__":
    unittest.main()
