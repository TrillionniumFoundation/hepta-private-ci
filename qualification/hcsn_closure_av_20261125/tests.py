"""Small causal/gradient/interface checks; no new confirmation data loaded."""

import unittest
import json
from pathlib import Path
import tempfile

import numpy as np
import torch

from .metrics import classification, ranks, semantic
from .models import BinarySpike, PairedEncoder, objective
from . import provenance


class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def inputs(self):
        generator = torch.Generator().manual_seed(9021)
        return torch.randn(2, 32, 130, generator=generator)*.2

    def test_common_frontend_head_and_real_gradients(self):
        x = self.inputs()
        previous = None
        for arm in ("hcsn", "transformer", "lif"):
            model = PairedEncoder(arm, 31011)
            current = {k: v for k, v in model.state_dict().items() if "frontend." in k or k.startswith("head.")}
            if previous is not None:
                self.assertEqual(current.keys(), previous.keys())
                self.assertTrue(all(torch.equal(current[k], previous[k]) for k in current))
            previous = current
            output = model(x, x.flip(1))
            self.assertEqual(output["fused_logits"].shape, (2, 6))
            objective(output, torch.tensor([1, 4])).backward()
            for encoder in (model.audio, model.video):
                self.assertTrue(bool(torch.isfinite(encoder.frontend.weight.grad).all()))
                self.assertGreater(float(encoder.frontend.weight.grad.abs().sum()), 0)
            if arm == "hcsn":
                self.assertLess(model.audio.diagnostics["mass_error"], 2e-9)
                self.assertFalse(any(k.startswith("audio.core.readout.") for k in model.state_dict()))
                self.assertEqual(int(torch.count_nonzero(model.audio.core.synaptic_mask[:, 8:16])), 0)

    def test_batch_independence_and_exact_reload(self):
        x = self.inputs()
        for arm in ("hcsn", "transformer", "lif"):
            model = PairedEncoder(arm, 31011).eval()
            with torch.no_grad():
                output = model(x, x)
                separate = model(x[:1], x[:1])
                for key in output:
                    torch.testing.assert_close(output[key][:1], separate[key], atol=2e-6, rtol=2e-6)
                restored = PairedEncoder(arm, 31011).eval()
                restored.load_state_dict(model.state_dict(), strict=True)
                result = restored(x, x)
                self.assertTrue(all(torch.equal(result[k], output[k]) for k in result))

    def test_spikes_and_semantic_gallery_exclusion(self):
        voltage = torch.tensor([-.2, .3], requires_grad=True)
        spikes = BinarySpike.apply(voltage)
        self.assertEqual(spikes.tolist(), [0., 1.])
        spikes.sum().backward()
        self.assertGreater(float(voltage.grad.min()), 0)
        scores = np.eye(4)*100 + np.array([[0, 0, 3, 1], [0, 0, 1, 3], [3, 1, 0, 0], [1, 3, 0, 0]])
        m = semantic(scores, [0, 1, 0, 1], [1, 1, 2, 2])
        self.assertEqual(m["class_recall_at_1"], 1.)
        self.assertEqual(m["mean_average_precision"], 1.)
        self.assertEqual(ranks(scores)["recall_at_1"], 1.)
        self.assertAlmostEqual(classification(np.zeros((6, 6)), np.arange(6))["cross_entropy"], np.log(6))

    def test_complete_protocol_gate_rejects_slot_and_budget_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            data, root = Path(temporary)/"data", Path(temporary)/"run"
            data.mkdir()
            base = provenance.read(provenance.HERE/"protocol.json")
            rows = {}
            for split, cohort in base["cohort"].items():
                file = data/(split+".npz")
                file.write_bytes(b"fixture bytes only, never decoded or fitted")
                rows[split] = {**cohort, "path": file.name, "sha256": provenance.digest(file)}
            provenance.create(data/"DATASET.json", {"splits": rows})
            original = provenance.prepare(root, data)
            self.assertEqual(provenance.load(root), original)
            for kind in ("slots", "budget", "dataset"):
                p = json.loads(json.dumps(original))
                if kind == "slots":
                    p["slots"] = p["slots"][:1]
                elif kind == "budget":
                    p["training"]["max_updates"] = 1
                else:
                    p["dataset"]["splits"]["train"]["examples"] = 1
                (root/"PROTOCOL.json").write_text(json.dumps(p))
                with self.assertRaises(ValueError):
                    provenance.load(root)


if __name__ == "__main__":
    unittest.main()
