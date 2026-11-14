"""Mandatory original 64-source evidence and 12 old-only stage1 checkpoints."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

import v34_independent_numpy_review as check

class OriginalMaterial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names=['HEPTA_V34_SOURCE','HEPTA_V34_CAPSULES','HEPTA_V34_STAGE1',
               'HEPTA_V34_PUBLIC','HEPTA_V34_PRIVATE']
        if any(not os.environ.get(n) for n in names):
            raise RuntimeError('Real V34 original TRAIN material required: '+str(names))
        cls.items=[Path(os.environ[n]) for n in names]
        cls.report=check.evaluate(*cls.items)

    def denied(self,index,alter):
        source,capsules,old,pub,private=self.items
        src=old if index=='old' else pub if index=='pub' else private
        doc=json.loads(src.read_bytes())
        alter(doc)
        with tempfile.TemporaryDirectory() as d:
            bad=Path(d)/'tamper.json';bad.write_bytes(check.canonical(doc))
            args=(source,capsules,
                  bad if index=='old' else old,
                  bad if index=='pub' else pub,
                  bad if index=='private' else private)
            with self.assertRaises((ValueError,KeyError,TypeError)):
                check.evaluate(*args)

    def test_original_48_weights_60_logits_review(self):
        x=self.report
        self.assertEqual(x['verified_stage2_head_states'],48)
        self.assertEqual(x['verified_model_logits'],60)
        self.assertEqual(x['total_optimizer_updates'],1440)
        self.assertEqual(x['source_family_count'],1)
        self.assertEqual(x['future_windows'],0)
        self.assertFalse(x['production_authorized'])

    def test_forged_sealed_old_weight_denied(self):
        self.denied('old',lambda x:x['records'][0]['weights']['w'][0].__setitem__(0,99.))

    def test_old_preprocessing_has_new_feature_denied(self):
        self.denied('old',lambda x:x.update(new_cell_features_accessed_in_model_process=True))
        self.denied('old',lambda x:x['records'][0].update(new_cell_feature_rows_seen=1))
        self.denied('private',lambda x:x['records'][0].update(old_scaler_refit_after_new_data=True))

    def test_forged_learned_output_denied(self):
        self.denied('private',lambda x:x['records'][0]['logits']['continued'][0].__setitem__(0,99.))

    def test_changed_task_accuracy_denied(self):
        self.denied('pub',lambda x:x['per_seed']['41']['split'].update(total_correct=64))

    def test_unpaid_old_updates_denied(self):
        self.denied('old',lambda x:x.update(total_old_only_updates=0))
        self.denied('private',lambda x:x['records'][0]['cost']['rehearsal'].update(updates=0))

    def test_forged_old_model_continuity_denied(self):
        self.denied('private',lambda x:x['records'][0].update(shared_old_head_state=False))

    def test_false_prospective_data_denied(self):
        self.denied('pub',lambda x:x.update(independent_future_windows=2))
        self.denied('pub',lambda x:x.update(independent_prospective_utility=0.4))

    def test_false_ndu_or_cell_permission_denied(self):
        for key in ('ndu_selector_authorized','model_selection_authorized','cell_split_authorized',
                    'production_authorized','final_use_authorized'):
            with self.subTest(key=key):self.denied('pub',lambda x:x.update({key:True}))

    def test_wrong_stage1_checkpoint_provenance_denied(self):
        self.denied('private',lambda x:x.update(stage1_checkpoint_sha256='a'*64))

if __name__=='__main__':unittest.main()
