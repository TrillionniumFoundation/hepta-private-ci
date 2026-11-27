"""Advance one single-core budget ladder, recording optimizer CPU time and atomic states."""
import argparse
import hashlib
import json
import os
import platform
import time
from pathlib import Path

import numpy as np
import torch
from scipy.spatial import cKDTree
from torch.nn import functional as F

from models import CommonEncoder, PriceCell, Data, make_table

ARMS=('literal','smooth','gru','attention')
SEEDS=(173,331,509,773)
RUNGS=(30,120,600,2520)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path,data):
    tmp=path.with_suffix('.part')
    tmp.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    tmp.replace(path)


def atomic_save(path,obj):
    tmp=path.with_suffix('.inflight')
    torch.save(obj,tmp);tmp.replace(path)


def model(arm,table):
    return PriceCell(arm,24,table) if arm in ('literal','smooth') else CommonEncoder(arm,24)


@torch.inference_mode()
def predict(module,data):
    module.eval(); rows=[]
    for ids in torch.arange(len(data)).split(384):
        x,s,_=data.sample(ids);rows.append(module(x,s).sigmoid().numpy())
    return np.concatenate(rows).reshape(-1,4,3)


def histories(data):
    # Clock, most recent 12h, and their historical scale are shared with neural arms.
    x=data['seq'];return np.column_stack([x[:,:,0],x[:,-1,1:]])


def analog(train,data,k):
    x=histories(train)
    std=np.maximum(x.std(0),1e-6)
    _,positions=cKDTree(x/std).query(histories(data)/std,k=k)
    costs=np.cumsum(train['future'][positions]*data['tariff'][:,None],axis=2)
    debits=costs[:,:,None,[1,3,5]]+np.array([0,1.25,0,1.25])[None,None,:,None]*np.array([0,1,1])
    return (debits>=np.array([2.5,2.5,5,5])[None,None,:,None]).mean(1)


def fit(args):
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    out=args.out;out.mkdir(parents=True,exist_ok=True)
    train=Data(args.data/'train.npz');dev=Data(args.data/'dev.npz')
    table=make_table(args.core);kfile=out/'analog.json'
    if not kfile.exists():
        with np.load(args.data/'train.npz') as t,np.load(args.data/'dev.npz') as d:
            start=time.monotonic()
            bs={k:float(np.mean((analog(t,d,k)-d['y'])**2)) for k in (16,64,256)}
            save_json(kfile,{'development_brier':bs,'selected_k':min(bs,key=bs.get),'wall_s':time.monotonic()-start})
    if not (out/'environment.json').exists():
        save_json(out/'environment.json',{'machine':platform.machine(),'platform':platform.platform(),'cpu':next((ln.split(':',1)[1].strip() for ln in Path('/proc/cpuinfo').read_text().splitlines() if ln.startswith('model name')),''),'affinity':sorted(os.sched_getaffinity(0)),'torch':str(torch.__version__),'numpy':np.__version__,'threads':torch.get_num_threads(),'start':time.time(),'table_max_log_margin':3,'grid_step':1/4096,'host_core_sha':digest(Path(args.core)/'he_xiong.py'),'data_split':digest(args.data/'split.json'),'sources':{p.name:digest(p) for p in [Path(__file__),Path(__file__).with_name('prepare.py'),Path(__file__).with_name('models.py')]}})
    for rung in RUNGS:
        for j,seed in enumerate(SEEDS):
            for offset in range(4):
                arm=ARMS[(offset+j)%4];directory=out/f'{arm}-{seed}'
                directory.mkdir(exist_ok=True)
                marker=directory/f'm{rung}.json';snap=directory/f'm{rung}.pt'
                if marker.exists():
                    assert snap.exists() and digest(snap)==json.loads(marker.read_text())['weights_sha256']
                    continue
                clock=time.monotonic();torch.manual_seed(seed)
                net=model(arm,table); opt=torch.optim.AdamW(net.parameters(),lr=.001,weight_decay=.0001)
                gen=torch.Generator().manual_seed(seed+474)
                ck=directory/'resume.pt';elapsed=0.;steps=0;previous_wall=0
                if ck.exists():
                    pack=torch.load(ck,weights_only=False)
                    net.load_state_dict(pack['net']);opt.load_state_dict(pack['opt']);gen.set_state(pack['sampler']);torch.set_rng_state(pack['global_rng'])
                    elapsed=pack['time'];steps=pack['steps'];previous_wall=pack['wall']
                opt_wall=previous_wall;last_saved=elapsed
                def save():
                    atomic_save(ck,dict(net=net.state_dict(),opt=opt.state_dict(),sampler=gen.get_state(),global_rng=torch.get_rng_state(),time=elapsed,steps=steps,wall=opt_wall))
                print('start',rung,seed,arm,round(elapsed,2),flush=True)
                while elapsed<rung:
                    cpu0=time.process_time();w0=time.monotonic()
                    net.train();opt.zero_grad(set_to_none=True)
                    x,s,y=train.sample(torch.randint(len(train),(96,),generator=gen))
                    logits=net(x,s)
                    loss=F.binary_cross_entropy_with_logits(logits,y);loss.backward()
                    norm=torch.nn.utils.clip_grad_norm_(net.parameters(),1.,error_if_nonfinite=True)
                    opt.step()
                    opt_wall+=time.monotonic()-w0;elapsed+=time.process_time()-cpu0;steps+=1
                    if elapsed-last_saved>=60:
                        save();last_saved=elapsed
                save();atomic_save(snap,net.state_dict())
                t0=time.monotonic();scores=predict(net,dev);cost=time.monotonic()-t0
                val=float(np.mean((scores-dev.y.numpy())**2))
                record={'arm':arm,'seed':seed,'budget_s':rung,'optimizer_cpu_s':elapsed,'optimizer_wall_s':opt_wall,'steps':steps,'dev_brier':val,'dev_wall_s':cost,'resume_segment_wall_s':time.monotonic()-clock,'parameters':sum(x.numel() for x in net.parameters()),'weights_sha256':digest(snap),'completed':time.time()}
                save_json(marker,record);print('done',json.dumps(record),flush=True)
    plan={}
    for seed in SEEDS:
        for arm in ARMS:
            label=f'{arm}-{seed}';d=out/label
            rows=[json.loads((d/f'm{r}.json').read_text()) for r in RUNGS]
            plan[label]=min(rows,key=lambda row:(row['dev_brier'],row['budget_s']))
    save_json(out/'seal.json',{'selected':plan,'k':json.loads(kfile.read_text()),'sealed_time':time.time()})
    print('sealed',digest(out/'seal.json'),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('data','out','core'):parser.add_argument('--'+name,type=Path,required=True)
    fit(parser.parse_args())
