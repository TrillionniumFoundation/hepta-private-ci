"""The follow-up cannot silently change precision or shrink its sealed roster."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import torch

from . import precision_run as protocol
from . import provenance as pv


class PrecisionTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)

    def test_full_protocol_rejects_shrunken_roster_or_changed_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/"trial"
            original = protocol.prepare(root)
            self.assertEqual(len(original["slots"]), 6)
            self.assertEqual(protocol.load(root), original)
            for mutation in ("roster", "gate", "source"):
                changed = deepcopy(original)
                if mutation == "roster":
                    changed["slots"].pop()
                elif mutation == "gate":
                    changed["comparison_gates"]["required_pairs"] = 1
                else:
                    changed["data"]["test_sources"] = [12000]
                (root/"PROTOCOL.json").unlink()
                pv.create(root/"PROTOCOL.json", changed)
                with self.assertRaisesRegex(ValueError, "precision roster"):
                    protocol.load(root)

    def test_actual_precision_finite_bp_and_projection_accounting(self):
        for variant in protocol.VARIANTS:
            torch.manual_seed(84031)
            slot = {"neurons": 64, "variant": variant,
                "precision": "mixed" if variant == "fast_mixed" else "native32"}
            model = protocol.factory(slot)
            x = (torch.randn(12, 2, 6)*.2).requires_grad_()
            logits, _, state = model(x, return_features=True)
            logits.square().mean().backward()
            dtype = torch.float64 if variant == "fast_mixed" else torch.float32
            self.assertEqual(state.density.dtype, dtype)
            self.assertTrue(bool(torch.isfinite(x.grad).all()))
            self.assertGreater(float(x.grad.abs().max()), 0.)
            self.assertTrue(bool(torch.isfinite(model.input_drive.weight.grad).all()))
            if variant == "projected_native32":
                self.assertEqual(model.last_diagnostics["projection_steps"], 12)
                self.assertLessEqual(model.last_diagnostics["raw_local_mass_defect_max"], 2e-6)
            wrong = dict(slot, precision="float64")
            with self.assertRaisesRegex(ValueError, "precision does not match"):
                protocol.factory(wrong)


if __name__ == "__main__":
    unittest.main()
