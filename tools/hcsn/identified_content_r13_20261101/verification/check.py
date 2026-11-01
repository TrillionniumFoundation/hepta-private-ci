"""Independent R13 full-chain first-gradient and local rank diagnostics."""

import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
import contract as c
import models

P=json.loads((ROOT/'PROTOCOL.json').read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name,data):
    path=ROOT/name
    if path.exists():
        raise ValueError(f'Refusing to overwrite {name}')
    raw=(json.dumps(data,indent=2,allow_nan=False)+'\n').encode()
    path.write_bytes(gzip.compress(raw,mtime=0) if name.endswith('.gz') else raw)


def scaled(a,b):
    return float(np.max(np.abs(np.asarray(a)-b)/np.maximum(1,np.abs(b))))


def raw_from_physical(sigma,liquidity):
    low,high=np.array(c.PROTOCOL['physical_lower']),np.array(c.PROTOCOL['physical_upper'])
    ratio=(np.array([sigma,liquidity])-low)/(high-low)
    return torch.tensor(np.log(ratio/(1-ratio)),dtype=torch.float64)


def mapping(raw):
    terms=c.model_terms(raw,prices=False)
    return torch.cat((terms['Q'].ravel(),terms['prior'],terms['reset'],terms['boundary'][None]))


def sequence(fixture):
    t=np.arange(fixture['length'])
    times=np.where(t%16==0,2.1,np.where(t%4==1,.75,.05)) if 'times' in fixture else np.resize(fixture['times_cycle'],len(t))
    tokens=np.resize(fixture['tokens_cycle'],len(t))
    observed=t%3!=1 if fixture['observed']!='all' else np.ones(len(t),bool)
    return dict(dt=torch.tensor(times[None,:],dtype=torch.float64),tokens=torch.tensor(tokens[None,:]),
                observed=torch.tensor(observed[None,:]),labels=torch.tensor((t%2)[None,:]))


def evaluate_vector(vector,batch,need_gradient):
    model=models.DistributionCell(P['likelihood'])
    with torch.no_grad():
        model.raw.copy_(torch.tensor(vector[:2]))
        model.logits.copy_(torch.tensor(vector[2:].reshape(2,6)))
    prediction=model(batch['dt'],batch['tokens'],batch['observed'])
    losses=models.objective(prediction,batch)
    grads=[]
    if need_gradient:
        for loss in losses:
            components=torch.autograd.grad(loss,(model.raw,model.logits),retain_graph=True)
            grads.append(torch.cat((components[0],components[1].ravel())).detach().numpy())
    return np.array([v.detach().item() for v in losses]),np.array(grads),prediction.detach().numpy()


def main():
    torch.set_num_threads(1)
    sources={name:sha(ROOT.parent/name) for name in ('contract.py','models.py','PROTOCOL.json',
             'propagation/api.py','propagation/finite_volume.py')}
    assert c.N_ACTIVE==56 and c.DIM==116
    assert c.PROTOCOL['physical_indices']==[2,5] and c.PROTOCOL['fixed_maturity']==1.3
    baseline=c.PROTOCOL['baseline_financial_parameters']
    sigma_zero=float(np.sqrt(2*(baseline[0]-baseline[1])))
    points=dict(initial=c.initial_raw(),truth=raw_from_physical(baseline[2],baseline[5]),
        mu_zero=raw_from_physical(sigma_zero,baseline[5]),
        mu_zero_sigma_minus_1e6=raw_from_physical(sigma_zero-1e-6,baseline[5]),
        mu_zero_sigma_plus_1e6=raw_from_physical(sigma_zero+1e-6,baseline[5]))
    maps=[]
    start=time.perf_counter()
    for name,raw in points.items():
        columns=[]
        for i in range(2):
            tangent=torch.eye(2,dtype=torch.float64)[i]
            value,column=torch.autograd.functional.jvp(mapping,raw,tangent)
            columns.append(column.detach().numpy())
        jac=np.stack(columns,axis=1)
        errors=[]
        for h in (1e-4,5e-5):
            finite=[]
            for i in range(2):
                step=torch.eye(2,dtype=torch.float64)[i]*h
                finite.append(((mapping(raw+step)-mapping(raw-step))/(2*h)).detach().numpy())
            fd=np.stack(finite,axis=1)
            errors.append(dict(step=h,error=scaled(jac,fd)))
        jq=jac[:c.DIM*c.DIM]
        singular=np.linalg.svd(jq,compute_uv=False)
        terms=c.model_terms(raw,prices=False)
        row=dict(name=name,raw=raw.tolist(),theta=terms['theta'].tolist(),boundary=float(terms['boundary']),
            singular_values=singular.tolist(),rank=int(np.sum(singular>1e-8*singular[0])),
            jacobian_column_norms=np.linalg.norm(jq,axis=0).tolist(),derivative_errors=errors,
            maturity_derivative=0.,reset_sum=float(terms['reset'].sum()),
            Q_row_sum_error=float(terms['Q'].sum(1).abs().max()),
            passed=bool(len(singular)==2 and singular[1]>1e-8*singular[0] and max(e['error'] for e in errors)<=P['mapping_gate']))
        maps.append(row)
        print('mapping',name,singular,'FD',errors,flush=True)
    losses=[]
    logits=np.log(np.array(P['likelihood'])).ravel()
    batches=[]
    for fixture in P['fixtures']:
        batch=sequence(fixture)
        teacher=models.DistributionCell(P['likelihood'])
        with torch.no_grad():
            teacher.raw.copy_(points['truth'])
            batch['posterior']=teacher(batch['dt'],batch['tokens'],batch['observed']).detach()
        batches.append((fixture['name'],batch))
        for name in ('initial','truth','mu_zero'):
            vector=np.r_[points[name].numpy(),logits]
            values,grad,predicted=evaluate_vector(vector,batch,True)
            finite=[]
            for h in (1e-4,5e-5):
                fd=[]
                for i in range(len(vector)):
                    a,b=vector.copy(),vector.copy()
                    a[i]+=h
                    b[i]-=h
                    va,_,_=evaluate_vector(a,batch,False)
                    vb,_,_=evaluate_vector(b,batch,False)
                    fd.append((va-vb)/(2*h))
                fd=np.stack(fd,axis=1)
                finite.append(dict(step=h,gradient=fd.tolist(),error=scaled(grad,fd)))
            row=dict(fixture=fixture['name'],point=name,sequence_length=fixture['length'],total_time=float(batch['dt'].sum()),
                losses=values.tolist(),gradient=grad.tolist(),finite_differences=finite,
                probability_mass_error=float(np.max(abs(predicted.sum(-1)-1))),
                minimum_state=float(predicted.min()),finite=bool(np.isfinite(predicted).all() and np.isfinite(grad).all()),
                nearest_nonzero_probability_to_log_clamp=float(np.min(abs(predicted[predicted>0]-1e-12))),
                logit_row_gradient_sums=grad[:,2:].reshape(3,2,6).sum(-1).tolist(),
                passed=bool(max(e['error'] for e in finite)<=P['loss_gradient_gate'] and np.isfinite(grad).all()))
            losses.append(row)
            print('loss',fixture['name'],name,[e['error'] for e in finite],flush=True)
    smooth=[]
    for fixture,batch in batches:
        center=np.r_[points['mu_zero'].numpy(),logits]
        _,g0,p0=evaluate_vector(center,batch,True)
        for eps in (1e-4,1e-6,1e-8):
            sides=[]
            for sign in (-1,1):
                raw=raw_from_physical(sigma_zero+sign*eps,baseline[5])
                v=np.r_[raw.numpy(),logits]
                _,g,p=evaluate_vector(v,batch,True)
                sides.append(dict(sign=sign,gradient_error_to_center=scaled(g,g0),
                                  state_error_to_center=float(np.max(abs(p-p0)))))
            smooth.append(dict(fixture=fixture,sigma_epsilon=eps,sides=sides))
        print('smooth',fixture,smooth[-1],flush=True)
    assert all(sha(ROOT.parent/n)==s for n,s in sources.items()),'Source changed during audit'
    payload=dict(source_sha256=sources,protocol_sha256=sha(ROOT/'PROTOCOL.json'),dimension=c.DIM,
        mapping=maps,losses=losses,mu_zero_smoothness=smooth,seconds=time.perf_counter()-start,
        conclusions=dict(mapping_all_pass=all(r['passed'] for r in maps),loss_all_pass=all(r['passed'] for r in losses)),
        limitation='Local generator rank2 is not observed-data global identifiability or proof of finite-data parameter recovery; two additive emission-logit gauges remain.')
    write('RAW.json.gz',payload)
    write('SUMMARY.json',{k:v for k,v in payload.items() if k not in ('mapping','losses','mu_zero_smoothness')})
    print(json.dumps(payload['conclusions']),flush=True)


if __name__=='__main__':
    main()
