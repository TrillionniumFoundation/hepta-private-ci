"""Source-first ModernBERT HDCF bridge tests with explicit fake-feature boundary."""
import copy
import hashlib
import os
import tempfile
import unittest

from modernbert_feature_bridge import (Denied, ORIGINAL_SOURCE, ORIGINAL_CODE_SHA, ORIGINAL_MODEL_SNAPSHOT,
        PUBLIC_SCHEMA, _cell_type, _source_checkout, _original_digest, stage_original,
        validate_public, review_original)
from physical_bank import SCHEMA, digest, train


def prepared():
    intents=['card_arrival','cash_withdrawal_not_recognised','exchange_rate','lost_or_stolen_phone']
    fit=[];held=[]; private=[]
    for c in range(4):
        for i in range(16):
            text=f'Original public fit intent {c} example {i} unique line'
            identity='fit:'+hashlib.sha256(text.encode()).hexdigest()
            fit.append({'id':identity,'text':text,'label':c})
        for i in range(8):
            text=f'Original public held intent {c} example {i} unique line'
            identity='heldout:'+hashlib.sha256(text.encode()).hexdigest()
            held.append({'id':identity,'text':text})
            private.append({'id':identity,'label':c})
    inputs={'schema':'hepta.banking77-four-intent-inputs.v1','intents':intents,'fit':fit,'heldout':held}
    inputs['input_id']=_original_digest(inputs)
    obs={'schema':'hepta.banking77-four-intent-labels.v1','input_id':inputs['input_id'],'rows':private}
    selection={'schema':'hepta.banking77-subset-selection.v1','input_id':inputs['input_id'],
               'task_subset_not_full_benchmark':True,'raw_sha256':{'train':'a'*64,'test':'b'*64},
               'selected_ids':{'fit':[r['id'] for r in fit], 'heldout':[r['id'] for r in held]}}
    return inputs,obs,selection


def fake_feature_bundle(public):
    """Fake features are NEVER treated as physical Encoder forwards."""
    rows=[]
    for group in ('fit','heldout'):
        for i, row in enumerate(public[group]):
            x=[((i%7)-3)*0.1, (i%3)*.1, .2, (i+1)*0.00011 + (0.002 if group=='heldout' else 0)]
            item={'id':row['id'], 'family':'BANKING77-train-original' if group=='fit'
                  else 'BANKING77-test-original','type':_cell_type(row['id']),'vector':x}
            if group=='fit':item['target']=row['label']%2
            rows.append((group,item))
    return {'schema':SCHEMA,'producer':{'encoder_sha256':ORIGINAL_MODEL_SNAPSHOT,
             'preprocess_sha256':'d'*64,'source_sha256':public['stage_digest'],
             'generation':1,'principal':'research-BANKING77'},
            'dimension':4,'types':['hash0','hash1'],'fit':[r for g,r in rows if g=='fit'],
            'held':[r for g,r in rows if g=='heldout']}


def fake_receipt(public,bundle):
    return {'schema':'hepta.hdcf.original-encoder-feature-producer.v1',
            'feature_bundle_digest':digest(bundle),'source_stage_digest':public['stage_digest'],
            'input_id':public['input_id'],'public_content_digest':digest(public),
            'source_file_sha256':public['source_material_sha256'],'original_source_revision':ORIGINAL_SOURCE,
            'dimension':bundle['dimension'],'token_counts':{'fit':[50]*64,'heldout':[50]*32},
            'model_snapshot_sha256':ORIGINAL_MODEL_SNAPSHOT,
            'original_code_sha':ORIGINAL_CODE_SHA,'observed_encoder_forward_calls':96,
            'observed_encoder_forward_wall_ns':123456789,
            'held_labels_loaded_in_encoder_producer':False,
            'pretrained_publisher_signature_independently_verified':False,
            'production_authorized':False}


class OriginalBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs,cls.observer,cls.selection=prepared()
        cls.pub,cls.priv=stage_original(cls.inputs,cls.observer,cls.selection)
        cls.bundle=fake_feature_bundle(cls.pub)
        cls.trial=train(cls.bundle,steps=24,seed=7347)
        cls.receipt=fake_receipt(cls.pub,cls.bundle)

    def test_stage_blind_source_and_target_population(self):
        self.assertEqual(self.pub['schema'],PUBLIC_SCHEMA)
        self.assertEqual(self.pub['source_revision'],ORIGINAL_SOURCE)
        self.assertEqual(len(self.pub['fit']),64)
        self.assertEqual(len(self.priv['targets']),32)
        self.assertFalse(self.pub['source_family_independence_verified'])
        self.assertTrue(all('label' not in row for row in self.pub['heldout']))
        self.assertFalse(any('text' in row for row in self.priv['targets']))

    def test_mock_review_structural_contract_does_not_claim_real_model(self):
        review=review_original(self.pub,self.priv,self.bundle,self.receipt,self.trial)
        self.assertEqual(review['observed_encoder_forward_calls'],96)
        self.assertFalse(review['pretrained_publisher_signature_independently_verified'])
        self.assertFalse(review['out_of_publisher_future_window_verified'])
        self.assertFalse(review['production_authorized'])
        self.assertEqual(set(review['score']['results']), {'frozen','shared_dense','shared_one_touch','split','swapped'})

    def test_original_held_label_cannot_enter_public_feature_input(self):
        bad=copy.deepcopy(self.pub)
        bad['heldout'][0]['label']=0
        with self.assertRaisesRegex(Denied,'leak'):
            validate_public(bad)

    def test_invalid_class_count_rejected_before_training(self):
        inputs=copy.deepcopy(self.inputs);inputs['fit'][0]['label']=3
        inputs['input_id']=_original_digest({k:v for k,v in inputs.items() if k!='input_id'})
        obs=copy.deepcopy(self.observer);obs['input_id']=inputs['input_id']
        selection=copy.deepcopy(self.selection);selection['input_id']=inputs['input_id']
        with self.assertRaises(Denied):
            stage_original(inputs,obs,selection)

    def test_unexpected_code_checkout_denied(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(Denied):
                _source_checkout(d)

    def test_false_forward_counts_and_receipt_drift_rejected(self):
        for key,value in [('observed_encoder_forward_calls',0),('model_snapshot_sha256','a'*64),
                          ('production_authorized',True),('pretrained_publisher_signature_independently_verified',True),
                          ('feature_bundle_digest','b'*64),('held_labels_loaded_in_encoder_producer',True)]:
            r=copy.deepcopy(self.receipt);r[key]=value
            with self.subTest(key=key),self.assertRaises(Denied):
                review_original(self.pub,self.priv,self.bundle,r,self.trial)

    def test_swapped_private_type_denied(self):
        p=copy.deepcopy(self.priv);p['targets'][0]['type']='evil'
        with self.assertRaises(Denied):
            review_original(self.pub,p,self.bundle,self.receipt,self.trial)

    def test_missing_label_row_and_bundle_drift_denied(self):
        p=copy.deepcopy(self.priv);p['targets'].pop()
        with self.assertRaises(Denied):
            review_original(self.pub,p,self.bundle,self.receipt,self.trial)
        bundle=copy.deepcopy(self.bundle);bundle['held'][0]['vector'][0]+=0.01
        with self.assertRaises(Denied):
            review_original(self.pub,self.priv,bundle,self.receipt,self.trial)


if __name__=='__main__':
    unittest.main()

class MockPhysicalEncoderMechanics(unittest.TestCase):
    """Actual tensor operations, but intentionally NOT a pretrained model trial."""

    @unittest.skipUnless(__import__('importlib').util.find_spec('torch'), 'PyTorch optional for source-only test lane')
    def test_96_original_shape_tensor_forwards_and_no_label_read(self):
        import torch
        from modernbert_feature_bridge import produce_original, review_original
        inputs, observer, selection=prepared()
        pub, priv=stage_original(inputs,observer,selection)

        class Mock:
            dimension=4
            calls=0
            receipt={'snapshot_sha256':ORIGINAL_MODEL_SNAPSHOT,
                     'upstream_revision':'8949b909ec900327062f0ebf497f51aef5e6f0c8',
                     'pretrained_provenance_independently_verified':False}
            def encode(self,row):
                self.calls+=1
                self.last=row
                b=hashlib.sha256(row['state'].encode()).digest()
                return torch.tensor([int.from_bytes(b[i:i+4],'little')/2**32
                                     for i in (0,4,8,12)],dtype=torch.float32),20
            def reverify(self):
                self.reverified=True

        model=Mock()
        bundle,receipt=produce_original(pub,model)
        self.assertTrue(model.reverified)
        self.assertEqual(model.calls,96)
        self.assertEqual(receipt['observed_encoder_forward_calls'],96)
        self.assertFalse(receipt['pretrained_publisher_signature_independently_verified'])
        self.assertEqual(len(receipt['token_counts']['heldout']),32)
        self.assertEqual(bundle['dimension'],4)
        self.assertFalse(any('target' in row for row in bundle['held']))
        t=train(bundle,steps=16)
        r=review_original(pub,priv,bundle,receipt,t)
        self.assertEqual(set(r['score']['results']), {'frozen','shared_dense','shared_one_touch','split','swapped'})
        self.assertFalse(r['production_authorized'])

    def test_768_dim_geometry_is_accepted_without_encoder_claim(self):
        from physical_bank import validate_bundle
        inputs,observer,selection=prepared()
        pub,_=stage_original(inputs,observer,selection)
        b=fake_feature_bundle(pub)
        for split in ('fit','held'):
            for row in b[split]:
                row['vector'].extend([0.0]*764)
        b['dimension']=768
        self.assertEqual(validate_bundle(b)[2],768)
