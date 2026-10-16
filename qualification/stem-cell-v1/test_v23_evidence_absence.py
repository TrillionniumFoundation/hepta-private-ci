"""V23 deterministic evidence-absence guard contracts: mocks are NOT model results."""
from __future__ import annotations
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import v23_evidence_absence_shadow as g
import v23_evidence_absence_review as r
from v21_original_plan_rebuilder import htext,digest


class FakeTokenizer:
    def encode(self,s):
        if type(s)is not str:raise ValueError('bad prompt')
        return [4,5,6]
    def decode(self,ids):
        if ids!=[88,2]:raise ValueError('bad ids')
        return 'fake-source-only-output'


class FakeModel:
    def __init__(self):self.calls=0;self.requests=0
    def generate(self,ids,max_tokens):
        if ids!=[4,5,6] or max_tokens!=24:raise ValueError('wrong selected model prompt')
        self.calls+=2;self.requests+=1
        return [88,2]


def mock_plan():
    requests={}
    for i in range(32):
        for arm,ids in [('none',[]),('retrieved',['a','b','c']),('witness',['w','a','b']),('lesion',['a','b'])]:
            p=f'fake-question-{i} experimental-arm-{arm}'
            rid=htext(p)
            requests[rid]={'case_id':f'cohort/q{i}','family':'cohort',
                           'arm':arm,'source_ids':ids,'prompt':p,'question_sha256':htext(str(i))}
    return {'requests':requests}


def public_fixture():
    x={
        'schema':g.SCHEMA+'.digest-only-physical-review-v1',
        'original_plan_sha256':g.V16_PLAN_SHA,
        'original_model_sha256':g.READER_SHA,
        'baseline_full_requests':128,
        'baseline_real_model_forwards':2951,
        'baseline_absent_evidence_nonabstentions':32,
        'baseline_unbound_citation_rows':3,
        'baseline_24_output_token_cap_reached':99,
        'new_real_model_requests':96,
        'new_deterministic_no_evidence_abstentions':32,
        'new_real_model_forwards':2293,
        'saved_real_forward_calls_vs_full_control':658,
        'saved_original_input_tokens_vs_full_control':1936,
        'saved_original_output_tokens_vs_full_control':645,
        'new_model_input_tokens':14328,
        'new_model_output_tokens':2210,
        'all_96_original_model_outputs_identical':True,
        'total_cpu_seconds':1.0,
        'total_wall_seconds':1.0,
        'guarded_private_result_sha256':'1'*64,
        'baseline_private_result_sha256':'2'*64,
        'guard_output_lineage_sha256':'3'*64,
        'reported_pretrained_backend':True,
        'pretrained_execution_independently_signed':False,
        'semantic_correctness_human_reviewed':False,
        'reference_qwen_executed':False,
        'production_authorized':False,
        'decision':'SHADOW_DETERMINISTIC_ABSTENTION_NOT_LEARNING_HOLD_NO_GO',
    }
    return x


class GuardTests(unittest.TestCase):
    def test_no_evidence_abstains(self):
        self.assertEqual(g.guard_decision('none',[]),g.GUARD)
    def test_nonempty_evidence_preserves_model(self):
        for arm,ids in [('retrieved',['a','b','c']),('witness',['w','a','b']),('lesion',['a','b'])]:
            self.assertEqual(g.guard_decision(arm,ids),g.MODEL)
    def test_refuse_hidden_empty_evidence_model(self):
        for arm in ('retrieved','witness','lesion'):
            with self.assertRaises(ValueError):g.guard_decision(arm,[])
    def test_refuse_source_smuggling_into_none(self):
        with self.assertRaises(ValueError):g.guard_decision('none',['a'])
    def test_refuse_wrong_type_and_unknown_arm(self):
        for arm,ids in [(None,[]),('none',None),('other',[]),('retrieved',[True]),('retrieved',['']),('retrieved',[0])]:
            with self.subTest(arm=arm,ids=ids),self.assertRaises(ValueError):g.guard_decision(arm,ids)
    def test_full_32_by_4_roster(self):
        plan=mock_plan()
        with patch.object(g,'validate_inputs',return_value=True):
            self.assertEqual(g.admitted_roster({}, {}, plan),g.EXPECTED)
    def test_reject_truncated_roster(self):
        plan=mock_plan();plan['requests'].pop(next(iter(plan['requests'])))
        with patch.object(g,'validate_inputs',return_value=True),self.assertRaises(ValueError):
            g.admitted_roster({}, {}, plan)
    def test_reject_arm_evidence_geometry(self):
        for arm in ('none','retrieved','witness','lesion'):
            plan=mock_plan()
            next(v for v in plan['requests'].values() if v['arm']==arm)['source_ids']=['wrong']
            with patch.object(g,'validate_inputs',return_value=True),self.assertRaises(ValueError):
                g.admitted_roster({}, {}, plan)
    def test_complete_mock_execution_is_not_model_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'complete.json';driver=FakeModel()
            with patch.object(g,'admitted_roster',return_value=g.EXPECTED):
                x=g.execute({}, {},mock_plan(),'',p,driver=driver,tokenizer=FakeTokenizer())
            self.assertEqual((x['guard_abstentions'],x['original_model_calls']),(32,96))
            self.assertEqual(x['original_pretrained_forwards'],192)
            self.assertFalse(x['true_pretrained_backend'])
            packet=json.loads(p.read_text())
            self.assertFalse(packet['true_pretrained_backend'])
            self.assertEqual(sum(a['route']==g.GUARD for a in packet['raw_answers'].values()),32)
            self.assertEqual(sum(a['answer_text']=='unknown' for a in packet['raw_answers'].values()),32)
            self.assertEqual(len(Path(str(p)+'.decisions.jsonl').read_text().splitlines()),128)
            with self.assertRaises(ValueError),patch.object(g,'admitted_roster',return_value=g.EXPECTED):
                g.execute({}, {},mock_plan(),'',p,driver=FakeModel(),tokenizer=FakeTokenizer())
    def test_incomplete_mock_never_seals_success(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'partial.json'
            with patch.object(g,'admitted_roster',return_value=g.EXPECTED),self.assertRaises(ValueError):
                g.execute({}, {},mock_plan(),'',p,driver=FakeModel(),tokenizer=FakeTokenizer(),limit=7)
            self.assertFalse(p.exists())
            self.assertEqual(len(Path(str(p)+'.decisions.jsonl').read_text().splitlines()),7)
    def test_only_test_fixture_is_allowed_to_supply_fake_backend(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'missing.json'
            with patch.object(g,'admitted_roster',return_value=g.EXPECTED),self.assertRaises(ValueError):
                g.execute({}, {},mock_plan(),'',p,driver=FakeModel(),tokenizer=None)
            self.assertFalse(p.exists())
    def test_true_guarded_model_cost_is_not_assumed_zero(self):
        a=public_fixture();self.assertEqual(r.check_public(a)['production_authorized'],False)
        self.assertGreater(a['total_cpu_seconds'],0)
    def test_public_refuses_authority(self):
        for field in ('production_authorized','reference_qwen_executed','pretrained_execution_independently_signed',
                      'semantic_correctness_human_reviewed'):
            a=public_fixture();a[field]=True
            with self.subTest(field=field),self.assertRaises(ValueError):r.check_public(a)
    def test_public_refuses_invented_learning(self):
        for field,value in [('decision','NDU_GAIN_PROVEN'),('new_real_model_forwards',0),
                            ('all_96_original_model_outputs_identical',False),
                            ('new_real_model_requests',128),('saved_real_forward_calls_vs_full_control',1000),
                            ('baseline_absent_evidence_nonabstentions',0)]:
            a=public_fixture();a[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):r.check_public(a)
    def test_public_rejects_unrecognized_private_data(self):
        a=public_fixture();a['private_raw_outputs']='secret'
        with self.assertRaises(ValueError):r.check_public(a)
    def test_public_rejects_invalid_digest(self):
        for digest_value in ('foo','g'*64,None):
            a=public_fixture();a['guarded_private_result_sha256']=digest_value
            with self.subTest(value=digest_value),self.assertRaises(ValueError):r.check_public(a)
    def test_public_rejects_bad_costs(self):
        for val in (True,-1,float('nan'),0,float('inf'),10000):
            a=public_fixture();a['total_cpu_seconds']=val
            with self.subTest(value=val),self.assertRaises(ValueError):r.check_public(a)
    def test_same_dummy_output_can_never_qualify_as_pretrained(self):
        a=public_fixture();a['reported_pretrained_backend']=False
        with self.assertRaises(ValueError):r.check_public(a)
    def test_python_optimization_does_not_disable_assertion_checks(self):
        # The actual implementation uses explicit raise ValueError, not assert.
        with self.assertRaises(ValueError):g.guard_decision('none',['not-empty'])


if __name__=='__main__':unittest.main()
