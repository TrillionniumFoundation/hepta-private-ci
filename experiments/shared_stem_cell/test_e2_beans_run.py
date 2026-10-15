"""Pure-fake-feature contract checks; NEVER real pretrained model evidence."""
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from e2_beans_source import CLASSES,SCHEMA,canon,sha,prepare_rows
from e2_beans_run import class_predictions,source_preflight,ARMS
from e2_beans_independent_score import score, Reject

def dataset(phase):
    rows=[]
    for cls in range(3):
        for i in range(16):
            im=Image.new('RGB',(64,64),((i*13+cls*41+(1 if phase=='test' else 0))%255,
                                      (i*17+cls*47)%255,(i*31+cls*19)%255))
            b=io.BytesIO();im.save(b,format='PNG')
            rows.append({'image_file_path':f'{phase}/{cls}/{i}.png',
                         'image':{'bytes':b.getvalue(),'path':None},'labels':cls})
    return rows

def onehot(n):return [1.0 if i==n else 0.0 for i in range(384)]

class NaturalComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.train=dataset('train');cls.future=dataset('test')
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'data'
        self.manifest=prepare_rows(self.train,self.future,self.root)
        self.source=self.root/'source';self.withheld=self.root/'withheld';self.producer=Path(self.tmp.name)/'producer'
        self.producer.mkdir()
        self.train_images=[json.loads(x) for x in (self.source/'train_images.jsonl').read_bytes().splitlines()]
        self.future_images=[json.loads(x) for x in (self.source/'future_images.jsonl').read_bytes().splitlines()]
        self.train_classes=[json.loads(x) for x in (self.source/'train_class.jsonl').read_bytes().splitlines()]
        self.future_labels=[json.loads(x) for x in (self.withheld/'future_class_targets.jsonl').read_bytes().splitlines()]
        trlabels={x['case_id']:CLASSES.index(x['class_label']) for x in self.train_classes}
        fulabels={x['case_id']:CLASSES.index(x['class_label']) for x in self.future_labels}
        gtrain=[{'case_id':r['case_id'],'target':{'values':onehot(trlabels[r['case_id']])}}
                for r in self.train_images]
        vtrain=[{'case_id':r['case_id'],'source':{'values':onehot(trlabels[r['case_id']])}}
                for r in self.train_images]
        vfuture=[{'case_id':r['case_id'],'source':{'values':onehot(fulabels[r['case_id']])}}
                 for r in self.future_images]
        geometry={'predictions':[
            {**{k:r[k] for k in ('case_id','group_id','scope','observed_at')},
             'source_input_sha256':r['image_sha256'],
             'predictions':{
               'fitted':onehot(fulabels[r['case_id']]),
               'rotated_target_control':onehot((fulabels[r['case_id']]+1)%3),
               'unaligned_identity':onehot((fulabels[r['case_id']]+2)%3),
             }} for r in self.future_images]}
        self.pred=class_predictions(geometry,gtrain,vtrain,vfuture,self.train_classes)
        pb=canon(self.pred)
        (self.producer/'sealed_class_predictions.json').write_bytes(pb)
        self.receipt={'schema':SCHEMA+'.producer-receipt','natural_images':True,
                     'dataset_revision':'27aa014ce09b193e1a6f58112d4a66e0eddb69c5',
                     'dataset_train_sha256':'7f905a7323966a58e89b8e839ed656bb869fc82d16a3fadc7dce40972a5f8b19',
                     'source_manifest_sha256':sha((self.root/'source-manifest.json').read_bytes()),
                     'dino_train_forwards':36,'dino_future_forwards':24,
                     'granite_train_forwards':10,'sealed_class_sha256':sha(pb),
                     'test_labels_seen':False,'model_origin_independently_attested':False,
                     'stem_selected':False,'production_accepted':False,'authority':'DENY_ALL'}
        (self.producer/'producer_receipt.json').write_bytes(canon(self.receipt))

    def rewrite(self,name,payload):
        (self.producer/name).write_bytes(canon(payload))
        if name=='sealed_class_predictions.json':
            self.receipt['sealed_class_sha256']=sha((self.producer/name).read_bytes())
            self.rewrite('producer_receipt.json',self.receipt)

    def test_positive_fake_features_do_not_promote(self):
        out=score(self.root,self.withheld,self.producer)
        self.assertEqual(out['accuracy']['fitted']['correct'],24)
        self.assertEqual(out['accuracy']['vision_prototype']['correct'],24)
        self.assertEqual(out['accuracy']['rotated_target_control']['correct'],0)
        self.assertEqual(out['paired_vs_frozen_vision_prototype']['fitted']['rescued'],0)
        self.assertFalse(out['chronological_future_test'])
        self.assertFalse(out['production_accepted'])
    def test_lineage_preflight(self):
        _,train,future=source_preflight(self.root)
        self.assertEqual((len(train),len(future)),(36,24))
    def test_baseline_missing_fails(self):
        self.pred['arms'].remove('vision_prototype')
        self.rewrite('sealed_class_predictions.json',self.pred)
        with self.assertRaises(Reject):score(self.root,self.withheld,self.producer)
    def test_duplicate_predict_case_fails(self):
        self.pred['rows'][1]['case_id']=self.pred['rows'][0]['case_id']
        self.rewrite('sealed_class_predictions.json',self.pred)
        with self.assertRaises(Reject):score(self.root,self.withheld,self.producer)
    def test_changed_future_label_fails(self):
        p=self.withheld/'future_class_targets.jsonl'
        p.write_bytes(p.read_bytes().replace(CLASSES[0].encode(),CLASSES[1].encode(),1))
        with self.assertRaises(Reject):score(self.root,self.withheld,self.producer)
    def test_wrong_receipt_model_count_rejected(self):
        self.receipt['dino_future_forwards']=23
        self.rewrite('producer_receipt.json',self.receipt)
        with self.assertRaises(Reject):score(self.root,self.withheld,self.producer)
    def test_expanded_producer_manifest_leaking_future_target_rejected(self):
        manifest=json.loads((self.root/'source-manifest.json').read_text())
        target=json.loads((self.withheld/'target-manifest.json').read_text())
        manifest['file_sha256s']['future_class_targets.jsonl']=target['file_sha256s']['future_class_targets.jsonl']
        (self.root/'source-manifest.json').write_bytes(canon(manifest))
        with self.assertRaises(Reject):score(self.root,self.withheld,self.producer)
    def test_wrong_original_dataset_revision_rejected(self):
        self.receipt['dataset_revision']='a'*40
        self.rewrite('producer_receipt.json',self.receipt)
        with self.assertRaises(Reject):score(self.root,self.withheld,self.producer)
    def test_wrong_source_image_content_rejected(self):
        row=self.future_images[0]
        (self.source/'images'/row['image_path']).write_bytes(b'changed')
        with self.assertRaises(Exception):source_preflight(self.root)
    def test_future_target_scope_collision_rejected(self):
        self.pred['rows'][0]['scope']='wrong-scope'
        self.rewrite('sealed_class_predictions.json',self.pred)
        with self.assertRaises(Reject):score(self.root,self.withheld,self.producer)
    def test_no_attestation_claim_allowed(self):
        self.receipt['model_origin_independently_attested']=True
        self.rewrite('producer_receipt.json',self.receipt)
        with self.assertRaises(Reject):score(self.root,self.withheld,self.producer)
    def test_real_labels_not_read_by_prototype(self):
        self.assertEqual(set(self.pred),{'schema','natural_images','arms','future_labels_seen',
                                          'stem_selected','production_accepted','authority','rows'})
        self.assertTrue(all('class_label' not in r for r in self.pred['rows']))

if __name__=='__main__':unittest.main()
