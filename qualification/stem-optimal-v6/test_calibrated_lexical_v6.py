"""Source-only adversarial original-shape fixtures, not true publisher efficacy."""
from __future__ import annotations

import copy
import hashlib
import json
from unittest.mock import patch
import unittest

import calibrated_lexical_v6 as candidate
import independent_calibration_review_v6 as reviewer


def fixture():
    rows = {'train':[], 'heldout':[]}
    for label, name in enumerate(candidate.INTENTS):
        for split, count in [('train',16),('heldout',8)]:
            for i in range(count):
                value=f'{split} illustrative account {name} number {i} query variant {label}'
                h=hashlib.sha256(value.encode()).hexdigest()
                row={'case_id':('fit:' if split=='train' else 'heldout:')+h,
                     'source_sha256':h, 'text':value}
                if split=='train':row['label']=label
                rows[split].append(row)
    for split in rows:
        rows[split].sort(key=lambda r:r['case_id'])
    result = {'schema':candidate.SOURCE_SCHEMA,'cohort':'hard-charge-four-intents-v3',
              'intents':list(candidate.INTENTS),'publisher_revision':candidate.PUBLISHER,
              'publisher_sha256':candidate.CSV_SHA,'train':rows['train'],
              'heldout':rows['heldout'],'heldout_labels_excluded':True,
              'research_only':True,'production_authorized':False}
    result['source_plan_sha256']=candidate.digest(candidate.canonical(result))
    return result


class TestFitOnlyCalibrator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = fixture()
        cls.sha=cls.source['source_plan_sha256']

    def setUp(self):
        self.patches=(patch.object(candidate,'SOURCE_SHA',self.sha),
                      patch.object(reviewer,'SOURCE_SHA',self.sha))
        for p in self.patches:p.start()
        self.addCleanup(self._stop)
        self.result = candidate.produce(self.source)

    def _stop(self):
        for p in reversed(self.patches):p.stop()

    def test_full_4fold_64fit_32label_free_control_replays(self):
        self.assertEqual(reviewer.independently_replay(self.source,self.result),
            {a:self.result['calibration'][a]['temperature'] for a in candidate.ARMS})
        self.assertEqual([sum(f['fold']==j for f in self.result['fit_folds']) for j in range(4)],
                         [16]*4)
        self.assertEqual(len(self.result['rows']),32)
        self.assertTrue(all('label' not in r for r in self.result['rows']))
        self.assertEqual(self.result['authority'],'DENY_ALL')
        self.assertFalse(self.result['production_authorized'])

    def test_future_case_text_never_changes_temperature_or_cross_validation(self):
        altered=copy.deepcopy(self.source)
        altered['heldout'][0]['text']='new heldout only invented wildcard xyzz example'
        digest=candidate.digest(altered['heldout'][0]['text'].encode())
        altered['heldout'][0]['source_sha256']=digest
        altered['heldout'][0]['case_id']='heldout:'+digest
        new_sha=candidate.digest(candidate.canonical({k:v for k,v in altered.items()
                                                        if k!='source_plan_sha256'}))
        altered['source_plan_sha256']=new_sha
        with patch.object(candidate,'SOURCE_SHA',new_sha):
            new=candidate.produce(altered)
        self.assertEqual(new['calibration'],self.result['calibration'])
        self.assertEqual(new['fit_folds'],self.result['fit_folds'])

    def test_change_tuned_temperature_denied(self):
        result=copy.deepcopy(self.result)
        a=candidate.ARMS[0]
        result['calibration'][a]['temperature']=100.0
        with self.assertRaisesRegex(ValueError,'tampered/heldout-tuned'):
            reviewer.independently_replay(self.source,result)

    def test_crossfit_loss_forgery_denied(self):
        result=copy.deepcopy(self.result)
        result['calibration'][candidate.ARMS[1]]['cv_brier_by_temp'][0]+=0.001
        with self.assertRaisesRegex(ValueError,'tampered/heldout-tuned'):
            reviewer.independently_replay(self.source,result)

    def test_source_mutation_even_same_plan_digest_denied(self):
        source=copy.deepcopy(self.source)
        source['train'][1]['label']=(source['train'][1]['label']+1)%4
        with self.assertRaisesRegex(ValueError,'original source has changed'):
            candidate.produce(source)
        with self.assertRaisesRegex(ValueError,'unsealed source text/label drift'):
            reviewer.independently_replay(source,self.result)

    def test_label_in_heldout_denied(self):
        source=copy.deepcopy(self.source)
        source['heldout'][0]['label']=3
        with self.assertRaises(ValueError):
            candidate.produce(source)

    def test_changed_heldout_probabilities_denied(self):
        result=copy.deepcopy(self.result)
        result['rows'][0]['scores'][candidate.ARMS[0]][1]+=0.001
        with self.assertRaises(ValueError):
            reviewer.independently_replay(self.source,result)

    def test_source_plan_and_fold_swap_denied(self):
        for alter in (
            lambda r:r.__setitem__('source_plan_sha256','0'*64),
            lambda r:r['fit_folds'][0].__setitem__('fold',(r['fit_folds'][0]['fold']+1)%4),
            lambda r:r.__setitem__('fold_salt','unfrozen'),
            lambda r:r['temperature_grid'].append(64.),
        ):
            result=copy.deepcopy(self.result)
            alter(result)
            with self.assertRaises(ValueError):
                reviewer.independently_replay(self.source,result)

    def test_fake_neural_and_future_claims_denied(self):
        for alter in (
            lambda r:r.__setitem__('production_authorized',True),
            lambda r:r.__setitem__('future_windows',2),
            lambda r:r.__setitem__('stem_winner_verified',True),
            lambda r:r['cost'].__setitem__('neural_forward_count',4),
            lambda r:r['cost'].__setitem__('p99_latency_ms',0.01),
            lambda r:r.__setitem__('heldout_label_access',True),
        ):
            result=copy.deepcopy(self.result)
            alter(result)
            with self.assertRaises(ValueError):
                reviewer.independently_replay(self.source,result)

    def test_train_only_idf_and_order_independence_of_heldout(self):
        a,_=candidate._scores(self.source['train'],self.source['heldout'],candidate.ARMS[0])
        b,_=candidate._scores(self.source['train'],list(reversed(self.source['heldout'])),candidate.ARMS[0])
        self.assertEqual(a,list(reversed(b)))

    def test_probability_temperature_never_changes_top_class(self):
        for arm in candidate.ARMS:
            p=self.result['rows'][0]['scores'][arm]
            self.assertEqual(len(p),4)
            self.assertAlmostEqual(sum(p),1.0,places=12)
        self.assertEqual(self.result['cost']['neural_forward_count'],0)


if __name__=='__main__':
    unittest.main()
