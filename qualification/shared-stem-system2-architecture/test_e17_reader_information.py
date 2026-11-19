"""E17 real original ModernBERT+Reader source-bound read-only diagnostics.

All tests parse actual pinned pretrained logits. No genuine human label vector
is ever sent to the blind producer. The old scored receipt is read by the
independent *post-seal* reviewer, never by the blind diagnostic.
"""
from __future__ import annotations

import copy
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from e14_multirc_route import read_prelabel
import e17_reader_signal as blind
import e17_independent_review as independent

SOURCE = os.environ.get('HEPTA_E17_REAL_ARCHIVE', '/mnt/data/hepta-artifact-11946621518.zip')


class OriginalInformationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.obs = read_prelabel(SOURCE)
        cls.report = blind.analyze_observation(cls.obs)

    def _sealed_review(self, change=None):
        with TemporaryDirectory() as td:
            rec = copy.deepcopy(self.report)
            if change is not None:
                change(rec)
            out = Path(td)/'blind.json'
            out.write_text(json.dumps(rec, separators=(',', ':'), sort_keys=True)+'\n')
            sha = sha256(out.read_bytes()).hexdigest()
            dst = str(Path(td)/'review.json')
            result = independent.review(SOURCE, str(out), sha, dst)
            self.assertEqual(result, sha256(Path(dst).read_bytes()).hexdigest())
            return json.loads(Path(dst).read_text())

    def test_01_actual_complete_original_source(self):
        self.assertEqual((len(self.obs['rows']), len(self.report['questions'])), (33, 8))
        self.assertEqual(len({q['source_group'] for q in self.report['questions']}), 4)
        self.assertEqual(sum(q['candidate_count'] for q in self.report['questions']), 33)
        self.assertEqual(self.report['new_pretrained_model_forwards'], 0)

    def test_02_no_query_exactly_invariant_every_question(self):
        q = self.report['summary']['no_query']
        self.assertEqual(q['exactly_invariant_questions'], 8)
        self.assertEqual(q['near_invariant_questions_descriptive'], 8)
        self.assertEqual(q['one_hard_prediction_per_question'], 8)
        self.assertEqual(q['max_probability_span'], 0)

    def test_03_conditioned_weak_variation_original_model(self):
        q=self.report['summary']['conditioned']
        self.assertEqual(q['exactly_invariant_questions'], 4)
        self.assertEqual(q['near_invariant_questions_descriptive'], 8)
        self.assertEqual(q['one_hard_prediction_per_question'], 8)
        self.assertLess(q['max_probability_span'], .001)

    def test_04_other_original_readers_real_candidate_dependence(self):
        self.assertEqual(self.report['summary']['mean_pool_query_fused']['exactly_invariant_questions'], 0)
        self.assertEqual(self.report['summary']['no_evidence']['exactly_invariant_questions'], 0)
        self.assertEqual(self.report['summary']['mean_pool_query_fused']['one_hard_prediction_per_question'], 8)
        self.assertEqual(self.report['summary']['no_evidence']['one_hard_prediction_per_question'], 7)

    def test_05_all_original_candidate_pairs_census(self):
        from math import comb
        expected=sum(comb(q['candidate_count'], 2) for q in self.report['questions'])
        self.assertTrue(expected > 0)
        for arm in self.report['summary']:
            self.assertEqual(self.report['summary'][arm]['total_within_question_pairs'], expected)
        self.assertEqual(self.report['summary']['no_query']['equal_margin_answer_pairs'], expected)

    def test_06_blind_excludes_original_score_zip_bytes(self):
        original = ZipFile.read
        seen=[]
        def spy(instance,name,*args,**kwargs):
            seen.append(name)
            return original(instance,name,*args,**kwargs)
        with patch.object(ZipFile,'read',spy):
            obs=read_prelabel(SOURCE)
            blind.analyze_observation(obs)
        self.assertEqual(set(seen),{
            'multirc-native-candidate-audit/audit.json',
            'multirc-native-candidate-audit/COMMITTED.json'})

    def test_07_independent_historical_human_mixed_labels_not_new_truth(self):
        r=self._sealed_review()
        self.assertEqual(r['original_human_source_groups_with_both_labels'], 8)
        self.assertEqual(r['no_query_frozen_reader_complete_question_correct_bound'], 0)
        self.assertFalse(r['no_query_candidate_invariant_head_can_complete_mixed_question'])
        self.assertTrue(r['original_human_labels_not_independently_resigned'])
        self.assertFalse(r['e15_e16_heldout_human_success_observed'])
        self.assertFalse(r['full_fbsde_utility_advantage_established'])

    def test_08_blind_write_once_and_exact_sha(self):
        with TemporaryDirectory() as td:
            f=Path(td)/'blind.json'
            digest=blind.produce(SOURCE,str(f))
            self.assertEqual(sha256(f.read_bytes()).hexdigest(),digest)
            with self.assertRaises(FileExistsError):blind.produce(SOURCE,str(f))

    def test_09_wrong_archive_fails_before_model_forward(self):
        with TemporaryDirectory() as td:
            bad=Path(td)/'fake.zip'
            bad.write_bytes(Path(SOURCE).read_bytes()+b'garbage')
            with self.assertRaises(ValueError):blind.produce(str(bad),str(Path(td)/'out.json'))

    def test_10_missing_original_candidate_is_invalid(self):
        bad=copy.deepcopy(self.obs)
        bad['rows'].pop()
        with self.assertRaises(ValueError):blind.analyze_observation(bad)

    def test_11_forged_margin_source_identity_rejected(self):
        bad=copy.deepcopy(self.obs)
        bad['predictions']['conditioned'][0]['task_id']='fabricated'
        with self.assertRaises(ValueError):blind.analyze_observation(bad)

    def test_12_corrupt_blind_question_spans_fail_even_with_new_sha(self):
        def mutate(r):r['questions'][0]['arms']['conditioned']['probability_span']+=.01
        with self.assertRaises(ValueError):self._sealed_review(mutate)

    def test_13_corrupt_summary_fails_even_with_new_sha(self):
        def mutate(r):r['summary']['no_query']['exactly_invariant_questions']=0
        with self.assertRaises(ValueError):self._sealed_review(mutate)

    def test_14_forbidden_go_flag_fails_even_with_new_sha(self):
        def mutate(r):r['production_accepted']=True
        with self.assertRaises(ValueError):self._sealed_review(mutate)

    def test_15_wrong_claim_of_prior_label_access_fails(self):
        def mutate(r):r['human_labels_opened_in_blind_stage']=True
        with self.assertRaises(ValueError):self._sealed_review(mutate)

    def test_16_changed_blind_file_without_new_sha_rejects(self):
        with TemporaryDirectory() as td:
            f=Path(td)/'blind.json'
            sha=blind.produce(SOURCE,str(f))
            f.write_bytes(f.read_bytes()+b' ')
            with self.assertRaises(ValueError):independent.review(SOURCE,str(f),sha,str(Path(td)/'score.json'))

    def test_17_unknown_critical_field_rejected_after_rehash(self):
        def mutate(r):r['unauthorized_online_policy'] = True
        with self.assertRaises(ValueError):self._sealed_review(mutate)

    def test_18_false_zero_forward_count_not_accepted_as_integer(self):
        def mutate(r):r['new_pretrained_model_forwards'] = False
        with self.assertRaises(ValueError):self._sealed_review(mutate)

    def test_19_no_new_training_or_system2_authority(self):
        self.assertFalse(self.report['same_question_answer_invariance_qualifies_system2'])
        self.assertFalse(self.report['model_selected'])
        self.assertFalse(self.report['production_accepted'])
        self.assertTrue(self.report['low_answer_variation_is_not_a_proof_of_no_useful_information'])


if __name__=='__main__':
    unittest.main()
