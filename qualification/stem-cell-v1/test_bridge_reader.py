import copy
import io
import unittest

import torch
from torch.nn import functional as F

from bridge_reader import BridgeReader, FactBridge, WideReader, build_reader, reader_identity
from token_reader import TokenReader


def fixture():
    generator = torch.Generator().manual_seed(902)
    facts = torch.randn(4, 3, 4, 384, generator=generator)
    question = torch.randn(4, 2, 384, generator=generator)
    candidate = torch.randn(4, 2, 384, generator=generator)
    fact_mask = torch.ones(4, 3, 4, dtype=torch.bool)
    fact_mask[:, 1, -1] = False
    return (facts, question, candidate, fact_mask,
            torch.ones(4, 2, dtype=torch.bool), torch.ones(4, 2, dtype=torch.bool))


class BridgeReaderTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.features = fixture()

    def test_equal_initial_behavior_and_common_tensor_initialization(self):
        rng = torch.random.get_rng_state().clone()
        base, bridge, wide = [build_reader(arm, 41) for arm in ("base", "bridge", "wide")]
        self.assertTrue(torch.equal(torch.random.get_rng_state(), rng))
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(41)
            legacy = TokenReader(384, 32, max_hops=8)
        for name, value in legacy.state_dict().items():
            self.assertTrue(torch.equal(base.state_dict()[name], value), name)
        for variant in (bridge, wide):
            self.assertEqual(sum(p.numel() for p in variant.parameters()), 38_466 + 4096)
            self.assertEqual(reader_identity(variant)["added_parameter_count"], 4096)
            for name, value in base.state_dict().items():
                self.assertTrue(torch.equal(variant.state_dict()[name], value), name)
            for depth in (1, 3, 8):
                self.assertTrue(torch.equal(base(*self.features, steps=depth),
                                            variant(*self.features, steps=depth)))

    def test_real_gradient_path_reaches_all_added_matrices_after_output_update(self):
        for arm in ("bridge", "wide"):
            model = build_reader(arm, 41)
            original = copy.deepcopy(model.state_dict())
            optimizer = torch.optim.SGD(model.parameters(), lr=.1)
            targets = torch.tensor([0, 1, 1, 0])
            for _ in range(3):
                optimizer.zero_grad()
                F.cross_entropy(model(*self.features, steps=3), targets).backward()
                optimizer.step()
            extra = [(name, value) for name, value in model.named_parameters()
                     if name not in build_reader("base", 41).state_dict()]
            self.assertEqual(len(extra), 4)
            for name, parameter in extra:
                self.assertGreater(parameter.grad.abs().sum().item(), 0, name)
                self.assertTrue(torch.isfinite(parameter.grad).all(), name)
                self.assertFalse(torch.equal(parameter, original[name]), name)

    def test_cross_fact_operation_and_control_locality(self):
        model = build_reader("bridge", 41)
        with torch.no_grad():
            model.fact_bridge.output.weight.copy_(torch.eye(32))
        prepared = model.prepare(*self.features)
        changed = list(self.features)
        changed[0] = changed[0].clone()
        changed[0][:, 2] *= -1
        modified = model.prepare(*changed)
        self.assertFalse(torch.equal(prepared["relations"][:, 0], modified["relations"][:, 0]))
        local = build_reader("wide", 41)
        with torch.no_grad():
            local.head.local_residual.output.weight.copy_(torch.eye(32))
        self.assertTrue(torch.equal(local.prepare(*self.features)["relations"][:, 0],
                                    local.prepare(*changed)["relations"][:, 0]))

    def test_masked_tokens_empty_facts_and_fact_permutation(self):
        for arm in ("bridge", "wide"):
            model = build_reader(arm, 41)
            with torch.no_grad():
                output = (model.fact_bridge.output if arm == "bridge"
                          else model.head.local_residual.output)
                output.weight.copy_(torch.eye(32))
            result = model(*self.features, steps=3, return_attention=True)
            changed = list(self.features)
            changed[0] = changed[0].clone()
            changed[0][~changed[3]] = 10000
            torch.testing.assert_close(result["logits"], model(*changed, steps=3))
            padded = list(self.features)
            padded[0] = torch.cat((padded[0], torch.randn(4, 1, 4, 384) * 10000), 1)
            padded[3] = torch.cat((padded[3], torch.zeros(4, 1, 4, dtype=torch.bool)), 1)
            torch.testing.assert_close(result["logits"], model(*padded, steps=3))
            permutation = torch.tensor([2, 0, 1])
            permuted = list(self.features)
            permuted[0], permuted[3] = permuted[0][:, permutation], permuted[3][:, permutation]
            torch.testing.assert_close(result["logits"], model(*permuted, steps=3))
            empty = list(self.features)
            empty[3] = torch.zeros_like(empty[3])
            absent = model(*empty, steps=3, return_attention=True)
            self.assertTrue(torch.isfinite(absent["logits"]).all())
            self.assertLessEqual(absent["state"].abs().max().item(), 1)
            self.assertTrue(torch.equal(absent["attentions"][-1], torch.zeros(4, 3)))

    def test_question_candidate_and_evidence_remain_distinct_features(self):
        for arm in ("bridge", "wide"):
            model = build_reader(arm, 41)
            expected = model(*self.features, steps=3)
            for feature in (0, 1, 2):
                changed = list(self.features)
                changed[feature] = -changed[feature]
                self.assertFalse(torch.equal(expected, model(*changed, steps=3)))

    def test_saved_weights_reconstruct_architecture_without_key_remapping(self):
        for arm in ("base", "bridge", "wide"):
            original = build_reader(arm, 41)
            with torch.no_grad():
                for value in original.parameters():
                    value.add_(.001)
            stream = io.BytesIO()
            torch.save(original.state_dict(), stream)
            stream.seek(0)
            restored = build_reader(arm, 123)
            restored.load_state_dict(torch.load(stream, weights_only=True), strict=True)
            self.assertEqual(reader_identity(original), reader_identity(restored))
            self.assertTrue(torch.equal(original(*self.features, steps=3),
                                        restored(*self.features, steps=3)))

    def test_recurrent_state_and_cross_fact_memory_bounds(self):
        model = build_reader("bridge", 41)
        with self.assertRaisesRegex(ValueError, "state"):
            model(*self.features, state=torch.full((4, 32), 2.))
        # The attention allocation guard is checked before forming the quadratic tensor.
        bridge = FactBridge(8)
        relations = torch.zeros(1, 1, 1, 8).expand(4096, 256, 1, 8)
        mask = torch.ones(1, 1, 1, dtype=torch.bool).expand(4096, 256, 1)
        with self.assertRaisesRegex(ValueError, "attention tensor limit"):
            bridge(relations, mask)
        for arm in ("missing", None):
            with self.assertRaisesRegex(ValueError, "known Reader"):
                build_reader(arm, 41)

    def test_small_dimensions_preserve_parameter_matched_family(self):
        for constructor in (BridgeReader, WideReader):
            model = constructor(8, 8, max_hops=3)
            self.assertEqual(reader_identity(model)["added_parameter_count"], 4 * 8 * 8)
            self.assertEqual(sum(value.numel() for value in model.parameters()),
                             sum(value.numel() for value in TokenReader(8, 8, max_hops=3).parameters())
                             + 4 * 8 * 8)

    def test_identity_rejects_class_spoofing_and_changed_parameter_shapes(self):
        model = build_reader("base", 41)
        model.reader_arm = "bridge"
        with self.assertRaisesRegex(ValueError, "class and matching arm"):
            reader_identity(model)
        model = build_reader("wide", 41)
        model.head.local_residual.input = torch.nn.Linear(31, 32, bias=False)
        with self.assertRaisesRegex(ValueError, "parameter names and shapes"):
            reader_identity(model)


if __name__ == "__main__":
    unittest.main()
