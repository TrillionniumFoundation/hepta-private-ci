"""Behavioral differentiation/accounting tests; no model-quality claim."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields
from threading import Barrier
import json
import unittest

import numpy as np

from scripts.ndu_portfolio.adapters import (
    AdapterProfile,
    FrozenBundle,
    TRAINABLE,
    check_gradients,
    make_bundle,
    objective_and_gradient,
    predict,
    run_adapter_experiment,
    train_candidate,
)
from scripts.ndu_portfolio.streaming import (
    ComputeCharge,
    StreamingLedger,
    run_streaming_experiment,
)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.bundle = make_bundle(2)
        rng = np.random.default_rng(91)
        self.features = rng.normal(size=(8, 5))
        self.target = (rng.uniform(size=(8, 2)) > 0.5).astype(float)
        self.preferences = np.tile([0.6, 0.4], (8, 1))

    def test_zero_adapter_reproduces_base_and_selected_is_immutable(self):
        before = self.bundle.digest()
        wc, wg, wa = self.bundle.effective()
        for actual, expected in zip(
            (wc, wg, wa),
            (
                self.bundle.base_cell,
                self.bundle.base_generator,
                self.bundle.control_base,
            ),
        ):
            np.testing.assert_array_equal(actual, expected)
        candidate, trace = train_candidate(
            self.bundle, self.features, self.target, self.preferences, steps=10
        )
        self.assertEqual(before, self.bundle.digest())
        self.assertNotEqual(candidate.digest(), before)
        for name in ("base_cell", "base_generator", "control_base"):
            np.testing.assert_array_equal(
                getattr(candidate, name), getattr(self.bundle, name)
            )
        with self.assertRaises(ValueError):
            self.bundle.base_cell.setflags(write=True)
        with self.assertRaises(ValueError):
            self.bundle.cell_up[0, 0] = 1
        self.assertTrue(
            all(b["objective"] >= a["objective"] for a, b in zip(trace, trace[1:]))
        )

    def test_gradients_cover_all_groups_with_and_without_risk(self):
        candidate, _ = train_candidate(
            self.bundle, self.features, self.target, self.preferences, steps=5
        )
        for risk in (0, 1e-9, 0.4):
            profile = AdapterProfile(risk_aversion=risk)
            result = check_gradients(
                candidate, self.features, self.target, self.preferences, profile
            )
            self.assertLess(result["max_absolute_error"], 1e-8)
            _, gradient = objective_and_gradient(
                candidate, self.features, self.target, self.preferences, profile
            )
            self.assertTrue(
                all(np.linalg.norm(gradient[name]) > 0 for name in TRAINABLE)
            )

    def test_effective_trust_region_and_fixed_training_objective(self):
        candidate, _ = train_candidate(
            self.bundle,
            self.features,
            self.target,
            self.preferences,
            steps=20,
            trust_radius=0.05,
            learning_rate=100,
        )
        distance = np.sqrt(
            sum(
                np.sum((a - b) ** 2)
                for a, b in zip(candidate.effective(), self.bundle.effective())
            )
        )
        self.assertLessEqual(distance, 0.05)
        initial = objective_and_gradient(
            self.bundle, self.features, self.target, self.preferences
        )[0]
        updated = objective_and_gradient(
            candidate, self.features, self.target, self.preferences
        )[0]
        self.assertGreater(updated, initial)

    def test_rejects_invalid_profiles_labels_and_shapes(self):
        with self.assertRaises(ValueError):
            AdapterProfile(risk_aversion=float("nan"))
        with self.assertRaises(ValueError):
            objective_and_gradient(
                self.bundle, self.features, self.target, np.full((8, 2), 0.8)
            )
        with self.assertRaises(ValueError):
            objective_and_gradient(
                self.bundle, self.features, self.target * 2, self.preferences
            )
        with self.assertRaises(ValueError):
            predict(self.bundle, np.empty((0, 5)))
        changed = {f.name: getattr(self.bundle, f.name) for f in fields(self.bundle)}
        changed["generator_up"] = np.zeros((4, 2))
        with self.assertRaises(ValueError):
            FrozenBundle(**changed)

    def test_synthetic_training_never_qualifies_real_generation(self):
        result = run_adapter_experiment()
        json.dumps(result, allow_nan=False)
        self.assertEqual(result["real_stage_3"], "HOLD")
        self.assertTrue(result["selected_unchanged"])
        self.assertLess(result["gradient_check"]["max_absolute_error"], 1e-8)
        self.assertGreater(
            result["train_objective_after"], result["train_objective_before"]
        )
        admission = "PASS" if all(result["synthetic_gates"].values()) else "REJECTED"
        self.assertEqual(result["synthetic_candidate_admission"], admission)


class StreamingTests(unittest.TestCase):
    def setUp(self):
        self.ledger = StreamingLedger(100, 200_000)
        self.charge = ComputeCharge("shared", 30, 0, 50_000, "inference")
        self.ledger.charge_compute(self.charge)

    def test_shared_work_is_once_but_controller_and_failure_costs_remain(self):
        self.assertFalse(self.ledger.charge_compute(self.charge))
        self.ledger.charge_compute(
            ComputeCharge("control", 5, 50_000, 60_000, "controller")
        )
        self.ledger.charge_compute(
            ComputeCharge("failed", 4, 60_000, 70_000, "inference", False)
        )
        report = self.ledger.report()
        self.assertEqual(
            (
                report["compute_units"],
                report["elapsed_us"],
                report["physical_work_count"],
            ),
            (39, 70_000, 3),
        )
        self.assertEqual(report["compute_by_kind"]["controller"], 5)
        self.assertEqual(report["failed_work_compute_units"], 4)
        with self.assertRaises(ValueError):
            self.ledger.charge_compute(
                ComputeCharge("shared", 0, 0, 50_000, "inference")
            )
        with self.assertRaises(ValueError):
            self.ledger.prepare_chunk("audio", 0, 0, 20_000, b"bad", ("failed",))

    def test_multirate_delivery_and_irreversibility(self):
        for i in range(4):
            self.ledger.prepare_chunk(
                "audio", i, i * 20_000, (i + 1) * 20_000, bytes([i + 1]), ("shared",)
            )
        for i in range(2):
            self.ledger.prepare_chunk(
                "video", i, i * 40_000, (i + 1) * 40_000, bytes([i + 1]), ("shared",)
            )
        delivered = self.ledger.deliver("audio", 3)
        self.ledger.deliver("video", 0)
        self.assertFalse(self.ledger.check_av_sync(5_000)["timestamp_sync_pass"])
        self.ledger.deliver("video", 1)
        self.assertTrue(self.ledger.check_av_sync(5_000)["timestamp_sync_pass"])
        self.assertEqual(self.ledger.deliver("audio", 3), delivered)
        with self.assertRaises(ValueError):
            self.ledger.prepare_chunk("audio", 0, 0, 20_000, b"changed", ("shared",))
        with self.assertRaises(ValueError):
            self.ledger.deliver("audio", 1)

    def test_incomplete_delivery_is_atomic_and_pending_revision_is_allowed(self):
        self.ledger.prepare_chunk("audio", 0, 0, 20_000, b"before", ("shared",))
        replacement = self.ledger.prepare_chunk(
            "audio", 0, 0, 20_000, b"after", ("shared",)
        )
        with self.assertRaises(ValueError):
            self.ledger.deliver("audio", 1)
        self.assertEqual(self.ledger.report()["delivered_chunks"]["audio"], 0)
        self.assertEqual(self.ledger.deliver("audio", 0), (replacement,))
        self.ledger.prepare_chunk("audio", 1, 21_000, 40_000, b"gap", ("shared",))
        with self.assertRaises(ValueError):
            self.ledger.deliver("audio", 1)

    def test_resource_overrun_is_observable_and_blocks_new_delivery(self):
        self.assertFalse(self.ledger.can_start(80, 60_000))
        self.assertFalse(self.ledger.can_start(1, 200_001))
        self.ledger.prepare_chunk("audio", 0, 0, 20_000, b"artifact", ("shared",))
        self.ledger.charge_compute(
            ComputeCharge("overrun", 80, 50_000, 200_001, "verification")
        )
        report = self.ledger.report()
        self.assertEqual(report["remaining_compute_units"], -10)
        self.assertFalse(report["deadline_pass"])
        with self.assertRaises(ValueError):
            self.ledger.deliver("audio", 0)
        with self.assertRaises(AttributeError):
            self.ledger.compute_budget = 999

    def test_concurrent_reservations_cannot_double_spend(self):
        ledger = StreamingLedger(100, 200_000)
        barrier = Barrier(2)

        def reserve(work_id):
            barrier.wait(timeout=2)
            try:
                return ledger.reserve_compute(work_id, 65, 100_000)
            except ValueError:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            accepted = list(pool.map(reserve, ("parallel-a", "parallel-b")))
        self.assertEqual(sum(accepted), 1)
        self.assertEqual(ledger.report()["reserved_compute_units"], 65)
        self.assertFalse(ledger.can_start(36, 100_000))

    def test_completion_releases_own_reservation_and_is_idempotent(self):
        ledger = StreamingLedger(100, 200_000)
        self.assertTrue(ledger.reserve_compute("a", 50, 100_000))
        self.assertFalse(ledger.reserve_compute("a", 50, 100_000))
        ledger.reserve_compute("b", 40, 150_000)
        with self.assertRaises(ValueError):
            ledger.reserve_compute("a", 51, 100_000)
        with self.assertRaises(ValueError):
            ledger.charge_compute(ComputeCharge("a", 30, 0, 90_000, "inference"))
        charge = ComputeCharge("a", 30, 0, 90_000, "inference")
        self.assertTrue(ledger.complete_compute(charge))
        self.assertFalse(ledger.complete_compute(charge))
        self.assertFalse(ledger.reserve_compute("a", 50, 100_000))
        report = ledger.report()
        self.assertEqual(
            (
                report["compute_units"],
                report["reserved_compute_units"],
                report["available_after_reservations"],
                report["outstanding_reservations"],
            ),
            (30, 40, 30, 1),
        )
        with self.assertRaises(ValueError):
            ledger.complete_compute(
                ComputeCharge("unreserved", 5, 90_000, 95_000, "inference")
            )

    def test_failed_completion_and_overrun_preserve_actual_cost(self):
        ledger = StreamingLedger(100, 200_000)
        ledger.reserve_compute("a", 60, 100_000)
        ledger.reserve_compute("b", 30, 150_000)
        ledger.complete_compute(ComputeCharge("a", 105, 0, 210_000, "inference"))
        during = ledger.report()
        self.assertEqual(
            (during["compute_units"], during["reserved_compute_units"]), (105, 30)
        )
        self.assertFalse(during["budget_pass"])
        self.assertFalse(during["deadline_pass"])
        ledger.complete_compute(
            ComputeCharge("b", 5, 50_000, 90_000, "verification", False)
        )
        after = ledger.report()
        self.assertEqual(
            (
                after["compute_units"],
                after["reserved_compute_units"],
                after["failed_work_compute_units"],
            ),
            (110, 0, 5),
        )
        self.assertEqual(after["reservation_breaches"], ["a"])

    def test_bounded_work_and_media_horizons(self):
        ledger = StreamingLedger(
            100, 200_000, max_physical_work=2, max_chunks_per_modality=2
        )
        ledger.reserve_compute("reserved", 10, 100_000)
        ledger.charge_compute(ComputeCharge("imported", 10, 0, 50_000, "inference"))
        with self.assertRaises(ValueError):
            ledger.reserve_compute("third", 1, 100_000)
        with self.assertRaises(ValueError):
            ledger.charge_compute(ComputeCharge("third", 1, 0, 1, "inference"))
        ledger.complete_compute(ComputeCharge("reserved", 8, 0, 90_000, "inference"))
        with self.assertRaises(ValueError):
            ledger.prepare_chunk(
                "audio", 2, 40_000, 60_000, b"beyond horizon", ("imported",)
            )
        with self.assertRaises(ValueError):
            ledger.deliver("audio", 2)
        for sequence in range(2):
            ledger.prepare_chunk(
                "audio",
                sequence,
                sequence * 20_000,
                (sequence + 1) * 20_000,
                b"within horizon",
                ("imported",),
            )
        self.assertEqual(len(ledger.deliver("audio", 1)), 2)
        self.assertEqual(ledger.report()["max_physical_work"], 2)

    def test_committed_prefix_survives_later_failed_delivery(self):
        self.ledger.prepare_chunk("audio", 0, 0, 20_000, b"committed", ("shared",))
        committed = self.ledger.deliver("audio", 0)
        self.ledger.prepare_chunk("audio", 1, 20_000, 40_000, b"pending", ("shared",))
        self.ledger.reserve_compute("later-work", 10, 100_000)
        self.ledger.complete_compute(
            ComputeCharge("later-work", 80, 50_000, 110_000, "inference", False)
        )
        with self.assertRaises(ValueError):
            self.ledger.deliver("audio", 1)
        self.assertEqual(self.ledger.deliver("audio", 0), committed)
        self.assertEqual(self.ledger.report()["delivered_chunks"]["audio"], 1)

    def test_time_units_and_missing_stream_fail_closed(self):
        for invalid in (True, 1.5, -1):
            with self.assertRaises(ValueError):
                ComputeCharge("invalid", invalid, 0, 1, "inference")
        self.assertFalse(self.ledger.check_av_sync(100)["timestamp_sync_pass"])
        result = run_streaming_experiment()
        self.assertTrue(result["delivered_prefix_rewrite_rejected"])
        self.assertTrue(result["shared_compute_charged_once"])
        self.assertEqual(result["ledger"]["real_stage_4"], "HOLD")
        self.assertFalse(result["actual_audio_video_generated"])


if __name__ == "__main__":
    unittest.main()
