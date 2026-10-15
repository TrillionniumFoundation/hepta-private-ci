"""Independent frozen-DINO visual linear probe: TRAIN only, no test labels.

Research extension of Beans E2, not a production model, publisher authentication,
or a matched-compute multimodal proof. Reuses original DINO features; no new
pretrained forward and no source/withheld label conflation.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from e2_beans_original_zip_review import (
    SCHEMA, CLASSES, Reject, require, canon, digest, original_zip, member,
    receipt, json_lines, _validate_source_images, _validate_producer,
)

ALPHA = 0.1  # preregistered; MUST NOT tune on future targets
INPUT_WIDTH = 384
PARAMETER_COUNT = INPUT_WIDTH * len(CLASSES) + len(CLASSES)
PROBE = 'hepta.e2.beans-frozen-vision-linear-probe.v1'


def _read_input(source_path, source_sha, producer_path, producer_sha):
    source = original_zip(source_path, source_sha)
    producer = original_zip(producer_path, producer_sha)
    for coll in (source, producer):
        require(not any(name.endswith(suffix) for name in coll for suffix in (
            'future_class_targets.jsonl', 'future_caption_targets.jsonl', 'target-manifest.json'
        )), 'future target material reached fit/predict job')
    manifest_raw = member(source, 'source-manifest.json')
    manifest = json.loads(manifest_raw)
    try:
        dataset = _validate_source_images(source, manifest)
        _validate_producer(producer, digest(manifest_raw), source, dataset)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise Reject('invalid canonical source or frozen-model material') from exc
    return source, producer, dataset, digest(manifest_raw)


def _features(producer, stage):
    rows = json_lines(member(producer, 'vision_'+stage+'/features.jsonl'))
    seen=set()
    by_case={}
    for row in rows:
        cid=row['case_id']
        require(cid not in seen, 'duplicate frozen source feature')
        seen.add(cid)
        a=np.asarray(row['source']['values'],dtype=np.float64)
        require(a.shape==(INPUT_WIDTH,) and np.all(np.isfinite(a)) and
                0.999<=float(np.linalg.norm(a))<=1.001,
                'invalid 384D pretrained feature')
        by_case[cid] = (row, a)
    require(len(by_case)==(36 if stage=='train' else 24), 'wrong source feature census')
    return by_case


def _solve(source, producer):
    train=_features(producer,'train')
    original = json_lines(member(source, 'source/train_class.jsonl'))
    classes={r['case_id']:r['class_label'] for r in original}
    require(len(classes)==36 and set(classes)==set(train), 'missing train-only supervision')
    ordered=sorted(classes)
    x=np.stack([train[k][1] for k in ordered],axis=0)
    y=np.array([[1.0 if classes[k]==label else 0.0 for label in CLASSES]
                for k in ordered],dtype=np.float64)
    xm=np.mean(x,axis=0)
    ym=np.mean(y,axis=0)
    xc=x-xm
    yc=y-ym
    # Well-conditioned dual ridge, exact single preregistered alpha.
    gram=xc@xc.T + ALPHA*np.eye(len(ordered),dtype=np.float64)
    dual=np.linalg.solve(gram,yc)
    w=xc.T@dual
    b=ym-xm@w
    require(w.shape==(INPUT_WIDTH,3) and b.shape==(3,) and
            np.isfinite(w).all() and np.isfinite(b).all(), 'nonfinite probe coefficients')
    return w,b,ordered


def _decision(scores):
    scores=np.asarray(scores,dtype=np.float64)
    require(scores.shape==(3,) and np.isfinite(scores).all(), 'invalid prediction scores')
    return CLASSES[int(np.argmax(scores))]


def seal(source_path, source_sha, producer_path, producer_sha):
    source,producer,rows,manifest_sha=_read_input(source_path,source_sha,producer_path,producer_sha)
    started=time.perf_counter_ns()
    w,b,train_case_ids=_solve(source,producer)
    fit_ns=time.perf_counter_ns()-started
    model={
        'schema':PROBE+'.model', 'source_zip_sha256':source_sha,
        'producer_zip_sha256':producer_sha,'source_manifest_sha256':manifest_sha,
        'train_classes_sha256':digest(member(source,'source/train_class.jsonl')),
        'alpha':ALPHA,'feature_width':INPUT_WIDTH,'train_cases':len(train_case_ids),
        'parameter_count':PARAMETER_COUNT,
        'weights':w.tolist(),'bias':b.tolist(),
        'trained_on_future_labels':False,'model_origin_independently_attested':False,
        'production_accepted':False,'stem_selected':False,'authority':'DENY_ALL'
    }
    model_sha=digest(canon(model))
    futures=_features(producer,'future')
    src_map={r['case_id']:r for r in rows['future_images.jsonl']}
    require(set(futures)==set(src_map),'missing future source match')
    started=time.perf_counter_ns()
    predicted=[]
    for cid in sorted(futures):
        row,feature=futures[cid]
        src=src_map[cid]
        for k in ('case_id','group_id','scope','observed_at','source_sha256'):
            require(row[k]==src[k], 'frozen probe source drift')
        require(row['source']['input_sha256']==src['image_sha256'], 'image bytes differ')
        predicted.append({
            'case_id':cid,'group_id':src['group_id'],'scope':src['scope'],
            'observed_at':src['observed_at'], 'source_input_sha256':src['image_sha256'],
            'predicted_label':_decision(feature@w+b)
        })
    predict_ns=time.perf_counter_ns()-started
    sealed={
        'schema':PROBE+'.sealed-predictions', 'model_sha256':model_sha,
        'source_zip_sha256':source_sha,'producer_zip_sha256':producer_sha,
        'source_manifest_sha256':manifest_sha,
        'rows':predicted,'future_labels_seen':False,
        'training_wall_ns_self_observed':fit_ns,
        'prediction_wall_ns_self_observed':predict_ns,
        'training_energy_joules':None,'target_host_attested':False,
        'natural_original_images_not_verified_by_probe':True,
        'stem_selected':False,'production_accepted':False,'authority':'DENY_ALL'
    }
    return model,sealed


def write_seal(output_dir, model, predictions):
    folder=Path(output_dir)
    require(not folder.exists() and folder.parent.is_dir(), 'create-only seal directory required')
    folder.mkdir()
    (folder/'probe_model.json').write_bytes(canon(model))
    (folder/'probe_predictions.json').write_bytes(canon(predictions))
    return {'model_sha256':digest(canon(model)),
            'predictions_sha256':digest(canon(predictions)),'authority':'DENY_ALL'}


def cli():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-zip',required=True,type=Path)
    p.add_argument('--source-sha256',required=True)
    p.add_argument('--producer-zip',required=True,type=Path)
    p.add_argument('--producer-sha256',required=True)
    p.add_argument('--output-dir',required=True,type=Path)
    a=p.parse_args()
    model,sealed=seal(a.source_zip,a.source_sha256,a.producer_zip,a.producer_sha256)
    print(json.dumps(write_seal(a.output_dir,model,sealed),sort_keys=True))

if __name__=='__main__':cli()
