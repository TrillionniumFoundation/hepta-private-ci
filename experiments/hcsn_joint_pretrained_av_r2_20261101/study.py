"""Prospectively fixed new-audio/new-video relation heads from actor OOF only."""

import argparse
import json
from pathlib import Path
import re
import time

import numpy as np

from experiments.hcsn_audio_pretrained_r2_20261101 import encoder as ae, study as audio
from experiments.hcsn_video_pretrained_feasibility_r2_20261101 import study as video


HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent
AUDIO=ae.HERE/'results/run001'
VIDEO=video.HERE/'results/run001'


def provider_guard(publication=False):
    af=json.loads((AUDIO/'CANDIDATE_FREEZE.json').read_text())
    vf=json.loads((VIDEO/'CANDIDATE_FREEZE.json').read_text())
    if publication:audio.candidate_guard(AUDIO)
    if any(ae.sha(AUDIO/name)!=value for name,value in af['files'].items()):raise ValueError('Audio provider artifact changed')
    if vf['identity']!=video.identity() or any(ae.sha(VIDEO/name)!=value for name,value in vf['files'].items()):
        raise ValueError('Fixed visual provider source/artifact changed')
    if vf['train_features_sha256']!=ae.sha(video.HERE/'inputs/train_features.npz') or vf['train_identity_sha256']!=ae.sha(video.HERE/'inputs/train_IDENTITY.json'):
        raise ValueError('Visual train-feature identity changed')
    return af,vf


def dependencies():
    af,vf=provider_guard()
    paths=[ae.HERE/'SOURCE_FREEZE.json',AUDIO/'CANDIDATE_FREEZE.json',VIDEO/'CANDIDATE_FREEZE.json',
           ae.HERE/'study.py',ae.HERE/'encoder.py',video.HERE/'study.py',video.HERE/'encoder.py',
           video.HERE/'SOURCE_FREEZE.json',video.HERE/'PROTOCOL.json',video.HERE/'SOURCE_IDENTITY.json',video.HERE/'CHECKPOINT.json',
           audio.OLD/'TRAIN_OOF.npz',audio.OLD/'text_encoder.npz',audio.PREVIOUS/'INPUT_IDENTITY.json']
    paths.extend(AUDIO/name for name in af['files']);paths.extend(VIDEO/name for name in vf['files'])
    return {str(p.relative_to(ROOT)):ae.sha(p) for p in paths}


def freeze_source():
    result=dict(schema='hcsn.joint.pretrained.source.v1',created_unix_ns=time.time_ns(),
        source={str((HERE/name).relative_to(ROOT)):ae.sha(HERE/name) for name in ['study.py','PROTOCOL.json']},
        dependencies=dependencies(),audio_candidate_sha256=ae.sha(AUDIO/'CANDIDATE_FREEZE.json'),
        video_candidate_sha256=ae.sha(VIDEO/'CANDIDATE_FREEZE.json'),development_loaded=False)
    ae.write(HERE/'SOURCE_FREEZE.json',result);return result


def source_guard():
    locked=json.loads((HERE/'SOURCE_FREEZE.json').read_text());pub=json.loads((HERE/'SOURCE_PUBLICATION.json').read_text())
    if pub['source_freeze_sha256']!=ae.sha(HERE/'SOURCE_FREEZE.json') or not re.fullmatch(r'[0-9a-f]{40}',pub['source_commit']):
        raise ValueError('Published joint source identity required')
    if any(ae.sha(ROOT/p)!=value for p,value in locked['source'].items()) or dependencies()!=locked['dependencies']:
        raise ValueError('Joint source/provider changed after freeze')
    provider_guard(publication=True);return locked


def clips(path,kind):
    with np.load(path,allow_pickle=False) as z:arrays={k:z[k] for k in ['clip','actor','label',kind]}
    expected={r['clip'] for r in json.loads((ae.HERE/'TRAIN_COHORT.json').read_text())['records']}
    if len(arrays['clip'])!=288 or len(set(arrays['clip'].tolist()))!=288 or set(arrays['clip'].tolist())!=expected:
        raise ValueError('Exact common288 provider OOF clips required')
    if not np.array_equal(arrays['label'],[ae.SENTENCES.index(str(c).split('_')[1]) for c in arrays['clip']]):
        raise ValueError('Provider sentence targets differ')
    if not np.array_equal(arrays['actor'],[str(c).split('_')[0] for c in arrays['clip']]):raise ValueError('Provider actor keys differ')
    if not np.isfinite(arrays[kind]).all() or np.any((arrays[kind]<0)|(arrays[kind]>1)):raise ValueError('Invalid OOF probability')
    return arrays


def map_probability(episodes,rows,scores,modality):
    mapping=dict(zip(rows['clip'].tolist(),scores.tolist(),strict=True))
    return np.asarray([mapping[f"{actor}_{ae.SENTENCES[int(s[modality])]}_{emotion}_XX"]
        for actor,emotion,s in zip(episodes['actor'],episodes['emotion'],episodes['sentence_indices'],strict=True)])


def fold_guard():
    records=[]
    for path in [AUDIO/'TRAINING.json',VIDEO/'TRAINING.json']:
        records.append(json.loads(path.read_text())['folds'])
    for left,right in zip(*records,strict=True):
        for key in ['fold','fit_actors','held_actors']:
            if left[key]!=right[key]:raise ValueError('Provider actor-crossfit partitions differ')
        if len(left['fit_actors'])!=18 or len(left['held_actors'])!=6 or set(left['fit_actors'])&set(left['held_actors']):
            raise ValueError('Incomplete or leaking actor split')


def train(out):
    source_guard();fold_guard();out.mkdir(parents=True,exist_ok=False)
    tick,cpu=time.perf_counter(),time.process_time();a=clips(AUDIO/'TRAIN_OOF.npz','audio');v=clips(VIDEO/'TRAIN_OOF.npz','video')
    episodes=audio.train_arrays();s=episodes['sentence_indices']
    if not np.array_equal(episodes['y'],(s[:,0]==s[:,1])&(s[:,1]==s[:,2])):raise ValueError('Original three-way relation labels required')
    with np.load(audio.OLD/'TRAIN_OOF.npz',allow_pickle=False) as z:
        if not np.array_equal(z['actor'],episodes['actor']) or not np.array_equal(z['sentence_indices'],s) or not np.array_equal(z['y'],episodes['y']):
            raise ValueError('Original nested text OOF episode order differs')
        text=z['probabilities'][:,2].copy()
    p=np.column_stack((map_probability(episodes,a,a['audio'],0),map_probability(episodes,v,v['video'],1),text))
    for name in ['AT_unique','AVT']:
        head=audio.fit(audio.relation_features(p,name),episodes['y'],episodes['sample_weight'],'joint/'+name)
        np.savez_compressed(out/(name+'_head.npz'),**head)
    np.savez_compressed(out/'TRAIN_OOF.npz',probabilities=p,actor=episodes['actor'],y=episodes['y'],
                        sample_weight=episodes['sample_weight'],sentence_indices=s)
    ae.write(out/'TRAINING.json',dict(fits=audio.FITS,audio_candidate_sha256=ae.sha(AUDIO/'CANDIDATE_FREEZE.json'),
        video_candidate_sha256=ae.sha(VIDEO/'CANDIDATE_FREEZE.json'),audio_oof_sha256=ae.sha(AUDIO/'TRAIN_OOF.npz'),
        video_oof_sha256=ae.sha(VIDEO/'TRAIN_OOF.npz'),body_cpu_seconds=time.process_time()-cpu,
        body_wall_seconds=time.perf_counter()-tick,development_loaded=False,new_provider_fitting=False))
    ae.write(out/'CANDIDATE_FREEZE.json',dict(schema='hcsn.joint.pretrained.candidate.v1',
        source_freeze_sha256=ae.sha(HERE/'SOURCE_FREEZE.json'),dependencies=dependencies(),
        files={p.name:ae.sha(p) for p in out.iterdir() if p.is_file()},development_loaded=False,created_unix_ns=time.time_ns()))
    print(json.dumps(dict(fits=len(audio.FITS),candidate_sha256=ae.sha(out/'CANDIDATE_FREEZE.json'))))


def candidate_guard(out):
    source_guard();locked=json.loads((out/'CANDIDATE_FREEZE.json').read_text());pub=json.loads((HERE/'CANDIDATE_PUBLICATION.json').read_text())
    if pub['candidate_freeze_sha256']!=ae.sha(out/'CANDIDATE_FREEZE.json') or not re.fullmatch(r'[0-9a-f]{40}',pub['source_commit']):
        raise ValueError('Published joint all-head candidate required')
    if locked['source_freeze_sha256']!=ae.sha(HERE/'SOURCE_FREEZE.json') or locked['dependencies']!=dependencies() or any(ae.sha(out/name)!=value for name,value in locked['files'].items()):
        raise ValueError('Frozen joint candidate changed')


def evaluate(audio_features,out):
    candidate_guard(out)
    a=audio.load_features(audio_features,'validation');v=video.features('validation')
    wanted={r['clip'] for r in json.loads((audio_features/'COHORT.json').read_text())['records']}
    if len(v['clip'])!=72 or set(v['clip'].tolist())!=wanted:raise ValueError('Common72clip validation set required')
    ap=audio.predict(dict(np.load(AUDIO/'audio_full_head.npz',allow_pickle=False)),a['features'])
    vp=video.predict(dict(np.load(VIDEO/'video_full.npz',allow_pickle=False)),video.encoder.descriptor(v['frame_embeddings'],v['tcn_logits']))
    episodes,features=audio.r1.load('validation')
    tp=audio.r1.predict(dict(np.load(audio.OLD/'text_encoder.npz',allow_pickle=False)),features['text','baseline'])
    p=np.column_stack((map_probability(episodes,a,ap,0),map_probability(episodes,v,vp,1),tp))
    heads={name:dict(np.load(out/(name+'_head.npz'),allow_pickle=False)) for name in ['AT_unique','AVT']}
    scores={name:audio.predict(head,audio.relation_features(p,name)) for name,head in heads.items()}
    y,w,actors=episodes['y'],episodes['sample_weight'],np.unique(episodes['actor']);delta=[]
    for actor in actors:
        ix=episodes['actor']==actor;av,at=scores['AVT'][ix],scores['AT_unique'][ix]
        delta.append([np.average(((av>=.5)==y[ix]).astype(float)-((at>=.5)==y[ix]),weights=w[ix]),
                      np.average((av-y[ix])**2-(at-y[ix])**2,weights=w[ix])])
    delta=np.asarray(delta);rng=np.random.default_rng(20261113);boot=delta[rng.integers(len(actors),size=(10000,len(actors)))].mean(1)
    interval=np.quantile(boot,[.025,.975],axis=0).T.tolist();rng=np.random.default_rng(20261114);shuffled=[]
    for _ in range(100):
        permuted=p.copy()
        for actor in actors:
            ix=np.flatnonzero(episodes['actor']==actor);permuted[ix,1]=p[rng.permutation(ix),1]
        prob=audio.predict(heads['AVT'],audio.relation_features(permuted,'AVT'))
        shuffled.append(float(np.average((prob>=.5)==y,weights=w)))
    aa=float(np.mean((ap>=.5)==a['label']));va=float(np.mean((vp>=.5)==v['label']))
    result=dict(schema='hcsn.joint.pretrained.development.v1',scope='Original six historical development actors only',
        sentence_audio_accuracy=aa,sentence_video_accuracy=va,
        relation={name:dict(accuracy=float(np.average((prob>=.5)==y,weights=w)),brier=float(np.average((prob-y)**2,weights=w))) for name,prob in scores.items()},
        actors=actors.tolist(),actor_differences=delta.tolist(),AVT_minus_AT_unique=dict(accuracy=float(delta[:,0].mean()),brier=float(delta[:,1].mean()),actor_bootstrap_95=interval),
        shuffled_video_accuracy=shuffled,joint_gate=bool(aa>=.9 and va>=.9 and interval[0][0]>0),
        candidate_sha256=ae.sha(out/'CANDIDATE_FREEZE.json'),audio_validation_identity_sha256=ae.sha(audio_features/'IDENTITY.json'),
        video_validation_identity_sha256=ae.sha(video.HERE/'inputs/validation_IDENTITY.json'),
        primary_V_only_attribution_replaced=False,analytic_core_contribution=False,external_independent_confirmation=False,
        energy_joules=None,gpu=None,production_activation=False,all_blockers_closed=False)
    np.savez_compressed(out/'VALIDATION_OUTPUTS.npz',probabilities=p,AT_unique=scores['AT_unique'],AVT=scores['AVT'],actor=episodes['actor'],
        y=y,sample_weight=w,audio=ap,audio_clip=a['clip'],audio_label=a['label'],video=vp,video_clip=v['clip'],video_label=v['label'])
    ae.write(out/'RESULT.json',result);print(json.dumps(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['freeze','train','evaluate']);parser.add_argument('--out',type=Path)
    parser.add_argument('--audio-features',type=Path);args=parser.parse_args()
    if args.phase=='freeze':print(json.dumps(freeze_source(),indent=2))
    elif args.phase=='train':train(args.out)
    else:evaluate(args.audio_features,args.out)
