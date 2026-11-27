"""Replay each sealed caption trajectory at its exact timed and common-token checkpoints."""
import argparse
import base64
from collections import defaultdict
import importlib.util
import json
from pathlib import Path
import time
import numpy as np
import torch

def atomic_json(p,obj):
    tmp=p.with_suffix(p.suffix+'.part');tmp.write_text(json.dumps(obj,allow_nan=False)+'\n');tmp.replace(p)
def fixed_clock(device):
    if device.type=='mps':torch.mps.synchronize()
    return time.monotonic()

def run(a):
    spec=importlib.util.spec_from_file_location('ucm_frozen',a.worker);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    source=a.base;out=a.out;out.mkdir(exist_ok=True,parents=True)
    seal=json.loads((source/'seal.json').read_text());result=json.loads((source/'result.json').read_text())
    assert m.sha(source/'seal.json')==result['seal'] and m.sha(source/'predictions.npz')==result['predictions']
    assert m.sha(a.worker)==seal['source_sha256'] and seal.get('device','cpu')==a.device
    device=torch.device(a.device);tol=2e-6 if a.device=='cpu' else 5e-5
    torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.backends.mha.set_fastpath_enabled(False)
    pack=base64.b85decode(m.PACK);x,c,splits,vocab=m.decode(pack,device);tables=m.law_tables()
    rows={};started=time.monotonic();base_pred=np.load(source/'predictions.npz')
    for d,depth in m.SIZES:
        for j,seed in enumerate(m.SEEDS):
            minimum={r:min(next(y['steps'] for y in seal['models'][f'{d}-{seed}-{arm}']['history'] if y['requested_s']==r)
                         for arm in m.ARMS) for r in seal['caps']}
            for off in range(len(m.ARMS)):
                arm=m.ARMS[(off+j)%len(m.ARMS)];key=f'{d}-{seed}-{arm}';record=seal['models'][key]
                done=out/(key+'.json');store=out/(key+'.npz')
                if done.exists():
                    saved=json.loads(done.read_text());assert saved['predictions_sha256']==m.sha(store);rows[key]=saved;continue
                torch.manual_seed(seed)
                net=m.Captioner(d,depth,vocab,arm,tables).to(device);opt=torch.optim.AdamW(net.parameters(),lr=.0003,weight_decay=.01)
                rng=np.random.default_rng(seed+228);labels=defaultdict(list)
                for entry in record['history']:
                    r=entry['requested_s'];labels[entry['steps']].append(f'time{r}');labels[minimum[r]].append(f'equal{r}')
                by_time={y['steps']:y for y in record['history']};snap={};report={};tokens=0;cpu=wall=0.;max_tensor_delta=None
                selected=next(t for t,y in by_time.items() if y['requested_s']==record['selected_rung'])
                for step in range(1,max(labels)+1):
                    ts=fixed_clock(device);cs=time.process_time()
                    im=rng.choice(splits[0],24);ci=rng.integers(0,c.shape[1],24);y=c[im,ci]
                    net.train();opt.zero_grad(set_to_none=True);z=net(x[im],y[:,:-1])
                    loss=m.F.cross_entropy(z.flatten(0,1),y[:,1:].flatten(),ignore_index=0)
                    if not torch.isfinite(loss):raise ArithmeticError(key+' nonfinite replay')
                    loss.backward();torch.nn.utils.clip_grad_norm_(net.parameters(),1.);opt.step()
                    t2=fixed_clock(device);wall+=t2-ts;cpu+=time.process_time()-cs;tokens+=int(y[:,1:].ne(0).sum().cpu())
                    if step not in labels:continue
                    q,n=m.evalset(net,x,c,splits[1],device);dev=float(q.sum()/n.sum())
                    rec={'step':step,'nonpadding_training_tokens':tokens,'dev_nll':dev,
                         'replay_optimizer_wall_s':wall,'replay_optimizer_cpu_s':cpu}
                    if step in by_time:
                        original=by_time[step];rec['original_rung']=original['requested_s'];rec['dev_abs_diff']=abs(dev-original['dev_nll'])
                    if step==selected:
                        ck=source/(key+'.pt');assert m.sha(ck)==record['selected_sha256']
                        original=torch.load(ck,map_location='cpu',weights_only=True)
                        max_tensor_delta=max(float((v.detach().cpu()-original[name]).abs().max()) for name,v in net.state_dict().items() if v.numel()>0)
                        del original
                    q,n=m.evalset(net,x,c,splits[2],device);alt,n2=m.evalset(net,x,c,splits[2],device,True)
                    assert np.array_equal(n,n2) and np.array_equal(n,base_pred['tokens'])
                    if step==selected:rec['selected_cold_mean_abs_delta']=float(abs(q.sum()-base_pred[key].sum())/n.sum())
                    for lab in labels[step]:
                        snap[lab]=q;snap[lab+'-shuffled']=alt;report[lab]=rec
                    snap['tokens']=n
                deviations=[z['dev_abs_diff'] for z in report.values() if 'dev_abs_diff' in z]
                assert max_tensor_delta is not None and len(deviations)>=4
                valid=bool(max_tensor_delta<=tol and max(deviations)<=tol)
                with store.with_suffix('.part').open('wb') as f:np.savez_compressed(f,**snap)
                store.with_suffix('.part').replace(store)
                meta=dict(valid=valid,tolerance=tol,max_dev_abs=max(deviations),selected_max_tensor_delta=max_tensor_delta,
                          predictions_sha256=m.sha(store),by_rung=report)
                atomic_json(done,meta);rows[key]=meta
                print(key,valid,'steps',max(labels),'max deltas',meta['max_dev_abs'],max_tensor_delta,flush=True)
                del net,opt
    base_pred.close()
    assert len(rows)==24
    atomic_json(out/'replay.json',dict(original_seal_sha256=result['seal'],device=a.device,matrix=rows,
                successful=sum(x['valid'] for x in rows.values()),finish_epoch=time.time(),last_process_wall_s=time.monotonic()-started))
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('base','out','worker'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--device',choices=['cpu','mps'],required=True)
    run(p.parse_args())
