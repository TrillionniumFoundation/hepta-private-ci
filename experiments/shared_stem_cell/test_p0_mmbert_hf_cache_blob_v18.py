"""Fake local content-addressed HF caches; original large model not loaded here."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from p0_mmbert_hf_cache_blob_v18 import (
    Invalid,REPO_CACHE_SLUG,REVISION,resolve_pinned_hf_cache_blob)

class OriginalHFContentBlobTests(unittest.TestCase):
    def create(self, root, *, fake_bytes=None):
        if fake_bytes is None:fake_bytes=b'pretrained-source-fixture'+bytes(range(256))*16
        sha=hashlib.sha256(fake_bytes).hexdigest()
        repo=Path(root)/REPO_CACHE_SLUG
        (repo/'blobs').mkdir(parents=True)
        snapshot=repo/'snapshots'/REVISION;snapshot.mkdir(parents=True)
        blob=repo/'blobs'/sha;blob.write_bytes(fake_bytes)
        alias=snapshot/'model.safetensors';alias.symlink_to('../../blobs/'+sha)
        return alias,blob

    def test_exact_content_addressed_alias_resolves_to_regular_blob(self):
        with tempfile.TemporaryDirectory() as t:
            alias,blob=self.create(t)
            result=resolve_pinned_hf_cache_blob(alias,REVISION)
            self.assertEqual(result,blob)
            self.assertFalse(result.is_symlink())
            self.assertTrue(alias.is_symlink())

    def test_registered_snapshot_regular_file_remains_allowed(self):
        with tempfile.TemporaryDirectory() as t:
            alias,blob=self.create(t)
            alias.unlink();alias.write_bytes(blob.read_bytes())
            self.assertEqual(resolve_pinned_hf_cache_blob(alias,REVISION),alias)

    def test_different_revision_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as t:
            alias,_=self.create(t)
            with self.assertRaises(Invalid):resolve_pinned_hf_cache_blob(alias,'f'*40)

    def test_different_repo_namespace_not_accepted(self):
        with tempfile.TemporaryDirectory() as t:
            alias,_=self.create(t)
            alias.parent.parent.parent.rename(Path(t)/'models--wrong--mmBERT-small')
            with self.assertRaises(Invalid):resolve_pinned_hf_cache_blob(alias,REVISION)

    def test_altered_cache_blob_detected_by_original_sha(self):
        with tempfile.TemporaryDirectory() as t:
            alias,blob=self.create(t)
            blob.write_bytes(blob.read_bytes()+b'tampered')
            with self.assertRaises(Invalid):resolve_pinned_hf_cache_blob(alias,REVISION)

    def test_missing_original_blob_remains_failure(self):
        with tempfile.TemporaryDirectory() as t:
            alias,blob=self.create(t)
            blob.unlink()
            with self.assertRaises((Invalid,FileNotFoundError)):
                resolve_pinned_hf_cache_blob(alias,REVISION)

    def test_absolute_symlink_not_accepted(self):
        with tempfile.TemporaryDirectory() as t:
            alias,blob=self.create(t)
            alias.unlink();alias.symlink_to(blob)
            with self.assertRaises(Invalid):resolve_pinned_hf_cache_blob(alias,REVISION)

    def test_directory_escape_not_accepted(self):
        with tempfile.TemporaryDirectory() as t:
            alias,blob=self.create(t)
            fake=Path(t)/'external.safetensors';fake.write_bytes(blob.read_bytes())
            alias.unlink();alias.symlink_to(fake)
            with self.assertRaises(Invalid):resolve_pinned_hf_cache_blob(alias,REVISION)

    def test_extra_ancestor_link_not_accepted(self):
        with tempfile.TemporaryDirectory() as t:
            alias,blob=self.create(t)
            root=alias.parent.parent.parent
            fake=root/'fake';fake.symlink_to(blob)
            alias.unlink();alias.symlink_to('../../fake')
            with self.assertRaises(Invalid):resolve_pinned_hf_cache_blob(alias,REVISION)

    def test_short_or_unsafe_source_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            alias,blob=self.create(t,fake_bytes=b'tiny')
            with self.assertRaises(Invalid):resolve_pinned_hf_cache_blob(alias,REVISION)

    def test_source_name_must_remain_model_safetensors(self):
        with tempfile.TemporaryDirectory() as t:
            alias,blob=self.create(t)
            alias.rename(alias.with_name('changed.safetensors'))
            with self.assertRaises(Invalid):resolve_pinned_hf_cache_blob(alias.with_name('changed.safetensors'),REVISION)

    def test_disallow_foreign_types_and_nonnative_revision(self):
        with tempfile.TemporaryDirectory() as t:
            alias,blob=self.create(t)
            for p,r in [(None,REVISION),(alias,None),(alias,42),(str(alias),'0'*40)]:
                with self.subTest(v=str(r)),self.assertRaises(Invalid):
                    resolve_pinned_hf_cache_blob(p,r)

    def test_native_safetensors_reader_receives_verified_regular_blob(self):
        import torch
        from safetensors.torch import save_file
        from safetensors import safe_open
        with tempfile.TemporaryDirectory() as t:
            src=torch.linspace(-.5,.5,9*384).reshape(9,384).clone()
            file=Path(t)/'small.safetensors'
            save_file({'decoder.weight':src},str(file))
            alias,blob=self.create(t,fake_bytes=file.read_bytes())
            regular=resolve_pinned_hf_cache_blob(alias,REVISION)
            # Native Torch+safetensors can read the verified ordinary blob
            # without bypassing the original loader's separate full checks.
            self.assertFalse(regular.is_symlink())
            with safe_open(str(regular),framework='pt',device='cpu') as f:
                self.assertEqual(f.keys(),['decoder.weight'])
                self.assertTrue(torch.equal(f.get_tensor('decoder.weight'),src))

if __name__=='__main__':unittest.main()
