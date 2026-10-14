"""Synthetic numeric doubles only; no real weights, new future, or promotions."""
import copy
import hashlib
import unittest
from unittest.mock import patch
from contextlib import contextmanager
import historical_head_anchor as anchor
import cell_learning

import numpy as np
from agnews_paired_shadow import compare, run_gemma, run_laya
import public_agnews_confirmatory as confirm
from paired_confirmatory_audit import AuditError, verify
from public_agnews_panel import canonical, sha
from test_public_agnews_confirmatory import inputs
from embeddinggemma2_shadow import rust_feature_digest_q24


# Deterministic numeric training stand-in; intentionally not a pretrained model.
class FakeHead:
    def __init__(self, seed=17):
        self.w=np.zeros(256,dtype=float)
        self.w[:2]=[0.002,-0.003]
    def clone_frozen(self):
        import copy
        return copy.deepcopy(self)
    def learn(self,x,y,lr):
        self.w += lr*(x.T @ (y-0.5))/len(y)
        return float(np.linalg.norm(self.w))
    def predict(self,x):
        return np.asarray(x) @ self.w
    def parameter_count(self):return 2018
    def export_q24(self):return {"w": [int(round(t*2**24)) for t in self.w.tolist()]}


@contextmanager
def stub_head():
    with patch.multiple(cell_learning,
        budgeted_cell=lambda *a,**k: FakeHead(),
        rust_candidate_digest=lambda weights:sha(canonical(weights))), \
         patch.object(anchor,"check_values",return_value={
             "reference_local_tensor_lineage_matched":False,
             "executed_reference_run":0,
         }):
        yield


class FakeStem:
    _verified_local_weights=True  # deliberate fixture: not a true model
    manifest={"dimension":256,"profile":"text",
              "revision":"914f7f89142e33e77833254d9c9b90c3cef7303b"}
    profile_digest="6"*64
    def __init__(self): self.model_encode_calls=0
    def encode_cells(self,batch):
        self.model_encode_calls+=1
        rows=[]
        for req in batch:
            basis=hashlib.sha256(req["input"]["value"].encode()).digest()
            values=[(basis[i%32]-128)*25000 for i in range(256)]
            rows.append({**{k:req[k] for k in (
                "cell_id","scope_id","principal_id","purpose_id","generation","authority_epoch")},
                "input_digest":req["input"]["sha256"],
                "pipeline_digest":self.profile_digest,
                "features_q24":values,"feature_digest":rust_feature_digest_q24(values),
                "authority":"DENY_ALL", "modality":"text",
                "role":"classification", "requires_new_neuron_profile":False})
        return {"physical_local_model_execution":True,
                "evidence_type":"local_weight_execution_unverified_origin",
                "production_promotion":"DENY_ALL", "feature_dimension":256,
                "cell_requests":len(batch), "rows":rows}


class FakeLaya:
    def system_one(self,state,questions):
        assert questions['category']['criteria']['sports']
        return {"answers":{"category":{"probabilities":{"world":.4,"sports":.6}}}}


def study():
    old,new=inputs()
    with patch.object(confirm,"SOURCE_PANEL_SHA256",sha(canonical(old))):
        fresh=confirm.create_panel(old,new)
        src={"schema":"hepta.stem.agnews-input-receipt.v1",
             "panel_digest":sha(canonical(old)),
             "source_sha256":old["dataset_file_sha256"],
             "counts_by_split_label":{f"{sp}/{label}":sum(c["split"]==sp and c["label"]==label
                for c in old["cases"]) for sp in ("train","calibration","test") for label in (0,1)},
             "future_longitudinal_evidence":False,"physical_model_weights_executed":False,
             "external_source_signer_authenticated":False,"production_promotion":"DENY_ALL"}
        with stub_head():
            gemma,extra_gemma=run_gemma(old,FakeStem(),confirmatory=fresh)
        laya,extra_laya=run_laya(old,FakeLaya(),revision="55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851",
                                 confirmatory=fresh)
        laya["metadata"]["model_parameter_count"]=421293827
        comp=compare(old,[*gemma,laya])
        values=(old,src,gemma,laya,comp,fresh,extra_gemma,extra_laya,new)
        with patch.object(anchor,"check_reports",return_value={
                "reference_local_tensor_lineage_matched":False,
                "executed_reference_run":0,
                }):
            report=verify(*values)
    return values,report


class ConfirmatoryAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.example,cls.report=study()

    def test_fake_executor_qualifies_only_contracts_not_model_gain(self):
        result=self.report
        self.assertEqual(result["extra_panel_rows"],128)
        self.assertEqual(result["production_promotion"],"DENY_ALL")
        self.assertEqual(len(result["metrics"]),4)
        self.assertTrue(result["source_case_selection_recomputed_from_full_val2_parquet"])
        self.assertFalse(result["new_window_is_chronologically_future"])
        self.assertFalse(result["foundation_pretraining_contamination_excluded"])
        self.assertFalse(result["model_forward_origin_independently_authenticated"])
        for arm in result["metrics"]:
            self.assertEqual(result["metrics"][arm]["cases"],128)
        self.assertEqual(result["fixed_logit_multiplier_from_prior_exploration"],1024)

    def test_separate_source_input_tamper_or_model_alias_rejected(self):
        for kind in ("source_change","source_label","duplicate","fake_future","bad_model","fake_scale","old_head"):
            v=copy.deepcopy(self.example)
            if kind=="source_change": v[8][0]["text"]="modified raw label source"
            elif kind=="source_label": v[8][0]["label"]=1-v[8][0]["label"]
            elif kind=="duplicate": v[6][0]["rows"][1]=copy.deepcopy(v[6][0]["rows"][0])
            elif kind=="fake_future":v[7]["cross_sectional_new_source_not_temporal_future"]=False
            elif kind=="bad_model":v[6][2]["metadata"]["revision"]="a"*40
            elif kind=="fake_scale":v[6][2]["rows"][0]["prob_sports"]+=.01
            elif kind=="old_head":v[6][2]["metadata"]["trained_head_digest"]="f"*64
            with patch.object(confirm,"SOURCE_PANEL_SHA256",sha(canonical(v[0]))):
                with self.subTest(kind=kind), \
                     patch.object(anchor,"check_reports",return_value={
                         "reference_local_tensor_lineage_matched":False,
                         "executed_reference_run":0,
                     }), \
                     self.assertRaises((AuditError,confirm.ConfirmatoryError)):
                    verify(*v)

    def test_new_labels_never_enter_head_training(self):
        original,new=self.example[0],self.example[8]
        with patch.object(confirm,"SOURCE_PANEL_SHA256",sha(canonical(original))):
            fresh1=confirm.create_panel(original,new)
            altered=copy.deepcopy(new)
            for item in altered:
                item["label"]=1-item["label"]
            fresh2=confirm.create_panel(original,altered)
            with stub_head():
                first_old,first_extra=run_gemma(original,FakeStem(),confirmatory=fresh1)
                second_old,second_extra=run_gemma(original,FakeStem(),confirmatory=fresh2)
            self.assertEqual(first_old[1]["metadata"]["head_artifact_digest"],
                             second_old[1]["metadata"]["head_artifact_digest"])
            scores1={c["source_digest"]:c["prob_sports"] for c in first_extra[1]["rows"]}
            scores2={c["source_digest"]:c["prob_sports"] for c in second_extra[1]["rows"]}
            self.assertEqual(scores1,scores2)


if __name__=="__main__":unittest.main()
