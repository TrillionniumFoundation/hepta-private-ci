"""Original-material adversarial checks; execute ONLY after verified stage/fit.

Never run against synthetic fixtures in a 'green' original-source job.
"""
from __future__ import annotations
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
import v32_independent_numpy_review as v

class Original(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Original suite MUST hard fail if material is not physically available.
        for k in ('HEPTA_V32_ORIGINAL_STAGE','HEPTA_V32_ACTUAL_REPORT','HEPTA_V32_ACTUAL_PRIVATE'):
            if k not in os.environ: raise RuntimeError('original V32 material mandatory: '+k)
        cls.source=Path(os.environ['HEPTA_V32_ORIGINAL_STAGE'])
        cls.pub=Path(os.environ['HEPTA_V32_ACTUAL_REPORT'])
        cls.private=Path(os.environ['HEPTA_V32_ACTUAL_PRIVATE'])
        cls.base=v.assess(cls.source,cls.pub,cls.private)

    def test_48_real_torch_head_states_independent(self):
        self.assertEqual(self.base['checkpoint_count'],48)
        self.assertEqual(self.base['source_bound_model_prediction_count'],60)
        self.assertEqual(self.base['physical_head_updates_charge'],1440)
        self.assertEqual(self.base['decision'],'HOLD_TRAIN_ONLY_ORIGINAL_OOF_NOT_PROSPECTIVE')
        self.assertTrue(self.base['independent_numpy_weight_forward_replay'])

    def denied(self,modify,*,private=True):
        with tempfile.TemporaryDirectory() as tmp:
            doc=json.loads((self.private if private else self.pub).read_bytes())
            modify(doc)
            changed=Path(tmp)/'tampered.json';changed.write_bytes(v.canonical(doc))
            with self.assertRaises(ValueError):
                v.assess(self.source,self.pub if private else changed,
                         changed if private else self.private)

    def test_changed_model_weight(self):
        self.denied(lambda x:x['records'][0]['weights']['old']['w'][0].__setitem__(0,1234.0))

    def test_changed_model_logit(self):
        self.denied(lambda x:x['records'][0]['logits']['split'][0].__setitem__(0,1234.0))

    def test_pretend_independent_future(self):
        self.denied(lambda x:x.update(chronological_future_windows=3),private=False)

    def test_promote_cell_without_authorizer(self):
        self.denied(lambda x:x.update(model_or_cell_split_authorized=True),private=False)
        self.denied(lambda x:x.update(production_authorized=True),private=False)

    def test_training_fold_case_leak_or_swap(self):
        self.denied(lambda x:x['records'][0]['held_case_ids'].__setitem__(0,
                        x['records'][0]['train_new_case_ids'][0]))

    def test_loss_of_exact_continuation_state(self):
        self.denied(lambda x:x['records'][0].update(split_new_model_state_reuses_continued=False))

    def test_fake_optimizer_updates(self):
        self.denied(lambda x:x.update(total_physical_optimizer_updates_paid=2880),private=False)
        self.denied(lambda x:x['records'][0]['cost']['old'].update(updates=0))

    def test_switch_research_original_archive(self):
        self.denied(lambda x:x.update(original_archive_sha256='0'*64),private=False)

    def test_corrupt_original_head_source(self):
        self.denied(lambda x:x['records'][0]['weights_sha256'].update(new='0'*64))

    def test_wrong_crossfold_accuracy(self):
        self.denied(lambda x:x['per_seed']['41']['arms']['split']['cell1_new_oof'].update(correct=32),private=False)

    def test_no_train_stage_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage=Path(tmp);stage.mkdir(exist_ok=True)
            (stage/'train-source.json').write_bytes((self.source/'train-source.json').read_bytes())
            (stage/'train-features.safetensors').write_bytes(b'fake bytes')
            with self.assertRaises(ValueError):v.assess(stage,self.pub,self.private)

if __name__=='__main__':unittest.main()
