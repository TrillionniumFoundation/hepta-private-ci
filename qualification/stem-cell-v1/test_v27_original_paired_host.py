"""Only synthetic adversarial I/O tests; no pretrained Qwen forward is faked."""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import v27_original_paired_prepare as p
import v27_paired_source_review as r


def archived_fixture(path, *, omit=None, duplicated=False):
    blobs = {
        'memory-inputs/reader/model.safetensors': b'weightbytes',
        'memory-inputs/reader/tokenizer.json': b'{"model":"BPE"}',
        'memory-inputs/reader/config.json': b'{"layers":30}',
        'memory-inputs/locomo.json': b'["opaque"]',
    }
    expected = {k:(hashlib.sha256(v).hexdigest(),len(v)) for k,v in blobs.items()}
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode='w:gz') as t:
        for key, value in blobs.items():
            if key == omit: continue
            for _ in range(2 if duplicated and key.endswith('tokenizer.json') else 1):
                ent = tarfile.TarInfo(key)
                ent.size = len(value)
                t.addfile(ent,io.BytesIO(value))
    with zipfile.ZipFile(path,'w') as f:
        f.writestr('memory-inputs.tar.gz',tar_buffer.getvalue())
    return expected


class V27SyntheticContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.zip = self.root/'test.zip'
        self.expected = archived_fixture(self.zip)

    def extract(self,**kwargs):
        with patch.object(p,'audit_archive',return_value={'decision':'SYNTHETIC_ONLY'}), \
             patch.object(p,'EXPECTED',self.expected):
            return p.extract_pinned(self.zip,self.root/'private',**kwargs)

    def test_synthetic_fixture_extracts_exact_four_regular_files(self):
        found=self.extract()
        self.assertEqual(set(found),set(self.expected))
        for filename,rel in p.TARGETS.items():
            blob=(self.root/'private'/rel)
            self.assertTrue(blob.is_file())
            self.assertFalse(blob.is_symlink())
            self.assertEqual(blob.stat().st_mode & 0o777,0o600)

    def test_denies_preexisting_workspace(self):
        (self.root/'private').mkdir()
        with self.assertRaises(ValueError):self.extract()

    def test_rejects_missing_source(self):
        archived_fixture(self.zip,omit='memory-inputs/locomo.json')
        with self.assertRaises(ValueError):self.extract()
        self.assertFalse((self.root/'private').exists())

    def test_rejects_repeated_source(self):
        archived_fixture(self.zip,duplicated=True)
        with self.assertRaises(ValueError):self.extract()
        self.assertFalse((self.root/'private').exists())

    def test_rejects_mutated_weight_bytes(self):
        self.expected['memory-inputs/reader/model.safetensors']=('0'*64,11)
        with self.assertRaises(ValueError):self.extract()

    def test_rejects_foreign_zip_entry(self):
        with zipfile.ZipFile(self.zip,'a') as f:f.writestr('foreign.txt','private source')
        with self.assertRaises(ValueError):self.extract()

    def test_frozen_real_archive_profile(self):
        self.assertEqual(p.ARTIFACT_SHA256,'07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af')
        self.assertEqual(len(p.TARGETS),4)

    def test_source_writer_is_create_only(self):
        file=self.root/'created.json'
        p.write_new(file,{'production_authorized':False})
        self.assertEqual(file.stat().st_mode & 0o777,0o600)
        with self.assertRaises(FileExistsError):p.write_new(file,{'production_authorized':True})

    def test_denies_unsealed_physical_source(self):
        with self.assertRaises(ValueError):r.review({}, {}, {}, {}, {}, {}, [])

    def test_denies_invented_qwen_128_without_physical_model(self):
        plan={'requests':{'fake':'row'}}
        with self.assertRaises(ValueError):r.review(plan,{'requests':128},{'verified_requests':128},{'reference_request_count':128},{'verified_reference_requests':128},{},[])

    def test_denies_fake_reference_capacity_promotion(self):
        with self.assertRaises(ValueError):r.review({}, {'production_authorized':True},{},{},{},{},[])

    def test_no_original_source_bytes_embedded_in_code(self):
        code=(Path(p.__file__).read_text()+Path(r.__file__).read_text())
        for dangerous in ('<|im_start|>user\nQuestion:', 'Paris is the capital', 'AKIA', 'hf_'):
            self.assertNotIn(dangerous,code)

    def test_no_claimed_semantic_success(self):
        for module in (p,r):
            self.assertIn('production_authorized',Path(module.__file__).read_text())

if __name__=='__main__':unittest.main()
