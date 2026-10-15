"""Synthetic contract tests only; no pretrained natural-image result."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import tempfile
import unittest

from e2_beans_original_zip_review import Reject, canon, digest
from test_e2_beans_original_zip_review import fake_archives, zipup
from e2_beans_frozen_vision_linear_probe import (
    seal, write_seal, PROBE, PARAMETER_COUNT,
)
from e2_beans_vision_probe_independent_score import (
    independent_score, paired, exact_mcnemar, read_pinned,
)

class PureVisionControlTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base=Path(temp.name)
        self.members=fake_archives()
        self.rebuild()

    def rebuild(self):
        self.paths={}
        self.pins={}
        for k,items in self.members.items():
            path=self.base/(k+'.zip')
            self.pins[k]=zipup(items,path)
            self.paths[k]=path

    def train(self):
        m,p=seal(self.paths['source'],self.pins['source'],self.paths['producer'],self.pins['producer'])
        return m,p

    def score(self, m=None,p=None):
        if m is None or p is None:
            m,p=self.train()
        return independent_score(self.paths,self.pins,m,digest(canon(m)),p)

    def test_main_contract_and_three_accuracy_arms_reconstructed(self):
        m,p=self.train()
        out=self.score(m,p)
        self.assertEqual(m['schema'],PROBE+'.model')
        self.assertEqual(m['parameter_count'],PARAMETER_COUNT)
        self.assertEqual(len(m['weights']),384)
        self.assertEqual(len(p['rows']),24)
        self.assertEqual(out['cases'],24)
        self.assertEqual(out['frozen_vision_ridge_correct'],8)
        self.assertEqual(out['original_fitted_bridge_correct'],24)
        self.assertFalse(out['matched_parameter_and_total_compute_budget'])
        self.assertFalse(out['original_source_independent_future_windows'])
        self.assertFalse(out['stem_selected'])
        self.assertEqual(out['authority'],'DENY_ALL')

    def test_no_future_label_in_sealed_docs(self):
        m,p=self.train()
        self.assertNotIn('future_class_targets.jsonl',repr(m)+repr(p))
        self.assertNotIn('class_label',repr(p))
        self.assertNotIn('withheld',repr(p))
        self.assertNotIn('future_targets',repr(m))

    def test_prediction_hash_binding_to_model(self):
        m,p=self.train()
        p['model_sha256']='0'*64
        with self.assertRaises(Reject):self.score(m,p)

    def test_change_model_parameter_after_seal_rejected(self):
        m,p=self.train()
        m['weights'][0][0]+=0.5
        with self.assertRaises(Reject):self.score(m,p)

    def test_model_falsely_claiming_authority_rejected(self):
        m,p=self.train()
        m['production_accepted']=True
        with self.assertRaises(Reject):self.score(m,p)

    def test_add_fake_future_label_to_source_only_archive_rejected(self):
        self.members['source']['source/future_class_targets.jsonl']=b'leak\n'
        self.rebuild()
        with self.assertRaises(Reject):self.train()

    def test_add_future_target_to_producer_rejected(self):
        self.members['producer']['target-manifest.json']=b'leak\n'
        self.rebuild()
        with self.assertRaises(Reject):self.train()

    def test_seal_sensitive_to_original_train_class_bytes(self):
        self.members['source']['source/train_class.jsonl']=b'{"wrong":true}\n'
        self.rebuild()
        with self.assertRaises(Reject):self.train()

    def test_vision_future_data_drift_rejected(self):
        self.members['producer']['vision_future/features.jsonl']=b'\n'
        self.rebuild()
        with self.assertRaises(Reject):self.train()

    def test_image_source_bytes_tamper_rejected(self):
        image=next(k for k in self.members['source'] if k.startswith('source/images/'))
        self.members['source'][image]=b'synthetic changed image'
        self.rebuild()
        with self.assertRaises(Reject):self.train()

    def test_missing_source_zip_rejected(self):
        with self.assertRaises(Reject):seal(self.base/'no.zip','a'*64,
                                              self.paths['producer'],self.pins['producer'])

    def test_modified_prediction_result_rejected(self):
        m,p=self.train()
        p['rows'][0]['predicted_label']='healthy'
        with self.assertRaises(Reject):self.score(m,p)

    def test_injected_false_natural_future_claim_rejected(self):
        m,p=self.train()
        p['target_host_attested']=True
        with self.assertRaises(Reject):self.score(m,p)

    def test_consistent_wrong_original_heldout_label_cannot_score(self):
        m,p=self.train()
        rows=[json.loads(s) for s in self.members['withheld']['future_class_targets.jsonl'].splitlines()]
        rows[0]['class_label']='healthy'
        self.members['withheld']['future_class_targets.jsonl']=b''.join(canon(x) for x in rows)
        self.rebuild()
        with self.assertRaises(Reject):self.score(m,p)

    def test_preregistered_alpha_immutable(self):
        m,p=self.train()
        m['alpha']=10.0
        with self.assertRaises(Reject):self.score(m,p)

    def test_invalid_weight_shape_rejected(self):
        m,p=self.train()
        m['weights'].pop()
        with self.assertRaises(Reject):self.score(m,p)

    def test_future_case_extra_prediction_rejected(self):
        m,p=self.train()
        p['rows'].append(copy.deepcopy(p['rows'][0]))
        with self.assertRaises(Reject):self.score(m,p)

    def test_exact_pairing(self):
        self.assertEqual(paired([True,False,True,False],[False,True,True,False]),
                         {'rescued':1,'harmed':1,'both_correct':1,'both_wrong':1})
        self.assertEqual(exact_mcnemar(0,0),1.0)
        self.assertEqual(exact_mcnemar(6,0),0.03125)
        self.assertEqual(exact_mcnemar(2,1),1.0)

    def test_create_only_seal(self):
        m,p=self.train()
        out=self.base/'probe-seal'
        written=write_seal(out,m,p)
        self.assertEqual(written['model_sha256'],digest((out/'probe_model.json').read_bytes()))
        self.assertEqual(written['predictions_sha256'],digest((out/'probe_predictions.json').read_bytes()))
        with self.assertRaises(Reject):write_seal(out,m,p)

    def test_strict_json_pins_reject_changed_file(self):
        m,p=self.train()
        out=self.base/'probe-seal'
        written=write_seal(out,m,p)
        obj=read_pinned(out/'probe_model.json',written['model_sha256'])
        self.assertEqual(obj,m)
        (out/'probe_model.json').write_text((out/'probe_model.json').read_text()+' ')
        with self.assertRaises(Reject):read_pinned(out/'probe_model.json',written['model_sha256'])

    def test_deterministic_proposed_predictions(self):
        m1,p1=self.train()
        m2,p2=self.train()
        self.assertEqual(digest(canon(m1)),digest(canon(m2)))
        self.assertEqual([x['predicted_label'] for x in p1['rows']],
                         [x['predicted_label'] for x in p2['rows']])

if __name__=='__main__':unittest.main()
