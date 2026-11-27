import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from public_encoder_probe import ALLOWED_FILES, MODEL_ID, acquire_public, freeze_public_source


class PublicProbeTests(unittest.TestCase):
    def info(self):
        return SimpleNamespace(sha='a'*40, siblings=[SimpleNamespace(rfilename=n,size=2) for n in ALLOWED_FILES])

    def test_only_explicit_stock_files_enter_lock(self):
        info=self.info();info.siblings.append(SimpleNamespace(rfilename='pytorch_model.bin',size=9))
        lock=freeze_public_source(info)
        self.assertEqual(set(lock['files']),set(ALLOWED_FILES))
        self.assertEqual(lock['model_id'],MODEL_ID)
        self.assertFalse(lock['independent_material_approval'])

    def test_missing_safe_weights_duplicate_and_large_download_reject(self):
        for mode in ('missing','duplicate','large','mutable'):
            info=self.info()
            if mode=='missing': info.siblings=[f for f in info.siblings if f.rfilename!='model.safetensors']
            if mode=='duplicate':info.siblings.append(info.siblings[0])
            if mode=='large':info.siblings[0].size=10**10
            if mode=='mutable':info.sha='main'
            with self.subTest(mode=mode),self.assertRaises(ValueError):freeze_public_source(info)

    def test_pin_is_written_before_transfer_and_no_authentication_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def download(repo,**kw):
                self.assertEqual(repo,MODEL_ID)
                self.assertFalse(kw['token'])
                self.assertEqual(kw['revision'],'a'*40)
                self.assertTrue((root/'source-lock.json').is_file())
                cache=Path(kw['local_dir']);cache.mkdir()
                for n in kw['allow_patterns']:(cache/n).write_bytes(b'{}')
            fake=SimpleNamespace(HfApi=lambda **kw:SimpleNamespace(model_info=lambda *a,**k:self.info()),
                                 snapshot_download=download)
            with patch.dict('sys.modules',{'huggingface_hub':fake}): target=acquire_public(root)
            self.assertEqual({x.name for x in target.iterdir()},set(ALLOWED_FILES))
            self.assertTrue((root/'downloaded-material.json').is_file())

    def test_network_transfer_failure_preserves_frozen_source_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def fail(*a,**k):raise OSError('offline')
            fake=SimpleNamespace(HfApi=lambda **kw:SimpleNamespace(model_info=lambda *a,**k:self.info()),
                                 snapshot_download=fail)
            with patch.dict('sys.modules',{'huggingface_hub':fake}),self.assertRaises(OSError):acquire_public(root)
            self.assertTrue((root/'source-lock.json').is_file())
            self.assertFalse((root/'downloaded-material.json').exists())

    def test_cli_import_does_not_require_transformers_or_network(self):
        result=subprocess.run([sys.executable,str(Path(__file__).with_name('public_encoder_probe.py')),'--help'],
                              capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('--acquire-public',result.stdout)


if __name__=='__main__':unittest.main()
