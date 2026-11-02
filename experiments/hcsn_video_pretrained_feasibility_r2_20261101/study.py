"""Frozen lipreading descriptors with actor-crossfit visual and AVT heads."""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import time

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
import torch

from . import encoder
from experiments.hcsn_video_raw_r2_20261101 import study as inherited

HERE=Path(__file__).resolve().parent
FITS=[]
FIT_LOG=None


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path,value):
    with Path(path).open('x') as stream:json.dump(value,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')


def identity():
    return dict(protocol_sha256=sha(HERE/'PROTOCOL.json'),source_sha256={name:sha(HERE/name) for name in ['encoder.py','study.py','register.py']},
        source_identity_sha256=sha(HERE/'SOURCE_IDENTITY.json'),checkpoint_receipt_sha256=sha(HERE/'CHECKPOINT.json'),inherited_source_sha256=sha(Path(inherited.__file__)),dependencies=inherited.deps(),cohort_sha256=sha(encoder.COHORT))


def check_source():
    assert identity()==json.loads((HERE/'SOURCE_FREEZE.json').read_text())['identity']


def predict(cp,x):return expit(((x-cp['mean'])/cp['scale'])@cp['beta'][:-1]+cp['beta'][-1])


def fit(x,y,w,tag,maxiter):
    tick,cpu=time.perf_counter(),time.process_time();mean=x.mean(0);scale=np.maximum(x.std(0),1e-8);xx=(x-mean)/scale
    def objective(beta):
        margin=xx@beta[:-1]+beta[-1];residual=w*(expit(margin)-y)
        return float(w@np.logaddexp(0,margin)-w@(y*margin)+.5*(beta[:-1]@beta[:-1])),np.r_[xx.T@residual+beta[:-1],residual.sum()]
    result=minimize(objective,np.zeros(x.shape[1]+1),jac=True,method='L-BFGS-B',options=dict(maxiter=maxiter,ftol=1e-10,gtol=1e-6))
    record=dict(tag=tag,success=bool(result.success),status=int(result.status),message=str(result.message),iterations=int(result.nit),gradient_inf=float(np.max(np.abs(result.jac))),rows=len(y),features=x.shape[1],cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-tick)
    FITS.append(record)
    if FIT_LOG is not None:
        with FIT_LOG.open('a') as stream:stream.write(json.dumps(record,sort_keys=True)+'\n')
    if not result.success:raise ArithmeticError(json.dumps(record))
    return dict(mean=mean,scale=scale,beta=result.x)


def relation(p,name):
    if name=='AT_unique':return np.column_stack((p[:,0],p[:,2],p[:,0]*p[:,2]))
    return np.column_stack([np.prod(p[:,ix],axis=1) for n in range(1,4) for ix in itertools.combinations(range(3),n)])


def extract(split,diagnostic_head=None):
    check_source();assert split in ['train','validation']
    inputs=HERE/'inputs';inputs.mkdir(exist_ok=True);target=inputs/f'{split}_features.npz'
    if target.exists():raise FileExistsError(target)
    rows=sorted([r for r in json.loads(encoder.COHORT.read_text())['records'] if r['split']==split],key=lambda r:r['clip'])
    assert len(rows)==(288 if split=='train' else 72)
    model=encoder.load();frames=[];logits=[];metadata=[];reverse=[];static=[]
    for i,row in enumerate(rows):
        pixels,detail=encoder.decode(row);embedding,score=encoder.encode(model,pixels)
        frames.append(embedding);logits.append(score);metadata.append(detail)
        if diagnostic_head is not None:
            for variant,destination in [(pixels[::-1].copy(),reverse),(np.repeat(pixels[:1],25,axis=0),static)]:
                f,l=encoder.encode(model,variant);destination.append(float(predict(diagnostic_head,encoder.descriptor(f,l)[None])[0]))
        if (i+1)%24==0:print(json.dumps(dict(split=split,encoded=i+1,total=len(rows))),flush=True)
    values=dict(frame_embeddings=np.stack(frames),tcn_logits=np.stack(logits),clip=np.asarray([r['clip'] for r in rows]),actor=np.asarray([r['actor'] for r in rows]),label=np.asarray([('DFA','IOM').index(r['sentence']) for r in rows]))
    if diagnostic_head is not None:values.update(reverse=np.asarray(reverse),static=np.asarray(static))
    np.savez_compressed(target,**values)
    write(inputs/f'{split}_IDENTITY.json',dict(identity=identity(),features_sha256=sha(target),records=metadata,split=split,actor_count=len(set(values['actor'].tolist())),raw_bytes=sum(r['bytes'] for r in rows),pretrained_parameters=sum(p.numel() for p in model.parameters())))
    return values


def features(split):
    record=json.loads((HERE/'inputs'/f'{split}_IDENTITY.json').read_text());path=HERE/'inputs'/f'{split}_features.npz'
    assert record['identity']==identity() and sha(path)==record['features_sha256']
    with np.load(path,allow_pickle=False) as raw:values={k:raw[k] for k in raw.files}
    assert np.array_equal(values['label'],np.asarray([('DFA','IOM').index(str(c).split('_')[1]) for c in values['clip']]))
    return values


def train(out):
    global FIT_LOG
    FIT_LOG=out/'FIT_RECORDS.jsonl'
    if FIT_LOG.exists():raise FileExistsError(FIT_LOG)
    check_source();v=features('train');x=encoder.descriptor(v['frame_embeddings'],v['tcn_logits']).astype(float)
    actors=np.unique(v['actor']);assert len(actors)==24;assert np.array_equal(np.unique(v['label']),[0,1]);oof=np.zeros(len(x));folds=[]
    for fold in range(4):
        held=np.isin(v['actor'],actors[fold::4]);cp=fit(x[~held],v['label'][~held],np.ones((~held).sum()),f'video/fold{fold}',1000)
        np.savez_compressed(out/f'video_fold{fold}.npz',**cp);oof[held]=predict(cp,x[held])
        folds.append(dict(fold=fold,fit_actors=np.unique(v['actor'][~held]).tolist(),held_actors=np.unique(v['actor'][held]).tolist(),accuracy=float(np.mean((oof[held]>=.5)==v['label'][held]))))
    cp=fit(x,v['label'],np.ones(len(x)),'video/full',1000);np.savez_compressed(out/'video_full.npz',**cp)
    a=inherited.arrays('train')
    with np.load(inherited.OLD/'TRAIN_OOF.npz',allow_pickle=False) as old:
        assert np.array_equal(old['actor'],a['actor']) and np.array_equal(old['y'],a['y']) and np.array_equal(old['sentence_indices'],a['sentence_indices'])
        p=old['probabilities'].copy()
    p[:,1]=inherited.map_video(a,v,oof)
    for name in ['AT_unique','AVT']:
        cp=fit(relation(p,name),a['y'],a['sample_weight'],f'relation/{name}',300);np.savez_compressed(out/f'{name}_head.npz',**cp)
    np.savez_compressed(out/'TRAIN_OOF.npz',probabilities=p,video=oof,clip=v['clip'],actor=v['actor'],label=v['label'])
    write(out/'TRAINING.json',dict(fits=FITS,folds=folds,video_oof_accuracy=float(np.mean((oof>=.5)==v['label'])),pretrained_frozen=True,new_neural_training=False,descriptor_features=x.shape[1],validation_loaded=False))
    files={p.name:sha(p) for p in out.iterdir() if p.is_file()}
    write(out/'CANDIDATE_FREEZE.json',dict(identity=identity(),train_features_sha256=sha(HERE/'inputs/train_features.npz'),train_identity_sha256=sha(HERE/'inputs/train_IDENTITY.json'),files=files,validation_loaded=False))
    print(json.dumps(dict(video_oof_accuracy=float(np.mean((oof>=.5)==v['label'])),candidate_freeze_sha256=sha(out/'CANDIDATE_FREEZE.json'))),flush=True)


def evaluate(out):
    check_source();locked=json.loads((out/'CANDIDATE_FREEZE.json').read_text())
    assert locked['identity']==identity() and all(sha(out/name)==value for name,value in locked['files'].items())
    assert locked['train_features_sha256']==sha(HERE/'inputs/train_features.npz') and locked['train_identity_sha256']==sha(HERE/'inputs/train_IDENTITY.json')
    cp=dict(np.load(out/'video_full.npz',allow_pickle=False));v=extract('validation',cp);a=inherited.arrays('validation')
    video=predict(cp,encoder.descriptor(v['frame_embeddings'],v['tcn_logits']));at=inherited.audio_text(a)
    p=np.column_stack((at[:,0],inherited.map_video(a,v,video),at[:,1]));scores={name:predict(dict(np.load(out/f'{name}_head.npz',allow_pickle=False)),relation(p,name)) for name in ['AT_unique','AVT']}
    y,w=a['y'],a['sample_weight'].astype(float);actors=np.unique(a['actor']);difference=[]
    for actor in actors:
        ix=a['actor']==actor
        difference.append([np.average(((scores['AVT'][ix]>=.5)==y[ix]).astype(float)-((scores['AT_unique'][ix]>=.5)==y[ix]),weights=w[ix]),np.average((scores['AVT'][ix]-y[ix])**2-(scores['AT_unique'][ix]-y[ix])**2,weights=w[ix])])
    difference=np.asarray(difference);rng=np.random.default_rng(20261103);bootstrap=difference[rng.integers(len(actors),size=(10000,len(actors)))].mean(1);interval=np.quantile(bootstrap,[.025,.975],axis=0).T.tolist()
    shuffled=[];head=dict(np.load(out/'AVT_head.npz',allow_pickle=False));rng=np.random.default_rng(20261104)
    for _ in range(100):
        permuted=p.copy()
        for actor in actors:
            ix=np.flatnonzero(a['actor']==actor);permuted[ix,1]=p[rng.permutation(ix),1]
        probability=predict(head,relation(permuted,'AVT'));shuffled.append(float(np.average((probability>=.5)==y,weights=w)))
    result=dict(scope='Same historical6actor development panel; no external/actor-pretraining novelty qualification',sentence_video_accuracy=float(np.mean((video>=.5)==v['label'])),video_clips=len(video),
        diagnostics={name:float(np.mean((v[name]>=.5)==v['label'])) for name in ['reverse','static']},
        relation={name:dict(accuracy=float(np.average((probability>=.5)==y,weights=w)),brier=float(np.average((probability-y)**2,weights=w))) for name,probability in scores.items()},
        actors=actors.tolist(),actor_differences=difference.tolist(),AVT_minus_AT_unique=dict(accuracy=float(difference[:,0].mean()),accuracy_actor_bootstrap_95=interval[0],brier=float(difference[:,1].mean()),brier_actor_bootstrap_95=interval[1]),
        shuffled_video_accuracy=shuffled,video_development_gate=bool(np.mean((video>=.5)==v['label'])>=.9 and interval[0][0]>0),
        candidate_freeze_sha256=sha(out/'CANDIDATE_FREEZE.json'),pretraining_actor_overlap='unknown',external_independent_confirmation=False,analytic_core_contribution=False,all_blockers_closed=False,production_activation=False,energy_joules=None)
    np.savez_compressed(out/'VALIDATION_OUTPUTS.npz',probabilities=p,AT_unique=scores['AT_unique'],AVT=scores['AVT'],actor=a['actor'],y=y,sample_weight=w,video=video,reverse=v['reverse'],static=v['static'],clip=v['clip'],video_actor=v['actor'],video_label=v['label'])
    write(out/'RESULT.json',result);print(json.dumps(result,sort_keys=True),flush=True)


if __name__=='__main__':
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['extract_train','train','evaluate']);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    if args.phase=='extract_train':extract('train')
    elif args.phase=='train':train(args.out)
    else:evaluate(args.out)
