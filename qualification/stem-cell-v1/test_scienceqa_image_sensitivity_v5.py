"""Deterministic original numerical sensitivity checks with synthetic fault input."""
import copy
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import scienceqa_image_sensitivity_v5 as a
import scienceqa_independent_rejudge_v5 as v5


class SensitivityV5Tests(unittest.TestCase):
    def test_original_real_archive_bytes_labelblind_review(self):
        # Real original archive is explicitly required by the separate physical
        # workflow; the unit test exercises simulated input identity.
        from test_scienceqa_independent_rejudge_v5 import fixture_source,fixture_archive
        _,_,source=fixture_source(full=True)
        archive=fixture_archive(source)
        doc=v5.parse(archive['sealed-source-bound-predictions.json'])
        doc['source_sha256']=source['source_sha256']
        archive['sealed-source-bound-predictions.json']=v5.canonical(doc)
        with patch.object(a,'SOURCE_SHA',source['source_sha256']), \
             patch.object(a,'PRED_SHA',v5.sha(archive['sealed-source-bound-predictions.json'])):
            r=a.review(archive)
            self.assertTrue(r['image_effect_on_predictions_observed'])
            self.assertFalse(r['visual_necessity_or_correctness_proven'])
            self.assertEqual(r['model_prediction_arms']['text_only']['argmax_flips_vs_text'],0)
            self.assertEqual(r['model_prediction_arms']['train_gate']['argmax_flips_vs_text'],64)
            self.assertEqual(r['authority'],'DENY_ALL')
            bad=copy.deepcopy(archive)
            doc=v5.parse(bad['sealed-source-bound-predictions.json'])
            doc['predictions'][0]['arms']['image_masked']=[.9,.03,.03,.04]
            bad['sealed-source-bound-predictions.json']=v5.canonical(doc)
            with self.assertRaises(v5.V5Error):a.review(bad)

    def test_invalid_probability_and_production_claim(self):
        from test_scienceqa_independent_rejudge_v5 import fixture_source,fixture_archive
        _,_,source=fixture_source(full=True)
        archive=fixture_archive(source)
        doc=v5.parse(archive['sealed-source-bound-predictions.json'])
        doc['source_sha256']=source['source_sha256'];doc['production_accepted']=True
        archive['sealed-source-bound-predictions.json']=v5.canonical(doc)
        with patch.object(a,'SOURCE_SHA',source['source_sha256']), \
             patch.object(a,'PRED_SHA',v5.sha(archive['sealed-source-bound-predictions.json'])):
            with self.assertRaises(v5.V5Error):a.review(archive)

if __name__=='__main__':unittest.main()
