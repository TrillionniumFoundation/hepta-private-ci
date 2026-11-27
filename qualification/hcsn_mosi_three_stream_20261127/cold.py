"""Authenticate every fit before testing. Cold scoring runs once per sealed seed/arm/size."""
import time
ENTRY=time.perf_counter();ENTRYCPU=time.process_time()
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from models import designs,SEEDS,RUNGS,SLICES,model,modalities,predict
from source import sha

HERE=Path(__file__).resolve().parent


def stamp(p,value):p.write_text(json.dumps(value,indent=1,sort_keys=True,allow_nan=False)+'\n')


def code():
    return {n:sha(HERE/n) for n in ['PROTOCOL.md','models.py','prepare.py','train.py','source.py','official_folds.py','cold.py','check_law.py','verify.py']}


def seal(a):
    if a.seal.exists():raise FileExistsError(a.seal)
    fits={};weights={};n=0
    for w,arm in designs():
        for s in SEEDS:
            path=a.models/f'{w}-{arm}-{s}.json';m=json.loads(path.read_bytes());fits[path.name]=sha(path)
            assert (m['width'],m['arm'],m['seed'])==(w,arm,s)
            for t in RUNGS:
                sel=m['selected'][str(t)]
                if sel is None:continue
                assert sel['cpu']<=t and sel['dev_video_mae']==min(v['dev_video_mae'] for v in m['history'] if v['cpu']<=t)
                f=a.models/sel['file'];h=weights.setdefault(f.name,sha(f));assert h==sel['sha256'];n+=1
    data=json.loads((a.data/'data.json').read_bytes())
    stamp(a.seal,{'fits':fits,'weights':weights,'model_prefixes':n,'code':code(),'data_manifest_sha256':sha(a.data/'data.json'),'test_input_sha256':data['splits']['test']['sha256'],'law_sha256':sha(a.law),'kernel_parity':sha(a.grad),'first_cold_scoring':'pending'})
    print('sealed',len(fits),len(weights),n,sha(a.seal),flush=True)


def derangement(video,seed):
    # Randomly propose a full permutation and repair donor collisions by two-way swaps.
    rand=np.random.default_rng(seed);p=rand.permutation(len(video))
    for i in range(len(video)):
        if video[p[i]]==video[i]:
            possible=np.flatnonzero((video[p]!=video[i])&(video!=video[p[i]]))
            j=rand.choice(possible);p[i],p[j]=p[j],p[i]
    assert len(set(p))==len(p) and np.all(video!=video[p])
    return p


def run(a):
    sealed=json.loads(a.seal.read_bytes());assert sealed['code']==code() and sha(a.law)==sealed['law_sha256']
    mpath=a.models/f'{a.width}-{a.arm}-{a.seed}.json';assert sha(mpath)==sealed['fits'][mpath.name]
    m=json.loads(mpath.read_bytes());assert sha(a.data/'test.npz')==sealed['test_input_sha256']
    torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.backends.mha.set_fastpath_enabled(False)
    with np.load(a.data/'test.npz') as f:x=torch.from_numpy(f['x']);y=f['y'];ids=f['clip'];vid=f['video']
    assert len(y)==686 and len(set(vid))==31
    donor=[derangement(vid,k) for k in (21901,65741,89303)]
    output={'clip':ids,'video':vid,'y':y,'donors':np.array(donor)}
    a.out.mkdir(exist_ok=True,parents=True);out=a.out/f'{a.width}-{a.arm}-{a.seed}.npz'
    if out.exists():raise FileExistsError(out)
    seen={};costs={};net=model(a.width,a.arm,a.law);base=modalities(x,a.arm)
    read_wall=time.perf_counter()-ENTRY;read_cpu=time.process_time()-ENTRYCPU
    for rung in RUNGS:
        row=m['selected'][str(rung)]
        if row is None:continue
        named=row['file']
        if named not in seen:
            begin=time.perf_counter();cpu=time.process_time()
            w=a.models/named;assert sha(w)==sealed['weights'][named]
            net.load_state_dict(torch.load(w,weights_only=True,map_location='cpu'))
            z=predict(net,base);assert np.isfinite(z).all();seen[named]=(z,time.perf_counter()-begin,time.process_time()-cpu)
        z,wall,used=seen[named];output['r'+str(rung)]=z;costs[str(rung)]={'model_load_and_inference_wall':wall,'model_load_and_inference_cpu':used}
    if m['selected'][str(max(RUNGS))] is not None:
        row=m['selected'][str(max(RUNGS))];net.load_state_dict(torch.load(a.models/row['file'],weights_only=True,map_location='cpu'))
        for key,sl in {**SLICES,'av':slice(768,793)}.items():
            modified=base.clone();modified[...,sl]=0
            output['drop_'+key]=predict(net,modified) if not torch.equal(modified,base) else output['r180'].copy()
            for j,p in enumerate(donor):
                modified=base.clone();modified[...,sl]=base[p][...,sl]
                output[f'swap_{key}_{j}']=predict(net,modified) if not torch.equal(modified,base) else output['r180'].copy()
    np.savez_compressed(out,**output)
    stamp(out.with_suffix('.json'),{'seal_sha256':sha(a.seal),'pred_sha256':sha(out),'source_and_start_wall':read_wall,'source_and_start_cpu':read_cpu,'rungs':costs,'all_perturbations_and_save_wall':time.perf_counter()-ENTRY,'total_cpu':time.process_time()-ENTRYCPU})
    print(a.width,a.arm,a.seed,len(output)-4,flush=True)


if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('cmd',choices=('seal','score'))
    for n in ('models','data','law','grad','seal','out'):q.add_argument(n,type=Path)
    q.add_argument('width',nargs='?',type=int);q.add_argument('arm',nargs='?');q.add_argument('seed',nargs='?',type=int)
    a=q.parse_args();(seal if a.cmd=='seal' else run)(a)
