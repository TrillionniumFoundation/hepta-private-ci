"""Synthetic receipt rejection regressions; no pretrained model is run here."""
from __future__ import annotations

import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import gate
import physical_evidence_review as p


def example(model):
    repo,rev,_,_ = gate.MODELS[model]
    source = {
        "schema":p.SOURCE_SCHEMA,"model":model,"repo":repo,"revision":rev,
        "file_count":5,"source_sha256_receipt":"a"*64,
        "total_bytes_rehashed":1_585_736_960 if model=="ettin400" else 846_195_574,
        "independently_rehashed_exact_physical_bytes":True,
        "actual_model_forward_verified":False,"all_four_models_complete":False,
        "issuer_signature_verified":False,"production_promotion_permitted":False,
        "authority":"DENY_ALL","disposition":"HOLD_NO_GO",
    }
    common={"original_cpu_base_forward_calls":1,"input_tokens":37 if model=="ettin400" else 42,
            "actual_tensor_values_loaded":447_458_496 if model=="ettin400" else 421_293_827,
            "torch_pickle_loaded":False,
            "actual_native_decision_probability":model=="laya421",
            "weights_only_loader_used":model=="ettin400"}
    if model=="ettin400":
        common.update({"output_type":"frozen_encoder_cls_fp32_sha256_not_decision_probability",
                       "feature_sha256":"c"*64,"feature_dimension":1024})
    else:
        common.update({"output_type":"native_laya_noul_probability_not_comparable_to_ettin_cls",
                       "probability":.6782,"runtime_tokenizer_config_modified":False,
                       "runtime_tokenizer_config_sha256":"d"*64,
                       "original_staged_tokenizer_was_not_modified":True})
    forward={"schema":p.FORWARD_SCHEMA,"model":model,"source_receipt_sha256":"a"*64,
             "source_weight_bytes_rehashed":source["total_bytes_rehashed"],"output":common,
             "clock_wall_ns_self_reported":10_000_000_000,
             "clock_cpu_ns_self_reported":8_000_000_000,
             "peak_rss_kib_linux_self_reported":3_000_000,
             "real_forward_on_fixed_unlabeled_probe":True,
             "isolated_allowlist_runtime_snapshot_verified":True,
             "heldout_human_task_score":None,"equal_head_training_budget_verified":False,
             "two_arm_scientific_winner_verified":False,
             "publisher_signature_verified":False,
             "production_promotion_permitted":False,
             "authority":"DENY_ALL","disposition":"HOLD_NO_GO"}
    return source,forward


def zip_fixture(model, source, forward, *, extra=None):
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(f'hepta-reviewed-{model}.json',json.dumps(source))
        z.writestr(f'hepta-forward-{model}.json',json.dumps(forward))
        if extra:
            z.writestr(extra,'not allowed')
    return buf.getvalue()


class PhysicalEvidenceTests(unittest.TestCase):
    def test_positive_synthetic_contract_for_both_models(self):
        for model in p.P1_MODEL_SET:
            with self.subTest(model=model):
                record=p.audit_one(model,*example(model))
                self.assertEqual(record['base_encoder_forward_calls'],1)
                self.assertFalse(record['head_training_and_human_scoring_verified'])

    def test_reject_missing_or_bad_source_identity(self):
        for key,value in [('revision','0'*40),('repo','other'),('model','openjev434'),
                          ('source_sha256_receipt','bad'),('independently_rehashed_exact_physical_bytes',False),
                          ('issuer_signature_verified',True),('authority','PERMIT'),
                          ('file_count',0),('all_four_models_complete',True),
                          ('production_promotion_permitted',True)]:
            source,forward=example('ettin400')
            source[key]=value
            with self.subTest(key=key),self.assertRaises(gate.Denied):
                p.audit_one('ettin400',source,forward)

    def test_reject_claimed_heldout_quality_promotion_or_equated_outputs(self):
        for path,value in [('heldout_human_task_score',.99),
                           ('production_promotion_permitted',True),
                           ('two_arm_scientific_winner_verified',True),
                           ('publisher_signature_verified',True),
                           ('isolated_allowlist_runtime_snapshot_verified',False),
                           ('source_weight_bytes_rehashed',1),
                           ('source_receipt_sha256','0'*64)]:
            source,forward=example('laya421')
            forward[path]=value
            with self.subTest(path=path),self.assertRaises(gate.Denied):
                p.audit_one('laya421',source,forward)

    def test_reject_missing_physical_forward_and_untrusted_output(self):
        for key,value in [('original_cpu_base_forward_calls',0),('actual_tensor_values_loaded',0),
                          ('input_tokens',0),('torch_pickle_loaded',True),
                          ('feature_sha256','0'),('feature_dimension',768),
                          ('actual_native_decision_probability',True)]:
            source,forward=example('ettin400')
            forward['output'][key]=value
            with self.subTest(key=key),self.assertRaises(gate.Denied):
                p.audit_one('ettin400',source,forward)

    def test_native_laya_noul_is_not_cls_score(self):
        source,forward=example('laya421')
        for bad in (float('nan'),float('inf'),-1,.0+1.01):
            badrec=copy.deepcopy(forward);badrec['output']['probability']=bad
            with self.subTest(bad=str(bad)),self.assertRaises(gate.Denied):
                p.audit_one('laya421',source,badrec)

    def test_reject_invalid_40hex_or_stale_p1_head(self):
        with self.assertRaises(gate.Denied):
            p.audit_both('x','y',head='f'*40)

    def test_reject_artifact_zip_without_original_exact_digest(self):
        source,forward=example('ettin400')
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/'pretend.zip'
            file.write_bytes(zip_fixture('ettin400',source,forward))
            with self.assertRaisesRegex(gate.Denied,'does not match pinned'):
                p.read_artifact(file,'ettin400')

    def test_reject_zip_with_extra_files_even_under_test_pin(self):
        source,forward=example('ettin400')
        data=zip_fixture('ettin400',source,forward,extra='model.safetensors')
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/'extra.zip';file.write_bytes(data)
            import hashlib
            with mock.patch.dict(p.PINNED_ZIP_SHA256,{'ettin400':hashlib.sha256(data).hexdigest()}):
                with self.assertRaisesRegex(gate.Denied,'missing/extra'):
                    p.read_artifact(file,'ettin400')

    def test_reject_fake_model_archive_swapped(self):
        source,forward=example('laya421')
        data=zip_fixture('laya421',source,forward)
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/'laya.zip';file.write_bytes(data)
            with self.assertRaises(gate.Denied):
                p.read_artifact(file,'ettin400')

    def test_duplicate_json_fields_denied(self):
        with self.assertRaisesRegex(gate.Denied,'duplicate'):
            p._read_json(b'{"authority":"DENY_ALL","authority":"PERMIT"}')

    def test_nan_inf_json_denied(self):
        for v in [b'NaN',b'Infinity',b'-Infinity']:
            with self.subTest(v=v),self.assertRaises(gate.Denied):
                p._read_json(b'{"number":'+v+b'}')

    def test_read_only_cli_requires_create_new_output(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'audit.json';out.write_text('not overwritten')
            with mock.patch.object(p,'audit_both',return_value={'authority':'DENY_ALL'}):
                with self.assertRaisesRegex(gate.Denied,'refusing overwrite'):
                    p.main(['--ettin','a','--laya','b','--out',str(out)])
            self.assertEqual(out.read_text(),'not overwritten')


if __name__=='__main__':
    unittest.main()
