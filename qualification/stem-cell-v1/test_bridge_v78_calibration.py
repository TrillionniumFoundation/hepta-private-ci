"""Actual originally scored MultiRC source-group controls; no future claim."""
from __future__ import annotations
import copy
from pathlib import Path
import tempfile
import json
import os
import unittest
from bridge_v78_original_calibration import (read_original,group_folds,run,choose_train_threshold,
    fit_scalar_calibrator,calibrated,scores)
from bridge_v78_calibration_review import verify

ARCHIVE=Path(os.environ.get('HEPTA_ORIGINAL_V6_ZIP','/NO_AUTHENTIC_V6_ARCHIVE_CONFIGURED'))
RESULT=Path(__file__).with_name('V78_ORIGINAL_LOGIT_SOURCE_HELDOUT_20261015.json')

class OriginalSourceCalibration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ARCHIVE.is_file():
            raise unittest.SkipTest("requires exact authenticated original V6 archive")
        cls.rows,cls.groups,cls.original=read_original(ARCHIVE)
        cls.result=json.loads(RESULT.read_text())

    def test_corpus_genuine_16_sources_and_old_model(self):
        self.assertEqual(len(self.rows),827)
        self.assertEqual(len(self.groups),16)
        self.assertEqual(len({(x['paragraph_id'],x['question_id']) for x in self.rows}),194)
        self.assertEqual(sum(x['label'] for x in self.rows),374)
        self.assertEqual(len(self.original),3)

    def test_exact_four_equal_source_folds(self):
        assigned=group_folds(self.groups)
        self.assertEqual({i:sum(f==i for f in assigned.values()) for i in range(4)},
                         {0:4,1:4,2:4,3:4})

    def test_train_only_threshold_not_best_ad_hoc_label_access(self):
        idx=[i for i,r in enumerate(self.rows) if group_folds(self.groups)[r['source_hash']]!=0]
        p=[self.original[41][i] for i in idx];y=[self.rows[i]['label'] for i in idx]
        self.assertAlmostEqual(choose_train_threshold(p,y),self.result['measures']['41']['folds'][0]['threshold'])

    def test_original_logit_calibration_does_train_two_real_scalars(self):
        from bridge_v78_original_calibration import fit_scalar_calibrator
        t=fit_scalar_calibrator(self.original[41][:32],[r['label'] for r in self.rows[:32]],seed=41)
        self.assertEqual(t['optimizer_updates'],240)
        self.assertEqual(t['trainable_parameters'],2)
        self.assertNotEqual(t['log_scale'],0.0)

    def test_original_real_execution_recomputes_sanitized_outcomes(self):
        new=run(ARCHIVE)
        for seed in ('41','47','53'):
            self.assertEqual(new['measures'][seed]['oof_prediction_sha256'],
                             self.result['measures'][seed]['oof_prediction_sha256'])
            for arm in self.result['arms']:
                self.assertEqual(new['measures'][seed]['arm_metrics'][arm],
                                 self.result['measures'][seed]['arm_metrics'][arm])
        self.assertEqual(self.result['actual_calibration_fits'],12)
        self.assertFalse(self.result['future_independent_multirc_verified'])

    def test_independent_pure_stdlib_review_passes_real_experiment(self):
        out=verify(ARCHIVE,self.result)
        self.assertTrue(out['all_three_seed_fold_predictions_replayed'])
        self.assertFalse(out['prospective_quality_verified'])

    def test_altered_heldout_measure_refused(self):
        d=copy.deepcopy(self.result);d['measures']['41']['arm_metrics']['fit_threshold']['f1_a']+=0.01
        with self.assertRaisesRegex(ValueError,'metric disagrees'):
            verify(ARCHIVE,d)

    def test_forged_fitted_parameters_refused(self):
        d=copy.deepcopy(self.result);d['measures']['47']['folds'][1]['calibrator']['bias']+=1.0
        with self.assertRaisesRegex(ValueError,'prediction recreation'):
            verify(ARCHIVE,d)

    def test_incomplete_original_seed_or_scope_fails(self):
        d=copy.deepcopy(self.result);d['seeds']=[41,47]
        with self.assertRaises(ValueError):verify(ARCHIVE,d)
        d=copy.deepcopy(self.result);d['production_authorized']=True
        with self.assertRaises(ValueError):verify(ARCHIVE,d)

    def test_changed_historical_source_data_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'wrong.zip';raw=bytearray(ARCHIVE.read_bytes());raw[50]^=2;p.write_bytes(raw)
            with self.assertRaisesRegex(ValueError,'V6 bytes changed'):
                verify(p,self.result)


if __name__=='__main__':unittest.main()
