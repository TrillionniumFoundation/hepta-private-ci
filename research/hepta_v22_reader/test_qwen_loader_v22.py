"""Regression for ACTUAL hosted failure 38925755341, not pretrained QA scoring."""
import inspect
import unittest
from types import SimpleNamespace

from v19_qwen_reference import load_frozen_qwen_model


class LockedTransformersLoaderTest(unittest.TestCase):
    def test_exact_pinned_4533_keyword_and_precision(self):
        calls = []
        class StrictQwen:
            def eval(self):
                calls.append('eval')
                return self
        class StrictAutoModel:
            @staticmethod
            def from_pretrained(location, *, local_files_only, trust_remote_code,
                                use_safetensors, torch_dtype):
                # Intentionally NO **kwargs: old "dtype" fails like hosted Qwen3.
                calls.append((location,local_files_only,trust_remote_code,
                              use_safetensors,torch_dtype))
                return StrictQwen()
        torch_stub=SimpleNamespace(float32=object())
        model=load_frozen_qwen_model(StrictAutoModel,'/frozen/model',torch_stub)
        self.assertIsInstance(model,StrictQwen)
        self.assertEqual(calls,[('/frozen/model',True,False,True,torch_stub.float32),'eval'])

    def test_old_dtype_fails_reproduction_control(self):
        class StrictAutoModel:
            @staticmethod
            def from_pretrained(location, *, torch_dtype):
                return location,torch_dtype
        with self.assertRaisesRegex(TypeError,'dtype'):
            StrictAutoModel.from_pretrained('frozen',dtype='fp32')

    def test_loader_has_no_model_or_network_fallback(self):
        source=inspect.getsource(load_frozen_qwen_model)
        self.assertIn('torch_dtype=torch_module.float32',source)
        self.assertNotIn('trust_remote_code=True',source)
        self.assertNotIn('local_files_only=False',source)
        self.assertNotIn('except',source)

    def test_loader_failure_propagates(self):
        class Broken:
            @staticmethod
            def from_pretrained(*args, **kwargs):
                raise RuntimeError('physical model unsupported')
        with self.assertRaisesRegex(RuntimeError,'unsupported'):
            load_frozen_qwen_model(Broken,'frozen',SimpleNamespace(float32=1))


if __name__=='__main__':
    unittest.main()
