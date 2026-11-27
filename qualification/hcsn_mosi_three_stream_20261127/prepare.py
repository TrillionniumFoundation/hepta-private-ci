"""Produce split-isolated six-step MOSI arrays, with train-only scaling and imputation."""
import argparse
import json
import time
from pathlib import Path
import numpy as np
from source import load,official,sha,SDK_COMMIT,MMSA_SHA

COLUMNS=(('text',0,768),('audio',768,773),('vision',773,793))


def grouped(values,n=6):
    m=len(values)
    ids=np.array_split(np.arange(m),n)
    rows=[]
    for no,b in enumerate(ids):
        if len(b)==0:b=np.array([min(m-1,int((no+.5)*m/n))])
        cut=values[b];finite=np.isfinite(cut)
        numerator=np.where(finite,cut,0.).sum(0,dtype='float64');den=finite.sum(0)
        row=np.full(len(den),np.nan);np.divide(numerator,den,out=row,where=den>0)
        rows.append(row)
    return np.asarray(rows,dtype='float32')


def main():
    a=argparse.ArgumentParser();a.add_argument('raw',type=Path);a.add_argument('folds',type=Path);a.add_argument('out',type=Path);p=a.parse_args()
    wall=time.perf_counter();cpu=time.process_time();arrays=load(p.raw);groups=official(p.folds);p.out.mkdir(exist_ok=True,parents=True)
    read=time.perf_counter()-wall
    xtrain=None;splits={};keys={}
    for split in ('train','valid','test'):
        src=arrays[split];clips=np.asarray(src['id']);vid=np.array([s.split('$_$')[0] for s in clips]);assert set(vid)==groups[split] and len(set(clips))==len(vid)
        keys[split]=set(clips);n=len(clips);x=np.empty((n,6,793),np.float32);number=[];holes=np.zeros(3,dtype=int)
        for i in range(n):
            step=np.flatnonzero(src['text_bert'][i,1,:]!=0)
            if len(step)>2:step=step[1:-1]
            if len(step)==0:raise ValueError('empty lexical sequence')
            number.append(len(step))
            for m,(key,start,stop) in enumerate(COLUMNS):
                v=src[key][i,step];holes[m]+=int((~np.isfinite(v)).sum())
                x[i,:,start:stop]=grouped(v)
        if split=='train':
            flat=x.reshape(-1,793).astype('float64');ok=np.isfinite(flat);mean=np.where(ok,flat,0).sum(0)/np.maximum(ok.sum(0),1)
            var=np.where(ok,(flat-mean)**2,0).sum(0)/np.maximum(ok.sum(0),1);sd=np.sqrt(var).clip(1e-5);xtrain=(mean,sd)
            np.savez_compressed(p.out/'standardization.npz',mean=mean,sd=sd)
        mean,sd=xtrain
        x=np.clip((np.where(np.isfinite(x),x,mean)-mean)/sd,-6.,6.).astype(np.float32)
        for _,start,stop in COLUMNS:x[:,:,start:stop]*=np.sqrt(793/(3*(stop-start)))
        target=np.asarray(src['regression_labels'],np.float32)
        assert target.shape==(n,) and np.all(np.isfinite(target))
        save=p.out/f'{split}.npz';np.savez_compressed(save,x=x,y=target,video=vid,clip=clips,valid_tokens=np.asarray(number))
        splits[split]={'cases':n,'videos':sorted(set(vid)),'feature_nonfinite_unaggregated':holes.tolist(),'min_valid_words':int(min(number)),'max_valid_words':int(max(number)),'sha256':sha(save)}
    assert not(keys['train']&keys['valid'] or keys['train']&keys['test'] or keys['valid']&keys['test'])
    assert all(not(groups[a]&groups[b]) for a,b in [('train','valid'),('train','test'),('valid','test')])
    info={'mmsa_sha':MMSA_SHA,'official_sdk':SDK_COMMIT,'fold_file_sha256':sha(p.folds),'splits':splits,'dimensions':dict(text=768,audio=5,vision=20),'bins':6,'source_read_unpack_wall_s':read,'feature_prep_total_wall_s':time.perf_counter()-wall,'feature_prep_total_cpu_s':time.process_time()-cpu,'standardization_sha256':sha(p.out/'standardization.npz')}
    (p.out/'data.json').write_text(json.dumps(info,sort_keys=True,indent=1)+'\n');print('MOSI',[(k,v['cases'],len(v['videos'])) for k,v in splits.items()],info['feature_prep_total_wall_s'],flush=True)


if __name__=='__main__':main()
