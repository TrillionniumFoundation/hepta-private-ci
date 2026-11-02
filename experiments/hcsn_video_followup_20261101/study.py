"""Train-only nested actor cross-fitting and video increment development check."""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import resource
import time

import numpy as np
from scipy.fft import dct
from scipy.optimize import minimize
from scipy.special import expit

HERE = Path(__file__).resolve().parent
SLICES = {'audio': slice(0,64), 'video': slice(64,128), 'text':slice(128,140)}
FITS = []


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n'
    with Path(path).open('x') as stream:
        stream.write(payload)


def load(split):
    root = HERE / 'inputs'
    identity = json.loads((HERE/'INPUT_IDENTITY.json').read_text())
    bound = {r['path']:r['sha256'] for r in identity['files']}
    def checked(path):
        assert sha(path) == bound[str(path.relative_to(HERE))], str(path)
        return path
    with np.load(checked(root/'data'/f'{split}.npz'), allow_pickle=False) as arrays:
        a = {k: arrays[k] for k in arrays.files}
    features = {('text','baseline'): a['x'][:,:,SLICES['text']].reshape(len(a['y']),-1)}
    for index, modality in enumerate(('audio','video')):
        loaded = []
        mouth = []
        for actor, emotion, sentences in zip(a['actor'],a['emotion'],a['sentence_indices']):
            name = f"{actor}_{('DFA','IOM')[sentences[index]]}_{emotion}_XX.npz"
            with np.load(checked(root/'av_features'/name), allow_pickle=False) as z:
                loaded.append(z[modality])
            if modality == 'video':
                with np.load(checked(root/'av_mouth_features'/name), allow_pickle=False) as z:
                    mouth.append(z['video'])
        features[modality,'temporal'] = np.asarray(loaded,dtype=np.float64)
        if modality == 'video':
            features[modality,'mouth'] = np.asarray(mouth,dtype=np.float64)
            coeff = features[modality,'mouth'][:,:360].reshape(-1,10,36)
            # Fixed accepted-prefix map; no labels, other clips, or full media.
            transformed = dct(coeff,axis=1,norm='ortho')[:,1:6]
            features[modality,'motion_dct'] = np.concatenate(
                (transformed.reshape(len(coeff),-1),coeff.std(axis=1)),axis=1)
    return a, features


def folds(actors, count):
    unique = np.unique(actors)
    for fold in range(count):
        held = np.isin(actors,unique[fold::count])
        yield np.flatnonzero(~held), np.flatnonzero(held)


def unique(arrays, modality):
    mi = ('audio','video','text').index(modality)
    seen = {}
    for i,key in enumerate(zip(arrays['actor'],arrays['emotion'],arrays['sentence_indices'][:,mi])):
        seen.setdefault(key,i)
    return np.asarray(list(seen.values()))


def fit(x,y,c,weights=None,tag=None):
    tick = time.process_time()
    x = np.asarray(x,dtype=np.float64)
    mean,scale = x.mean(0),np.maximum(x.std(0),1e-8)
    xx = (x-mean)/scale
    weights = np.ones(len(y)) if weights is None else weights
    def objective(beta):
        margin = xx@beta[:-1]+beta[-1]
        loss = np.dot(weights,np.logaddexp(0,margin)-y*margin)+np.dot(beta[:-1],beta[:-1])/(2*c)
        residual = weights*(expit(margin)-y)
        grad = np.r_[xx.T@residual+beta[:-1]/c,residual.sum()]
        return float(loss),grad
    result = minimize(objective,np.zeros(xx.shape[1]+1),jac=True,method='L-BFGS-B',
                      options={'maxiter':300,'ftol':1e-10,'gtol':1e-6})
    FITS.append(dict(tag=tag,rows=len(y),features=x.shape[1],C=c,
                     success=bool(result.success),status=int(result.status),iterations=int(result.nit),
                     gradient_inf=float(np.abs(result.jac).max()),cpu_seconds=time.process_time()-tick))
    return dict(mean=mean,scale=scale,beta=result.x)


def predict(model,x):
    return expit(((x-model['mean'])/model['scale'])@model['beta'][:-1]+model['beta'][-1])


def loss(y,p):
    p = np.clip(p,1e-12,1-1e-12)
    return float(-np.mean(y*np.log(p)+(1-y)*np.log1p(-p)))


def select(features,y,actors,modality,count,tag):
    names = {'audio':['temporal'],'video':['temporal','mouth','motion_dct'],'text':['baseline']}[modality]
    candidates = []
    for name in names:
        for c in ([0.1] if modality=='text' else [0.01,0.1,1.0]):
            x = features[modality,name]
            scores = np.empty(len(y))
            for k,(train,held) in enumerate(folds(actors,count)):
                model = fit(x[train],y[train],c,tag=f'{tag}/{name}/{c}/{k}')
                scores[held] = predict(model,x[held])
            candidates.append(dict(feature=name,C=c,loss=loss(y,scores),
                                   accuracy=float(np.mean((scores>=.5)==y))))
    selected = min(candidates,key=lambda row:row['loss'])
    return selected,candidates


def relation_features(p):
    return np.column_stack([np.prod(p[:,group],axis=1) for n in range(1,4)
                            for group in itertools.combinations(range(3),n)])


def prepare(out):
    train,features = load('train')
    models,selected,probabilities = {},{},np.zeros((len(train['y']),3))
    for mi,mod in enumerate(('audio','video','text')):
        ix = unique(train,mod)
        actors = train['actor'][ix]
        target = train['sentence_indices'][ix,mi]
        fx = {(mod,k):v[ix] for (m,k),v in features.items() if m==mod}
        outer_scores = np.empty(len(ix))
        selection_rows = []
        for k,(fit_ix,held_ix) in enumerate(folds(actors,4)):
            subset = {key:v[fit_ix] for key,v in fx.items()}
            chosen,candidates = select(subset,target[fit_ix],actors[fit_ix],mod,3,f'{mod}/outer{k}/select')
            model = fit(fx[mod,chosen['feature']][fit_ix],target[fit_ix],chosen['C'],tag=f'{mod}/outer{k}/final')
            outer_scores[held_ix] = predict(model,fx[mod,chosen['feature']][held_ix])
            selection_rows.append(dict(fold=k,held_actors=np.unique(actors[held_ix]).tolist(),
                                       fit_actors=np.unique(actors[fit_ix]).tolist(),selected=chosen,candidates=candidates))
        chosen,candidates = select(fx,target,actors,mod,4,f'{mod}/full/select')
        model = fit(fx[mod,chosen['feature']],target,chosen['C'],tag=f'{mod}/full/final')
        np.savez_compressed(out/f'{mod}_encoder.npz',**model)
        models[mod] = model
        mapping = {(a,e,int(s[mi])):p for a,e,s,p in zip(train['actor'][ix],train['emotion'][ix],train['sentence_indices'][ix],outer_scores)}
        probabilities[:,mi] = [mapping[a,e,int(s[mi])] for a,e,s in zip(train['actor'],train['emotion'],train['sentence_indices'])]
        selected[mod] = dict(selected=chosen,candidates=candidates,outer=selection_rows,
                             nested_oof_loss=loss(target,outer_scores),nested_oof_accuracy=float(np.mean((outer_scores>=.5)==target)))
    heads = {}
    for name,visible in [('AT',[0,2]),('AVT',[0,1,2])]:
        p = np.full_like(probabilities,.5);p[:,visible]=probabilities[:,visible]
        model = fit(relation_features(p),train['y'],1.,train['sample_weight'],f'relation/{name}')
        np.savez_compressed(out/f'{name}_head.npz',**model)
        heads[name] = model
    np.savez_compressed(out/'TRAIN_OOF.npz',probabilities=probabilities,actor=train['actor'],y=train['y'],sentence_indices=train['sentence_indices'])
    write(out/'TRAINING.json',dict(selected=selected,fits=FITS,train_data_sha256=sha(HERE/'inputs/data/train.npz'),
                                 validation_loaded=False))
    checkpoints = {p.name:sha(p) for p in sorted(out.glob('*.npz'))}
    write(out/'CANDIDATE_FREEZE.json',dict(source_sha256=sha(__file__),protocol_sha256=sha(HERE/'PROTOCOL.json'),
            training_sha256=sha(out/'TRAINING.json'),input_identity_sha256=sha(HERE/'INPUT_IDENTITY.json'),checkpoints=checkpoints,validation_loaded=False))


def evaluate(out):
    freeze = json.loads((out/'CANDIDATE_FREEZE.json').read_text())
    assert freeze['source_sha256']==sha(__file__) and freeze['protocol_sha256']==sha(HERE/'PROTOCOL.json')
    assert all(sha(out/k)==v for k,v in freeze['checkpoints'].items())
    assert freeze['training_sha256'] == sha(out/'TRAINING.json')
    assert freeze['input_identity_sha256'] == sha(HERE/'INPUT_IDENTITY.json')
    training = json.loads((out/'TRAINING.json').read_text())
    arrays,features = load('validation')
    p = np.column_stack([predict(dict(np.load(out/f'{mod}_encoder.npz')),features[mod,training['selected'][mod]['selected']['feature']]) for mod in ('audio','video','text')])
    scores = {}
    for name,visible in [('AT',[0,2]),('AVT',[0,1,2])]:
        inputs=np.full_like(p,.5);inputs[:,visible]=p[:,visible]
        scores[name] = predict(dict(np.load(out/f'{name}_head.npz')),relation_features(inputs))
    y,w,actors = arrays['y'],arrays['sample_weight'],np.unique(arrays['actor'])
    metrics = {name:dict(accuracy=float(np.average((s>=.5)==y,weights=w)),brier=float(np.average((s-y)**2,weights=w))) for name,s in scores.items()}
    diffs = []
    for actor in actors:
        ix=arrays['actor']==actor
        diffs.append([np.average(((scores['AVT'][ix]>=.5)==y[ix]).astype(float)-((scores['AT'][ix]>=.5)==y[ix]),weights=w[ix]),
                      np.average((scores['AVT'][ix]-y[ix])**2-(scores['AT'][ix]-y[ix])**2,weights=w[ix])])
    diffs=np.asarray(diffs);rng=np.random.default_rng(20261101)
    boot=diffs[rng.integers(len(actors),size=(10000,len(actors)))].mean(1)
    intervals=np.quantile(boot,[.025,.975],axis=0).T.tolist()
    rng=np.random.default_rng(20261102);permutations=[]
    head=dict(np.load(out/'AVT_head.npz'))
    for _ in range(100):
        permuted=p.copy()
        for actor in actors:
            ix=np.flatnonzero(arrays['actor']==actor);permuted[ix,1]=p[rng.permutation(ix),1]
        s=predict(head,relation_features(permuted));permutations.append(float(np.average((s>=.5)==y,weights=w)))
    sentence = {}
    for i,mod in enumerate(('audio','video','text')):
        ix=unique(arrays,mod);sentence[mod]=dict(accuracy=float(np.mean((p[ix,i]>=.5)==arrays['sentence_indices'][ix,i])),count=len(ix))
    np.savez_compressed(out/'VALIDATION_OUTPUTS.npz',probabilities=p,AT=scores['AT'],AVT=scores['AVT'],actor=arrays['actor'],y=y,sample_weight=w,sentence_indices=arrays['sentence_indices'])
    result=dict(scope='Historical six-actor development evaluation; no new independent confirmation',
        sentence=sentence,relation=metrics,actor_differences=diffs.tolist(),actors=actors.tolist(),
        AVT_minus_AT=dict(accuracy=float(diffs[:,0].mean()),accuracy_actor_bootstrap_95=intervals[0],
                          brier=float(diffs[:,1].mean()),brier_actor_bootstrap_95=intervals[1]),
        shuffled_video_accuracy=dict(mean=float(np.mean(permutations)),range=[min(permutations),max(permutations)],all=permutations),
        candidate_freeze_sha256=sha(out/'CANDIDATE_FREEZE.json'),validation_data_sha256=sha(HERE/'inputs/data/validation.npz'),
        video_gate=bool(sentence['video']['accuracy']>=.9 and intervals[0][0]>0),
        genuinely_external_confirmation=False,analytic_core_contribution=False,production_activation=False,all_blockers_closed=False,energy_joules=None)
    write(out/'RESULT.json',result)
    print(json.dumps(result,sort_keys=True))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','evaluate']);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    if args.mode=='prepare':prepare(args.out)
    else:evaluate(args.out)


if __name__=='__main__':
    main()
