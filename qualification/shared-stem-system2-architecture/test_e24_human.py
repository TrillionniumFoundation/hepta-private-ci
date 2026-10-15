"""Actual ORIGINAL MultiRC label-owner postseal research; never a blind-stage test."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import unittest

from e14_multirc_route import read_prelabel, write_once
from e24_question_risk import fit_one, blind_identity, METHODS
from e24_independent_review import reviewer,strict_document,reference_features,reference_train,ref_predict
from e23_original_owner_question_gate import E15_OWNERS,E16_OWNERS,original_owner_labels
from e21_whole_question import signflip_p


def input_paths():
    def req(name):
        value=os.environ.get(name)
        if not value or not Path(value).is_file():
            raise RuntimeError('Original, SHA-locked source missing: '+name)
        return value
    original=req('HEPTA_E24_ORIGINAL') if os.environ.get('HEPTA_E24_ORIGINAL') else req('HEPTA_E23_ORIGINAL')
    owners15=[req(f'HEPTA_E23_E15_OWNER_{i}') for i in range(4)]
    owners16=[req(f'HEPTA_E23_E16_OWNER_{i}') for i in range(4)]
    return original,owners15,owners16


class E24OriginalHumanContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src,cls.owner15,cls.owner16=input_paths()
        cls.obs=read_prelabel(cls.src)
        cls.labels,_=original_owner_labels(cls.obs,cls.owner15,E15_OWNERS,name='E15_original_owner')
        cls.other,_=original_owner_labels(cls.obs,cls.owner16,E16_OWNERS,name='E16_original_owner')
        cls.temp=TemporaryDirectory()
        cls.tmp=Path(cls.temp.name)
        cls.blind=cls.tmp/'blind.json'
        write_once(str(cls.blind),blind_identity(cls.obs))
        cls.files=[];cls.shas=[]
        from zipfile import ZipFile
        for i in range(4):
            with ZipFile(cls.owner15[i]) as z:mat=json.loads(z.read(f'training-fold-{i}.json'))
            out=fit_one(cls.obs,mat)
            path=cls.tmp/f'held-{i}.json'
            cls.shas.append(write_once(str(path),out));cls.files.append(str(path))
        cls.review=reviewer(cls.src,str(cls.blind),cls.files,cls.shas,cls.owner15,cls.owner16)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def invoke(self,files=None,shas=None,owner15=None,owner16=None,blind=None):
        return reviewer(self.src,str(blind or self.blind),files or self.files,shas or self.shas,
                        owner15 or self.owner15,owner16 or self.owner16)

    def test_01_two_original_label_owners_replay_same_33_human_labels(self):
        self.assertEqual(self.labels,self.other)
        self.assertEqual(len(self.labels),33)
        self.assertEqual(set(self.labels),{r['task_id'] for r in self.obs['rows']})

    def test_02_all_eight_original_questions_have_true_and_false_candidates(self):
        q={}
        for r in self.obs['rows']:
            q.setdefault((r['source_group'],r['question_slot']),set()).add(self.labels[r['task_id']])
        self.assertEqual(len(q),8)
        self.assertEqual(set(map(tuple,map(sorted,q.values()))),{(0,1)})

    def test_03_true_original_E16_brier_numerically_replayed(self):
        baseline=self.review['results'][METHODS[0]]
        self.assertEqual(baseline['correct'],20)
        self.assertAlmostEqual(baseline['brier'],.4679101347990239,delta=1e-11)
        self.assertEqual(baseline['complete_questions'],0)

    def test_04_new_exploratory_low_tau_whole_questions(self):
        self.assertEqual([(m,self.review['results'][m]['correct'],
                           self.review['results'][m]['complete_questions']) for m in METHODS],
                         [(METHODS[0],20,0),(METHODS[1],21,2),(METHODS[2],19,1),(METHODS[3],19,0)])

    def test_05_brier_and_question_success_tradeoff_not_hidden(self):
        r=self.review['results']
        self.assertGreater(r[METHODS[1]]['brier'],r[METHODS[0]]['brier'])
        self.assertLess(r[METHODS[3]]['brier'],r[METHODS[0]]['brier'])
        self.assertEqual(sum(r[METHODS[1]]['by_question'].values()),2)
        self.assertEqual(r[METHODS[1]]['complete_passages'],0)

    def test_06_fourfold_true_label_sgd_weights_and_pred_replayed(self):
        self.assertEqual(len(self.review['four_original_real_SGD_holdout_replays']),4)
        self.assertTrue(all(x['independent_original_label_replay'] for x in self.review['four_original_real_SGD_holdout_replays']))

    def test_07_exact_same_five_parameters_and_48_updates(self):
        for r in self.review['four_original_real_SGD_holdout_replays']:
            self.assertEqual(r['full_training_question_count'],6)
        self.assertTrue(all(x>0 for x in self.review['physical_local_Python_CPU_ns_not_target_hardware']['train'].values()))

    def test_08_source_is_one_family_and_temperature_grid_is_posthoc(self):
        self.assertTrue(self.review['source_family_reused_after_prior_analysis'])
        self.assertTrue(self.review['all_group_loss_variants_exploratory_not_prospectively_preregistered'])
        self.assertFalse(self.review['statistical_superiority_or_independent_future_benefit'])
        self.assertFalse(self.review['original_human_parquet_reopened'])

    def test_09_no_model_or_system2_or_full_service_authority(self):
        for key in ('production_accepted','model_selected','system2_fbsde_permitted',
                    'complete_question_task_ready_for_production',
                    'full_online_source_and_model_cost_measured'):
            self.assertIs(self.review[key],False)

    def test_10_excluding_original_fold_rejected(self):
        with self.assertRaises(ValueError):self.invoke(files=self.files[:3])
        with self.assertRaises(ValueError):self.invoke(shas=self.shas[:3])

    def test_11_original_train_only_owner_zip_byte_tamper_rejected(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'forged.zip';p.write_bytes(Path(self.owner15[0]).read_bytes()+b'x')
            bad=[str(p)]+self.owner15[1:]
            with self.assertRaises(ValueError):self.invoke(owner15=bad)

    def test_12_original_owner_disjoint_split_swap_rejected(self):
        bad=self.owner16[:];bad[2]=bad[1]
        with self.assertRaises(ValueError):self.invoke(owner16=bad)

    def test_13_changed_held_predictions_with_resealed_sha_rejected(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'forged.json';a=json.loads(Path(self.files[0]).read_text())
            a['held_predictions'][0]['probabilities'][METHODS[1]]+=.07
            p.write_text(json.dumps(a));bad=[str(p)]+self.files[1:]
            hashes=[sha256(p.read_bytes()).hexdigest()]+self.shas[1:]
            with self.assertRaisesRegex(ValueError,'probability'):
                self.invoke(files=bad,shas=hashes)

    def test_14_changed_HUMAN_train_weights_rejected_even_if_sealed(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'w.json';a=json.loads(Path(self.files[1]).read_text())
            a['weights'][METHODS[1]][1]+=.01
            p.write_text(json.dumps(a));bad=self.files[:];bad[1]=str(p)
            hashes=self.shas[:];hashes[1]=sha256(p.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError,'weights'):
                self.invoke(files=bad,shas=hashes)

    def test_15_false_training_meter_rejected(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'meter.json';a=json.loads(Path(self.files[1]).read_text())
            a['meters'][METHODS[2]]['optimizer_updates']=0
            p.write_text(json.dumps(a));bad=self.files[:];bad[1]=str(p)
            hashes=self.shas[:];hashes[1]=sha256(p.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError,'compute|cost'):
                self.invoke(files=bad,shas=hashes)

    def test_16_false_system2_promotion_rejected(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'promo.json';a=json.loads(Path(self.files[0]).read_text())
            a['incremental_system2_admitted']=True
            p.write_text(json.dumps(a));bad=self.files[:];bad[0]=str(p)
            hashes=self.shas[:];hashes[0]=sha256(p.read_bytes()).hexdigest()
            with self.assertRaises(ValueError):self.invoke(files=bad,shas=hashes)

    def test_17_unknown_source_fields_rejected(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'rogue.json';a=json.loads(Path(self.files[0]).read_text())
            a['original_untrusted_label_from_held']=1
            p.write_text(json.dumps(a));bad=self.files[:];bad[0]=str(p)
            hashes=self.shas[:];hashes[0]=sha256(p.read_bytes()).hexdigest()
            with self.assertRaises(ValueError):self.invoke(files=bad,shas=hashes)

    def test_18_blind_prelabel_changed_even_if_sha_recomputed_rejected(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/'blind.json';a=json.loads(self.blind.read_text());a['new_pretrained_forwards']=1
            p.write_text(json.dumps(a))
            with self.assertRaises(ValueError):self.invoke(blind=p)

    def test_19_cross_source_complete_questions_do_not_disappear(self):
        arm=self.review['results'][METHODS[1]]
        self.assertEqual(len(arm['by_question']),8)
        self.assertEqual(sum(arm['by_question'].values()),2)
        self.assertEqual(len(arm['by_passage']),4)
        self.assertEqual(sum(arm['by_passage'].values()),0)

    def test_20_no_new_authenticated_human_observer(self):
        self.assertTrue(self.review['original_owner_source_not_independent_human_signer'])
        self.assertEqual(self.review['original_validation_parquet_sha256'],
                         '5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada')

if __name__=='__main__':unittest.main()
