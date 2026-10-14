"""Pinned real-run identity mechanics; no model-origin or FinalUse claims."""
from __future__ import annotations
import copy
import unittest
from historical_head_anchor import (
    HISTORICAL, HistoricalIdentityError, check_values, check_reports,
)


def matched_args():
    return {
        'original_panel_digest': HISTORICAL['original_panel_digest'],
        'gemma_revision': HISTORICAL['gemma_revision'],
        'stem_digest': HISTORICAL['gemma_stem_digest'],
        'frozen_head_digest': HISTORICAL['frozen_head_digest'],
        'trained_head_digest': HISTORICAL['trained_head_digest'],
        'head_parameters': HISTORICAL['head_parameters'],
        'head_optimizer_steps': HISTORICAL['head_optimizer_steps'],
        'training_seed': HISTORICAL['training_seed'],
    }


def matched_reports():
    common = dict(backend='google/embeddinggemma-2',
                  revision=HISTORICAL['gemma_revision'],
                  stem_digest=HISTORICAL['gemma_stem_digest'],
                  head_parameters=HISTORICAL['head_parameters'])
    gemma = [
        dict(arm_id='gemma2_frozen_head', metadata={**common,
                'optimizer_steps':0,'head_artifact_digest':HISTORICAL['frozen_head_digest']}),
        dict(arm_id='gemma2_trained_head', metadata={**common,
                'optimizer_steps':40,'head_artifact_digest':HISTORICAL['trained_head_digest']}),
    ]
    laya = dict(metadata={'revision':HISTORICAL['laya_revision'],
                          'model_parameter_count':HISTORICAL['laya_parameters'],
                          'trainable_parameters':0})
    return gemma, laya


class HistoricalArtifactIdentity(unittest.TestCase):
    def test_reference_must_retain_exact_historical_weights(self):
        checked=check_values(**matched_args())
        self.assertEqual(checked['executed_reference_run'],38521871187)
        self.assertEqual(checked['production_promotion'],'DENY_ALL')
        self.assertFalse(checked['model_origin_independently_authenticated'])
        gemma,laya=matched_reports()
        self.assertTrue(check_reports(
            original_panel_digest=HISTORICAL['original_panel_digest'],
            original_gemma=gemma,original_laya=laya)['reference_local_tensor_lineage_matched'])

    def test_changed_training_seed_rank_or_model_digest_rejected(self):
        changes={'original_panel_digest':'0'*64,
                 'gemma_revision':'f'*40,
                 'stem_digest':'e'*64,
                 'frozen_head_digest':'e'*64,
                 'trained_head_digest':'e'*64,
                 'head_parameters':2000,
                 'head_optimizer_steps':41,
                 'training_seed':11}
        for key,value in changes.items():
            args=matched_args();args[key]=value
            with self.subTest(key=key),self.assertRaises(HistoricalIdentityError):
                check_values(**args)

    def test_report_aliases_and_model_replacement_rejected(self):
        for kind in ('fake_laya','wrong_laya_size','extra_arm','wrong_step',
                     'stem_drift','head_swap'):
            gemma,laya=matched_reports()
            if kind=='fake_laya':laya['metadata']['revision']='f'*40
            elif kind=='wrong_laya_size':laya['metadata']['model_parameter_count']=400000001
            elif kind=='extra_arm':gemma.append(copy.deepcopy(gemma[0]))
            elif kind=='wrong_step':gemma[1]['metadata']['optimizer_steps']=41
            elif kind=='stem_drift':gemma[0]['metadata']['stem_digest']='f'*64
            else:gemma[1]['metadata']['head_artifact_digest']='f'*64
            with self.subTest(kind=kind),self.assertRaises(HistoricalIdentityError):
                check_reports(original_panel_digest=HISTORICAL['original_panel_digest'],
                              original_gemma=gemma,original_laya=laya)

    def test_real_val2_retraining_drift_does_not_pass_exact_head_gate(self):
        # An actual earlier val2 run produced a different Q24 candidate digest,
        # despite the same Stem and frozen Head. Never silently relabel it as
        # an exact historical checkpoint replay.
        changed = matched_args()
        changed["trained_head_digest"] = (
            "bcebc80c25c36256199e72ac30b99a2907d55e18aed11950d10da720a61aab18")
        with self.assertRaisesRegex(HistoricalIdentityError, "trained_head_digest"):
            check_values(**changed)

    def test_historical_constant_identity_is_stable(self):
        self.assertEqual(HISTORICAL['source_commit'],
                         '1f231584124e62a11cf932d937ea4a7ad2437ab2')
        self.assertEqual(HISTORICAL['archived_zip_sha256'],
                         'cbedc87a883b34bc26447fab73f425469a3baa1f76afb35361abb0a446bda75d')

if __name__=='__main__':unittest.main()
