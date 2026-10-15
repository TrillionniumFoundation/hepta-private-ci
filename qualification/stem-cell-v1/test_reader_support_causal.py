"""Source-only numerical and tamper tests: no pretrained task-efficacy claims."""
import copy
import hashlib
import unittest

import torch

from reader_support_causal import (PLAN, OBS, CONDITIONS, condition_texts, digest,
    run_blind, review, validate_plan)


class ToyEncoder:
    def __init__(self):
        self.calls = []

    def __call__(self, text):
        self.calls.append(text)
        value = (sum(text.encode()) % 101) / 101
        return torch.tensor([[value, 0.2, 0.3, 0.4],
                             [0.1, value, 0.4, 0.5]], dtype=torch.float32)


class ToyQuery:
    def __init__(self):
        self.calls = []

    def __call__(self, text):
        self.calls.append(text)
        return torch.tensor([0.9, 0.2, 0.3, 0.1], dtype=torch.float32)


class ToyReader(torch.nn.Module):
    def forward(self, states, query):
        evidence = (states * query).sum()
        return torch.stack((-evidence, evidence))


def fixture():
    rows = []
    for i in range(2):
        passage = f'Item {i} is RED. Item {i} is BIG. Extra evidence stays.'
        first = f'Item {i} is RED.'
        second = f'Item {i} is BIG.'
        a, b = passage.index(first), passage.index(second)
        rows.append(dict(task_id=f'task{i}',source_group=f'group{i}',
                         evidence=passage, question=f'Is item {i} red?', answer='yes',
                         support_spans=[[a,a+len(first)], [b,b+len(second)]],
                         critical_span_index=0))
    plan = dict(schema=PLAN, panel_sha256='a'*64, model_sha256='b'*64, rows=rows,
                labels_available_to_runner=False, support_independently_verified=False)
    plan['plan_id'] = digest(plan)
    return plan


def seal(plan):
    plan['plan_id'] = digest({k: v for k, v in plan.items() if k != 'plan_id'})
    return plan


class SupportCounterfactualTest(unittest.TestCase):
    def setUp(self):
        self.plan = fixture()
        self.encoder = ToyEncoder()
        self.query = ToyQuery()
        self.reader = ToyReader().eval()
        self.weights = 'c'*64

    def run_it(self, plan=None, **kwargs):
        return run_blind(plan if plan is not None else self.plan, encoder=self.encoder,
            question_encoder=self.query, reader=self.reader,
            weight_sha256=self.weights, **kwargs)

    def rejection(self, mutator):
        d = copy.deepcopy(self.plan)
        mutator(d)
        seal(d)
        with self.assertRaises(ValueError):
            validate_plan(d)

    def test_full_torch_execution_and_complete_denominator(self):
        out = self.run_it()
        self.assertEqual((out['physical_encoder_calls'], out['physical_reader_calls'],
                          out['physical_query_calls']), (8,8,2))
        self.assertEqual(len(self.encoder.calls),8)
        self.assertEqual(len(self.query.calls),2)
        self.assertFalse(out['original_prediction_replay_verified'])
        self.assertEqual(out['authority'], 'DENY_ALL')
        self.assertFalse(out['external_semantic_sufficiency_authenticated'])
        self.assertFalse(out['production_authorized'])
        for row in out['rows']:
            self.assertEqual(set(row['observations']), set(CONDITIONS))
            self.assertEqual(set(row['condition_wall_ns']),set(CONDITIONS))
            self.assertNotIn('answer', str(row))
            self.assertNotIn('RED', str(row))

    def test_exact_previous_prediction_replay(self):
        out=self.run_it()
        refs=[dict(task_id=r['task_id'], source_group=r['source_group'],
                   logits=r['observations']['ordinary_retrieval']['logits'],
                   weights_sha256=self.weights) for r in out['rows']]
        replay=self.run_it(reference_rows=refs)
        self.assertTrue(replay['original_prediction_replay_verified'])
        self.assertEqual(replay['physical_encoder_calls'],8)
        self.assertEqual([r['observations']['ordinary_retrieval']['logits'] for r in out['rows']],
                         [r['observations']['ordinary_retrieval']['logits'] for r in replay['rows']])

    def test_wrong_original_logit_fails(self):
        out=self.run_it()
        refs=[dict(task_id=r['task_id'],source_group=r['source_group'],
                   logits=r['observations']['ordinary_retrieval']['logits'][:],
                   weights_sha256=self.weights) for r in out['rows']]
        refs[0]['logits'][0] += 0.2
        with self.assertRaisesRegex(ValueError, 'cannot replay'):
            self.run_it(reference_rows=refs)

    def test_original_replay_requires_complete_same_source(self):
        out=self.run_it()
        refs=[dict(task_id=r['task_id'],source_group=r['source_group'],
                   logits=r['observations']['ordinary_retrieval']['logits'],
                   weights_sha256=self.weights) for r in out['rows']]
        refs[0]['source_group']='wrong'
        with self.assertRaises(ValueError):self.run_it(reference_rows=refs)
        with self.assertRaises(ValueError):self.run_it(reference_rows=refs[:1])

    def test_blind_plan_never_contains_human_labels(self):
        self.rejection(lambda d:d['rows'][0].update(label=1))
        self.rejection(lambda d:d.update(labels_available_to_runner=True))
        self.rejection(lambda d:d.update(support_independently_verified=True))

    def test_duplicate_task_and_source_text_conflict(self):
        self.rejection(lambda d:d['rows'][1].update(task_id='task0'))
        self.rejection(lambda d:d['rows'][1].update(source_group='group0'))

    def test_wrong_or_unsafe_span_does_not_pass(self):
        self.rejection(lambda d:d['rows'][0].update(support_spans=[[2,10],[8,13]]))
        self.rejection(lambda d:d['rows'][0].update(support_spans=[[0,100000],[14,22]]))
        self.rejection(lambda d:d['rows'][0].update(support_spans=[[0,0],[4,12]]))
        self.rejection(lambda d:d['rows'][0].update(critical_span_index=2))
        self.rejection(lambda d:d['rows'][0].update(critical_span_index=True))
        self.rejection(lambda d:d['rows'][0].update(support_spans=[[0,2]]))

    def test_cannot_reseal_wrong_source_digest_or_fake_proof(self):
        self.rejection(lambda d:d.update(panel_sha256='f'*63))
        self.rejection(lambda d:d.update(production_authorized=True))
        wrong=fixture();wrong['rows'][0]['answer']='changed'
        with self.assertRaises(ValueError):validate_plan(wrong)

    def test_runtime_refuses_invalid_feature_and_nonfinite_readout(self):
        with self.assertRaises(ValueError):
            run_blind(self.plan,encoder=lambda _:torch.ones((2,3)),
                      question_encoder=self.query,reader=self.reader,weight_sha256=self.weights)
        with self.assertRaises(ValueError):
            run_blind(self.plan,encoder=self.encoder,question_encoder=self.query,
                      reader=lambda s,q:torch.tensor([0.,float('nan')]),
                      weight_sha256=self.weights)
        with self.assertRaises(ValueError):
            run_blind(self.plan,encoder=self.encoder,question_encoder=self.query,
                      reader=ToyReader().train(),weight_sha256=self.weights)

    def test_original_and_premise_variants_are_genuinely_distinct(self):
        c=condition_texts(self.plan['rows'][0])
        self.assertNotEqual(c['ordinary_retrieval'],c['support_candidate'])
        self.assertNotEqual(c['premise_removed'],c['support_candidate'])
        self.assertEqual(c['no_evidence'],'Evidence unavailable.')

    def _scored(self):
        result=self.run_it()
        labels=dict(schema='hepta.reader.support-label-owner.v1',
                    plan_id=self.plan['plan_id'],labels={'task0':1,'task1':0})
        return result,labels

    def test_separately_opened_owner_labels_are_descriptive_only(self):
        result,labels=self._scored()
        score=review(self.plan,result,labels,expected_observation_id=result['observation_id'],
                     expected_labels_sha256=digest(labels))
        self.assertEqual(score['tasks'],2)
        self.assertEqual(score['source_groups'],2)
        self.assertTrue(score['premise_removed_has_no_valid_original_ground_truth'])
        self.assertFalse(score['support_candidate_semantic_sufficiency_independently_verified'])
        self.assertFalse(score['production_authorized'])
        self.assertNotIn('premise_removed',score['original_label_descriptive_accuracy'])
        self.assertEqual(set(score['original_label_descriptive_brier']),
                         {'no_evidence','ordinary_retrieval','support_candidate'})

    def test_scoring_rejects_relabel_and_task_drift(self):
        result,labels=self._scored()
        labels['labels'].pop('task0')
        with self.assertRaises(ValueError):
            review(self.plan,result,labels,expected_observation_id=result['observation_id'],
                   expected_labels_sha256=digest(labels))
        labels['labels']['task0']=1
        tampered=copy.deepcopy(result)
        tampered['rows'][0]['source_group']='different'
        tampered['observation_id']=digest({k:v for k,v in tampered.items() if k!='observation_id'})
        with self.assertRaises(ValueError):
            review(self.plan,tampered,labels,expected_observation_id=tampered['observation_id'],
                   expected_labels_sha256=digest(labels))

    def test_scoring_rejects_changed_probability_even_if_resealed(self):
        obs,labels=self._scored()
        changed=copy.deepcopy(obs)
        changed['rows'][0]['observations']['no_evidence']['probability']=0.999
        changed['observation_id']=digest({k:v for k,v in changed.items() if k!='observation_id'})
        with self.assertRaisesRegex(ValueError, 'altered'):
            review(self.plan,changed,labels,expected_observation_id=changed['observation_id'],
                   expected_labels_sha256=digest(labels))

    def test_scoring_rejects_changed_evidence_content_even_if_resealed(self):
        obs,labels=self._scored()
        obs['rows'][1]['observations']['premise_removed']['evidence_sha256']='0'*64
        obs['observation_id']=digest({k:v for k,v in obs.items() if k!='observation_id'})
        with self.assertRaises(ValueError):
            review(self.plan,obs,labels,expected_observation_id=obs['observation_id'],
                   expected_labels_sha256=digest(labels))

    def test_missing_condition_and_false_authority_cannot_score(self):
        obs,labels=self._scored()
        obs['rows'][0]['observations'].pop('premise_removed')
        obs['observation_id']=digest({k:v for k,v in obs.items() if k!='observation_id'})
        with self.assertRaises(ValueError):
            review(self.plan,obs,labels,expected_observation_id=obs['observation_id'],
                   expected_labels_sha256=digest(labels))
        obs,labels=self._scored()
        obs['production_authorized']=True
        obs['observation_id']=digest({k:v for k,v in obs.items() if k!='observation_id'})
        with self.assertRaises(ValueError):
            review(self.plan,obs,labels,expected_observation_id=obs['observation_id'],
                   expected_labels_sha256=digest(labels))

if __name__=='__main__': unittest.main()
