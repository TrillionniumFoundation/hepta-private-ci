"""Synthetic GH Actions API envelope tests — NOT a real physical Model PASS."""
from __future__ import annotations
import copy
import json
import tempfile
from pathlib import Path
import unittest

import e3_physical_run_metadata_admission as m

SHA="a"*40
def fixture():
    run={"id":123,"name":m.WORKFLOW,"event":"push",
         "head_branch":m.BRANCH,"head_sha":SHA,
         "repository":{"full_name":m.REPOSITORY},
         "status":"completed","conclusion":"success","run_attempt":1}
    jobs={"jobs":[{
        "id":i+1,"run_id":123,"name":name,"status":"completed","conclusion":"success",
        "steps":[{"name":step,"status":"completed","conclusion":"success"}
                 for step in required]
    } for i,(name,required) in enumerate(m.REQUIRED.items())]}
    artifacts={"artifacts":[{
        "name":name,"id":i+1,"size_in_bytes":1000,"expired":False,
        "digest":"sha256:"+"b"*64,"workflow_run":{"id":123}
    } for i,name in enumerate(m.ARTIFACTS)]}
    return run,jobs,artifacts

class RestMetadataScope(unittest.TestCase):
    def test_complete_synthetic_metadata_is_nonpromoting(self):
        obj=m.audited(*fixture(),SHA)
        self.assertTrue(obj["original_hosted_execution_metadata_complete"])
        self.assertFalse(obj["original_artifact_zip_bytes_independently_verified"])
        self.assertFalse(obj["prepost_input_tree_artifact_contents_verified"])
        self.assertFalse(obj["resource_cost_matched"])
        self.assertIsNone(obj["stem_winner"])
        self.assertEqual(obj["authority"],"DENY_ALL")

    def test_queued_workflow_denied(self):
        x=list(fixture());x[0]["status"]="queued";x[0]["conclusion"]=None
        with self.assertRaises(m.MissingPhysicalReceipt):m.audited(*x,SHA)

    def test_green_pr_with_skipped_physical_jobs_denied(self):
        x=list(fixture());x[0]["event"]="pull_request"
        x[1]["jobs"][2]["conclusion"]="skipped"
        with self.assertRaises(m.MissingPhysicalReceipt):m.audited(*x,SHA)

    def test_success_workflow_skipped_real_ocr_denied(self):
        x=list(fixture());y=next(v for v in x[1]["jobs"] if v["name"]=="physical-ocr-granite")
        y["conclusion"]="skipped"
        with self.assertRaises(m.MissingPhysicalReceipt):m.audited(*x,SHA)

    def test_missing_model_step_denied(self):
        x=list(fixture());x[1]["jobs"][2]["steps"]=[]
        with self.assertRaises(m.MissingPhysicalReceipt):m.audited(*x,SHA)

    def test_bypassed_prepost_ledger_denied(self):
        x=list(fixture())
        for j in x[1]["jobs"]:
            j["steps"]=[s for s in j["steps"] if "Independently recheck source tree AFTER" not in s["name"]]
        with self.assertRaises(m.MissingPhysicalReceipt):m.audited(*x,SHA)

    def test_label_reopened_before_predictions_denied(self):
        x=list(fixture())
        j=next(v for v in x[1]["jobs"] if v["name"]=="independent-five-arm-review")
        j["steps"][2],j["steps"][3]=j["steps"][3],j["steps"][2]
        with self.assertRaises(m.MissingPhysicalReceipt):m.audited(*x,SHA)

    def test_different_original_head_sha_denied(self):
        x=fixture()
        with self.assertRaises(m.MissingPhysicalReceipt):m.audited(*x,"b"*40)

    def test_wrong_source_branch_denied(self):
        x=list(fixture());x[0]["head_branch"]="main"
        with self.assertRaises(m.MissingPhysicalReceipt):m.audited(*x,SHA)

    def test_missing_independent_review_denied(self):
        x=list(fixture());x[1]["jobs"].pop()
        with self.assertRaises(m.MissingPhysicalReceipt):m.audited(*x,SHA)

    def test_duplicate_job_denied(self):
        x=list(fixture());x[1]["jobs"][0]["name"]=x[1]["jobs"][1]["name"]
        with self.assertRaises(m.MissingPhysicalReceipt):m.audited(*x,SHA)

    def test_queued_substep_denied(self):
        x=list(fixture());x[1]["jobs"][1]["steps"][0]["status"]="queued"
        with self.assertRaises(m.MissingPhysicalReceipt):m.audited(*x,SHA)

    def test_bad_run_id_denied(self):
        x=list(fixture());x[1]["jobs"][0]["run_id"]=122
        with self.assertRaises(m.MissingPhysicalReceipt):m.audited(*x,SHA)

    def test_missing_native_numeric_artifact_denied(self):
        x=list(fixture());x[2]["artifacts"]=[v for v in x[2]["artifacts"] if "native" not in v["name"]]
        with self.assertRaises(m.MissingPhysicalReceipt):m.audited(*x,SHA)

    def test_zero_size_artifact_denied(self):
        x=list(fixture());x[2]["artifacts"][0]["size_in_bytes"]=0
        with self.assertRaises(m.MissingPhysicalReceipt):m.audited(*x,SHA)

    def test_duplicated_artifact_denied(self):
        x=list(fixture());x[2]["artifacts"].append(dict(x[2]["artifacts"][0]))
        with self.assertRaises(m.MissingPhysicalReceipt):m.audited(*x,SHA)

    def test_artifact_origin_mismatch_denied(self):
        x=list(fixture());x[2]["artifacts"][0]["workflow_run"]["id"]=321
        with self.assertRaises(m.MissingPhysicalReceipt):m.audited(*x,SHA)

    def test_invalid_zip_digest_denied(self):
        x=list(fixture());x[2]["artifacts"][0]["digest"]="sha256:nope"
        with self.assertRaises(m.MissingPhysicalReceipt):m.audited(*x,SHA)

    def test_expired_artifact_denied(self):
        x=list(fixture());x[2]["artifacts"][0]["expired"]=True
        with self.assertRaises(m.MissingPhysicalReceipt):m.audited(*x,SHA)

    def test_strict_duplicate_json_fields_denied(self):
        with self.assertRaises(m.MissingPhysicalReceipt):
            m.parse(b'{"id":1,"id":2}')

    def test_strict_nonfinite_json_denied(self):
        with self.assertRaises(m.MissingPhysicalReceipt):
            m.parse(b'{"invalid":NaN}')

    def test_wrong_local_rest_source_symlink_denied(self):
        with tempfile.TemporaryDirectory() as path:
            root=Path(path)
            source=root/"rest.json"
            source.write_text('{"status":"queued"}')
            link=root/"link"
            link.symlink_to(source)
            with self.assertRaises(m.MissingPhysicalReceipt):
                m.read(link)

if __name__=="__main__":
    unittest.main()
