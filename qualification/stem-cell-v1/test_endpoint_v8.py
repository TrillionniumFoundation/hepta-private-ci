"""Mechanism regressions; not a pretrained Encoder or transfer evaluation."""
import copy
import unittest
import torch
from torch.nn import functional as F

from token_reader import TokenReader
from bridge_reader import build_reader
from endpoint_v8 import TokenMatchBridge, build_endpoint
from structural_null_v8 import infer_public, infer_case, RejectGrammar


def features(seed=7, *, batch=3, facts=3, tokens=2):
    generator = torch.Generator().manual_seed(seed)
    rows = (torch.randn(batch, facts, tokens, 384, generator=generator),
            torch.randn(batch, 2, 384, generator=generator),
            torch.randn(batch, 2, 384, generator=generator))
    mask = torch.ones(batch, facts, tokens, dtype=torch.bool)
    return (*rows, mask, torch.ones(batch, 2, dtype=torch.bool),
            torch.ones(batch, 2, dtype=torch.bool))


class EndpointMechanism(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_matched_parameter_count_and_common_initialization(self):
        for seed in (41, 47, 53):
            e, b, w, base = build_endpoint(seed), build_reader('bridge', seed), build_reader('wide', seed), build_reader('base', seed)
            self.assertEqual([sum(p.numel() for p in m.parameters()) for m in (e, b, w, base)],
                             [42562, 42562, 42562, 38466])
            for name, tensor in base.state_dict().items():
                self.assertTrue(torch.equal(e.state_dict()[name], tensor))
            self.assertTrue(torch.equal(e(*features(), steps=3), base(*features(), steps=3)))
            self.assertTrue(torch.equal(e(*features(), steps=3), b(*features(), steps=3)))
            self.assertTrue(torch.equal(e(*features(), steps=3), w(*features(), steps=3)))

    def test_no_source_or_caller_rng_contamination(self):
        first = torch.random.get_rng_state().clone()
        a = build_endpoint(47)
        self.assertTrue(torch.equal(first, torch.random.get_rng_state()))
        b = build_endpoint(47)
        for key in a.state_dict():
            self.assertTrue(torch.equal(a.state_dict()[key], b.state_dict()[key]))

    def test_masks_and_missing_evidence_do_not_grow(self):
        bridge = TokenMatchBridge(32)
        with torch.no_grad():
            for layer in (bridge.query, bridge.key, bridge.value, bridge.output):
                layer.weight.copy_(torch.eye(32))
        relations = torch.randn(2, 3, 2, 32)
        mask = torch.tensor([[[1, 1], [0, 0], [1, 0]], [[1, 0], [0, 0], [0, 0]]], dtype=torch.bool)
        y = bridge(relations, mask)
        self.assertTrue(torch.equal(y[0, 1], relations[0, 1]))
        self.assertTrue(torch.equal(y[0, 2, 1], relations[0, 2, 1]))
        self.assertTrue(torch.equal(y[1], relations[1]))
        self.assertFalse(torch.equal(y[0, 0, 0], relations[0, 0, 0]))

    def test_key_value_corruption_changes_only_cross_fact_message(self):
        bridge = TokenMatchBridge(32)
        with torch.no_grad():
            for layer in (bridge.query, bridge.key, bridge.value, bridge.output):
                layer.weight.copy_(torch.eye(32))
        x = torch.randn(1, 3, 2, 32, generator=torch.Generator().manual_seed(19))
        m = torch.ones(1, 3, 2, dtype=torch.bool)
        self.assertGreater((bridge(x, m) - bridge(x, m, desync_keys=True)).abs().sum().item(), 1e-4)
        self.assertTrue(torch.allclose(bridge(x[:, :1], m[:, :1]), x[:, :1]))

    def test_gradients_can_reach_all_four_projections(self):
        bridge = TokenMatchBridge(32)
        x = torch.randn(2, 3, 3, 32)
        m = torch.ones(2, 3, 3, dtype=torch.bool)
        opt = torch.optim.Adam(bridge.parameters(), lr=.02, foreach=False)
        for _ in range(3):
            opt.zero_grad(set_to_none=True)
            # output layer is initially zero; Q/K/V gradients appear after its first update.
            y = bridge(x, m)
            (y.square().mean()).backward()
            opt.step()
        for layer in (bridge.query, bridge.key, bridge.value, bridge.output):
            self.assertIsNotNone(layer.weight.grad)
            self.assertTrue(torch.isfinite(layer.weight.grad).all())
            self.assertGreater(layer.weight.grad.abs().sum().item(), 0)

    def test_fail_closed_nonfinite_shape_and_bound(self):
        b = TokenMatchBridge(32)
        x = torch.randn(2, 2, 2, 32)
        m = torch.ones(2, 2, 2, dtype=torch.bool)
        for bad, mask in ((x * float('nan'), m), (x, m.float()), (x, m[:, :1])):
            with self.assertRaises(ValueError):
                b(bad, mask)
        with self.assertRaises(ValueError):
            b(torch.zeros(16, 20, 20, 32), torch.ones(16, 20, 20, dtype=torch.bool))
        with self.assertRaises(ValueError):
            build_endpoint(-1)


FACTS = ('The coin belongs to Ada.', 'The bead belongs to Ben.',
         'Ada stores all their possessions in the green box.',
         'Ben stores all their possessions in the silver box.')
Q = 'Where is the coin stored?'
C = 'The green box.'


class PublicNull(unittest.TestCase):
    def test_positive_negative_counterfactual_worlds(self):
        yes, proof = infer_public(FACTS, Q, C)
        no, nproof = infer_public(('The coin belongs to Ben.', 'The bead belongs to Ada.',
                                   *FACTS[2:]), Q, C)
        self.assertEqual((yes, no), (1, 0))
        self.assertEqual(proof, (1, 3))
        self.assertEqual(nproof, (1, 4))

    def test_sentence_shuffle_same_answer_but_proof_tracks_source(self):
        order = (2, 0, 3, 1)
        result, proof = infer_public(tuple(FACTS[i] for i in order), Q, C)
        self.assertEqual(result, 1)
        self.assertEqual(proof, (1, 2))

    def test_never_reads_label_annotation_metadata(self):
        class Case:
            facts = FACTS
            question = Q
            candidate = C
            @property
            def label(self):
                raise AssertionError('label leakage')
            @property
            def evidence_sentence_indices(self):
                raise AssertionError('annotation leakage')
            @property
            def paragraph_id(self):
                raise AssertionError('world-id leakage')
        self.assertEqual(infer_case(Case()), (1, (1, 3)))

    def test_unknown_missing_ambiguous_and_invalid_reject(self):
        variants = [(FACTS[:3], Q, C),
                    ((FACTS[0], FACTS[0], *FACTS[2:]), Q, C),
                    ((FACTS[0], FACTS[1], FACTS[2], FACTS[2]), Q, C),
                    (FACTS, 'What color?', C), (FACTS, Q, 'The black box.'),
                    (FACTS, 'Where is the lantern stored?', C),
                    ((FACTS[0], FACTS[1], 'Bad fact.', FACTS[3]), Q, C)]
        for args in variants:
            with self.subTest(args=args), self.assertRaises(RejectGrammar):
                infer_public(*args)

    def test_not_suitable_for_general_prose(self):
        with self.assertRaises(RejectGrammar):
            infer_public(('A paragraph explaining monetary policy.',)*4, 'Why?', 'Because')


if __name__ == '__main__':
    unittest.main()
