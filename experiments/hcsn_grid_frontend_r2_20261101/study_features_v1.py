"""Registered GRID frozen AV features, actor crossfit and clean AT/AVT heads."""
import argparse
import hashlib
import itertools
import re
import json
from pathlib import Path
import time

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
import torch

from experiments.hcsn_grid_frontend_r2_20261101 import data_v2 as data

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
FITS=[]


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path,**values):
    with Path(path).open('xb') as stream:np.savez_compressed(stream,**values)


def model_guard():
    frozen=json.loads((HERE/'MODEL_SOURCE_FREEZE.json').read_text())
    publication=json.loads((HERE/'PUBLICATION_MODEL_SOURCE.json').read_text())
    if publication['model_source_freeze_sha256']!=sha(HERE/'MODEL_SOURCE_FREEZE.json') or not re.fullmatch('[0-9a-f]{40}',publication['source_commit']):raise ValueError('Modelsourcepublication')
    for relative,digest in frozen['files'].items():
        if Path(relative).is_absolute() or '..' in Path(relative).parts or sha(HERE/relative)!=digest:raise ValueError('Modelsourceidentity')
    for relative,digest in frozen['dependencies'].items():
        if sha(ROOT/relative)!=digest:raise ValueError('Encoderimplementationidentity')
    data.source_guard()
    return frozen


class Encoders:
    def __init__(self):
        model_guard()
        binding=json.loads((HERE/'ENCODERS.json').read_text())
        audio_path=ROOT.parent/'upstream_audio/wav2vec2_fairseq_base_ls960_asr_ls960.pth'
        video_path=ROOT.parent/'pretrained_lipreading_weights/resnet18_mstcn_video.pth'
        if sha(audio_path)!=binding['audio_checkpoint_sha256'] or sha(video_path)!=binding['video_checkpoint_sha256']:raise ValueError('Encodercheckpointidentity')
        from experiments.hcsn_audio_pretrained_r2_20261101.encoder import FrozenSpeech
        from experiments.hcsn_video_pretrained_feasibility_r2_20261101 import encoder as video
        self.audio=FrozenSpeech(checkpoint=audio_path)
        self.video=video.load()
        self.audio.model.eval().requires_grad_(False);self.video.eval().requires_grad_(False)

    def infer(self,wave,pixels):
        with torch.inference_mode():
            layers,_=self.audio.model.extract_features(torch.from_numpy(wave[None]))
            a=layers[-1][0]
            x=(torch.from_numpy(np.ascontiguousarray(pixels)).float()/255-.421)/.165
            v=self.video(x[None,None],lengths=[25])[0]
            if a.shape!=(49,768) or v.shape!=(25,512):raise ValueError('Frozenfeaturedimensions')
            af=torch.cat((a.mean(0),a.std(0,unbiased=False))).numpy().astype(np.float32)
            vf=torch.cat((v.mean(0),v.std(0,unbiased=False))).numpy().astype(np.float32)
        if not np.isfinite(af).all() or not np.isfinite(vf).all():raise ValueError('Nonfinitefeatures')
        return af,vf


def text_feature(word):
    if word not in ['bin','set']:raise ValueError('Registeredliteralcommand')
    return np.bincount([ord(c)-97 for c in word],minlength=26).astype(np.float32)/len(word)


def features(role,out,candidate=None):
    model_guard()
    cohort=json.loads((HERE/'COHORT_SELECTION.json').read_text())
    if role!='train':data.permit(candidate,cohort)
    rows=[r for r in cohort['entries'] if r['role']==role]
    out.mkdir(parents=True,exist_ok=False)
    encoder=Encoders();arrays={k:[] for k in ['A','V','T']};details=[]
    tick=time.process_time()
    for i,row in enumerate(rows):
        wave,pixels,detail=data.prefix(row,candidate)
        a,v=encoder.infer(wave,pixels)
        arrays['A'].append(a);arrays['V'].append(v);arrays['T'].append(text_feature(row['command']));details.append(detail)
        if (i+1)%16==0:print(json.dumps(dict(role=role,prepared=i+1,total=len(rows))),flush=True)
    save(out/'FEATURES.npz',**{k:np.stack(v) for k,v in arrays.items()},
         actor=np.asarray([r['speaker'] for r in rows]),member=np.asarray([r['name'] for r in rows]),label=np.asarray([r['sentence_target'] for r in rows]))
    data.write(out/'IDENTITY.json',dict(role=role,features_sha256=sha(out/'FEATURES.npz'),cohort_sha256=sha(HERE/'COHORT_SELECTION.json'),
        protocol_sha256=sha(HERE/'PROTOCOL.json'),encoder_manifest_sha256=sha(HERE/'ENCODERS.json'),model_source_freeze_sha256=sha(HERE/'MODEL_SOURCE_FREEZE.json'),
        acquisition_sha256=sha(HERE/'inputs'/f'{role.upper()}_ACQUISITION.json'),details=details,body_cpu_seconds=time.process_time()-tick,
        body_scope='Excludes initial model loading and decoder-child CPU; outer complete-child meter is authoritative',energy_joules=None))


def load(role,directory):
    model_guard();identity=json.loads((directory/'IDENTITY.json').read_text())
    if identity['role']!=role or identity['features_sha256']!=sha(directory/'FEATURES.npz') or identity['cohort_sha256']!=sha(HERE/'COHORT_SELECTION.json') or identity['model_source_freeze_sha256']!=sha(HERE/'MODEL_SOURCE_FREEZE.json'):raise ValueError('Featureidentity')
    if identity['acquisition_sha256']!=sha(HERE/'inputs'/f'{role.upper()}_ACQUISITION.json'):raise ValueError('Acquisitionidentity')
    with np.load(directory/'FEATURES.npz',allow_pickle=False) as z:arrays={k:z[k] for k in z.files}
    rows=[r for r in json.loads((HERE/'COHORT_SELECTION.json').read_text())['entries'] if r['role']==role]
    if arrays['member'].tolist()!=[r['name'] for r in rows] or arrays['actor'].tolist()!=[r['speaker'] for r in rows] or arrays['label'].tolist()!=[r['sentence_target'] for r in rows]:raise ValueError('Explicitcommandtargetidentity')
    if any(arrays[k].shape!=(len(rows),width) or not np.isfinite(arrays[k]).all() for k,width in [('A',1536),('V',1024),('T',26)]):raise ValueError('Featuredimensions')
    return arrays,rows


def fit(x,y,c,tag,weights=None):
    tick=time.process_time();x=np.asarray(x,dtype=float);y=np.asarray(y,dtype=float)
    if set(y)!={0,1}:raise ValueError('Binarycommandtargetrequired')
    w=np.ones(len(y)) if weights is None else np.asarray(weights,dtype=float)
    mean=x.mean(0);scale=np.maximum(x.std(0),1e-8);xx=(x-mean)/scale
    def objective(beta):
        margin=xx@beta[:-1]+beta[-1];residual=w*(expit(margin)-y)
        return float(np.dot(w,np.logaddexp(0,margin)-y*margin)+np.dot(beta[:-1],beta[:-1])/(2*c)),np.r_[xx.T@residual+beta[:-1]/c,residual.sum()]
    r=minimize(objective,np.zeros(x.shape[1]+1),jac=True,method='L-BFGS-B',options={'maxiter':500,'ftol':1e-10,'gtol':1e-6})
    FITS.append(dict(tag=tag,C=c,rows=len(y),features=x.shape[1],success=bool(r.success),status=int(r.status),iterations=int(r.nit),cpu_seconds=time.process_time()-tick))
    if not r.success or not np.isfinite(r.x).all():raise ValueError('Classifieroptimizerfailed; failedrunretained')
    return dict(mean=mean,scale=scale,beta=r.x)


def infer(cp,x):return expit(((x-cp['mean'])/cp['scale'])@cp['beta'][:-1]+cp['beta'][-1])


def head_features(p,name):
    if name=='AT':return np.column_stack((p[:,0],p[:,2],p[:,0]*p[:,2]))
    return np.column_stack([np.prod(p[:,g],axis=1) for n in range(1,4) for g in itertools.combinations(range(3),n)])


def episodes(arrays,probabilities):
    p=[];y=[];weights=[];actors=[];orders=[];commands=[]
    for actor in np.unique(arrays['actor']):
        groups={target:[i for i,(a,t) in enumerate(zip(arrays['actor'],arrays['label'])) if a==actor and t==target] for target in [0,1]}
        for group in groups.values():group.sort(key=lambda i:arrays['member'][i])
        if any(len(group)!=16 for group in groups.values()):raise ValueError('Registered16plus16pairing')
        for ordinal in range(16):
            for a,v,t in itertools.product(range(2),repeat=3):
                p.append([probabilities[groups[a][ordinal],0],probabilities[groups[v][ordinal],1],probabilities[groups[t][ordinal],2]])
                equal=int(a==v==t);y.append(equal);weights.append(3 if equal else 1);actors.append(actor);orders.append(ordinal);commands.append([a,v,t])
    return np.asarray(p),np.asarray(y),np.asarray(weights,dtype=float),np.asarray(actors),np.asarray(orders),np.asarray(commands)


def train(feature_root,out):
    arrays,rows=load('train',feature_root);out.mkdir(parents=True,exist_ok=False)
    actors=np.unique(arrays['actor']);p=np.empty((len(rows),3));records=[]
    if actors.tolist()!=[1,3,4,5,6,7]:raise ValueError('Registeredtrainingactors')
    for index,name in enumerate(['A','V','T']):
        for fold in range(3):
            held=np.isin(arrays['actor'],actors[fold::3]);cp=fit(arrays[name][~held],arrays['label'][~held],.1,f'{name}/fold{fold}')
            p[held,index]=infer(cp,arrays[name][held]);records.append(dict(modality=name,fold=fold,held_actors=actors[fold::3].tolist(),fit_actors=actors[~np.isin(actors,actors[fold::3])].tolist()))
        cp=fit(arrays[name],arrays['label'],.1,f'{name}/full');save(out/f'{name}_classifier.npz',**cp)
    q,y,w,a,ordinal,commands=episodes(arrays,p)
    for name in ['AT','AVT']:save(out/f'{name}_head.npz',**fit(head_features(q,name),y,1.,name,w))
    save(out/'TRAIN_OOF.npz',probabilities=p,member=arrays['member'],actor=arrays['actor'],label=arrays['label'],episode_probabilities=q,y=y,weights=w,episode_actor=a,ordinal=ordinal,commands=commands)
    data.write(out/'TRAINING.json',dict(fits=FITS,folds=records,train_features_sha256=sha(feature_root/'FEATURES.npz'),train_identity_sha256=sha(feature_root/'IDENTITY.json'),
        oof_accuracy={name:float(np.mean((p[:,i]>=.5)==arrays['label'])) for i,name in enumerate(['A','V','T'])},development_loaded=False,confirmation_loaded=False))
    source=json.loads((HERE/'MODEL_SOURCE_FREEZE.json').read_text())
    data.write(out/'CANDIDATE_FREEZE.json',dict(schema='hcsn.grid.candidate.v1',protocol_sha256=sha(HERE/'PROTOCOL.json'),cohort_sha256=sha(HERE/'COHORT_SELECTION.json'),
        source_freeze_sha256=sha(HERE/'SOURCE_FREEZE_V2.json'),model_source_freeze_sha256=sha(HERE/'MODEL_SOURCE_FREEZE.json'),source_files=source['files'],
        files={p.name:sha(p) for p in out.iterdir() if p.is_file()},feature_root=str(feature_root.resolve().relative_to(HERE.resolve())),train_feature_sha256=sha(feature_root/'FEATURES.npz'),
        development_loaded=False,confirmation_loaded=False))
    print(json.dumps(dict(fits=len(FITS),candidate_sha256=sha(out/'CANDIDATE_FREEZE.json'))),flush=True)


def evaluate(role,feature_root,out):
    if role not in ['development','confirmation']:raise ValueError('Evaluationrole')
    model_guard();candidate=out/'CANDIDATE_FREEZE.json';data.permit(candidate,json.loads((HERE/'COHORT_SELECTION.json').read_text()))
    frozen=json.loads(candidate.read_text())
    if frozen['model_source_freeze_sha256']!=sha(HERE/'MODEL_SOURCE_FREEZE.json'):raise ValueError('Modelsourcemismatch')
    arrays,rows=load(role,feature_root)
    probabilities=np.column_stack([infer(dict(np.load(out/f'{name}_classifier.npz',allow_pickle=False)),arrays[name]) for name in ['A','V','T']])
    p,y,w,actors,ordinal,commands=episodes(arrays,probabilities);scores={name:infer(dict(np.load(out/f'{name}_head.npz',allow_pickle=False)),head_features(p,name)) for name in ['AT','AVT']}
    unique=np.unique(actors);differences=[];rates=[]
    for actor in unique:
        ix=actors==actor
        differences.append([np.average(((scores['AVT'][ix]>=.5)==y[ix]).astype(float)-((scores['AT'][ix]>=.5)==y[ix]),weights=w[ix]),np.average((scores['AVT'][ix]-y[ix])**2-(scores['AT'][ix]-y[ix])**2,weights=w[ix])])
        rates.append(np.average((scores['AVT'][ix]>=.5)==y[ix],weights=w[ix]))
    differences=np.asarray(differences);rng=np.random.default_rng(20261105 if role=='development' else 20261106);indices=rng.integers(len(unique),size=(10000,len(unique)))
    intervals=np.quantile(differences[indices].mean(1),[.025,.975],axis=0).T.tolist();full_interval=np.quantile(np.asarray(rates)[indices].mean(1),[.025,.975]).tolist()
    sentence={name:float(np.mean((probabilities[:,i]>=.5)==arrays['label'])) for i,name in enumerate(['A','V','T'])}
    rng=np.random.default_rng(20261107 if role=='development' else 20261108);shuffled=[];head=dict(np.load(out/'AVT_head.npz',allow_pickle=False))
    for _ in range(100):
        altered=p.copy()
        for actor in unique:
            ix=np.flatnonzero(actors==actor);altered[ix,1]=p[rng.permutation(ix),1]
        shuffled.append(float(np.average((infer(head,head_features(altered,'AVT'))>=.5)==y,weights=w)))
    result=dict(role=role,actors=unique.tolist(),clips=len(rows),episodes=len(y),sentence_accuracy=sentence,
        relation={name:dict(accuracy=float(np.average((s>=.5)==y,weights=w)),brier=float(np.average((s-y)**2,weights=w))) for name,s in scores.items()},
        AVT_actor_bootstrap_95=full_interval,AVT_minus_AT=dict(accuracy=float(differences[:,0].mean()),accuracy_actor_bootstrap_95=intervals[0],brier=float(differences[:,1].mean()),brier_actor_bootstrap_95=intervals[1]),
        actor_differences=differences.tolist(),shuffled_video_accuracy=shuffled,
        registered_quality_gate=bool(sentence['A']>=.9 and sentence['V']>=.9 and sentence['T']>=.99 and full_interval[0]>5/6 and intervals[0][0]>0),
        candidate_sha256=sha(candidate),features_sha256=sha(feature_root/'FEATURES.npz'),
        scope='SeparatefixedGRIDcommandconsistencyrecording-group study; fourconfirmationactors only; no globalunseenhumanidentity/newlyrecordedtoday/open-domain/analyticcore/GPUadoptionclaim',
        all_blockers_closed=False,production_activation=False,energy_joules=None)
    save(out/f'{role}_OUTPUTS.npz',clip_probabilities=probabilities,clip_label=arrays['label'],clip_actor=arrays['actor'],member=arrays['member'],episode_probabilities=p,y=y,weights=w,actor=actors,ordinal=ordinal,commands=commands,AT=scores['AT'],AVT=scores['AVT'])
    data.write(out/f'{role}_RESULT.json',result);print(json.dumps(result,sort_keys=True),flush=True)


if __name__=='__main__':
    torch.set_num_threads(1)
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['features','train','evaluate']);parser.add_argument('--role',choices=['train','development','confirmation'],default='train');parser.add_argument('--features',type=Path);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--candidate',type=Path);args=parser.parse_args()
    if args.mode=='features':features(args.role,args.out,args.candidate)
    elif args.mode=='train':train(args.features,args.out)
    else:evaluate(args.role,args.features,args.out)
