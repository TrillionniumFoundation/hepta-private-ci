import pathlib
import sys
import unittest

try:
    import torch
    from torch import nn
except ImportError:
    torch = None

if torch is not None:
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from native_latent import (NATIVE_SPECS, CellRequest, LightCellHead,
                               SharedStemServer, StemContractError,
                               StemSpec, build_encoder, parameter_count)


@unittest.skipUnless(torch is not None, 'optional PyTorch physical CPU smoke')
class NativeLatentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_native_architectures_are_genuinely_150m_300m_scale(self):
        budgets = {'hepta_latent_150m': 150_000_000,
                   'hepta_latent_300m': 300_000_000}
        for name, spec in NATIVE_SPECS.items():
            with self.subTest(name=name):
                count = parameter_count(spec)
                self.assertLess(abs(count - budgets[name]) / budgets[name], 0.05)
                self.assertFalse(any(p.requires_grad for p in build_encoder(spec).parameters()))

    def test_tiny_native_encoder_actually_executes(self):
        stem = build_encoder(StemSpec('tiny_untrained', 32, 2, 4), device='cpu')
        slots = torch.randn(1, 6, 32)
        with torch.no_grad():
            result = stem(slots)
        self.assertEqual(tuple(result.shape), tuple(slots.shape))
        self.assertTrue(torch.isfinite(result).all())

    def test_one_stem_call_fans_out_to_64_cell_heads(self):
        class CountingEncoder(nn.Module):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def forward(self, values):
                self.calls += 1
                return 2 * values

        encoder = CountingEncoder()
        server = SharedStemServer(encoder, generation=7, width=32, encoder_sha256='a' * 64)
        heads = [LightCellHead(32, state_width=8, adapter_rank=4) for _ in range(64)]
        requests = [CellRequest(f'cell.{i}', 7, head, torch.zeros(2, 8), 'b' * 64)
                    for i, head in enumerate(heads)]
        slots = torch.randn(2, 4, 32)
        result = server.evaluate(slots, requests)
        self.assertEqual(encoder.calls, 1)
        self.assertEqual(server.owner_forward_calls, 1)
        self.assertEqual(len(result['cell_results']), 64)
        self.assertIsNone(result['physical_backend_forward_calls'])
        self.assertFalse(result['performance_qualified'])
        self.assertEqual(result['authority'], 'DENY_ALL')
        self.assertFalse(result['production_activation_allowed'])
        for row in result['cell_results']:
            self.assertEqual(row['advisory']['action_logits'].shape, (2, 4))

    def test_zero_delta_adapter_matches_shared_feature(self):
        head = LightCellHead(32, state_width=8)
        shared = torch.randn(3, 32)
        state = torch.zeros(3, 8)
        actual = head(shared, state)
        self.assertTrue(torch.allclose(actual['task_logits'], head.task_head(shared)))
        self.assertTrue(torch.allclose(actual['action_logits'], head.action_head(shared)))

    def test_stale_generation_and_duplicate_cell_fail_before_execution(self):
        class CountingEncoder(nn.Module):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def forward(self, features):
                self.calls += 1
                return features
        encoder = CountingEncoder()
        server = SharedStemServer(encoder, generation=4, width=32, encoder_sha256='a'*64)
        head = LightCellHead(32)
        good = CellRequest('cell.a', 4, head, torch.zeros(1, 8), 'b'*64)
        stale = CellRequest('cell.b', 3, head, torch.zeros(1, 8), 'c'*64)
        with self.assertRaises(StemContractError):
            server.evaluate(torch.ones(1, 4, 32), [good, stale])
        with self.assertRaises(StemContractError):
            server.evaluate(torch.ones(1, 4, 32), [good, good])
        with self.assertRaises(StemContractError):
            server.evaluate(torch.full((1, 4, 32), float('nan')), [good])
        wrong_state = CellRequest('cell.c', 4, head, torch.zeros(1, 3), 'd'*64)
        with self.assertRaises(StemContractError):
            server.evaluate(torch.ones(1, 4, 32), [good, wrong_state])
        self.assertEqual(encoder.calls, 0)

    def test_unfrozen_shared_stem_refused(self):
        with self.assertRaises(StemContractError):
            SharedStemServer(nn.Linear(32, 32), generation=1, width=32,
                             encoder_sha256='a'*64)


if __name__ == '__main__':
    unittest.main()
