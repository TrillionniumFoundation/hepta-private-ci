"""E22 sealed-human scorer adversarial tests; synthetic labels are NOT results."""
from __future__ import annotations
import copy
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
import e22_e16_question_gate as gate
import e22_independent_human_score as score
from test_e22_blind import originals


class OriginalScoreContract(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source,cls.e15,cls.e16=originals()
        cls.blind=gate.blind_e22(cls.source,cls.e15,cls.e16)

    @staticmethod
    def synthetic_labels(blind):
        seen={};labels={}
        for r in blind['rows']:
            k=(r['source_group'],r['question_slot']);i=seen.get(k,0)
            labels[r['task_id']]=i%2  # Synthetic alternating labels ONLY
            seen[k]=i+1
        return labels

    def test_01_true_original_E16_existing_two_human_score_receipts(self):
        # Already executed independently on GitHub, no E22 improvement claim.
        available=[os.environ.get('HEPTA_E22_E16_SCORE_SOURCE'),os.environ.get('HEPTA_E22_E16_SCORE_MERGE')]
        if any(not p or not Path(p).is_file() for p in available):
            raise ValueError('both exact prior E16 scored original-human ZIPs mandatory')
        observed=[]
        for p,(_,outer,_) in zip(available,score.E16_SCORES):
            raw=score._zip(p,outer,('original-human-e16-centered-result.json',))
            r=score._json_bytes(raw['original-human-e16-centered-result.json'])
            self.assertFalse(r['production_accepted'])
            self.assertEqual(r['results']['centered_scaled_5']['correct'],20)
            self.assertEqual(r['results']['mean_pool_query_fused']['correct'],17)
            observed.append(r['results'])
        self.assertEqual(observed[0],observed[1])

    def test_02_full_original_candidate_question_census_with_SYNTHETIC_truth(self):
        result=score.question_metrics(self.blind,self.synthetic_labels(self.blind))
        self.assertEqual(set(result),set(gate.ALL))
        self.assertTrue(all(r['total']==33 and 0<=r['complete_original_questions']<=8
                            and 0<=r['complete_original_passages']<=4 for r in result.values()))

    def test_03_incomplete_false_or_nan_label_fails(self):
        lab=self.synthetic_labels(self.blind)
        lab.pop(next(iter(lab)))
        with self.assertRaises(ValueError):score.question_metrics(self.blind,lab)
        lab=self.synthetic_labels(self.blind)
        lab[next(iter(lab))]=False
        with self.assertRaises(ValueError):score.question_metrics(self.blind,lab)

    def test_04_malicious_authority_and_unknown_field_rejected(self):
        lab=self.synthetic_labels(self.blind)
        for k,v in (('production_accepted',True),('new_pretrained_forwards',False),
                    ('system2_fbsde_permitted',True),('unknown_production_signer','forged')):
            bad=copy.deepcopy(self.blind);bad[k]=v
            with self.subTest(k=k),self.assertRaises(ValueError):score.question_metrics(bad,lab)

    def test_05_rehashed_original_result_changes_rejected(self):
        lab=self.synthetic_labels(self.blind)
        bad=copy.deepcopy(self.blind)
        bad['rows'][0]['probs']['centered_scaled_5']=0.9
        # A new digest of forged blind predictions MUST still fail independent
        # source-archive reconstruction before even opening human labels.
        with TemporaryDirectory() as temp:
            changed=Path(temp)/'forged-blind.json'
            gate.once(str(changed),bad)
            with self.assertRaisesRegex(ValueError,'blind predictions changed'):
                score.audit(self.source,self.e15,self.e16,str(changed),
                    '/nonexistent/original-human.parquet',[str(changed)]*2,[str(changed)]*2)

    def test_06_probability_nonfloat_or_changed_census_fails(self):
        lab=self.synthetic_labels(self.blind)
        for x in (True,'0.5',float('nan'),-0.2):
            bad=copy.deepcopy(self.blind);bad['rows'][0]['probs']['centered_scaled_5']=x
            with self.assertRaises(ValueError):score.question_metrics(bad,lab)

    def test_07_not_fabricate_complete_success_for_invariant_noquery(self):
        lab=self.synthetic_labels(self.blind)
        metrics=score.question_metrics(self.blind,lab)
        self.assertEqual(metrics['no_query']['complete_original_questions'],0)
        self.assertEqual(metrics['no_query']['complete_original_passages'],0)

    def test_08_absent_ORIGINAL_human_parquet_fails_before_any_score(self):
        with TemporaryDirectory() as temp:
            sealed=Path(temp)/'blind.json'
            gate.once(str(sealed),self.blind)
            with self.assertRaises((ValueError,FileNotFoundError)):
                score.audit(self.source,self.e15,self.e16,str(sealed),
                            str(Path(temp)/'not-a-real-original-validation.parquet'),
                            [str(Path(temp)/'no-e15-score.zip')]*2,
                            [str(Path(temp)/'no-e16-score.zip')]*2)

    def test_09_exact_four_cluster_signflip_descriptive_not_confirmatory(self):
        from e21_whole_question import signflip_p
        self.assertEqual(signflip_p([0,0,0,0]),1)
        self.assertTrue(0<signflip_p([0,3,0,0])<=1)
        with self.assertRaises(ValueError):signflip_p([1,2,3])

    def test_10_score_does_not_introduce_new_predicted_labels(self):
        self.assertTrue(all(set(x['probs'])==set(gate.ALL) for x in self.blind['rows']))
        self.assertFalse(self.blind['human_labels_opened'])
        self.assertEqual(len(self.blind['rows']),33)
