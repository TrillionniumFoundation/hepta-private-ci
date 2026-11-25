"""Semantic checks run before the supplemental training protocol is sealed."""
import unittest
import torch
from qualification.hcsn_smallnet_20261124.model import ModelConfig, SmallHCSN
from .model import SignedOnlySmallHCSN, verify_state_mask


class SignedControlTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.config = ModelConfig(neurons=8, message_mode='flow', precision='float64', backend='dense')

    def pair(self):
        torch.manual_seed(1101)
        base = SmallHCSN(self.config)
        torch.manual_seed(1101)
        signed = SignedOnlySmallHCSN(self.config)
        return base, signed

    def test_initialization_changes_only_persistent_mask(self):
        base, signed = self.pair()
        for name, tensor in base.state_dict().items():
            if name != 'synaptic_mask':
                self.assertTrue(torch.equal(tensor, signed.state_dict()[name]), name)
        verify_state_mask(self.config, signed.state_dict())
        with self.assertRaises(ValueError):
            verify_state_mask(self.config, base.state_dict())

    def test_original_core_reload_retains_mask_and_full_forward(self):
        base, signed = self.pair()
        base.load_state_dict(signed.state_dict())
        verify_state_mask(self.config, base.state_dict())
        x = torch.randn(3, 2, 6, dtype=torch.float64)
        with torch.no_grad():
            a = base(x, return_features=True)
            b = signed(x, return_features=True)
        self.assertTrue(torch.equal(a[0], b[0]))
        self.assertTrue(torch.equal(a[1], b[1]))
        for key in ('density', 'boundary', 'drift', 'cost', 'message'):
            self.assertTrue(torch.equal(getattr(a[2], key), getattr(b[2], key)))

    def test_unsigned_message_is_inert_signed_message_is_used(self):
        base, model = self.pair()
        x = torch.zeros(1, 2, 6, dtype=torch.float64)
        def output(network, channel=None):
            state = network.initial_state(2)
            if channel is not None:
                state.message[:, channel, :4] = torch.tensor([.2, -.1, .3, -.4])
            return network(x, state=state)
        with torch.no_grad():
            reference = output(model)
            self.assertTrue(torch.equal(reference, output(model, 1)))
            self.assertTrue(torch.equal(reference, output(model, 0)))
            self.assertGreater(float((reference-output(model, 2)).abs().max()), 1e-10)
            self.assertGreater(float((output(base)-output(base, 1)).abs().max()), 1e-10)


if __name__ == '__main__':
    unittest.main()
