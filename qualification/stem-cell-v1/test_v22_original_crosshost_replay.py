"""Deterministic synthetic denial tests; NEVER counts as 135M pretrained work."""
from __future__ import annotations
import copy
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import v22_original_crosshost_execute as e
import v22_original_crosshost_review as v
from v21_original_plan_rebuilder import digest,htext,canonical

class FakeToken:
    def encode(self,prompt): return [ord(x) for x in prompt]
    def decode(self,ids): return 'Paris' if ids==[44,2] else 'unreviewed'

class FakeModel:
    calls=0
    def generate(self,ids,max_tokens):
        self.calls+=2
        return [44,2]


def fixture():
    source={'family_order':list(('conv-47','conv-48','conv-49','conv-50')),'families':{f:{'passages':[{'id':'p','text':'Paris'}]} for f in ('conv-47','conv-48','conv-49','conv-50')}}
    routes={'rows':[]};requests={};cases=[]; gold=[]
    for fam in ('conv-47','conv-48','conv-49','conv-50'):
        qa=[]
        for i in range(8):
            qa.append({'answer': 'Paris' if i < 4 or i>4 else None})
            cid=f'{fam}/q{i}'
            arms={}
            for arm in ('none','retrieved','witness','lesion'):
                prompt=f'Input-{cid}-{arm}'
                rid=htext(prompt)
                requests[rid]={'case_id':cid,'family':fam,'arm':arm,
                         'prompt':prompt,'source_ids':['p'],'question_sha256':htext('Q')}
                arms[arm]={'request_id':rid,'evidence_ids':['p']}
            cases.append({'id':cid,'family':fam,
                  'cohort':v.GROUPS[0] if i<4 else v.GROUPS[1],
                  'witness_id':'p','arms':arms})
        gold.append({'sample_id':fam,'qa':qa})
    gold.extend({'sample_id':f'extra-{i}','qa':[]} for i in range(6))
    plan={'source_sha256':digest(source),'bm25_routes_sha256':digest(routes),
          'reader_sha256':e.READER_SHA,'tokenizer_sha256':e.TOKEN_SHA,
          'reader_config_sha256':e.READER_CFG_SHA,
          'answer_dependent_historical_selection':True,
          'label_text_entered_model_prompts':False,'production_authorized':False,
          'frozen_arms':['none','retrieved','witness','lesion'],
          'requests':requests,'cases':cases}
    return source,routes,plan,gold


class V22MockOnly(unittest.TestCase):
    def setUp(self):
        self.source,self.routes,self.plan,self.gold=fixture()
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.plan_sha=digest(self.plan)
        self.checks=ExitStack();self.addCleanup(self.checks.close)
        for owner,field,value in ((e,'SOURCE_SHA',digest(self.source)),
                                  (e,'PRIVATE_ROUTE_SHA',digest(self.routes)),
                                  (e,'V16_PLAN_SHA',self.plan_sha),
                                  (v,'V16_PLAN_SHA',self.plan_sha)):
            self.checks.enter_context(patch.object(owner,field,value))
        self.checks.enter_context(patch.object(e,'source_routes',lambda _:self.routes))
    def output(self):
        return self.root/'model-answers.json'
    def execute_mock(self,**kwargs):
        return e.replay(self.source,self.routes,self.plan, None, self.output(),
                        driver=kwargs.get('driver',FakeModel()),
                        tokenizer=kwargs.get('tokenizer',FakeToken()),
                        limit=kwargs.get('limit'))
    def full(self):
        self.execute_mock()
        raw=e.read_private(self.output())
        lines=v.strict_start_lines(str(self.output())+'.starts.jsonl')
        return raw,lines
    def test_128_actual_api_invocations_with_fake_model_are_not_claimed_as_pretrained(self):
        data=self.execute_mock()
        self.assertEqual(data['requests'],128)
        self.assertFalse(data['stronger_reference_reader_executed'])
        self.assertEqual(data['real_model_forward_calls'],256)
        self.assertEqual(self.output().stat().st_mode & 0o777,0o600)
        self.assertEqual(Path(str(self.output())+'.starts.jsonl').stat().st_mode & 0o777,0o600)
    def test_correct_complete_separate_review(self):
        raw,starts=self.full()
        a=v.verify_raw(self.plan,raw,starts,FakeToken())
        self.assertEqual(a['verified_original_requests'],128)
        self.assertEqual(a['physical_forward_calls'],256)
        self.assertIsNone(a['independent_semantic_correctness'])
    def test_no_postseal_overwrite(self):
        self.execute_mock()
        with self.assertRaises(ValueError):self.execute_mock()
    def test_incomplete_probe_must_not_seal(self):
        with self.assertRaises(ValueError):self.execute_mock(limit=1)
        self.assertFalse(self.output().exists())
        self.assertTrue(Path(str(self.output())+'.starts.jsonl').exists())
    def test_missing_original_request_denied(self):
        self.plan['requests'].pop(next(iter(self.plan['requests'])))
        with self.assertRaises(ValueError):self.execute_mock()
    def test_unverified_model_identity_denied(self):
        self.plan['reader_sha256']='0'*64
        with self.assertRaises(ValueError):self.execute_mock()
    def test_unauthorized_production_denied(self):
        self.plan['production_authorized']=True
        with self.assertRaises(ValueError):self.execute_mock()
    def test_rank_substitution_denied(self):
        self.routes['rows'].append({'forged':True})
        with self.assertRaises(ValueError):self.execute_mock()
    def test_malformed_model_token_denied(self):
        class BadModel(FakeModel):
            def generate(self,ids,max_tokens):return [True]
        with self.assertRaises(ValueError):self.execute_mock(driver=BadModel())
        self.assertFalse(self.output().exists())
    def test_cross_scope_input_rejected(self):
        self.source['families']['conv-47']['passages'][0]['text']='Modified'
        with self.assertRaises(ValueError):self.execute_mock()
    def test_wrong_evidence_output_rejected(self):
        raw,starts=self.full()
        rid=next(iter(raw['raw_answers']))
        raw['raw_answers'][rid]['source_ids']=['foreign']
        with self.assertRaises(ValueError):v.verify_raw(self.plan,raw,starts,FakeToken())
    def test_one_missing_output_rejected(self):
        raw,starts=self.full()
        raw['raw_answers'].pop(next(iter(raw['raw_answers'])))
        with self.assertRaises(ValueError):v.verify_raw(self.plan,raw,starts,FakeToken())
    def test_fake_forward_total_rejected(self):
        raw,starts=self.full();raw['model_forwards']+=1
        with self.assertRaises(ValueError):v.verify_raw(self.plan,raw,starts,FakeToken())
    def test_fake_reference_or_human_flag_rejected(self):
        raw,starts=self.full()
        for field,val in (('stronger_reference_reader_executed',True),
                          ('human_verified_sufficiency',True),
                          ('independent_semantic_correctness',1.0)):
            changed=copy.deepcopy(raw);changed[field]=val
            with self.subTest(field=field),self.assertRaises(ValueError):
                v.verify_raw(self.plan,changed,starts,FakeToken())
    def test_changed_tokens_or_start_rejected(self):
        raw,starts=self.full()
        changed=copy.deepcopy(starts);changed[0]['input_ids_sha256']='0'*64
        with self.assertRaises(ValueError):v.verify_raw(self.plan,raw,changed,FakeToken())
        out=copy.deepcopy(raw)
        out['raw_answers'][next(iter(out['raw_answers']))]['token_ids']=[-1,2]
        with self.assertRaises(ValueError):v.verify_raw(self.plan,out,starts,FakeToken())
    def test_duplicate_starts_rejected(self):
        raw,starts=self.full();starts[-1]=starts[0]
        with self.assertRaises(ValueError):v.verify_raw(self.plan,raw,starts,FakeToken())
    def test_gold_unknown_not_failure_and_no_semantics_claim(self):
        raw,_=self.full()
        result=v.weak_label_review(self.plan,raw,self.gold)
        for arm in ('none','retrieved','witness','lesion'):
            cnt=result['per_cohort_arm'][v.GROUPS[1]][arm]
            self.assertEqual((cnt['cases'],cnt['known'],cnt['unknown']), (16,12,4))
        self.assertFalse(result['human_evidence_sufficiency_verified'])
        self.assertFalse(result['historical_v16_weak_counts_match_current_host'])
    def test_gold_nonstrings_rejected(self):
        raw,_=self.full();self.gold[0]['qa'][0]['answer']=True
        with self.assertRaises(ValueError):v.weak_label_review(self.plan,raw,self.gold)
    def _toy_sanitized_receipt(self):
        counts={}
        for cohort in v.GROUPS:
            known=16 if cohort==v.GROUPS[0] else 11
            counts[cohort]={a:{'cases':16,'known':known,'unknown':16-known,
                               'substring':v.ORIGINAL_STATS[cohort][a], 'exact':0} for a in v.ARMS}
        return {'schema':v.LABELS,'original_plan_sha256':self.plan_sha,
                'verified_original_requests':128,'physical_forward_calls':2951,
                'input_tokens':16264,'output_tokens':2855,
                'actual_answer_token_lineage_sha256':'a'*64,
                'private_original_result_sha256':'b'*64,
                'model_operator_hf_parity_verified':False,
                'independent_semantic_correctness':None,
                'stronger_reference_reader_executed':False,
                'production_authorized':False,'per_cohort_arm':counts,
                'per_correlated_root_case_counts':{f:8 for f in v.HELD},
                'historical_v16_weak_substring_counts':v.ORIGINAL_STATS,
                'historical_v16_weak_counts_match_current_host':True,
                'historical_cohort_selection_answer_dependent':True,
                'historical_unique_source_roots':4,'future_windows':0,
                'human_evidence_sufficiency_verified':False,
                'gold_opened_only_after_model_result':True,
                'model_is_frozen_original_135m':True,
                'reference_qwen_128_calls':0,
                'decision':'PHYSICAL_135M_REPLAY_ONLY_HOLD_NO_GO'}
    def test_public_report_rejects_fake_qwen_and_semantic_gain(self):
        receipt=self._toy_sanitized_receipt()
        self.assertFalse(v.verify_public_receipt(receipt)['production_authorized'])
        for field,value in (('reference_qwen_128_calls',128),('production_authorized',True),
                            ('independent_semantic_correctness',0.9),
                            ('historical_unique_source_roots',32),
                            ('physical_forward_calls',2952)):
            changed=copy.deepcopy(receipt);changed[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                v.verify_public_receipt(changed)
    def test_public_source_only_never_grants_attestation(self):
        r=v.verify_public_receipt(self._toy_sanitized_receipt())
        self.assertFalse(r['original_model_forward_independently_attested_by_this_check'])
        self.assertFalse(r['qwen_reference_executed'])
    def test_public_receipt_duplicate_or_noninteger_counts_denied(self):
        r=self._toy_sanitized_receipt()
        r['per_cohort_arm'][v.GROUPS[0]]['witness']['known']=True
        with self.assertRaises(ValueError):v.verify_public_receipt(r)
    def test_second_process_exact_output_parity_even_with_different_clocks(self):
        from v22_original_repeat_compare import compare
        raw,starts=self.full()
        other=copy.deepcopy(raw)
        other['execution_cpu_seconds']+=2
        other['execution_wall_seconds']+=5
        for row in other['raw_answers'].values():row['cpu_seconds']+=0.01
        result=compare(self.plan,raw,starts,other,starts,FakeToken())
        self.assertTrue(result['byte_identical_original_responses'])
        self.assertEqual(result['total_physical_model_forwards'],512)
        self.assertFalse(result['production_authorized'])
        rid=next(iter(other['raw_answers']))
        other['raw_answers'][rid]['answer_text']='different'
        with self.assertRaises(ValueError):compare(self.plan,raw,starts,other,starts,FakeToken())
    def test_second_process_missing_start_rejected(self):
        from v22_original_repeat_compare import compare
        raw,starts=self.full()
        with self.assertRaises(ValueError):compare(self.plan,raw,starts,raw,starts[:-1],FakeToken())
    def test_private_duplicate_json_denied(self):
        bad=self.root/'dup.json';bad.write_text('{"a":1,"a":2}')
        with self.assertRaises(ValueError):e.read_private(bad)
    def test_symlink_rejected(self):
        safe=self.root/'safe.json';safe.write_text('{"a":1}')
        link=self.root/'link.json';link.symlink_to(safe)
        with self.assertRaises(ValueError):e.read_private(link)
    def test_cannot_infer_replicated_historical_accuracy_from_mock(self):
        raw,_=self.full()
        report=v.weak_label_review(self.plan,raw,self.gold)
        self.assertEqual(report['historical_unique_source_roots'],4)
        self.assertEqual(report['future_windows'],0)
        self.assertIsNone(report['independent_semantic_correctness'])

if __name__=='__main__':unittest.main()
