"""Original archived source test and denial-focused adversarial controls.

Requires exact real ZIP artifacts. Never substitutes synthetic originals or
marks a missing publisher/source receipt as a successful test.
"""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

import original_crossdomain_v10 as v


def original_paths():
    paths={}
    for kind in v.ORIGINALS:
        key="HDCF_V10_"+kind.upper()
        candidate=os.environ.get(key)
        if not candidate:
            raise v.Denied("missing original archive: "+key)
        paths[kind]=candidate
    return paths


class OriginalV10Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paths=original_paths()
        cls.docs={kind:v.read_original(path,kind) for kind,path in cls.paths.items()}

    def test_real_original_observations(self):
        receipt=v.audit_documents(self.docs)
        self.assertEqual(receipt['disposition'],'HOLD_NO_GO_DENY_ALL')
        self.assertEqual([x['original_cases'] for x in receipt['panels']],[32,24])
        self.assertEqual([x['split_correct'] for x in receipt['panels']],[20,16])
        self.assertEqual([x['shared_correct'] for x in receipt['panels']],[16,16])
        self.assertFalse(receipt['joint_pooled_significance_test_performed'])
        self.assertFalse(receipt['cell_split_promoted'])

    def test_real_text_pair_recount(self):
        row=v.audit_documents(self.docs)['panels'][0]
        self.assertEqual((row['split_only_correct'],row['shared_only_correct']),(12,8))
        self.assertEqual(row['nominal_case_level_p'],0.5034446716308594)

    def test_real_image_strong_frozen_reference(self):
        row=v.audit_documents(self.docs)['panels'][1]
        self.assertEqual((row['strong_frozen_visual_correct'],row['split_correct']),(21,16))
        self.assertEqual(row['nominal_vs_visual_p'],.2265625)
        self.assertEqual((row['split_only_correct'],row['shared_only_correct']),(0,0))

    def rejected(self, mutate):
        docs=copy.deepcopy(self.docs)
        mutate(docs)
        with self.assertRaises((v.Denied,TypeError,ValueError,KeyError)):
            v.audit_documents(docs)

    def test_changed_modern_probability(self):
        self.rejected(lambda d: d['modern_trial']['predictions']['split'][0].update(p1=.99))

    def test_changed_blind_label(self):
        self.rejected(lambda d: d['modern_targets']['targets'][0].update(target=1))

    def test_changed_source_revision(self):
        self.rejected(lambda d: d['modern_targets'].update(source_revision='evil'))

    def test_split_duplicate_case(self):
        self.rejected(lambda d: d['modern_trial']['predictions']['split'].__setitem__(1,
                         copy.deepcopy(d['modern_trial']['predictions']['split'][0])))

    def test_tamper_original_brier(self):
        self.rejected(lambda d: d['modern_review']['score']['results']['split'].update(brier=0.01))

    def test_mismatched_work(self):
        self.rejected(lambda d: d['modern_trial']['arms']['split'].update(
                          estimated_parameter_touches=17))

    def test_changed_original_visual_prototype(self):
        self.rejected(lambda d: d['beans_review'].update(binary_original_visual_prototype_correct=16))

    def test_changed_original_discordance(self):
        self.rejected(lambda d: d['beans_review']['matched_split_vs_shared_one_touch'].update(
                          split_only_correct=4))

    def test_qualified_issuer_claim_denied(self):
        self.rejected(lambda d: d['beans_review'].update(source_independent_issuers=True))

    def test_production_authority_claim_denied(self):
        self.rejected(lambda d: d['modern_review'].update(production_authorized=True))

    def test_original_zip_byte_tampering_rejected(self):
        original=Path(self.paths['beans_review']).read_bytes()
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'fake.zip'
            path.write_bytes(original[:-2]+b'XX')
            with self.assertRaises(v.Denied):
                v.read_original(path,'beans_review')

    def test_duplicate_json_key_rejected(self):
        with self.assertRaises(v.Denied):
            v.strict_json(b'{"x":1,"x":2}')

    def test_nonfinite_json_rejected(self):
        with self.assertRaises(v.Denied):
            v.strict_json(b'{"x":NaN}')

    def test_archive_scope_missing_not_optional(self):
        with self.assertRaises(v.Denied):
            v.audit_paths({'modern_trial':self.paths['modern_trial']})

    def test_exact_paired_count_statistics(self):
        self.assertEqual(v._exact_pair(12,8),.5034446716308594)
        self.assertEqual(v._exact_pair(0,0),1.0)
        self.assertEqual(v._exact_pair(3,8),.2265625)
        with self.assertRaises(v.Denied):
            v._exact_pair(True,1)

    def test_file_symlink_denied(self):
        with tempfile.TemporaryDirectory() as temp:
            symlink=Path(temp)/'alias.zip'
            symlink.symlink_to(self.paths['beans_review'])
            with self.assertRaises(v.Denied):
                v.read_original(symlink,'beans_review')

    def test_real_original_sources_have_no_self_promotion(self):
        receipt=v.audit_paths(self.paths)
        self.assertFalse(receipt['complete_lifecycle_tco_attested'])
        self.assertFalse(receipt['physical_4096_cell_model_selection_authorized'])
        self.assertFalse(receipt['real_audio_video_encoder_evidence'])
        self.assertEqual(receipt['independent_source_family_count_certified'],0)


if __name__=='__main__':
    unittest.main()
