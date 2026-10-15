"""Natural Beans source -> genuine frozen DINO/Granite -> TRAIN-only Bridge.

Research-only. Prediction receives no test labels, captions or withheld manifest.
Independent evaluator alone may load test targets after predictions are sealed.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
from e2_beans_source import (SCHEMA, DATA_REV, TRAIN_SHA, TEST_SHA, CLASSES, SourceError,
                             canon, sha, put, require)

ARMS=("fitted","rotated_target_control","unaligned_identity","vision_prototype")
SOURCE_NAMES={"train_images.jsonl","future_images.jsonl","train_anchors.jsonl","train_class.jsonl"}
TARGET_NAMES={"future_caption_targets.jsonl","future_class_targets.jsonl"}

def strict_json(path):
    def unique(pairs):
        v={}
        for k,x in pairs:
            require(k not in v,"duplicated JSON field")
            v[k]=x
        return v
    raw=Path(path).read_bytes()
    obj=json.loads(raw,object_pairs_hook=unique)
    require(canon(obj)==raw,"noncanonical JSON manifest")
    return obj

def strict_rows(path):
    raw=Path(path).read_bytes()
    require(raw and len(raw)<=8_000_000 and raw.endswith(b'\n'),"bad bounded rows")
    out=[json.loads(line) for line in raw.splitlines()]
    require(all(canon(row)==line+b'\n' for row,line in zip(out,raw.splitlines())),"noncanonical rows")
    return out

def source_preflight(root):
    src=root/'source'
    m=strict_json(root/'source-manifest.json')
    require(m['schema']==SCHEMA+'.source-plan' and m['natural_images'] is True
            and m['dataset_revision']==DATA_REV and m['train_parquet_sha256']==TRAIN_SHA
            and m['phase_time_is_not_original_timestamp'] is True
            and m['train_cases']==36 and m['test_cases']==24
            and m['production_accepted'] is False and m['stem_selected'] is False
            and m['authority']=='DENY_ALL' and set(m['file_sha256s'])==SOURCE_NAMES,
            'invalid source-only natural dataset manifest')
    for name in SOURCE_NAMES:
        require(sha((src/name).read_bytes())==m['file_sha256s'][name],"changed source-only data: "+name)
    train=strict_rows(src/'train_images.jsonl');test=strict_rows(src/'future_images.jsonl')
    require(len(train)==36 and len(test)==24,"incorrect natural cohort count")
    require({x['group_id'] for x in train}.isdisjoint({x['group_id'] for x in test}),"source group collision")
    require({x['image_sha256'] for x in train}.isdisjoint({x['image_sha256'] for x in test}),"source image overlap")
    require(max(x['observed_at'] for x in train)<min(x['observed_at'] for x in test),"phase ordinal order drift")
    for item in train+test:
        require(item['scope']==m['scope'] and item['condition']=='vision_required',"unknown source scope/condition")
        base=item['image_path']
        require(type(base) is str and '/' not in base and '\\' not in base and '..' not in base
                and base.startswith(item['case_id']+'.'),"unsafe source image path")
        image_file=src/'images'/base
        require(image_file.is_file() and not image_file.is_symlink(),"missing or linked source image")
        require(sha(image_file.read_bytes())==item['image_sha256'],"original image byte drift")
        digest=sha(canon(['hepta.e2.image-case.v1',item['case_id'],item['group_id'],item['scope'],
                          item['observed_at'],item['condition'],item['image_sha256'],item['question']]))
        require(item['source_sha256']==digest,"question/image seal mismatch")
    return m,train,test

def cosine(a,b):
    require(len(a)==len(b)==384,"noncanonical 384D feature width")
    aa=math.fsum(x*x for x in a);bb=math.fsum(x*x for x in b)
    require(aa>0 and bb>0,"zero prototype norm")
    return math.fsum(x*y for x,y in zip(a,b))/math.sqrt(aa*bb)

def class_predictions(geometry,granite_training,vision_training,vision_future,train_classes):
    label_by_case={r['case_id']:r['class_label'] for r in train_classes}
    require(len(label_by_case)==36 and set(label_by_case.values())==set(CLASSES),'missing train labels')
    source_g={r['case_id']:r['target']['values'] for r in granite_training}
    source_v={r['case_id']:r['source']['values'] for r in vision_training}
    require(set(label_by_case)==set(source_g)==set(source_v),'train source identity drift')
    buckets_g={name:[] for name in CLASSES};buckets_v={name:[] for name in CLASSES}
    for case,label in label_by_case.items():
        require(label in CLASSES,'unknown class label')
        buckets_g[label].append(source_g[case]);buckets_v[label].append(source_v[case])
    require(all(len(buckets_g[name])==len(buckets_v[name])==12 for name in CLASSES),
            'imbalanced train-only centroids')
    def centroid(v):return [math.fsum(row[i] for row in v)/len(v) for i in range(384)]
    granite_centers={k:centroid(v) for k,v in buckets_g.items()}
    vision_centers={k:centroid(v) for k,v in buckets_v.items()}
    future_v={r['case_id']:r['source']['values'] for r in vision_future}
    output=[]
    for row in geometry['predictions']:
        case=row['case_id'];require(case in future_v,'unpaired future vision feature')
        answers={}
        for arm in ARMS:
            vec=future_v[case] if arm=='vision_prototype' else row['predictions'][arm]
            centers=vision_centers if arm=='vision_prototype' else granite_centers
            answers[arm]=max(CLASSES,key=lambda name:(cosine(vec,centers[name]),-CLASSES.index(name)))
        output.append({k:row[k] for k in ('case_id','group_id','scope','observed_at','source_input_sha256')}
                      | {'predicted_labels':answers})
    require(len(output)==len(future_v)==24,'class prediction coverage failure')
    return {'schema':SCHEMA+'.class-predictions','natural_images':True,'arms':list(ARMS),
            'future_labels_seen':False,'stem_selected':False,'production_accepted':False,
            'authority':'DENY_ALL','rows':output}

def fit_predict(root,out,dino,granite,granite_profile):
    from e2_real_vision_features import run as vision_run
    from e2_real_vision_bridge_ingress import produce as produce_ingress
    from multimodal_alignment import train,predict
    from multimodal_real_encoder import run_offline
    from multimodal_alignment_contract import load_pinned_jsonl,canonical,write_new
    manifest,train_data,test_data=source_preflight(root)
    source=root/'source';out.mkdir(parents=True,exist_ok=False)
    def image_forward(phase):
        filename='train_images.jsonl' if phase=='train' else 'future_images.jsonl'
        return vision_run(dino,source/'images',source/filename,manifest['file_sha256s'][filename],phase,
                          sha((dino/'config.json').read_bytes()),
                          sha((dino/'preprocessor_config.json').read_bytes()),
                          out/('vision_'+phase))
    rvtrain=image_forward('train');rvfuture=image_forward('future')
    require(rvtrain['actual_model_forwards']==36 and rvfuture['actual_model_forwards']==24,
            'actual original DINO physical forward count missing')
    vi_train=(out/'vision_train'/'features.jsonl').read_bytes()
    vi_future=(out/'vision_future'/'features.jsonl').read_bytes()
    paired=produce_ingress(vi_train,rvtrain,phase='train',anchors=(source/'train_anchors.jsonl').read_bytes())
    future=produce_ingress(vi_future,rvfuture,phase='future')
    pair_sha=put(out/'train_bridge.jsonl',b''.join(canonical(row) for row in paired))
    fut_sha=put(out/'future_bridge.jsonl',b''.join(canonical(row) for row in future))
    profile_sha=sha(granite_profile.read_bytes())
    gtrain=run_offline(granite_profile,profile_sha,granite,out/'train_bridge.jsonl',
                       pair_sha,out/'granite_train','train')
    require(gtrain['model_checkpoint_locally_verified'] is True and
            gtrain['production_accepted'] is False and gtrain['physical_forwards']>0,
            'real frozen Granite forward missing')
    encoded,_=load_pinned_jsonl(out/'granite_train'/'encoded.jsonl',gtrain['encoded_sha256'])
    fit=train(encoded,gtrain['encoded_sha256'])
    fit_sha=write_new(out/'bridge_fit.json',fit)
    future_rows,_=load_pinned_jsonl(out/'future_bridge.jsonl',fut_sha)
    geometry=predict(fit,future_rows,fit_sha,fut_sha)
    geo_sha=write_new(out/'sealed_geometry_predictions.json',geometry)
    vision_train_rows=[json.loads(x) for x in vi_train.splitlines()]
    vision_future_rows=[json.loads(x) for x in vi_future.splitlines()]
    cl=class_predictions(geometry,encoded,vision_train_rows,vision_future_rows,
                         strict_rows(source/'train_class.jsonl'))
    class_sha=write_new(out/'sealed_class_predictions.json',cl)
    receipt={'schema':SCHEMA+'.producer-receipt','natural_images':True,
             'dataset_revision':DATA_REV,'dataset_train_sha256':TRAIN_SHA,
             'dino_revision':rvtrain['encoder_revision'],
             'dino_weights_sha256':rvtrain['snapshot_file_sha256s']['model.safetensors'],
             'dino_train_forwards':36,'dino_future_forwards':24,
             'granite_revision':gtrain['model_revision'],'granite_train_forwards':gtrain['physical_forwards'],
             'granite_train_encoded_sha256':gtrain['encoded_sha256'],
             'source_manifest_sha256':sha((root/'source-manifest.json').read_bytes()),
             'fit_sha256':fit_sha,'sealed_geometry_sha256':geo_sha,
             'sealed_class_sha256':class_sha,'test_labels_seen':False,
             'model_origin_independently_attested':False,
             'stem_selected':False,'production_accepted':False,'authority':'DENY_ALL'}
    put(out/'producer_receipt.json',canon(receipt))
    return receipt

def eval_geometry(produced,withheld,source_manifest,output,granite,profile):
    from multimodal_real_encoder import run_offline
    from multimodal_alignment_evaluator import evaluate
    from multimodal_alignment_contract import load_pinned_document,load_pinned_jsonl,write_new
    src_manifest_bytes=source_manifest.read_bytes()
    target_manifest=strict_json(withheld/'target-manifest.json')
    require(target_manifest['schema']==SCHEMA+'.withheld-target-plan' and
            target_manifest['source_manifest_sha256']==sha(src_manifest_bytes) and
            target_manifest['original_test_parquet_sha256']==TEST_SHA and
            target_manifest['authority']=='DENY_ALL' and
            set(target_manifest['file_sha256s'])==TARGET_NAMES,
            'test label manifest not independently bound')
    future_caption=withheld/'future_caption_targets.jsonl'
    target_sha=target_manifest['file_sha256s']['future_caption_targets.jsonl']
    require(sha(future_caption.read_bytes())==target_sha,'future caption tamper')
    original_receipt=strict_json(produced/'producer_receipt.json')
    geometry_src=produced/'sealed_geometry_predictions.json'
    require(original_receipt['sealed_geometry_sha256']==sha(geometry_src.read_bytes()) and
            original_receipt['test_labels_seen'] is False,'prediction not sealed')
    output.mkdir(parents=True,exist_ok=False)
    profile_sha=sha(profile.read_bytes())
    gfuture=run_offline(profile,profile_sha,granite,future_caption,target_sha,
                        output/'granite_future_targets','future_targets')
    require(gfuture['model_checkpoint_locally_verified'] is True and
            gfuture['production_accepted'] is False,'future genuine Granite target missing')
    geometry=load_pinned_document(geometry_src,original_receipt['sealed_geometry_sha256'])
    targets,_=load_pinned_jsonl(output/'granite_future_targets'/'encoded.jsonl',gfuture['encoded_sha256'])
    report=evaluate(geometry,targets,original_receipt['sealed_geometry_sha256'],gfuture['encoded_sha256'])
    report['physical_future_granite_batched_forwards']=gfuture['physical_forwards']
    report['natural_image_source_retro_only']=True
    report['true_prospective_window']=False
    report['production_accepted']=False
    write_new(output/'independent_geometry_readout.json',report)
    return report

def main():
    p=argparse.ArgumentParser()
    sp=p.add_subparsers(dest='command',required=True)
    fit=sp.add_parser('fit-predict')
    fit.add_argument('--source-root',required=True,type=Path)
    fit.add_argument('--dino',required=True,type=Path)
    fit.add_argument('--granite',required=True,type=Path)
    fit.add_argument('--granite-profile',required=True,type=Path)
    fit.add_argument('--output',required=True,type=Path)
    ev=sp.add_parser('evaluate-geometry')
    ev.add_argument('--producer',required=True,type=Path)
    ev.add_argument('--withheld',required=True,type=Path)
    ev.add_argument('--source-manifest',required=True,type=Path)
    ev.add_argument('--granite',required=True,type=Path)
    ev.add_argument('--granite-profile',required=True,type=Path)
    ev.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    if a.command=='fit-predict':
        print(json.dumps(fit_predict(a.source_root,a.output,a.dino,a.granite,a.granite_profile),sort_keys=True))
    else:
        print(json.dumps(eval_geometry(a.producer,a.withheld,a.source_manifest,a.output,
                                       a.granite,a.granite_profile),sort_keys=True))
if __name__=='__main__':main()
