"""Pure synthetic archive mutation tests. NOT pretrained natural Beans evidence."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from e2_beans_original_zip_review import (
    Reject, ARMS, CLASSES, DATA_REV, DATA_TRAIN, DATA_TEST, MODEL_REVISIONS,
    DINO_WEIGHT_SHA, SCHEMA, canon, digest, original_zip, review_archives,
)


def jsonl(rows):return b''.join(canon(x) for x in rows)


def fake_archives():
    source={};withheld={};producer={};independent={}
    train=[];future=[];classes=[];anchors=[];labels=[];captions=[]
    scope='hepta-e2-natural-beans-retrospective-research'
    for i in range(60):
        phase='train' if i<36 else 'future'
        cid=f'case-{i:03d}';grp=f'origin-{i:03d}'
        name=CLASSES[(i//12)%3] if i<36 else CLASSES[((i-36)//8)%3]
        raw=(b'\xff\xd8'+bytes([i])*92+b'\xff\xd9')
        image_sha=digest(raw)
        observed=i+1 if i<36 else 1000+i
        question='Which disease class does this photographed bean leaf show?'
        record={'case_id':cid,'group_id':grp,'scope':scope,'observed_at':observed,
                'split':phase,'condition':'vision_required',
                'image_path':cid+'.jpg','image_sha256':image_sha,'question':question}
        record['source_sha256']=digest(canon(['hepta.e2.image-case.v1',cid,grp,scope,observed,
                                                'vision_required',image_sha,question]))
        source['source/images/'+cid+'.jpg']=raw
        if phase=='train':
            train.append(record)
            classes.append({'case_id':cid,'class_label':name})
            anchors.append({k:record[k] for k in ('case_id','group_id','scope','observed_at','source_sha256')}
                            | {'target_text':'a bean leaf '+name})
        else:
            future.append(record)
            captions.append({k:record[k] for k in ('case_id','group_id','scope','observed_at')}
                            | {'split':'future','source_input_sha256':image_sha,
                               'target_text':'a plant leaf '+name})
            labels.append({k:record[k] for k in ('case_id','group_id','scope','observed_at','source_sha256')}
                          | {'source_input_sha256':image_sha,'class_label':name})
    src={'train_images.jsonl':train,'future_images.jsonl':future,
         'train_anchors.jsonl':anchors,'train_class.jsonl':classes}
    src_pins={}
    for name,rows in src.items():
        b=jsonl(rows);source['source/'+name]=b;src_pins[name]=digest(b)
    source_manifest={'schema':SCHEMA+'.source-plan','natural_images':True,
        'dataset_repo':'AI-Lab-Makerere/beans','dataset_revision':DATA_REV,
        'train_parquet_sha256':DATA_TRAIN,'phase_time_is_not_original_timestamp':True,
        'train_cases':36,'test_cases':24,'file_sha256s':src_pins,'scope':scope,
        'production_accepted':False,'stem_selected':False,'authority':'DENY_ALL'}
    source['source-manifest.json']=canon(source_manifest)
    tgt_pins={}
    for name,rows in (('future_caption_targets.jsonl',captions),('future_class_targets.jsonl',labels)):
        withheld[name]=jsonl(rows);tgt_pins[name]=digest(withheld[name])
    target_manifest={'schema':SCHEMA+'.withheld-target-plan',
        'source_manifest_sha256':digest(source['source-manifest.json']),
        'original_test_parquet_sha256':DATA_TEST,'file_sha256s':tgt_pins,
        'production_accepted':False,'authority':'DENY_ALL'}
    withheld['target-manifest.json']=canon(target_manifest)
    predictions=[]
    per={a:{'correct':0,'total':24} for a in ARMS}
    paired={a:{'rescued':0,'harmed':0,'both_correct':0,'both_wrong':0} for a in ARMS if a!='vision_prototype'}
    for r,t in zip(future,labels):
        label=t['class_label'];other=CLASSES[(CLASSES.index(label)+1)%3]
        predicted={'fitted':label,'rotated_target_control':other,
                   'unaligned_identity':other,'vision_prototype':label if int(r['case_id'][-3:])%3 else other}
        predictions.append({k:r[k] for k in ('case_id','group_id','scope','observed_at')}
                           | {'source_input_sha256':r['image_sha256'],'predicted_labels':predicted})
        correct={a:predicted[a]==label for a in ARMS}
        for a in ARMS:per[a]['correct']+=int(correct[a])
        for a in paired:
            current,base=correct[a],correct['vision_prototype']
            key='rescued' if current and not base else 'harmed' if base and not current else 'both_correct' if current else 'both_wrong'
            paired[a][key]+=1
    p_doc={'schema':SCHEMA+'.class-predictions','natural_images':True,
           'arms':list(ARMS),'future_labels_seen':False,'stem_selected':False,
           'production_accepted':False,'authority':'DENY_ALL','rows':predictions}
    producer['sealed_class_predictions.json']=canon(p_doc)
    producer['sealed_geometry_predictions.json']=canon({'prediction':'toy'})
    producer['bridge_fit.json']=canon({'train_examples':36,'production_accepted':False,
                'bridges':{'fitted':{},'rotated_target_control':{},'unaligned_identity':{}}})
    producer['granite_train/encoded.jsonl']=jsonl([{'toy':'train'}])
    for phase,n in (('train',36),('future',24)):
        path='vision_'+phase+'/'
        rows=train if phase=='train' else future
        vectors=[]
        for record in rows:
            feat={k:record[k] for k in ('case_id','group_id','scope','observed_at','split',
                                        'condition','image_sha256','question','source_sha256')}
            feat['source']={'modality':'image','input_sha256':record['image_sha256'],
                'encoder_sha256':digest(b'original-DINO-model'), 'values':[1.0]+[0.0]*383}
            vectors.append(feat)
        blob=jsonl(vectors)
        producer[path+'features.jsonl']=blob
        producer[path+'receipt.json']=canon({'phase':phase,
                'source_sha256':digest(source['source/'+phase+'_images.jsonl']),
                'image_count':n,'actual_model_forwards':n,
                'checkpoint_locally_byte_verified':True,'publisher_authenticated':False,
                'labels_seen':False,'production_accepted':False,'authority':'DENY_ALL',
                'encoder_revision':MODEL_REVISIONS['dino'],
                'snapshot_file_sha256s':{'model.safetensors':DINO_WEIGHT_SHA},
                'output_sha256':digest(blob)})
    producer['granite_train/receipt.json']=canon({'phase':'train',
                'model_revision':MODEL_REVISIONS['granite'],
                'model_checkpoint_locally_verified':True,'physical_forwards':18,
                'encoded_sha256':digest(producer['granite_train/encoded.jsonl']),
                'production_accepted':False})
    receipt={'schema':SCHEMA+'.producer-receipt','natural_images':True,
         'dataset_revision':DATA_REV,'dataset_train_sha256':DATA_TRAIN,
         'dino_revision':MODEL_REVISIONS['dino'],'granite_revision':MODEL_REVISIONS['granite'],
         'dino_weights_sha256':DINO_WEIGHT_SHA,'dino_train_forwards':36,'dino_future_forwards':24,
         'granite_train_forwards':18,'source_manifest_sha256':digest(source['source-manifest.json']),
         'test_labels_seen':False,'model_origin_independently_attested':False,
         'stem_selected':False,'production_accepted':False,'authority':'DENY_ALL',
         'fit_sha256':digest(producer['bridge_fit.json']),
         'sealed_geometry_sha256':digest(producer['sealed_geometry_predictions.json']),
         'sealed_class_sha256':digest(producer['sealed_class_predictions.json']),
         'granite_train_encoded_sha256':digest(producer['granite_train/encoded.jsonl'])}
    producer['producer_receipt.json']=canon(receipt)
    independent['independent_class_readout.json']=canon({'schema':SCHEMA+'.independent-class-readout',
        'source_manifest_sha256':digest(source['source-manifest.json']),
        'predictions_sha256':digest(producer['sealed_class_predictions.json']),
        'total_cases':24,'natural_original_images':True,'chronological_future_test':False,
        'independent_ground_truth_owner':False,'production_accepted':False,
        'authority':'DENY_ALL','accuracy':per,'paired_vs_frozen_vision_prototype':paired})
    independent['independent_geometry_readout.json']=canon({
        'physical_future_granite_batched_forwards':12,'true_prospective_window':False,
        'production_accepted':False})
    return {'source':source,'withheld':withheld,'producer':producer,'independent':independent}


def zipup(members, path):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as zf:
        for k, v in members.items():zf.writestr(k,v)
    return digest(Path(path).read_bytes())


class NaturalArchiveReviewTests(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory();self.addCleanup(self.dir.cleanup)
        self.members=fake_archives()
    def run_review(self):
        paths={};pins={}
        for k,files in self.members.items():
            target=Path(self.dir.name)/(k+'.zip')
            pins[k]=zipup(files,target);paths[k]=target
        return review_archives(paths,pins)
    def test_positive_synthetic_60_image_census_no_promotion(self):
        out=self.run_review()
        self.assertEqual(out['cases'],24)
        self.assertEqual(out['correct_per_arm']['fitted'],24)
        self.assertEqual(out['authority'],'DENY_ALL')
        self.assertFalse(out['independent_training_or_model_execution_attestation'])
        self.assertFalse(out['natural_future1_future2_future3_verified'])
        self.assertFalse(out['production_accepted'])
    def test_missing_original_zip(self):
        with self.assertRaises(Reject):review_archives({'source':'no'}, {'source':'a'*64})
    def test_rehash_changed_original_zip_not_equal_pinned_sha(self):
        root=Path(self.dir.name)/'source.zip'
        expected=zipup(self.members['source'],root)
        root.write_bytes(root.read_bytes()+b'tampered')
        with self.assertRaises(Reject):original_zip(root,expected)
    def test_duplicate_zip_member(self):
        p=Path(self.dir.name)/'duplicate.zip'
        with zipfile.ZipFile(p,'w') as z:
            z.writestr('x.txt','a');z.writestr('x.txt','b')
        with self.assertRaises(Reject):original_zip(p,digest(p.read_bytes()))
    def test_zip_traversal(self):
        p=Path(self.dir.name)/'traversal.zip'
        with zipfile.ZipFile(p,'w') as z:z.writestr('../secret','oops')
        with self.assertRaises(Reject):original_zip(p,digest(p.read_bytes()))
    def test_withheld_leak_into_producer(self):
        self.members['producer']['future_class_targets.jsonl']=b'\n'
        with self.assertRaises(Reject):self.run_review()
    def test_image_mutation_without_matching_meta(self):
        k=next(k for k in self.members['source'] if k.startswith('source/images/'))
        self.members['source'][k]=b'changed-but-rehashed-ZIP'
        with self.assertRaises(Reject):self.run_review()
    def test_future_source_jsonl_changed_even_if_zip_rehashed(self):
        self.members['source']['source/future_images.jsonl']+=b'\n'
        with self.assertRaises(Reject):self.run_review()
    def test_target_label_forgery_even_if_manifest_rehashed(self):
        old=self.members['withheld']['future_class_targets.jsonl']
        lines=old.splitlines();label=json.loads(lines[0]);label['class_label']=CLASSES[1]
        lines[0]=canon(label).strip()
        new=b'\n'.join(lines)+b'\n'
        self.members['withheld']['future_class_targets.jsonl']=new
        m=json.loads(self.members['withheld']['target-manifest.json'])
        m['file_sha256s']['future_class_targets.jsonl']=digest(new)
        self.members['withheld']['target-manifest.json']=canon(m)
        with self.assertRaises(Reject):self.run_review()
    def test_missing_four_arms(self):
        doc=json.loads(self.members['producer']['sealed_class_predictions.json'])
        doc['rows'][0]['predicted_labels'].pop('vision_prototype')
        new=canon(doc)
        self.members['producer']['sealed_class_predictions.json']=new
        rec=json.loads(self.members['producer']['producer_receipt.json']);rec['sealed_class_sha256']=digest(new)
        self.members['producer']['producer_receipt.json']=canon(rec)
        with self.assertRaises(Reject):self.run_review()
    def test_wrong_weights_but_consistent_zip(self):
        rec=json.loads(self.members['producer']['producer_receipt.json'])
        rec['dino_weights_sha256']='a'*64
        self.members['producer']['producer_receipt.json']=canon(rec)
        with self.assertRaises(Reject):self.run_review()
    def test_fake_model_authority(self):
        rec=json.loads(self.members['producer']['producer_receipt.json'])
        rec['production_accepted']=True
        self.members['producer']['producer_receipt.json']=canon(rec)
        with self.assertRaises(Reject):self.run_review()
    def test_false_prospective_geometry(self):
        g=json.loads(self.members['independent']['independent_geometry_readout.json'])
        g['true_prospective_window']=True
        self.members['independent']['independent_geometry_readout.json']=canon(g)
        with self.assertRaises(Reject):self.run_review()
    def test_tampered_original_score(self):
        score=json.loads(self.members['independent']['independent_class_readout.json'])
        score['accuracy']['fitted']['correct']=21
        self.members['independent']['independent_class_readout.json']=canon(score)
        with self.assertRaises(Reject):self.run_review()
    def test_swapped_case_reference(self):
        doc=json.loads(self.members['producer']['sealed_class_predictions.json'])
        doc['rows'][0]['source_input_sha256']='a'*64
        new=canon(doc)
        self.members['producer']['sealed_class_predictions.json']=new
        rec=json.loads(self.members['producer']['producer_receipt.json']);rec['sealed_class_sha256']=digest(new)
        self.members['producer']['producer_receipt.json']=canon(rec)
        with self.assertRaises(Reject):self.run_review()
    def test_manifest_target_revision_mismatch(self):
        m=json.loads(self.members['withheld']['target-manifest.json'])
        m['original_test_parquet_sha256']='f'*64
        self.members['withheld']['target-manifest.json']=canon(m)
        with self.assertRaises(Reject):self.run_review()
    def test_missing_real_model_receipt(self):
        del self.members['producer']['granite_train/receipt.json']
        with self.assertRaises(Reject):self.run_review()


    def test_changed_vision_forward_count(self):
        rec=json.loads(self.members['producer']['vision_future/receipt.json'])
        rec['actual_model_forwards']=23
        self.members['producer']['vision_future/receipt.json']=canon(rec)
        with self.assertRaises(Reject):self.run_review()
    def test_changed_vision_source_digest(self):
        rec=json.loads(self.members['producer']['vision_train/receipt.json'])
        rec['source_sha256']='a'*64
        self.members['producer']['vision_train/receipt.json']=canon(rec)
        with self.assertRaises(Reject):self.run_review()
    def test_vision_feature_dimension(self):
        blob=self.members['producer']['vision_future/features.jsonl']
        rows=[json.loads(x) for x in blob.splitlines()]
        rows[0]['source']['values'].pop()
        new=jsonl(rows)
        self.members['producer']['vision_future/features.jsonl']=new
        rec=json.loads(self.members['producer']['vision_future/receipt.json'])
        rec['output_sha256']=digest(new)
        self.members['producer']['vision_future/receipt.json']=canon(rec)
        with self.assertRaises(Reject):self.run_review()
    def test_wrong_vision_feature_case(self):
        rows=[json.loads(x) for x in self.members['producer']['vision_future/features.jsonl'].splitlines()]
        rows[0]['source']['input_sha256']='d'*64
        new=jsonl(rows);self.members['producer']['vision_future/features.jsonl']=new
        rec=json.loads(self.members['producer']['vision_future/receipt.json'])
        rec['output_sha256']=digest(new)
        self.members['producer']['vision_future/receipt.json']=canon(rec)
        with self.assertRaises(Reject):self.run_review()
    def test_future_captions_wrong_case(self):
        rows=[json.loads(x) for x in self.members['withheld']['future_caption_targets.jsonl'].splitlines()]
        rows[0]['source_input_sha256']='b'*64
        new=jsonl(rows);self.members['withheld']['future_caption_targets.jsonl']=new
        rec=json.loads(self.members['withheld']['target-manifest.json'])
        rec['file_sha256s']['future_caption_targets.jsonl']=digest(new)
        self.members['withheld']['target-manifest.json']=canon(rec)
        with self.assertRaises(Reject):self.run_review()
    def test_train_class_missing(self):
        rows=[json.loads(x) for x in self.members['source']['source/train_class.jsonl'].splitlines()]
        rows[0]['case_id']=rows[1]['case_id']
        new=jsonl(rows);self.members['source']['source/train_class.jsonl']=new
        rec=json.loads(self.members['source']['source-manifest.json'])
        rec['file_sha256s']['train_class.jsonl']=digest(new)
        self.members['source']['source-manifest.json']=canon(rec)
        with self.assertRaises(Reject):self.run_review()
    def test_future_targets_leak_into_source(self):
        self.members['source']['source/future_class_targets.jsonl']=b'leaked-target'
        with self.assertRaises(Reject):self.run_review()
    def test_invalid_future_source_group_overlap(self):
        rows=[json.loads(x) for x in self.members['source']['source/future_images.jsonl'].splitlines()]
        rows[0]['group_id']='origin-000'
        new=jsonl(rows);self.members['source']['source/future_images.jsonl']=new
        rec=json.loads(self.members['source']['source-manifest.json'])
        rec['file_sha256s']['future_images.jsonl']=digest(new)
        self.members['source']['source-manifest.json']=canon(rec)
        with self.assertRaises(Reject):self.run_review()
    def test_false_original_independent_source_timestamp(self):
        rec=json.loads(self.members['source']['source-manifest.json'])
        rec['phase_time_is_not_original_timestamp']=False
        self.members['source']['source-manifest.json']=canon(rec)
        with self.assertRaises(Reject):self.run_review()
    def test_invalid_granite_pretrained_revision(self):
        rec=json.loads(self.members['producer']['granite_train/receipt.json'])
        rec['model_revision']='f'*40
        self.members['producer']['granite_train/receipt.json']=canon(rec)
        with self.assertRaises(Reject):self.run_review()

from e2_beans_original_zip_review import review_archives
if __name__=='__main__':unittest.main()
