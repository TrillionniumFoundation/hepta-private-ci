"""Physical byte checks with tiny fake files; NO pretrained checkpoint/model calls."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as S

import gate
import preflight
import review_bytes
import source_bytes


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git_hash(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def material(model):
    contents = {n: ("weights:" + n).encode() if preflight.is_weight(n) else
                ("config:" + n).encode() for n in preflight.WANTED[model]}
    if model.startswith("laya"):
        contents["tokenizer/tokenizer_config.json"] = b"tiny tokenizer"
    elif model == "ettin400":
        contents["tokenizer_config.json"] = b"tiny tokenizer"
    else:
        contents["spm.model"] = b"tiny spm bytes"
    return contents


def harness(model, *, altered_download=None, extra=None):
    raw=material(model)
    repo,rev,_,_=gate.MODELS[model]
    entries=[]
    for name, data in raw.items():
        weight=preflight.is_weight(name)
        entries.append(S(rfilename=name,size=len(data),lfs={"sha256":sha(data)} if weight else None,
                         blob_id=None if weight else git_hash(data)))
    if extra:
        entries.extend(extra)
    info=S(sha=rev,siblings=entries)
    def lookup(*,repo_id,revision,files_metadata):
        assert repo_id==repo and revision==rev and files_metadata
        return info
    def download(*,repo_id,revision,local_dir,allow_patterns,max_workers):
        assert repo_id==repo and revision==rev and max_workers==2
        assert sorted(allow_patterns)==sorted(raw)
        for name, data in (altered_download or raw).items():
            p=Path(local_dir)/name
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_bytes(data)
        return local_dir
    return lookup,download,raw


class PhysicalSourceTests(unittest.TestCase):
    def test_all_four_verified_original_bytes(self):
        for model in gate.MODELS:
            with self.subTest(model=model), tempfile.TemporaryDirectory() as td:
                lookup,dl,raw=harness(model)
                receipt=source_bytes.acquire(model,lookup,dl,Path(td)/"new")
                self.assertEqual(receipt["file_count"],len(raw))
                self.assertTrue(receipt["selected_source_bytes_verified"])
                self.assertIs(receipt["tensor_model_loaded"],False)
                self.assertIs(receipt["torch_pickle_loaded"],False)
                review=review_bytes.audit(receipt,Path(td)/"new")
                self.assertTrue(review["independently_rehashed_exact_physical_bytes"])
                self.assertFalse(review["production_promotion_permitted"])
    def test_wrong_published_bytes_deny(self):
        lookup,_,raw=harness("ettin400")
        changed=dict(raw)
        changed["pytorch_model.bin"]+=b"!"
        _,dl,_=harness("ettin400",altered_download=changed)
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(gate.Denied):
                source_bytes.acquire("ettin400",lookup,dl,Path(td)/"stage")
    def test_same_size_rehashed_model_denied(self):
        lookup,_,raw=harness("ettin400")
        changed=dict(raw)
        changed["pytorch_model.bin"]=b"?"+raw["pytorch_model.bin"][1:]
        _,dl,_=harness("ettin400",altered_download=changed)
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(gate.Denied): source_bytes.acquire("ettin400",lookup,dl,Path(td)/"stage")
    def test_independent_reviewer_catches_postseal_tamper(self):
        lookup,dl,_=harness("ettin400")
        with tempfile.TemporaryDirectory() as td:
            stage=Path(td)/"stage"
            receipt=source_bytes.acquire("ettin400",lookup,dl,stage)
            (stage/"config.json").write_bytes(b"tampered content")
            with self.assertRaises(review_bytes.Rejected): review_bytes.audit(receipt,stage)
    def test_second_process_denies_late_added_model_config(self):
        lookup,dl,_=harness("ettin400")
        with tempfile.TemporaryDirectory() as td:
            stage=Path(td)/"stage"
            receipt=source_bytes.acquire("ettin400",lookup,dl,stage)
            # The *first* source-byte scan has already passed.
            (stage/"generation_config.json").write_text('{"eos_token_id":0}')
            with self.assertRaisesRegex(review_bytes.Rejected, "unregistered"):
                review_bytes.audit(receipt,stage)

    def test_second_process_denies_late_added_tokenizer_symlink(self):
        lookup,dl,_=harness("ettin400")
        with tempfile.TemporaryDirectory() as td:
            stage=Path(td)/"stage"
            receipt=source_bytes.acquire("ettin400",lookup,dl,stage)
            (stage/"tokenizer_extra.json").symlink_to("tokenizer.json")
            with self.assertRaisesRegex(review_bytes.Rejected,"symlink"):
                review_bytes.audit(receipt,stage)

    def test_second_process_denies_unregistered_empty_dir(self):
        lookup,dl,_=harness("ettin400")
        with tempfile.TemporaryDirectory() as td:
            stage=Path(td)/"stage"
            receipt=source_bytes.acquire("ettin400",lookup,dl,stage)
            (stage/"unregistered").mkdir()
            with self.assertRaisesRegex(review_bytes.Rejected,"unregistered"):
                review_bytes.audit(receipt,stage)

    def test_second_process_allows_only_ordinary_hub_cache(self):
        lookup,dl,_=harness("ettin400")
        with tempfile.TemporaryDirectory() as td:
            stage=Path(td)/"stage"
            receipt=source_bytes.acquire("ettin400",lookup,dl,stage)
            cache=stage/".cache"/"huggingface";cache.mkdir(parents=True)
            (cache/"download").write_bytes(b"cache")
            self.assertTrue(review_bytes.audit(receipt,stage)["independently_rehashed_exact_physical_bytes"])
            (cache/"escape").symlink_to("download")
            with self.assertRaisesRegex(review_bytes.Rejected,"symlink"):
                review_bytes.audit(receipt,stage)

    def test_missing_source_denied(self):
        lookup,_,raw=harness("ettin400")
        changed=dict(raw);changed.pop("tokenizer.json")
        _,dl,_=harness("ettin400",altered_download=changed)
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(gate.Denied): source_bytes.acquire("ettin400",lookup,dl,Path(td)/"stage")
    def test_symlink_weight_denied(self):
        lookup,_,raw=harness("ettin400")
        def dl(*,repo_id,revision,local_dir,allow_patterns,max_workers):
            root=Path(local_dir);(root/"real").write_bytes(raw["pytorch_model.bin"])
            (root/"pytorch_model.bin").symlink_to("real")
            for name,data in raw.items():
                if name!="pytorch_model.bin":(root/name).write_bytes(data)
            return local_dir
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(gate.Denied): source_bytes.acquire("ettin400",lookup,dl,Path(td)/"stage")
    def test_symlink_parent_denied(self):
        lookup,_,raw=harness("laya421")
        def dl(*,repo_id,revision,local_dir,allow_patterns,max_workers):
            root=Path(local_dir)
            (root/"real").mkdir()
            (root/"tokenizer").symlink_to("real",target_is_directory=True)
            for name,data in raw.items():
                p=root/name;p.parent.mkdir(exist_ok=True);p.write_bytes(data)
            return local_dir
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(gate.Denied): source_bytes.acquire("laya421",lookup,dl,Path(td)/"stage")
    def test_unselected_family_weights_not_downloaded(self):
        fake=b"sibling secret weights"
        extra=[S(rfilename="typed-decisions/model.safetensors",size=len(fake),lfs={"sha256":sha(fake)},blob_id=None)]
        lookup,_,raw=harness("laya421",extra=extra)
        def dl(*,repo_id,revision,local_dir,allow_patterns,max_workers):
            self.assertNotIn("typed-decisions/model.safetensors",allow_patterns)
            for name,data in raw.items():
                p=Path(local_dir)/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
            return local_dir
        with tempfile.TemporaryDirectory() as td:
            receipt=source_bytes.acquire("laya421",lookup,dl,Path(td)/"stage")
            self.assertFalse(any("typed-decisions" in x["filename"] for x in receipt["files"]))
    def test_unselected_file_staged_denied(self):
        lookup,_,raw=harness("ettin400")
        def dl(*,repo_id,revision,local_dir,allow_patterns,max_workers):
            for name,data in raw.items():(Path(local_dir)/name).write_bytes(data)
            (Path(local_dir)/"unsafe.py").write_bytes(b"print('unexpected')")
            return local_dir
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(gate.Denied): source_bytes.acquire("ettin400",lookup,dl,Path(td)/"stage")
    def test_wrong_downloader_root_denied(self):
        lookup,_,_=harness("ettin400")
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(gate.Denied):
                source_bytes.acquire("ettin400",lookup,lambda **_:td,Path(td)/"new")
    def test_auditor_rejects_fake_promotion(self):
        lookup,dl,_=harness("ettin400")
        with tempfile.TemporaryDirectory() as td:
            r=source_bytes.acquire("ettin400",lookup,dl,Path(td)/"stage")
            for field in ("production_promotion_permitted","tensor_model_loaded","torch_pickle_loaded"):
                fake=dict(r)
                fake[field]=True
                with self.assertRaises(review_bytes.Rejected): review_bytes.audit(fake,Path(td)/"stage")
    def test_auditor_rejects_duplicate_json_and_nan(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"record.json"
            for text in ('{"a":1,"a":2}', '{"a":NaN}'):
                p.write_text(text)
                with self.assertRaises(review_bytes.Rejected): review_bytes.read_sealed(p)
    def test_create_only_receipts(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"r.json"
            source_bytes.write_new(p,{"authority":"DENY_ALL"})
            with self.assertRaises(gate.Denied):source_bytes.write_new(p,{"authority":"DENY_ALL"})
            self.assertEqual(json.loads(p.read_text())["authority"],"DENY_ALL")
    def test_wrong_git_blob_id_denied(self):
        lookup,dl,_=harness("ettin400")
        def wrong_info(*,repo_id,revision,files_metadata):
            info=lookup(repo_id=repo_id,revision=revision,files_metadata=files_metadata)
            next(v for v in info.siblings if v.rfilename=="config.json").blob_id="0"*40
            return info
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(gate.Denied):source_bytes.acquire("ettin400",wrong_info,dl,Path(td)/"stage")

if __name__=="__main__": unittest.main()
