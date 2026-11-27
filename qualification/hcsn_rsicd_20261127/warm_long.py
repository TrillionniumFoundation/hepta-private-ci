"""Round-robin the three physical trajectories at preregistered active-time endpoints."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
import torch

from study import ROOT, SEEDS, LONG, atomic, sha, setup_data, gallery, score, load_model
from warm import Towers, embeddings, inputs
from neural import masked_infonce
from adam import Adam

def initializer():
    choices=[]
    for seed in SEEDS:
        root=ROOT/'short'/f'literal-{seed}'
        rows=json.loads((root/'history.json').read_text())
        best=max(rows,key=lambda x:(x['dev_r1'],x['dev_r5'],-x['time']))
        file=root/best['state'];assert sha(file)==best['hash']
        choices.append((best['width'],best['ridge'],best['hash'],file))
    assert len({c[:3] for c in choices})==1
    return choices[0]

def one(seed,budget):
    start=time.perf_counter();cpu_start=time.process_time();torch.set_num_threads(1)
    d,V=setup_data();tr=np.flatnonzero(d['split']==0);dv=gallery(d,1)
    out=ROOT/'hybrid_long'/str(seed);out.mkdir(exist_ok=True,parents=True)
    w,r,identity,source=initializer()
    with np.load(ROOT/'law.npz') as f:z=dict(f)
    m,_=load_model(source);nets=[Towers(m,z),Towers(m,z)]
    rates=[.0003,.001];ops=[Adam(net.parameters(),lr,weight_decay=.001) for net,lr in zip(nets,rates)]
    rng=[np.random.default_rng(seed),np.random.default_rng(seed)]
    order=[0,1] if SEEDS.index(seed)%2==0 else [1,0]
    steps=[0,0];prior=0.;best=None;cpu_prior=0.;best_row=None;written=0;last_index=1
    archive=out/'training.resume.pt';hist=out/'history.jsonl'
    if not archive.exists() and hist.exists():
        hist.replace(out/f'interrupted-before-first-state-{time.time_ns()}.jsonl')
    if archive.exists():
        old=torch.load(archive,map_location='cpu',weights_only=False)
        assert old['seed']==seed and old['init_hash']==identity
        prior=old['elapsed'];cpu_prior=old['cpu'];best=old['best'];best_row=old['best_row']
        steps=old['steps'];written=old['written'];last_index=old['last_index']
        with hist.open('rb+') as f:
            f.seek(0,2)
            if f.tell()>written:
                f.seek(written);tail=f.read()
                (out/f'interrupted-{time.time_ns()}.jsonl').write_bytes(tail);f.truncate(written)
        for i in range(2):
            nets[i].load_state_dict(old['nets'][i]);ops[i].n,ops[i].state=old['optimizers'][i]
            rng[i].bit_generator.state=old['rng'][i]
    def clock():return prior+time.perf_counter()-start
    def sofar():return cpu_prior+time.process_time()-cpu_start
    def save():
        tmp=out/'training.resume.tmp'
        snap=dict(seed=seed,init_hash=identity,width=w,ridge=r,elapsed=clock(),cpu=sofar(),steps=steps,best=best,best_row=best_row,last_index=last_index,written=written,nets=[n.state_dict() for n in nets],optimizers=[(o.n,o.state) for o in ops],rng=[g.bit_generator.state for g in rng])
        torch.save(snap,tmp);tmp.replace(archive)
        atomic(out/'progress.json',{k:snap[k] for k in ('seed','init_hash','width','ridge','elapsed','cpu','steps','best','best_row','written')})
    def evaluate(i):
        nonlocal best,best_row,written,last_index
        I,T=embeddings(nets[i],d,V,dv);met,_=score(I,T,d,dv)
        q=(met['strict_R1'],met['strict_R5']);entry={'step':steps[i],'rate':rates[i],'dev_r1':q[0],'dev_r5':q[1],'state':None}
        if best is None or q>best:
            state=out/f"lr{i}-s{steps[i]}.pt";torch.save(nets[i].state_dict(),state)
            entry['state']=state.name;entry['hash']=sha(state);best=q
        entry['time']=clock()
        if entry['state']:best_row=entry
        with hist.open('ab') as f:
            f.write((json.dumps(entry,separators=(',',':'))+'\n').encode());written=f.tell()
        last_index=order.index(i)
    if not hist.exists():
        for i in order:evaluate(i)
    last_save=clock()
    while clock()<budget:
        next_index=1-last_index;i=order[next_index]
        for _ in range(8):
            ix=rng[i].choice(tr,64,replace=False);ops[i].zero_grad()
            x,y=nets[i](*inputs(d,V,ix));loss=masked_infonce(x,y,torch.tensor(d['title'][ix]))
            loss.backward();ops[i].step();steps[i]+=1
        evaluate(i)
        if clock()-last_save>=60:save();last_save=clock()
    save()
    atomic(out/f'budget-{budget}.json',{'seed':seed,'budget':budget,'start_active_s':prior,'end_active_s':clock(),'quantum_elapsed':time.perf_counter()-start,'quantum_cpu':time.process_time()-cpu_start,'steps':steps,'init_hash':identity,'physical_width':w,'ridge':r})
def seal(budget):
    choices={}
    for seed in SEEDS:
        out=ROOT/'hybrid_long'/str(seed);assert (out/f'budget-{budget}.json').is_file()
        hist=[json.loads(x) for x in (out/'history.jsonl').read_text().splitlines()]
        eligible=[r for r in hist if r['state'] and r['time']<=budget]
        if not eligible:raise RuntimeError('no fully completed eligible state')
        choice=max(eligible,key=lambda r:(r['dev_r1'],r['dev_r5'],-r['time']));assert sha(out/choice['state'])==choice['hash']
        choices[str(seed)]=choice
    atomic(ROOT/'hybrid_long'/f'seal-{budget}.json',choices)
def cold(budget):
    torch.set_num_threads(1);root=ROOT/'hybrid_long';sealpath=root/f'seal-{budget}.json'
    selections=json.loads(sealpath.read_text());d,V=setup_data();ix=gallery(d,2)
    with np.load(ROOT/'law.npz') as f:z=dict(f)
    width,ridge,src_hash,file=initializer();models,_=load_model(file);all_rows={};arrays={}
    for seed in SEEDS:
        record=selections[str(seed)];path=root/str(seed)/record['state'];assert sha(path)==record['hash']
        net=Towers(models,z);net.load_state_dict(torch.load(path,map_location='cpu',weights_only=True))
        r=score(*embeddings(net,d,V,ix),d,ix);all_rows[str(seed)]=r[0];arrays[str(seed)]=np.stack(list(r[1].values())).astype(np.int16)
    data=root/f'cold-{budget}.npz';np.savez_compressed(data,**arrays)
    with np.load(ROOT/'short'/'cold_ranks.npz') as f:
        base=[f[f'literal/{s}/60'] for s in SEEDS]
        diff=np.mean([((arrays[str(s)][:,:,0]==1).astype(float)-(b[:,:,0]==1)).mean(0) for s,b in zip(SEEDS,base)],0)
    g=np.random.default_rng(220711);boot=np.concatenate([diff[g.integers(len(ix),size=(100,len(ix)))].mean(1) for _ in range(80)])
    atomic(root/f'outcome-{budget}.json',dict(scores=all_rows,delta_vs_frozen=float(diff.mean()),paired95_vs_frozen=np.quantile(boot,[.025,.975]).tolist(),n=len(ix),seed_roster=SEEDS,seal_sha=sha(sealpath),ranks_sha=sha(data),width=width,ridge=ridge,init_sha=src_hash,conventional_long_comparison='pending when all three conventional states reach this budget'))
def supervise():
    root=ROOT/'hybrid_long';root.mkdir(exist_ok=True)
    for budget in LONG:
        for seed in SEEDS:
            if not (root/str(seed)/f'budget-{budget}.json').is_file():
                subprocess.run([sys.executable,str(Path(__file__).resolve()),'one',str(seed),str(budget)],check=True)
        if not (root/f'seal-{budget}.json').exists():seal(budget)
        if not (root/f'outcome-{budget}.json').exists():cold(budget)
        print('sealed',budget,flush=True)
if __name__=='__main__':
    if len(sys.argv)==1:supervise()
    elif sys.argv[1]=='one':one(int(sys.argv[2]),int(sys.argv[3]))
