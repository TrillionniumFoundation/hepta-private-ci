"""Synthetic ONLY. V30 physical score, CPU and model bytes require hosted real run."""
from __future__ import annotations
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

import v28_physical_lazy_vision as p
import v29_route_only as prior
import v30_live_text_vision as v


def source_fixture():
    cases=[];route=[];scores={}
    for i in range(64):
        ident=f'{i+1:064x}';group=f'{1000+i:064x}'
        cases.append({'id':ident,'group':group,'split':'test','image':f'{2000+i:064x}',
                      'question':'SYNTHETIC '+str(i),'choices':['a','b','c','d'],'hint':'',
                      'scope':'public-scienceqa-e3-research'})
        trigger=i<21
        route.append({'id':ident,'group':group,'trigger_vision':trigger})
        scores[ident]=(0.2509,0.2507,0.2493,0.2491) if trigger else (0.8,0.1,0.05,0.05)
    return cases,route,scores


class LiveTextRoute(unittest.TestCase):
    def test_valid_live_source_threshold_exact_21(self):
        a,b,c=source_fixture()
        found=v.route_from_live_text(a,c,b)
        self.assertEqual(len(found),21)
        self.assertEqual([x['id'] for x in found],[x['id'] for x in a[:21]])

    def test_training_label_not_consulted_for_route(self):
        a,b,c=source_fixture();a[0]['answer']=3
        self.assertEqual(len(v.route_from_live_text(a,c,b)),21)
        # Model's actual encode_text_scores independently rejects answer inputs.

    def test_invalid_score_missing_case_rejected(self):
        a,b,c=source_fixture();c.pop(a[20]['id'])
        with self.assertRaises(p.Reject):v.route_from_live_text(a,c,b)

    def test_boolean_and_nan_score_rejected(self):
        for value in (True,float('nan'),float('inf'),-1.0):
            a,b,c=source_fixture();c[a[0]['id']]=(value,.25,.25,.25)
            with self.subTest(value=value),self.assertRaises(p.Reject):v.route_from_live_text(a,c,b)

    def test_exact_prediction_route_change_rejected(self):
        a,b,c=source_fixture();b[0]['trigger_vision']=False
        with self.assertRaisesRegex(p.Reject,'contradicts'):v.route_from_live_text(a,c,b)

    def test_duplicate_group_and_order_rejected(self):
        a,b,c=source_fixture();a[1]['group']=a[0]['group']
        with self.assertRaises(p.Reject):v.route_from_live_text(a,c,b)
        a,b,c=source_fixture();b[0],b[1]=b[1],b[0]
        with self.assertRaises(p.Reject):v.route_from_live_text(a,c,b)

    def test_counterfactual_class_payload_rejected(self):
        a,b,c=source_fixture();b[0]['image_class']=1
        with self.assertRaises(p.Reject):v.route_from_live_text(a,c,b)

    def test_false_prob_shape_rejected(self):
        for value in ((0.2,0.3,0.4),(0.2,0.3,0.4,0.4),[True,.1,.1,.1]):
            a,b,c=source_fixture();c[a[0]['id']]=value
            with self.subTest(value=value),self.assertRaises(p.Reject):v.route_from_live_text(a,c,b)

    def test_wrong_route_cutoff_is_not_autotuned(self):
        a,b,c=source_fixture();c[a[0]['id']]=(.6,.1,.2,.1)
        with self.assertRaises(p.Reject):v.route_from_live_text(a,c,b)

    def test_nan_softmax_denied(self):
        with self.assertRaises(p.Reject):v.softmax([0,0,float('nan'),1])
        with self.assertRaises(p.Reject):v.softmax([0,0,0])
        with self.assertRaises(p.Reject):v.softmax([True,0.,0.,0.])

    def test_softmax_is_normed_stable_and_pure(self):
        x=v.softmax((500,500,499,498))
        self.assertEqual(len(x),4)
        self.assertAlmostEqual(sum(x),1.0,places=13)
        self.assertEqual(v.softmax((3,2,1,0)),v.softmax((4,3,2,1)))


class ABBA(unittest.TestCase):
    def fake(self, *, invalid_batch=False, swapped=False, drift=False):
        a,b,c=source_fixture(); call=[0]
        def text(rows):
            call[0]+=1
            selected=dict(c)
            if swapped and call[0]==2:selected[a[0]['id']]=(.8,.1,.05,.05)
            return {'text_items':320,'text_batches':20,'text_wall_ns':100,'text_cpu_ns':90},selected
        def vision(rows):
            key={r['id'] for r in rows}
            obs={'items':len(rows),'batches':8 if len(rows)==64 else 3,
                 'cpu_ns':200,'wall_ns':220,'media_bytes_read':len(rows)*123}
            if invalid_batch and len(rows)==21:obs['batches']=0
            val=1. if drift and len(rows)==21 else 0.
            return obs,{k:[val]*384 for k in key}
        return a,b,text,vision

    def test_four_valid_arms_and_counts(self):
        a,b,text,vision=self.fake()
        rows,td,vd=v.study_arms(a,b,text,vision)
        self.assertEqual([x['arm'] for x in rows],['all64','conditional21','conditional21','all64'])
        self.assertEqual([x['text_batches'] for x in rows],[20]*4)
        self.assertEqual([x['batches'] for x in rows],[8,3,3,8])
        self.assertEqual((td,vd),(0.,0.))

    def test_real_driver_arity_gate(self):
        a,b,text,vision=self.fake(invalid_batch=True)
        with self.assertRaises(p.Reject):v.study_arms(a,b,text,vision)

    def test_static_history_cannot_select_without_live_text(self):
        a,b,text,vision=self.fake(swapped=True)
        with self.assertRaises(p.Reject):v.study_arms(a,b,text,vision)

    def test_vision_parity_is_strict(self):
        a,b,text,vision=self.fake(drift=True)
        with self.assertRaises(p.Reject):v.study_arms(a,b,text,vision)

    def test_miscounted_text_batches_rejected(self):
        a,b,text,vision=self.fake()
        def false_text(rows):
            receipt,prob=text(rows);receipt['text_batches']=19
            return receipt,prob
        with self.assertRaises(p.Reject):v.study_arms(a,b,false_text,vision)

    def test_same_text_model_required_each_arm(self):
        a,b,text,vision=self.fake()
        call=[0]
        def bad_text(rows):
            call[0]+=1
            obs,prob=text(rows)
            if call[0]==3:prob[a[35]['id']]=(.7,.15,.1,.05)
            return obs,prob
        with self.assertRaises(p.Reject):v.study_arms(a,b,bad_text,vision)

    def test_backend_width_and_strict_model_tuple(self):
        self.assertEqual(v.GRANITE_REPO,'ibm-granite/granite-embedding-97m-multilingual-r2')
        self.assertEqual(v.GRANITE_REV,'835ad14087e140460703cf0fae09f97d469d65c2')
        self.assertEqual(v.TEXT_WIDTH,384)
        self.assertEqual((v.TEXT_BATCH,v.TEXT_FORWARDS),(16,20))
        self.assertEqual(v.SCHEMA,'hepta.stem.v30.live-text-selective-vision-cost.v1')


class Workflow(unittest.TestCase):
    def test_workflow_is_push_only_for_real_weights(self):
        root=Path(__file__).resolve().parents[2]
        file=root/'.github/workflows/hepta-stem-v30-live-text-vision.yml'
        s=file.read_text()
        self.assertIn('v30_live_text_vision.py',s)
        self.assertIn("github.event_name == 'push'",s)
        self.assertIn('--predictor-source-only',s)
        self.assertIn('test ! -e "$RUNNER_TEMP/original-e3.zip"',s)
        self.assertIn('fit_labels.jsonl',s)
        self.assertIn('v29_route_only.py',s)
        self.assertNotIn('--plan "$RUNNER_TEMP/private-v29-full-plan.json" \\\n            --source-dir',s)
        self.assertIn('DENY_ALL',s)

    def test_pinned_model_dependencies_are_not_silent(self):
        text=(Path(__file__).resolve().parents[2]/'.github/workflows/hepta-stem-v30-live-text-vision.yml').read_text()
        for blob in ('733da82a4bbbde1b256dfd1dbe4c05832dcd4856',
                     'b99c99d8e13a4d1899a0597d7733753fb3ce092a',
                     '27839fbeb9402e8afeb1f2a23288006146757a53',
                     'd562d7e5c518a1f194c0f026968e8d64e996c527',
                     'f4ec7f415c6dc3f51a965c603eb96339d908413c',
                     'b3d54cec40c82d51457925f2a2113566cd8f1c6c'):
            self.assertIn(blob,text)
        self.assertIn('a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202',text)
        self.assertIn('d8a555bef8f95680cd35a16cf3dbe7f8e9ab717fe626e4dc82e6fd61538773a6',text)


if __name__=='__main__':unittest.main()
