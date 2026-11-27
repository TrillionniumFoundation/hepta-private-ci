"""E18 original pretrained archive numerical replay and adversarial deny-all tests."""
from __future__ import annotations

import copy
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from e14_multirc_route import ARMS, read_prelabel
from e18_precision_boundary import PROFILES, analyze, produce, projected
from e18_independent_precision_review import (audit_original, independent_quantize,
                                              review)


class E18RealArchiveQualification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive = os.environ.get('HEPTA_E18_ORIGINAL_ARCHIVE', '/mnt/data/hepta-artifact-11946621518.zip')
        # A missing original zip is failure, never synthetic fallback or skip.
        cls.original = read_prelabel(cls.archive)
        cls.blind = analyze(cls.original)

    def test_original_33_candidate_four_passage_eight_question_census(self):
        self.assertEqual((self.blind['original_candidates'], self.blind['original_questions'],
                          self.blind['original_passages']), (33, 8, 4))
        self.assertEqual(sum(q['candidate_count'] for q in self.blind['question_rows']), 33)
        self.assertEqual(len(set(q['source_group'] for q in self.blind['question_rows'])), 4)
        self.assertEqual(self.blind['authority'], 'DENY_ALL')

    def test_real_pretrained_conditioned_profile_collapse(self):
        expected = dict(original_fp32=4, q24_rne=4, fp16_rne=6, bf16_rne=8)
        for profile, amount in expected.items():
            self.assertEqual(self.blind['summary']['conditioned'][profile]
                             ['questions_exactly_candidate_invariant'], amount)
        self.assertEqual(self.blind['summary']['conditioned']['bf16_rne']
                         ['equal_margin_candidate_pairs'], 55)

    def test_three_other_reader_negative_and_positive_controls(self):
        for profile in PROFILES:
            self.assertEqual(self.blind['summary']['no_query'][profile]
                             ['questions_exactly_candidate_invariant'], 8)
            self.assertEqual(self.blind['summary']['mean_pool_query_fused'][profile]
                             ['questions_exactly_candidate_invariant'], 0)
            self.assertEqual(self.blind['summary']['no_evidence'][profile]
                             ['questions_exactly_candidate_invariant'], 0)

    def test_all_original_logits_independent_rounding_parity(self):
        n = 0
        for arm in ARMS:
            for candidate in self.original['predictions'][arm]:
                for logit in candidate['logits']:
                    for profile in PROFILES:
                        self.assertEqual(projected(logit, profile),
                                         independent_quantize(logit, profile))
                        n += 1
        self.assertEqual(n, 33*4*2*4)

    def test_ieee_bfloat16_even_tie_rounding(self):
        self.assertEqual(projected(1+2**-8,'bf16_rne'),1.0)
        self.assertEqual(projected(1+3*2**-8,'bf16_rne'),1+2**-6)
        self.assertEqual(projected(-1-2**-8,'bf16_rne'),-1.0)
        self.assertEqual(projected(-1-3*2**-8,'bf16_rne'),-1-2**-6)

    def test_ieee_half_even_tie_rounding(self):
        self.assertEqual(projected(1+2**-11,'fp16_rne'),1.0)
        self.assertEqual(projected(1+3*2**-11,'fp16_rne'),1+2**-9)

    def test_q24_even_ties(self):
        self.assertEqual(projected(2**-25,'q24_rne'),0)
        self.assertEqual(projected(3*2**-25,'q24_rne'),2**-23)
        self.assertEqual(projected(-3*2**-25,'q24_rne'),-2**-23)

    def test_fail_on_unregistered_or_unrepresentable_number(self):
        for bad in [float('inf'), float('nan'), 9, True, 0.1, '1', None]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                projected(bad,'bf16_rne')
        with self.assertRaises(ValueError):
            projected(0.0,'bf16/invalid')

    def test_independent_second_algorithm_recomputes_source_and_all_fields(self):
        actual = audit_original(self.original, self.blind)
        self.assertEqual(actual['conditioned']['bf16_rne']['invariant'],8)
        self.assertEqual(actual['conditioned']['original_fp32']['invariant'],4)

    def test_reject_forged_quantization_summary(self):
        bad = copy.deepcopy(self.blind)
        bad['summary']['conditioned']['bf16_rne']['questions_exactly_candidate_invariant'] = 7
        with self.assertRaises(ValueError):
            audit_original(self.original,bad)

    def test_reject_changed_raw_precision_contrast(self):
        bad = copy.deepcopy(self.blind)
        bad['question_rows'][0]['arms']['conditioned']['original_fp32']['max_signed_margin_span'] += 0.01
        with self.assertRaises(ValueError):
            audit_original(self.original,bad)

    def test_reject_after_self_rehash_unknown_authority_field(self):
        for key,value in [('authorized',True),('production_accepted',1),('model_selected',1),
                          ('pretrained_model_new_forward_count',False)]:
            with self.subTest(key=key):
                bad = copy.deepcopy(self.blind)
                bad[key] = value
                with self.assertRaises(ValueError):
                    audit_original(self.original,bad)

    def test_reject_changed_source_identity_and_production_flag(self):
        for key,value in [('original_pretrained_observation_id','0'*64),
                          ('archive_sha256','0'*64),('precision_profiles',list(reversed(PROFILES))),
                          ('post_logit_projection_not_reexecuted_bf16_fp16_encoder',False)]:
            with self.subTest(key=key):
                bad=copy.deepcopy(self.blind)
                bad[key]=value
                with self.assertRaises(ValueError):audit_original(self.original,bad)

    def test_reject_missing_candidate_rows(self):
        bad = copy.deepcopy(self.blind)
        bad['question_rows'].pop()
        with self.assertRaises(ValueError):
            audit_original(self.original,bad)

    def test_reject_forged_equal_pair_count(self):
        bad = copy.deepcopy(self.blind)
        bad['question_rows'][0]['arms']['no_query']['bf16_rne']['equal_margin_candidate_pairs'] -= 1
        with self.assertRaises(ValueError):
            audit_original(self.original,bad)

    def test_reject_nonoriginal_archive_and_missing_source(self):
        with self.assertRaises(ValueError):read_prelabel('/tmp/nonexistent-e18-archive.zip')
        with TemporaryDirectory() as tmp:
            p = Path(tmp)/'mutated.zip'
            p.write_bytes(Path(self.archive).read_bytes() + b'forgery')
            with self.assertRaises(ValueError):read_prelabel(str(p))

    def test_read_original_scored_human_receipt_only_after_create_only_seal(self):
        with TemporaryDirectory() as tmp:
            blind=Path(tmp)/'blind.json'; outcome=Path(tmp)/'review.json'
            digest=produce(self.archive,str(blind))
            self.assertEqual(digest,sha256(blind.read_bytes()).hexdigest())
            assert not outcome.exists()
            review_digest=review(self.archive,str(blind),digest,str(outcome))
            result=json.loads(outcome.read_text())
            self.assertEqual(review_digest,sha256(outcome.read_bytes()).hexdigest())
            self.assertEqual(result['original_questions_with_mixed_human_labels'],8)
            self.assertFalse(result['model_selected'])
            self.assertFalse(result['online_FBSDE_net_gain_established'])
            self.assertTrue(result['bf16_postlogit_not_equal_actual_bf16_weight_execution'])
            self.assertTrue(result['bf16_postlogit_conditioned_deterministic_margin_only_cannot_finish_eight_mixed_questions'])

    def test_reject_changed_seal_bytes_even_when_source_json_semantics_same(self):
        with TemporaryDirectory() as tmp:
            blind=Path(tmp)/'blind.json';out=Path(tmp)/'out.json'
            original_digest=produce(self.archive,str(blind))
            blind.write_bytes(blind.read_bytes()+b'\n')
            with self.assertRaises(ValueError):
                review(self.archive,str(blind),original_digest,str(out))

    def test_prevent_overwrite_of_create_only_prediction_and_score(self):
        with TemporaryDirectory() as tmp:
            blind=Path(tmp)/'blind.json';out=Path(tmp)/'out.json'
            digest=produce(self.archive,str(blind))
            with self.assertRaises(FileExistsError):produce(self.archive,str(blind))
            review(self.archive,str(blind),digest,str(out))
            with self.assertRaises(FileExistsError):review(self.archive,str(blind),digest,str(out))

    def test_hold_original_scored_archive_as_negative_not_selection(self):
        with TemporaryDirectory() as tmp:
            blind=Path(tmp)/'blind.json';out=Path(tmp)/'out.json'
            digest=produce(self.archive,str(blind))
            review(self.archive,str(blind),digest,str(out))
            result=json.loads(out.read_text())
            self.assertFalse(result['original_human_label_signer_authenticated'])
            self.assertFalse(result['prospective_learning_improvement'])
            self.assertFalse(result['production_accepted'])
            self.assertFalse(result['original_q24_profile_not_actual_worker_q24_receipt'] is False)


if __name__ == '__main__':unittest.main()
