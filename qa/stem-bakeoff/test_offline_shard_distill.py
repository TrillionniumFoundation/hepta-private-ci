"""Hermetic synthetic tests of the P6 offline student learning split boundary.

No licensed checkpoint, source authority, trained full-size Stem, or GPU is
involved. Real P5 shard I/O is used on the connected repo's CI runner.
"""
import hashlib
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
                expected_slot_sha256=hashlib.sha256(slots.numpy().tobytes()).hexdigest(),
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
            expected_slot_sha256=p.expected_slot_sha256,
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
            expected_slot_sha256=p.expected_slot_sha256,
            sample_digests=p.sample_digests)
        with self.assertRaises(OfflineDistillError):
            self.run_trial()
        self.cohorts["ood"] = PairedCohort(
            slots=self.cohorts["train"].slots.clone(), teacher_shard=p.teacher_shard,
            expected_source_sha256=p.expected_source_sha256,
            expected_npy_sha256=p.expected_npy_sha256,
            expected_slot_sha256=self.cohorts["train"].expected_slot_sha256,
            sample_digests=p.sample_digests)
        with self.assertRaisesRegex(OfflineDistillError, "duplicates"):
            self.run_trial()

    def test_student_slot_digest_pin_rejects_mutated_source_features(self):
        old = self.cohorts["calibration"]
        mutated = old.slots + 0.25
        self.cohorts["calibration"] = PairedCohort(
            slots=mutated, teacher_shard=old.teacher_shard,
            expected_source_sha256=old.expected_source_sha256,
            expected_npy_sha256=old.expected_npy_sha256,
            expected_slot_sha256=old.expected_slot_sha256,
            sample_digests=old.sample_digests)
        with self.assertRaisesRegex(OfflineDistillError, "source-slot digest mismatch"):
            self.run_trial()

    def test_optimizer_cannot_reach_external_cell_head(self):
        cell_parameter = torch.nn.Parameter(torch.ones(1))
        bad_optimizer = torch.optim.SGD(
            list(self.student.parameters()) + list(self.readout.parameters()) + [cell_parameter],
            lr=0.01)
        with self.assertRaisesRegex(OfflineDistillError, "optimizer must own"):
            self.run_trial(optimizer=bad_optimizer)

    def test_frozen_student_cannot_masquerade_as_student_training(self):
        self.student.requires_grad_(False)
        readout_only = torch.optim.SGD(self.readout.parameters(), lr=0.01)
        with self.assertRaisesRegex(OfflineDistillError, "optimizer must own"):
            self.run_trial(optimizer=readout_only)

    def test_bad_projection_aborts_before_train(self):
        bad_readout = torch.nn.Linear(8, 5)
        optimizer = torch.optim.SGD(list(self.student.parameters()) +
                                    list(bad_readout.parameters()), lr=0.01)
        original = [p.detach().clone() for p in self.student.parameters()]
        with self.assertRaisesRegex(OfflineDistillError, "projection"):
            self.run_trial(readout=bad_readout, optimizer=optimizer)
        self.assertTrue(all(torch.equal(a, b) for a, b in
                            zip(original, self.student.parameters())))


    def test_late_caller_mutation_cannot_replace_heldout_snapshot(self):
        observed = []

        def capture_eval_input(module, arguments):
            if not module.training:
                observed.append(arguments[0].detach().clone())

        hook = self.student.register_forward_pre_hook(capture_eval_input)
        self.addCleanup(hook.remove)
        original_heldout = self.cohorts["future_1"].slots.clone()
        def forward_then_mutate_caller(module, _inputs, _output):
            if module.training:
                with torch.no_grad():
                    self.cohorts["future_1"].slots.add_(7.0)

        mutation = self.student.register_forward_hook(forward_then_mutate_caller)
        self.addCleanup(mutation.remove)
        self.run_trial(steps=1)
        # Five frozen preflight observations, one train step, five heldouts.
        self.assertEqual(len(observed), 10)
        self.assertTrue(torch.equal(observed[2], original_heldout))
        self.assertTrue(torch.equal(observed[7], original_heldout))

    def test_inplace_student_cannot_rewrite_verified_training_inputs(self):
        class InPlaceStudent(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.gain = torch.nn.Parameter(torch.ones(1))
                self.observed = []

            def forward(self, slots):
                self.observed.append(slots.detach().clone())
                slots.add_(1.0)
                return slots * self.gain

        student = InPlaceStudent()
        optimizer = torch.optim.SGD(
            list(student.parameters()) + list(self.readout.parameters()), lr=0.05
        )
        source = self.cohorts["train"].slots.clone()
        self.run_trial(student=student, optimizer=optimizer, steps=2)
        # Initial eval, both train steps, and final eval must see the same
        # validated train slots even with in-place operations in forward().
        for index in (0, 5, 6, 7):
            self.assertTrue(torch.equal(student.observed[index], source))
        self.assertTrue(torch.equal(self.cohorts["train"].slots, source))


    def test_paired_split_receipts_bind_verified_student_and_teacher_bytes(self):
        report = self.run_trial(steps=1)
        receipts = report["paired_split_receipts"]
        self.assertEqual(set(receipts), set(SPLITS))
        self.assertEqual(len({r["teacher_feature_sha256"] for r in receipts.values()}),
                         len(SPLITS))
        for split, item in self.cohorts.items():
            with self.subTest(split=split):
                receipt = receipts[split]
                manifest = json.loads((item.teacher_shard / "manifest.json").read_text())
                self.assertEqual(receipt["source_manifest_sha256"],
                                 item.expected_source_sha256)
                self.assertEqual(receipt["student_slot_sha256"],
                                 item.expected_slot_sha256)
                self.assertEqual(receipt["teacher_npy_sha256"],
                                 item.expected_npy_sha256)
                self.assertEqual(receipt["teacher_feature_sha256"],
                                 manifest["raw_feature_sha256"])
                self.assertEqual(receipt["source_row_count"], item.slots.shape[0])
                self.assertEqual(receipt["student_slot_shape"], list(item.slots.shape))
                self.assertEqual(receipt["teacher_feature_shape"],
                                 list(manifest["shape"]))
        self.assertFalse(report["heldout_sources_independently_attested"])
        self.assertFalse(report["performance_qualified"])
        self.assertEqual(report["release"], "HOLD_NO_GO")

    def test_caller_replaces_cohort_object_after_preflight_without_rewriting_report(self):
        old = self.cohorts["future_2"]
        pinned_source = old.expected_source_sha256
        def forward_then_replace_caller_cohort(module, _inputs, _output):
            if module.training:
                self.cohorts["future_2"] = PairedCohort(
                    slots=old.slots + 9.0, teacher_shard=old.teacher_shard,
                    expected_source_sha256="e" * 64,
                    expected_npy_sha256="0" * 64,
                    expected_slot_sha256="1" * 64,
                    sample_digests=old.sample_digests)

        mutation = self.student.register_forward_hook(forward_then_replace_caller_cohort)
        self.addCleanup(mutation.remove)
        report = self.run_trial(steps=1)
        self.assertNotEqual(self.cohorts["future_2"].expected_source_sha256,
                            pinned_source)
        self.assertEqual(report["source_split_digests"]["future_2"], pinned_source)
        self.assertEqual(
            report["paired_split_receipts"]["future_2"]["source_manifest_sha256"],
            pinned_source)
        self.assertFalse(report["production_activation_allowed"])

    def test_caller_mutation_after_optimizer_step_cannot_rewrite_report_pins(self):
        untouched = self.cohorts["ood"].expected_slot_sha256
        eval_calls = [0]

        def after_step_eval_mutates_caller(module, _inputs, _output):
            if not module.training:
                eval_calls[0] += 1
                # Exactly five pre-train validation forwards precede this.
                if eval_calls[0] == 6:
                    with torch.no_grad():
                        self.cohorts["ood"].slots.add_(17.0)

        mutation = self.student.register_forward_hook(after_step_eval_mutates_caller)
        self.addCleanup(mutation.remove)
        report = self.run_trial(steps=1)
        self.assertEqual(report["paired_split_receipts"]["ood"]["student_slot_sha256"],
                         untouched)
        after_caller_mutation = hashlib.sha256(
            self.cohorts["ood"].slots.numpy().tobytes()).hexdigest()
        self.assertNotEqual(after_caller_mutation, untouched)
        self.assertFalse(report["production_activation_allowed"])

    def test_custom_optimizer_cannot_execute_foreign_step(self):
        foreign = torch.nn.Parameter(torch.ones(1))
        before = foreign.detach().clone()
        calls = [0]

        class ForeignSGD(torch.optim.SGD):
            def step(self, closure=None):
                calls[0] += 1
                with torch.no_grad():
                    foreign.add_(7)
                return super().step(closure)

        optimizer = ForeignSGD(list(self.student.parameters()) +
                               list(self.readout.parameters()), lr=0.05)
        with self.assertRaisesRegex(OfflineDistillError, "unsafe offline optimizer"):
            self.run_trial(optimizer=optimizer, steps=1)
        self.assertEqual(calls[0], 0)
        torch.testing.assert_close(foreign, before, rtol=0, atol=0)

    def test_step_override_and_global_optimizer_hooks_fail_closed(self):
        from torch.optim.optimizer import register_optimizer_step_pre_hook
        foreign = torch.nn.Parameter(torch.ones(1))
        before = foreign.detach().clone()
        calls = [0]

        def hostile(*_args, **_kwargs):
            calls[0] += 1
            with torch.no_grad():
                foreign.add_(3)

        self.optimizer.step = hostile
        with self.assertRaisesRegex(OfflineDistillError, "unsafe offline optimizer"):
            self.run_trial(steps=1)
        del self.optimizer.step

        handle = register_optimizer_step_pre_hook(hostile)
        try:
            with self.assertRaisesRegex(OfflineDistillError, "unsafe offline optimizer"):
                self.run_trial(steps=1)
        finally:
            handle.remove()
        self.assertEqual(calls[0], 0)
        torch.testing.assert_close(foreign, before, rtol=0, atol=0)

    def test_distinct_parameter_objects_sharing_storage_are_rejected(self):
        # Fresh IDs are insufficient: the foreign Readout may alias a Student
        # allocation via a distinct Parameter view.
        self.readout.weight = torch.nn.Parameter(self.student[0].weight.detach()[:4])
        aliased = torch.optim.SGD(list(self.student.parameters()) +
                                  list(self.readout.parameters()), lr=0.05)
        with self.assertRaisesRegex(OfflineDistillError, "unsafe offline optimizer"):
            self.run_trial(optimizer=aliased, steps=1)

    def test_optimizer_momentum_storage_alias_rejected_before_training(self):
        parameter = next(self.student.parameters())
        optimizer = torch.optim.SGD(list(self.student.parameters()) +
                                    list(self.readout.parameters()),
                                    lr=0.05, momentum=0.5)
        optimizer.state[parameter]["momentum_buffer"] = parameter.detach()
        with self.assertRaisesRegex(OfflineDistillError, "unsafe offline optimizer"):
            self.run_trial(optimizer=optimizer, steps=1)

    def test_late_global_registration_before_step_rejected(self):
        from torch.optim.optimizer import register_optimizer_step_pre_hook
        foreign = torch.nn.Parameter(torch.ones(1))
        before = foreign.detach().clone()
        handle = [None]
        calls = [0]

        def hostile(*_args):
            calls[0] += 1
            with torch.no_grad():
                foreign.add_(5)

        def register_late(module, _inputs, _output):
            if module.training and handle[0] is None:
                handle[0] = register_optimizer_step_pre_hook(hostile)

        registration = self.student.register_forward_hook(register_late)
        try:
            with self.assertRaisesRegex(OfflineDistillError, "unsafe offline optimizer"):
                self.run_trial(steps=1)
        finally:
            registration.remove()
            if handle[0] is not None:
                handle[0].remove()
        self.assertIsNotNone(handle[0])
        self.assertEqual(calls[0], 0)
        torch.testing.assert_close(foreign, before, rtol=0, atol=0)


if __name__ == "__main__":
    unittest.main()
