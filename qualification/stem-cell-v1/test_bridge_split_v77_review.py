"""Independent stdlib original-archive / signed-off-scopes adversarial tests."""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from bridge_split_v77_review import validate_reports,SCHEMA

ROOT=Path('/mnt/data/hepta_v77')
ARCHIVE=Path(os.environ.get('HEPTA_ORIGINAL_V6_ZIP',
           '/mnt/data/hepta_research_material/hepta_bridge_learning_v6_20261015.zip'))
FIRST=Path(os.environ.get('HEPTA_V77_FIRST',ROOT/'V77_REAL_V6_SHARED_TRUNK_SYNTHETIC_CELL_SPLIT_20261015.json'))
REPEAT=Path(os.environ.get('HEPTA_V77_REPLICA',ROOT/'V77_REAL_V6_SHARED_TRUNK_SYNTHETIC_CELL_SPLIT_REPLICA_20261015.json'))

@unittest.skipUnless(all(x.is_file() for x in (ARCHIVE,FIRST,REPEAT)),
 'requires real original V6 archive and two separately executed physical results')
class PhysicalArchivedReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=json.loads(FIRST.read_text())
        cls.repeated=json.loads(REPEAT.read_text())
    def checked(self,a=None,b=None):
        with tempfile.TemporaryDirectory() as d:
            one,two=Path(d)/'a.json',Path(d)/'b.json'
            one.write_text(json.dumps(self.original if a is None else a))
            two.write_text(json.dumps(self.repeated if b is None else b))
            return validate_reports(ARCHIVE,one,two)
    def test_authentic_3_seed_original_and_repeated_head_digest_agreement(self):
        r=self.checked()
        self.assertEqual(r['schema'],'hepta.bridge.split-cell-v77.independent-receipt-review.v1')
        self.assertTrue(r['all_candidate_head_sha256_deterministically_identical_across_two_real_runs'])
        self.assertFalse(r['actual_pretrained_encoder_executed'])
        self.assertEqual(len(r['per_seed']),3)
    def test_deny_faked_natural_generalization(self):
        a=copy.deepcopy(self.original)
        a['real_multirc_generalization_verified']=True
        with self.assertRaisesRegex(ValueError,'scientific scope'):
            self.checked(a)
    def test_deny_unauthorized_cell_split(self):
        a=copy.deepcopy(self.original)
        a['cell_split_production_authorized']=True
        with self.assertRaisesRegex(ValueError,'scientific scope'):
            self.checked(a)
    def test_deny_extra_qualification_field(self):
        a=copy.deepcopy(self.original)
        a['future_generation_capability_established']=True
        with self.assertRaisesRegex(ValueError,'exact original'):
            self.checked(a)
    def test_deny_relabeling_synthetic_as_real_granite(self):
        a=copy.deepcopy(self.original)
        a['results'][0]['original_granite_features_used']=True
        with self.assertRaisesRegex(ValueError,'synthetic-only scope'):
            self.checked(a)
    def test_deny_swapped_original_pretrained_parent(self):
        a=copy.deepcopy(self.original)
        a['results'][0]['parent_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'original frozen V6'):
            self.checked(a)
    def test_deny_nonzero_frozen_original_training_updates(self):
        a=copy.deepcopy(self.original)
        a['results'][1]['original_parent_state_train_gradient_count']=1
        with self.assertRaisesRegex(ValueError,'original frozen V6'):
            self.checked(a)
    def test_deny_replayed_falsified_head_digest(self):
        a=copy.deepcopy(self.original)
        a['results'][1]['head_sha256']='c'*64
        with self.assertRaisesRegex(ValueError,'drift'):
            self.checked(a)
    def test_deny_forged_training_score(self):
        a=copy.deepcopy(self.original)
        a['results'][0]['synthetic_train_new_correct']=159
        with self.assertRaisesRegex(ValueError,'drift'):
            self.checked(a)
    def test_deny_truncated_physical_cohort(self):
        a=copy.deepcopy(self.original)
        a['physical_allocated_cell_heads']=64
        with self.assertRaisesRegex(ValueError,'exact 3-seed'):
            self.checked(a)
    def test_deny_duplicate_result_json_properties(self):
        from bridge_split_v77_review import _json
        with self.assertRaisesRegex(ValueError,'duplicate JSON'):
            _json(b'{"run":1,"run":2}')
    def test_archive_tamper_refused(self):
        with tempfile.TemporaryDirectory() as d:
            bad=Path(d)/'V6.zip'
            raw=bytearray(ARCHIVE.read_bytes());raw[90]^=1
            bad.write_bytes(raw)
            with self.assertRaisesRegex(ValueError,'authentic V6'):
                validate_reports(bad,FIRST,REPEAT)

if __name__=='__main__':unittest.main()
