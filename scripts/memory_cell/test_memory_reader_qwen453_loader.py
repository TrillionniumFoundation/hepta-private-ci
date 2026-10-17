"""Minimal strict 4.53.3 loader regression; fixtures are NOT physical Qwen inference."""
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock

import memory_reader_strong_reference as reader


class PinnedLoaderTests(TestCase):
    def test_4533_uses_torch_dtype_keyword_not_forwarded_dtype(self):
        model = Mock()
        model.eval.return_value = model

        class Strict4533:
            @staticmethod
            def from_pretrained(folder, **kwargs):
                if 'dtype' in kwargs:
                    raise TypeError("Qwen3ForCausalLM.__init__() got an unexpected keyword argument 'dtype'")
                self.assertEqual(folder, '/frozen/model')
                self.assertEqual(kwargs, {
                    'local_files_only': True,
                    'trust_remote_code': False,
                    'use_safetensors': True,
                    'torch_dtype': 'fp32-sentinel',
                    'attn_implementation': 'eager',
                })
                return model

        actual = reader.load_frozen_qwen(Strict4533, '/frozen/model', precision='fp32-sentinel')
        self.assertIs(actual, model)
        model.eval.assert_called_once_with()

    def test_pretrained_loader_error_fails_closed_no_model_fallback(self):
        class FailLoad:
            called = 0
            @classmethod
            def from_pretrained(cls, path, **kwargs):
                cls.called += 1
                raise RuntimeError('original pinned model bytes unavailable')
        with self.assertRaisesRegex(RuntimeError, 'original pinned model bytes unavailable'):
            reader.load_frozen_qwen(FailLoad, Path('/no-weights'), precision='fp32')
        self.assertEqual(FailLoad.called, 1)

    def test_loader_never_uses_network_or_remote_code(self):
        calls = []
        class Tracer:
            @staticmethod
            def from_pretrained(path, **kwargs):
                calls.append(kwargs)
                return Mock()
        reader.load_frozen_qwen(Tracer, '/frozen', precision='fp32')
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]['local_files_only'])
        self.assertFalse(calls[0]['trust_remote_code'])
        self.assertTrue(calls[0]['use_safetensors'])
