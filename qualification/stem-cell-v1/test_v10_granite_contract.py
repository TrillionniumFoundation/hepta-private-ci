"""Source-first real Granite contracts, with a clearly NON-pretrained toy SGD fixture."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import torch

from v9_source_panels import dataset_design, panel
from v9_frozen_v8_readout import OriginalV8SyntheticBank
from v9_typed_graph import digest
from v10_granite_features import (source_owner, to_public_reader_case,
                                   validate_public, load, save_new)
from v10_granite_reader import (ARMS, SEEDS, TRAIN_UPDATES, RealTokenStore,
                                grouped_train, fit_one)
from v10_granite_score import review


class FakeSyntheticOnly:
    """DOES NOT pretend to provide a real pretrained checkpoint or feature bank."""
    def __init__(self,public,root):
        self.public=public
        self.root=root
        self.bank=OriginalV8SyntheticBank()
        save_new(root/'real-encoder-receipt.json',{'synthetic_mechanism_test_only':True,
                  'real_pretrained_forward_executed':False,'authority':'DENY_ALL'})

    def batch(self,rows):
        batches=[self.bank.encode([row]) for row in rows]
        f=max(row[0].shape[1] for row in batches)
        b=len(batches)
        fact=torch.zeros(b,f,3,384)
        mask=torch.zeros(b,f,3,dtype=torch.bool)
        for i,row in enumerate(batches):
            n=row[0].shape[1]
            fact[i,:n]=row[0][0]
            mask[i,:n]=row[3][0]
        return (fact,torch.cat([row[1] for row in batches]),
                torch.cat([row[2] for row in batches]),mask,
                torch.cat([row[4] for row in batches]),
                torch.cat([row[5] for row in batches]))


class V10Source(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.design,cls.public,cls.truth=dataset_design()
        cls.training={k:v for k,v in cls.truth.items() if k.startswith('train/')}

    def test_entire_source_is_unlabeled_and_stable(self):
        self.assertEqual(len(validate_public(self.public)),1248)
        self.assertEqual(len(grouped_train(self.public,self.training)),72)
        self.assertEqual(len({c['source_group'] for c in self.public}),312)
        self.assertFalse(any('label' in c for c in self.public))

    def test_owner_seals_source_and_labels_separately(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'source'
            seal=source_owner(root)
            self.assertEqual(seal['public_sha256'],digest(self.public))
            self.assertEqual(seal['train_rows'],288)
            self.assertEqual(seal['held_rows'],960)
            self.assertTrue((root/'held-labels-restricted.json').exists())
            self.assertTrue((root/'train-labels.json').exists())
            with self.assertRaises(FileExistsError):
                source_owner(root)

    def test_encoder_receives_dummy_labels_only(self):
        for row in self.public[::27]:
            item=to_public_reader_case(row)
            self.assertEqual(item.label,0)
            self.assertIn(item.source_split,('train','validation'))
            self.assertEqual(item.facts,tuple(row['facts']))

    def test_extra_gold_field_rejected_before_encoding(self):
        changed=deepcopy(self.public)
        changed[0]['label']=1
        with self.assertRaises(ValueError):
            validate_public(changed)

    def test_held_truth_forbidden_during_fitting(self):
        both=dict(self.truth)
        with self.assertRaises(ValueError):
            grouped_train(self.public,both)
        missing=dict(self.training)
        missing.pop(next(iter(missing)))
        with self.assertRaises(ValueError):
            grouped_train(self.public,missing)

    def test_completely_fake_model_receipt_cannot_load(self):
        with tempfile.TemporaryDirectory() as t:
            f=FakeSyntheticOnly(self.public,Path(t))
            with self.assertRaises((ValueError,FileNotFoundError)):
                RealTokenStore(self.public,Path(t))

    def test_toy_real_reader_SGD_is_executed_but_never_admitted_as_granite(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            fake=FakeSyntheticOnly(self.public,root)
            start=fit_one(fake,self.training,41,'bridge',root/'fit',updates=4)
            self.assertEqual(start['actual_updates'],4)
            self.assertEqual(start['total_optimizer_case_exposures'],64)
            self.assertFalse(start['frozen_pretrained_features_verified'])
            self.assertEqual(start['experiment_origin'],'synthetic_mechanism_test_only')
            self.assertFalse(start['model_selected'])
            self.assertTrue((root/'fit'/'reader.safetensors').is_file())
            self.assertEqual(len(load(root/'fit'/'schedule.json')),4)

    def test_all_report_fields_forbid_promotion(self):
        self.assertEqual(ARMS,('base','bridge','endpoint'))
        self.assertEqual(SEEDS,(41,47,53))
        self.assertEqual(TRAIN_UPDATES,256)

    def test_independent_postseal_will_not_accept_faked_granite_receipt(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            source_owner(root/'source')
            public=root/'source'/'public.json'
            seal=root/'source'/'source-seal.json'
            held=root/'source'/'held-labels-restricted.json'
            model=root/'models';model.mkdir()
            receipt=root/'fake-encoder.json'
            save_new(receipt,{'schema':'hepta.v10.real-granite-encoding.v1',
                             'real_pretrained_forward_executed':False})
            save_new(root/'predictions.json',{'schema':'hepta.v10.real-granite-blind.v1',
                                            'probabilities':{},'authority':'DENY_ALL'})
            with self.assertRaises(ValueError):
                review(public,seal,held,root/'predictions.json',model,receipt,root/'score.json')


if __name__=='__main__':unittest.main()
