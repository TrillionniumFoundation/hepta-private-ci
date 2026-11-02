"""Fixed raw mouth pixel temporal classifier, actor cross-fitting and AVT check."""
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
from torch import nn

HERE=Path(__file__).resolve().parent
PREVIOUS=HERE.parent/'hcsn_video_followup_20261101'
OLD=PREVIOUS/'results/run002'
FITS=[]


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path,value):
    with Path(path).open('x') as stream:json.dump(value,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')


def deps():
    paths=[PREVIOUS/'INPUT_IDENTITY.json',OLD/'CANDIDATE_FREEZE.json',OLD/'TRAINING.json',OLD/'TRAIN_OOF.npz',OLD/'audio_encoder.npz',OLD/'text_encoder.npz']
    return {str(p.relative_to(HERE.parent.parent)):sha(p) for p in paths}


def raw(split):
    identity=json.loads((HERE/'inputs'/f'{split}_IDENTITY.json').read_text())
    assert identity['source_sha256']==sha(HERE/'raw_data.py') and identity['protocol_sha256']==sha(HERE/'PROTOCOL.json')
    path=HERE/'inputs'/f'{split}_pixels.npz';assert sha(path)==identity['pixels_sha256']
    with np.load(path,allow_pickle=False) as z:return {k:z[k] for k in z.files}


def transform(pixels):
    # All normalization is per accepted-prefix clip; no fitted data statistics.
    x=torch.tensor(pixels,dtype=torch.float32)/255
    mean=x.mean((1,2,3),keepdim=True);scale=x.std((1,2,3),keepdim=True).clamp_min(.01)
    return torch.stack(((x-mean)/scale,(x-x.mean(1,keepdim=True))/scale),1)


class Visual(nn.Module):
    def __init__(self):
        super().__init__()
        self.network=nn.Sequential(nn.Conv3d(2,8,(3,5,5),stride=(1,2,2),padding=(1,2,2)),nn.SiLU(),
            nn.Conv3d(8,16,3,stride=2,padding=1),nn.SiLU(),nn.Conv3d(16,16,3,stride=2,padding=1),nn.SiLU(),
            nn.Flatten(),nn.Linear(1536,64),nn.SiLU(),nn.Dropout(.15),nn.Linear(64,1))
    def forward(self,x):return self.network(x).squeeze(-1)


def infer(model,x):
    model.eval()
    with torch.no_grad():return torch.cat([model(xx).sigmoid() for xx in x.split(24)]).numpy()


def train_one(x,y,seed,out):
    torch.manual_seed(seed);rng=np.random.default_rng(seed);tick=time.process_time();wall=time.perf_counter()
    model=Visual();optimizer=torch.optim.AdamW(model.parameters(),lr=.003,weight_decay=.001);losses=[]
    labels=torch.tensor(y,dtype=torch.float32)
    for update in range(300):
        model.train();ix=rng.integers(len(y),size=24)
        optimizer.zero_grad(set_to_none=True);loss=nn.functional.binary_cross_entropy_with_logits(model(x[ix]),labels[ix]);loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(),1.);optimizer.step()
        if update%25==0 or update==299:losses.append(dict(update=update+1,loss=float(loss.detach())))
    model.eval();torch.save(model.state_dict(),out)
    return model,dict(seed=seed,updates=300,rows=len(y),parameters=sum(p.numel() for p in model.parameters()),losses=losses,
                     cpu_seconds=time.process_time()-tick,wall_seconds=time.perf_counter()-wall,checkpoint_sha256=sha(out))


def relation_features(p):
    return np.column_stack([np.prod(p[:,group],axis=1) for n in range(1,4) for group in itertools.combinations(range(3),n)])


def head_features(p,name):
    if name=='AT_unique':return np.column_stack((p[:,0],p[:,2],p[:,0]*p[:,2]))
    return relation_features(p)


def fit(x,y,w,tag):
    mean=x.mean(0);scale=np.maximum(x.std(0),1e-8);xx=(x-mean)/scale
    def objective(beta):
        margin=xx@beta[:-1]+beta[-1];residual=w*(expit(margin)-y)
        return float(np.dot(w,np.logaddexp(0,margin)-y*margin)+.5*np.dot(beta[:-1],beta[:-1])),np.r_[xx.T@residual+beta[:-1],residual.sum()]
    r=minimize(objective,np.zeros(x.shape[1]+1),jac=True,method='L-BFGS-B',options={'maxiter':300,'ftol':1e-10,'gtol':1e-6})
    FITS.append(dict(tag=tag,success=bool(r.success),status=int(r.status),iterations=int(r.nit)))
    return dict(mean=mean,scale=scale,beta=r.x)


def predict(model,x):return expit(((x-model['mean'])/model['scale'])@model['beta'][:-1]+model['beta'][-1])


def arrays(split):
    path=PREVIOUS/'inputs/data'/f'{split}.npz'
    rows=json.loads((PREVIOUS/'INPUT_IDENTITY.json').read_text())['files']
    expected=next(r['sha256'] for r in rows if r['path']==f'inputs/data/{split}.npz')
    assert sha(path)==expected
    with np.load(path,allow_pickle=False) as z:return {k:z[k] for k in z.files}


def audio_text(a):
    identity={r['path']:r['sha256'] for r in json.loads((PREVIOUS/'INPUT_IDENTITY.json').read_text())['files']}
    values=[]
    for actor,emotion,sentences in zip(a['actor'],a['emotion'],a['sentence_indices']):
        p=PREVIOUS/'inputs/av_features'/f"{actor}_{('DFA','IOM')[sentences[0]]}_{emotion}_XX.npz"
        assert sha(p)==identity[str(p.relative_to(PREVIOUS))]
        with np.load(p,allow_pickle=False) as z:values.append(z['audio'])
    audio=predict(dict(np.load(OLD/'audio_encoder.npz')),np.asarray(values))
    text=predict(dict(np.load(OLD/'text_encoder.npz')),a['x'][:,:,128:140].reshape(len(a['y']),-1))
    return np.column_stack((audio,text))


def map_video(a,v,scores):
    mapping={clip:score for clip,score in zip(v['clip'],scores)}
    return np.asarray([mapping[f"{actor}_{('DFA','IOM')[sentences[1]]}_{emotion}_XX"] for actor,emotion,sentences in zip(a['actor'],a['emotion'],a['sentence_indices'])])


def train(out):
    v=raw('train');a=arrays('train');x=transform(v['pixels']);actor_set=np.unique(v['actor']);assert len(actor_set)==24
    oof=np.empty(len(x));records=[]
    for fold in range(4):
        held=np.isin(v['actor'],actor_set[fold::4]);model,r=train_one(x[~held],v['label'][~held],5103+fold,out/f'video_fold{fold}.pt')
        oof[held]=infer(model,x[held]);records.append(r|dict(fold=fold,fit_actors=np.unique(v['actor'][~held]).tolist(),held_actors=np.unique(v['actor'][held]).tolist()))
        print(json.dumps(dict(completed_fold=fold,oof_accuracy=float(np.mean((oof[held]>=.5)==v['label'][held])))),flush=True)
    model,r=train_one(x,v['label'],5107,out/'video_full.pt');records.append(r|dict(fold='full'))
    with np.load(OLD/'TRAIN_OOF.npz',allow_pickle=False) as z:
        assert np.array_equal(z['actor'],a['actor']) and np.array_equal(z['y'],a['y']) and np.array_equal(z['sentence_indices'],a['sentence_indices'])
        p=z['probabilities'].copy()
    p[:,1]=map_video(a,v,oof)
    for name,visible in [('AT',[0,2]),('AT_unique',[0,2]),('AVT',[0,1,2])]:
        masked=np.full_like(p,.5);masked[:,visible]=p[:,visible]
        cp=fit(head_features(masked,name),a['y'],a['sample_weight'],name);np.savez_compressed(out/f'{name}_head.npz',**cp)
    np.savez_compressed(out/'TRAIN_OOF.npz',probabilities=p,video=oof,clip=v['clip'],actor=v['actor'],label=v['label'])
    write(out/'TRAINING.json',dict(visual_fits=records,relation_fits=FITS,nested_video_oof_accuracy=float(np.mean((oof>=.5)==v['label'])),validation_loaded=False,
        torch_version=torch.__version__,numpy_version=np.__version__))
    files={p.name:sha(p) for p in out.iterdir() if p.is_file()}
    write(out/'CANDIDATE_FREEZE.json',dict(source_sha256=sha(__file__),raw_source_sha256=sha(HERE/'raw_data.py'),protocol_sha256=sha(HERE/'PROTOCOL.json'),
        train_input_sha256=sha(HERE/'inputs/train_pixels.npz'),train_identity_sha256=sha(HERE/'inputs/train_IDENTITY.json'),dependencies=deps(),files=files,validation_loaded=False))


def evaluate(out):
    frozen=json.loads((out/'CANDIDATE_FREEZE.json').read_text())
    assert frozen['source_sha256']==sha(__file__) and frozen['raw_source_sha256']==sha(HERE/'raw_data.py') and frozen['protocol_sha256']==sha(HERE/'PROTOCOL.json')
    assert frozen['dependencies']==deps() and all(sha(out/name)==value for name,value in frozen['files'].items())
    assert frozen['train_identity_sha256']==sha(HERE/'inputs/train_IDENTITY.json') and frozen['train_input_sha256']==sha(HERE/'inputs/train_pixels.npz')
    v=raw('validation');a=arrays('validation');model=Visual();model.load_state_dict(torch.load(out/'video_full.pt',weights_only=True));x=transform(v['pixels'])
    original=infer(model,x);reverse=infer(model,x.flip(2));static=infer(model,transform(np.repeat(v['pixels'][:,:1],16,axis=1)))
    at=audio_text(a);p=np.column_stack((at[:,0],map_video(a,v,original),at[:,1]));scores={}
    for name,visible in [('AT',[0,2]),('AT_unique',[0,2]),('AVT',[0,1,2])]:
        masked=np.full_like(p,.5);masked[:,visible]=p[:,visible];scores[name]=predict(dict(np.load(out/f'{name}_head.npz')),head_features(masked,name))
    y,w,actors=a['y'],a['sample_weight'].astype(float),np.unique(a['actor']);differences=[]
    for actor in actors:
        ix=a['actor']==actor
        differences.append([np.average(((scores['AVT'][ix]>=.5)==y[ix]).astype(float)-((scores['AT_unique'][ix]>=.5)==y[ix]),weights=w[ix]),np.average((scores['AVT'][ix]-y[ix])**2-(scores['AT_unique'][ix]-y[ix])**2,weights=w[ix])])
    differences=np.asarray(differences);rng=np.random.default_rng(20261103);boot=differences[rng.integers(len(actors),size=(10000,len(actors)))].mean(1)
    intervals=np.quantile(boot,[.025,.975],axis=0).T.tolist();rng=np.random.default_rng(20261104);permutations=[]
    cp=dict(np.load(out/'AVT_head.npz'))
    for _ in range(100):
        permuted=p.copy()
        for actor in actors:
            ix=np.flatnonzero(a['actor']==actor);permuted[ix,1]=p[rng.permutation(ix),1]
        s=predict(cp,relation_features(permuted));permutations.append(float(np.average((s>=.5)==y,weights=w)))
    result=dict(scope='Historical6actor development; independent external population not acquired',sentence_video_accuracy=float(np.mean((original>=.5)==v['label'])),
        sentence_clips=len(v['label']),diagnostics={name:float(np.mean((prob>=.5)==v['label'])) for name,prob in [('reverse',reverse),('static',static)]},
        relation={name:dict(accuracy=float(np.average((s>=.5)==y,weights=w)),brier=float(np.average((s-y)**2,weights=w))) for name,s in scores.items()},
        actors=actors.tolist(),actor_differences=differences.tolist(),AVT_minus_AT_unique=dict(accuracy=float(differences[:,0].mean()),accuracy_actor_bootstrap_95=intervals[0],brier=float(differences[:,1].mean()),brier_actor_bootstrap_95=intervals[1]),
        shuffled_video_accuracy=permutations,video_gate=bool(np.mean((original>=.5)==v['label'])>=.9 and intervals[0][0]>0),candidate_freeze_sha256=sha(out/'CANDIDATE_FREEZE.json'),
        all_blockers_closed=False,external_independent_confirmation=False,analytic_core_contribution=False,production_activation=False,energy_joules=None)
    np.savez_compressed(out/'VALIDATION_OUTPUTS.npz',probabilities=p,AT=scores['AT'],AVT=scores['AVT'],actor=a['actor'],y=y,sample_weight=w,
                        video=original,reverse=reverse,static=static,clip=v['clip'],video_actor=v['actor'],video_label=v['label'])
    write(out/'RESULT.json',result);print(json.dumps(result,sort_keys=True),flush=True)


if __name__=='__main__':
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['train','evaluate']);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    if args.mode=='train':train(args.out)
    else:evaluate(args.out)
