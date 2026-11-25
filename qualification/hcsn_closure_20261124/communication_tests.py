"""Causal-path checks use constructed inputs, never prospective holdout sources."""

import json
import io
import unittest

import torch

from qualification.hcsn_smallnet_20261124.model import ModelConfig, SmallHCSN
from .communication import (CommunicationHCSN, ControlSpec, control_step,
                            initial_control, pack_state, transform_unsigned, unpack_state)


def probe_model(mode):
    torch.manual_seed(99021)
    config = ModelConfig(neurons=8, precision="float64", backend="dense", message_mode="boundary")
    model = CommunicationHCSN(config, control_mode=mode)
    with torch.no_grad():
        model.input_drive.weight.zero_()
        model.input_drive.bias.zero_()
        model.input_drive.weight[:, 1] = .7
        model.input_mark.weight.zero_()
        model.input_mark.bias.zero_()
        model.recurrent.weight.zero_()
        model.recurrent.weight[4:, :4] = .1
        model.raw_cost.fill_(.23)
        model.readout.weight.zero_()
        model.readout.bias.zero_()
        model.readout.weight[1, 4::5] = 1
        model.readout.weight[0, 4::5] = -1
    return model


def pulse(value, late=5):
    x = torch.zeros(12, 2, 6, dtype=torch.float64)
    x[:, :, 4] = torch.arange(12, dtype=torch.float64)[:, None]/11
    x[late, :, 1], x[late, :, 3] = value, 1
    return x


def causal_diagnostic():
    records = {}
    for mode in ("raw", "accumulate", "hold"):
        model = probe_model(mode)
        for late in (4, 5):
            with torch.no_grad():
                positive = model(pulse(.6, late))
                negative = model(pulse(-.6, late))
            delta = (positive-negative).abs().amax((1, 2))
            changed = torch.where(delta > 1e-12)[0]
            records[mode+"_late"+str(late)] = {
                "first_receiver_margin_effect": None if not len(changed) else int(changed[0]),
                "max_logit_difference": float(delta.max()),
                "all_prefix_differences": delta.tolist()}
    return {"scope": "controlled-weights causal path; not a trained accuracy comparison", "cases": records}


class CommunicationTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)

    def test_accumulator_conserves_impulses_and_waits_for_its_clock(self):
        frame = torch.zeros(2, 6, dtype=torch.float64)
        state = initial_control(frame, ControlSpec("accumulate", 2))
        emitted = []
        for tick in range(5):
            value = frame.clone()
            value[:, 1] = tick + 1
            output, state, due = control_step(value, state)
            if due:
                emitted.append(output[:, 1])
        self.assertTrue(torch.equal(torch.stack(emitted)[:, 0], torch.tensor([1., 5., 9.], dtype=torch.float64)))
        self.assertEqual(float(state.pending.abs().sum()), 0.)

    def test_boundary_alias_and_latest_possible_receiver_law_time(self):
        cases = causal_diagnostic()["cases"]
        self.assertIsNone(cases["raw_late5"]["first_receiver_margin_effect"])
        self.assertEqual(cases["raw_late4"]["first_receiver_margin_effect"], 6)
        for mode in ("accumulate", "hold"):
            self.assertEqual(cases[mode+"_late4"]["first_receiver_margin_effect"], 6)
            self.assertEqual(cases[mode+"_late5"]["first_receiver_margin_effect"], 8)

    def test_raw_wrapper_matches_core_and_future_cannot_change_prefix(self):
        torch.manual_seed(812)
        config = ModelConfig(neurons=8, precision="float64", backend="dense")
        wrapped = CommunicationHCSN(config)
        base = SmallHCSN(config)
        base.load_state_dict({k:v for k,v in wrapped.state_dict().items() if k != "unsigned_reference"})
        x = pulse(.35)
        with torch.no_grad():
            a, fa, sa = wrapped(x, return_features=True)
            b, fb, sb = base(x, return_features=True)
            self.assertTrue(torch.equal(a, b))
            self.assertTrue(torch.equal(fa, fb))
            self.assertTrue(torch.equal(sa.density, sb.density))
            for mode in ("accumulate", "hold"):
                model = probe_model(mode)
                changed = x.clone()
                changed[7, :, 1], changed[7, :, 3] = .8, 1
                original, altered = model(x), model(changed)
                self.assertTrue(torch.equal(original[:7], altered[:7]))
                self.assertGreater(float((original[7:]-altered[7:]).abs().max()), 1e-10)

    def test_odd_cut_continuation_retains_pending_input_and_held_state(self):
        for mode in ("accumulate", "hold"):
            model = probe_model(mode)
            x = pulse(.37, late=3)
            with torch.no_grad():
                all_output, _, final = model(x, return_features=True)
                early, _, state = model(x[:4], return_features=True)
                serialized = io.BytesIO()
                torch.save(pack_state(state), serialized)
                serialized.seek(0)
                loaded = unpack_state(torch.load(serialized, weights_only=True))
                late, _, restored = model(x[4:], state=loaded, return_features=True)
            self.assertTrue(torch.equal(torch.cat((early, late)), all_output))
            self.assertTrue(torch.equal(restored.density, final.density))
            self.assertTrue(torch.equal(restored.control.pending, final.control.pending))
            self.assertTrue(torch.equal(restored.control.held, final.control.held))
            self.assertEqual(restored.step, 12)

    def test_buffered_cue_gradient_matches_nonzero_finite_difference(self):
        model = probe_model("accumulate")
        x = pulse(.37).requires_grad_()
        model(x)[-1, :, 1].sum().backward()
        actual = float(x.grad[5, :, 1].sum())
        epsilon = 1e-5
        with torch.no_grad():
            fd = float((model(pulse(.37+epsilon))[-1, :, 1].sum()
                        -model(pulse(.37-epsilon))[-1, :, 1].sum())/(2*epsilon))
        self.assertGreater(abs(fd), 1e-8)
        self.assertLess(abs(actual-fd), 2e-7)

    def test_unsigned_centering_is_local_and_bounding_has_unit_lipschitz_constant(self):
        reference = torch.tensor([.4, .8], dtype=torch.float64)
        message = torch.tensor([[[3., 4.], [.4, .8], [-.2, .1]],
                                [[5., 6.], [2., 3.], [.3, -.4]]], dtype=torch.float64, requires_grad=True)
        centered = transform_unsigned(message, reference, "centered")
        self.assertTrue(torch.equal(centered[0, 1], torch.zeros(2, dtype=torch.float64)))
        bounded = transform_unsigned(message, reference, "centered_bounded", .25)
        self.assertTrue(torch.equal(bounded[:, 0], message[:, 0]))
        self.assertTrue(torch.equal(bounded[:, 2], message[:, 2]))
        self.assertLessEqual(float(bounded[:, 1].detach().abs().max()), .25)
        gradient = torch.autograd.grad(bounded[:, 1].sum(), message)[0][:, 1]
        self.assertTrue(bool(((gradient >= 0) & (gradient <= 1)).all()))
        self.assertTrue(torch.equal(transform_unsigned(message[:1], reference, "centered_bounded", .25), bounded[:1]))


if __name__ == "__main__":
    unittest.main()
