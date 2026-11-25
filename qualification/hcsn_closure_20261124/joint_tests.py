"""Smoke-only algebra, causal-state and BP contracts for the joint protocol."""

from dataclasses import replace
import unittest

import torch

from qualification.hcsn_smallnet_20261124.model import ModelConfig
from .fast_kernel import FastSignedHCSN
from .joint_run import CHANNELS, JointHCSN, check_checkpoint_masks, factory, parameter_accounting


class JointTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(86031)
        self.config = ModelConfig(neurons=32, message_mode="full", boundary_mode="qvi",
            feature_bank="value_risk", precision="mixed", backend="uniformized")
        self.x = torch.randn(12, 2, 6)*.25

    def test_signed_matches_existing_fast_outputs_all_state_and_gradients(self):
        left = FastSignedHCSN(replace(self.config, message_mode="flow"), scripted=True)
        right = JointHCSN(self.config, "signed_only")
        saved = left.state_dict()
        saved["synaptic_mask"] = right.synaptic_mask.clone()
        right.load_state_dict(saved)
        outcomes = []
        for model in (left, right):
            x = self.x.clone().requires_grad_()
            logits, features, state = model(x, return_features=True)
            (logits.square().mean()+.001*features.square().mean()).backward()
            outcomes.append((logits, features, state,
                {n: None if p.grad is None else p.grad.clone() for n,p in model.named_parameters()}, x.grad))
        for i in (0, 1, 4):
            torch.testing.assert_close(outcomes[0][i], outcomes[1][i], atol=0, rtol=0)
        self.assertEqual(outcomes[0][2].step, outcomes[1][2].step)
        for field in ("density", "boundary", "drift", "cost", "message"):
            torch.testing.assert_close(getattr(outcomes[0][2], field), getattr(outcomes[1][2], field), atol=0, rtol=0)
        for key, value in outcomes[0][3].items():
            if value is None:
                self.assertIsNone(outcomes[1][3][key])
            else:
                torch.testing.assert_close(value, outcomes[1][3][key], atol=0, rtol=0)

    def test_all_masks_causal_resume_and_true_bp(self):
        for channel in CHANNELS:
            model = JointHCSN(self.config, channel)
            n, h = self.config.neurons, self.config.neurons//2
            self.assertEqual(int(torch.count_nonzero(model.synaptic_mask[:,n:2*n])), 0)
            self.assertEqual(parameter_accounting(model)["structurally_active_recurrent_parameters"],
                             2*(n*n-h*h) if channel == "boundary_signed" else n*n-h*h)
            full, _, state = model(self.x, return_features=True)
            changed = self.x.clone(); changed[6:] += .6
            torch.testing.assert_close(model(changed)[:6], full[:6], atol=0, rtol=0)
            first, _, mid = model(self.x[:5], return_features=True)
            second, _, resumed = model(self.x[5:], state=mid, return_features=True)
            torch.testing.assert_close(torch.cat((first,second)), full, atol=0, rtol=0)
            for field in ("density", "boundary", "drift", "cost", "message"):
                torch.testing.assert_close(getattr(resumed,field), getattr(state,field), atol=0, rtol=0)
            optimizer = torch.optim.SGD(model.parameters(), lr=.1)
            loss = torch.nn.functional.cross_entropy(full[-1], torch.tensor([0,1]))
            loss.backward()
            for parameter in (model.input_drive.weight, model.recurrent.weight, model.readout.weight):
                self.assertTrue(bool(torch.isfinite(parameter.grad).all()))
                self.assertGreater(float(parameter.grad.abs().max()), 0.)
            self.assertEqual(float((model.recurrent.weight.grad*(1-model.synaptic_mask)).abs().max()), 0.)
            before = model.readout.weight.detach().clone()
            optimizer.step()
            self.assertFalse(torch.equal(before, model.readout.weight))

    def test_all_four_saved_states_reject_mask_tampering(self):
        slot = {"neurons":32,"variant":"boundary_signed"}
        model = factory(slot)
        for name in ("initial_model", "selected_model", "last_model", "cpu_prefix_model"):
            saved = {key:{n:v.clone() for n,v in model.state_dict().items()} for key in
                     ("initial_model", "selected_model", "last_model", "cpu_prefix_model")}
            check_checkpoint_masks(saved,slot)
            saved[name]["synaptic_mask"][0,32] = 1
            with self.assertRaisesRegex(ValueError, "checkpoint channel"):
                check_checkpoint_masks(saved,slot)


if __name__ == "__main__":
    unittest.main()
