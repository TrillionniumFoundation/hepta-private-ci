"""Strict retrospective route/custody tests; fake source and fake model receipts.

These source-only tests never load pretrained material or read publisher gold.
"""
from __future__ import annotations

import copy
import math
import unittest
from unittest.mock import patch

import selective_route_v8 as producer
import independent_selective_review_v8 as reviewer


def fixture():
    cases=[{'case_id':f'heldout:{i:064x}', 'source_sha256':f'{i:064x}',
            'text':f'fake test {i}'} for i in range(32)]
    fit=[{'case_id':f'fit:{i:064x}', 'label':i % 4} for i in range(64)]
    source={'cohort':'hard-charge-four-intents-v3',
            'source_plan_sha256':producer.SOURCE_SHA,
            'heldout_labels_excluded':True,'heldout':cases,'train':fit}
    model={}
    for arm in producer.CANDIDATES:
        p=[.04,.01,.92,.03]
        model[arm]={'rows':[{'case_id':r['case_id'], 'source_sha256':r['source_sha256'],
                             'scores': {'learned':p[:],'frozen_init':[.25]*4,
                                        'centroid':[.25]*4}} for r in cases]}
    cheap={'schema':'hepta.stem.hard-charge.lexical-control.v4',
           'source_plan_sha256':producer.SOURCE_SHA,'authority':'DENY_ALL',
           'production_authorized':False,'future_windows':0,
           'cost':{'neural_encoder_forward_count':0},'rows':[]}
    for i,row in enumerate(cases):
        # Exactly 8 cases have smaller margins; neither source nor producer has gold.
        p=[.26,.25,.25,.24] if i<8 else [.8,.10,.05,.05]
        cheap['rows'].append({'case_id':row['case_id'],'source_sha256':row['source_sha256'],
                              'scores': {producer.CHEAP_ARM:p[:],
                                         'word_12_tfidf_centroid':p[:]}})
    return source,model,cheap


class SelectiveV8Tests(unittest.TestCase):
    def setUp(self):
        self.source,self.models,self.cheap=fixture()

    def produce(self):
        with patch.object(producer.v5,'original_nogold',return_value={}),\
             patch.object(reviewer.v5,'original_nogold',return_value={}):
            route=producer.produce(self.source,copy.deepcopy(self.source),self.models,self.cheap)
            reviewer.audit_prelabel(self.source,self.models,self.cheap,route)
        return route

    def audited(self,r):
        with patch.object(reviewer.v5,'original_nogold',return_value={}):
            return reviewer.audit_prelabel(self.source,self.models,self.cheap,r)

    def test_one_exact_unlabelled_eight_case_route_replays_independently(self):
        doc=self.produce()
        self.assertEqual(len(doc['selected_case_ids']),8)
        self.assertEqual(doc['selected_case_ids'],
                         [f'heldout:{i:064x}' for i in range(8)])
        self.assertEqual(doc['evidence']['actual_new_encoder_sequence_forwards'],0)
        self.assertFalse(doc['evidence']['measured_heldout_encoder_savings'])
        self.assertEqual(doc['authority'],'DENY_ALL')
        self.assertFalse(doc['production_authorized'])

    def test_priority_is_pinned_to_full_case_id_tie_break(self):
        scores={f'heldout:{i:064x}':[.26,.25,.25,.24] for i in reversed(range(32))}
        expected=[f'heldout:{i:064x}' for i in range(8)]
        self.assertEqual(producer.select_unlabelled(scores),expected)
        self.assertEqual(reviewer.reference_route(self.source,self.cheap)[0],expected)

    def test_no_target_and_no_heldout_order_leak(self):
        route=self.produce()
        self.assertTrue(all(set(row)=={'case_id','source_sha256',
                         'selected_for_hypothetical_escalation','scores'} for row in route['rows']))
        modified=copy.deepcopy(self.source)
        modified['heldout'][0]['label']=1
        with patch.object(producer.v5,'original_nogold',return_value={}):
            # The original verified cohort digest/source owner rejects this in V5;
            # local V8 must independently reject accidental label-bearing input.
            with self.assertRaises(ValueError):
                producer.produce(modified,self.source,self.models,self.cheap)

    def test_swapped_model_scores_and_missing_cases_fail(self):
        for change in (lambda c:c['granite47']['rows'].pop(),
                       lambda c:c['granite97']['rows'][0]['scores'].__setitem__('label',2),
                       lambda c:c['mmbert140']['rows'][0].__setitem__('source_sha256','wrong')):
            model=copy.deepcopy(self.models)
            change(model)
            with patch.object(producer.v5,'original_nogold',return_value={}):
                with self.assertRaises(ValueError):
                    producer.produce(self.source,self.source,model,self.cheap)

    def test_reviewer_rejects_forged_savings_and_authority(self):
        for mutate in (lambda x:x['evidence'].__setitem__('measured_heldout_encoder_savings',True),
                       lambda x:x['evidence'].__setitem__('actual_new_encoder_sequence_forwards',8),
                       lambda x:x.__setitem__('stem_winner_verified',True),
                       lambda x:x.__setitem__('production_authorized',True),
                       lambda x:x.__setitem__('future_windows',1),
                       lambda x:x.__setitem__('selected_case_ids',x['selected_case_ids'][:7])):
            result=copy.deepcopy(self.produce());mutate(result)
            with self.assertRaises(ValueError):
                self.audited(result)

    def test_reviewer_rejects_case_and_score_tamper(self):
        for mutate in (lambda x:x['rows'][0]['scores']['granite47'].__setitem__(1,.9),
                       lambda x:x['rows'][0].__setitem__('label',0),
                       lambda x:x['rows'].pop(),
                       lambda x:x['rows'][8].__setitem__('selected_for_hypothetical_escalation',True)):
            result=copy.deepcopy(self.produce());mutate(result)
            with self.assertRaises(ValueError):
                self.audited(result)

    def test_reviewer_rejects_nonfinite_cheap_probabilities(self):
        cheap=copy.deepcopy(self.cheap)
        cheap['rows'][0]['scores'][producer.CHEAP_ARM][2]=float('nan')
        with patch.object(producer.v5,'original_nogold',return_value={}):
            with self.assertRaises(ValueError):
                producer.produce(self.source,self.source,self.models,cheap)

    def test_pairstat_correctness(self):
        gold={f'heldout:{i:064x}':i%4 for i in range(32)}
        full={key:[float(j==value) for j in range(4)] for key,value in gold.items()}
        cheap={key:list(full[key]) for key in gold}
        for i in range(4):
            key=f'heldout:{i:064x}'
            cheap[key]=[float(j!=gold[key] and j==(gold[key]+1)%4) for j in range(4)]
        outcome=reviewer._paired(full,cheap,gold)
        self.assertEqual(outcome['candidate_only'],4)
        self.assertEqual(outcome['comparator_only'],0)
        self.assertEqual(outcome['candidate_correct'],32)
        self.assertEqual(outcome['comparator_correct'],28)


if __name__=='__main__':
    unittest.main()
