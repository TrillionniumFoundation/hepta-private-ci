"""Numerical controls; synthetic inputs here are NOT original task evidence."""
import tempfile
from pathlib import Path
import unittest
import torch

from fbsde_acquisition_study import make_head
from fbsde_head_fusion_probe import (benchmark, original_material,
                                     fused_logits, pack_gates)


class HeadFusionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_same_frozen_weights_all_64_inputs_and_saturated_gates(self):
        with torch.random.fork_rng(devices=[]), torch.inference_mode():
            torch.manual_seed(71)
            model=make_head(torch).eval().requires_grad_(False)
            original={k:v.clone() for k,v in model.state_dict().items()}
            x=torch.randn(64,384)
            x=torch.cat((x, x*4),0)
            y=model(x)
            packed=pack_gates(model)
            candidate=fused_logits(model,x,packed)
            self.assertLessEqual(float((y-candidate).abs().max()),1e-6)
            self.assertTrue(torch.equal(y.argmax(-1),candidate.argmax(-1)))
            for name, tensor in original.items():
                self.assertTrue(torch.equal(tensor, model.state_dict()[name]))

    def test_fused_projection_keeps_original_parameter_inventory(self):
        model=make_head(torch).eval()
        before=sum(p.numel() for p in model.parameters())
        packed=pack_gates(model)
        self.assertEqual(tuple(packed[0].shape),(32,384))
        self.assertEqual(tuple(packed[1].shape),(32,))
        self.assertEqual(before,sum(p.numel() for p in model.parameters()))
        self.assertEqual(set(model.state_dict()),{
            "value.weight","value.bias","gate.weight","gate.bias",
            "out.weight","out.bias"})

    def test_wrong_archive_fails_before_weights_only_decoder(self):
        with tempfile.TemporaryDirectory() as root:
            f=Path(root)/"fake.zip"
            f.write_bytes(b"not-a-real-archive")
            with self.assertRaisesRegex(ValueError,"different historical ZIP"):
                original_material(f)

    def test_invalid_budgets_cannot_run_archive(self):
        with tempfile.TemporaryDirectory() as root:
            for args in ({"threads":0},{"threads":3},{"threads":True},
                         {"repetitions":100},{"warmup":0}):
                with self.subTest(args=args),self.assertRaises(ValueError):
                    benchmark(Path(root)/"unprovided.zip",
                              Path(root)/"unwritten",**args)
            self.assertFalse((Path(root)/"unwritten").exists())


if __name__=="__main__":
    unittest.main()
