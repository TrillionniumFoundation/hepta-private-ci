"""V24 mechanism/negative contracts only; fake Reader is NOT neural evidence."""
from __future__ import annotations
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest

import v24_lesion_source_scoped_citations as producer
import v24_lesion_citation_independent_review as audit


class FakeTokenizer:
    def encode(self,prompt):
        if type(prompt) is not str or not prompt:
            raise ValueError('bad prompt')
        return [11,12,13]
    def decode(self,ids):
        if ids==[41,2]:return 'Cited answer [E1]'
        if ids==[42,2]:return 'Cited answer [E3]'
        return 'uncited'

class FakeModel:
    def __init__(self,ids=None):self.calls=0;self.ids=ids or [41,2]
    def generate(self,ids,max_tokens):
        if max_tokens!=24 or ids!=[11,12,13]:raise ValueError('changed input')
        self.calls+=2
        return self.ids


def fixture():
    raw={'requests':{},'cases':[]}
    for i in range(32):
        fam=('conv-47','conv-48','conv-49','conv-50')[i//8]
        cid=f'{fam}/q{i%8}'
        old_prompt=f'<|im_start|>system\n{producer.ORIGINAL}<|im_end|>\nQuestion: {cid}\n[E1] source a\n[E2] source b\n'
        old_id=producer.htext(old_prompt)
        raw['requests'][old_id]={'case_id':cid,'family':fam,'arm':'lesion',
                                 'prompt':old_prompt,'source_ids':['a','b'],
                                 'question_sha256':producer.htext(cid)}
        raw['cases'].append({'id':cid})
    return {'irrelevant':'source'},{'irrelevant':'rank'},raw


class SourceScopedContracts(unittest.TestCase):
    def setUp(self):
        self.source,self.routes,self.parent=fixture()
        self.override=patch.object(producer,'validate_inputs',return_value=True)
        self.override.start()
        self.addCleanup(self.override.stop)
        self.plan=producer.build(self.source,self.routes,self.parent)
    def refuse(self,fn):
        copy=deepcopy(self.parent);fn(copy)
        with self.assertRaises(ValueError):producer.build(self.source,self.routes,copy)
    def test_exact_32_unique_proposals(self):
        self.assertEqual(len(self.plan['requests']),32)
        self.assertTrue(self.plan['original_gold_available_to_producer'] is False)
        self.assertEqual(self.plan['max_new_tokens'],24)
        self.assertTrue(all(p['prompt'].count(producer.INTERVENTION)==1 for p in self.plan['requests'].values()))
    def test_prompt_only_clause_changes(self):
        for r in self.plan['requests'].values():
            old=self.parent['requests'][r['old_request_id']]
            self.assertEqual(r['prompt'],old['prompt'].replace(producer.ORIGINAL,producer.INTERVENTION))
            self.assertEqual(r['source_ids'],old['source_ids'])
            self.assertEqual(r['question_sha256'],old['question_sha256'])
    def test_reject_missing_lesion(self):
        self.refuse(lambda x:x['requests'].pop(next(iter(x['requests']))))
    def test_reject_duplicate_case(self):
        keys=list(self.parent['requests'])
        self.refuse(lambda x:x['requests'][keys[1]].__setitem__('case_id',x['requests'][keys[0]]['case_id']))
    def test_reject_foreign_citation_arm(self):
        self.refuse(lambda x:x['requests'][next(iter(x['requests']))].__setitem__('arm','witness'))
    def test_reject_three_lesion_sources(self):
        self.refuse(lambda x:x['requests'][next(iter(x['requests']))].__setitem__('source_ids',['a','b','c']))
    def test_reject_missing_reference_clause(self):
        self.refuse(lambda x:x['requests'][next(iter(x['requests']))].__setitem__('prompt','other system'))
    def test_reject_duplicate_reference_clause(self):
        self.refuse(lambda x:x['requests'][next(iter(x['requests']))].__setitem__('prompt',producer.ORIGINAL*2))
    def test_reject_different_lesion_evidence_count(self):
        self.refuse(lambda x:x['requests'][next(iter(x['requests']))].__setitem__('source_ids',[]))
    def test_mock_executes_but_marks_nonphysical(self):
        with TemporaryDirectory() as td:
            out=Path(td)/'answers.json'
            model=FakeModel()
            result=producer.execute(self.source,self.routes,self.parent,self.plan,'unused',out,
                                    driver=model,tokenizer=FakeTokenizer())
            packet=json.loads(out.read_text())
            self.assertEqual(model.calls,64)
            self.assertEqual(result['physical_requests'],32)
            self.assertFalse(packet['true_pretrained_backend'])
            self.assertFalse(packet['production_authorized'])
            self.assertEqual(len((Path(str(out)+'.starts.jsonl')).read_text().splitlines()),32)
            with self.assertRaises(ValueError):
                producer.execute(self.source,self.routes,self.parent,self.plan,'unused',out,
                                 driver=FakeModel(),tokenizer=FakeTokenizer())
    def test_reject_incomplete_model_census(self):
        with TemporaryDirectory() as td:
            out=Path(td)/'incomplete.json'
            with self.assertRaises(ValueError):
                producer.execute(self.source,self.routes,self.parent,self.plan,'unused',out,
                                 driver=FakeModel(),tokenizer=FakeTokenizer(),limit=31)
            self.assertFalse(out.exists())
    def test_reject_mutated_frozen_plan(self):
        with TemporaryDirectory() as td:
            altered=deepcopy(self.plan);altered['production_authorized']=True
            with self.assertRaises(ValueError):
                producer.execute(self.source,self.routes,self.parent,altered,'unused',Path(td)/'r.json',
                                 driver=FakeModel(),tokenizer=FakeTokenizer())
    def test_reject_forged_source_binding(self):
        with TemporaryDirectory() as td:
            altered=deepcopy(self.plan);key=next(iter(altered['requests']));altered['requests'][key]['source_ids']=['b','a']
            with self.assertRaises(ValueError):
                producer.execute(self.source,self.routes,self.parent,altered,'unused',Path(td)/'r.json',
                                 driver=FakeModel(),tokenizer=FakeTokenizer())
    def test_reject_invalid_generated_token(self):
        for token in (-1,49152,True,4.0):
            with TemporaryDirectory() as td:
                with self.subTest(token=token),self.assertRaises(ValueError):
                    producer.execute(self.source,self.routes,self.parent,self.plan,'unused',Path(td)/'r.json',
                                     driver=FakeModel([token,2]),tokenizer=FakeTokenizer())
    def test_reject_unbounded_output(self):
        with TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                producer.execute(self.source,self.routes,self.parent,self.plan,'unused',Path(td)/'r.json',
                                 driver=FakeModel([41]*25),tokenizer=FakeTokenizer())
    def test_reject_mixed_mock_pair(self):
        with TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                producer.execute(self.source,self.routes,self.parent,self.plan,'unused',Path(td)/'r.json',
                                 driver=FakeModel())
    def test_reject_invalid_limit(self):
        with TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                producer.execute(self.source,self.routes,self.parent,self.plan,'unused',Path(td)/'r.json',
                                 driver=FakeModel(),tokenizer=FakeTokenizer(),limit=True)

class IndependentContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path(__file__).with_name('V24_ORIGINAL_LESION_CITATION_RESULT_20261016.json')
        cls.receipt=json.loads(path.read_text())
    def test_real_receipt_structure_only_not_attestation(self):
        result=audit.check_public(self.receipt)
        self.assertFalse(result['original_real_model_execution_independently_attested_by_this_check'])
    def refuse(self,fn):
        obj=deepcopy(self.receipt);fn(obj)
        with self.assertRaises(ValueError):audit.check_public(obj)
    def test_bounded_citations(self):
        self.assertEqual(audit.structural_cites('text [E1]', ['a','b']),'in_range')
        self.assertEqual(audit.structural_cites('text [E1] and [E2]', ['a','b']),'in_range')
        self.assertEqual(audit.structural_cites('text [E3]', ['a','b']),'out_of_range')
        self.assertEqual(audit.structural_cites('text with no source', ['a','b']),'absent')
    def test_reject_foreign_citation_scope(self):
        with self.assertRaises(ValueError):audit.structural_cites('text [E1]', ['a'])
    def test_reject_fake_qwen(self):self.refuse(lambda x:x.__setitem__('reference_qwen_executed',True))
    def test_reject_fake_semantics(self):self.refuse(lambda x:x.__setitem__('semantic_accuracy',1))
    def test_reject_false_human(self):self.refuse(lambda x:x.__setitem__('independent_human_review',True))
    def test_reject_production(self):self.refuse(lambda x:x.__setitem__('production_authorized',True))
    def test_reject_missing_result(self):self.refuse(lambda x:x.pop('source_scoped_structural_citations'))
    def test_reject_wrong_total(self):self.refuse(lambda x:x['source_scoped_structural_citations'].__setitem__('in_range',28))
    def test_reject_forged_transition(self):self.refuse(lambda x:x['paired_structural_transitions'].__setitem__('out_of_range->in_range',0))
    def test_reject_forged_weak_hit(self):
        self.refuse(lambda x:x['original_publisher_answer_weak_proxy']['not_literal_in_annotated_source'].__setitem__('source_scoped_literal',12))
    def test_reject_fake_future(self):self.refuse(lambda x:x.__setitem__('correlated_source_roots',32))
    def test_reject_private_text_in_public(self):self.refuse(lambda x:x.__setitem__('original_private_prompt','sensitive'))
    def test_reject_empty_receipt_sha(self):self.refuse(lambda x:x.__setitem__('output_lineage_sha256','0'))
    def test_reject_invalid_forward_type(self):self.refuse(lambda x:x.__setitem__('source_scoped_model_forwards',True))
    def test_reject_postseal_forgery(self):self.refuse(lambda x:x.__setitem__('publisher_labels_opened_postseal',False))


class RepeatContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).parent
        cls.report=json.loads((root/'V24_ORIGINAL_LESION_REPEAT_20261016.json').read_text())
        cls.original=json.loads((root/'V24_ORIGINAL_LESION_CITATION_RESULT_20261016.json').read_text())
    def test_public_repeat_non_authorizing(self):
        from v24_lesion_repeat_compare import check_public_repeat
        status=check_public_repeat(self.report)
        self.assertFalse(status['independent_physical_execution_proven_by_this_check'])
    def test_repeat_uses_distinct_cpu_observation(self):
        from v24_lesion_repeat_compare import compare
        fake=deepcopy(self.original)
        fake['private_source_scoped_answer_sha256']='a'*64
        fake['source_scoped_cpu_seconds']=fake['source_scoped_cpu_seconds']+1
        receipt=compare(self.original,fake)
        self.assertEqual(receipt['actual_model_forward_calls_per_process'],775)
        self.assertFalse(receipt['production_authorized'])
    def test_identical_timing_receipt_not_two_processes(self):
        from v24_lesion_repeat_compare import compare
        with self.assertRaises(ValueError):compare(self.original,self.original)
    def test_wrong_model_token_lineage_fails(self):
        from v24_lesion_repeat_compare import compare
        second=deepcopy(self.original)
        second['private_source_scoped_answer_sha256']='b'*64
        second['output_lineage_sha256']='c'*64
        with self.assertRaises(ValueError):compare(self.original,second)
    def test_wrong_citation_transition_fails(self):
        from v24_lesion_repeat_compare import compare
        second=deepcopy(self.original)
        second['private_source_scoped_answer_sha256']='b'*64
        second['paired_structural_transitions']['out_of_range->in_range']=2
        with self.assertRaises(ValueError):compare(self.original,second)
    def test_fake_hf_parity_fails_public(self):
        from v24_lesion_repeat_compare import check_public_repeat
        bad=deepcopy(self.report);bad['official_hf_numeric_parity_verified']=True
        with self.assertRaises(ValueError):check_public_repeat(bad)
    def test_wrong_second_run_count_fails(self):
        from v24_lesion_repeat_compare import check_public_repeat
        bad=deepcopy(self.report);bad['actual_model_forward_calls_per_process']+=1
        with self.assertRaises(ValueError):check_public_repeat(bad)
    def test_unchanged_full_receipt_fake_repeat_fails(self):
        from v24_lesion_repeat_compare import check_public_repeat
        bad=deepcopy(self.report);bad['second_private_result_sha256']=bad['first_private_result_sha256']
        with self.assertRaises(ValueError):check_public_repeat(bad)

if __name__=='__main__':unittest.main()
