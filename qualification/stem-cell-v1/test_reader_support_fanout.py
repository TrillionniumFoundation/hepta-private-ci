"""Physical PyTorch fanout paired to a nonshared Reader, not model efficacy."""
import copy
import unittest

import torch

from reader_support_causal import digest, run_blind
from reader_support_fanout import (context_claim, checked_prior, run_shared_fanout)
from test_reader_support_causal import ToyEncoder, ToyQuery, ToyReader, fixture


class SourceAwareEncoder(ToyEncoder):
    pass


def paired():
    plan=fixture()
    # Actual two Reader questions per source group; 4 tasks, 8 logical
    # repeatable conditions per group, but source and scope remain isolated.
    rows=[]
    for old in plan['rows']:
        for j in range(2):
            item=dict(old,task_id=old['task_id']+'-q'+str(j),
                      question=old['question']+' '+str(j))
            rows.append(item)
    plan['rows']=rows
    plan['plan_id']=digest({k:v for k,v in plan.items() if k!='plan_id'})
    baseline=run_blind(plan,encoder=SourceAwareEncoder(),question_encoder=ToyQuery(),
                       reader=ToyReader().eval(),weight_sha256='c'*64,
                       reference_rows=None)
    # Independent original-only replay claim is already tested in the V2 owner;
    # instantiate exact frozen reference here by recomputing it once.
    refs=[dict(task_id=r['task_id'],source_group=r['source_group'],
               logits=r['observations']['ordinary_retrieval']['logits'],
               weights_sha256='c'*64) for r in baseline['rows']]
    baseline=run_blind(plan,encoder=SourceAwareEncoder(),question_encoder=ToyQuery(),
                       reader=ToyReader().eval(),weight_sha256='c'*64,
                       reference_rows=refs)
    return plan,baseline


def ctx(**change):
    context=context_claim(principal='research-subject',scope='research-scoped',
                  generation=9,authority_epoch=3,stem_sha256='b'*64,
                  tokenizer_sha256='e'*64,source_use_revision='source-2026')
    context.update(change)
    return context


class SharedFeatureCausalCost(unittest.TestCase):
    def setUp(self):
        self.plan,self.original=paired()
        self.encoder=SourceAwareEncoder()
        self.query=ToyQuery()
        self.reader=ToyReader().eval()
        self.checks=[]

    def callback(self,task,group,condition,key,context):
        self.checks.append((task,group,condition,key))
        return True

    def execute(self, **kw):
        args=dict(encoder=self.encoder,question_encoder=self.query,reader=self.reader,
            reader_sha256='c'*64,context=ctx(),final_use_callback=self.callback)
        args.update(kw)
        return run_shared_fanout(self.plan,self.original,**args)

    def test_real_model_math_parity_with_actual_shared_encoder_and_per_use_checks(self):
        report=self.execute()
        self.assertEqual(report['reference_uncached_encoder_calls'],16)
        self.assertEqual(report['logical_feature_borrows'],16)
        self.assertEqual(report['per_use_callback_calls'],16)
        self.assertEqual(report['physical_reader_calls'],16)
        self.assertEqual(report['physical_query_calls'],4)
        self.assertEqual(len(self.encoder.calls),report['physical_encoder_calls'])
        self.assertEqual(len(self.checks),16)
        self.assertGreater(report['cache_hits'],0)
        self.assertLess(report['physical_encoder_calls'],16)
        self.assertEqual(report['max_abs_logit_difference'],0.0)
        self.assertFalse(report['runtime_final_use_authenticated'])
        self.assertFalse(report['model_learning_improvement_verified'])
        self.assertEqual(report['authority'],'DENY_ALL')

    def test_cache_does_not_share_neutral_evidence_across_source_groups(self):
        report=self.execute()
        self.assertEqual(report['physical_encoder_calls'],8)
        self.assertEqual(report['distinct_source_bound_keys'],8)
        self.assertEqual(report['cache_hits'],8)
        neutral=[k for _,group,c,k in self.checks if c=='no_evidence']
        self.assertNotEqual(neutral[0],neutral[-1])
        self.assertEqual(len(set(neutral)),2)

    def test_zero_cache_budget_reexecutes_every_row_but_preserves_outputs(self):
        report=self.execute(max_cache_bytes=0)
        self.assertEqual(report['physical_encoder_calls'],16)
        self.assertEqual(report['cache_hits'],0)
        self.assertEqual(report['peak_cached_feature_bytes'],0)
        self.assertEqual(report['max_abs_logit_difference'],0.0)

    def test_capacity_bounded_eviction_does_not_overstate_saved_forwards(self):
        report=self.execute(max_cache_bytes=40)
        self.assertLessEqual(report['peak_cached_feature_bytes'],40)
        self.assertEqual(report['physical_encoder_calls']+report['cache_hits'],16)
        self.assertGreater(report['cache_evictions'],0)

    def test_no_host_hook_and_denied_cached_borrow_both_fail(self):
        with self.assertRaises(ValueError):self.execute(final_use_callback=None)
        self.checks=[]
        def refuse(task,group,condition,key,context):
            self.checks.append(task)
            return len(self.checks)<5
        with self.assertRaisesRegex(ValueError,'host did not admit'):
            self.execute(final_use_callback=refuse)
        self.assertEqual(len(self.checks),5)

    def test_wrong_model_scope_or_epoch_is_rejected(self):
        for other in (ctx(stem_sha256='f'*64),ctx(authority_epoch=-1),
                      ctx(principal=''),ctx(generation=True),ctx(tokenizer_sha256='X'*64)):
            with self.subTest(other=other),self.assertRaises(ValueError):
                self.execute(context=other)

    def test_scope_epoch_generation_and_tokenizer_all_separate_cache_identities(self):
        contexts=[ctx(),ctx(scope='other-scope'),ctx(authority_epoch=4),
                  ctx(generation=11),ctx(tokenizer_sha256='d'*64),
                  ctx(principal='other-person'),ctx(source_use_revision='other')]
        ids=[]
        for context in contexts:
            self.checks=[]
            self.execute(context=context)
            ids.append(self.checks[0][-1])
        self.assertEqual(len(set(ids)),len(ids))

    def test_reject_changed_observation_even_rehashed(self):
        self.original['rows'][0]['observations']['support_candidate']['logits'][0]+=0.25
        self.original['observation_id']=digest({k:v for k,v in self.original.items() if k!='observation_id'})
        with self.assertRaises(ValueError):self.execute()

    def test_reject_mutating_reader_even_when_cached(self):
        class CorruptReader(ToyReader):
            def forward(self, states, question):
                state=super().forward(states,question)
                states[0,0].add_(1)
                return state
        with self.assertRaisesRegex(ValueError,'mutated shared'):
            self.execute(reader=CorruptReader().eval())

    def test_reject_false_physical_baseline_and_mismatched_roster(self):
        self.original['physical_encoder_calls']+=1
        self.original['observation_id']=digest({k:v for k,v in self.original.items() if k!='observation_id'})
        with self.assertRaises(ValueError):self.execute()
        self.original['physical_encoder_calls']-=1
        self.original['observation_id']=digest({k:v for k,v in self.original.items() if k!='observation_id'})
        self.plan['rows'][0]['task_id']='wrong-owner'
        self.plan['plan_id']=digest({k:v for k,v in self.plan.items() if k!='plan_id'})
        with self.assertRaises(ValueError):self.execute()

    def test_all_outputs_remain_stated_non_production(self):
        report=self.execute()
        for claim in ('cache_independently_authorized', 'runtime_final_use_authenticated',
                      'real_pretrained_model_origin_authenticated',
                      'prospective_task_success_verified','model_learning_improvement_verified',
                      'full_lifecycle_cost_verified','production_authorized'):
            self.assertFalse(report[claim])
        self.assertGreater(report['measured_single_pass_wall_ns'],0)
        self.assertEqual(report['report_id'],digest({k:v for k,v in report.items() if k!='report_id'}))

if __name__=='__main__':unittest.main()
