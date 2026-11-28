"""A separately sealed, width-64 replication on the exact published MOSI tensors."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parent
CODE=ROOT/'source'
STAGE=ROOT/'fresh'
BASE=ROOT/'reconstructed'
SEEDS=(413,677,941)
RUNGS=(15,60,180)
DESIGNS=[(0,a) for a in ('raw_all','raw_text','raw_av')]+[(64,a) for a in
        ('fp_h','fp_h_text','fp_h_av','fp_h_shuffle','fp_r','random_h','bp_h','transformer','transformer_text')]
BASE_STUDY_SHA='75ec41f336ab20aded67a94ac8c435861fe7fc1e2fc4276e8a5ceb5d4b31d256'
PROTOCOL_SHA='813ac67397570b2cd3410daef3b14b4df35c98596e498d3045448babaa3e6af3'


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(p.read_text())
def write(p,x):
    tmp=p.with_suffix('.tmp')
    tmp.write_text(json.dumps(x,indent=1,sort_keys=True,allow_nan=False)+'\n')
    tmp.replace(p)
def identity():
    if sha(ROOT/'PROSPECTIVE_REPLICATION.md')!=PROTOCOL_SHA or sha(CODE/'SEAL.json')!=BASE_STUDY_SHA:
        raise ValueError('frozen design source differs')
    s=read(CODE/'SEAL.json')
    for k,v in s['code'].items():
        if sha(CODE/k)!=v:raise ValueError(k)
    if sha(CODE/'law.npz')!=s['law_sha256'] or sha(BASE/'test.npz')!=s['test_input_sha256']:
        raise ValueError('historical inputs differ')
    return s


def av_inputs():
    import numpy as np
    dst=STAGE/'av_train_inputs';dst.mkdir(exist_ok=True)
    provenance={}
    for split in ('train','valid'):
        origin=BASE/(split+'.npz');target=dst/(split+'.npz')
        with np.load(origin) as f:rows={k:f[k] for k in f.files}
        x=rows['x'];x[...,:768]=0
        if not target.exists():
            with target.with_suffix('.tmp').open('wb') as f:np.savez_compressed(f,**rows)
            target.with_suffix('.tmp').replace(target)
        with np.load(target) as f:
            if set(rows)!=set(f.files) or any(not np.array_equal(v,f[k]) for k,v in rows.items()):
                raise ValueError('AV mask receipt')
        provenance[split]={'original':sha(origin),'only_text_zeroed':sha(target)}
    write(dst/'manifest.json',provenance)
    return dst


def format_fit(raw_arm,arm,w,s,rawdir):
    old=f'{w}-{raw_arm}-{s}';new=f'{w}-{arm}-{s}'
    receipt=read(rawdir/(old+'.json'))
    receipt['source_fit_json_sha256']=sha(rawdir/(old+'.json'))
    if arm!=raw_arm:receipt['explicit_modality_transform']='zero text coordinates [0:768] on the immutable normalized tensors'
    receipt['arm']=arm
    dest=STAGE/'models'
    for rung in receipt['selected'].values():
        if rung is None:continue
        src=rawdir/rung['file']
        if sha(src)!=rung['sha256']:raise ValueError('state mismatch')
        name=src.name.replace(old,new,1)
        existing=dest/name
        if not existing.exists():os.link(src,existing)
        if sha(existing)!=rung['sha256']:raise ValueError('materialized identity')
        rung['file']=name
    write(dest/(new+'.json'),receipt)


def train_all():
    frozen=identity();sys.path.insert(0,str(CODE));av=av_inputs()
    existing=ROOT/'candidate_replay'/'fits'
    if not (ROOT/'candidate_replay'/'candidate_hash_seal.json').exists():raise ValueError('incomplete developer-only existing campaign')
    for w,arm in DESIGNS:
        rawarm='fp_h' if arm=='fp_h_av' else arm
        for s in SEEDS:
            key=f'{w}-{arm}-{s}'
            if (STAGE/'models'/(key+'.json')).is_file():continue
            old=existing/f'{w}-{rawarm}-{s}.json'
            if old.exists() and arm!='fp_h_av':source=existing
            else:
                source=STAGE/'extra_fits'/arm;source.mkdir(exist_ok=True,parents=True)
                candidate=source/f'{w}-{rawarm}-{s}.json'
                if not candidate.exists():
                    subprocess.run([sys.executable,str(CODE/'train.py'),str(av if arm=='fp_h_av' else BASE),
                              str(CODE/'law.npz'),str(source),str(w),rawarm,str(s)],check=True)
            format_fit(rawarm,arm,w,s,source);print('development',key,flush=True)
    fitsha={};weights={};selected=0
    for w,arm in DESIGNS:
        for s in SEEDS:
            name=f'{w}-{arm}-{s}.json';p=STAGE/'models'/name;fitsha[name]=sha(p);rec=read(p)
            if (rec['width'],rec['arm'],rec['seed'])!=(w,arm,s):raise ValueError('cell')
            for rung in RUNGS:
                pick=rec['selected'][str(rung)]
                choices=[k for k in rec['history'] if k['cpu']<=rung]
                if not choices:
                    if pick is not None:raise ValueError('late selection')
                    continue
                best=min(choices,key=lambda k:(k['dev_video_mae'],k['dev_pooled_mse']))
                if pick is None or (pick['dev_video_mae'],pick['dev_pooled_mse'])!=(best['dev_video_mae'],best['dev_pooled_mse']):
                    raise ValueError('selected by inappropriate outcome')
                sf=STAGE/'models'/pick['file']
                if sha(sf)!=pick['sha256']:raise ValueError('weights')
                weights[sf.name]=pick['sha256'];selected+=1
    if len(fitsha)!=36:raise ValueError('incomplete panel')
    sealed={'kind':'new width-64/pooled 36-cell reconstruction, independent of historical fit identities',
            'historical_seal_sha256':BASE_STUDY_SHA,'fresh_protocol_sha256':PROTOCOL_SHA,'fresh_driver_sha256':sha(Path(__file__)),
            'fits':fitsha,'weights':weights,'model_prefixes':selected,'code':frozen['code'],'law_sha256':frozen['law_sha256'],
            'data_manifest_sha256':sha(BASE/'data.json'),'test_input_sha256':frozen['test_input_sha256'],
            'AV_input_provenance_sha256':sha(av/'manifest.json')}
    p=STAGE/'FRESH_SEAL.json'
    if p.exists() and read(p)!=sealed:raise ValueError('fresh seal altered')
    if not p.exists():write(p,sealed)
    print('sealed',len(fitsha),len(weights),selected,sha(p),flush=True)


def score_one(w,arm,s):
    sys.path.insert(0,str(CODE))
    import cold
    from types import SimpleNamespace
    fd=STAGE/'cold';fd.mkdir(exist_ok=True);name=f'{w}-{arm}-{s}'
    p=fd/(name+'.npz');receipt=fd/(name+'.json')
    if p.exists() and receipt.exists():
        if sha(p)!=read(receipt)['pred_sha256'] or sha(STAGE/'FRESH_SEAL.json')!=read(receipt)['seal_sha256']:raise ValueError('stored scores')
        return
    original=cold.modalities
    def masked(x,k):
        if k=='fp_h_av':
            x=x.clone();x[...,:768]=0;return x
        return original(x,k)
    cold.modalities=masked
    # Start new-process accounting before the original reader. The original
    # implementation separately records import/graph build and prediction cost.
    with tempfile.TemporaryDirectory(dir=fd) as scratch:
        args=SimpleNamespace(seal=STAGE/'FRESH_SEAL.json',law=CODE/'law.npz',models=STAGE/'models',data=BASE,
                             width=w,arm=arm,seed=s,out=Path(scratch))
        cold.run(args)
        src=Path(scratch)/(name+'.npz');sr=src.with_suffix('.json')
        if read(sr)['pred_sha256']!=sha(src):raise ValueError('score mismatch')
        os.replace(src,p);os.replace(sr,receipt)


def verify():
    # Reuse the original independent video/seed-bootstrap and scoring program.
    # Set the list of enrolled widths and add the separately fit AV control.
    sys.path.insert(0,str(CODE));import verify as original
    original.DESIGNS=DESIGNS
    original.SHARED=('fp_h','fp_r','random_h','bp_h','transformer','fp_h_av')
    sys.argv=[str(CODE/'verify.py'),str(STAGE/'models'),str(STAGE/'cold'),
              str(BASE/'data.json'),str(STAGE/'FRESH_SEAL.json'),str(STAGE/'result')]
    original.main()


def run():
    import fcntl
    STAGE.mkdir(exist_ok=True);lock=(STAGE/'run.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    (STAGE/'models').mkdir(exist_ok=True)
    train_all()
    for w,arm in DESIGNS:
        for s in SEEDS:
            subprocess.run([sys.executable,__file__,'--score',str(w),arm,str(s)],check=True)
    verify()
    result=STAGE/'result';s=read(result/'SUMMARY.json')
    files=sorted(f for part in ('models','cold','result') for f in (STAGE/part).glob('*') if f.is_file())
    note={'actual_groups':len(read(STAGE/'FRESH_SEAL.json')['fits']),'score_archives':len(list((STAGE/'cold').glob('*.npz'))),
          'summary_sha256':sha(result/'SUMMARY.json'),'seal_sha256':sha(STAGE/'FRESH_SEAL.json'),
          'scope':s['scope'],'files':{str(p.relative_to(STAGE)):sha(p) for p in files}}
    write(STAGE/'terminal_manifest.json',note)
    print('verified fresh terminal',sha(STAGE/'terminal_manifest.json'),flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--score',nargs=3);a=ap.parse_args()
    if a.score:score_one(int(a.score[0]),a.score[1],int(a.score[2]))
    else:run()
