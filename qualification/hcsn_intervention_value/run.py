"""Fit, seal and then confirm source-grouped intervention policies in fresh processes."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

START=time.monotonic()
import numpy as np
import torch
from qualification.hcsn_qvi_retrieval.verify import UPSTREAM
from qualification.hcsn_qvi_retrieval.adapt import FitConfig,fit_arm,predict
from .policy import (HORIZON,STOP,READ,WAIT,PRICE,RATE,RHO,features,fit_teacher,forecast,
                     free_state,representation,stop_values,validate)

HERE=Path(__file__).parent
SEEDS=(181391,284729,395201)
ARMS=[('plain','keep')]+[(m,opt) for m in ('context','fixed','learned','qvi','external') for opt in ('keep','bp')]
AVAIL=('read','noread')


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path,x):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f: json.dump(x,f,separators=(',',':'),allow_nan=False); f.write('\n')


def load(path): return json.loads(path.read_text())


def sources():
    names=['hcsn_intervention_value/policy.py','hcsn_intervention_value/run.py','hcsn_intervention_value/policy_protocol.json','hcsn_intervention_value/protocol.json',
           'hcsn_qvi_task_surface/model.py','hcsn_qvi_retrieval/dynamics.py','hcsn_qvi_retrieval/adapt.py']
    for n,oid in UPSTREAM.items():
        payload=(HERE.parent/n).read_bytes()
        if hashlib.sha1(f'blob {len(payload)}\0'.encode()+payload).hexdigest()!=oid:
            raise ValueError('pinned Git source changed: '+n)
    return {n:sha(HERE.parent/n) for n in names+['hcsn_qvi_retrieval/verify.py']+sorted(UPSTREAM)}


def shard(root,name):
    path=root/(name+'.npz')
    with np.load(path,allow_pickle=False) as data:
        s={k:data[k] for k in ('x','dt','group','source','target','query_id')}
        for key,alias in [('scores','free'),('read_scores','paid')]: s[key]=data[key if key in data else alias]
        if 'class_id' in data: s['class_id']=data['class_id']
        if 'split' in data and set(np.asarray(data['split']).reshape(-1).tolist())!={name}: raise ValueError('split name mismatch')
    validate(s); s['hash']=sha(path); return s


def ids(s): return {k:sorted({str(v) for v in s[k]}) for k in ('source','group','query_id')}


def disjoint(a,b):
    for k in a:
        if set(a[k])&set(b[k]): raise ValueError('cross-split overlap in '+k)


def init(threads=1):
    torch.set_num_threads(threads); torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)


def check_front(data):
    file=data/'frontend_seal.json'; seal=load(file)
    if (not seal.get('selected') or seal.get('heldout_opened') is not False or
        set(seal['sha256'])!={'train.npz','dev.npz','retain.npz','front_weights.json','panels.json','chooser.json'} or
        any(sha(data/name)!=v for name,v in seal['sha256'].items())):
        raise ValueError('unselected frontend or changed frontend evidence')
    panels=load(data/'panels.json'); chosen=panels[seal['selected']]
    if any(not chosen[phase]['paid_gate_pass'] for phase in ('train','dev')):
        raise ValueError('paid intervention failed TRAIN or DEV opportunity gate')
    return sha(file)


def check_test_receipt(data,evidence):
    model=check_seal(evidence); front=check_front(data); meta=load(evidence/'prepare/metadata.json')
    ticket=load(data/'heldout_controls.json')
    if (meta['frontend_seal']!=front or ticket['policy_seal']!=model or
        ticket['frontend_seal']!=front or sha(data/'test.npz')!=ticket['ready_hash']):
        raise ValueError('missing materialization ticket for this frozen policy and TEST archive')
    return model


def prepare_fit(data,evidence):
    frontend_sha=check_front(data)
    names=['train','dev','retain']; parts={n:shard(data,n) for n in names}
    identities={n:ids(s) for n,s in parts.items()}
    for i,n in enumerate(names):
        for o in names[:i]: disjoint(identities[n],identities[o])
    train=parts['train']; z=free_state(train['x'],train['scores'],train['dt'])
    _,idx,count=np.unique(train['group'],return_inverse=True,return_counts=True)
    w=1/count[idx]; w=w/w.sum()
    mu=w@z.mean(1); scale=np.sqrt(w@((z-mu)**2).mean(1)).clip(min=1e-6)
    for avail in AVAIL:
        start=time.monotonic(); cpu=time.process_time(); obj=fit_teacher(train,avail=='read')
        for k in ('held','targets'): obj[k]=obj[k].tolist()
        obj.update(availability=avail,train_hash=train['hash'],row_ids=train['query_id'].astype(str).tolist(),
                   elapsed_seconds=time.monotonic()-start,cpu_seconds=time.process_time()-cpu)
        write(evidence/'prepare'/(avail+'.json'),obj)
    write(evidence/'prepare'/'metadata.json',dict(sources=sources(),frontend_seal=frontend_sha,identities=identities,
          inputs={n:s['hash'] for n,s in parts.items()},mu=mu.tolist(),scale=scale.tolist(),
          seeds=SEEDS,arms=ARMS,fit_splits=names,physical_clock_seconds=[.48]*HORIZON))


def frontend(s,meta,teacher,training=False):
    z=free_state(s['x'],s['scores'],s['dt'])
    if training:
        if s['hash']!=teacher['train_hash'] or list(map(str,s['query_id']))!=teacher['row_ids']: raise ValueError('TRAIN row alignment')
        q=np.asarray(teacher['held']); s['targets']=np.array(teacher['targets'])
        _,idx,count=np.unique(s['group'],return_inverse=True,return_counts=True)
        s['row_weights']=np.broadcast_to((1./count[idx])[:,None],s['dt'].shape).copy()
    else: q=forecast(teacher['models'],z)
    s['qt']=torch.from_numpy(q); s['zt']=torch.from_numpy((z-meta['mu'])/meta['scale'])
    s['clock']=torch.from_numpy(s['dt'].astype(np.float64))
    return s


def score(q,s,can_read):
    # Decisions are completely determined by prefix scores before paid outcomes are joined.
    q=np.asarray(q).copy()
    if q.shape!=(*s['dt'].shape,3) or not np.isfinite(q).all(): raise ValueError('nonfinite/incomplete q')
    if not can_read: q[:,:,READ]=-np.inf
    q[:,-1,WAIT]=-np.inf
    prefix_actions=q.argmax(-1); ends=(prefix_actions!=WAIT).argmax(1); idx=np.arange(len(ends))
    actions=prefix_actions[idx,ends]; rewards=stop_values(s)[idx,ends,actions]
    hit=(rewards>0).astype(int); elapsed=(s['dt'].cumsum(1)-s['dt'][:,:1])[idx,ends]
    values=np.exp(-RHO*elapsed)*rewards+RATE*np.expm1(-RHO*elapsed)/RHO
    def means(v,group): return {str(k):float(v[group==k].mean()) for k in sorted(set(group))}
    by=means(values,s['group']); r1=means(hit,s['group'])
    return dict(utility=float(np.mean(list(by.values()))),r1=float(np.mean(list(r1.values()))),
        per_source=by,per_source_r1=r1,per_recording=means(values,s['source']),
        episode_utility=values.tolist(),episode_hit=hit.tolist(),exit_prefix=ends.tolist(),terminal_action=actions.tolist(),
        reads=int((actions==READ).sum()),waiting_queries=int((ends>0).sum()),read_after_wait=int(((ends>0)&(actions==READ)).sum()),wait_steps=int(ends.sum()))


def immediate_controls(q,s,can_read):
    forced=q.copy(); forced[:,:,WAIT]=-1e30
    stop=np.zeros_like(q); stop[:,:,STOP]=1.
    controls={'immediate_conditional':score(forced,s,can_read),'immediate_free':score(stop,s,can_read)}
    if can_read:
        paid=np.zeros_like(q); paid[:,:,READ]=1.
        controls['immediate_paid']=score(paid,s,True)
    return controls


def advantage_calibration(q,s):
    # Descriptive reliability of conditional net READ-minus-STOP dollars. Both
    # potential terminal outcomes are scored on the paired recording at each prefix.
    immediate=stop_values(s); observed=immediate[:,:,READ]-immediate[:,:,STOP]
    pred=q[:,:,READ]-q[:,:,STOP]; rows=[]
    _,idx,count=np.unique(s['group'],return_inverse=True,return_counts=True)
    w=np.broadcast_to((1./count[idx])[:,None],pred.shape)
    bins=np.digitize(pred,[-.5,-.15,0.,.15,.5])
    for k in range(6):
        mask=bins==k
        if mask.any(): rows.append(dict(bin=k,count=int(mask.sum()),prediction=float(np.average(pred[mask],weights=w[mask])),
                  realized=float(np.average(observed[mask],weights=w[mask]))))
    return dict(breaks=[-.5,-.15,0.,.15,.5],rows=rows)


def brief(result): return {k:v for k,v in result.items() if k not in ('episode_utility','episode_hit','exit_prefix','terminal_action')}


def group_delta(a,b): return {k:a['per_source'][k]-b['per_source'][k] for k in a['per_source']}


def fit_group(data,evidence,avail,seed):
    init(); folder=evidence/'fit'; meta=load(evidence/'prepare/metadata.json'); teacher=load(evidence/'prepare'/(avail+'.json'))
    can_read=avail=='read'; parts=[]
    for name in ('train','dev','retain'):
        s=shard(data,name)
        if s['hash']!=meta['inputs'][name]: raise ValueError('changed '+name)
        parts.append(frontend(s,meta,teacher,name=='train'))
    train,dev,retain=parts; dim=train['zt'].shape[-1]
    for mode,method in ARMS:
        t0=time.monotonic(); c0=time.process_time()
        model=representation(mode,seed,dim); get=features(model,mode,can_read)
        origin=torch.zeros(0,dtype=torch.float64) if model is None else model.initial_edit_vector()
        incumbent={}
        def assess(theta,head):
            with torch.no_grad():
                a,b=(score(predict(get(theta,s),head).numpy(),s,can_read) for s in (dev,retain))
            if not incumbent: incumbent.update(head=head.tolist(),dev=a,retain=b)
            delta=min(group_delta(b,incumbent['retain']).values())
            return a['utility'],delta>=-.05-1e-12,dict(dev=brief(a),retain=brief(b),worst_retain_delta=delta)
        selection=fit_arm(method,origin,get,train,dev,score=assess,config=FitConfig())
        if selection.report['errors']: raise RuntimeError(str(selection.report['errors']))
        start_select=selection.report['selected_index']; row=selection.report['attempts'][start_select]
        with torch.no_grad(): chosen_dev_q=predict(get(selection.theta,dev),selection.head).numpy()
        fast=immediate_controls(chosen_dev_q,dev,can_read); best_fast=max(fast,key=lambda k:fast[k]['utility'])
        write(folder/(f'{avail}-{mode}-{method}-{seed}.json'),dict(availability=avail,seed=seed,mode=mode,method=method,
            theta=selection.theta.tolist(),head=selection.head.tolist(),keep_head=incumbent['head'],keep_theta=origin.tolist(),
            immediate_choice=best_fast,immediate_dev={k:brief(v) for k,v in fast.items()},
            dev_read_advantage_calibration=advantage_calibration(chosen_dev_q,dev) if can_read else None,
            selected_dev=row['diagnostics'][0]['dev'],selected_retain=row['diagnostics'][0]['retain'],report=selection.report,
            wall_seconds=time.monotonic()-t0,cpu_seconds=time.process_time()-c0))


def cases(): return [f'{av}-{m}-{o}-{seed}.json' for av in AVAIL for seed in SEEDS for m,o in ARMS]


def expected_files():
    return (['prepare/metadata.json']+['prepare/'+av+'.json' for av in AVAIL]+['fit/'+p for p in cases()]+
            ['cost/prepare.json']+[f'cost/fit-{av}-{seed}.json' for av in AVAIL for seed in SEEDS])


def check_seal(evidence):
    path=evidence/'selection_seal.json'; seal=load(path)
    if (set(seal['files'])!=set(expected_files()) or seal['sources']!=sources() or
            any(sha(evidence/p)!=h for p,h in seal['files'].items())): raise ValueError('incomplete/changed fit seal')
    for name in seal['files']:
        if name.startswith('cost/'):
            receipt=load(evidence/name)
            if receipt['returncode'] or sha((evidence/name).with_suffix('.log'))!=receipt['log_sha']:
                raise ValueError('unbound failed cold receipt')
    return sha(path)


def confirm_group(data,evidence,avail,seed):
    init(); seal=check_test_receipt(data,evidence); meta=load(evidence/'prepare/metadata.json'); teacher=load(evidence/'prepare'/(avail+'.json'))
    can_read=avail=='read'; test=shard(data,'test'); dim=len(meta['mu'])
    for prior in meta['identities'].values(): disjoint(ids(test),prior)
    frontend(test,meta,teacher)
    for mode,method in ARMS:
        t0=time.monotonic(); c0=time.process_time(); key=f'{avail}-{mode}-{method}-{seed}.json'; path=evidence/'fit'/key
        trained=load(path); model=representation(mode,seed,dim); get=features(model,mode,can_read)
        with torch.no_grad():
            def output(prefix):
                theta=torch.tensor(trained[prefix+'theta'],dtype=torch.float64); head=torch.tensor(trained[prefix+'head'],dtype=torch.float64)
                return predict(get(theta,test),head).numpy()
            q=output(''); keep=score(output('keep_'),test,can_read); chosen=score(q,test,can_read); suppressed=score(q,test,False)
        fast=immediate_controls(q,test,can_read); immediate=fast['immediate_free']; delta=group_delta(chosen,keep)
        write(evidence/'confirm'/key,dict(key=key,availability=avail,seed=seed,mode=mode,method=method,
            chosen=chosen,keep=keep,disable_read=suppressed,immediate_stop=immediate,immediate_choice=trained['immediate_choice'],
            immediate_controls=fast,read_advantage_calibration=advantage_calibration(q,test) if can_read else None,
            q=q.tolist(),query_id=test['query_id'].astype(str).tolist(),source=test['source'].astype(str).tolist(),group=test['group'].astype(str).tolist(),
            task_resources=dict(test_sha=test['hash'],sealed_fit_sha=sha(path),selection_seal_sha=seal),
            worst_delta=min(delta.values()),by_source_delta=delta,gain_vs_immediate_free=chosen['utility']-immediate['utility'],
            pass_capability=chosen['utility']>=.60-1e-12 and chosen['r1']>=.70-1e-12 and min(delta.values())>=-.05-1e-12,
            wall_seconds=time.monotonic()-t0,cpu_seconds=time.process_time()-c0))


def support(a,b):
    delta=group_delta(a,b); n=len(delta); pos=sum(v>1e-12 for v in delta.values()); ties=sum(abs(v)<=1e-12 for v in delta.values())
    p=sum(math.comb(n,i) for i in range(pos,n+1))/2**n
    return dict(group_differences=delta,positive=pos,ties=ties,negative=n-pos-ties,one_sided_sign_p=p)


def summarize(evidence):
    rows=[]
    for seed in SEEDS:
        for m,o in ARMS:
            a,b=(load(evidence/'confirm'/f'{v}-{m}-{o}-{seed}.json') for v in AVAIL)
            ar,br=a['chosen'],b['chosen']; diff=ar['utility']-br['utility']; fast=a['immediate_controls'][a['immediate_choice']]
            instant=ar['utility']-fast['utility']; paid=support(ar,br); timing=support(ar,fast)
            deployable=diff>1e-12 and ar['reads']>0
            temporal=deployable and instant>1e-12 and ar['waiting_queries']>0
            supported=temporal and max(paid['one_sided_sign_p'],timing['one_sided_sign_p'])<=.025+1e-12
            rows.append(dict(seed=seed,mode=m,method=o,utility=ar['utility'],r1=ar['r1'],read=ar['reads'],wait=ar['waiting_queries'],
              read_after_wait=ar['read_after_wait'],paid_gain_vs_matched_noread=diff,paid_gain_by_group=paid['group_differences'],
              gain_vs_immediate_free=a['gain_vs_immediate_free'],dev_locked_immediate=a['immediate_choice'],
              gain_vs_dev_locked_immediate=instant,paid_gain_vs_disable_read=ar['utility']-a['disable_read']['utility'],
              source_support={'versus_refit_noread':paid,'versus_dev_locked_immediate':timing},
              pass_capability=a['pass_capability'],positive_paid_value=deployable,positive_paid_timing=temporal,
              supported_paid_timing=supported,pass_joint=a['pass_capability'] and supported))
    gates=('pass_capability','positive_paid_value','positive_paid_timing','supported_paid_timing','pass_joint')
    families={f'{m}-{o}':{g:all(r[g] for r in rows if (r['mode'],r['method'])==(m,o)) for g in gates} for m,o in ARMS}
    write(evidence/'summary.json',dict(rows=rows,families=families,
        pass_joint_definition='Absolute utility/R1/retention AND observed READs and WAITs AND strictly positive paired macro utility gains versus both matched refit noREAD and DEV-locked immediate AND source sign P<=.025 for both. Families require all three seeds. Marginal arm evidence; no correction over 11 exploratory families.'))


def cold(action,data,evidence,avail=None,seed=None):
    label=action if avail is None else f'{action}-{avail}-{seed}'
    out=evidence/'cost'/(label+'.json'); logfile=out.with_suffix('.log'); out.parent.mkdir(parents=True,exist_ok=True)
    cmd=[sys.executable,'-m','qualification.hcsn_intervention_value.run',action+'-worker',str(data),str(evidence)]
    if avail is not None: cmd+=['--availability',avail,'--seed',str(seed)]
    import resource
    t0=time.time(); stats=resource.getrusage(resource.RUSAGE_CHILDREN)
    with logfile.open('x') as f: ret=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,
        env={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}).returncode
    end=time.time(); final=resource.getrusage(resource.RUSAGE_CHILDREN)
    write(out,dict(start_unix=t0,end_unix=end,wall_seconds=end-t0,
        cpu_seconds=final.ru_utime+final.ru_stime-stats.ru_utime-stats.ru_stime,returncode=ret,log_sha=sha(logfile)))
    if ret: raise RuntimeError('failed cold process '+str(logfile))


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('phase',choices=('fit','confirm','prepare-worker','fit-worker','confirm-worker'))
    p.add_argument('data',type=Path); p.add_argument('evidence',type=Path); p.add_argument('--availability',choices=AVAIL); p.add_argument('--seed',type=int,choices=SEEDS)
    a=p.parse_args(); phase=a.phase; root=a.evidence
    if phase=='prepare-worker': prepare_fit(a.data,root); return
    if phase.endswith('-worker'):
        if a.availability is None or a.seed is None: p.error('availability and seed required')
        (fit_group if phase=='fit-worker' else confirm_group)(a.data,root,a.availability,a.seed); return
    if phase=='fit': cold('prepare',a.data,root)
    else: check_test_receipt(a.data,root)
    for avail in AVAIL:
        for seed in SEEDS: cold(phase,a.data,root,avail,seed)
    if phase=='fit': write(root/'selection_seal.json',dict(files={n:sha(root/n) for n in expected_files()},sources=sources(),arm_count=len(cases())))
    else: summarize(root)


if __name__=='__main__': main()
