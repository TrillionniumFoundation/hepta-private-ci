"""Offline fault and identity tests for *real pinned* Laya local checkpoint loader.

Only synthetic small material is used; no genuine pretrained weights or
model quality results are inferred from this suite.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock

from p0_laya_snapshot_v14 import (
    Invalid, MODEL_ID, REVISION, REQUIRED, PATTERNS, MAX_FILE_BYTES,
    load_pinned_laya, _exact_file,
)


class FakeModel:
    def predict(self, state, questions):
        return {"answers": {"supports": {"noul": 0.375}}}


class PinnedNativeLoaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.files = {
            "model.safetensors": b"this is a tiny FAKE serialized model, not original weights",
            "rl_agent_config.json": b'{"model_type":"synthetic"}',
            "tokenizer/tokenizer.json": b'{"synthetic":"tokenizer"}',
            "tokenizer/tokenizer_config.json": b'{"synthetic":true}',
            "encoder/config.json": b'{"synthetic":"encoder"}',
        }
        for name, data in self.files.items():
            p = self.root/name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        self.info_sha = REVISION
        self.siblings = self.make_siblings()
        self.loader = Mock(return_value=FakeModel())
        self.calls = []

    def make_siblings(self):
        return [SimpleNamespace(rfilename=name, size=len(data),
                                lfs={'sha256': hashlib.sha256(data).hexdigest()} if
                                name == 'model.safetensors' else None)
                for name, data in self.files.items()]

    def model_info(self, **kw):
        self.calls.append(('info', kw))
        self.assertEqual(kw, {'repo_id': MODEL_ID, 'revision': REVISION,
                              'files_metadata': True})
        return SimpleNamespace(sha=self.info_sha, siblings=self.siblings)

    def download(self, **kw):
        self.calls.append(('snapshot', kw))
        self.assertEqual(kw, {'repo_id': MODEL_ID, 'revision': REVISION,
                              'allow_patterns': list(PATTERNS)})
        return str(self.root)

    def load(self):
        return load_pinned_laya(model_info=self.model_info, download=self.download,
                                load_agent=self.loader)

    def test_pinned_original_local_loader_uses_no_unsupported_revision_keyword(self):
        agent, receipt = self.load()
        self.assertEqual(agent.predict('', {})['answers']['supports']['noul'], .375)
        self.loader.assert_called_once_with(str(self.root), device='cpu', fast=False)
        self.assertEqual([c[0] for c in self.calls], ['info','snapshot'])
        self.assertEqual(set(receipt['files']), REQUIRED)
        self.assertEqual(receipt['model_revision'], REVISION)
        self.assertTrue(receipt['publisher_lfs_model_digest_checked'])
        self.assertFalse(receipt['publisher_signature_independently_verified'])
        self.assertFalse(receipt['production_promotion_permitted'])
        self.assertEqual(receipt['authority'],'DENY_ALL')

    def test_wrong_hub_commit_never_loads_model(self):
        self.info_sha='0'*40
        with self.assertRaises(Invalid):self.load()
        self.loader.assert_not_called()
        self.assertEqual([c[0] for c in self.calls],['info'])

    def test_missing_original_weights_never_loads(self):
        (self.root/'model.safetensors').unlink()
        with self.assertRaises(Invalid):self.load()
        self.loader.assert_not_called()

    def test_missing_pretrained_publisher_lfs_sha_never_loads(self):
        for s in self.siblings:
            if s.rfilename=='model.safetensors':s.lfs=None
        with self.assertRaises(Invalid):self.load()
        self.loader.assert_not_called()

    def test_changed_and_rehashed_local_weight_cannot_reuse_old_publisher_digest(self):
        (self.root/'model.safetensors').write_bytes(b'different local weight bytes')
        with self.assertRaisesRegex(Invalid, 'size differs|SHA mismatch'):
            self.load()
        self.loader.assert_not_called()

    def test_new_bytes_same_length_detected_by_lfs_digest(self):
        model=self.root/'model.safetensors'
        b=model.read_bytes()
        model.write_bytes(b'X'+b[1:])
        with self.assertRaisesRegex(Invalid, 'LFS SHA mismatch'):
            self.load()
        self.loader.assert_not_called()

    def test_required_original_source_component_must_exist(self):
        for name in sorted(REQUIRED):
            with self.subTest(name=name):
                s=next(s for s in self.siblings if s.rfilename==name)
                self.siblings.remove(s)
                with self.assertRaises(Invalid):self.load()
                self.siblings.append(s)
        self.loader.assert_not_called()

    def test_symlinked_same_source_bytes_are_hashed_not_trusted_by_path(self):
        p=self.root/'model.safetensors'
        alternate=self.root/'cached-blob'
        p.replace(alternate)
        p.symlink_to(alternate)
        agent, r=self.load()
        self.assertTrue(r['publisher_lfs_model_digest_checked'])
        self.loader.assert_called_once()

    def test_symlinked_malicious_weights_with_different_bytes_denied(self):
        p=self.root/'model.safetensors'
        p.unlink()
        target=self.root/'other-model-blob'
        target.write_bytes(b'A'*len(self.files['model.safetensors']))
        p.symlink_to(target)
        with self.assertRaisesRegex(Invalid, 'LFS SHA mismatch'):
            self.load()
        self.loader.assert_not_called()

    def test_snapshot_invalid_download_path_never_calls_native_loader(self):
        with self.assertRaises(Invalid):
            load_pinned_laya(model_info=self.model_info,
                             download=lambda **kw: str(self.root/'absent'),
                             load_agent=self.loader)
        self.loader.assert_not_called()

    def test_publisher_inventory_not_duplicated(self):
        self.siblings.append(self.siblings[0])
        with self.assertRaisesRegex(Invalid,'duplicate'):
            self.load()
        self.loader.assert_not_called()

    def test_snapshot_non_native_or_fake_agent_never_gets_receipt(self):
        self.loader.return_value=object()
        with self.assertRaisesRegex(Invalid, 'interface absent'):
            self.load()

    def test_original_path_allowlist_rejects_traversal_and_hidden(self):
        for value in ('../model.safetensors','tokenizer/../model.safetensors',
                      '/tokenizer/tokenizer.json','tokenizer/.hidden','tokenizer/a/b',
                      'encoder/./config.json','',None,'other/root.txt'):
            with self.subTest(value=value):self.assertFalse(_exact_file(value))
        self.assertTrue(_exact_file('model.safetensors'))

    def test_empty_config_fails_before_native_model_loading(self):
        (self.root/'rl_agent_config.json').write_bytes(b'')
        with self.assertRaises(Invalid):self.load()
        self.loader.assert_not_called()

    def test_source_inventory_budget_is_bounded(self):
        self.assertGreater(MAX_FILE_BYTES, 843_000_000)
        self.assertLess(MAX_FILE_BYTES, 3_000_000_000)


if __name__=='__main__':
    unittest.main()
