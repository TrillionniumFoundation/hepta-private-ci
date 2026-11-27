"""One-core FP32 size comparison with atomic resumable rungs and all-model cold seal."""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import time
import numpy as np
import torch

def write_json(path,value):
    pending=path.with_suffix(path.suffix+'.tmp')
    pending.write_text(json.dumps(value,allow_nan=False)+'\n')
    pending.replace(path)
def save(path,data):
    pending=path.with_suffix('.tmp')
    torch.save(data,pending)
    pending.replace(path)
def cpu_info():
    for line in Path('/proc/cpuinfo').read_text().splitlines():
        if line.startswith('model name'):return line.split(':',1)[1].strip()
    return 'CPU'
def run(a):
    spec=importlib.util.spec_from_file_location('ucm_frozen',a.worker)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    expected='40dacfd435b5b8723ffdab24b120985ffcf5c56a7c4f735965552c3a450712d8'
    if m.sha(a.worker)!=expected:raise ValueError('incorrect training source')
    work=a.out;work.mkdir(exist_ok=True,parents=True)
    torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.backends.mha.set_fastpath_enabled(False)
    device=torch.device('cpu');tic=time.monotonic();pack=m.base64.b85decode(m.PACK);x,c,splits,vocab=m.decode(pack,device);table=m.law_tables()
    train=c[splits[0],:,1:].numpy().ravel();ct=np.bincount(train[train!=0],minlength=vocab)+1;ct[0]=0
    f=ct/ct.sum();v=c[splits[1],:,1:].numpy().ravel();base=float(-np.log(f[v[v!=0]]).mean())
    init=work/'setup.json'
    if not init.exists():
        write_json(init,dict(started=datetime.datetime.now(datetime.timezone.utc).isoformat(),cpu=cpu_info(),
            affinity=sorted(os.sched_getaffinity(0)),precision='float32',torch=str(torch.__version__),
            source_sha256=expected,pack_sha256=hashlib.sha256(pack).hexdigest(),caps=[15,60,180,360],
            setup_wall_s=time.monotonic()-tic,unigram_dev_nll=base,targets=[base-d for d in (.25,.75,1.25,1.75)]))
    config=json.loads(init.read_text())
    for d,depth in m.SIZES:
        for j,seed in enumerate(m.SEEDS):
            for off in range(len(m.ARMS)):
                arm=m.ARMS[(j+off)%len(m.ARMS)];key=f'{d}-{seed}-{arm}';end=work/(key+'.json');weights=work/(key+'.pt')
                if end.exists():
                    if m.sha(weights)!=json.loads(end.read_text())['selected_sha256']:raise ValueError('checkpoint integrity')
                    continue
                start=time.monotonic();torch.manual_seed(seed)
                net=m.Captioner(d,depth,vocab,arm,table);opt=torch.optim.AdamW(net.parameters(),lr=.0003,weight_decay=.01)
                rng=np.random.default_rng(seed+228);cpu=wall=prev_wall=0.;steps=0;best=float('inf');best_rung=0;hist=[]
                resume=work/(key+'.resume.pt')
                if resume.exists():
                    z=torch.load(resume,map_location='cpu',weights_only=False)
                    net.load_state_dict(z['net']);opt.load_state_dict(z['opt']);rng.bit_generator.state=z['rng']
                    cpu,wall,steps,best,best_rung,hist,prev_wall=z['stats'];del z
                print('start',key,'params',sum(p.numel() for p in net.parameters()),'from',steps,flush=True)
                for rung in config['caps']:
                    if len(hist) and rung<=hist[-1]['requested_s']:continue
                    while cpu<rung:
                        t=time.monotonic();u=time.process_time()
                        ab=rng.choice(splits[0],24);ca=rng.integers(0,c.shape[1],24);label=c[ab,ca]
                        net.train();opt.zero_grad(set_to_none=True);scores=net(x[ab],label[:,:-1])
                        loss=m.F.cross_entropy(scores.flatten(0,1),label[:,1:].flatten(),ignore_index=0)
                        if not torch.isfinite(loss):raise ArithmeticError('nonfinite training loss')
                        loss.backward();torch.nn.utils.clip_grad_norm_(net.parameters(),1.);opt.step()
                        cpu+=time.process_time()-u;wall+=time.monotonic()-t;steps+=1
                    t=time.monotonic();losses,counts=m.evalset(net,x,c,splits[1],device);v=float(losses.sum()/counts.sum())
                    validation=time.monotonic()-t;save_t=time.monotonic()
                    if v<best:
                        save(weights,net.state_dict());best=v;best_rung=rung
                    hist.append(dict(requested_s=rung,optimizer_cpu_s=cpu,optimizer_wall_s=wall,steps=steps,
                        dev_nll=v,validation_s=validation,selected_weight_write_s=time.monotonic()-save_t,
                        elapsed_fit_wall_s=prev_wall+time.monotonic()-start))
                    if rung!=config['caps'][-1]:
                        save(resume,dict(net=net.state_dict(),opt=opt.state_dict(),rng=rng.bit_generator.state,
                                         stats=(cpu,wall,steps,best,best_rung,hist,prev_wall+time.monotonic()-start)))
                    print(key,rung,steps,v,round(wall,3),flush=True)
                write_json(end,dict(history=hist,params=sum(p.numel() for p in net.parameters()),selected_rung=best_rung,
                    selected_sha256=m.sha(weights),fit_wall_s=prev_wall+time.monotonic()-start,
                    process_high_water_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
                resume.unlink(missing_ok=True);del net,opt
    models={f'{d}-{s}-{a}':json.loads((work/f'{d}-{s}-{a}.json').read_text()) for d,_ in m.SIZES for s in m.SEEDS for a in m.ARMS}
    seal=work/'seal.json'
    if not seal.exists():write_json(seal,{**config,'models':models})
    assert json.loads(seal.read_text())['models']==models and len(models)==24
    pred={};times={};coldstart=time.monotonic()
    for d,depth in m.SIZES:
        for seed in m.SEEDS:
            for arm in m.ARMS:
                key=f'{d}-{seed}-{arm}';ck=work/(key+'.pt');after=time.monotonic()
                assert m.sha(ck)==models[key]['selected_sha256']
                net=m.Captioner(d,depth,vocab,arm,table)
                net.load_state_dict(torch.load(ck,map_location='cpu',weights_only=True))
                st=time.monotonic()
                q,n=m.evalset(net,x,c,splits[2],device);ts=time.monotonic()
                alt,alt_n=m.evalset(net,x,c,splits[2],device,True);assert np.array_equal(n,alt_n)
                pred[key]=q;pred[key+'-shuffled']=alt;pred['tokens']=n
                times[key]=dict(cold_load_and_hash_s=st-after,aligned_s=ts-st,shuffled_s=time.monotonic()-ts)
                del net
    np.savez_compressed(work/'predictions.npz',**pred)
    write_json(work/'result.json',dict(seal=m.sha(seal),predictions=m.sha(work/'predictions.npz'),
         per_model_times=times,cold_wall_s=time.monotonic()-coldstart,ended=datetime.datetime.now(datetime.timezone.utc).isoformat(),
         weighted_nll={k:float(v.sum()/n.sum()) for k,v in pred.items() if k!='tokens'}))
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('worker','out'):p.add_argument('--'+name,type=Path,required=True)
    run(p.parse_args())
