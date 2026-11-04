"""V33 genuine original-material tests: mandatory source and real fit receipts."""
from __future__ import annotations

from copy import deepcopy
import os
import json
import tempfile
from pathlib import Path
import unittest

import v33_independent_numpy_review as r

class OriginalMaterial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        keys=('HEPTA_V33_STAGE','HEPTA_V33_PUBLIC','HEPTA_V33_PRIVATE')
        for key in keys:
            if not os.environ.get(key):raise RuntimeError('Real original V33 material mandatory: '+key)
        cls.stage=Path(os.environ[keys[0]])
        cls.pub=Path(os.environ[keys[1]])
        cls.priv=Path(os.environ[keys[2]])
        cls.verified=r.review(cls.stage,cls.pub,cls.priv)

    def test_actual_numpy_replay_all_checkpoints(self):
        self.assertEqual(self.verified['checkpoint_count'],48)
        self.assertEqual(self.verified['source_bound_model_prediction_count'],60)
        self.assertEqual(self.verified['physical_head_optimizer_updates_paid'],1440)
        self.assertFalse(self.verified['normalized_withheld_groups_used'])
        self.assertEqual(self.verified['decision'],'HOLD_CORRECTED_FOLD_NORMALIZATION_NOT_PROSPECTIVE')

    def denied(self,mutate, *, public=False):
        data=json.loads((self.pub if public else self.priv).read_bytes())
        mutate(data)
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/'candidate.json';path.write_bytes(r.canonical(data))
            with self.assertRaises((ValueError,KeyError,TypeError)):
                r.review(self.stage,path if public else self.pub,path if not public else self.priv)

    def test_changed_held_scaler_hash_is_denied(self):
        self.denied(lambda x:x['records'][0].update(normalizer_sha256='0'*64))

    def test_normalizer_admitting_held_features_is_denied(self):
        self.denied(lambda x:x['records'][0].update(normalization_has_held_features=True))
        self.denied(lambda x:x['records'][0].update(normalization_fit_group_count=64))
        self.denied(lambda x:x.update(held_groups_used_for_fit=True),public=True)

    def test_forced_global_64_transductive_scaler_is_denied(self):
        self.denied(lambda x:x.update(fold_normalization='GLOBAL_64_FEATURES'),public=True)

    def test_old_label_source_cross_fold_is_denied(self):
        self.denied(lambda x:x['records'][0]['fitted_case_ids'].__setitem__(0,x['records'][0]['held_case_ids'][0]))

    def test_changed_physical_old_head_is_denied(self):
        self.denied(lambda x:x['records'][0]['states']['old']['w'][0].__setitem__(0,999.))

    def test_changed_physical_logits_is_denied(self):
        self.denied(lambda x:x['records'][0]['logits']['split'][0].__setitem__(0,[0,0,0,0]))

    def test_false_paid_steps_is_denied(self):
        self.denied(lambda x:x.update(physical_head_optimizer_updates=0),public=True)
        self.denied(lambda x:x['records'][0]['cost']['continued'].update(updates=0))

    def test_promotion_or_fake_future_is_denied(self):
        self.denied(lambda x:x.update(production_authorized=True),public=True)
        self.denied(lambda x:x.update(model_selection_authorized=True),public=True)
        self.denied(lambda x:x.update(ndu_selector_authorized=True),public=True)
        self.denied(lambda x:x.update(cell_split_authorized=True),public=True)
        self.denied(lambda x:x.update(independent_future_windows=3),public=True)

    def test_false_metric_or_forward_share_is_denied(self):
        self.denied(lambda x:x['per_seed']['41']['split'].update(total_correct=64),public=True)
        self.denied(lambda x:x['records'][0].update(split_reuses_continued=False))

    def test_wrong_source_snapshot_is_denied(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);(p/'train-source.json').write_bytes((self.stage/'train-source.json').read_bytes())
            (p/'train-features.safetensors').write_bytes(b'fake-but-scored')
            with self.assertRaises(ValueError):r.review(p,self.pub,self.priv)

if __name__=='__main__':unittest.main()
