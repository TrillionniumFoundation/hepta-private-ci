"""One registered secondary temporal GRID descriptor; no primary replacement."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

import numpy as np
import torch

from experiments.hcsn_grid_frontend_r2_20261101 import study as primary
from experiments.hcsn_grid_frontend_r2_20261101 import data_v2 as data

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PRIMARY=HERE.parent/'hcsn_grid_frontend_r2_20261101'
ORIGINAL=PRIMARY/'results/run001'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def guard():
    frozen=json.loads((HERE/'SOURCE_FREEZE.json').read_text());pub=json.loads((HERE/'PUBLICATION_SOURCE.json').read_text())
    if pub['source_freeze_sha256']!=sha(HERE/'SOURCE_FREEZE.json') or not re.fullmatch('[0-9a-f]{40}',pub['source_commit']):raise ValueError('Secondarysourcepublication')
    for name,value in frozen['files'].items():
        if sha(HERE/name)!=value:raise ValueError('Secondarysourceidentity')
    for name,value in frozen['dependencies'].items():
        if sha(ROOT/name)!=value:raise ValueError('Primarydependencyidentity')
    primary.model_guard()
    return frozen


def candidate_guard(out):
    guard();candidate=out/'CANDIDATE_FREEZE.json';pub=json.loads((HERE/'PUBLICATION_CANDIDATE.json').read_text())
    if pub['candidate_sha256']!=sha(candidate) or not re.fullmatch('[0-9a-f]{40}',pub['candidate_commit']):raise ValueError('Secondarycandidatepublication')
    value=json.loads(candidate.read_text())
    if value['source_freeze_sha256']!=sha(HERE/'SOURCE_FREEZE.json') or value['primary_candidate_sha256']!=sha(ORIGINAL/'CANDIDATE_FREEZE.json'):raise ValueError('Secondarycandidateidentity')
    for name,digest in value['files'].items():
        if sha(out/name)!=digest:raise ValueError('Secondaryheadidentity')
    data.permit(ORIGINAL/'CANDIDATE_FREEZE.json',json.loads((PRIMARY/'COHORT_SELECTION.json').read_text()))
    return candidate


def features(role,out,candidate=None):
    guard()
    if role!='train':candidate_guard(Path(candidate).parent)
    from experiments.hcsn_video_pretrained_feasibility_r2_20261101 import encoder
    model=encoder.load();rows=[r for r in json.loads((PRIMARY/'COHORT_SELECTION.json').read_text())['entries'] if r['role']==role]
    out.mkdir(parents=True,exist_ok=False);vectors=[];details=[]
    for i,row in enumerate(rows):
        _,pixels,detail=data.prefix(row,None if role=='train' else ORIGINAL/'CANDIDATE_FREEZE.json')
        frames,logits=encoder.encode(model,pixels);vector=encoder.descriptor(frames,logits)
        if vector.shape!=(3060,) or not np.isfinite(vector).all():raise ValueError('Registeredtemporalfeature')
        vectors.append(vector.astype(np.float32));details.append(detail)
        if (i+1)%16==0:print(json.dumps(dict(role=role,prepared=i+1,total=len(rows))),flush=True)
    primary.save(out/'FEATURES.npz',V=np.stack(vectors),actor=np.asarray([r['speaker'] for r in rows]),member=np.asarray([r['name'] for r in rows]),label=np.asarray([r['sentence_target'] for r in rows]))
    data.write(out/'IDENTITY.json',dict(role=role,features_sha256=sha(out/'FEATURES.npz'),source_freeze_sha256=sha(HERE/'SOURCE_FREEZE.json'),cohort_sha256=sha(PRIMARY/'COHORT_SELECTION.json'),details=details,primary_acquisition_sha256=sha(PRIMARY/'inputs'/f'{role.upper()}_ACQUISITION.json')))


def load(role,directory):
    guard();identity=json.loads((directory/'IDENTITY.json').read_text())
    if identity['role']!=role or identity['source_freeze_sha256']!=sha(HERE/'SOURCE_FREEZE.json') or identity['features_sha256']!=sha(directory/'FEATURES.npz'):raise ValueError('Secondaryfeatureidentity')
    if identity['primary_acquisition_sha256']!=sha(PRIMARY/'inputs'/f'{role.upper()}_ACQUISITION.json'):raise ValueError('Secondaryacquisitionidentity')
    with np.load(directory/'FEATURES.npz',allow_pickle=False) as z:values={k:z[k] for k in z.files}
    original,rows=primary.load(role,PRIMARY/'features'/role)
    if values['V'].shape!=(len(rows),3060) or not np.isfinite(values['V']).all() or not all(np.array_equal(values[k],original[k]) for k in ['actor','member','label']):raise ValueError('Secondarymembertargetidentity')
    return values,original


def train(feature_root,out):
    values,original=load('train',feature_root);out.mkdir(parents=True,exist_ok=False)
    primary.FITS.clear();primary.FIT_PATH=out;actors=np.unique(values['actor'])
    with np.load(ORIGINAL/'TRAIN_OOF.npz',allow_pickle=False) as z:p=z['probabilities'].copy()
    copied=[]
    for name in ['A_classifier.npz','T_classifier.npz','AT_head.npz',*[f'{mod}_fold{k}.npz' for mod in ['A','T'] for k in range(3)]]:
        shutil.copyfile(ORIGINAL/name,out/name);copied.append(dict(file=name,sha256=sha(out/name)))
    for fold in range(3):
        held=np.isin(values['actor'],actors[fold::3]);cp=primary.fit(values['V'][~held],values['label'][~held],.1,f'V/fold{fold}')
        primary.save(out/f'V_fold{fold}.npz',**cp);p[held,1]=primary.infer(cp,values['V'][held])
    primary.save(out/'V_classifier.npz',**primary.fit(values['V'],values['label'],.1,'V/full'))
    q,y,w,a,ordinal,commands=primary.episodes(original,p)
    primary.save(out/'AVT_head.npz',**primary.fit(primary.head_features(q,'AVT'),y,1.,'AVT',w))
    with np.load(ORIGINAL/'TRAIN_OOF.npz',allow_pickle=False) as z:
        if not np.array_equal(p[:,[0,2]],z['probabilities'][:,[0,2]]):raise ValueError('PrimaryATOOFchanged')
    primary.save(out/'TRAIN_OOF.npz',probabilities=p,actor=values['actor'],member=values['member'],label=values['label'],episode_probabilities=q,y=y,weights=w,episode_actor=a,ordinal=ordinal,commands=commands)
    data.write(out/'TRAINING.json',dict(fits=primary.FITS,copied_primary_files=copied,primary_candidate_sha256=sha(ORIGINAL/'CANDIDATE_FREEZE.json'),secondary_features_sha256=sha(feature_root/'FEATURES.npz'),primary_AT_features_sha256=sha(PRIMARY/'features/train/FEATURES.npz'),A_T_OOF_bitwise_reused=True,oof_video_accuracy=float(np.mean((p[:,1]>=.5)==values['label'])),held_media_accessed=False))
    data.write(out/'CANDIDATE_FREEZE.json',dict(source_freeze_sha256=sha(HERE/'SOURCE_FREEZE.json'),primary_candidate_sha256=sha(ORIGINAL/'CANDIDATE_FREEZE.json'),files={p.name:sha(p) for p in out.iterdir() if p.is_file()},held_media_accessed=False))
    print(json.dumps(dict(new_fits=len(primary.FITS),candidate_sha256=sha(out/'CANDIDATE_FREEZE.json'))),flush=True)


def evaluate(role,feature_root,out):
    candidate=candidate_guard(out);values,original=load(role,feature_root)
    p=np.column_stack([primary.infer(dict(np.load(out/f'{name}_classifier.npz',allow_pickle=False)),values['V'] if name=='V' else original[name]) for name in ['A','V','T']])
    q,y,w,actors,ordinal,commands=primary.episodes(original,p);at=primary.infer(dict(np.load(out/'AT_head.npz',allow_pickle=False)),primary.head_features(q,'AT'));new=primary.infer(dict(np.load(out/'AVT_head.npz',allow_pickle=False)),primary.head_features(q,'AVT'))
    oldp=p.copy();oldp[:,1]=primary.infer(dict(np.load(ORIGINAL/'V_classifier.npz',allow_pickle=False)),original['V']);oldq,*_=primary.episodes(original,oldp);old=primary.infer(dict(np.load(ORIGINAL/'AVT_head.npz',allow_pickle=False)),primary.head_features(oldq,'AVT'))
    unique=np.unique(actors);rng=np.random.default_rng(20261105 if role=='development' else 20261106);indices=rng.integers(len(unique),size=(10000,len(unique)));reports={}
    for name,scores,clip_p in [('primary',old,oldp),('secondary',new,p)]:
        differences=[];rates=[]
        for actor in unique:
            ix=actors==actor;rates.append(np.average((scores[ix]>=.5)==y[ix],weights=w[ix]))
            differences.append([np.average(((scores[ix]>=.5)==y[ix]).astype(float)-((at[ix]>=.5)==y[ix]),weights=w[ix]),np.average((scores[ix]-y[ix])**2-(at[ix]-y[ix])**2,weights=w[ix])])
        differences=np.asarray(differences);intervals=np.quantile(differences[indices].mean(1),[.0125,.9875],axis=0).T.tolist();full=np.quantile(np.asarray(rates)[indices].mean(1),[.0125,.9875]).tolist()
        sentence={mod:float(np.mean((clip_p[:,i]>=.5)==values['label'])) for i,mod in enumerate(['A','V','T'])}
        reports[name]=dict(sentence_accuracy=sentence,accuracy=float(np.average((scores>=.5)==y,weights=w)),brier=float(np.average((scores-y)**2,weights=w)),AVT_actor_bootstrap_975=full,AVT_minus_AT=dict(accuracy=float(differences[:,0].mean()),accuracy_actor_bootstrap_975=intervals[0],brier=float(differences[:,1].mean()),brier_actor_bootstrap_975=intervals[1]),actor_differences=differences.tolist(),family_adjusted_gate=bool(sentence['A']>=.9 and sentence['V']>=.9 and sentence['T']>=.99 and full[0]>5/6 and intervals[0][0]>0))
    result=dict(role=role,actors=unique.tolist(),clips=len(values['label']),episodes=len(y),quantiles=[.0125,.9875],interval_coverage=.975,nominal_two_candidate_family_coverage=.95,primary_candidate_sha256=sha(ORIGINAL/'CANDIDATE_FREEZE.json'),secondary_candidate_sha256=sha(candidate),reports=reports,scope='Bothfixedcandidates onsharedregisteredgroups; originalprimary95%reportunchanged; fourconfirmationactors only, descriptivebootstrap notdistribution-freeguarantee; noheld-drivenselection',all_blockers_closed=False,production_activation=False,energy_joules=None)
    primary.save(out/f'{role}_OUTPUTS.npz',clip_probabilities=p,primary_clip_probabilities=oldp,clip_label=values['label'],clip_actor=values['actor'],member=values['member'],episode_probabilities=q,y=y,weights=w,actor=actors,ordinal=ordinal,commands=commands,AT=at,primary_AVT=old,secondary_AVT=new)
    data.write(out/f'{role}_FAMILY_RESULT.json',result);print(json.dumps(result,sort_keys=True),flush=True)


if __name__=='__main__':
    torch.set_num_threads(1)
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['features','train','evaluate']);parser.add_argument('--role',choices=['train','development','confirmation'],default='train');parser.add_argument('--features',type=Path);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--candidate',type=Path);args=parser.parse_args()
    if args.mode=='features':features(args.role,args.out,args.candidate)
    elif args.mode=='train':train(args.features,args.out)
    else:evaluate(args.role,args.features,args.out)
