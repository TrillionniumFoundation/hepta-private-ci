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
