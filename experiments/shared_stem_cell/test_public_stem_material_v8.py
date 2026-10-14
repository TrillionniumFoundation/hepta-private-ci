"""Offline contract checks: no pretrained weights, no model-quality claims."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS
import tempfile
import unittest

from public_stem_material_v8 import (
    AdmissionError, CATALOG, SCHEMA, acquire, canonical, make_plan,
    strict_json, validate_plan, verify_hub_against_plan,
)

REV = "1"*40


def fixture(candidate="granite-97m-r2"):
    files = {
        "config.json":b'{"model_type":"modernbert"}',
        "tokenizer.json":b'{"type":"test"}',
        "tokenizer_config.json":b'{"special_tokens":[]}',
        "model.safetensors":b'test-fixture-not-a-safetensor',
    }
    sib = []
    for name,data in files.items():
        sha = hashlib.sha256(data).hexdigest()
        sib.append(NS(rfilename=name, size=len(data), lfs={"sha256":sha}))
    info=NS(id=CATALOG[candidate]["repo_id"],sha=REV,siblings=sib)
    return info, files


class PublicStemMaterialTests(unittest.TestCase):
    def test_plan_has_two_independent_exact_sources(self):
        for candidate in CATALOG:
            info, _ = fixture(candidate)
            plan = make_plan(candidate, info)
            self.assertEqual(validate_plan(plan),plan)
            self.assertEqual(plan["revision"],REV)
            self.assertEqual(plan["profile"]["width"],384)
            self.assertEqual(plan["source_authority"],
                "untrusted_public_hub_metadata_no_publisher_attestation")
            self.assertIs(plan["production_accepted"],False)
        self.assertEqual(CATALOG["mmbert-small"]["pooling"],"attention-mask-mean")
        self.assertEqual(CATALOG["granite-97m-r2"]["pooling"],"cls-first-token")

    def test_never_accept_moving_tag_as_run_revision(self):
        info,_=fixture()
        plan=make_plan("granite-97m-r2",info)
        plan["revision"]="main"
        with self.assertRaisesRegex(AdmissionError,"unversioned"):
            validate_plan(plan)

    def test_reject_wrong_publisher_or_repository_and_source_digest(self):
        info,_=fixture()
        with self.assertRaisesRegex(AdmissionError,"model identity"):
            make_plan("mmbert-small",info)
        plan=make_plan("granite-97m-r2",info)
        with self.assertRaisesRegex(AdmissionError,"revision or inventory changed"):
            verify_hub_against_plan(plan,NS(id=info.id,sha="2"*40,siblings=info.siblings))
        with self.assertRaisesRegex(AdmissionError,"revision or inventory changed"):
            altered_siblings = [NS(rfilename=x.rfilename, size=x.size, lfs=x.lfs)
                                for x in info.siblings]
            altered_siblings[0].size += 1
            altered=NS(id=info.id,sha=info.sha,siblings=altered_siblings)
            verify_hub_against_plan(plan,altered)

    def test_reject_unknown_weights_and_metadata_gap(self):
        info,_=fixture()
        info.siblings=[x for x in info.siblings if x.rfilename!="tokenizer.json"]
        with self.assertRaisesRegex(AdmissionError,"essentials"):
            make_plan("granite-97m-r2",info)
        info,_=fixture()
        info.siblings=[x for x in info.siblings if x.rfilename!="model.safetensors"]
        with self.assertRaisesRegex(AdmissionError,"weights"):
            make_plan("granite-97m-r2",info)

    def test_reject_nonpositive_and_unknown_remote_file_size(self):
        for size in (None,0,-1,1201*1024*1024):
            info,_=fixture()
            info.siblings[0].size=size
            with self.subTest(size=size),self.assertRaisesRegex(AdmissionError,"unmeasured or oversized"):
                make_plan("granite-97m-r2",info)

    def test_deduplicate_and_forbid_mixed_unordered_material(self):
        info,_=fixture()
        info.siblings.append(info.siblings[-1])
        with self.assertRaisesRegex(AdmissionError,"duplicate Hub"):
            make_plan("granite-97m-r2",info)
        info,_=fixture()
        plan=make_plan("granite-97m-r2",info)
        plan["files"] = plan["files"][::-1]
        with self.assertRaisesRegex(AdmissionError,"noncanonical"):
            validate_plan(plan)

    def test_reject_unsafe_paths_and_overbound_inventory(self):
        info,_=fixture()
        plan=make_plan("granite-97m-r2",info)
        plan["files"][0]["name"]="../config.json"
        with self.assertRaisesRegex(AdmissionError,"unapproved"):
            validate_plan(plan)

    def test_reject_mutated_catalog_or_claimed_production_authority(self):
        info,_=fixture()
        plan=make_plan("granite-97m-r2",info)
        plan["profile"]["pooling"]="attention-mask-mean"
        with self.assertRaisesRegex(AdmissionError,"pooling"):
            validate_plan(plan)
        plan=make_plan("granite-97m-r2",info)
        plan["production_accepted"]=True
        with self.assertRaisesRegex(AdmissionError,"cannot grant"):
            validate_plan(plan)

    def test_reject_duplicate_noncanonical_plan_and_unsafe_symlink(self):
        info,_=fixture()
        plan=make_plan("granite-97m-r2",info)
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/"plan.json"
            f.write_bytes(canonical(plan))
            self.assertEqual(strict_json(f),plan)
            f.write_text(json.dumps(plan))
            with self.assertRaisesRegex(AdmissionError,"canonical"):
                strict_json(f)
            f.write_text('{"schema":"a","schema":"b"}')
            with self.assertRaisesRegex(AdmissionError,"duplicate"):
                strict_json(f)
            f.unlink()
            f.symlink_to(Path(tmp)/"target")
            with self.assertRaises(AdmissionError):
                strict_json(f)

    def test_offline_complete_acquisition_rechecks_every_file(self):
        info,files=fixture()
        plan=make_plan("granite-97m-r2",info)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name,blob in files.items():
                (root/name).write_bytes(blob)
            calls=[]
            def download(repo,name,revision):
                calls.append((repo,name,revision))
                return root/name
            receipt=acquire(plan,root/"snapshot",model_info=info,downloader=download)
            self.assertEqual(sorted(receipt["manifest"]["files"]),sorted(files))
            self.assertEqual(len(calls),len(files))
            self.assertTrue(all(ref==REV for _,_,ref in calls))
            self.assertEqual(receipt["revision"],REV)
            self.assertEqual((root/"snapshot"/"model.safetensors").read_bytes(), files["model.safetensors"])
            with self.assertRaisesRegex(AdmissionError,"new directory"):
                acquire(plan,root/"snapshot",model_info=info,downloader=download)

    def test_download_tampering_rejected_even_before_weight_loader(self):
        info,files=fixture()
        plan=make_plan("granite-97m-r2",info)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name,blob in files.items():
                (root/name).write_bytes(blob)
            (root/"model.safetensors").write_bytes(files["model.safetensors"][:-1]+b'X')
            with self.assertRaisesRegex(AdmissionError,"SHA-256"):
                acquire(plan,root/"snapshot",model_info=info,
                    downloader=lambda _,name,rev:root/name)
            self.assertFalse((root/"snapshot").exists())

    def test_tampered_plan_rejects_missing_or_mixed_shards_without_remote(self):
        info, _ = fixture()
        info.siblings = [row for row in info.siblings
                         if row.rfilename != "model.safetensors"]
        info.siblings.extend([
            NS(rfilename="model-00001-of-00002.safetensors", size=1, lfs={"sha256": "a"*64}),
            NS(rfilename="model-00002-of-00002.safetensors", size=1, lfs={"sha256": "b"*64}),
            NS(rfilename="model.safetensors.index.json", size=8, lfs=None),
        ])
        plan = make_plan("granite-97m-r2", info)
        validate_plan(plan)
        dropped = {**plan, "files": [row for row in plan["files"]
                                    if row["name"] != "model-00002-of-00002.safetensors"]}
        with self.assertRaisesRegex(AdmissionError, "incomplete or inconsistent"):
            validate_plan(dropped)
        mixed = {**plan, "files": [*plan["files"],
                                  {"name": "model.safetensors", "size": 1,
                                   "hub_lfs_sha256": "c"*64}]}
        mixed["files"] = sorted(mixed["files"], key=lambda row: row["name"])
        with self.assertRaisesRegex(AdmissionError, "mixed direct"):
            validate_plan(mixed)

    def test_acquire_verifies_exact_shard_index_semantics(self):
        for bad in (False, True):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                info, base=fixture()
                base.pop("model.safetensors")
                base["model-00001-of-00002.safetensors"] = b"shard-one"
                base["model-00002-of-00002.safetensors"] = b"shard-two"
                mapped=("model-00001-of-00002.safetensors" if bad
                        else "model-00002-of-00002.safetensors")
                base["model.safetensors.index.json"] = json.dumps({"metadata": {},
                    "weight_map": {"layer.0": "model-00001-of-00002.safetensors",
                                   "layer.1": mapped}}).encode()
                info.siblings=[NS(rfilename=name,size=len(blob),
                                  lfs={"sha256":hashlib.sha256(blob).hexdigest()})
                               for name,blob in base.items()]
                plan=make_plan("granite-97m-r2",info)
                for name,blob in base.items():
                    (root/name).write_bytes(blob)
                if bad:
                    with self.assertRaisesRegex(AdmissionError, "does not cover"):
                        acquire(plan,root/"snapshot",model_info=info,
                                downloader=lambda _r,name,_v:root/name)
                    self.assertFalse((root/"snapshot").exists())
                else:
                    result=acquire(plan,root/"snapshot",model_info=info,
                                   downloader=lambda _r,name,_v:root/name)
                    self.assertEqual(len(result["manifest"]["files"]),len(base))

    def test_no_fallback_for_incomplete_sharded_model(self):
        info,_=fixture()
        info.siblings=[x for x in info.siblings if x.rfilename!='model.safetensors']
        info.siblings.extend([
            NS(rfilename='model-00001-of-00002.safetensors',size=1,lfs={'sha256':'a'*64}),
            NS(rfilename='model.safetensors.index.json',size=10,lfs=None),
        ])
        with self.assertRaisesRegex(AdmissionError,"missing model shard"):
            make_plan("granite-97m-r2",info)

if __name__ == "__main__":
    unittest.main()
