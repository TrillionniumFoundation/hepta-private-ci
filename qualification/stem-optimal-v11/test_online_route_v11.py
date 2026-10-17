"""No-network, label-blind routing invariants; synthetic cases are NOT model evidence."""
from __future__ import annotations

import copy
import hashlib
import random
import unittest

import online_route_v11 as v11


def sample():
    rng = random.Random(837)
    lexicon = ('money transfer card fee cash exchange refund airport account current '
               'payment deposit income denied foreign withdrawal charged phone issue '
               'why when how bill online').split()
    families = ('card', 'cash', 'exchange', 'transfer')
    fit = []
    for i in range(64):
        label = i % 4
        text = ' '.join(rng.choices(lexicon, k=rng.randint(8, 23))) + f' {i} ' + families[label]
        digest = hashlib.sha256(text.encode()).hexdigest()
        fit.append({'case_id':'fit:'+digest, 'source_sha256':digest, 'label':label, 'text':text})
    held = []
    for i in range(32):
        text = ' '.join(rng.choices(lexicon, k=rng.randint(7, 24))) + f' test-{i}'
        digest = hashlib.sha256(text.encode()).hexdigest()
        held.append({'case_id':'heldout:'+digest, 'source_sha256':digest, 'text':text})
    probs = v11.reference_predict(fit, held)
    cheap = [{'case_id':row['case_id'], 'source_sha256':row['source_sha256'],
              'scores':{'word_12_tfidf_centroid':[0.25]*4,
                        'char_345_tfidf_centroid':probs[i]}}
             for i,row in enumerate(held)]
    return fit, held, cheap


class TrainOnlyOnlinePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fit, cls.held, cls.cheap = sample()
        cls.plan = v11.build(cls.fit, cls.held, cls.cheap)

    def test_actual_cpu_lexical_and_train_only_fourfold(self):
        self.assertEqual(self.plan['fit_fold_census'], {'0':16,'1':16,'2':16,'3':16})
        self.assertEqual(self.plan['target_fit_escalations'],16)
        self.assertTrue(0 < self.plan['fit_oof_margin_boundary'] < 1)
        self.assertEqual(len(self.plan['fit_oof_scores_sha256']),64)
        self.assertEqual(self.plan['authority'],'DENY_ALL')
        self.assertFalse(self.plan['whole_batch_test_ranking_used'])
        self.assertFalse(self.plan['test_labels_used_for_selection'])

    def test_online_order_independence(self):
        permuted = list(reversed(self.held))
        backwards = v11.build(self.fit,permuted,self.cheap)
        original = {r['case_id']:r['escalate'] for r in self.plan['rows']}
        newer = {r['case_id']:r['escalate'] for r in backwards['rows']}
        self.assertEqual(original,newer)
        self.assertEqual(self.plan['fit_oof_margin_boundary'],backwards['fit_oof_margin_boundary'])

    def test_other_request_cannot_change_prior_routing(self):
        other = copy.deepcopy(self.held)
        updated = copy.deepcopy(self.cheap)
        other[0]['text'] += ' altered entirely unique other request text'
        recalculated = v11.reference_predict(self.fit,other)
        updated[0]['scores'][v11.CHAR] = recalculated[0]
        revised = v11.build(self.fit,other,updated)
        self.assertEqual(self.plan['rows'][1:],revised['rows'][1:])

    def test_heldout_label_or_new_authority_rejected(self):
        source = {'schema':'hepta.stem.charge-stress.source.v3',
                  'source_plan_sha256':v11.SOURCE_SHA,'heldout_labels_excluded':True,
                  'production_authorized':False, 'train':self.fit,'heldout':self.held}
        cheap = {'schema':'hepta.stem.hard-charge.lexical-control.v4',
                 'source_plan_sha256':v11.SOURCE_SHA,'authority':'DENY_ALL',
                 'production_authorized':False,'future_windows':0,
                 'cost':{'neural_encoder_forward_count':0},'rows':self.cheap}
        with self.assertRaisesRegex(ValueError,'canonical publisher'):
            v11.verify_source(source,cheap)
        source['heldout'] = copy.deepcopy(self.held)
        source['heldout'][0]['label'] = 1
        with self.assertRaises(ValueError):v11.verify_source(source,cheap)
        cheap['production_authorized'] = True
        with self.assertRaisesRegex(ValueError,'original cheap authority'):
            v11.verify_source(source,cheap)

    def test_bad_original_scores_denied_even_if_normalized(self):
        damaged = copy.deepcopy(self.cheap)
        a = damaged[0]['scores'][v11.CHAR]
        a[0] += 0.001
        a[1] -= 0.001
        with self.assertRaisesRegex(ValueError,'numeric replay disagrees'):
            v11.build(self.fit,self.held,damaged)

    def test_missing_duplicate_cases_denied(self):
        with self.assertRaises(ValueError):
            v11.build(self.fit,self.held,self.cheap[:-1])
        duplicated = copy.deepcopy(self.cheap)
        duplicated[-1] = copy.deepcopy(duplicated[0])
        with self.assertRaises(ValueError):
            v11.build(self.fit,self.held,duplicated)

    def test_changed_fit_class_or_cv_size_denied(self):
        bad = copy.deepcopy(self.fit)
        bad[0]['label'] = (bad[0]['label'] + 1)%4
        with self.assertRaisesRegex(ValueError,'balanced fit'):
            v11.trained_threshold(bad)
        with self.assertRaisesRegex(ValueError,'fit train-only case count'):
            v11.trained_threshold(self.fit[:-1])

    def test_no_label_branch_or_forged_forward_claim(self):
        self.assertFalse(self.plan['production_authorized'])
        self.assertFalse(self.plan['physical_encoder_savings_verified'])
        self.assertEqual(self.plan['actual_new_pretrained_encoder_forwards'],0)
        self.assertEqual(self.plan['source_independent_families'],1)
        self.assertEqual(self.plan['future_windows'],0)
        self.assertTrue(self.plan['previous_test_gold_exposed'])

    def test_bad_probs_denied(self):
        for prob in ([float('nan'),.25,.25,.25], [.5,.5,.5,False], [.4,.4,.4,-.2]):
            with self.assertRaises(ValueError):
                v11.margin(prob)


if __name__ == '__main__':
    unittest.main()
