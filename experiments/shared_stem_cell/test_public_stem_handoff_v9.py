"""Only synthetic V8 receipt fixtures; do not claim real model execution."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace as NS

from public_stem_material_v8 import (
    CATALOG, RECEIPT, PROBE_TEXTS, canonical, make_plan, probe_input_digest, sha
)
from public_stem_handoff_v9 import AdmissionError, PROFILE, SCHEMA, _json, handoff, main

REVISION = '1'*40


def fixture(root, candidate='granite-97m-r2'):
    blobs={'config.json':b'{"model_type":"bert"}',
           'tokenizer.json':b'{"tokenizer": true}',
           'tokenizer_config.json':b'{"tokenizer": "test"}',
           'model.safetensors':b'tiny-not-pretrained'}
    info=NS(id=CATALOG[candidate]['repo_id'],sha=REVISION,siblings=[
        NS(rfilename=k,size=len(v),lfs={'sha256':hashlib.sha256(v).hexdigest()})
        for k,v in blobs.items()])
    plan=make_plan(candidate,info)
    for k,raw in blobs.items():
        (root/k).write_bytes(raw)
    digests={k:sha(raw) for k,raw in blobs.items()}
    manifest={'revision':REVISION,'kind':plan['profile']['kind'],'files':digests}
    material={'revision':REVISION,'file_sha256s':digests,'manifest':manifest}
    physical={'schema':RECEIPT,'candidate':candidate,'repo_id':plan['repo_id'],
              'revision':REVISION,'snapshot_digest':sha(canonical(manifest)),
              'plan_sha256':sha(canonical(plan)), 'pooling':plan['profile']['pooling'],
              'normalization':plan['profile']['normalization'],
              'feature_width':plan['profile']['width'],
              'feature_sha256':sha(b'fake-physical-feature'),
              'probe_input_sha256':probe_input_digest(PROBE_TEXTS),
              'probe_count':len(PROBE_TEXTS),
              'forward_calls':2,'wall_ns':1,'cpu_ns':1,
              'process_lifetime_peak_rss_bytes':1,
              'pretrained_source_independently_attested':False,
              'matched_pair_completed':False,'heldout_efficacy_evaluated':False,
              'production_accepted':False,'authority':'DENY_ALL'}
    return plan,material,physical


class V9HandoffTests(unittest.TestCase):
    def test_real_identifiers_only_form_non_authoritative_linkage(self):
        for candidate in CATALOG:
            with self.subTest(candidate=candidate),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                plan,material,physical=fixture(root,candidate)
                profile,receipt=handoff(plan,material,physical,root)
                self.assertEqual(profile['schema'],PROFILE)
                self.assertEqual(profile['pooling'],CATALOG[candidate]['pooling'])
                self.assertEqual(receipt['schema'],SCHEMA)
                self.assertEqual(receipt['snapshot_sha256'],physical['snapshot_digest'])
                self.assertFalse(receipt['v5_train_predict_completed'])
                self.assertFalse(receipt['independently_attested_physical_execution'])
                self.assertFalse(receipt['production_accepted'])
                self.assertEqual(receipt['authority'],'DENY_ALL')

    def test_every_byte_is_rehashed_before_profile_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);plan,material,physical=fixture(root)
            (root/'model.safetensors').write_bytes(b'tiny-not-pretrainee')
            with self.assertRaisesRegex(AdmissionError,'digest changed'):
                handoff(plan,material,physical,root)
            (root/'model.safetensors').write_bytes(b'tiny-not-pretrained')
            (root/'unregistered.bin').write_bytes(b'extra')
            with self.assertRaisesRegex(AdmissionError,'undeclared'):
                handoff(plan,material,physical,root)

    def test_cross_model_and_pooling_identity_drift_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);plan,material,physical=fixture(root)
            for k,v in [('candidate','mmbert-small'),('pooling','attention-mask-mean'),
                        ('normalization','none'),('feature_width',100),
                        ('snapshot_digest','f'*64),('plan_sha256','f'*64)]:
                copy_p={**physical,k:v}
                if copy_p[k] == physical[k]:
                    continue
                with self.subTest(field=k),self.assertRaisesRegex(AdmissionError,'physical receipt'):
                    handoff(plan,material,copy_p,root)

    def test_handoff_rejects_missing_or_changed_probe_census(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);plan,material,physical=fixture(root)
            for key,value in (("probe_count",0),
                              ("probe_count",True),
                              ("probe_input_sha256","f"*64)):
                with self.subTest(key=key,value=value):
                    with self.assertRaisesRegex(AdmissionError,"input census"):
                        handoff(plan,material,{**physical,key:value},root)
            for field in ("probe_count","probe_input_sha256"):
                broken={k:v for k,v in physical.items() if k!=field}
                with self.subTest(missing=field),self.assertRaisesRegex(
                        AdmissionError,"input census"):
                    handoff(plan,material,broken,root)

    def test_missing_physical_observation_or_fake_authority_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);plan,material,physical=fixture(root)
            for k,v in [('forward_calls',0),('wall_ns',0),
                        ('feature_sha256','bad'),('cpu_ns',None)]:
                with self.subTest(field=k),self.assertRaises(AdmissionError):
                    handoff(plan,material,{**physical,k:v},root)
            for k,v in [('pretrained_source_independently_attested',True),
                        ('production_accepted',True),('authority','ALLOW')]:
                with self.subTest(field=k),self.assertRaisesRegex(AdmissionError,'authority'):
                    handoff(plan,material,{**physical,k:v},root)

    def test_profile_cannot_use_modified_manifest_or_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);plan,material,physical=fixture(root)
            for value in ({**material,'revision':'2'*40},
                          {**material,'manifest':{**material['manifest'],'kind':'masked_lm'}},
                          {**material,'file_sha256s':{**material['file_sha256s'],
                                                      'phantom.bin':'f'*64}}):
                with self.assertRaises(AdmissionError):
                    handoff(plan,value,physical,root)

    def test_cli_writes_exact_two_files_and_rejects_duplicate_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);model=root/'model';model.mkdir()
            plan,material,physical=fixture(model)
            paths=[root/'plan.json',root/'material.json',root/'physical.json']
            for path,obj in zip(paths,(plan,material,physical)):
                path.write_bytes(canonical(obj))
            args=['--plan',str(paths[0]),'--material',str(paths[1]),
                  '--physical',str(paths[2]),'--model-root',str(model),
                  '--output',str(root/'out')]
            self.assertEqual(main(args),0)
            self.assertEqual({p.name for p in (root/'out').iterdir()},
                             {'profile.json','handoff.json'})
            with self.assertRaisesRegex(AdmissionError,'duplicate'):
                paths[1].write_text('{"schema":1,"schema":2}')
                _json(paths[1])
            self.assertEqual(main(args),2)


if __name__=='__main__':
    unittest.main()
