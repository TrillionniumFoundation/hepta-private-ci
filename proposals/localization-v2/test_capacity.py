import os
import unittest

import torch

from capacity import adamw, match_width, parameter_audit
from models import ARMS, build_model


class CapacityTests(unittest.TestCase):
    def test_official_widths_have_fresh_causal_state_and_connected_gradients(self):
        torch.set_num_threads(1)
        for arm in ARMS:
            with self.subTest(arm=arm):
                model = build_model(arm, os.environ.get("HCSN_S4_REPO"), width=6)
                x, dt = torch.randn(2, 7, 25, dtype=torch.float64), torch.full((2, 7), .02, dtype=torch.float64)
                first = model(x, dt)
                torch.testing.assert_close(first, model(x, dt), rtol=0., atol=0.)
                torch.testing.assert_close(first[:, :3], model(x[:, :3], dt[:, :3]), rtol=1e-10, atol=1e-10)
                self.assertEqual(first.shape, (2, 7, 11))
                audit = parameter_audit(model, (x, dt))
                self.assertEqual(audit["disconnected_parameters"], [])
                optimizer, receipt = adamw(model, .0003, .0001)
                covered = []
                for group in optimizer.param_groups:
                    for parameter in group["params"]:
                        hints = getattr(parameter, "_optim", {})
                        self.assertEqual((group["lr"], group["weight_decay"]),
                                         (hints.get("lr", .0003), hints.get("weight_decay", .0001)))
                        covered.append(id(parameter))
                self.assertEqual(sorted(covered), sorted(id(p) for p in model.parameters() if p.requires_grad))
                self.assertEqual(sum(len(row["parameter_names"]) for row in receipt), len(covered))

    def test_count_only_selection_preserves_rng_and_reports_no_match(self):
        count = parameter_audit(build_model("gru", width=6))["trainable_real_scalars"]
        rng = torch.get_rng_state().clone()
        result = match_width("gru", count, [4, 6, 8])
        self.assertEqual(result["selected"]["width"], 6)
        torch.testing.assert_close(rng, torch.get_rng_state(), rtol=0., atol=0.)
        self.assertIsNone(match_width("gru", 1, [4, 6, 8])["selected"])

    def test_complex_frozen_disconnected_and_aliases_are_distinguished(self):
        model = torch.nn.Linear(3, 2).double()
        model.extra = torch.nn.Parameter(torch.ones(2, dtype=torch.complex128))
        model.frozen = torch.nn.Parameter(torch.zeros(3), requires_grad=False)
        audit = parameter_audit(model)
        self.assertEqual((audit["trainable_real_scalars"], audit["frozen_real_scalars"]), (12, 3))
        model.aliased = torch.nn.Parameter(model.weight.detach())
        with self.assertRaisesRegex(ValueError, "aliased"):
            parameter_audit(model)
        del model.aliased
        class Probe(torch.nn.Module):
            def __init__(self, inner):
                super().__init__()
                self.inner = inner

            def forward(self, x, dt):
                return self.inner(x)
        probe = Probe(model)
        audit = parameter_audit(probe, (torch.ones(1, 3, dtype=torch.float64), None))
        self.assertEqual(audit["disconnected_parameters"], ["inner.extra"])


if __name__ == "__main__":
    unittest.main()
