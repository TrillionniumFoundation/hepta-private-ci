"""P0.9 tests. Authentic publisher tests SKIP rather than mock physical evidence."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest

import matched_router_p06 as p06
import p09_budgeted_shadow as s

ORIGINAL=Path(os.getenv('P09_AGNEWS_ZIP','/mnt/data/hepta-mmbert-agnews-original-p08.zip'))
RUN=Path(os.getenv('P09_RUN_DIR','/mnt/data/hepta-p09-run'))


def vectors(**override):
    table={key:[0.25]*4 for key in p06.ALL_ARMS}
    for key,p in override.items():table[key]=p
    return table

class PureDecisionTests(unittest.TestCase):
    def test_static_policy_no_learning_and_denial(self):
        self.assertTrue(s.POLICY['historically_exposed_panel'])
        self.assertFalse(s.POLICY['prospective_policy'])
        self.assertEqual(s.POLICY['authority'],'DENY_ALL')
        self.assertEqual(len(s.POLICY_SHA),64)
    def test_mutated_registered_threshold_is_rejected(self):
        # Mutable Python dictionaries do NOT authorize a changed policy SHA.
        with patch.dict(s.POLICY, {'centroid_fast_floor': 0.01}):
            with self.assertRaises(p06.Denied):
                s.decide(vectors(centroid_train_loo=[.85,.05,.05,.05]))

    def test_fast_centroid(self):
        a,p=s.decide(vectors(centroid_train_loo=[.85,.05,.05,.05]))
        self.assertEqual((a,p),('centroid_fast','centroid_train_loo'))
    def test_split_shadow(self):
        a,p=s.decide(vectors(centroid_train_loo=[.4,.2,.2,.2],
                               split=[.10,.70,.1,.1]))
        self.assertEqual((a,p),('split_shadow','split'))
    def test_shared_shadow(self):
        a,p=s.decide(vectors(centroid_train_loo=[.35,.25,.25,.15],
                               shared_one=[.65,.15,.1,.1]))
        self.assertEqual((a,p),('shared_shadow','shared_one'))
    def test_abstain(self):
        a,p=s.decide(vectors(centroid_train_loo=[.32,.23,.23,.22]))
        self.assertEqual((a,p),('stop_shadow','stop'))
    def test_uncertain_cheap(self):
        a,p=s.decide(vectors(centroid_train_loo=[.49,.2,.2,.11]))
        self.assertEqual((a,p),('centroid_uncertain','centroid_train_loo'))
    def test_breaks_ties_without_seeking_gold(self):
        v=vectors(centroid_train_loo=[.5,.2,.2,.1],split=[.58,.2,.12,.1])
        self.assertEqual(s.decide(v),('centroid_uncertain','centroid_train_loo'))
    def test_reject_nan_and_invalid_sum(self):
        for p in [[float('nan'),.4,.3,.3],[.9,.2,0.,0.],[-.1,.5,.3,.3]]:
            with self.subTest(p=p),self.assertRaises(p06.Denied):
                s.decide(vectors(shared_one=p))
    def test_reject_missing_or_extra_arm(self):
        x=vectors();x.pop('split')
        with self.assertRaises(p06.Denied):s.decide(x)
        x=vectors();x['unauthorized']=[1.,0.,0.,0.]
        with self.assertRaises(p06.Denied):s.decide(x)
    def test_no_native_ui_or_fbsde_claim(self):
        src=Path(s.__file__).read_text()
        self.assertNotIn('mprotect(',src)
        self.assertNotIn('exec(',src)
        self.assertNotIn('subprocess.run(',src)
        self.assertNotIn('create_capability',src)
        self.assertFalse(s.POLICY['prospective_policy'])

class OriginalHistoricalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ORIGINAL.is_file() or not (RUN/'prelabel.json').is_file():
            raise unittest.SkipTest('genuine original prior mmBERT material and sealed P0.6 predictor absent')
        cls.source=p06.json_read(RUN/'source.json')
        cls.prelabel=p06._check_prelabel(RUN/'prelabel.json',RUN/'prelabel-seal.json')
        cls.shadow=s.proposed(cls.source,cls.prelabel)

    def test_authentic_prelabel_96_actions_and_unchanged_provenance(self):
        self.assertEqual(len(self.shadow['choices']),96)
        self.assertEqual(self.shadow['registered_policy_sha256'],s.POLICY_SHA)
        self.assertFalse(self.shadow['claims']['production_authorized'])
        self.assertFalse(self.shadow['claims']['resource_savings_physically_measured'])
        # Assert the actual source-head journal, not a cross-device/version
        # numerical byte hash accidentally frozen from one Python environment.
        self.assertEqual(self.shadow['original_prelabel_sha256'],
            hashlib.sha256((RUN/'prelabel.json').read_bytes()).hexdigest())
    def test_reject_prediction_mutation_even_when_internally_rehashed(self):
        x=copy.deepcopy(self.shadow)
        x['choices'][0]['probabilities']=[1.,0.,0.,0.]
        with self.assertRaises(p06.Denied):s.verify_shadow(self.source,self.prelabel,x)
    def test_reject_future_promotion_forgery(self):
        x=copy.deepcopy(self.shadow)
        x['claims']['prospective_window']=True
        with self.assertRaises(p06.Denied):s.verify_shadow(self.source,self.prelabel,x)
    def test_reject_label_leak_into_held_source(self):
        source=copy.deepcopy(self.source)
        source['holdout'][0]['target']=1
        with self.assertRaises(p06.Denied):s.proposed(source,self.prelabel)
    def test_reject_other_source(self):
        source=copy.deepcopy(self.source)
        source['archive_sha256']='0'*64
        with self.assertRaises(p06.Denied):s.proposed(source,self.prelabel)
    def test_reject_duplicate_p06_case_arm(self):
        x=copy.deepcopy(self.prelabel)
        x['trials'][0]['predictions'][0]=x['trials'][0]['predictions'][1]
        with self.assertRaises(p06.Denied):s.proposed(self.source,x)
    def test_reject_missing_physical_work_claim(self):
        x=copy.deepcopy(self.prelabel)
        x['original_encoder_new_forward_calls']=1
        with self.assertRaises(p06.Denied):s.proposed(self.source,x)
    def test_filesystem_genuine_roundtrip_and_symlink_denial(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);d.chmod(0o700)
            proposal=d/'shadow.json';seal=d/'seal.json'
            original_sha=s.record(RUN/'source.json',RUN/'prelabel.json',
                   RUN/'prelabel-seal.json',proposal,seal)['shadow_sha256']
            self.assertEqual(original_sha,p06.json_read(seal)['shadow_file_sha256'])
            self.assertEqual(proposal.stat().st_mode&0o777,0o600)
            with self.assertRaises(FileExistsError):
                s.record(RUN/'source.json',RUN/'prelabel.json',RUN/'prelabel-seal.json',proposal,seal)
            link=d/'shadow-symlink.json';link.symlink_to(proposal)
            with self.assertRaises(OSError):
                s._sealed_shadow(RUN/'source.json',RUN/'prelabel.json',
                                 RUN/'prelabel-seal.json',link,seal)
    def test_invalid_shadow_seal_refused_before_gold(self):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t);d.chmod(0o700)
            proposal=d/'shadow.json';seal=d/'seal.json'
            s.record(RUN/'source.json',RUN/'prelabel.json',RUN/'prelabel-seal.json',proposal,seal)
            ss=p06.json_read(seal);ss['registered_policy_sha256']='f'*64
            altered=d/'wrong-seal.json';p06.write_private(altered,ss)
            with self.assertRaises(p06.Denied):
                s._sealed_shadow(RUN/'source.json',RUN/'prelabel.json',RUN/'prelabel-seal.json',proposal,altered)
    def test_actual_original_full_numerical_review_is_negative(self):
        if not (RUN/'shadow.json').is_file():
            self.skipTest('separate process shadow artefact not available')
        r=s.score(ORIGINAL,RUN/'source.json',RUN/'prelabel.json',RUN/'prelabel-seal.json',
                  RUN/'shadow.json',RUN/'shadow-seal.json')
        self.assertEqual([r['results'][str(k)]['correct_when_abstentions_count_as_incorrect']
                          for k in p06.SEEDS],[22,20,20])
        self.assertEqual([r['results'][str(k)]['centroid_reference_correct']
                          for k in p06.SEEDS],[28,28,28])
        self.assertEqual(r['disposition'],'HOLD_NO_GO')
        self.assertFalse(r['incremental_execution_latency_or_energy_measured'])

if __name__=='__main__':unittest.main()
