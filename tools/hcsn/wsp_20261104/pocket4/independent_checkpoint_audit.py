#!/usr/bin/env python3
"""Read-only, CPU-only audit of actual Laya checkpoints and known-row readouts.

Historical labels have already been viewed. This is a numerical audit, never a
blind generalization experiment or authorization to publish/trade/deploy weights.
The only outputs are new files below an explicitly absent output directory.
"""
from __future__ import annotations
import argparse, hashlib, json, math, os, pathlib, resource, struct, time
os.environ.update(CUDA_VISIBLE_DEVICES='', HIP_VISIBLE_DEVICES='', ROCR_VISIBLE_DEVICES='', OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2')


def sha(path):
    h=hashlib.sha256()
    with pathlib.Path(path).open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()


def stats_checkpoint(path, expected=None):
    import numpy as np
    path=pathlib.Path(path);start=time.perf_counter();cpu=time.process_time()
    before=path.stat();identity=sha(path)
    if expected is not None and identity!=expected:raise ValueError('HASH_MISMATCH:'+str(path))
    with path.open('rb') as f:
        n=struct.unpack('<Q',f.read(8))[0]
        if n>16*1024*1024:raise ValueError('HEADER_TOO_LARGE')
        header=json.loads(f.read(n))
    total=0;items=[];by_dtype={}
    for name,s in header.items():
        if name=='__metadata__':continue
        dtype={'F16':'<f2','F32':'<f4','F64':'<f8'}.get(s['dtype'])
        if dtype is None:raise ValueError('UNSUPPORTED_DTYPE')
        count=math.prod(s['shape']);lo,hi=s['data_offsets']
        if hi-lo!=count*np.dtype(dtype).itemsize:raise ValueError('SHAPE_SIZE')
        if hi+8+n>before.st_size:raise ValueError('OUT_OF_BOUNDS')
        x=np.memmap(path,mode='r',dtype=dtype,offset=8+n+lo,shape=(count,))
        finite=0;zero=0;squared=0.;minimum=math.inf;maximum=-math.inf
        for pos in range(0,count,1<<20):
            a=np.asarray(x[pos:pos+(1<<20)],dtype=np.float64)
            finite+=int(np.isfinite(a).sum());zero+=int(np.count_nonzero(a==0))
            squared+=float(a@a);minimum=min(minimum,float(a.min()));maximum=max(maximum,float(a.max()))
        del x
        total+=count;by_dtype[s['dtype']]=by_dtype.get(s['dtype'],0)+count
        items.append(dict(name=name,shape=s['shape'],dtype=s['dtype'],parameters=count,finite=finite,zeros=zero,l2=math.sqrt(squared),minimum=minimum,maximum=maximum))
    after=path.stat()
    if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('SOURCE_CHANGED')
    return dict(path=str(path),sha256=identity,bytes=before.st_size,parameters=total,tensors=len(items),dtype_parameters=by_dtype,all_finite=all(s['finite']==s['parameters'] for s in items),specialized_names=[s['name'] for s in items if any(k in s['name'].lower() for k in ('first_passage','reset','belief','call','put','continuation','ndu'))],tensor_statistics=items,wall_seconds=time.perf_counter()-start,cpu_seconds=time.process_time()-cpu)


def main():
    p=argparse.ArgumentParser();p.add_argument('--study',required=True);p.add_argument('--base',required=True);p.add_argument('--adapter',required=True);p.add_argument('--adapter-sha256',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    out=pathlib.Path(a.output);out.mkdir(parents=True,exist_ok=False)
    if hasattr(os,'sched_setaffinity'):
        allowed=os.sched_getaffinity(0);os.sched_setaffinity(0,set(sorted(allowed)[:2]))
    start=time.perf_counter();cpu=time.process_time()
    import numpy as np, torch
    from safetensors.numpy import load_file
    torch.set_num_threads(2);torch.set_num_interop_threads(1)
    study=pathlib.Path(a.study);snapshot=study/'snapshot';manifest=json.loads((snapshot/'source-manifest.json').read_text())
    for name,record in manifest['files'].items():
        if sha(snapshot/name)!=record['sha256']:raise ValueError('SNAPSHOT_HASH:'+name)
    feature_path=study/'features/original-fp32.safetensors'
    feature_manifest=json.loads((study/'features/manifest.json').read_text())
    if sha(feature_path)!=feature_manifest['features_sha256']:raise ValueError('FEATURE_HASH')
    x=load_file(str(feature_path))['features'].astype(np.float64)
    rows=json.loads((snapshot/'dataset-selected.json').read_text())['rows']
    y=np.asarray([float(r['net_usd'])/100 for r in rows]);heads=load_file(str(snapshot/'value-head.safetensors'))
    theta=np.r_[heads['value.weight'].reshape(-1),heads['value.bias']].astype(np.float64)
    z=np.c_[x,np.ones(len(x))];radius=.1
    if x.shape!=(54,768) or theta.shape!=(769,) or not np.isfinite(z).all() or not np.isfinite(y).all():raise ValueError('FROZEN_SCHEMA')
    if np.linalg.norm(theta)>radius+1e-6:raise ValueError('PARENT_NORM')
    stamps=[r['input_started_at_ms'] for r in rows]
    order=np.argsort(stamps,kind='stable');z=z[order];x=x[order];y=y[order]
    xc=x-x.mean(axis=0);s=np.linalg.svd(xc,compute_uv=False);std_bound=100*radius*s[0]/math.sqrt(len(x))
    certificate={'rows':len(x),'dimension':x.shape[1],'joint_head_l2_cap':radius,'feature_sha256':sha(feature_path),'centered_singular_max':float(s[0]),'target_std_usd':float((100*y).std()),'any_admissible_raw_prediction_std_upper_bound_usd':float(std_bound),'any_admissible_raw_prediction_rmse_lower_bound_usd':float(max(0,(100*y).std()-std_bound)),'formula':'RMSE >= |sd(y)-sd(pred)| >= max(0, sd(y)-100*r*sigma_max(X_centered)/sqrt(n))','interpretation':'FINITE_KNOWN_ROW_CAPACITY_CERTIFICATE_NOT_GENERALIZATION','labels_previously_viewed':True,'clipped_prediction_bound_note':'Clipping to [-15,15] is 1-Lipschitz, so it cannot increase prediction standard deviation; same lower bound applies.'}
    def metrics(w,xx,yy):
        raw=100*(xx@w);target=100*yy;clipped=np.clip(raw,-15,15)
        return {'raw_rmse_usd':float(np.sqrt(np.mean((raw-target)**2))),'raw_mae_usd':float(np.mean(np.abs(raw-target))),'clipped_rmse_usd':float(np.sqrt(np.mean((clipped-target)**2))),'clipped_mae_usd':float(np.mean(np.abs(clipped-target))),'prediction_sd_usd':float(raw.std()),'norm':float(np.linalg.norm(w))}
    def exact(xx,yy):
        eig,u=np.linalg.eigh(xx@xx.T/len(xx));eig=np.maximum(eig,0);rhs=u.T@yy
        def solve(lam):return xx.T@(u@(rhs/(eig+lam)))/len(xx)
        low=1e-12;high=1.
        while np.linalg.norm(solve(high))>radius:high*=2
        for _ in range(90):
            mid=(low+high)/2
            if np.linalg.norm(solve(mid))>radius:low=mid
            else:high=mid
        w=solve(high);g=xx.T@(xx@w-yy)/len(xx)+high*w
        return w,{'lambda':float(high),'kkt_residual_l2':float(np.linalg.norm(g)),'label_dependent_closed_form_fit':True,'gradient_steps':0}
    experiments=[]
    for n in (18,36,54):
        tx,ty=z[:n],y[:n];tests=slice(n,n+18) if n<54 else slice(0,54)
        arms={'noop':(theta.copy(),{'gradient_steps':0,'labels_used':False,'wall_seconds':0.,'cpu_seconds':0.})}
        t=time.perf_counter();c=time.process_time();w,info=exact(tx,ty);info.update(wall_seconds=time.perf_counter()-t,cpu_seconds=time.process_time()-c,labels_used=True);arms['exact_constrained_mse']=(w,info)
        t=time.perf_counter();c=time.process_time();bias=theta.copy();bias[-1]+=float((ty-tx@theta).mean());bn=np.linalg.norm(bias)
        if bn>radius:bias*=radius/bn
        arms['bias_only_then_global_projection']=(bias,dict(wall_seconds=time.perf_counter()-t,cpu_seconds=time.process_time()-c,labels_used=True,gradient_steps=0))
        # Same objective, same training rows, same radius; fixed 64-step budget.
        t=time.perf_counter();c=time.process_time();weight=torch.tensor(theta,dtype=torch.float64,requires_grad=True);xt=torch.tensor(tx);yt=torch.tensor(ty)
        L=float(np.linalg.norm(tx,2)**2/len(tx));eta=1/max(L,1e-12)
        for step in range(64):
            pred=xt@weight;loss=((pred-yt)**2).mean()/2;loss.backward()
            with torch.no_grad():
                weight-=eta*weight.grad;wn=torch.linalg.vector_norm(weight)
                if wn>radius:weight*=radius/wn
                weight.grad.zero_()
        gd=weight.detach().numpy();arms['projected_gradient64_mse']=(gd,dict(wall_seconds=time.perf_counter()-t,cpu_seconds=time.process_time()-c,labels_used=True,gradient_steps=64,step_size=eta))
        for seed in range(5):
            t=time.perf_counter();c=time.process_time();rng=np.random.default_rng(20261104+seed);d=rng.standard_normal(len(theta));d*=np.linalg.norm(w-theta)/np.linalg.norm(d);rw=theta+d;rn=np.linalg.norm(rw)
            if rn>radius:rw*=radius/rn
            arms[f'random_normmatched_seed{seed}']=(rw,dict(wall_seconds=time.perf_counter()-t,cpu_seconds=time.process_time()-c,labels_used=False,gradient_steps=0,seed=20261104+seed,reference_delta_l2=float(np.linalg.norm(w-theta))))
        record={'training_rows':n,'test_rows':len(z[tests]),'scope':'KNOWN_LABEL_RETROSPECTIVE_TEMPORAL_REPLAY' if n<54 else 'ALL_KNOWN_ROWS_CAPACITY_CERTIFICATE','selection_used_test_labels':False,'all_labels_previously_viewed':True,'arms':{}}
        for name,(wt,info) in arms.items():
            record['arms'][name]={'construction':info,'training':metrics(wt,tx,ty),'evaluation':metrics(wt,z[tests],y[tests]),'delta_l2':float(np.linalg.norm(wt-theta))}
        experiments.append(record)
    checkpoints=[stats_checkpoint(pathlib.Path(a.base)/'model.safetensors','9d628fd971b700382ac6f65920a86f149777b2e748e0c955fb3b19695aa8f204'),stats_checkpoint(a.adapter,a.adapter_sha256),stats_checkpoint(snapshot/'value-head.safetensors',manifest['files']['value-head.safetensors']['sha256'])]
    report={'schema':'hepta.wsp.independent-pocket4-audit.v1','utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'research_only':True,'actual_checkpoint_audit':True,'blind_generalization_claim':False,'end_to_end_task_value_claim':False,'original_files_changed':False,'prospective_protocol_changed':False,'trade_authority':False,'broker_orders_sent':0,'full_encoder_forward_executed':False,'cuda_initialized':torch.cuda.is_initialized(),'capacity_certificate':certificate,'experiments':experiments,'checkpoints':checkpoints,'compute':{'wall_seconds':time.perf_counter()-start,'cpu_seconds':time.process_time()-cpu,'max_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,'cpu_threads':2,'shared_feature_extraction':'REUSED_PINNED_EXISTING_CACHE; NOT_INCLUDED_IN_INCREMENTAL_TIMES','llm_reasoning_cost_measured':False,'energy_measured':False},'software':{'numpy':np.__version__,'torch':torch.__version__},'source_sha256':sha(__file__)}
    output=out/'report.json';output.write_text(json.dumps(report,sort_keys=True,indent=2,allow_nan=False)+'\n');print(json.dumps({'report':str(output),'sha256':sha(output),'certificate':certificate,'compute':report['compute'],'checkpoint_finite':[p['all_finite'] for p in checkpoints]}))

if __name__=='__main__':main()
