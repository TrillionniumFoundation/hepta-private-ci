"""Source-only 18-fit screening matrix for the exclusive boundary-port model."""
import argparse,fcntl,hashlib,json,os
from pathlib import Path
import subprocess,sys,time

import numpy as np
import torch
from torch.nn import functional as F

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from fit import read_inputs,embed
from score import score_embeddings
from port import PortEncoder,ARMS,SEEDS


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def write(p,v):
    t=p.with_suffix('.part');t.write_text(json.dumps(v,indent=2)+'\n');os.replace(t,p)


def fit(work,out,law,arm,bits,seed):
    t=time.perf_counter();cpu=time.process_time();torch.set_num_threads(1)
    dest=out/'fits'/f'{arm}-{bits}-{seed}';dest.mkdir(parents=True,exist_ok=True)
    if (dest/'selected.json').exists():return
    pix,tok,group,split,vocab=read_inputs(work/'input.npz');train=np.flatnonzero(split==0);dev=np.flatnonzero(split==1)
    model=PortEncoder(arm,bits,seed,vocab,law)
    opt=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01);rng=np.random.default_rng(seed);state=dest/'resume.pt'
    if state.exists():
        r=torch.load(state,weights_only=False,map_location='cpu');model.load_state_dict(r['model']);opt.load_state_dict(r['opt'])
        rng.bit_generator.state=r['rng'];torch.set_rng_state(r['torch_rng']);last,history,tp,tc,vd=r['step'],r['history'],r['train_wall_s'],r['train_cpu_s'],r['validation_wall_s']
    else:history=[];last=0;tp=tc=vd=0.
    for step in range(last+1,2049):
        v=time.perf_counter();c=time.process_time();model.train();idx=rng.choice(train,32,replace=False);caps=(step+np.arange(32))%5
        im,tx=model(pix[idx],tok[idx,caps]);sim=15*(im@tx.T);g=torch.from_numpy(group[idx,caps]);mask=g[:,None].eq(g[None,:]).to(sim.dtype);p=mask/mask.sum(1,keepdim=True)
        loss=-.5*((p*sim.log_softmax(1)).sum(1).mean()+(p*sim.T.log_softmax(1)).sum(1).mean())
        opt.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1);opt.step();tp+=time.perf_counter()-v;tc+=time.process_time()-c
        if step in (128,512,2048):
            v=time.perf_counter();im,tx=embed(model,pix,tok,dev);sc=float(score_embeddings(im,tx,group[dev,0])[:,:,0].mean());vd+=time.perf_counter()-v
            destp=dest/f's{step}.pt';tmp=destp.with_suffix('.part');torch.save(model.state_dict(),tmp);os.replace(tmp,destp)
            history.append(dict(step=step,dev_concordance=sc,sha256=sha(destp),loss=float(loss.detach()),train_wall_s=tp,train_cpu_s=tc,dev_wall_s=vd))
            print(arm,bits,seed,step,sc,flush=True)
        if step in (128,512,1024,1536,2048):
            temp=state.with_suffix('.part');torch.save(dict(model=model.state_dict(),opt=opt.state_dict(),rng=rng.bit_generator.state,torch_rng=torch.get_rng_state(),step=step,history=history,train_wall_s=tp,train_cpu_s=tc,validation_wall_s=vd),temp);os.replace(temp,state)
    write(dest/'selected.json',dict(seed=seed,arm=arm,bits=bits,n_param=sum(x.numel() for x in model.parameters()),history=history,selected=max(history,key=lambda x:x['dev_concordance']),process_wall_s=time.perf_counter()-t,process_cpu_s=time.process_time()-cpu))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('work',type=Path);p.add_argument('out',type=Path);p.add_argument('law',type=Path);p.add_argument('--one',nargs=3);a=p.parse_args()
    if a.one:
        target=a.out/'fits'/f'{a.one[0]}-{a.one[1]}-{a.one[2]}';target.mkdir(exist_ok=True,parents=True)
        with (target/'fit.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            fit(a.work,a.out,a.law,a.one[0],int(a.one[1]),int(a.one[2]))
    else:
        for j in range(6):
            for i,sd in enumerate(SEEDS):
                choices=[(x,b) for b in (32,8) for x in ARMS];arm,bits=choices[(i+j)%6]
                subprocess.run([sys.executable,__file__,str(a.work),str(a.out),str(a.law),'--one',arm,str(bits),str(sd)],check=True)
        print('all 18 sealed candidates ready',flush=True)
