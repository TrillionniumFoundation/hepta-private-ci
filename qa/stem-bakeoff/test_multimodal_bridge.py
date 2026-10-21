import pathlib
import sys
import unittest

try:
    import torch
except ImportError:
    torch = None

if torch is not None:
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from multimodal_bridge import (MultimodalSlotizer, LatentBridgeError, shadow_distill_step)
    from native_latent import build_encoder, StemSpec


@unittest.skipUnless(torch is not None, 'optional PyTorch CPU smoke')
class SharedMultimodalBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.manual_seed(31)
        torch.set_num_threads(1)

    @staticmethod
    def stem():
        return MultimodalSlotizer({'text': 32, 'image': 32, 'audio': 32},
                                  latent_width=32, slots=4, heads=4)

    def test_pooled_embeddings_are_one_token_and_missingness_explicit(self):
        s = self.stem()
        out = s({'text': torch.ones(2, 32), 'image': torch.randn(2, 4, 32)},
                source_digests={'text': 'a' * 64, 'image': 'b' * 64}, generation=5)
        self.assertEqual(out.slots.shape, (2, 4, 32))
        self.assertEqual(out.global_feature.shape, (2, 32))
        self.assertEqual(out.missing_mask, (False, False, True, True, True))
        self.assertEqual(out.authority, 'DENY_ALL')
        self.assertFalse(out.production_activation_allowed)
        self.assertEqual(len(out.source_manifest_digest), 64)

    def test_temporal_timestamps_bound_and_strictly_ordered(self):
        s = self.stem()
        features = {'audio': torch.randn(2, 3, 32)}
        with self.assertRaises(LatentBridgeError):
            s(features, source_digests={'audio': 'c' * 64}, generation=5)
        with self.assertRaises(LatentBridgeError):
            s(features, source_digests={'audio': 'c' * 64}, generation=5,
              timestamps={'audio': torch.tensor([[0.,2.,1.],[0.,1.,2.]])})
        out = s(features, source_digests={'audio': 'c' * 64}, generation=5,
                timestamps={'audio': torch.tensor([[0.,1.,2.],[0.,1.,2.]])})
        self.assertEqual(out.slots.shape, (2, 4, 32))

    def test_material_bytes_and_temporal_tags_are_digest_bound(self):
        from multimodal_bridge import _tensor_bytes_sha256
        bridge = self.stem()
        features = {'audio': torch.randn(2, 3, 32)}
        digests = {'audio': 'd' * 64}
        times = {'audio': torch.tensor([[0., 1., 2.], [0., 1., 2.]])}
        original = bridge(features, source_digests=digests, generation=7,
                          timestamps=times)
        repeated = bridge(features, source_digests=digests, generation=7,
                          timestamps=times)
        changed_time = bridge(features, source_digests=digests, generation=7,
                              timestamps={'audio': times['audio'] + 0.25})
        changed_feature = bridge({'audio': features['audio'] + 0.125},
                                  source_digests=digests, generation=7,
                                  timestamps=times)
        self.assertEqual(original.source_manifest_digest,
                         repeated.source_manifest_digest)
        self.assertNotEqual(original.source_manifest_digest,
                            changed_time.source_manifest_digest)
        self.assertNotEqual(original.source_manifest_digest,
                            changed_feature.source_manifest_digest)
        # A BF16 teacher tensor can be hashed losslessly without casting to FP32.
        self.assertEqual(len(_tensor_bytes_sha256(torch.ones(2, 3, dtype=torch.bfloat16))), 64)

    def test_modality_and_time_receipts_use_frozen_projected_snapshots(self):
        bridge = self.stem()
        original = torch.randn(2, 3, 32)
        original_times = torch.tensor([[0., 1., 2.], [0., 1., 2.]])
        source_digests = {'audio': 'e' * 64}
        expected = bridge({'audio': original.clone()}, source_digests=source_digests,
                          generation=9, timestamps={'audio': original_times.clone()})
        caller_features = original.clone()
        caller_times = original_times.clone()

        def mutate_original_caller(_module, _arguments, _output):
            # Runs after projector computation, before temporal phase and digest.
            # Both must remain tied to the bytes used by the projection.
            with torch.no_grad():
                caller_features.add_(11.0)
                caller_times.add_(10.0)

        hook = bridge.projectors['audio'].register_forward_hook(mutate_original_caller)
        try:
            observed = bridge({'audio': caller_features},
                              source_digests=source_digests, generation=9,
                              timestamps={'audio': caller_times})
        finally:
            hook.remove()
        self.assertFalse(torch.equal(caller_features, original))
        self.assertFalse(torch.equal(caller_times, original_times))
        self.assertEqual(observed.source_manifest_digest,
                         expected.source_manifest_digest)
        torch.testing.assert_close(observed.slots, expected.slots, rtol=0, atol=0)

    def test_multimodal_batch_and_element_budgets_fail_closed(self):
        bridge = self.stem()
        with self.assertRaisesRegex(LatentBridgeError, "invalid/nonfinite"):
            bridge({'text': torch.ones(9, 32)}, source_digests={'text': 'a' * 64},
                   generation=1)
        big_bridge = MultimodalSlotizer({'text': 512, 'image': 512},
                                         latent_width=32, slots=4, heads=4,
                                         max_tokens=1024)
        large = torch.zeros(8, 300, 512)
        with self.assertRaisesRegex(LatentBridgeError, "token/element budget"):
            big_bridge({'text': large, 'image': large},
                       source_digests={'text': 'a' * 64, 'image': 'b' * 64},
                       generation=1)

    def test_unknown_model_modality_wrong_digest_bad_token_and_generation_rejected(self):
        s = self.stem()
        for features,digests,gen in [
            ({'unsupported': torch.zeros(2, 32)}, {'unsupported':'a'*64}, 1),
            ({'text': torch.zeros(2, 31)}, {'text':'a'*64}, 1),
            ({'text': torch.zeros(2, 32)}, {'text':'short'}, 1),
            ({'text': torch.zeros(2, 32)}, {'text':'a'*64}, 0),
            ({'text': torch.full((2, 32), float('nan'))}, {'text':'a'*64}, 1),
        ]:
            with self.subTest(features=tuple(features), gen=gen):
                with self.assertRaises(LatentBridgeError):
                    s(features, source_digests=digests, generation=gen)
        with self.assertRaises(LatentBridgeError):
            s({'image': torch.randn(2, 300, 32)}, source_digests={'image':'a'*64}, generation=1)

    def test_foreign_cell_or_teacher_optimizer_parameters_rejected_before_forward(self):
        bridge = self.stem()
        student = build_encoder(StemSpec('tiny_training_only', 32, 1, 4),
                                device='cpu', trainable=True)
        foreign_cell = torch.nn.Linear(32, 1)
        optimizer = torch.optim.AdamW(
            list(bridge.parameters()) + list(student.parameters())
            + list(foreign_cell.parameters()), lr=0.01)
        calls = [0]

        def count_projection(_module, _inputs, _outputs):
            calls[0] += 1

        hook = bridge.projectors['text'].register_forward_hook(count_projection)
        try:
            with self.assertRaisesRegex(LatentBridgeError, "foreign, frozen or duplicate"):
                shadow_distill_step(
                    student, bridge, {'text': torch.ones(2, 32)},
                    {'text': 'a' * 64}, torch.ones(2, 32), optimizer,
                    generation=1)
        finally:
            hook.remove()
        self.assertEqual(calls[0], 0)
        self.assertIsNone(foreign_cell.weight.grad)

    def test_optimizer_param_injection_by_projection_hook_prevents_weight_step(self):
        bridge = self.stem()
        student = build_encoder(StemSpec('tiny_training_only', 32, 1, 4),
                                device='cpu', trainable=True)
        optimizer = torch.optim.SGD(
            list(bridge.parameters()) + list(student.parameters()), lr=0.1)
        foreign_cell_weight = torch.nn.Parameter(torch.ones(1))
        before = bridge.projectors['text'].weight.detach().clone()

        def inject_foreign_parameter(_module, _inputs, _outputs):
            optimizer.param_groups[0]['params'].append(foreign_cell_weight)

        hook = bridge.projectors['text'].register_forward_hook(inject_foreign_parameter)
        try:
            with self.assertRaisesRegex(LatentBridgeError, "foreign, frozen or duplicate"):
                shadow_distill_step(
                    student, bridge, {'text': torch.ones(2, 32)},
                    {'text': 'a' * 64}, torch.ones(2, 32), optimizer,
                    generation=1)
        finally:
            hook.remove()
        torch.testing.assert_close(bridge.projectors['text'].weight, before, rtol=0, atol=0)
        self.assertIsNone(foreign_cell_weight.grad)

    def test_teacher_target_frozen_before_hook_mutation_and_receipted(self):
        from copy import deepcopy
        from multimodal_bridge import _tensor_bytes_sha256

        slotizer = self.stem()
        control_slotizer = deepcopy(slotizer)
        student = build_encoder(StemSpec('tiny_training_only', 32, 1, 4),
                                device='cpu', trainable=True)
        control_student = deepcopy(student)
        optimizer = torch.optim.SGD(list(slotizer.parameters())
                                    + list(student.parameters()), lr=0.001)
        control_optimizer = torch.optim.SGD(list(control_slotizer.parameters())
                                            + list(control_student.parameters()),
                                            lr=0.001)
        inputs = {'text': torch.randn(2, 32)}
        caller_target = torch.randn(2, 32, requires_grad=True)
        frozen_target = caller_target.detach().clone()
        original_sha = _tensor_bytes_sha256(frozen_target)
        calls = [0]

        def mutate_caller(_module, _inputs, _output):
            calls[0] += 1
            with torch.no_grad():
                caller_target.add_(10)

        hook_a = slotizer.projectors['text'].register_forward_hook(mutate_caller)
        hook_b = student.register_forward_hook(mutate_caller)
        try:
            got = shadow_distill_step(
                student, slotizer, inputs, {'text': 'a' * 64},
                caller_target, optimizer, generation=1)
        finally:
            hook_b.remove()
            hook_a.remove()
        control = shadow_distill_step(
            control_student, control_slotizer, inputs, {'text': 'a' * 64},
            frozen_target, control_optimizer, generation=1)
        self.assertEqual(calls[0], 2)
        self.assertNotEqual(_tensor_bytes_sha256(caller_target), original_sha)
        self.assertEqual(got['teacher_target_sha256'], original_sha)
        self.assertEqual(got['paired_distillation_sha256'],
                         control['paired_distillation_sha256'])
        self.assertAlmostEqual(got['loss'], control['loss'], places=6)
        for actual, expected in zip(slotizer.parameters(), control_slotizer.parameters()):
            torch.testing.assert_close(actual, expected, rtol=0, atol=0)
        for actual, expected in zip(student.parameters(), control_student.parameters()):
            torch.testing.assert_close(actual, expected, rtol=0, atol=0)
        self.assertIsNone(caller_target.grad)

    def test_malformed_teacher_target_rejected_before_projector(self):
        slotizer = self.stem()
        student = build_encoder(StemSpec('tiny_training_only', 32, 1, 4),
                                device='cpu', trainable=True)
        optimizer = torch.optim.SGD(list(slotizer.parameters())
                                    + list(student.parameters()), lr=0.001)
        calls = [0]

        def count_forward(_module, _inputs, _output):
            calls[0] += 1

        hook = slotizer.projectors['text'].register_forward_hook(count_forward)
        try:
            for target in (torch.ones(9, 32), torch.ones(2, 31),
                           torch.ones(2, 32, dtype=torch.int32),
                           torch.full((2, 32), float('nan'))):
                with self.subTest(target_shape=tuple(target.shape),
                                  target_dtype=str(target.dtype)):
                    with self.assertRaises(LatentBridgeError):
                        shadow_distill_step(student, slotizer, {'text': torch.ones(2, 32)},
                                            {'text': 'a' * 64}, target, optimizer,
                                            generation=1)
        finally:
            hook.remove()
        self.assertEqual(calls[0], 0)

    def test_teacher_is_detached_and_small_student_offline_step_changes_weights(self):
        stem = self.stem()
        student = build_encoder(StemSpec('tiny_training_only', 32, 1, 4),
                                device='cpu', trainable=True)
        optimizer = torch.optim.AdamW(list(stem.parameters()) + list(student.parameters()), lr=0.01)
        teacher_feature = torch.ones(2, 32, requires_grad=True)
        teacher_goal = torch.randn(2, 32, requires_grad=True)
        prior = stem.projectors['text'].weight.detach().clone()
        out = shadow_distill_step(student, stem, {'text': teacher_feature},
                                  {'text': 'a'*64}, teacher_goal,
                                  optimizer, generation=1)
        self.assertGreater(out['loss'], 0)
        self.assertFalse(out['production_activation_allowed'])
        self.assertFalse(out['checkpoint_qualified'])
        self.assertIsNone(teacher_feature.grad)
        self.assertIsNone(teacher_goal.grad)
        self.assertFalse(torch.allclose(prior, stem.projectors['text'].weight))


if __name__ == '__main__':
    unittest.main()
