"""Private update parity and independently pinned checkpoint recovery."""

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

from action_microbatch_compare import compare_condition, file_sha, save_checkpoint, verify_checkpoint
from cell_learning_models import canonical
from cell_microbatch_training import FrozenTrainingBank, MicrobatchCellTrainer


class ActionMicrobatchTests(unittest.TestCase):
    def fixture(self, width=13):
        matrix = np.random.default_rng(435).normal(size=(8, width)).astype(np.float32)
        bank = FrozenTrainingBank.build({"action": matrix},
            {"action": [f"source-{i}" for i in range(8)]}, "a"*64)
        return bank, np.arange(8, dtype=np.int64) % 2

    def test_three_modes_keep_private_states_and_match_actual_scalar_updates(self):
        bank, labels = self.fixture()
        for mode in ("linear", "gated", "residual"):
            with self.subTest(mode=mode):
                report, state = compare_condition(bank, labels, 5, mode, steps=3,
                                                  microbatch=2, first="batched")
                self.assertEqual(report["task_count"], 1)
                self.assertEqual(report["actual_total_private_optimizer_updates_both_methods"], 30)
                self.assertEqual(report["actual_total_example_updates_both_methods"], 240)
                self.assertEqual(report["executions"]["scalar"]["initial_parameter_digests"],
                                 report["executions"]["batched"]["initial_parameter_digests"])
                self.assertEqual(report["executions"]["batched"]["distinct_trained_private_states"], 5)
                self.assertFalse(report["new_tasks_inferred_from_cell_count"])
                self.assertFalse(report["heldout_or_calibration_labels_used"])
                self.assertEqual(report["executions"]["batched"]["accounting"]["actual_parameter_bytes"],
                                 sum(value.nbytes for value in state.values()))
                self.assertEqual(report["executions"]["batched"]["accounting"]["actual_moment_bytes"],
                                 2*sum(value.nbytes for value in state.values()))

    def test_actual_770d_rank4_roundtrip_restores_distinct_endpoints(self):
        bank, labels = self.fixture(width=770)
        report, state = compare_condition(bank, labels, 3, "residual", steps=2, microbatch=2)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/"checkpoint"
            digest = save_checkpoint(root, report, state)
            recovered = verify_checkpoint(root, digest)
            self.assertEqual([r["cell_index"] for r in recovered["restored_head_checks"]], [0, 2])
            self.assertEqual([r["tensor_sha256"] for r in recovered["restored_head_checks"]],
                [report["executions"]["batched"]["trained_parameter_digests"][i] for i in (0, 2)])
            self.assertTrue(recovered["all_saved_arrays_verified"])
            self.assertEqual(recovered["verified_parameter_states"], 3)
            self.assertFalse(recovered["quality_scoring"])
            self.assertEqual(recovered["optimizer_updates"], 0)

    def test_checkpoint_save_rejects_arrays_changed_after_comparison(self):
        bank, labels = self.fixture()
        report, state = compare_condition(bank, labels, 3, "linear", steps=2)
        changed = {name: value.copy() for name, value in state.items()}
        changed["W"][1, 0, 0] += .01
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/"checkpoint"
            with self.assertRaisesRegex(ValueError, "measured batched state"):
                save_checkpoint(root, report, changed)
            self.assertFalse(root.exists())

    def test_recovery_binds_middle_cell_digest_even_when_endpoint_logits_match(self):
        bank, labels = self.fixture()
        report, state = compare_condition(bank, labels, 3, "linear", steps=2)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/"checkpoint"
            save_checkpoint(root, report, state)
            meta = json.loads((root/"checkpoint.json").read_bytes())
            meta["parameter_digests"][1] = "f"*64
            (root/"checkpoint.json").write_bytes(canonical(meta)+b"\n")
            with self.assertRaisesRegex(ValueError, "Head digest"):
                verify_checkpoint(root, file_sha(root/"checkpoint.json"))

    def test_hostile_checkpoint_numpy_header_rejects_before_numeric_load(self):
        bank, labels = self.fixture()
        report, state = compare_condition(bank, labels, 3, "linear", steps=2)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/"checkpoint"
            save_checkpoint(root, report, state)
            header = io.BytesIO()
            np.lib.format.write_array_header_1_0(header,
                {"descr": "<f8", "fortran_order": False, "shape": (2**60, 13, 2)})
            ordinary = io.BytesIO()
            np.save(ordinary, state["b"], allow_pickle=False)
            with zipfile.ZipFile(root/"parameters.npz", "w") as archive:
                archive.writestr("W.npy", header.getvalue())
                archive.writestr("b.npy", ordinary.getvalue())
            meta = json.loads((root/"checkpoint.json").read_bytes())
            meta.update(parameter_file_sha256=file_sha(root/"parameters.npz"),
                        parameter_file_bytes=(root/"parameters.npz").stat().st_size)
            (root/"checkpoint.json").write_bytes(canonical(meta)+b"\n")
            with patch("action_microbatch_compare.np.load", side_effect=AssertionError("allocated hostile header")):
                with self.assertRaisesRegex(ValueError, "before allocation"):
                    verify_checkpoint(root, file_sha(root/"checkpoint.json"))

    def test_parameter_or_manifest_tampering_is_rejected(self):
        bank, labels = self.fixture()
        report, state = compare_condition(bank, labels, 2, "gated", steps=2)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/"checkpoint"
            digest = save_checkpoint(root, report, state)
            metadata = json.loads((root/"checkpoint.json").read_bytes())
            metadata["parameter_digests"][0] = "f"*64
            (root/"checkpoint.json").write_bytes(canonical(metadata)+b"\n")
            with self.assertRaisesRegex(ValueError, "manifest identity"):
                verify_checkpoint(root, digest)
            with self.assertRaisesRegex(ValueError, "Head digest"):
                verify_checkpoint(root, file_sha(root/"checkpoint.json"))
            (root/"parameters.npz").write_bytes(b"changed weights")
            with self.assertRaisesRegex(ValueError, "bytes or authority"):
                verify_checkpoint(root, file_sha(root/"checkpoint.json"))

    def test_resource_rejection_happens_before_scalar_or_batched_updates(self):
        bank, labels = self.fixture(width=770)
        with patch("action_microbatch_compare.NumpyCellHead.train") as scalar:
            with patch.object(MicrobatchCellTrainer, "train") as batched:
                with self.assertRaisesRegex(ValueError, "memory bound"):
                    compare_condition(bank, labels, 8, "residual", max_tensor_bytes=4096)
        scalar.assert_not_called()
        batched.assert_not_called()

    def test_actual_changed_parameter_snapshot_fails_comparison(self):
        bank, labels = self.fixture()
        original = MicrobatchCellTrainer.parameters
        def changed(instance):
            arrays = {key: value.copy() for key, value in original(instance).items()}
            arrays["W"][0, 0, 0] += .01
            return arrays
        with patch.object(MicrobatchCellTrainer, "parameters", changed):
            with self.assertRaisesRegex(ValueError, "parameter parity"):
                compare_condition(bank, labels, 3, "linear", steps=2)

    def test_changed_final_loss_fails_the_same_frozen_parity_tolerance(self):
        bank, labels = self.fixture()
        original = MicrobatchCellTrainer.train
        def changed(instance, *args, **kwargs):
            report = original(instance, *args, **kwargs)
            report["final_loss"][0] += .01
            return report
        with patch.object(MicrobatchCellTrainer, "train", changed):
            with self.assertRaisesRegex(ValueError, "loss parity"):
                compare_condition(bank, labels, 3, "linear", steps=2)

    def test_symbolic_link_ancestor_cannot_redirect_checkpoint_output(self):
        bank, labels = self.fixture()
        report, state = compare_condition(bank, labels, 1, "linear", steps=1)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/"real").mkdir()
            (root/"linked").symlink_to(root/"real", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symbolic links"):
                save_checkpoint(root/"linked"/"output", report, state)
            self.assertEqual(list((root/"real").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
