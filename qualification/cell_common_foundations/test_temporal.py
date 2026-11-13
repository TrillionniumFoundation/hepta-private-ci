"""Behavioral comparison gates; missing Torch/HCSN is an error, never a skip."""

import copy
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import torch

from qualification.cell_common_foundations.temporal import (
    FrozenTemporalKernel,
    HCSN_HASHES,
    KINDS,
    TemporalBatch,
    checkpoint_difference,
    make_temporal_batch,
    run_temporal_pilot,
    verify_hcsn_source,
)


class TemporalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.previous_threads)

    def test_short_and_long_dependency_clocks_and_serialized_recovery(self):
        for kind in KINDS:
            for horizon in (4, 32):
                with self.subTest(kernel=kind, horizon=horizon):
                    batch = make_temporal_batch(4, horizon, 91)
                    kernel = FrozenTemporalKernel(kind, 12)
                    with torch.no_grad():
                        outputs, state, diagnostics = kernel(
                            batch.encoded(), batch.dt, state=kernel.initial_state(4)
                        )
                    torch.testing.assert_close(
                        state.elapsed, batch.dt.sum(1), rtol=0, atol=1e-14
                    )
                    self.assertEqual(state.position, horizon)
                    self.assertTrue(bool(torch.isfinite(outputs).all()))
                    recovered = checkpoint_difference(kernel, batch, outputs)
                    self.assertLessEqual(recovered["maximum_feature_error"], 1e-11)
                    self.assertLessEqual(recovered["elapsed_maximum_error"], 1e-13)
                    if kind == "hcsn":
                        self.assertLessEqual(
                            diagnostics["maximum_mass_residual"],
                            kernel.model.mass_tolerance,
                        )

    def test_early_cue_and_actual_delay_affect_all_representations(self):
        values = torch.zeros(2, 4, 3, dtype=torch.float64)
        values[:, 0, 0] = torch.tensor([-1.0, 1.0])
        values[:, 0, 1] = 1.0
        values[:, -1, 2] = 1.0
        targets = torch.tensor([0.0, 1.0], dtype=torch.float64)
        batch = TemporalBatch(
            values, torch.full((2, 4), 0.03, dtype=torch.float64), targets
        )
        delayed = TemporalBatch(
            values, torch.full((2, 4), 0.09, dtype=torch.float64), targets
        )
        for kind in KINDS:
            with self.subTest(kernel=kind), torch.no_grad():
                kernel = FrozenTemporalKernel(kind, 29)
                original, _, _ = kernel(
                    batch.encoded(), batch.dt, state=kernel.initial_state(2)
                )
                shifted, _, _ = kernel(
                    delayed.encoded(), delayed.dt, state=kernel.initial_state(2)
                )
                self.assertGreater(
                    float((original[0, -1] - original[1, -1]).abs().max()), 1e-10
                )
                self.assertGreater(float((shifted - original).abs().max()), 1e-8)

    def test_changed_kernel_and_incomplete_checkpoint_are_rejected(self):
        batch = make_temporal_batch(4, 4, 25)
        for kind in KINDS:
            with self.subTest(kernel=kind), torch.no_grad():
                kernel = FrozenTemporalKernel(kind, 11)
                state = kernel.initial_state(4)
                checkpoint = kernel.checkpoint(state)
                broken = copy.deepcopy(checkpoint)
                if kind == "hcsn":
                    broken["payload"]["layers"][0]["content_mass"] = torch.zeros(
                        1, dtype=torch.float64
                    )
                else:
                    broken["payload"]["hidden"] = torch.zeros(1, dtype=torch.float64)
                with self.assertRaises((ValueError, RuntimeError, IndexError)):
                    kernel.restore_checkpoint(broken)
                if kind == "hcsn":
                    substituted = copy.deepcopy(checkpoint)
                    substituted["payload"]["model"]["readout.bias"].add_(0.01)
                    before = kernel.signature()
                    with self.assertRaisesRegex(ValueError, "frozen HCSN model"):
                        kernel.restore_checkpoint(substituted)
                    self.assertEqual(kernel.signature(), before)
                next(kernel.parameters()).add_(0.001)
                with self.assertRaisesRegex(ValueError, "changed frozen kernel"):
                    kernel(batch.encoded(), batch.dt, state=state)
                with self.assertRaisesRegex(ValueError, "another frozen kernel"):
                    kernel.restore_checkpoint(checkpoint)

    def test_unqualified_long_gaps_are_not_silently_subdivided(self):
        batch = make_temporal_batch(4, 4, 19)
        invalid_dt = batch.dt.clone()
        invalid_dt[0, 1] = 0.11
        for kind in KINDS:
            kernel = FrozenTemporalKernel(kind, 13)
            with self.assertRaisesRegex(ValueError, "0 <= dt"):
                kernel(batch.encoded(), invalid_dt, state=kernel.initial_state(4))

    def test_hcsn_modified_source_cannot_inherit_exact_head_identity(self):
        directory = Path(__file__).resolve().parents[1] / "hcsn_differentiable"
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            for name in HCSN_HASHES:
                (destination / name).write_bytes((directory / name).read_bytes())
            verify_hcsn_source(destination)
            with (destination / "operator.py").open("ab") as stream:
                stream.write(b"\n# changed source\n")
            with self.assertRaisesRegex(ValueError, "differs"):
                verify_hcsn_source(destination)

    def test_executable_head_only_comparison_preserves_shared_contract(self):
        events = []
        report = run_temporal_pilot(
            seeds=(7,),
            horizon=8,
            size=4,
            head_steps=2,
            on_attempt=lambda event, row: events.append((event, row)),
        )
        self.assertEqual(
            report["counts"],
            {"planned": 4, "attempted": 4, "completed": 4, "failed": 0},
            report,
        )
        self.assertEqual(
            [(event, row["status"]) for event, row in events],
            [("started", "running"), ("finished", "completed")] * 4,
        )
        for started, finished in zip(events[::2], events[1::2]):
            self.assertEqual(
                (started[1]["kernel"], started[1]["seed"]),
                (finished[1]["kernel"], finished[1]["seed"]),
            )
        first = report["attempts"][0]
        for attempt in report["attempts"]:
            self.assertEqual(attempt["panel_sha256"], first["panel_sha256"])
            self.assertEqual(attempt["contract_sha256"], first["contract_sha256"])
            self.assertEqual(attempt["head_updates_completed"], 6)
            self.assertEqual(
                set(attempt["cases"]),
                {"short_dependency", "long_dependency", "delay_adaptation"},
            )
            for stage in ("before", "after", "original_delay_panel_after"):
                self.assertTrue(
                    0 <= attempt["cases"]["delay_adaptation"][stage]["accuracy"] <= 1
                )
        self.assertFalse(report["full_parameter_training"])
        self.assertFalse(report["production_qualified"])
        self.assertIsNone(report["energy_joules"])

    def test_receipt_write_errors_propagate_outside_model_failure_handling(self):
        def start_failure(event, row):
            raise OSError("start receipt write failed")

        target = "qualification.cell_common_foundations.temporal.FrozenTemporalKernel"
        with mock.patch(target) as constructor:
            with self.assertRaisesRegex(OSError, "start receipt"):
                run_temporal_pilot(
                    seeds=(7,),
                    horizon=8,
                    size=4,
                    head_steps=1,
                    on_attempt=start_failure,
                )
            constructor.assert_not_called()

        events = []

        def terminal_failure(event, row):
            events.append((event, row["status"]))
            if event == "finished":
                raise OSError("terminal receipt write failed")

        with mock.patch(
            target, side_effect=RuntimeError("injected kernel failure")
        ) as constructor:
            with self.assertRaisesRegex(OSError, "terminal receipt"):
                run_temporal_pilot(
                    seeds=(7,),
                    horizon=8,
                    size=4,
                    head_steps=1,
                    on_attempt=terminal_failure,
                )
            self.assertEqual(constructor.call_count, 1)
        self.assertEqual(events, [("started", "running"), ("finished", "failed")])


if __name__ == "__main__":
    unittest.main()
