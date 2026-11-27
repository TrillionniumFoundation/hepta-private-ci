"""Fixture-only behavior tests; scores here are not real-data evidence."""

import copy
from dataclasses import replace
import hashlib
import io
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
import torch

from cell_evolution_snapshot import EvolutionError, WithdrawalViewV1, digest
from cell_head_training import _state_digest
from feature_shard import write_shard
from offline_shard_distill import OfflineDistillError, PairedCohort, SPLITS
from shared_coco_inputs import canonical, control_cohorts, raw_slots, source_digest
from shared_student_training import (TEACHER, TEACHER_INVENTORY, TEACHER_REVISION,
    load_shared_student, new_student, tensor_sha, train_shared_student)


class Withdrawals:
    def __init__(self):
        self.view = WithdrawalViewV1("fixture-shared-student")

    def __call__(self):
        return self.view

    def revoke(self, source):
        self.view = replace(self.view, epoch=self.view.epoch + 1,
                            revoked_source_digests=tuple(sorted(set(self.view.revoked_source_digests) | {source})))


def fixture(root):
    generator = torch.Generator().manual_seed(101)
    cohorts, records = {}, {}
    for split, name in enumerate(SPLITS):
        slots = torch.randn((2, 32, 64), generator=generator) * 0.1
        slots[:, :, 63] = 1
        target = torch.randn((2, 1536), generator=generator) * 0.1
        records[name] = []
        for row in range(2):
            image = 10 * split + row
            record = {"image_id": image, "caption_id": 100 + image, "source_group_id": f"coco2017:{image}"}
            for kind in ("image", "text", "teacher_image_source", "teacher_text_source"):
                record[kind + "_sha256"] = digest(["fixture", split, row, kind])
            records[name].append({**record, "source_record_sha256": digest(record)})
        destination = root / name
        receipt = write_shard(destination, target, candidate=TEACHER, revision=TEACHER_REVISION,
            checkpoint_inventory_sha256=TEACHER_INVENTORY, ordered_source_manifest_sha256=digest(records[name]))
        cohorts[name] = PairedCohort(slots, destination, digest(records[name]), receipt["npy_sha256"],
            tensor_sha(slots), tuple(r["source_record_sha256"] for r in records[name]))
    return cohorts, records


class SharedStudentTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.storage = tempfile.TemporaryDirectory()
        cls.root = Path(cls.storage.name)
        cls.cohorts, cls.records = fixture(cls.root)
        cls.teacher_before = {name: (cls.root / name / "features.npy").read_bytes() for name in SPLITS}
        cls.slots_before = {name: value.slots.clone() for name, value in cls.cohorts.items()}
        cls.student, cls.predictions = train_shared_student(cls.cohorts, cls.records, cls.root / "trained",
            Withdrawals(), seed=7, teacher_bank_sha256="a" * 64, input_manifest_sha256="b" * 64,
            scope_id="fixture-shared-student", steps=3)

    @classmethod
    def tearDownClass(cls):
        cls.storage.cleanup()

    def test_real_shared_backbone_and_readout_update_with_exact_cost_ledger(self):
        initial = new_student(7)
        for name in ("student", "readout"):
            self.assertNotEqual(_state_digest(initial[name]), _state_digest(self.student._model[name]))
        report = self.student.report
        self.assertEqual(report["parameter_count"], 133312)
        self.assertEqual(report["resident_tensor_bytes"], 533248)
        self.assertEqual(report["gradient_bytes_before_clear"], 533248)
        self.assertEqual(report["parameter_example_updates"], 133312 * 2 * 3)
        self.assertEqual(report["optimizer_state_bytes"], 0)
        self.assertEqual(report["observed_forwards"], {"student_module_forwards": 23,
            "student_example_calls": 46, "readout_module_forwards": 23, "readout_example_calls": 46})
        self.assertEqual(report["observed_forwards_by_phase"]["optimizer_train"], {
            "student_module_forwards": 3, "student_example_calls": 6,
            "readout_module_forwards": 3, "readout_example_calls": 6})
        self.assertEqual(report["training"]["optimizer_steps_heldout"], 0)
        self.assertFalse(report["old_cell_or_feature_generation_reuse_allowed"])
        self.assertTrue(all(not p.requires_grad and p.grad is None for p in self.student._model.parameters()))
        for name in SPLITS:
            self.assertEqual((self.root / name / "features.npy").read_bytes(), self.teacher_before[name])
            self.assertTrue(torch.equal(self.cohorts[name].slots, self.slots_before[name]))

    def test_real_npz_reload_has_identical_predictions(self):
        loaded = load_shared_student(self.root / "trained", expected_manifest_sha256=self.student.manifest_sha256,
                                     withdrawal_provider=Withdrawals())
        for name in SPLITS:
            result = loaded.predict_slots(self.cohorts[name].slots, role=name,
                expected_slots_sha256=self.cohorts[name].expected_slot_sha256, withdrawal_provider=Withdrawals())
            self.assertTrue(np.array_equal(result["teacher_prediction"].numpy(), self.predictions["after:" + name]))
            self.assertEqual(result["shared_slots"].shape, self.cohorts[name].slots.shape)
        with self.assertRaisesRegex(ValueError, "binding"):
            loaded.predict_slots(self.cohorts["ood"].slots, role="train",
                expected_slots_sha256=self.cohorts["ood"].expected_slot_sha256, withdrawal_provider=Withdrawals())

    def test_group_overlap_and_mutated_holdout_fail_before_any_student_forward(self):
        bad_records = copy.deepcopy(self.records)
        bad_records["ood"][0] = copy.deepcopy(self.records["train"][0])
        changed = dict(self.cohorts)
        changed["ood"] = replace(changed["ood"], slots=changed["ood"].slots + 0.1)
        for cohorts, records in ((self.cohorts, bad_records), (changed, self.records)):
            with patch("shared_student_training.new_student", side_effect=AssertionError("preflight ran model")):
                with self.assertRaises((ValueError, OfflineDistillError)):
                    train_shared_student(cohorts, records, self.root / "never-written", Withdrawals(), seed=7,
                        teacher_bank_sha256="a" * 64, input_manifest_sha256="b" * 64, scope_id="fixture-shared-student")
            self.assertFalse((self.root / "never-written").exists())

    def test_training_ancestor_revocation_latches_and_prevents_frozen_inference(self):
        withdrawals = Withdrawals()
        loaded = load_shared_student(self.root / "trained", expected_manifest_sha256=self.student.manifest_sha256,
                                     withdrawal_provider=withdrawals)
        source = self.records["train"][0]["teacher_image_source_sha256"]
        withdrawals.revoke(source)
        with patch.object(loaded._model["student"], "forward", side_effect=AssertionError("withdrawn student ran")):
            with self.assertRaises(EvolutionError):
                loaded.predict_slots(self.cohorts["ood"].slots, role="ood",
                    expected_slots_sha256=self.cohorts["ood"].expected_slot_sha256, withdrawal_provider=withdrawals)
        withdrawals.view = WithdrawalViewV1("fixture-shared-student")
        with self.assertRaisesRegex(EvolutionError, "frontier"):
            loaded.predict_slots(self.cohorts["ood"].slots, role="ood",
                expected_slots_sha256=self.cohorts["ood"].expected_slot_sha256, withdrawal_provider=withdrawals)
        withdrawals.revoke(source)
        with self.assertRaises(EvolutionError):
            load_shared_student(self.root / "trained", expected_manifest_sha256=self.student.manifest_sha256,
                                withdrawal_provider=withdrawals)

    def test_mid_inference_withdrawal_discards_output(self):
        withdrawals = Withdrawals()
        loaded = load_shared_student(self.root / "trained", expected_manifest_sha256=self.student.manifest_sha256,
                                     withdrawal_provider=withdrawals)
        source = self.records["train"][0]["image_sha256"]
        hook = loaded._model["readout"].register_forward_hook(lambda module, args, result: withdrawals.revoke(source))
        try:
            with self.assertRaises(EvolutionError):
                loaded.predict_slots(self.cohorts["ood"].slots, role="ood",
                    expected_slots_sha256=self.cohorts["ood"].expected_slot_sha256, withdrawal_provider=withdrawals)
        finally:
            hook.remove()

    def test_artifact_input_and_in_memory_tampering_fail_closed(self):
        directory = self.root / "corrupt"
        shutil.copytree(self.root / "trained", directory)
        weights = directory / "weights.npz"
        data = bytearray(weights.read_bytes()); data[-1] ^= 1; weights.write_bytes(data)
        with self.assertRaises(ValueError):
            load_shared_student(directory, expected_manifest_sha256=self.student.manifest_sha256,
                                withdrawal_provider=Withdrawals())
        for missing_pin in (None, "", "x" * 64):
            with self.assertRaises(ValueError):
                load_shared_student(self.root / "trained", expected_manifest_sha256=missing_pin,
                                    withdrawal_provider=Withdrawals())
        loaded = load_shared_student(self.root / "trained", expected_manifest_sha256=self.student.manifest_sha256,
                                     withdrawal_provider=Withdrawals())
        slots = self.cohorts["ood"].slots
        for invalid in (slots + 0.1, slots.double(), slots.clone().requires_grad_(True)):
            with self.assertRaises(ValueError):
                loaded.predict_slots(invalid, role="ood", expected_slots_sha256=tensor_sha(slots), withdrawal_provider=Withdrawals())
        with torch.no_grad():
            next(loaded._model.parameters()).add_(0.1)
        with self.assertRaises(ValueError):
            loaded.predict_slots(slots, role="ood", expected_slots_sha256=tensor_sha(slots), withdrawal_provider=Withdrawals())

    def test_raw_images_and_captions_are_independent_of_teacher_features(self):
        image = Image.new("RGB", (16, 16), (40, 90, 200))
        stream = io.BytesIO(); image.save(stream, format="JPEG"); data = stream.getvalue()
        decoded = Image.open(io.BytesIO(data)).convert("RGB")
        source = {"image_id": 5, "caption_id": 6, "width": 16, "height": 16, "text": "fixture caption",
            "image_sha256": hashlib.sha256(data).hexdigest(),
            "text_sha256": hashlib.sha256(b"fixture caption").hexdigest(),
            "decoded_rgb_sha256": hashlib.sha256(canonical([16, 16, "RGB"]) + decoded.tobytes()).hexdigest()}
        original = raw_slots(data, source)
        changed = {**source, "text": "a different caption", "text_sha256": hashlib.sha256(b"a different caption").hexdigest()}
        updated = raw_slots(data, changed)
        self.assertTrue(torch.equal(original[:16], updated[:16]))
        self.assertFalse(torch.equal(original[16:], updated[16:]))
        self.assertNotEqual(source_digest(source, "text"), source_digest(changed, "text"))
        controls = {arm: control_cohorts(self.cohorts, arm) for arm in ("multimodal", "image_only", "text_only")}
        for name in SPLITS:
            self.assertTrue(torch.equal(controls["image_only"][name].slots[:, :16], self.cohorts[name].slots[:, :16]))
            self.assertEqual(torch.count_nonzero(controls["image_only"][name].slots[:, 16:]), 0)
            self.assertEqual(torch.count_nonzero(controls["text_only"][name].slots[:, :16]), 0)
            self.assertEqual(controls["text_only"][name].expected_npy_sha256, self.cohorts[name].expected_npy_sha256)

    def test_three_controls_start_equal_and_use_same_update_budget(self):
        reports = []
        for arm in ("multimodal", "image_only", "text_only"):
            student, _ = train_shared_student(control_cohorts(self.cohorts, arm), self.records,
                self.root / ("control-" + arm), Withdrawals(), seed=17, teacher_bank_sha256="a" * 64,
                input_manifest_sha256="b" * 64, scope_id="fixture-shared-student", steps=1)
            reports.append(student.report)
        self.assertEqual(len({r["initial_tensor_sha256"] for r in reports}), 1)
        self.assertEqual(len({r["trained_tensor_sha256"] for r in reports}), 3)
        for key in ("parameter_example_updates", "parameter_count", "observed_forwards"):
            self.assertEqual([r[key] for r in reports], [reports[0][key]] * 3)


if __name__ == "__main__":
    unittest.main()
