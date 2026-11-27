"""Trace actual selected routers and remove one contribution at a time on train photos."""
from pathlib import Path
import datetime
import hashlib
import json
import math
import os
import sys
import time
import fcntl

ROOT = Path(os.environ.get('HEPTA_FLICKR_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(ROOT))
import numpy as np
import torch
from model import Captioner
from panel import Samples, score

BASE=ROOT/'router_audit'
ARMS=('hcsn','smooth','lif')
SEEDS=(17011,24203,39827)
BUDGETS=(20,2520)


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def write(p,x):
    t=p.with_name(p.name+'.part');t.write_text(json.dumps(x,indent=2,sort_keys=True,allow_nan=False));t.replace(p)


def describe(arr):
    return dict(mean=float(arr.mean(dtype=np.float64)),sd=float(arr.std(dtype=np.float64)),
            min=float(arr.min()),p05=float(np.quantile(arr,.05)),p50=float(np.quantile(arr,.5)),
            p95=float(np.quantile(arr,.95)),max=float(arr.max()))


def release(r,patches,mode='reference',fixed_rates=None,history=None):
    n,_,d=patches.shape
    rows=patches.reshape(n*4,4,d)
    drive=r.drive(rows)
    prior=drive.new_zeros(n*4,4)
    margin=prior+.18
    av=prior+r.law.a0
    fv=prior+r.law.f0
    rest=prior[:,:1]+1
    total=patches.new_zeros(n*4,d)
    mass_t=[]
    for t in range(3):
        if r.arm=='lif':
            v=.8*margin+drive[:,t]+r.rec(prior)
            soft=torch.sigmoid(4*(v-1))
            hit=(v>=1.).to(v.dtype)+soft-soft.detach()
            margin=v*(1-hit)
            prior=hit
            trace={'voltage':v,'release':hit}
        else:
            equity_feedback=.4*torch.tanh((av-r.law.a0)/20)
            passage_feedback=.4*torch.tanh(fv-r.law.f0)
            if mode=='remove_equity':equity_feedback=torch.zeros_like(equity_feedback)
            if mode=='remove_annual':passage_feedback=torch.zeros_like(passage_feedback)
            control=torch.tanh(drive[:,t]+r.rec(prior)+(equity_feedback+passage_feedback))
            b=torch.log1p(r.law.kappa*control)
            if mode=='fixed_boundary':b=torch.zeros_like(b)
            x=margin+prior-b
            eq,slope,year,quarter,margin=r.law.lookup(x).unbind(-1)
            if r.arm=='hcsn':
                av=torch.where(x>0,eq+slope*(.28*r.law.principal*control),0.)
                fv=year
                hit=quarter
            else:
                av=r.law.a0+20*torch.tanh((x-.18)*r.law.da/20)
                fv=r.law.f0+torch.tanh((x-.18)*r.law.df)
                logit=math.log(r.law.h0/(1-r.law.h0))+(x-.18)*r.law.dh/(r.law.h0*(1-r.law.h0))
                hit=torch.sigmoid(logit)
            prior=b
            trace={'live_log_margin':x,'log_boundary_move':b,'next_mean_margin':margin,'equity_level':av,
                   'annual_feedback_state':fv,'release':hit,'equity_feedback':equity_feedback,'annual_feedback':passage_feedback}
        propensity=hit.mean(-1,keepdim=True)
        if mode=='fixed_mass':propensity=torch.full_like(propensity,float(fixed_rates[t]))
        mass=rest*propensity
        total=total+mass*rows[:,t]
        rest=rest-mass
        mass_t.append(mass)
        if history is not None:
            for k,v in trace.items():history.setdefault(k,[]).append(v.detach().cpu().numpy().ravel().copy())
    total=total+rest*rows[:,3]
    mass_t.append(rest)
    if history is not None:history.setdefault('position_mass',[]).append(torch.cat(mass_t,1).cpu().numpy().copy())
    return total.reshape(n,4,d)


@torch.no_grad()
def trace(model,data):
    history={}
    residual=0.
    for start in range(0,len(data.pix),64):
        px=torch.from_numpy(np.array(data.pix[start:start+64],copy=True))
        patches=model.patch(px.permute(0,3,1,2).float()/127.5-1).flatten(2).transpose(1,2)+model.image_pos
        true=model.router(patches)
        reconstructed=release(model.router,patches,history=history)
        residual=max(residual,float((true-reconstructed).abs().max()))
    assert residual<3e-5,residual
    arr={k:np.concatenate(v) for k,v in history.items()}
    mass=arr.pop('position_mass');assert np.max(np.abs(mass.sum(1)-1))<1e-6
    average_mass=mass.mean(0,dtype=np.float64)
    rates=(average_mass[:-1]/(1-np.r_[0.,np.cumsum(average_mass[:-2])])).tolist()
    report={k:describe(v) for k,v in arr.items()}
    report.update(rows=len(mass),components_over_three_transitions=arr['release'].size,
                  max_abs_reproduction=residual,mean_routed_mass=average_mass.tolist(),
                  last_patch_mass=describe(mass[:,-1]),fixed_conditional_release=rates,
                  release_over_half=float(np.mean(arr['release']>.5)),release_over_99=float(np.mean(arr['release']>.99)))
    if 'live_log_margin' in arr:
        x=arr['live_log_margin'];report.update(nonpositive_margin_fraction=float(np.mean(x<=0)),lookup_above_two_fraction=float(np.mean(x>2)),
              first_three_release_mean=float(np.mean(arr['release'],dtype=np.float64)))
    return report,rates


def main_stage(stage,train,subset,seedids):
    path=BASE/f'{stage:04d}';path.mkdir(exist_ok=True)
    archive=ROOT/'development_archive'/f'{stage:04d}'
    seal=json.loads((archive/'stage_seal.json').read_text())
    cells={}
    n0=None
    for arm in ARMS:
        for seed in SEEDS:
            k=f'{arm}-{seed}';receipt=archive/f'{k}.json'
            assert sha(receipt)==seal['receipts'][k]
            j=json.loads(receipt.read_text());ck=ROOT/'development_archive'/'objects'/(j['selected_sha256']+'.pt')
            assert sha(ck)==j['selected_sha256']
            model=Captioner(arm,3490);model.load_state_dict(torch.load(ck,map_location='cpu',weights_only=True));model.eval()
            diagnostics,rates=trace(model,train)
            scores={};scored={}
            modes=['original','fixed_mass'] if arm=='lif' else ['original','remove_equity','remove_annual','fixed_boundary','fixed_mass']
            own=model.router.forward
            try:
                for mode in modes:
                    if mode!='original':
                        model.router.forward=lambda patches,m=mode:release(model.router,patches,m,rates)
                    s,n=score(model,train,subset,torch.device('cpu'))
                    scores[mode]=s;scored[mode]=float(s.sum()/n.sum())
                    if n0 is None:n0=n
                    assert np.array_equal(n0,n)
            finally:
                model.router.forward=own
            np.savez_compressed(path/(k+'.npz'),counts=n0,ids=seedids,**scores)
            cells[k]=dict(arm=arm,seed=seed,stage=stage,selected_step=j['fit']['best_step'],current_step=j['fit']['steps'],
                selected_sha256=j['selected_sha256'],trace=diagnostics,training_nll=scored,raw_sha256=sha(path/(k+'.npz')))
            print(stage,k,diagnostics['mean_routed_mass'],flush=True)
    res={};draws=np.random.default_rng(118873).integers(len(n0),size=(4000,len(n0)))
    for arm in ARMS:
        rows=[cells[f'{arm}-{s}'] for s in SEEDS]
        res[arm]={}
        for mode in rows[0]['training_nll']:
            diffs=[]
            for seed in SEEDS:
                with np.load(path/f'{arm}-{seed}.npz') as z:
                    assert np.array_equal(z['ids'],seedids) and np.array_equal(z['counts'],n0)
                    diffs.append(z[mode]-z['original'])
            mean=np.mean(diffs,axis=0);boot=mean[draws].sum(1)/n0[draws].sum(1)
            res[arm][mode]=dict(nll_increment=float(mean.sum()/n0.sum()),paired_photo95=np.quantile(boot,[.025,.975]).tolist())
    write(path/'summary.json',dict(arms=res,cells=cells,training_trace_images=len(train.pix),scoring_train_images=len(subset),tokens=int(n0.sum()),
        subset_ids_sha256=hashlib.sha256(seedids.tobytes()).hexdigest(),sealed_stage_sha256=sha(archive/'stage_seal.json'),
        source=sha(Path(__file__)),protocol=sha(Path(__file__).with_name('PROTOCOL.md'))))


def main():
    BASE.mkdir(exist_ok=True);lock=(BASE/'trace.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    m=json.loads((ROOT/'data/manifest.json').read_text());train=Samples(ROOT/'data','train',m)
    subset=np.asarray(sorted(range(len(train.pix)),key=lambda i:hashlib.sha256(b'hepta-router-train-diagnostics-v1'+bytes(train.ids[i])).digest())[:256])
    for stage in BUDGETS:
        deadline=time.monotonic()+44000
        while not (ROOT/'development_archive'/f'{stage:04d}'/'stage_seal.json').is_file():
            if time.monotonic()>deadline:raise TimeoutError(stage)
            time.sleep(30)
        if not (BASE/f'{stage:04d}'/'summary.json').exists():main_stage(stage,train,subset,train.ids[subset])
    print('completed visual router mechanisms',flush=True)


if __name__=='__main__':main()
