"""Original E3 result audit tests; synthetic fixtures cannot certify a model."""
import copy
from unittest.mock import patch
import unittest

import scienceqa_margin_stability_v6 as m
from scienceqa_independent_rejudge_v5 import canonical, sha, V5Error


def fixture():
    rows = []
    for i in range(64):
        baseline = [.6, .2, .1, .1]
        override = [.2, .6, .1, .1] if i % 2 == 0 else baseline[:]
        arms = {a: (override[:] if a == 'train_gate' else baseline[:]) for a in m.ARMS}
        rows.append({'id': f'{i:064x}', 'group': f'{(i+64):064x}',
                     'source_input_sha256': f'{(i+128):064x}',
                     'split': 'test', 'arms': arms})
    doc = {'source_sha256':'a'*64, 'arms':list(m.ARMS),
           'production_accepted':False, 'held_labels_visible_to_inference':False,
           'predictions':rows}
    return {'sealed-source-bound-predictions.json':canonical(doc)}


class MarginOriginalTests(unittest.TestCase):
    def test_positive_distinct_from_model_quality(self):
        data = fixture()
        with patch.object(m, 'SOURCE_SHA','a'*64), patch.object(
            m, 'PRED_SHA', sha(data['sealed-source-bound-predictions.json'])):
            result = m.audit(data)
        self.assertEqual(result['case_count'],64)
        self.assertEqual(result['arms']['train_gate']['argmax_changes_vs_text'],32)
        self.assertEqual(result['arms']['train_gate']['certified_changed_at_epsilon']['0.0050'],32)
        self.assertEqual(result['arms']['text_only']['argmax_changes_vs_text'],0)
        self.assertFalse(result['visual_necessity_or_task_quality_proven'])
        self.assertFalse(result['actual_image_intervention_performed'])
        self.assertFalse(result['heldout_labels_accessed'])
        self.assertEqual(result['authority'], 'DENY_ALL')

    def test_small_margin_flips_must_abstain(self):
        data = fixture(); doc=m.parse(data['sealed-source-bound-predictions.json'])
        for row in doc['predictions']:
            base = [.251,.249,.25,.25]
            arm = [.249,.251,.25,.25]
            for name in m.ARMS:
                row['arms'][name] = arm[:] if name == 'train_gate' else base[:]
        data['sealed-source-bound-predictions.json'] = canonical(doc)
        with patch.object(m, 'SOURCE_SHA','a'*64), patch.object(
            m, 'PRED_SHA', sha(data['sealed-source-bound-predictions.json'])):
            out = m.audit(data)['arms']['train_gate']
        self.assertEqual(out['argmax_changes_vs_text'],64)
        self.assertEqual(out['certified_changed_at_epsilon']['0.0010'],0)
        self.assertEqual(out['abstaining_cases_at_epsilon']['0.0010'],64)

    def test_reject_output_identity_and_improper_probabilities(self):
        data=fixture()
        with self.assertRaises(V5Error):m.audit(data)
        for kind in ('mask','nan','duplicate','production','ids'):
            bad=copy.deepcopy(data)
            doc=m.parse(bad['sealed-source-bound-predictions.json'])
            if kind=='mask':doc['predictions'][0]['arms']['image_masked']=[.2,.6,.1,.1]
            elif kind=='nan':doc['predictions'][0]['arms']['train_gate']=[float('nan'),.2,.2,.6]
            elif kind=='duplicate':doc['predictions'][1]['id']=doc['predictions'][0]['id']
            elif kind=='production':doc['production_accepted']=True
            elif kind=='ids':doc['predictions'][0]['source_input_sha256']='123'
            try:bad['sealed-source-bound-predictions.json']=canonical(doc)
            except ValueError: continue  # parse explicitly refuses nonfinite JSON
            with patch.object(m,'SOURCE_SHA','a'*64),patch.object(
                 m,'PRED_SHA',sha(bad['sealed-source-bound-predictions.json'])):
                with self.subTest(kind=kind),self.assertRaises(V5Error):m.audit(bad)

    def test_robustness_certificate_threshold(self):
        self.assertEqual(m.top_two([.3,.3,.2,.2]),(0,0))
        self.assertEqual(m.top_two([.1,.6,.2,.1])[0],1)
        self.assertAlmostEqual(m.top_two([.1,.6,.2,.1])[1],.4)
        with self.assertRaises(V5Error):m.top_two([.5,.5,0.01,0])


if __name__=='__main__':unittest.main()
