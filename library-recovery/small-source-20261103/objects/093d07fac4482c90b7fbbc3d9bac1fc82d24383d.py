"""Offline guard tests on exact original, incomplete P0 original two-encoder study.
No owner-held labels, model publisher attestation or NDU acceptance.
"""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

from actual_feature_head_shadow_v1 import (
    E1_SOURCE_GIT_BLOB, MODELS, ORIGINAL_SHA256, SCHEMA, SOURCE_GITHUB_RUN,
    SOURCE_HEAD, Invalid, execute, load_existing_probe, parse_source,
    source_indices, verify_archive, zip_read,
)

ROOT = Path(__file__).resolve().parent
SOURCE = Path(os.environ.get('HEPTA_ORIGINAL_ARTIFACT_ROOT', ROOT))


def actual_source():
    fit = parse_source(zip_read(verify_archive(SOURCE,'p0_multirc_fit_38868208650.zip'),'fit.json'))
    blind = parse_source(zip_read(verify_archive(SOURCE,'p0_multirc_blind_38868208650.zip'),'blind.json'))
    return fit,blind


class P0PartialActualGatedShadowChecks(unittest.TestCase):
    def test_frozen_original_blob_identity(self):
        e1=load_existing_probe(SOURCE)
        self.assertEqual(e1.PARAMETERS,4145)
        self.assertEqual(e1.STEPS,40)
        self.assertEqual(e1.SEEDS,(41,47,53))
        self.assertEqual(len(E1_SOURCE_GIT_BLOB),40)

    def test_outer_zip_bytes_match_immutable_original(self):
        for name,digest in ORIGINAL_SHA256.items():
            with self.subTest(name=name):
                self.assertEqual(len(digest),64)
                self.assertEqual(verify_archive(SOURCE,name).name,name)

    def test_wrong_model_or_missing_file_rejected(self):
        with self.assertRaises(Invalid):verify_archive(SOURCE,'owner-only-human-labels.zip')
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(Invalid):verify_archive(Path(temp),'p0_multirc_fit_38868208650.zip')

    def test_bad_original_archive_bytes_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'p0_multirc_fit_38868208650.zip'
            path.write_bytes((SOURCE/path.name).read_bytes()+b'bad')
            with self.assertRaises(Invalid):verify_archive(Path(temp),path.name)

    def test_symlink_to_original_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            link=Path(temp)/'p0_multirc_fit_38868208650.zip'
            link.symlink_to(SOURCE/link.name)
            with self.assertRaises(Invalid):verify_archive(Path(temp),link.name)

    def test_unlabeled_exact_split_census(self):
        fit,blind=actual_source()
        train,cal,held,pairs=source_indices(fit,blind)
        self.assertEqual([len(train),len(cal),len(held),len(pairs)],[91,32,116,58])
        self.assertEqual(sum(fit['cases'][i]['label'] for i in train),32)
        self.assertEqual(sum(fit['cases'][i]['label'] for i in cal),16)
        self.assertFalse(any('label' in r for r in blind['cases']))

    def test_fake_held_label_rejected(self):
        fit,blind=actual_source()
        blind['cases'][0]['label']=1
        with self.assertRaises(Invalid):source_indices(fit,blind)

    def test_cross_split_source_group_rejected(self):
        fit,blind=actual_source()
        blind['cases'][0]['source_group']=fit['cases'][0]['source_group']
        with self.assertRaises(Invalid):source_indices(fit,blind)

    def test_missing_pair_control_rejected(self):
        fit,blind=actual_source()
        blind['cases'][0]['condition']='missing'
        with self.assertRaises(Invalid):source_indices(fit,blind)

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaises(Invalid):parse_source(b'{"model":1,"model":2}')

    def test_nonfinite_source_json_rejected(self):
        with self.assertRaises(Invalid):parse_source(b'{"prob":NaN}')

    def test_real_models_only_granite_gemma(self):
        self.assertEqual(set(MODELS),{'granite_97m_r2','embeddinggemma_2_text'})
        self.assertNotIn('mmbert_small',MODELS)

    @classmethod
    def setUpClass(cls):
        # Execute real 2 x 3 x 4 heads once per test mode and reuse bounded
        # numerical receipt. This does not import, call or validate an Encoder.
        cls.real = execute(SOURCE)

    def test_actual_replay_of_original_sources_and_4145_heads(self):
        r=self.real
        self.assertEqual(r['schema'],SCHEMA)
        self.assertEqual(r['original_actions_run_id'],SOURCE_GITHUB_RUN)
        self.assertEqual(r['original_source_commit_sha'],SOURCE_HEAD)
        self.assertEqual(r['authority'],'DENY_ALL')
        self.assertFalse(r['complete_original_four_stem_gate_satisfied'])
        self.assertFalse(r['original_human_held_labels_accessed'])
        self.assertFalse(r['original_encoder_freshly_loaded_or_reforwarded_in_this_shadow'])
        self.assertFalse(r['production_finaluse_granted'])
        for model,info in r['models'].items():
            with self.subTest(model=model):
                self.assertEqual(info['original_P0_head_predictions_independently_replayed'],348)
                self.assertEqual(info['new_pretrained_encoder_model_loads'],0)
                self.assertEqual(info['new_pretrained_encoder_forward_passes'],0)
                self.assertEqual(info['head_per_cell_fp32_parameter_bytes'],16580)
                self.assertEqual(len(info['arms']),12)

    def test_training_changed_all_gated_additive_weights(self):
        for info in self.real['models'].values():
            for row in info['arms']:
                self.assertEqual(row['trained'],row['weights_changed_from_same_seed_initialization'])
                self.assertEqual(row['optimizer_steps'],40 if row['trained'] else 0)
                self.assertEqual(row['parameter_count'],4145)

    def test_actual_trained_calibration_majority_collapse_is_not_hidden(self):
        for model,info in self.real['models'].items():
            for row in info['arms']:
                if row['trained']:
                    with self.subTest(model=model,seed=row['seed'],arm=row['arm']):
                        self.assertEqual(row['calibration_predicted_positive_count_at_0_5'],0)
                        self.assertEqual(row['calibration_observed_positive_count'],16)
                        self.assertEqual(row['calibration_accuracy_optimistically_tuned'],.5)
                        self.assertGreater(row['calibration_brier_optimistically_tuned'],.25)
                        self.assertEqual(len(row['blind_forecast_sha256']),64)

    def test_no_held_test_accuracy_published(self):
        text=json.dumps(self.real,sort_keys=True)
        for forbidden in ('held_test_accuracy','test_label','independent_human_score',
                          'original_human_held_label_value'):
            self.assertNotIn(forbidden,text)
        self.assertTrue(self.real['calibration_accuracies_not_independent_test_scores'])
        self.assertTrue(self.real['calibration_labels_used_for_temperature_selection'])
        for info in self.real['models'].values():
            for row in info['arms']:
                self.assertTrue(0<=row['blind_original_vs_no_evidence_mean_abs_probability_change_without_labels']<=1)


if __name__ == '__main__':
    unittest.main()
