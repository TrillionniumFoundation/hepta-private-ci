"""Adversarial original-source replay on SYNTHETIC publisher-shaped examples."""

import copy
from tempfile import TemporaryDirectory
from pathlib import Path
import json
import unittest

import torch

from e27_reader_owner import execute, material_owner, write_once
from e27_reader_review import score, true_source_roster, exact_sign_test, read_bytes, digest
from test_e27_token_interaction import _raw, FakeSharedEncoder


class OriginalReaderScoreContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.train_rows=[r for i in range(48) for r in _raw(i,'train')]
        cls.val_rows=[r for i in range(8) for r in _raw(i,'validation')]
        cls.train,cls.held,cls.gold,cls.selection=material_owner(cls.train_rows,cls.val_rows)
        cls.observed=execute(cls.train,cls.held,embedder=FakeSharedEncoder())
        # This is a SYNTHETIC SCORE-CONTRACT fixture and explicitly NOT an
        # authentic pretrained Reader; only imitate that boolean for testing
        # downstream schema coverage. Original-model authentication is false.
        cls.observed={**cls.observed,'real_pretrained_encoder':True}

    def test_independent_true_source_identity_and_complete_group_roster(self):
        r=true_source_roster(self.val_rows)
        self.assertEqual(len(r),8)
        self.assertEqual(sum(len(a) for _,qs in r for _,a in qs),48)

    def test_complete_original_synthetic_scores_and_nonclaims(self):
        review=score(self.observed,self.val_rows,trained_source_sha=digest(self.train))
        self.assertEqual(review['results']['aware']['candidate_total'],48)
        self.assertEqual(review['results']['answer_muted']['whole_question_total'],16)
        self.assertEqual(review['results']['aware']['mixed_label_question_count'],16)
        self.assertFalse(review['neural_training_numerically_replayed_independently'])
        self.assertFalse(review['physical_pretrained_origin_signature_verified'])
        self.assertFalse(review['ndu_full_fbsde_gain_established'])
        self.assertFalse(review['production_accepted'])

    def test_forged_source_owner_and_authority_rejected(self):
        for change in ({'authority':'ALLOW'}, {'production_accepted':True},
                       {'held_labels_loaded_during_fit_or_blind':True},
                       {'model_revision':'moving/model-tag'},
                       {'encoder_checkpoint_digest_profile':'0'*64},
                       {'train_material_sha256':'0'*64},
                       {'task_gain_established':True}):
            with self.subTest(change=change):
                out=copy.deepcopy(self.observed)
                out.update(change)
                with self.assertRaises(ValueError):
                    score(out,self.val_rows,trained_source_sha=digest(self.train))

    def test_missing_duplicated_or_ghost_candidates_rejected(self):
        out=copy.deepcopy(self.observed)
        out['predictions']=out['predictions'][:-1]
        with self.assertRaises(ValueError):score(out,self.val_rows)
        out=copy.deepcopy(self.observed)
        out['predictions'][1]=copy.deepcopy(out['predictions'][0])
        with self.assertRaises(ValueError):score(out,self.val_rows)
        out=copy.deepcopy(self.observed)
        out['predictions'][0]['candidate_id']='a'*64
        with self.assertRaises(ValueError):score(out,self.val_rows)

    def test_original_held_text_and_gold_both_independently_replayed(self):
        review=score(self.observed,self.val_rows,trained_source_sha=digest(self.train),
                     held_material=self.held,original_gold=self.gold)
        self.assertEqual(review['results']['aware']['candidate_total'],48)
        swapped=copy.deepcopy(self.held)
        swapped['groups'][0]['questions'][0]['candidates'][0]['text']='counterfeit candidate'
        out=copy.deepcopy(self.observed)
        out['held_material_sha256']=digest(swapped)
        with self.assertRaises(ValueError):
            score(out,self.val_rows,held_material=swapped)
        bad_gold=copy.deepcopy(self.gold)
        bad_gold['cases'][0]['label']=1-bad_gold['cases'][0]['label']
        with self.assertRaises(ValueError):
            score(self.observed,self.val_rows,original_gold=bad_gold)

    def test_unknown_zero_nan_or_fabricated_model_cost_rejected(self):
        for value in (float('nan'),float('inf'),101.0):
            with self.subTest(value=value):
                out=copy.deepcopy(self.observed)
                out['predictions'][0]['logits']['aware']=value
                with self.assertRaises(ValueError):score(out,self.val_rows)
        out=copy.deepcopy(self.observed)
        out['physical_meter']['feature_generation_cpu_ns']=0
        with self.assertRaises(ValueError):score(out,self.val_rows)
        out=copy.deepcopy(self.observed)
        out['shared_encoder_calls']+=1
        with self.assertRaises(ValueError):score(out,self.val_rows)

    def test_forged_unmatched_head_or_training_steps_rejected(self):
        for arm,field,value in [
            ('aware','parameter_count',-1),
            ('answer_muted','optimizer_steps',63),
            ('answer_muted','training_examples',1),
            ('aware','fit_cpu_ns',0),
            ('answer_muted','answer_visible',True),
        ]:
            with self.subTest(arm=arm,field=field):
                out=copy.deepcopy(self.observed)
                out['head_budgets'][arm][field]=value
                with self.assertRaises(ValueError):score(out,self.val_rows)

    def test_true_label_counterfactual_changes_scoring_but_not_route(self):
        before=score(self.observed,self.val_rows)
        rows=copy.deepcopy(self.val_rows)
        for row in rows:row['label']=1-row['label']
        after=score(self.observed,rows)
        self.assertNotEqual(before['results']['aware']['candidate_brier'],
                            after['results']['aware']['candidate_brier'])
        self.assertEqual(before['observed_publisher_source_paragraphs'],
                         after['observed_publisher_source_paragraphs'])
        self.assertEqual(before['blind_semantic_source_digest'],
                         after['blind_semantic_source_digest'])

    def test_label_not_allowed_in_actual_prediction_artifact(self):
        out=copy.deepcopy(self.observed)
        out['predictions'][0]['label']=1
        with self.assertRaises(ValueError):score(out,self.val_rows)

    def test_source_exact_sign_flip_has_no_fake_significance(self):
        self.assertEqual(exact_sign_test([0]*8),1.0)
        self.assertEqual(exact_sign_test([1,1]),0.5)
        self.assertEqual(exact_sign_test([1,-1]),1.0)

    def test_review_strict_json_nonfinite_and_exclusive_write(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'e.json'
            write_once(p,{'authority':'DENY_ALL'})
            self.assertEqual(read_bytes(p)['authority'],'DENY_ALL')
            with self.assertRaises(FileExistsError):write_once(p,{})
            p.write_text('{"number":NaN}')
            with self.assertRaises(ValueError):read_bytes(p)
            p.write_text('{"x":0,"x":1}')
            with self.assertRaises(ValueError):read_bytes(p)

    def test_cross_split_alias_and_original_id_duplicate_rejected(self):
        bad=copy.deepcopy(self.val_rows)
        bad[1]['idx']['answer']=0
        with self.assertRaises(ValueError):true_source_roster(bad)
        out=copy.deepcopy(self.observed)
        out['predictions'][0]['source_group']='0'*64
        with self.assertRaises(ValueError):score(out,self.val_rows)


if __name__=='__main__':unittest.main()
