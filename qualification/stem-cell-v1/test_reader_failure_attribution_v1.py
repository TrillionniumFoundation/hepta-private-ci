"""Synthetic contract tests only; not pretrained Reader or human efficacy tests."""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from reader_failure_attribution_v1 import (
    OBS, PLAN, REPLAY, REVIEW, _p1, _read_file, attribute, digest)


def seal(obj, key):
    obj[key] = digest({k: v for k, v in obj.items() if k != key})
    return obj


def make_fixture():
    rows = []
    obs_rows = []
    for i in range(2):
        passage = f"subject {i} wears blue. subject {i} lives north. other fact."
        spans = [[passage.index(f"subject {i} wears blue"), passage.index(f"subject {i} wears blue")+len(f"subject {i} wears blue.")],
                 [passage.index(f"subject {i} lives north"), passage.index(f"subject {i} lives north")+len(f"subject {i} lives north.")]]
        row = dict(task_id=f"case-{i}", source_group=f"root-{i}", evidence=passage,
                   question=f"Does subject {i} wear blue?", answer="yes",
                   support_spans=spans, critical_span_index=0)
        rows.append(row)
        from reader_failure_attribution_v1 import _condition_texts
        observations = {}
        for name, source_text in _condition_texts(row).items():
            logits = [-2., 2.] if name == 'support_candidate' or i == 1 else [2., -2.]
            observations[name] = dict(logits=logits, probability=_p1(logits),
                evidence_sha256=hashlib.sha256(source_text.encode()).hexdigest())
        obs_rows.append(dict(task_id=row['task_id'], source_group=row['source_group'],
            original_input_sha256=hashlib.sha256(passage.encode()).hexdigest(),
            observations=observations, condition_wall_ns=dict.fromkeys(observations, 1)))
    plan = seal(dict(schema=PLAN, panel_sha256='a'*64, model_sha256='b'*64,
                     rows=rows, labels_available_to_runner=False,
                     support_independently_verified=False), 'plan_id')
    observed = seal(dict(schema=OBS, plan_id=plan['plan_id'],
        panel_sha256=plan['panel_sha256'], model_sha256=plan['model_sha256'],
        reader_weights_sha256='c'*64,condition_order=['no_evidence','ordinary_retrieval',
        'support_candidate','premise_removed'],rows=obs_rows,physical_encoder_calls=8,
        physical_reader_calls=8, physical_query_calls=2,
        original_prediction_replay_verified=True, production_authorized=False,
        reading_labels=False,authority='DENY_ALL',
        measured_whole_call_wall_ns=90000,
        external_semantic_sufficiency_authenticated=False,
        independent_real_source_authenticated=False,
        measured_complete_model_lifecycle=False), 'observation_id')
    replay = seal(dict(schema=REPLAY, observation_id=observed['observation_id'],
        plan_id=plan['plan_id'], model_sha256=plan['model_sha256'],
        reader_weights_sha256='c'*64, physically_reexecuted_encoder_calls=8,
        physically_reexecuted_reader_calls=8, physically_reexecuted_query_calls=2,
        max_absolute_logit_difference=0.0, label_owner_material_opened=False,
        production_authorized=False,authority='DENY_ALL',
        actual_reexecution_wall_ns=99000,
        exact_frozen_model_loader_used=False,
        external_original_model_signer_verified=False,
        independent_semantic_sufficiency_verified=False), 'replay_id')
    labels = dict(schema='hepta.reader.support-label-owner.v1',
                  plan_id=plan['plan_id'], labels={'case-0':1,'case-1':1})
    reviewers = []
    for who in ('reviewer-independent-A','reviewer-independent-B'):
        reviewers.append(dict(reviewer_id=who, rows=[dict(task_id=r['task_id'],
            source_group=r['source_group'], support_decidable=True,removed_decidable=False)
            for r in rows]))
    review = seal(dict(schema=REVIEW, plan_id=plan['plan_id'],
        observation_id=observed['observation_id'], labels_visible=False,
        reviewers=reviewers), 'review_id')
    return plan, observed, replay, labels, review


class AttributionTests(unittest.TestCase):
    def setUp(self):
        self.inputs = make_fixture()

    def test_closed_retrieval_diagnostic_and_no_promotion(self):
        output = attribute(*self.inputs)
        self.assertEqual(output['counts']['total_candidates'],2)
        self.assertEqual(output['counts']['candidate_retrieval_gap'],1)
        self.assertEqual(output['counts']['candidate_reader_or_representation_blocker'],0)
        self.assertFalse(output['premise_removed_original_binary_label_valid'])
        self.assertFalse(output['semantic_sufficiency_independently_certified'])
        self.assertEqual(output['decision'],'DESCRIPTIVE_HOLD_NO_GO')
        self.assertNotIn('subject',json.dumps(output))

    def test_data_driven_reader_capacity_candidate_not_a_win(self):
        d = copy.deepcopy(self.inputs)
        d[1]['rows'][0]['observations']['support_candidate']['logits']=[2.,-2.]
        d[1]['rows'][0]['observations']['support_candidate']['probability']=_p1([2.,-2.])
        seal(d[1], 'observation_id')
        d[2]['observation_id']=d[1]['observation_id'];seal(d[2],'replay_id')
        d[4]['observation_id']=d[1]['observation_id'];seal(d[4],'review_id')
        output=attribute(*d)
        self.assertEqual(output['counts']['candidate_reader_or_representation_blocker'],1)
        self.assertFalse(output['reader_capacity_or_retrieval_winner_verified'])

    def test_different_group_same_original_source_refused(self):
        d=copy.deepcopy(self.inputs)
        d[0]['rows'][1]['evidence']=d[0]['rows'][0]['evidence']
        seal(d[0],'plan_id')
        d[1]['plan_id']=d[0]['plan_id']
        from reader_failure_attribution_v1 import _condition_texts
        changed=d[0]['rows'][1]
        target=d[1]['rows'][1]
        target['original_input_sha256']=hashlib.sha256(changed['evidence'].encode()).hexdigest()
        for condition,text in _condition_texts(changed).items():
            target['observations'][condition]['evidence_sha256']=hashlib.sha256(text.encode()).hexdigest()
        seal(d[1],'observation_id')
        d[2]['plan_id']=d[0]['plan_id'];d[2]['observation_id']=d[1]['observation_id'];seal(d[2],'replay_id')
        d[3]['plan_id']=d[0]['plan_id']
        d[4]['plan_id']=d[0]['plan_id'];d[4]['observation_id']=d[1]['observation_id'];seal(d[4],'review_id')
        with self.assertRaisesRegex(ValueError,'aliased source root'):
            attribute(*d)

    def test_missing_critical_premise_is_not_original_wrong_answer(self):
        out=attribute(*self.inputs)
        self.assertNotIn('premise_removed_correct',out['counts'])
        self.assertEqual(out['counts']['removed_premise_unanswerable_claims'],2)

    def test_review_disagreement_drops_task_without_cherry_pick(self):
        d=copy.deepcopy(self.inputs)
        d[4]['reviewers'][1]['rows'][0]['support_decidable']=False
        seal(d[4],'review_id')
        out=attribute(*d)
        self.assertEqual(out['counts']['reviewer_disagreements'],1)
        self.assertEqual(out['counts']['reviewer_claimed_support_decidable'],1)
        self.assertEqual(out['counts']['total_candidates'],2)

    def test_review_cannot_include_labels_or_auth(self):
        for field,value in [('label',1),('certified',True)]:
            d=copy.deepcopy(self.inputs)
            d[4]['reviewers'][0]['rows'][0][field]=value
            seal(d[4],'review_id')
            with self.assertRaises(ValueError):attribute(*d)

    def test_mismatched_review_identity_and_same_reviewer(self):
        d=copy.deepcopy(self.inputs)
        d[4]['observation_id']='d'*64;seal(d[4],'review_id')
        with self.assertRaises(ValueError):attribute(*d)
        d=copy.deepcopy(self.inputs)
        d[4]['reviewers'][1]['reviewer_id']=d[4]['reviewers'][0]['reviewer_id'];seal(d[4],'review_id')
        with self.assertRaises(ValueError):attribute(*d)

    def test_label_owner_cannot_omit_or_use_boolean_label(self):
        d=copy.deepcopy(self.inputs);d[3]['labels'].pop('case-0')
        with self.assertRaises(ValueError):attribute(*d)
        d=copy.deepcopy(self.inputs);d[3]['labels']['case-0']=True
        with self.assertRaises(ValueError):attribute(*d)

    def test_resealed_tampered_logits_rejected(self):
        d=copy.deepcopy(self.inputs)
        d[1]['rows'][0]['observations']['support_candidate']['logits'][1]=50.
        seal(d[1],'observation_id')
        d[2]['observation_id']=d[1]['observation_id'];seal(d[2],'replay_id')
        d[4]['observation_id']=d[1]['observation_id'];seal(d[4],'review_id')
        with self.assertRaisesRegex(ValueError,'probability'):
            attribute(*d)

    def test_replay_mandatory_even_with_syntactically_good_score(self):
        d=copy.deepcopy(self.inputs);d[2]['physically_reexecuted_reader_calls']=7;seal(d[2],'replay_id')
        with self.assertRaisesRegex(ValueError,'second Reader'):
            attribute(*d)

    def test_original_observation_promotion_and_missing_case_denied(self):
        d=copy.deepcopy(self.inputs);d[1]['production_authorized']=True;seal(d[1],'observation_id')
        with self.assertRaises(ValueError):attribute(*d)
        d=copy.deepcopy(self.inputs);d[1]['rows'].pop();seal(d[1],'observation_id')
        with self.assertRaises(ValueError):attribute(*d)

    def test_strict_disk_path_sha_duplicates_and_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'data.json';p.write_text('{"a":1,"b":2}')
            correct=hashlib.sha256(p.read_bytes()).hexdigest()
            self.assertEqual(_read_file(str(p),correct),{'a':1,'b':2})
            with self.assertRaises(ValueError):_read_file(str(p),'0'*64)
            p.write_text('{"a":1,"a":2}')
            with self.assertRaisesRegex(ValueError,'duplicate'): _read_file(str(p),hashlib.sha256(p.read_bytes()).hexdigest())
            link=Path(temp)/'link.json';link.symlink_to(p)
            with self.assertRaises(OSError):_read_file(str(link),hashlib.sha256(p.read_bytes()).hexdigest())
            with self.assertRaises(ValueError):_read_file('relative.json',correct)

    def test_malformed_probability_binary_operator_rejected(self):
        for wrong in [True, 10., -4.]:
            d=copy.deepcopy(self.inputs)
            d[1]['rows'][1]['observations']['ordinary_retrieval']['probability']=wrong
            seal(d[1],'observation_id')
            d[2]['observation_id']=d[1]['observation_id'];seal(d[2],'replay_id')
            d[4]['observation_id']=d[1]['observation_id'];seal(d[4],'review_id')
            with self.assertRaises(ValueError):attribute(*d)
        d=copy.deepcopy(self.inputs)
        d[1]['rows'][1]['observations']['ordinary_retrieval']['probability']=float('nan')
        with self.assertRaises(ValueError): seal(d[1],'observation_id')


if __name__ == '__main__':
    unittest.main()
