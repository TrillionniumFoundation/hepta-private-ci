"""No model/Bridge imports. Independently score original Beans source/target split.

All output is observational, not model selection, prospective learning evidence,
independent publication/ground-truth ownership, or production qualification.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path

SCHEMA='hepta.e2.beans-natural-retrospective.v1'
CLASSES=('angular_leaf_spot','bean_rust','healthy')
ARMS=('fitted','rotated_target_control','unaligned_identity','vision_prototype')
SRC={'train_images.jsonl','future_images.jsonl','train_anchors.jsonl','train_class.jsonl'}
TGT={'future_caption_targets.jsonl','future_class_targets.jsonl'}
TRAIN_SHA='7f905a7323966a58e89b8e839ed656bb869fc82d16a3fadc7dce40972a5f8b19'
TEST_SHA='534a6b0648f585d69b7ec0ad7a7540720d60c8db8106dc6d0508296316f6cb27'
REV='27aa014ce09b193e1a6f58112d4a66e0eddb69c5'

class Reject(ValueError):pass

def sha(x):return hashlib.sha256(x).hexdigest()
def canon(x):return (json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)+'\n').encode()
def digest(x):
    return type(x) is str and len(x)==64 and all(c in '0123456789abcdef' for c in x)
def pairs(v):
    x={}
    for k,a in v:
        if k in x:raise Reject('duplicate JSON field')
        x[k]=a
    return x

def read(path:Path,pin:str|None=None,jsonl=False):
    if path.is_symlink() or not path.is_file() or not 0<path.stat().st_size<=9_000_000:
        raise Reject('invalid path, symlink or size')
    raw=path.read_bytes()
    if pin is not None and (not digest(pin) or sha(raw)!=pin):
        raise Reject('byte digest mismatch')
    def parse(raw_line):
        r=json.loads(raw_line,object_pairs_hook=pairs,
                     parse_constant=lambda _: (_ for _ in ()).throw(Reject('nonfinite JSON')))
        if canon(r)!=raw_line:raise Reject('noncanonical JSON')
        return r
    if not jsonl:return parse(raw)
    if not raw.endswith(b'\n'):raise Reject('noncanonical JSONL')
    return [parse(line+b'\n') for line in raw.splitlines()]

def score(source_root:Path,withheld:Path,producer:Path):
    src_bytes=(source_root/'source-manifest.json').read_bytes()
    src=read(source_root/'source-manifest.json')
    tgt=read(withheld/'target-manifest.json')
    if (type(src) is not dict or set(src)!={'schema','natural_images','dataset_repo','dataset_revision',
               'train_parquet_sha256','phase_time_is_not_original_timestamp','train_cases','test_cases',
               'file_sha256s','scope','production_accepted','stem_selected','authority'}
        or src['schema']!=SCHEMA+'.source-plan' or src['natural_images'] is not True
        or src['dataset_repo']!='AI-Lab-Makerere/beans' or src['dataset_revision']!=REV
        or src['train_parquet_sha256']!=TRAIN_SHA or src['phase_time_is_not_original_timestamp'] is not True
        or src['train_cases']!=36 or src['test_cases']!=24
        or src['production_accepted'] is not False or src['stem_selected'] is not False
        or src['authority']!='DENY_ALL' or type(src['file_sha256s']) is not dict
        or set(src['file_sha256s'])!=SRC):
        raise Reject('source or leaked test target manifest')
    if (type(tgt) is not dict or set(tgt)!={'schema','source_manifest_sha256','original_test_parquet_sha256',
                                          'file_sha256s','production_accepted','authority'}
        or tgt['schema']!=SCHEMA+'.withheld-target-plan'
        or tgt['source_manifest_sha256']!=sha(src_bytes)
        or tgt['original_test_parquet_sha256']!=TEST_SHA
        or tgt['production_accepted'] is not False or tgt['authority']!='DENY_ALL'
        or type(tgt['file_sha256s']) is not dict or set(tgt['file_sha256s'])!=TGT):
        raise Reject('withheld target seal mismatch')
    for pin in list(src['file_sha256s'].values())+list(tgt['file_sha256s'].values()):
        if not digest(pin):raise Reject('bad pinned source digest')
    train=read(source_root/'source'/'train_images.jsonl',src['file_sha256s']['train_images.jsonl'],True)
    future=read(source_root/'source'/'future_images.jsonl',src['file_sha256s']['future_images.jsonl'],True)
    classes=read(source_root/'source'/'train_class.jsonl',src['file_sha256s']['train_class.jsonl'],True)
    labels=read(withheld/'future_class_targets.jsonl',tgt['file_sha256s']['future_class_targets.jsonl'],True)
    prediction_path=producer/'sealed_class_predictions.json';pred_raw=prediction_path.read_bytes()
    receipt=read(producer/'producer_receipt.json')
    if (receipt.get('schema')!=SCHEMA+'.producer-receipt' or receipt.get('natural_images') is not True
        or receipt.get('dataset_revision')!=REV or receipt.get('dataset_train_sha256')!=TRAIN_SHA
        or receipt.get('source_manifest_sha256')!=sha(src_bytes)
        or receipt.get('dino_train_forwards')!=36 or receipt.get('dino_future_forwards')!=24
        or type(receipt.get('granite_train_forwards')) is not int or receipt['granite_train_forwards']<=0
        or receipt.get('sealed_class_sha256')!=sha(pred_raw)
        or receipt.get('test_labels_seen') is not False
        or receipt.get('model_origin_independently_attested') is not False
        or receipt.get('production_accepted') is not False
        or receipt.get('stem_selected') is not False or receipt.get('authority')!='DENY_ALL'):
        raise Reject('producer receipt claims invalid original model or authority')
    pred=read(prediction_path,receipt['sealed_class_sha256'])
    if (type(pred) is not dict or set(pred)!={'schema','natural_images','arms','future_labels_seen',
                                               'stem_selected','production_accepted','authority','rows'}
        or pred['schema']!=SCHEMA+'.class-predictions' or pred['arms']!=list(ARMS)
        or pred['natural_images'] is not True or pred['future_labels_seen'] is not False
        or pred['stem_selected'] is not False or pred['production_accepted'] is not False
        or pred['authority']!='DENY_ALL'):
        raise Reject('prediction missing registered complete four arms')
    if not all(type(x) is list for x in (train,future,classes,labels,pred['rows'])):
        raise Reject('invalid source and target sequence')
    if (len(train),len(future),len(classes),len(labels),len(pred['rows']))!=(36,24,36,24,24):
        raise Reject('sample count mismatch')
    for source_row in train+future:
        expected={'case_id','group_id','scope','observed_at','split','condition',
                  'image_path','image_sha256','question','source_sha256'}
        if type(source_row) is not dict or set(source_row)!=expected:
            raise Reject('unreviewed natural source schema')
        basename=source_row['image_path']
        if (type(basename) is not str or '/' in basename or '..' in basename or
            '\\' in basename or not basename.startswith(source_row['case_id']+'.')):
            raise Reject('unsafe or misbound image path')
        original_image=source_root/'source'/'images'/basename
        if original_image.is_symlink() or not original_image.is_file() or not 50 < original_image.stat().st_size <= 3_000_000:
            raise Reject('invalid original natural-image bytes')
        if sha(original_image.read_bytes())!=source_row['image_sha256']:
            raise Reject('original image source changed')
        claimed=sha(canon(['hepta.e2.image-case.v1',source_row['case_id'],source_row['group_id'],
                           source_row['scope'],source_row['observed_at'],source_row['condition'],
                           source_row['image_sha256'],source_row['question']]))
        if claimed!=source_row['source_sha256']:
            raise Reject('original image and question identity mismatch')
    train_ids={x['case_id'] for x in train};train_groups={x['group_id'] for x in train}
    future_by={x['case_id']:x for x in future};labels_by={x['case_id']:x for x in labels}
    if (len(train_ids)!=36 or len(train_groups)!=36 or len(future_by)!=24 or len(labels_by)!=24 or
        set(future_by)!=set(labels_by) or train_ids&set(future_by) or
        train_groups&{x['group_id'] for x in future} or
        {x['image_sha256'] for x in train}&{x['image_sha256'] for x in future}):
        raise Reject('train/test source collision')
    if (len({x['case_id'] for x in classes})!=36 or set(x['case_id'] for x in classes)!=train_ids or
        sorted([sum(x['class_label']==c for x in classes) for c in CLASSES])!=[12,12,12]):
        raise Reject('train class or budget mismatch')
    tallies={a:{'correct':0,'total':0} for a in ARMS}
    paired={a:{'rescued':0,'harmed':0,'both_correct':0,'both_wrong':0} for a in ARMS if a!='vision_prototype'}
    per_class={a:{c:{'correct':0,'total':0} for c in CLASSES} for a in ARMS}
    seen=set()
    for row in pred['rows']:
        if type(row) is not dict or set(row)!={'case_id','group_id','scope','observed_at',
                  'source_input_sha256','predicted_labels'} or row['case_id'] in seen:
            raise Reject('invalid or duplicated prediction case')
        cid=row['case_id'];seen.add(cid)
        if cid not in future_by or cid not in labels_by:raise Reject('unknown future case')
        srcrow=future_by[cid];label=labels_by[cid]
        if (type(label) is not dict or set(label)!={'case_id','group_id','scope','observed_at',
                          'source_sha256','source_input_sha256','class_label'}
            or label['class_label'] not in CLASSES):raise Reject('malformed independent target')
        for k in ('case_id','group_id','scope','observed_at'):
            if row[k]!=srcrow[k] or label[k]!=srcrow[k]:raise Reject('wrong source and label linkage')
        if (srcrow['scope']!=src['scope'] or srcrow['condition']!='vision_required' or
            label['source_sha256']!=srcrow['source_sha256'] or
            label['source_input_sha256']!=srcrow['image_sha256'] or
            row['source_input_sha256']!=srcrow['image_sha256']):
            raise Reject('wrong future source and label digest')
        answers=row['predicted_labels']
        if type(answers) is not dict or set(answers)!=set(ARMS):raise Reject('missing control arm')
        right={}
        for a in ARMS:
            if answers[a] not in CLASSES:raise Reject('unknown predicted class')
            right[a]=answers[a]==label['class_label']
            tallies[a]['correct']+=int(right[a]);tallies[a]['total']+=1
            per_class[a][label['class_label']]['correct']+=int(right[a]);per_class[a][label['class_label']]['total']+=1
        for a in paired:
            current,baseline=right[a],right['vision_prototype']
            paired[a]['rescued' if current and not baseline else
                      'harmed' if baseline and not current else
                      'both_correct' if current else 'both_wrong']+=1
    if seen!=set(future_by):raise Reject('missing or extra prediction')
    return {'schema':SCHEMA+'.independent-class-readout','natural_original_images':True,
            'source_labels_from_public_dataset':True,'chronological_future_test':False,
            'independent_publisher_attestation':False,'independent_ground_truth_owner':False,
            'model_selection_permitted':False,'production_accepted':False,'authority':'DENY_ALL',
            'source_manifest_sha256':sha(src_bytes),'predictions_sha256':sha(pred_raw),
            'total_cases':24,'accuracy':tallies,'per_class':per_class,
            'paired_vs_frozen_vision_prototype':paired,
            'caveat':'Pinned retrospectively labeled Beans test split; no natural prospective utility evidence.'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--source-root',required=True,type=Path)
    p.add_argument('--withheld',required=True,type=Path)
    p.add_argument('--producer',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();z=score(a.source_root,a.withheld,a.producer)
    if a.output.exists():raise Reject('readout overwrite prohibited')
    a.output.write_bytes(canon(z));print(json.dumps(z,sort_keys=True))

if __name__=='__main__':main()
