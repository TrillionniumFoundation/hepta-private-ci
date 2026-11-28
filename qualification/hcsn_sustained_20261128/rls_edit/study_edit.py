"""Frozen-parent sequential CREMA-D weight edits; full development seal precedes held scoring."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import numpy as np
import torch
from torch.nn import functional as F
from rls_core import BUDGETS,METHODS,GROUPS,prior,rls_step,projected,target_labels,summarize,outcomes,select_masks,gate,unit

SEEDS=(137,311,557)
PARENT_SEAL='6ef8baad733525893762dd8fd7e79e30b133cf2bc023e409ff570627699d100c'
PROTOCOL='849c3c01a416b21072124a388324c01d398f6fc331212693ea8bb374bbd77b45'
HERE=Path(__file__).resolve().parent


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(p.read_text())
def write(p,d):
    p.parent.mkdir(exist_ok=True,parents=True);tmp=p.with_suffix('.tmp')
    tmp.write_text(json.dumps(d,sort_keys=True,indent=1,allow_nan=False)+'\n');tmp.replace(p)
def npz(p,**d):
    temp=p.with_suffix('.partial')
    with temp.open('wb') as f:np.savez_compressed(f,**d)
    temp.replace(p)
def as_tensor(a):return torch.from_numpy(a).contiguous()
def strain(z):return z.detach().contiguous().cpu().numpy()


@torch.no_grad()
def feature(net, data, rows=None):
    captures=[]
    hook=net.out[1].register_forward_pre_hook(lambda m,args:captures.append(args[0].detach().clone()))
    try:
        if rows is None:
            approx=net.encode(net.text(data.tokens));k=captures[0]
        else:
            outputs=[net.encode(net.front(data.v[idx],data.audio[idx])) for idx in np.array_split(rows,(len(rows)+31)//32)]
            approx=torch.cat(outputs);k=torch.cat(captures)
    finally:hook.remove()
    if k.shape!=(len(k),96):raise ValueError(k.shape)
    return k,approx


def parent_info(parent_root,seed):
    fix=parent_root/'whole_edit';primary=fix/'development_seal.json'
    assert sha(primary)==PARENT_SEAL
    seal=read(primary);key=f'full_bp-{seed}';epoch=seal['picks'][key]['raw']
    rec=next(r for r in seal['fits'][key] if r['epoch']==epoch)
    weights=fix/key/rec['weights'];assert sha(weights)==rec['sha256']
    return weights,{'seed':seed,'epoch':epoch,'sha256':rec['sha256'],'training_examples':rec['training_examples'],
                    'model_parameters':rec['model_parameters'],'fit_s':rec['fit_s'],
                    'through_parent_development_s':rec['charged_to_development_s'],'previous_total_arm_s':read(fix/'terminal.json')['charged_s'][key]}


def get_net(root,d,s,parent_root):
    from direct import make_net
    p,receipt=parent_info(parent_root,s)
    net=make_net(root,d,s);net.load_state_dict(torch.load(p,weights_only=True,map_location='cpu'));net.eval();net.requires_grad_(False)
    return net,receipt


def materialize(root,d,out,seed,held,parent_root):
    from study import inference
    base=out/str(seed);base.mkdir(exist_ok=True)
    side='held' if held else 'basis'
    meta=base/(side+'.json');archive=base/(side+'.npz')
    if meta.is_file():
        note=read(meta);assert sha(archive)==note['archive_sha256'];return note
    ts=time.perf_counter();net,rec=get_net(root,d,seed,parent_root);parent_load=time.perf_counter()-ts;tic=time.perf_counter()
    with torch.no_grad():
        kt,prompt=feature(net,d);w0=net.out[1].weight.T.contiguous()
        assert kt.shape==(72,96) and w0.shape==(96,256)
        groups={'held':d.test} if held else {'train':d.train,'dev':d.dev};a={'text':strain(kt),'W0':strain(w0)}
        errs={}
        for split,idx in groups.items():
            k,pred=feature(net,d,idx);native=12*(pred@prompt.T)
            cached=projected(k,kt,w0)
            err=float((native-cached).abs().max());assert err<2e-5,(err,split)
            if split in ('dev','held'):
                check=inference(net,d,idx);err=max(err,float((check-cached).abs().max()));assert err<2e-5
            a.update({split:strain(k),split+'_y':strain(d.y[idx]),split+'_ids':d.names[idx]});errs[split]=err
    npz(archive,**a);note={'parent':rec,'parent_deserialization_s':parent_load,'keys_and_validation_and_save_s':time.perf_counter()-tic,
                            'archive_sha256':sha(archive),'parent_native_max_abs':errs}
    write(meta,note);return note


def load_arrays(p):
    with np.load(p,allow_pickle=False) as d:return {k:(d[k] if k.endswith('_ids') else as_tensor(d[k])) for k in d.files}


def gradients(mode,wprev,w0,anchors,mu,k,v,labels,text,capture):
    w=wprev.float().clone().requires_grad_(True);base=w0.float();a=anchors.float()
    opt=torch.optim.Adam([w],lr=.003)
    if mode=='quad':
        gram,rhs=prior(base,a,mu);gram+=k.T@k;rhs+=k.T@v
    for step in range(1,129):
        opt.zero_grad(set_to_none=True)
        if mode=='quad':
            loss=((w*(gram@w)).sum()-2*(w*rhs).sum())/(len(k)*w.shape[1])
        else:
            delta=w-base
            reg=(delta.square().sum()+mu**2*(a@delta).square().sum())/(len(k)*w.shape[1])
            loss=F.cross_entropy(projected(k,text,w),labels)+reg
        loss.backward();opt.step()
        if step in BUDGETS:capture(step,w.detach().clone())
    return w.detach().double()


def fit_one(out,seed,arm):
    setup_begin=time.perf_counter();base=out/str(seed);b=load_arrays(base/'basis.npz');basis_read=time.perf_counter()-setup_begin;dest=base/arm;dest.mkdir(exist_ok=True)
    w0=b['W0'].double();text=b['text'];y=b['train_y'];idxs=b['train_ids'];dev=b['dev'];dy=b['dev_y']
    old=projected(dev,text,w0.float());keys=b['train'];protected=np.flatnonzero(y.numpy()//6>=6)
    protected=protected[np.argsort(idxs[protected],kind='stable')]
    keep=np.random.default_rng(912731).choice(protected,size=128,replace=False); keep=keep[np.argsort(idxs[keep],kind='stable')]
    anchors=torch.cat((text,keys[keep])).double();assert anchors.shape==(200,96)
    template=F.normalize(text.double()@w0,dim=-1)
    mu=float(arm.split('-')[-1]) if arm!='parent' else 0.
    tic=time.perf_counter()
    if arm.startswith('rls'):
        start,_=prior(w0,anchors,mu);p=torch.linalg.inv(start)
    else:p=torch.empty(0,dtype=torch.float64)
    inverse_setup=time.perf_counter()-tic;setup=time.perf_counter()-setup_begin;w=w0.clone();elapsed=setup;written={}
    all_keys=[];allv=[];alllabels=[]
    for stage in range(6):
        sf=dest/f'stage{stage}.json';saved=dest/f'stage{stage}.npz'
        tic=time.perf_counter()
        order=np.flatnonzero(y.numpy()//6==stage);order=order[np.argsort(idxs[order],kind='stable')]
        k=keys[order].double();new=target_labels(y[order],stage)
        v=(k@w0).norm(dim=1,keepdim=True)*template[new];all_keys.append(k);allv.append(v);alllabels.append(new)
        if sf.exists():
            note=read(sf);assert sha(saved)==note['archive_sha256'];st=load_arrays(saved)
            w=st['last'].double();p=st['inverse'].double();elapsed=note['through_stage_s'];written[str(stage)]=note;continue
        checkpoints={};records={};dold=summarize(old,old,dy,stage);numerical=None
        prep_s=time.perf_counter()-tic;dev_s=0.;training_start=time.perf_counter()
        def capture(n,weight):
            nonlocal dev_s
            validation_start=time.perf_counter();name=str(n);cast=weight.detach().float().contiguous();checkpoints['W'+name]=strain(cast)
            pred=projected(dev,text,cast);met=summarize(pred,old,dy,stage)
            records[name]={'development':met,'gate':bool(gate(met,dold)),
                           'through_candidate_s':elapsed+time.perf_counter()-tic,
                           'frobenius_delta':float((cast.double()-w0).norm()),
                           'changed':int((cast!=w0.float()).sum())}
            dev_s+=time.perf_counter()-validation_start
        if arm=='parent':capture(0,w)
        elif arm.startswith('rls'):
            w,p=rls_step(w,p,k,v);capture(0,w)
            # Batch parity is an audit cost tracked separately for this arm.
            audit_start=time.perf_counter()
            kk=torch.cat(all_keys);vv=torch.cat(allv);s,t=prior(w0,anchors,mu)
            ref=torch.linalg.solve(s+kk.T@kk,t+kk.T@vv)
            diff=w-ref;rel=float(diff.norm()/ref.norm());absolute=float(diff.abs().max())
            assert rel<1e-7 and absolute<1e-7,(stage,rel,absolute)
            numerical={'relative_frobenius':rel,'max_absolute':absolute,'audit_wall_s':time.perf_counter()-audit_start}
        elif arm.startswith('recent'):
            s,t=prior(w0,anchors,mu);w=torch.linalg.solve(s+k.T@k,t+k.T@v);capture(0,w)
        else:
            w=gradients(arm.split('-')[0],w,w0,anchors,mu,torch.cat(all_keys).float(),torch.cat(allv).float(),torch.cat(alllabels),text,capture)
        audit_s=numerical['audit_wall_s'] if numerical else 0.
        optimize_s=time.perf_counter()-training_start-dev_s-audit_s;save_start=time.perf_counter()
        npz(saved,last=strain(w),inverse=strain(p),**checkpoints);save_s=time.perf_counter()-save_start;elapsed+=time.perf_counter()-tic-audit_s
        note={'stage':stage,'train_examples_current':len(order),'train_examples_cumulative':sum(map(len,all_keys)),
              'owner_seed':seed,'arm':arm,'anchor_ids_sha256':hashlib.sha256('\n'.join(idxs[keep]).encode()).hexdigest(),
              'train_order_sha256':hashlib.sha256('\n'.join(idxs[order]).encode()).hexdigest(),'anchor_count':200,
              'setup_s':setup,'basis_read_s':basis_read,'initial_inverse_setup_s':inverse_setup,
              'stage_keys_and_parent_metrics_s':prep_s,'stage_algebra_or_gradient_s':optimize_s,'stage_development_s':dev_s,'stage_serialization_s':save_s,'through_stage_s':elapsed,'archive_sha256':sha(saved),'records':records,'batch_parity':numerical}
        write(sf,note);written[str(stage)]=note
        print('stage',seed,arm,stage,round(elapsed,2),flush=True)
    return written


def freeze(root,out,parent_root):
    from study import Data,HASHES
    for rel,h in HASHES.items():assert sha(root/rel)==h,rel
    start=time.perf_counter();d=Data(root)
    prep=out/'prepared.json'
    if not prep.exists():write(prep,{'shared_input_load_s':time.perf_counter()-start,'data_hashes':HASHES,'unit':unit()})
    assert read(prep)['data_hashes']==HASHES
    registry={};picks={}
    for s in SEEDS:
        materialize(root,d,out,s,False,parent_root)
        for arm in METHODS:
            block=fit_one(out,s,arm);key=f'{s}/{arm}';registry[key]={};picks[key]={}
            for j,r in block.items():
                registry[key][j]={'metadata':sha(out/str(s)/arm/f'stage{j}.json'),'weights_hash':r['archive_sha256']}
                passing=[int(n) for n,rec in r['records'].items() if rec['gate']]
                picks[key][j]={'primary':max(map(int,r['records'])),'earliest_dev_gate_budget':min(passing) if passing else None}
    node={'protocol_sha256':sha(HERE/'PROTOCOL.md'),'source_sha256':sha(Path(__file__)),'core_sha256':sha(HERE/'rls_core.py'),
          'parent_selection_sha256':PARENT_SEAL,'parents':{str(s):read(out/str(s)/'basis.json') for s in SEEDS},
          'prepared_sha256':sha(prep),'stages':registry,'picks':picks}
    seal=out/'development_seal.json'
    if seal.exists():assert read(seal)==node
    else:write(seal,node)
    print('sealed',sha(seal),len(registry),flush=True)
    return d,node


def score(root,out,d,seal,parent_root):
    from study import inference
    losses={};metrics={};clocks={}
    for s in SEEDS:
        sb=out/str(s);materialize(root,d,out,s,True,parent_root);b=load_arrays(sb/'held.npz')
        av,text,w0=b['held'],b['text'],b['W0'];y=b['held_y'];actors=np.array([str(i).split('_')[0] for i in b['held_ids']])
        parent_logits=projected(av,text,w0)
        for arm in METHODS:
            key=f'{s}/{arm}';metrics[key]={};clocks[key]={}
            for st in range(6):
                j=str(st);p=sb/arm/f'stage{st}.npz';note=read(sb/arm/f'stage{st}.json')
                assert sha(p)==seal['stages'][key][j]['weights_hash']
                data=load_arrays(p);pack={};sttime=time.perf_counter();rows={};audit_s=0.
                doparent=summarize(parent_logits,parent_logits,y,st)
                for n,record in note['records'].items():
                    w=data['W'+n];z=projected(av,text,w);pack['scores'+n]=strain(z)
                    if st==5 and arm=='rls-1':
                        checkstart=time.perf_counter();net,_=get_net(root,d,s,parent_root)
                        with torch.no_grad():net.out[1].weight.copy_(w.T)
                        err=float((inference(net,d,d.test)-z).abs().max());assert err<2e-5
                        audit_s+=time.perf_counter()-checkstart
                    met=summarize(z,parent_logits,y,st);rows[n]={'cold':met,'gate':bool(gate(met,doparent))}
                    if int(n)==seal['picks'][key][j]['primary']:
                        losses[s,arm,st]=outcomes(z,parent_logits,y,st)
                file=sb/arm/f'held{st}.npz';npz(file,ids=b['held_ids'],original_y=strain(y),edited_y=strain(target_labels(y,st)),**pack)
                metrics[key][j]={'budgets':rows,'scores_sha256':sha(file)}
                clocks[key][j]={'through_inference_and_save_s':time.perf_counter()-sttime-audit_s,'separate_native_parity_audit_s':audit_s}
        # Original data ordering is identical across seeds.
    who=np.unique(actors);assert len(who)==16
    draws=np.random.default_rng(83573).integers(len(who),size=(4000,len(who)))
    contrasts={}
    for mu in (1,4):
        a=f'rls-{mu}'
        for ctrl in ('parent',f'recent-{mu}',f'quad-{mu}',f'ce-{mu}'):
            key=f'{a}_minus_{ctrl}';contrasts[key]={}
            for st in range(6):
                dif={}
                for group,mask0 in select_masks(y,st).items():
                    mask=mask0.numpy()
                    if not mask.any():continue
                    count=np.array([np.sum(mask&(actors==v)) for v in who])
                    dif[group]={}
                    for metric in ('nll','top1','kl_parent_edited'):
                        dv=np.stack([losses[s,a,st][metric]-losses[s,ctrl,st][metric] for s in SEEDS]).mean(0)
                        sums=np.array([dv[mask&(actors==v)].sum() for v in who]);den=count[draws].sum(1)
                        boot=sums[draws].sum(1)/den
                        dif[group][metric]={'mean':float(dv[mask].mean()),'actor_CI95':np.quantile(boot,[.025,.975]).tolist()}
                contrasts[key][str(st)]=dif
    common=read(out/'prepared.json')['shared_input_load_s'];gates={}
    for arm in METHODS:
        gates[arm]={}
        for st in range(6):
            re={}
            for s in SEEDS:
                key=f'{s}/{arm}';j=str(st);selected=seal['picks'][key][j]['earliest_dev_gate_budget']
                if selected is None:re[str(s)]={'qualified':False,'reason':'development censored'};continue
                n=str(selected);node=metrics[key][j]['budgets'][n]
                b=seal['parents'][str(s)];h=read(out/str(s)/'held.json');rec=read(out/str(s)/arm/f'stage{st}.json')
                # All registered budgets at this and earlier stages were scored. Charge full qualification overhead as a conservative upper bound.
                extra=sum(clocks[key][str(k)]['through_inference_and_save_s'] for k in range(st+1))
                wall=common+b['parent_deserialization_s']+b['keys_and_validation_and_save_s']+rec['through_stage_s']+h['parent_deserialization_s']+h['keys_and_validation_and_save_s']+extra
                re[str(s)]={'qualified':node['gate'],'selected_budget':selected,'charged_qualification_upper_s':wall,
                            'optimization_and_development_through_selected_candidate_s':rec['records'][n]['through_candidate_s'],'inherited_parent_training_s':b['parent']['fit_s']}
            gates[arm][str(st)]={'all_three':all(v['qualified'] for v in re.values()),'by_seed':re}
    terminal={'seal_sha256':sha(out/'development_seal.json'),'seed_count':3,'methods':METHODS,'stages':6,'cold_subjects':16,
              'score_archives':len(metrics)*6,'weights_archives':len(metrics)*6,'cold_scores':metrics,'timing':clocks,
              'paired_actor_contrasts':contrasts,'quality_gates':gates}
    write(out/'terminal.json',terminal);print('terminal',sha(out/'terminal.json'),flush=True)


def run(root,out,parent_root):
    torch.set_num_threads(1);torch.set_num_interop_threads(1);out.mkdir(parents=True,exist_ok=True)
    lock=(out/'lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    sys.path.insert(0,str(parent_root));sys.path.insert(0,str(root/'src'))
    assert sha(HERE/'PROTOCOL.md')==PROTOCOL
    if (out/'terminal.json').exists():return
    d,s=freeze(root,out,parent_root);score(root,out,d,s,parent_root)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('out',type=Path);p.add_argument('--study-root',type=Path,required=True);args=p.parse_args()
    run(args.root.resolve(),args.out.resolve(),args.study_root.resolve())
