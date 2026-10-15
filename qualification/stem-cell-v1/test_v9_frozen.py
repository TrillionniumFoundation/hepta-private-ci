"""Source/score contracts for frozen original V8 synthetic weights; no model download."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import torch
from v9_blind_benchmark import write_once
from v9_source_panels import dataset_design
from v9_typed_graph import digest
from v9_frozen_v8_readout import (ARMS, SEEDS, V8_LOCKED_SHA256,
    OriginalV8SyntheticBank, load_exact_v8_weights)
from v9_frozen_v8_score import score


class FrozenSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_original_vector_identity_seed_and_base_dimensions(self):
        b=OriginalV8SyntheticBank()
        self.assertEqual(tuple(b.word('own','OWN').shape),(384,))
        self.assertEqual(float(b.word('own','OWN')[3]),3.)
        self.assertEqual(float(b.word('color','green')[2]),3.)
        self.assertTrue(torch.equal(b.word('person','Ada'),b.word('person','Ada')))
        self.assertTrue(torch.equal(b.word('person','Ada')[8:136],
                                    b.word('color','Ada')[8:136]))
        self.assertFalse(torch.equal(b.word('person','Ada'), b.word('person','Ben')))

    def test_physical_batch_geometry_and_no_targets(self):
        cases,_=__import__('v9_source_panels').panel('held_novel',5,2)
        data=OriginalV8SyntheticBank().encode(cases[:8])
        self.assertEqual(tuple(data[0].shape),(8,10,3,384))
        self.assertEqual(tuple(data[1].shape),(8,2,384))
        self.assertEqual(tuple(data[3].shape),(8,10,3))
        self.assertEqual(set(data[3].flatten().tolist()),{True})

    def test_refuse_unsupported_kind(self):
        with self.assertRaises(ValueError):
            OriginalV8SyntheticBank().word('injected_answer','yes')

    def test_all_twelve_expected_sha_locked(self):
        self.assertEqual(len(V8_LOCKED_SHA256),12)
        for seed in SEEDS:
            for arm in ARMS:
                self.assertRegex(V8_LOCKED_SHA256[f'{seed}/{arm}'],r'^[0-9a-f]{64}$')

    def test_bad_archive_and_mutated_weights_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with self.assertRaises(FileNotFoundError):
                load_exact_v8_weights(root,41,'bridge')
            target=root/'verified-seed41';target.mkdir()
            (target/'weights-41-bridge.safetensors').write_bytes(b'forged model')
            with self.assertRaisesRegex(ValueError,'SHA256 mismatch'):
                load_exact_v8_weights(root,41,'bridge')

    def test_invalid_model_identity_rejected(self):
        with self.assertRaises(ValueError):
            load_exact_v8_weights(Path('/nonexistent'),42,'bridge')
        with self.assertRaises(ValueError):
            load_exact_v8_weights(Path('/nonexistent'),41,'new-model')


class FrozenScorer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design,cls.public,cls.truth=dataset_design()
        cls.models={f'{seed}/{arm}':{c['case_id']:0.5 for c in cls.public}
                   for seed in SEEDS for arm in ARMS}
        cls.record=dict(schema='hepta.v9.previous-synthetic-head-zero-shot.v1',
            public_sha256=digest(cls.public),candidate_ids=[c['case_id'] for c in cls.public],
            probabilities=cls.models,weight_files={k:{'sha256':V8_LOCKED_SHA256[k]} for k in cls.models},
            optimizer_updates=0,actual_pretrained_encoder_forwards=0,
            V9_label_access=False,V9_checkpoint_selection=False,authority='DENY_ALL',
            production_accepted=False)
        cls.record['probs_sha256']=digest(cls.models)

    def _run(self,record,*,accept):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name,data in [('public.json',self.public),('truth.json',self.truth),('frozen.json',record)]:
                write_once(root/name,data)
            if accept:
                r=score(root/'public.json',root/'truth.json',root/'frozen.json',root/'score.json')
                self.assertEqual(len(r['observations']),156)
                self.assertFalse(r['selected_winner'])
                self.assertFalse(r['production_accepted'])
            else:
                with self.assertRaises(ValueError):
                    score(root/'public.json',root/'truth.json',root/'frozen.json',root/'score.json')

    def test_independent_full_panel_null(self):
        self._run(self.record,accept=True)

    def test_no_hiding_or_double_counting_cases(self):
        x=copy.deepcopy(self.record)
        k=next(iter(x['probabilities']))
        x['probabilities'][k].pop(next(iter(x['probabilities'][k])))
        x['probs_sha256']=digest(x['probabilities'])
        self._run(x,accept=False)

    def test_resealed_fabricated_pretrained_call_denied(self):
        x=copy.deepcopy(self.record)
        x['actual_pretrained_encoder_forwards']=1
        self._run(x,accept=False)

    def test_future_label_leak_and_authority_denied(self):
        for k,v in [('V9_label_access',True),('authority','GRANT'),
                    ('production_accepted',True),('optimizer_updates',100)]:
            x=copy.deepcopy(self.record);x[k]=v
            self._run(x,accept=False)

    def test_nonfinite_probability_denied(self):
        x=copy.deepcopy(self.record)
        k=next(iter(x['probabilities']))
        cid=next(iter(x['probabilities'][k]))
        x['probabilities'][k][cid]=float('nan')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'public.json').write_text(json.dumps(self.public))
            (root/'truth.json').write_text(json.dumps(self.truth))
            (root/'frozen.json').write_text(json.dumps(x))
            with self.assertRaises(ValueError):
                score(root/'public.json',root/'truth.json',root/'frozen.json',root/'score.json')


if __name__=='__main__':unittest.main()
