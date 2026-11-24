"""Execute the actual linear producers; synthetic controls grant no admission."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from hepta_cells import differentiation_reference as reference


class DifferentiationReferenceTests(unittest.TestCase):
    def test_real_fits_match_selected_head_work_and_keep_old_predictions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "original"
            report = reference.run_reference(root, seeds=(17,), steps=4)
            run = report["runs"][0]
            shared, routed, frozen = (
                run["arms"][arm] for arm in ("shared_bank", "routed_heads", "frozen")
            )
            self.assertEqual((report["fits"], report["optimizer_steps"]), (4, 16))
            self.assertEqual(shared["parameters"], routed["parameters"])
            self.assertEqual(shared["counters"], routed["counters"])
            self.assertEqual(shared["counters"]["optimizer_steps"], 8)
            self.assertEqual(frozen["training"], [])
            self.assertEqual(frozen["counters"]["optimizer_steps"], 0)
            self.assertEqual(
                [row["dataset_digest"] for row in shared["training"]],
                [row["dataset_digest"] for row in routed["training"]],
            )
            for arm in run["arms"].values():
                self.assertTrue(arm["old_task_predictions_retained"])
                self.assertTrue(arm["replay_without_model_execution"])
            for panel in routed["panels"]:
                self.assertEqual(panel["selected_cost"]["head_calls"], 1)
                self.assertEqual(panel["dense_cost"]["head_calls"], 2)
                self.assertEqual(
                    panel["dense_cost"]["forward_mac"],
                    2 * panel["selected_cost"]["forward_mac"],
                )
                self.assertEqual(len(panel["receipts"]), 1)
                self.assertEqual(len(panel["dense_receipts"]), 2)
            with (
                np.load(root / "17-inputs.npz", allow_pickle=False) as data,
                np.load(root / "17-routed_heads.npz", allow_pickle=False) as trained,
                np.load(root / "17-frozen.npz", allow_pickle=False) as fixed,
            ):
                self.assertFalse(
                    np.array_equal(
                        data["task0_initial_weights"], trained["phase0_task0_weights"]
                    )
                )
                np.testing.assert_array_equal(
                    data["task0_initial_weights"], fixed["phase1_task0_weights"]
                )
                np.testing.assert_array_equal(
                    trained["phase0_task0_weights"], trained["phase1_task0_weights"]
                )
            for name, pin in report["artifacts"].items():
                raw = (root / name).read_bytes()
                self.assertEqual(
                    (len(raw), hashlib.sha256(raw).hexdigest()),
                    (pin["bytes"], pin["sha256"]),
                )
            self.assertEqual(
                (report["scientific_acceptance"], report["decision"]),
                ("HOLD", "NoUpdate"),
            )
            self.assertFalse(run["total_physical_compute_matched"])
            self.assertGreater(
                shared["explicit_layout_copy_scalars"],
                routed["explicit_layout_copy_scalars"],
            )
            with self.assertRaises(FileExistsError):
                reference.run_reference(root, seeds=(17,), steps=4)

    def test_different_active_work_leaves_original_failed_attempt(self):
        original = reference._Bank.replace

        def changed(bank, task, component, candidate):
            original(bank, task, component, candidate)
            if bank.arm == "routed_heads":
                bank.counters["gradient_mac"] += 1

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "failed"
            with patch.object(reference._Bank, "replace", changed):
                with self.assertRaisesRegex(RuntimeError, "controls diverged"):
                    reference.run_reference(root, seeds=(17,), steps=1)
            self.assertFalse((root / "RESULT.json").exists())
            failure = json.loads((root / "FAILURE.json").read_text())
            self.assertEqual(failure["status"], "FAILED")
            self.assertTrue((root / "17-routed_heads.npz").is_file())
            events = [
                json.loads(line)
                for line in (root / "EVENTS.jsonl").read_text().splitlines()
            ]
            self.assertEqual(events[-1]["status"], "failed")
            self.assertEqual(
                sum(
                    e["status"] == "completed" and e["stage"] == "training"
                    for e in events[:-1]
                ),
                4,
            )

    def test_source_drift_and_invalid_rosters_never_emit_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "changed"
            with patch.object(
                reference,
                "_sources",
                side_effect=[{"module": "first"}, {"module": "changed"}],
            ):
                with self.assertRaisesRegex(RuntimeError, "source changed"):
                    reference.run_reference(root, seeds=(29,), steps=1)
            self.assertTrue((root / "FAILURE.json").is_file())
            self.assertFalse((root / "RESULT.json").exists())
            for seeds, steps in (
                ((1, 1), 1),
                ((True,), 1),
                ((), 1),
                ((1,), True),
                ((1,), 129),
            ):
                with self.subTest(seeds=seeds, steps=steps):
                    with self.assertRaises(ValueError):
                        reference.run_reference(
                            Path(directory) / "invalid", seeds=seeds, steps=steps
                        )
            self.assertFalse((Path(directory) / "invalid").exists())

    def test_checkpoint_failure_retains_completed_training_cost_before_publication(
        self,
    ):
        original_open = Path.open

        def fail_checkpoint(path, *args, **kwargs):
            if path.name.endswith("-fit0.npz"):
                raise OSError("injected checkpoint write failure")
            return original_open(path, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "failed-checkpoint"
            with patch.object(Path, "open", fail_checkpoint):
                with self.assertRaisesRegex(OSError, "checkpoint write failure"):
                    reference.run_reference(root, seeds=(17,), steps=1)
            events = [
                json.loads(line)
                for line in (root / "EVENTS.jsonl").read_text().splitlines()
            ]
            completed = [
                event
                for event in events
                if event.get("stage") == "training" and event["status"] == "completed"
            ]
            self.assertEqual(len(completed), 1)
            self.assertEqual(completed[0]["receipt"]["completed_steps"], 1)
            self.assertEqual(completed[0]["receipt"]["items"], reference.TRAIN_ROWS)
            self.assertGreaterEqual(completed[0]["receipt"]["process_cpu_seconds"], 0)
            self.assertFalse((root / "RESULT.json").exists())
            self.assertFalse((root / "17-shared_bank-fit0.npz").exists())
            self.assertFalse(
                any(event.get("stage") == "checkpoint" for event in events)
            )


if __name__ == "__main__":
    unittest.main()
