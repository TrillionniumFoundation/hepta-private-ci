"""Source-only numerical and tamper tests: no pretrained task-efficacy claims."""
import copy
import hashlib
import unittest

import torch

from reader_support_causal import (PLAN, OBS, REPLAY, CONDITIONS, condition_texts, digest,
    run_blind, replay_physical, review, validate_plan)


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
        first=self.run_it()
        self.refs=[dict(task_id=r['task_id'],source_group=r['source_group'],
                   logits=r['observations']['ordinary_retrieval']['logits'],
                   weights_sha256=self.weights) for r in first['rows']]
        result=self.run_it(reference_rows=self.refs)
        self.physical_replay=replay_physical(self.plan,result,encoder=self.encoder,
            question_encoder=self.query,reader=self.reader,
            expected_reader_weights_sha256=self.weights)
        labels=dict(schema='hepta.reader.support-label-owner.v1',
                    plan_id=self.plan['plan_id'],labels={'task0':1,'task1':0})
        return result,labels

    def reviewed(self, obs, labels, *, references=None, weight_id=None):
        return review(self.plan,obs,labels,expected_observation_id=obs['observation_id'],
                 expected_labels_sha256=digest(labels),
                 original_reference_rows=self.refs if references is None else references,
                 expected_reader_weights_sha256=self.weights if weight_id is None else weight_id,
                 physical_replay_receipt=self.physical_replay)

    @staticmethod
    def reseal(obs):
        obs['observation_id'] = digest({k:v for k,v in obs.items() if k!='observation_id'})

    def test_separately_opened_owner_labels_are_descriptive_only(self):
        result,labels=self._scored()
        score=self.reviewed(result,labels)
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
            self.reviewed(result,labels)
        labels['labels']['task0']=1
        tampered=copy.deepcopy(result)
        tampered['rows'][0]['source_group']='different'
        tampered['observation_id']=digest({k:v for k,v in tampered.items() if k!='observation_id'})
        with self.assertRaises(ValueError):
            self.reviewed(tampered,labels)

    def test_scoring_rejects_changed_probability_even_if_resealed(self):
        obs,labels=self._scored()
        changed=copy.deepcopy(obs)
        changed['rows'][0]['observations']['no_evidence']['probability']=0.999
        changed['observation_id']=digest({k:v for k,v in changed.items() if k!='observation_id'})
        self.physical_replay['observation_id']=changed['observation_id']
        self.physical_replay['replay_id']=digest({k:v for k,v in self.physical_replay.items() if k!='replay_id'})
        with self.assertRaisesRegex(ValueError, 'altered'):
            self.reviewed(changed,labels)

    def test_scoring_rejects_changed_evidence_content_even_if_resealed(self):
        obs,labels=self._scored()
        obs['rows'][1]['observations']['premise_removed']['evidence_sha256']='0'*64
        obs['observation_id']=digest({k:v for k,v in obs.items() if k!='observation_id'})
        with self.assertRaises(ValueError):
            self.reviewed(obs,labels)

    def test_missing_condition_and_false_authority_cannot_score(self):
        obs,labels=self._scored()
        obs['rows'][0]['observations'].pop('premise_removed')
        obs['observation_id']=digest({k:v for k,v in obs.items() if k!='observation_id'})
        with self.assertRaises(ValueError):
            self.reviewed(obs,labels)
        obs,labels=self._scored()
        obs['production_authorized']=True
        obs['observation_id']=digest({k:v for k,v in obs.items() if k!='observation_id'})
        with self.assertRaises(ValueError):
            self.reviewed(obs,labels)

    def test_reviewer_requires_producer_original_replay(self):
        obs,labels=self._scored()
        obs['original_prediction_replay_verified']=False
        self.reseal(obs)
        with self.assertRaisesRegex(ValueError,'provenance'):
            self.reviewed(obs,labels)

    def test_reviewer_reloads_independent_original_not_claimed_replay(self):
        obs,labels=self._scored()
        fake=copy.deepcopy(self.refs)
        fake[0]['logits'][0] += 0.1
        with self.assertRaisesRegex(ValueError,'prediction differs'):
            self.reviewed(obs,labels,references=fake)
        fake=copy.deepcopy(self.refs)
        fake[0]['task_id']='other'
        with self.assertRaisesRegex(ValueError,'task inventory'):
            self.reviewed(obs,labels,references=fake)

    def test_reviewer_rejects_wrong_model_and_reader_id_even_if_resealed(self):
        for field,value in [('model_sha256','d'*64),('panel_sha256','e'*64),
                            ('reader_weights_sha256','f'*64)]:
            obs,labels=self._scored()
            obs[field]=value
            self.reseal(obs)
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.reviewed(obs,labels)

    def test_reviewer_rejects_false_claimed_authority_and_labels(self):
        for field,value in [('reading_labels',True),('independent_real_source_authenticated',True),
                            ('external_semantic_sufficiency_authenticated',True),
                            ('measured_complete_model_lifecycle',True),
                            ('production_authorized',True),('authority','GRANT')]:
            obs,labels=self._scored()
            obs[field]=value
            self.reseal(obs)
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.reviewed(obs,labels)

    def test_reviewer_rejects_forged_physical_counters(self):
        for field,value in [('physical_encoder_calls',7),('physical_reader_calls',9),
                            ('physical_query_calls',1),('physical_encoder_calls',8.0)]:
            obs,labels=self._scored()
            obs[field]=value
            self.reseal(obs)
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.reviewed(obs,labels)

    def test_reviewer_rejects_unaccounted_condition_wall_time(self):
        obs,labels=self._scored()
        obs['measured_whole_call_wall_ns']=1
        self.reseal(obs)
        # Also reseal a malicious replay receipt, to exercise deeper cost checks;
        # a digest by itself never authenticates the physical work.
        self.physical_replay['observation_id']=obs['observation_id']
        self.physical_replay['replay_id']=digest({k:v for k,v in self.physical_replay.items() if k!='replay_id'})
        with self.assertRaisesRegex(ValueError,'undercounts'):
            self.reviewed(obs,labels)

    def test_reviewer_rejects_v1_observation_schema_not_silently_relabelled(self):
        obs,labels=self._scored()
        obs['schema']='hepta.reader.support-causal-observation.v1'
        self.reseal(obs)
        with self.assertRaises(ValueError):
            self.reviewed(obs,labels)

    def test_reviewer_rejects_extra_attacker_claims(self):
        obs,labels=self._scored()
        obs['independent_source_verified']=True
        self.reseal(obs)
        with self.assertRaises(ValueError):
            self.reviewed(obs,labels)

    def test_reviewer_rejects_missing_or_altered_original_reference(self):
        obs,labels=self._scored()
        with self.assertRaises(ValueError):
            self.reviewed(obs,labels,references=[])
        with self.assertRaises(ValueError):
            self.reviewed(obs,labels,weight_id='f'*64)
        x=copy.deepcopy(self.refs)
        x[0]['weights_sha256']='f'*64
        with self.assertRaises(ValueError):
            self.reviewed(obs,labels,references=x)

    def test_score_carries_separately_computed_original_reference_digest(self):
        obs,labels=self._scored()
        result=self.reviewed(obs,labels)
        self.assertTrue(result['original_v1_replayed_at_scoring'])
        self.assertEqual(len(result['original_v1_reference_sha256']),64)
        self.assertFalse(result['independent_model_origin_signatures_verified'])
        self.assertTrue(result['full_tensor_call_census_structurally_verified'])
        self.assertEqual(result['authority'],'DENY_ALL')
        self.assertNotIn('premise_removed',result['original_label_descriptive_accuracy'])

    def test_second_pass_executes_four_real_torch_conditions_again(self):
        obs,labels=self._scored()
        self.assertEqual(self.physical_replay['physically_reexecuted_encoder_calls'],8)
        self.assertEqual(self.physical_replay['physically_reexecuted_reader_calls'],8)
        self.assertEqual(self.physical_replay['physically_reexecuted_query_calls'],2)
        self.assertEqual(len(self.encoder.calls),8+8+8)
        self.assertFalse(self.physical_replay['independent_semantic_sufficiency_verified'])
        self.assertFalse(self.physical_replay['production_authorized'])

    def test_second_pass_catches_changed_non_original_predictions(self):
        obs,labels=self._scored()
        tampered=copy.deepcopy(obs)
        tampered['rows'][0]['observations']['premise_removed']['logits'][0] += 0.12
        self.reseal(tampered)
        with self.assertRaisesRegex(ValueError,'differs from sealed logits'):
            replay_physical(self.plan,tampered,encoder=self.encoder,
                question_encoder=self.query,reader=self.reader,
                expected_reader_weights_sha256=self.weights)

    def test_second_pass_refuses_mutated_frozen_identity(self):
        obs,labels=self._scored()
        with self.assertRaises(ValueError):
            replay_physical(self.plan,obs,encoder=self.encoder,
                question_encoder=self.query,reader=self.reader,
                expected_reader_weights_sha256='d'*64)
        with self.assertRaises(ValueError):
            replay_physical(self.plan,obs,encoder=lambda _:torch.ones((1,4)),
                question_encoder=self.query,reader=self.reader,
                expected_reader_weights_sha256=self.weights)

    def test_scoring_refuses_altered_replay_census_even_if_rehashed(self):
        obs,labels=self._scored()
        bad=copy.deepcopy(self.physical_replay)
        bad['physically_reexecuted_encoder_calls']=7
        bad['replay_id']=digest({k:v for k,v in bad.items() if k!='replay_id'})
        with self.assertRaisesRegex(ValueError,'physical replay evidence'):
            review(self.plan,obs,labels,expected_observation_id=obs['observation_id'],
                expected_labels_sha256=digest(labels),original_reference_rows=self.refs,
                expected_reader_weights_sha256=self.weights,physical_replay_receipt=bad)

    def test_scoring_rejects_fake_external_signer_in_replay(self):
        obs,labels=self._scored()
        bad=copy.deepcopy(self.physical_replay)
        bad['external_original_model_signer_verified']=True
        bad['replay_id']=digest({k:v for k,v in bad.items() if k!='replay_id'})
        with self.assertRaises(ValueError):
            review(self.plan,obs,labels,expected_observation_id=obs['observation_id'],
                expected_labels_sha256=digest(labels),original_reference_rows=self.refs,
                expected_reader_weights_sha256=self.weights,physical_replay_receipt=bad)

    def test_scoring_refuses_missing_replay_receipt(self):
        obs,labels=self._scored()
        with self.assertRaises(ValueError):
            review(self.plan,obs,labels,expected_observation_id=obs['observation_id'],
                expected_labels_sha256=digest(labels),original_reference_rows=self.refs,
                expected_reader_weights_sha256=self.weights,physical_replay_receipt=None)

    def test_replay_ledger_and_signed_scores_remain_research_only(self):
        obs,labels=self._scored()
        scores=self.reviewed(obs,labels)
        self.assertEqual(scores['physical_replay_id'],self.physical_replay['replay_id'])
        self.assertTrue(scores['physical_second_pass_reexecution_structurally_verified'])
        self.assertFalse(scores['independent_model_origin_signatures_verified'])
        self.assertNotIn('premise_removed',scores['original_label_descriptive_brier'])

if __name__=='__main__': unittest.main()
