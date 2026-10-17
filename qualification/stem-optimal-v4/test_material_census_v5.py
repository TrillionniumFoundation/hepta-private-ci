"""Original-tensor value-coverage source-only adversarial checks, no real HF load."""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

import material_census_v5 as census


class RealTorchTensorCensusTests(unittest.TestCase):
    def setUp(self):
        try:
            import torch
            from safetensors.torch import save_file
        except ImportError:
            self.fail('Torch and safetensors are mandatory for the physical source tests')
        self.torch = torch
        self.save_file = save_file

    def model(self):
        import torch
        mdl = torch.nn.Sequential(torch.nn.Linear(3, 4, bias=True),
                                  torch.nn.Linear(4, 2, bias=False))
        with torch.no_grad():
            # Nontrivial weights and a duplicate-valued buffer are intentional.
            mdl[0].weight.copy_(torch.arange(12, dtype=torch.float32).reshape(4, 3) / 31)
            mdl[0].bias.copy_(torch.tensor([0.03, 0.2, 0.5, 1.]))
            mdl[1].weight.copy_(torch.arange(8, dtype=torch.float32).reshape(2, 4) / 21)
        return mdl

    def source(self, root, model, *, dtype=None, omit=None):
        torch = self.torch
        values = {name: p.detach().clone().to(dtype=dtype or torch.float32)
                  for name, p in model.named_parameters() if name != omit}
        values['unselected.vision.weight'] = torch.ones(5, 6)
        path = root / 'check.safetensors'
        self.save_file(values, str(path))
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_complete_tensor_values_cover_all_parameters_and_ignore_extra_modalities(self):
        model = self.model()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, sha = self.source(root, model)
            result = census.verify_source_value_coverage(model, source, expected_sha=sha)
            self.assertTrue(result['source_value_coverage_verified'])
            self.assertEqual(result['runtime_parameter_elements'], 4*3 + 4 + 2*4)
            self.assertEqual(result['runtime_unique_parameter_tensors'], 3)
            self.assertEqual(result['original_archive_tensor_count'], 4)
            self.assertFalse(result['strict_logical_name_mapping_verified'])
            self.assertFalse(result['model_issuer_signature_verified'])
            self.assertEqual(len(result['proof_digest']), 64)

    def test_randomly_initialized_tied_token_embedding_is_rejected(self):
        torch = self.torch
        model = self.model()
        with tempfile.TemporaryDirectory() as temp:
            source, sha = self.source(Path(temp), model)
            with torch.no_grad():
                model[0].weight[0,0] += .125
            with self.assertRaisesRegex(ValueError, 'lacks original source tensor values'):
                census.verify_source_value_coverage(model, source, expected_sha=sha)

    def test_missing_original_tensor_is_rejected_without_fallback(self):
        model = self.model()
        with tempfile.TemporaryDirectory() as temp:
            source, sha = self.source(Path(temp), model, omit='0.weight')
            with self.assertRaisesRegex(ValueError, 'lacks original source'):
                census.verify_source_value_coverage(model, source, expected_sha=sha)

    def test_bfloat16_checkpoint_cast_to_fp32_roundtrip(self):
        torch = self.torch
        mdl = torch.nn.Linear(2,2, bias=False)
        with torch.no_grad():
            mdl.weight.copy_(torch.tensor([[.125,-.25],[.5,.75]]))
        with tempfile.TemporaryDirectory() as temp:
            source, sha = self.source(Path(temp), mdl, dtype=torch.bfloat16)
            result = census.verify_source_value_coverage(mdl, source, expected_sha=sha)
            self.assertEqual(result['runtime_parameter_elements'],4)

    def test_sha_tamper_and_untrusted_path(self):
        model=self.model()
        with tempfile.TemporaryDirectory() as temp:
            path, sha=self.source(Path(temp), model)
            with self.assertRaisesRegex(ValueError,'original SHA'):
                census.verify_source_value_coverage(model, path, expected_sha='0'*64)
            link=Path(temp)/'symlink.safetensors'
            link.symlink_to(path)
            with self.assertRaisesRegex(ValueError,'unsafe original'):
                census.verify_source_value_coverage(model, link, expected_sha=sha)

    def test_distinct_runtime_equal_values_cannot_reuse_one_source_tensor(self):
        import torch
        mdl=torch.nn.Module()
        mdl.a=torch.nn.Parameter(torch.ones(3))
        mdl.b=torch.nn.Parameter(torch.ones(3))
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'one.safetensors'
            self.save_file({'unique':torch.ones(3)},str(path))
            sha=hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError,'lacks original'):
                census.verify_source_value_coverage(mdl,path,expected_sha=sha)


if __name__=='__main__':
    unittest.main()
