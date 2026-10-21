"""Hermetic synthetic tests of the P6 offline student learning split boundary.

No licensed checkpoint, source authority, trained full-size Stem, or GPU is
involved. Real P5 shard I/O is used on the connected repo's CI runner.
"""
import json
import pathlib
import sys
import tempfile
import unittest

try:
    import torch
except ImportError:
    torch = None

if torch is not None:
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from feature_shard import write_shard
    from offline_shard_distill import PairedCohort, OfflineDistillError, run_offline_distillation, SPLITS


@unittest.skipUnless(torch is not None, "optional pinned Torch shadow experiment")
class OfflineShardDistillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.teacher = "embeddinggemma2_740m"
        self.revision = "a" * 40
        self.checkpoint = "b" * 64
        self.cohorts = {}
        torch.manual_seed(13)
        for idx, split in enumerate(SPLITS):
            # Distinct source rows and distinct model-ready input slots.
            slots = torch.randn(2, 3, 8) + idx
            targets = torch.tanh(slots.mean(1)[:, :4] * 0.6 + idx * 0.05)
            source = str(idx + 1) * 64
            path = self.root / split
            receipt = write_shard(path, targets, candidate=self.teacher,
                                  revision=self.revision,
                                  checkpoint_inventory_sha256=self.checkpoint,
                                  ordered_source_manifest_sha256=source)
            self.cohorts[split] = PairedCohort(
                slots=slots, teacher_shard=path,
                expected_source_sha256=source,
                expected_npy_sha256=receipt["npy_sha256"],
                sample_digests=("c" * 63 + str(idx), "d" * 63 + str(idx)),
            )
        self.student = torch.nn.Sequential(torch.nn.Linear(8, 8), torch.nn.Tanh())
        self.readout = torch.nn.Linear(8, 4)
        self.optimizer = torch.optim.SGD(
            list(self.student.parameters()) + list(self.readout.parameters()), lr=0.05)

    def run_trial(self, **overrides):
        kwargs = dict(student=self.student, readout=self.readout,
                      optimizer=self.optimizer, cohorts=self.cohorts,
                      student_candidate="hepta_latent_150m",
                      teacher_candidate=self.teacher, teacher_revision=self.revision,
                      checkpoint_inventory_sha256=self.checkpoint,
                      student_width=8, target_width=4, steps=12)
        kwargs.update(overrides)
        return run_offline_distillation(**kwargs)

    def test_real_tiny_gradient_step_train_only_and_non_authorizing(self):
        report = self.run_trial()
        self.assertEqual(report["optimizer_steps_train_only"], 12)
        self.assertEqual(report["optimizer_steps_heldout"], 0)
        self.assertLess(report["loss_after"]["train"], report["loss_before"]["train"])
        self.assertEqual(set(report["loss_after"]), set(SPLITS))
        self.assertFalse(report["student_checkpoint_qualified"])
        self.assertFalse(report["pretrained_weights_independently_attested"])
        self.assertFalse(report["production_activation_allowed"])
        self.assertEqual(report["authority"], "DENY_ALL")

    def test_source_overlap_rejected_before_optimizer_changes(self):
        p = self.cohorts["future_1"]
        self.cohorts["future_1"] = PairedCohort(
            slots=p.slots, teacher_shard=p.teacher_shard,
            expected_source_sha256=p.expected_source_sha256,
            expected_npy_sha256=p.expected_npy_sha256,
            sample_digests=self.cohorts["train"].sample_digests)
        original = [v.detach().clone() for v in self.student.parameters()]
        with self.assertRaisesRegex(OfflineDistillError, "overlapping"):
            self.run_trial()
        self.assertTrue(all(torch.equal(a, b) for a, b in
                            zip(original, self.student.parameters())))

    def test_teacher_identity_or_source_binding_cannot_change(self):
        for field, value in (("teacher_candidate", "t5gemma2_encoder_270m"),
                             ("checkpoint_inventory_sha256", "f" * 64),
                             ("teacher_revision", "c" * 40)):
            with self.subTest(field=field), self.assertRaises(OfflineDistillError):
                self.run_trial(**{field: value})
        manifest = self.root / "train" / "manifest.json"
        contents = json.loads(manifest.read_text())
        contents["authority"] = "GRANT_ALL"
        manifest.write_text(json.dumps(contents))
        with self.assertRaises(OfflineDistillError):
            self.run_trial()

    def test_invalid_heldout_input_or_duplicate_batch_prevents_train(self):
        p = self.cohorts["ood"]
        self.cohorts["ood"] = PairedCohort(
            slots=torch.full_like(p.slots, float("nan")), teacher_shard=p.teacher_shard,
            expected_source_sha256=p.expected_source_sha256,
            expected_npy_sha256=p.expected_npy_sha256,
            sample_digests=p.sample_digests)
        with self.assertRaises(OfflineDistillError):
            self.run_trial()
        self.cohorts["ood"] = PairedCohort(
            slots=self.cohorts["train"].slots.clone(), teacher_shard=p.teacher_shard,
            expected_source_sha256=p.expected_source_sha256,
            expected_npy_sha256=p.expected_npy_sha256,
            sample_digests=p.sample_digests)
        with self.assertRaisesRegex(OfflineDistillError, "duplicates"):
            self.run_trial()

    def test_optimizer_cannot_reach_external_cell_head(self):
        cell_parameter = torch.nn.Parameter(torch.ones(1))
        bad_optimizer = torch.optim.SGD(
            list(self.student.parameters()) + list(self.readout.parameters()) + [cell_parameter],
            lr=0.01)
        with self.assertRaisesRegex(OfflineDistillError, "optimizer must own"):
            self.run_trial(optimizer=bad_optimizer)

    def test_bad_projection_aborts_before_train(self):
        bad_readout = torch.nn.Linear(8, 5)
        optimizer = torch.optim.SGD(list(self.student.parameters()) +
                                    list(bad_readout.parameters()), lr=0.01)
        original = [p.detach().clone() for p in self.student.parameters()]
        with self.assertRaisesRegex(OfflineDistillError, "projection"):
            self.run_trial(readout=bad_readout, optimizer=optimizer)
        self.assertTrue(all(torch.equal(a, b) for a, b in
                            zip(original, self.student.parameters())))


if __name__ == "__main__":
    unittest.main()
