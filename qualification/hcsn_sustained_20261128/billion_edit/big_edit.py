"""Restartable CPU-only hidden editing of the pinned 1.016B literal audiovisual HCSN."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import threading
import time

import numpy as np
import torch
from torch.nn import functional as F

from calibration_reference import fit as fit_scale, stats

SEEDS=(137,311,557)
ARMS=("forward","same_site_bp","head","shuffled","keep")
PREFIXES=(4,16)
STUDY_SHA="69e8cf12bcfcd414175250405ac08286901457377d76c1ad28f08d33a775dbc1"
DIRECT_SHA="eee77e7f1efea51f707b2468169b255131b667b5ec056e96e4fa5155548203bc"
DIM=4096
FULL_PARAMS=1016475200
SITE_PARAMS=4980736
SHARD=32


def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def checkpoint(path,writer):
    temp=path.with_suffix(path.suffix+'.tmp')
    with temp.open('wb') as f:
        writer(f); f.flush(); os.fsync(f.fileno())
    os.replace(temp,path)


def dump(p,v):checkpoint(p,lambda f:f.write((json.dumps(v,indent=1,allow_nan=False)+'\n').encode()))
def load(p):return json.loads(p.read_text())
def put(p,v):checkpoint(p,lambda f:torch.save(v,f))
def get(p):return torch.load(p,map_location='cpu',weights_only=True)
def amp():return torch.autocast(device_type='cpu',dtype=torch.bfloat16,cache_enabled=False)


def event(out,**payload):
    record={'utc_unix':time.time(),'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,**payload}
    with (out/'events.jsonl').open('a') as f:f.write(json.dumps(record,allow_nan=False)+'\n');f.flush()
    print(json.dumps(record,allow_nan=False),flush=True)


def watch_memory(out):
    def observe():
        while True:
            rss=int(next(x.split()[1] for x in Path('/proc/self/status').read_text().splitlines() if x.startswith('VmRSS:')))
            if rss>18*1024**2:
                event(out,stage="memory_guard",rss_kib=rss);os._exit(88)
            time.sleep(.5)
    threading.Thread(target=observe,daemon=True).start()


def ridge(x,y,force=None):
    x=x.double();y=y.double()
    n,d=x.shape;l2=max(1.e-9,.01*float(x.square().sum())/d)
    dual=n<d if force is None else force=='dual'
    gram=x@x.T if dual else x.T@x
    gram.diagonal().add_(l2)
    return (x.T@torch.linalg.solve(gram,y) if dual else torch.linalg.solve(gram,x.T@y)).T


def unit():
    g=torch.Generator().manual_seed(955)
    for n,d in ((23,140),(39,16)):
        x=torch.randn(n,d,generator=g,dtype=torch.float64);y=torch.randn(n,15,generator=g,dtype=torch.float64)
        a=ridge(x,y,'dual');b=ridge(x,y,'primal')
        delta=(a-b).abs().max().item()
        if delta>1e-10:raise ValueError('dual/primal ridge')
        resid=(x.T@(x@a.T-y)+.01*x.square().sum()/d*a.T).abs().max().item()
        if resid>1e-9:raise ValueError('ridge stationarity')
        yield {'rows':n,'width':d,'dual_primal_max_abs':delta,'normal_equations_max_abs':resid}


def matrices(net):
    return {**{f'read.{i}':m.read.weight for i,m in enumerate(net.mixer)},'projection':net.out[1].weight}


def make(root,d,seed):
    from encoder import AVText
    net=AVText('literal',DIM,seed,d.words,root/'src/law4.npz')
    if sum(p.numel() for p in net.parameters())!=FULL_PARAMS or sum(p.numel() for p in matrices(net).values())!=SITE_PARAMS:
        raise ValueError("wrong parameter counts")
    net.requires_grad_(False)
    return net


def values(net):
    return {k:v.detach().clone() for k,v in matrices(net).items()}


@torch.no_grad()
def restore(net,weights):
    params=matrices(net)
    if set(params)!=set(weights):raise ValueError('incomplete weight patch')
    for k,v in params.items():v.copy_(weights[k])


def transformed(net,h,lower,i):
    m,n1,ff,n2=net.mixer[i],net.n1[i],net.ff[i],net.n2[i]
    new_h=[];marks=[]
    for j in range(0,len(h),16):
        q=slice(j,j+16)
        with amp():
            out,mark,_=m(n1(h[q]),None if lower is None else lower[q],net.law)
            u=h[q]+out
            new_h.append((u+ff(n2(u))).float())
        marks.append(mark.float())
    return torch.cat(new_h),torch.cat(marks)


@torch.no_grad()
def forward_write(net,d,ids,method,seed,cell,out,progress):
    labels=d.y[ids]
    g=torch.Generator().manual_seed(seed+71439)
    proto=F.normalize(torch.randn(6,72,DIM,generator=g),dim=-1)*DIM**.5
    final=F.normalize(torch.randn(72,256,generator=g),dim=-1)
    target_y=labels[torch.randperm(len(ids),generator=g)] if method=='shuffled' else labels
    target_y=target_y.repeat(2)
    if progress.exists():
        old=get(progress);restore(net,old['weights']);start=old['next'];h,lower=old['h'],old['lower'];elapsed=old['fit_s']
    else:
        start=0;t=time.perf_counter()
        with amp():h=torch.cat((net.front(d.v[ids],d.audio[ids]),net.text(d.tokens[labels]))).float()
        lower=None;elapsed=time.perf_counter()-t
    for i in range(start,6):
        t=time.perf_counter()
        if method!='head':
            m=net.mixer[i];n1=net.n1[i];features=[];residual=[]
            handle=m.read.register_forward_pre_hook(lambda module,args:features.append(args[0][:,-1].float().clone()))
            try:
                for j in range(0,len(h),16):
                    q=slice(j,j+16)
                    with amp():
                        part,_,_=m(n1(h[q]),None if lower is None else lower[q],net.law)
                    residual.append((h[q]+part)[:,-1].float())
            finally:handle.remove()
            current=torch.cat(residual);teacher=proto[i,target_y]*current.square().mean().sqrt()
            delta=ridge(torch.cat(features),teacher-current).float()
            m.read.weight.add_(delta,alpha=.5)
        h,lower=transformed(net,h,lower,i)
        elapsed+=time.perf_counter()-t
        put(progress,{'weights':values(net),'next':i+1,'h':h,'lower':lower,'fit_s':elapsed})
        event(out,cell=cell.name,stage="hidden_layer_written" if method!='head' else 'frozen_layer_traversed',layer=i+1,optimization_s=elapsed)
    t=time.perf_counter()
    net.out[1].weight.copy_(ridge(net.out[0](h[:,-1]),final[labels.repeat(2)]).float())
    return elapsed+time.perf_counter()-t


def bp_write(net,d,ids,cell,out,progress):
    from encoder import pair_loss
    selected=list(matrices(net).values())
    for p in selected:p.requires_grad_(True)
    opt=torch.optim.AdamW(selected,lr=.0001,weight_decay=.01,foreach=False)
    elapsed=0.;start=0
    if progress.exists():
        q=get(progress);restore(net,q['weights']);opt.load_state_dict(q['optimizer'])
        start=q['next'];elapsed=q['fit_s']
    for k,rows in enumerate(ids.reshape(-1,16)):
        if k<start:continue
        t=time.perf_counter();opt.zero_grad(set_to_none=True)
        y=d.y[rows]
        with amp():v,txt=net(d.v[rows],d.audio[rows],d.tokens[y])
        loss=pair_loss(v.float(),txt.float(),y)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(selected,1.,error_if_nonfinite=True);opt.step()
        elapsed+=time.perf_counter()-t
        put(progress,{'weights':values(net),'optimizer':opt.state_dict(),'next':k+1,'fit_s':elapsed})
        event(out,stage="bp_update",cell=cell.name,completed=k+1,loss=float(loss.detach()),optimization_s=elapsed)
    return elapsed


def fitted(root,d,cell,method,seed,n,out):
    meta=cell/'fit.json';patch=cell/'writes.pt'
    if meta.exists():
        j=load(meta)
        if digest(patch)!=j['sha256']:raise ValueError("weights mismatch")
        return j
    t=time.perf_counter()
    net=make(root,d,seed);base=values(net)
    idx=np.random.default_rng(seed+7369).choice(d.train,size=(n,16)).ravel()
    progress=cell/'partial.pt';setup=time.perf_counter()-t
    if method=='same_site_bp':fit_s=bp_write(net,d,idx,cell,out,progress)
    elif method!='keep':fit_s=forward_write(net,d,idx,method,seed,cell,out,progress)
    else:fit_s=0.
    weights=values(net)
    delta={k:v-base[k] for k,v in weights.items()}
    changed={k:int(v.count_nonzero()) for k,v in delta.items()}
    if method=='forward' and min(changed.values())<=0:raise ValueError("missing hidden edit")
    if method=='keep' and sum(changed.values())!=0:raise ValueError("KEEP changed")
    post=time.perf_counter()
    put(patch,weights)
    result={'method':method,'seed':seed,'steps':n,'examples':len(idx),'unique_examples':len(np.unique(idx)),
            'input_index_sha256':hashlib.sha256(idx.astype('<i8').tobytes()).hexdigest(),'full_parameters':FULL_PARAMS,
            'eligible_parameters':SITE_PARAMS,'changed':changed,'delta_frobenius':{k:float(v.norm()) for k,v in delta.items()},
            'sha256':digest(patch),'setup_s':setup,'optimization_s':fit_s,'postfit_s':time.perf_counter()-post}
    # Wall time for actual full successful uninterrupted training or resumed segment.
    result['invocation_wall_s']=time.perf_counter()-t
    dump(meta,result)
    if progress.exists():progress.unlink()
    event(out,cell=cell.name,stage='fit_complete',optimization_s=fit_s,changed=sum(changed.values()))
    return result


@torch.no_grad()
def predict(root,d,cell,rows,split,seed,out):
    folder=cell/split;folder.mkdir(exist_ok=True);final=folder/'scores.npz';meta=folder/'timing.json'
    if final.exists() and meta.exists():
        receipt=load(meta)
        if digest(final)!=receipt['sha256']:raise ValueError("score hash mismatch")
        with np.load(final) as a:
            if not np.array_equal(a['ids'],d.names[rows]) or not np.array_equal(a['labels'],d.y[rows].numpy()):raise ValueError('split mismatch')
            return a['scores'],receipt['wall_s']
    start=time.perf_counter();net=make(root,d,seed);restore(net,get(cell/'writes.pt'));net.eval()
    with amp():prompts=net.encode(net.text(d.tokens))
    prompt=prompts.float()
    scores=[];elapsed=time.perf_counter()-start
    for j in range(0,len(rows),SHARD):
        group=rows[j:j+SHARD];part=folder/f'{j:05}.npz'
        if part.exists():
            with np.load(part) as f:
                if not np.array_equal(f['ids'],d.names[group]):raise ValueError('shard identity')
                s=f['scores'];cost=float(f['elapsed'])
        else:
            t=time.perf_counter()
            with amp():h=net.encode(net.front(d.v[group],d.audio[group]))
            s=(12*(h.float()@prompt.T)).numpy()
            if not np.isfinite(s).all() or s.shape!=(len(group),72):raise ValueError('bad logits')
            cost=time.perf_counter()-t
            checkpoint(part,lambda f:np.savez(f,ids=d.names[group],scores=s,elapsed=cost))
        scores.append(s);elapsed+=cost
    total=np.concatenate(scores)
    checkpoint(final,lambda f:np.savez_compressed(f,ids=d.names[rows],labels=d.y[rows].numpy(),scores=total))
    dump(meta,{'wall_s':elapsed,'sha256':digest(final),'clips':len(rows),'cold':split=='cold'})
    event(out,cell=cell.name,stage=split+'_complete',seconds=elapsed)
    return total,elapsed


def launch(args):
    base,root,out=args.base.resolve(),args.root.resolve(),args.out.resolve()
    out.mkdir(mode=0o700,parents=True,exist_ok=True)
    lock=(out/'job.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if (out/'terminal.json').exists():print("already finished",flush=True);return
    watch_memory(out);torch.set_num_threads(1);torch.set_num_interop_threads(1)
    try:os.nice(5)
    except OSError:pass
    t=time.perf_counter();sys.path[:0]=[str(base),str(root/'src')]
    if digest(base/'study.py')!=STUDY_SHA or digest(base/'direct.py')!=DIRECT_SHA:raise ValueError('study source mismatch')
    from study import Data,HASHES
    for r,sha in HASHES.items():
        if digest(root/r)!=sha:raise ValueError('prepared source mismatch')
    d=Data(root);dy=d.y[d.dev].numpy();count=np.bincount(d.y[d.train].numpy(),minlength=72)
    if min(count)<=0:raise ValueError('empty train class')
    prior=np.log(count/count.sum());zero=np.zeros_like(prior)
    design={'source_sha256':digest(Path(__file__)),'secondary_source_sha256':digest(Path(__file__).with_name('calibration_reference.py')),
            'protocol_sha256':digest(Path(__file__).with_name('PROTOCOL.md')),
            'parent_hashes':HASHES,'study_sha256':STUDY_SHA,'direct_sha256':DIRECT_SHA,
            'torch':str(torch.__version__),'device':'cpu','threads':torch.get_num_threads(),
            'full_parameters':FULL_PARAMS,'eligible_parameters':SITE_PARAMS,'seeds':SEEDS,'arms':ARMS,
            'prefixes':PREFIXES,'train_dev_cold':[len(d.train),len(d.dev),len(d.test)],
            'ridge_checks':list(unit()),'train_histogram':count.tolist()}
    stamp=out/'design.json'
    if stamp.exists() and load(stamp)!=json.loads(json.dumps(design)):raise ValueError('resumed design differs')
    if not stamp.exists():dump(stamp,design)
    common=time.perf_counter()-t
    event(out,stage='verified_launch',common_preparation_s=common,full_parameters=FULL_PARAMS,eligible=SITE_PARAMS)
    cells=[]
    for i,seed in enumerate(SEEDS):
        for n in PREFIXES:
            for a in range(len(ARMS)):
                method=ARMS[(a+i)%len(ARMS)]
                if method=='keep' and n!=PREFIXES[0]:continue
                cell=out/f'{method}-{seed}-{n}';cell.mkdir(exist_ok=True)
                cells.append((method,seed,n,cell))
    for method,seed,n,cell in cells:fitted(root,d,cell,method,seed,n,out)
    candidates={}
    for method,seed,n,cell in cells:
        path=cell/'development.json'
        if path.exists():record=load(path)
        else:
            raw,etime=predict(root,d,cell,d.dev,'dev',seed,out)
            scores=raw.astype(np.float64);t=time.perf_counter()
            uncal,_=stats(scores,dy,1.,zero);cal=fit_scale(scores,dy,prior)
            fit_meta=load(cell/'fit.json')
            record={'cell':cell.name,'steps':n,'weights_sha256':fit_meta['sha256'],'dev_score_sha256':digest(cell/'dev'/'scores.npz'),
                    'raw':uncal,'secondary':cal,'dev_seconds':etime,'calibration_seconds':time.perf_counter()-t,
                    'original_fit_seconds':fit_meta['invocation_wall_s']}
            dump(path,record)
        candidates.setdefault(f'{method}-{seed}',[]).append(record)
    if sum(map(len,candidates.values()))!=27:raise ValueError('incomplete development panel')
    picks={}
    for group,rows in candidates.items():
        picks[group]={'raw':min(rows,key=lambda r:(r['raw']['nll'],r['steps']))['cell'],
                      'secondary':min(rows,key=lambda r:(r['secondary']['dev']['nll'],r['steps']))['cell']}
    frozen={'design_sha256':digest(stamp),'candidates':candidates,'picks':picks}
    seal=out/'development_seal.json'
    if seal.exists() and load(seal)!=frozen:raise ValueError('selection seal mismatch')
    if not seal.exists():dump(seal,frozen)
    seal_sha=digest(seal);event(out,stage='all_candidates_sealed',sha256=seal_sha)
    cy=d.y[d.test].numpy();actors=d.actors[d.test];who=np.unique(actors)
    selected_losses={'raw':{},'secondary':{}};coldrows={};total_cost={}
    for method,seed,n,cell in cells:
        raw,seconds=predict(root,d,cell,d.test,'cold',seed,out)
        data=load(cell/'development.json');group=f'{method}-{seed}'
        coldrows[cell.name]={}
        coldrows[cell.name]['cold_seconds']=seconds
        for mode,beta,bias in [('raw',1.,zero),('secondary',data['secondary']['multiplier'],prior)]:
            metric,loss=stats(raw.astype(np.float64),cy,beta,bias)
            if picks[group][mode]==cell.name:selected_losses[mode][group]=loss
            dv=data['raw'] if mode=='raw' else data['secondary']['dev']
            coldrows[cell.name][mode]={'dev':dv,'cold':metric,'at_4_1':max(dv['nll'],metric['nll'])<=4.1}
            cost=data['original_fit_seconds']+data['dev_seconds']+seconds
            if mode=='secondary':cost+=data['calibration_seconds']
            total_cost.setdefault(group,{'raw':common,'secondary':common})[mode]+=cost
    means={};contrasts={};mass=np.array([(actors==a).sum() for a in who])
    ix=np.random.default_rng(91363).integers(len(who),size=(4000,len(who)))
    for mode,losses in selected_losses.items():
        means[mode]={}
        for method in ARMS:
            groups=[f'{method}-{s}' for s in SEEDS];rows=[coldrows[picks[g][mode]][mode] for g in groups]
            means[mode][method]={'dev_nll':float(np.mean([r['dev']['nll'] for r in rows])),
                'cold_nll':float(np.mean([r['cold']['nll'] for r in rows])),
                'cold_top1':float(np.mean([r['cold']['top1'] for r in rows])),
                'seeds_both_at_4_1':sum(r['at_4_1'] for r in rows),
                'mean_both_prefixes_end_to_end_s':float(np.mean([total_cost[g][mode] for g in groups]))}
        contrasts[mode]={}
        for method in ARMS[1:]:
            diff=np.stack([losses[f'forward-{s}']-losses[f'{method}-{s}'] for s in SEEDS]).mean(0)
            sums=np.array([diff[actors==a].sum() for a in who])
            boots=sums[ix].sum(1)/mass[ix].sum(1)
            contrasts[mode][method]={'mean':float(diff.mean()),'actor_ci95':np.quantile(boots,[.025,.975]).tolist(),
                                     'paired_actor_loss_sums':sums.tolist(),'actor_clip_counts':mass.tolist()}
    if digest(seal)!=seal_sha:raise ValueError('seal changed')
    result={'source_sha256':design['source_sha256'],'development_seal_sha256':seal_sha,'cold_by_candidate':coldrows,
            'selection':picks,'averages':means,'paired_actor_contrasts':contrasts,'costs':total_cost,
            'training_prior_cold':stats(np.zeros((len(cy),72)),cy,0.,prior)[0],
            'test_actors':who.tolist(),'full_parameters':FULL_PARAMS,'eligible_parameters':SITE_PARAMS}
    dump(out/'terminal.json',result);event(out,stage='terminal',result_sha256=digest(out/'terminal.json'))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for flag in ('base','root','out'):p.add_argument(flag,type=Path)
    args=p.parse_args()
    launch(args)
