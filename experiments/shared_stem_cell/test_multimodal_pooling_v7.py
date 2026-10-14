"""Contract tests for model-native pooling, not real pretrained-model efficacy."""
import unittest
from types import SimpleNamespace

import torch

from multimodal_alignment_contract import canonical, sha
from multimodal_bridge import ContractError
from multimodal_native_pool_v7 import pool_hidden_state
from multimodal_pinned_candidate import _encode, _v6_material_gate
from multimodal_real_encoder import PROFILE_SCHEMA, feature_rows, validated_profile
from test_multimodal_real_encoder import FakeBackend, profile as base_profile, train_rows


class PoolingKernelTests(unittest.TestCase):
    def test_cls_is_first_token_and_masked_mean_is_not(self):
        hidden = torch.tensor([[[2., 4.], [6., 8.], [100., 100.]],
                               [[3., 5.], [7., 9.], [-9., -9.]]])
        mask = torch.tensor([[1, 1, 0], [1, 1, 0]], dtype=torch.int64)
        self.assertTrue(torch.equal(pool_hidden_state(hidden, mask, "cls-first-token"),
                                    torch.tensor([[2., 4.], [3., 5.]])))
        self.assertTrue(torch.equal(pool_hidden_state(hidden, mask, "attention-mask-mean"),
                                    torch.tensor([[4., 6.], [5., 7.]])))

    def test_invalid_masks_and_hidden_states_reject(self):
        h = torch.ones(2, 2, 3)
        for mask in [torch.tensor([[0,1],[1,1]]),torch.tensor([[1,2],[1,1]]),
                     torch.ones(3,2,dtype=torch.int),torch.ones(2,2,dtype=torch.float32)]:
            with self.subTest(mask=mask), self.assertRaises(ValueError):
                pool_hidden_state(h, mask, "cls-first-token")
        for bad in [torch.full((2,2,3),float("nan")),torch.zeros(2,2,0),
                    torch.ones(2,3),torch.ones(2,2,3,dtype=torch.int32)]:
            with self.assertRaises(ValueError):
                pool_hidden_state(bad, torch.ones(2,2,dtype=torch.int64), "attention-mask-mean")
        with self.assertRaises(ValueError):
            pool_hidden_state(h,torch.ones(2,2,dtype=torch.long),"unregistered")


class NativeIngressTests(unittest.TestCase):
    @staticmethod
    def cls_profile():
        _, mean = base_profile()
        raw = {**mean, "pooling": "cls-first-token", "normalization": "unit_l2"}
        return validated_profile(raw, sha(canonical(raw)))

    def test_profile_seals_pooling_and_different_feature_identity(self):
        mean, _ = base_profile()
        cls = self.cls_profile()
        self.assertNotEqual(mean.profile_digest, cls.profile_digest)
        self.assertEqual(cls.pooling, "cls-first-token")
        class Explicit(FakeBackend):
            def encode(self, texts, *, pooling="attention-mask-mean"):
                self.requested = pooling
                return super().encode(texts)
        a = Explicit(mean.snapshot_digest)
        b = Explicit(cls.snapshot_digest)
        _, old_receipt = feature_rows(train_rows(), "train", a, mean)
        _, new_receipt = feature_rows(train_rows(), "train", b, cls)
        self.assertEqual(b.requested, "cls-first-token")
        self.assertEqual(new_receipt["pooling"], "cls-first-token")
        self.assertNotEqual(old_receipt["feature_encoder_identity"],
                            new_receipt["feature_encoder_identity"])
        self.assertEqual(a.forward_calls, b.forward_calls)

    def test_cls_requires_explicit_backend_support(self):
        cls = self.cls_profile()
        with self.assertRaises(TypeError):
            feature_rows(train_rows(),"train",FakeBackend(cls.snapshot_digest),cls)

    def test_v5_candidate_dispatch_uses_pooling_not_implicit_mean(self):
        cls = self.cls_profile()
        class Explicit:
            def __init__(self):
                self.forward_calls = 0
                self.seen = []
            def encode(self, texts, *, pooling):
                self.seen.append(pooling)
                self.forward_calls += 1
                return torch.tensor([[float(i + 1), 1.] for i in range(len(texts))])
        backend = Explicit()
        out = _encode(backend,["q0","q1","q2","q3"],cls)
        self.assertEqual(tuple(out.shape),(4,2))
        self.assertEqual(backend.seen,["cls-first-token"]*2)
        norms=torch.linalg.vector_norm(out,dim=1)
        self.assertTrue(torch.allclose(norms,torch.ones_like(norms)))

    def test_official_granite_named_cli_rejects_mean_even_with_signed_material(self):
        _, mean = base_profile()
        args = SimpleNamespace(candidate="granite_97m",operator_trust="trust",
                               operator_trust_sha256="a"*64,signed_claim="claim",
                               signed_claim_sha256="b"*64)
        with self.assertRaisesRegex(ContractError,"CLS pooling"):
            _v6_material_gate(args,{},"unused",mean)
        with self.assertRaises(ContractError):
            _v6_material_gate(SimpleNamespace(candidate="tiny_random",
                operator_trust="trust",operator_trust_sha256="a"*64,
                signed_claim="claim",signed_claim_sha256="b"*64),{},"unused",mean)


if __name__ == "__main__":
    unittest.main()
