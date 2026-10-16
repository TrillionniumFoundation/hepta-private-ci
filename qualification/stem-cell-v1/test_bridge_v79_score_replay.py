"""Adversarial exact original-label candidate receipts and NumPy replay tests."""
from pathlib import Path
import os
import copy
import json
import shutil
import tempfile
import unittest
import numpy as np

from bridge_v79_score_cell_review import read_head,read_json,review,numpy_forward
from bridge_v79_archived_scores import (load_sources,make_features,original_logits)

V6=Path(os.environ.get('HEPTA_V6_ORIGINAL_ARCHIVE','/nonexistent/needs-hepta-V6-evidence.zip'))
V7=Path(os.environ.get('HEPTA_V7_ORIGINAL_ARCHIVE','/nonexistent/needs-hepta-V7-evidence.zip'))
RUN=Path(os.environ.get('HEPTA_V79_ACTUAL_RUN','/nonexistent/needs-hepta-V79-executed-private-results'))

class IndependentTrueHumanLabelReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not V6.exists() or not V7.exists() or not RUN.exists():
            raise unittest.SkipTest('original V6/V7 archives and actual 12-run receipts required')
        cls.original=load_sources(V6,V7)

    def test_actual_all_twelve_complete_numeric_replay(self):
        result=review(V6,V7,RUN)
        self.assertEqual(result['candidate_models_independently_replayed'],12)
        self.assertEqual(result['candidate_optimizer_steps_receipted'],5040)
        self.assertLess(result['maximum_original_torch_vs_numpy_abs_logits_error'],1e-5)
        self.assertTrue(result['new_embedded_features_are_public_handcrafted_lexical_not_97d_hidden'])
        self.assertFalse(result['future_source_disjoint_prospective_efficacy_established'])
        self.assertFalse(result['production_authorized'])

    def test_actual_old_weight_source_and_head_numeric_geometry(self):
        p=RUN/'seed-41'/'score_text_source'
        manifest=read_json(p/'candidate.json')
        w,hashvalue=read_head(p/'head-weights.npz',manifest['weights_file_sha256'])
        self.assertEqual(hashvalue,manifest['final_head_sha256'])
        self.assertEqual(sum(q.size for q in w.values()),1700)
        x=make_features(self.original['tune'][:32],self.original['reports'][41]['tune_p'][:32],mode='score_text')
        out=numpy_forward(w,x,original_logits(self.original['reports'][41]['tune_p'][:32]))
        self.assertEqual(out.shape,(32,2))
        self.assertTrue(np.isfinite(out).all())

    def _copy_and_mutate(self,relative,mutation):
        with tempfile.TemporaryDirectory() as td:
            other=Path(td)/'run'
            shutil.copytree(RUN,other)
            path=other/relative
            mutation(path)
            with self.assertRaises((ValueError,KeyError,TypeError)):
                review(V6,V7,other)

    def test_changed_weight_without_manifest_update_denied(self):
        self._copy_and_mutate('seed-41/score_text_source/head-weights.npz',
            lambda path:path.write_bytes(path.read_bytes()[:-1]+b'!'))

    def test_tampered_model_report_claim_denied(self):
        def mutate(path):
            data=json.loads(path.read_text())
            data['cell_split_authorized']=True
            path.write_text(json.dumps(data))
        self._copy_and_mutate('completed.json',mutate)

    def test_tampered_external_tune_logits_denied(self):
        def mutate(path):
            x=np.load(path,allow_pickle=False)
            x[0,0]+=50
            with path.open('wb') as file:np.save(file,x)
        self._copy_and_mutate('seed-41/score_text_source/tune-logits.npy',mutate)

    def test_tampered_current_src_report_denied(self):
        def mutate(path):
            data=json.loads(path.read_text())
            data['tune_metrics']['f1_a']=0.99
            path.write_text(json.dumps(data))
        self._copy_and_mutate('seed-53/score_text_source/candidate.json',mutate)

    def test_clone_repeated_labels_do_not_add_independent_sources(self):
        scored=review(V6,V7,RUN)
        ci=scored['source_cluster_exploratory_bootstrap']['text_source_vs_frozen']
        self.assertEqual(ci['source_groups'],16)
        self.assertTrue(ci['repeated_seeds_are_not_new_samples'])
        self.assertTrue(ci['first_seen_on_historical_development_tune'])

if __name__=='__main__':unittest.main()
