"""Mock-weights-only P1 real-loader contract tests; NO pretrained efficacy claims."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

import p1_real_granite_cohort as p1
import p1_real_granite_review as audit


class FakePhysicalStem:
    def __init__(self):
        self.model=torch.nn.Linear(p1.WIDTH,p1.WIDTH).eval()
        for weight in self.model.parameters(): weight.requires_grad_(False)
        self.calls=0
        self.model_load_ms=1.0
        self.device='cpu';self.revision=p1.GRANITE_REVISION
        self.model_id='NOT_REAL_GRANITE_FAKE_FOR_TESTS'

    def encode(self,row,*,allow_truncation=False):
        self.calls+=1
        seed=int(hashlib.sha256(p1.canonical(row)).hexdigest()[:12],16)
        gen=torch.Generator(device='cpu').manual_seed(seed)
        input_vector=torch.randn(p1.WIDTH,generator=gen)
        with torch.no_grad():
            x=self.model(input_vector)
            value=torch.round(x*(1<<24))/(1<<24)
        return (value.detach().clone(),
                {'research_only_feature_sha256':p1.tensor_sha(value)},
                {'original_tokens':20,'truncated':False,'encoder_forward_ms':0.1})


def fixture_original():
    parts=('train',)*128+('calibration',)*32+('test',)*64
    cases=[]
    for i,split in enumerate(parts):
        state=f'Actual data is MOCK for mechanisms, unique number {i}.'
        joint={'state':state,'question':'Which category does the news report describe?',
               'options':['world','sports']}
        root=hashlib.sha256(state.encode()).hexdigest()
        cases.append(dict(case_id=root[:24],group_id=root,split=split,
                          joint_input=joint,joint_input_digest=hashlib.sha256(p1.canonical(joint)).hexdigest(),
                          label=int(i%3==0)))
    return dict(schema='MOCK_NOT_PUBLIC',cases=cases)


def setup_fixture():
    panel=fixture_original();sha=p1.digest(panel)
    with patch.object(p1,'PANEL_SHA',sha), patch.object(audit,'PANEL_SHA',sha):
        train,blind,owner=p1.prepare_material(panel)
    return panel,train,blind,owner,sha


class RealGraniteP1Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel,cls.train,cls.blind,cls.owner,cls.sha=setup_fixture()

    def run_case(self, cells=64,mode='repeated4',cache_bytes=32*1024*1024,weight_origin='fixture'):
        with patch.object(p1,'PANEL_SHA',self.sha):
            backend=FakePhysicalStem()
            receipt=p1.run_cohort(self.train,self.blind,backend,cells=cells,
                        mode=mode,cache_bytes=cache_bytes,
                        seed=7347,weight_origin=weight_origin)
            return backend,receipt

    def audit(self,*reports,train=None,blind=None,labels=None,panel=None):
        with patch.object(audit,'PANEL_SHA',self.sha):
            return audit.review_public(panel or self.panel,train or self.train,blind or self.blind,
                                        labels or self.owner,list(reports))

    def test_frozen_bfloat16_pretrained_storage_can_be_hashed_losslessly(self):
        class TinyStem:
            pass
        stem=TinyStem()
        stem.model=torch.nn.Linear(16,4).to(dtype=torch.bfloat16).eval()
        for parameter in stem.model.parameters():
            parameter.requires_grad_(False)
        before={name:p.detach().clone() for name,p in stem.model.named_parameters()}
        got,count=p1.backend_digest(stem)
        self.assertEqual(count,68)
        manual=hashlib.sha256()
        for name,parameter in sorted(stem.model.named_parameters()):
            raw=parameter.detach().contiguous()
            data=raw.view(torch.uint8).numpy().tobytes()
            self.assertEqual(len(data),raw.numel()*raw.element_size())
            manual.update(name.encode()+b'\0')
            manual.update(data)
        self.assertEqual(got,manual.hexdigest())
        for name,p in stem.model.named_parameters():
            self.assertTrue(torch.equal(p,before[name]),name)

    def test_native_float32_storage_hash_keeps_previous_bytes(self):
        class TinyStem:
            pass
        stem=TinyStem()
        stem.model=torch.nn.Linear(16,4).eval()
        for parameter in stem.model.parameters():
            parameter.requires_grad_(False)
        got,_=p1.backend_digest(stem)
        legacy=hashlib.sha256()
        for name,parameter in sorted(stem.model.named_parameters()):
            legacy.update(name.encode()+b'\0')
            legacy.update(parameter.detach().contiguous().numpy().tobytes())
        self.assertEqual(got,legacy.hexdigest())

    def test_frozen_bfloat16_mutation_changes_physical_hash(self):
        class TinyStem:
            pass
        stem=TinyStem()
        stem.model=torch.nn.Linear(16,4).to(dtype=torch.bfloat16).eval()
        for parameter in stem.model.parameters():
            parameter.requires_grad_(False)
        before,_=p1.backend_digest(stem)
        with torch.no_grad():
            stem.model.bias[0]+=1
        after,_=p1.backend_digest(stem)
        self.assertNotEqual(before,after)

    def test_complete_fourteen_slot_physical_mock_and_independent_audit(self):
        outcomes=[]
        with patch.object(p1,'PANEL_SHA',self.sha):
            backend=FakePhysicalStem()  # One physical owned Stem for all 14 process-local arms.
            for n in p1.SIZES:
                for mode in p1.MODES:
                    outcomes.append(p1.run_cohort(self.train,self.blind,backend,
                        cells=n,mode=mode,cache_bytes=32*1024*1024,weight_origin='fixture'))
            for mode in ('repeated4','test_panel'):
                outcomes.append(p1.run_cohort(self.train,self.blind,backend,
                    cells=256,mode=mode,cache_bytes=0,weight_origin='fixture'))
        self.assertEqual(len(outcomes),14)
        self.assertEqual(self.audit(*outcomes)['studies'],14)
        self.assertEqual([r['shared']['physical_model_api_calls'] for r in outcomes],
                         [4,8,8,4,25,8,4,64,8,4,64,8,25,25])
        self.assertFalse(any(r['pretrained_weight_execution_claimed'] for r in outcomes))

    def test_mock_real_compute_then_independent_score(self):
        backend,r=self.run_case(64,'repeated4')
        self.assertEqual(r['active_cells'],8)
        self.assertEqual((r['complete_real_source_material_calls'],r['baseline']['physical_model_api_calls'],
                          r['shared']['physical_model_api_calls'],r['shared']['cache_hits']),
                         (224,8,4,4))
        self.assertEqual(backend.calls,236)
        self.assertEqual(r['head_parameter_count'],64*9744)
        self.assertTrue(r['local_cell_train']['dormant_weights_byte_identical'])
        self.assertFalse(r['pretrained_weight_execution_claimed'])
        outcome=self.audit(r)
        self.assertEqual(outcome['studies'],1)
        self.assertEqual(outcome['models']['64:repeated4:33554432']['quality']['trained']['total'],96)
        self.assertFalse(outcome['independent_pretrained_model_origin_verified'])
        self.assertFalse(outcome['production_promotion_permitted'])

    def test_no_cache_is_valid_negative_control(self):
        _,r=self.run_case(64,'repeated4',0)
        self.assertEqual(r['shared']['physical_model_api_calls'],8)
        self.assertEqual(r['shared']['cache_hits'],0)
        self.assertEqual(self.audit(r)['studies'],1)

    def test_distinct_real_test_source_uses_not_invented(self):
        _,r=self.run_case(64,'test_panel')
        self.assertEqual(r['source_group_count'],8)
        self.assertEqual(r['shared']['cache_hits'],0)
        self.assertEqual(self.audit(r)['studies'],1)

    def test_two_principals_no_cross_tenant_feature_reuse(self):
        _,r=self.run_case(64,'two_scopes')
        self.assertEqual(r['source_group_count'],4)
        self.assertEqual(r['unique_scoped_source_count'],8)
        self.assertEqual((r['shared']['physical_model_api_calls'],r['shared']['cache_hits']),(8,0))
        self.assertEqual(self.audit(r)['studies'],1)

    def test_256_physical_heads_and_negative_all_distinct(self):
        _,r=self.run_case(256,'test_panel')
        self.assertEqual(r['active_cells'],25)
        self.assertEqual(r['shared']['cache_hits'],0)
        self.assertEqual(r['head_per_cell_parameters'],9744)
        self.assertEqual(self.audit(r)['studies'],1)

    def test_pinned_pretrained_claim_must_load_large_original_revision(self):
        with self.assertRaisesRegex(ValueError,'actual pinned full Granite97'):
            self.run_case(64,'repeated4',weight_origin='pinned_public_research')

    def test_training_material_integrity_against_forged_labels(self):
        changed=copy.deepcopy(self.train)
        changed['rows'][0]['label']=1-changed['rows'][0]['label']
        changed['seal_id']=p1.digest({k:v for k,v in changed.items() if k!='seal_id'})
        with patch.object(audit,'PANEL_SHA',self.sha):
            with self.assertRaisesRegex(ValueError,'original publisher source'):
                audit.validate_original(self.panel,changed,self.blind,self.owner)

    def test_unsealed_original_source_forbidden(self):
        x=copy.deepcopy(self.blind)
        x['rows'][0]['joint_input']['state']='tampered source'
        with patch.object(p1,'PANEL_SHA',self.sha):
            with self.assertRaises(ValueError):p1.verify_material(self.train,x)
        with patch.object(audit,'PANEL_SHA',self.sha):
            with self.assertRaises(ValueError):audit.validate_original(self.panel,self.train,x,self.owner)

    def test_test_label_must_not_enter_worker_blind_material(self):
        x=copy.deepcopy(self.blind);x['rows'][0]['label']=1
        x['seal_id']=p1.digest({k:v for k,v in x.items() if k!='seal_id'})
        with patch.object(p1,'PANEL_SHA',self.sha):
            with self.assertRaisesRegex(ValueError,'label isolation'):
                p1.verify_material(self.train,x)

    def test_p1_report_false_encoder_savings_rejected(self):
        _,r=self.run_case(64,'repeated4')
        r['shared']['physical_model_api_calls']-=1
        r['report_sha256']=p1.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaises(ValueError):self.audit(r)

    def test_p1_report_false_pretrained_flag_rejected(self):
        _,r=self.run_case(64,'repeated4')
        r['pretrained_weight_execution_claimed']=True
        r['report_sha256']=p1.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'fabricated real 97M'):
            self.audit(r)

    def test_p1_report_cross_scoped_cache_claim_rejected(self):
        _,r=self.run_case(64,'two_scopes')
        r['unique_scoped_source_count']=4
        r['report_sha256']=p1.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'source diversity'):
            self.audit(r)

    def test_p1_report_false_externally_validated_quality_rejected(self):
        _,r=self.run_case(64,'repeated4')
        r['quality_superiority_established']=True
        r['report_sha256']=p1.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'unsupported'):
            self.audit(r)

    def test_independent_label_owner_fails_on_swapped_labels(self):
        _,r=self.run_case(64,'repeated4')
        labels=copy.deepcopy(self.owner)
        labels['rows'][0]['label']=1-labels['rows'][0]['label']
        labels['seal_id']=p1.digest({k:v for k,v in labels.items() if k!='seal_id'})
        with self.assertRaisesRegex(ValueError,'original publicly labeled'):
            self.audit(r,labels=labels)

    def test_missing_frozen_nochange_head_is_not_a_learning_win(self):
        _,r=self.run_case(64,'repeated4')
        r['quality_probes'].pop('no_change')
        r['report_sha256']=p1.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'matched frozen'):
            self.audit(r)

    def test_file_strict_rejects_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'original.json'
            path.write_text('{"a":1,"a":2}')
            with self.assertRaisesRegex(ValueError,'malformed'):
                audit.read_strict(path)

    def test_file_reader_does_not_accept_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'real.json';p.write_text('{"a":1}')
            (Path(tmp)/'alias.json').symlink_to(p)
            with self.assertRaises(OSError):audit.read_strict(Path(tmp)/'alias.json')

    def test_both_control_reports_must_not_alias_experiment_identity(self):
        _,r=self.run_case(64,'repeated4')
        with self.assertRaisesRegex(ValueError,'duplicate experimental'):
            self.audit(r,copy.deepcopy(r))

    def test_all_real_original_panel_sha_or_canonical_source_must_match(self):
        changed=copy.deepcopy(self.panel)
        changed['cases'][4]['joint_input']['state']='changed'
        with patch.object(audit,'PANEL_SHA',self.sha):
            with self.assertRaisesRegex(ValueError,'original 224-case'):
                audit.validate_original(changed,self.train,self.blind,self.owner)

    def test_4096_true_head_residency_and_real_test_source_reuse(self):
        _,r=self.run_case(4096,'test_panel')
        self.assertEqual(r['active_cells'],409)
        self.assertEqual(r['resident_head_tensor_bytes'],159645696)
        self.assertEqual(r['source_group_count'],64)
        self.assertEqual(r['shared']['physical_model_api_calls'],64)
        self.assertEqual(r['shared']['cache_hits'],345)
        self.assertEqual(r['matched_baseline_total_api_calls'],633)
        self.assertEqual(r['matched_shared_total_api_calls'],288)
        self.assertTrue(r['local_cell_train']['dormant_weights_byte_identical'])
        self.assertEqual(self.audit(r)['studies'],1)

    def test_4096_two_tenant_scopes_remain_independent(self):
        _,r=self.run_case(4096,'two_scopes')
        self.assertEqual(r['source_group_count'],4)
        self.assertEqual(r['unique_scoped_source_count'],8)
        self.assertEqual((r['shared']['physical_model_api_calls'],r['shared']['cache_hits']), (8,401))
        self.assertEqual(self.audit(r)['studies'],1)

    def test_report_cannot_hide_full_224_material_calls_from_cost(self):
        _,r=self.run_case(64,'repeated4')
        r['complete_actual_pretrained_api_calls']-=1
        r['report_sha256']=p1.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'unaccounted model materialization'):
            self.audit(r)

    def test_report_cannot_relabel_random_heads_as_production_generation(self):
        _,r=self.run_case(64,'repeated4')
        r['decoder_generation_executed']=True
        r['report_sha256']=p1.digest({k:v for k,v in r.items() if k!='report_sha256'})
        with self.assertRaisesRegex(ValueError,'unaccounted model materialization'):
            self.audit(r)

    def test_finite_q24_input_and_no_inference_tensor_optimization_leak(self):
        value=torch.ones(p1.WIDTH,dtype=torch.float32)/10
        with self.assertRaisesRegex(ValueError,'not exact Q24'):
            p1.q24_vector(value)
        with torch.inference_mode():
            raw=torch.ones(p1.WIDTH,dtype=torch.float32)/2
        check=p1.q24_vector(raw)
        self.assertTrue(torch.equal(check,raw))

    def test_insufficient_cache_budget_preserves_true_no_gain(self):
        _,r=self.run_case(256,'test_panel',cache_bytes=1536)
        self.assertEqual(r['shared']['physical_model_api_calls'],25)
        self.assertEqual(r['shared']['cache_hits'],0)
        self.assertEqual(self.audit(r)['studies'],1)

    def test_original_training_and_calibration_not_future(self):
        _,r=self.run_case(64,'repeated4')
        score=self.audit(r)
        self.assertTrue(score['retrospective_public_calibration_and_test'])
        self.assertEqual(score['actual_independent_observed_future_task_groups'],0)
        self.assertFalse(score['capacity_compression_10t_or_100t_established'])

if __name__=='__main__':unittest.main()
