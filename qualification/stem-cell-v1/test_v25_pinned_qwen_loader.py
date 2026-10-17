"""No-pretrained, source-scope regressions for exact pinned 4.53.3 Qwen loader."""
from __future__ import annotations
import ast
from pathlib import Path
from unittest import TestCase

from v25_pinned_qwen_loader import load_local_qwen_fp32


class Tracer:
    def __init__(self):
        self.calls = []
    def from_pretrained(self, path, **options):
        if 'dtype' in options:
            raise TypeError("Qwen3ForCausalLM.__init__() got an unexpected keyword argument 'dtype'")
        self.calls.append((path, options))
        return self
    def eval(self):
        return self


class PinnedQwenLoaderTests(TestCase):
    def test_explicit_torch_dtype_and_restricted_file_policy(self):
        factory = Tracer()
        sentinel = object()
        model = load_local_qwen_fp32('/tmp/readonly-qwen', model_loader=factory, torch_dtype=sentinel)
        self.assertIs(model, factory)
        self.assertEqual(factory.calls, [('/tmp/readonly-qwen', {
            'local_files_only': True,
            'trust_remote_code': False,
            'use_safetensors': True,
            'torch_dtype': sentinel,
        })])

    def test_pathlike_model_folder_keeps_absolute_lexical_identity(self):
        factory = Tracer()
        folder = Path('/tmp/frozen-qwen')
        load_local_qwen_fp32(folder, model_loader=factory, torch_dtype=object())
        self.assertEqual(factory.calls[0][0], str(folder))

    def test_missing_dtype_rejected_before_loader(self):
        factory = Tracer()
        with self.assertRaises(ValueError):
            load_local_qwen_fp32('/tmp/readonly-qwen', model_loader=factory, torch_dtype=None)
        self.assertEqual(factory.calls, [])

    def test_empty_path_rejected_before_loader(self):
        factory = Tracer()
        with self.assertRaises(ValueError):
            load_local_qwen_fp32(' ', model_loader=factory, torch_dtype=object())
        self.assertEqual(factory.calls, [])

    def test_both_existing_physical_entrypoints_use_exact_same_adapter(self):
        root = Path(__file__).resolve().parent
        for filename in ('v17_reference_reader_physical.py', 'v18_reference_public_smoke.py'):
            with self.subTest(filename=filename):
                source = (root / filename).read_text(encoding='utf8')
                tree = ast.parse(source)
                imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                           and n.module == 'v25_pinned_qwen_loader']
                self.assertEqual(len(imports), 1)
                self.assertIn('load_local_qwen_fp32', [x.name for x in imports[0].names])
                calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Name) and n.func.id == 'load_local_qwen_fp32']
                self.assertEqual(len(calls), 1)
                kwargs = {x.arg for x in calls[0].keywords}
                self.assertEqual(kwargs, {'model_loader','torch_dtype'})
                self.assertFalse(any(
                    isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == 'from_pretrained'
                    and isinstance(n.func.value, ast.Name)
                    and n.func.value.id == 'AutoModelForCausalLM'
                    for n in ast.walk(tree)))


if __name__ == '__main__':
    import unittest
    unittest.main()
