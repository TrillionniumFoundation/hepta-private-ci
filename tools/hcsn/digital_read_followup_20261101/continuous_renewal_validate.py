"""Independent numerical/Monte Carlo checks for the continuous reference.

The PDE reference uses a central-difference generator, not image-law code.
Statistical checks use predeclared six-standard-error acceptance bands plus
measured mesh bias. They qualify a bounded numerical reference, not task gains.
"""
import argparse
from dataclasses import asdict, replace
import csv,hashlib,json,math,time
from pathlib import Path
import numpy as np
from scipy import sparse
from scipy.sparse.linalg import expm_multiply
from scipy.special import ndtr
from continuous_renewal import (Law,State,exit_cdf,exit_density,killed_cdf,
    advance,checkpoint,restore,BASELINE_COMMIT,VERSION)


def generator(law,n,renewal=True,count=False):
    b=law.boundary;dx=2*b/n;xs=np.linspace(-b,b,n+1)[1:-1]
    m=n-1;Q=np.zeros((m+2,m+2))
    r=law.diffusion**2/(2*dx**2)+law.drift/(2*dx)
    l=law.diffusion**2/(2*dx**2)-law.drift/(2*dx)
    if min(r,l)<0:raise ValueError("mesh violates generator positivity")
    event=np.zeros(m+2)
    for j in range(m):
        Q[j,j]=-r-l
        Q[j,j+1 if j<m-1 else m+1]+=r
        Q[j,j-1 if j>0 else m]+=l
        if j==0:event[j]+=l
        if j==m-1:event[j]+=r
    if renewal:
        for k,center in enumerate((law.reset_minus,law.reset_plus)):
            w=np.zeros(m)
            if law.reset_sd==0:
                z=(center-xs[0])/dx;i=int(math.floor(z));f=z-i
                if not 0<=i<m-1:raise ValueError("reset outside interior reference mesh")
                w[i]=1-f;w[i+1]=f
            else:
                edges=np.r_[-b,(xs[:-1]+xs[1:])/2,b]
                vals=ndtr((edges-center)/law.reset_sd)
                w=np.diff(vals)/(vals[-1]-vals[0])
            Q[m+k,:m]=law.recovery_rate*w
            Q[m+k,m+k]=-law.recovery_rate
    A=sparse.csr_matrix(Q.T)
    if count:
        A=sparse.bmat([[A,None],[sparse.csr_matrix(event[None,:]),sparse.csr_matrix((1,1))]],format="csr")
    return A,xs


def pde(law,t,n=200,renewal=True,count=False,x=0):
    A,xs=generator(law,n,renewal,count)
    p=np.zeros(A.shape[0]);z=(x-xs[0])/(xs[1]-xs[0]);i=int(math.floor(z));f=z-i
    if i<0 or i+1>=len(xs):raise ValueError("reference start near boundary unsupported")
    p[i]=1-f;p[i+1]=f
    out=expm_multiply(A*t,p)
    m=len(xs)
    return dict(lower=float(out[m]),upper=float(out[m+1]),active=float(out[:m].sum()),
                mean_voltage=float(out[:m]@xs+law.boundary*(out[m+1]-out[m])),
                mass=float(out[:m+2].sum()),event_count=float(out[-1]) if count else None)


def samples(law,t,n,seed,split=False):
    rng=np.random.default_rng(seed);rows=[];first=[]
    for _ in range(n):
        s=State();events=[]
        if split:
            s,a=advance(s,t*.37,law,rng)
            s,c=advance(s,t*.63,law,rng)
            events=a+[dict(e,time=e['time']+t*.37) for e in c]
        else:s,events=advance(s,t,law,rng)
        rows.append([s.mode==-1,s.mode==1,s.mode==0,s.voltage,len(events),len(events)>=2])
        first.append(events[0]['time'] if events else None)
    a=np.array(rows,dtype=float)
    return dict(mean=a.mean(0).tolist(),se=(a.std(0,ddof=1)/math.sqrt(n)).tolist(),
                multi_event_paths=int(a[:,5].sum()),first_hit_times=first,raw=a)


def run(nmc=4000,raw_path=None):
    started=time.perf_counter();cpu_started=time.process_time();checks=[];details={}
    def check(name,predicate,**data):
        checks.append(dict(name=name,passed=bool(predicate),**data))
    # Deterministic PDE/image comparisons cover drift, times and off-center x.
    cases=[(Law(),0.,.05),(Law(),0.,.5),(Law(),0.,2.),
           (Law(drift=.8),-.24,1.2),
           (Law(boundary=1.2,diffusion=.35,drift=-1.1),.36,2.),
           (Law(boundary=1.,diffusion=.575,drift=.1),.2,.75)]
    errors=[]
    for law,x,t in cases:
        probs=exit_cdf(x,t,law);surv=killed_cdf(x,law.boundary,t,law)
        ref=pde(law,t,n=300,renewal=False,x=x)
        ref2=pde(law,t,n=150,renewal=False,x=x)
        err=max(abs(probs[0]-ref['lower']),abs(probs[1]-ref['upper']))
        bias=max(abs(ref['lower']-ref2['lower']),abs(ref['upper']-ref2['upper']))
        check('killed_mass',abs(probs.sum()+surv-1)<3e-10,error=float(abs(probs.sum()+surv-1)))
        check('independent_killed_PDE',err<max(.001,2*bias),error=err,mesh_difference=bias,law=asdict(law),x=x,t=t)
        eps=min(1e-5,t/100)
        diff=(exit_cdf(x,t+eps,law)-exit_cdf(x,t-eps,law))/(2*eps) if t+eps<=2 else (exit_cdf(x,t,law)-exit_cdf(x,t-eps,law))/eps
        flux=exit_density(x,t,law)
        check('flux_CDF_derivative',np.max(abs(diff-flux))<2e-5,error=float(np.max(abs(diff-flux))))
        check('image_truncation_stability',np.max(abs(exit_cdf(x,t,law,8)-exit_cdf(x,t,law,16)))<1e-12)
        errors.append(err)
    sweep_errors=[];symmetry_errors=[]
    for b in (.8,1.2):
        for sig in (.35,.8):
            for mu in (-1.1,0,1.1):
                law=Law(boundary=b,diffusion=sig,drift=mu)
                reflected=replace(law,drift=-mu)
                for rel in (-.99,-.6,0,.6,.99):
                    for t in (1e-5,.01,.25,1,2):
                        x=b*rel;probs=exit_cdf(x,t,law)
                        sweep_errors.append(abs(probs.sum()+killed_cdf(x,b,t,law)-1))
                        symmetry_errors.append(float(np.max(abs(probs-exit_cdf(-x,t,reflected)[::-1]))))
    check('envelope_probability_mass',max(sweep_errors)<3e-10,contexts=len(sweep_errors),maximum_error=max(sweep_errors))
    check('reflection_symmetry',max(symmetry_errors)<1e-13,maximum_error=max(symmetry_errors))
    law=Law();whole=samples(law,2.,nmc,0xA391)
    split=samples(law,2.,nmc,0xC015,split=True)
    ref=pde(law,2.,n=240,renewal=True,count=True)
    coarse=pde(law,2.,n=120,renewal=True,count=True)
    expected=np.array([ref['lower'],ref['upper'],ref['active'],ref['mean_voltage'],ref['event_count']])
    expected2=np.array([coarse['lower'],coarse['upper'],coarse['active'],coarse['mean_voltage'],coarse['event_count']])
    bias=np.abs(expected-expected2)
    for i,name in enumerate(('lower_refractory','upper_refractory','active','voltage_mean','event_count')):
        d=abs(whole['mean'][i]-expected[i]);tol=6*whole['se'][i]+2*bias[i]+.002
        check('renewal_PDE_'+name,d<tol,mc=whole['mean'][i],reference=float(expected[i]),error=float(d),tolerance=float(tol))
        dsplit=abs(whole['mean'][i]-split['mean'][i]);stol=6*math.hypot(whole['se'][i],split['se'][i])+.002
        check('distribution_semigroup_'+name,dsplit<stol,error=dsplit,tolerance=stol)
    check('multiple_continuous_resets',whole['multi_event_paths']>100,
          paths=whole['multi_event_paths'],samples=nmc)
    # A mean count above one cannot be represented by the old <=1-event kernel.
    check('more_than_one_expected_event',whole['mean'][4]-6*whole['se'][4]>1,
          mean=whole['mean'][4],lower_six_se=whole['mean'][4]-6*whole['se'][4])
    check('independent_generator_mass',abs(ref['mass']-1)<1e-9,mass=ref['mass'])
    # Recovery starts at the hit, and checkpointing keeps exact residual time/RNG.
    rng=np.random.default_rng(123);state=State()
    state,events=advance(state,1.8,law,rng)
    payload=checkpoint(state,rng,law);s2,r2,l2=restore(json.loads(json.dumps(payload)))
    next1,e1=advance(state,.7,law,rng);next2,e2=advance(s2,.7,l2,r2)
    check('checkpoint_exact_replay',next1==next2 and e1==e2 and rng.bit_generator.state==r2.bit_generator.state)
    refractory=State(-law.boundary,-1,.2)
    after,ev=advance(refractory,.1,law,np.random.default_rng(9))
    check('refractory_true_residual',after.mode==-1 and abs(after.refractory_remaining-.1)<1e-15 and not ev)
    after,ev=advance(refractory,.25,law,np.random.default_rng(9))
    check('release_consumes_remaining_interval',after.mode==0 and abs(after.voltage)>0 and not ev)
    r=np.random.default_rng(1);before=deepcopy_state(r)
    zero,ze=advance(State(),0,law,r)
    check('zero_duration_identity',zero==State() and not ze and before==deepcopy_state(r))
    rejected=False
    try:
        r=np.random.default_rng(123)
        old=deepcopy_state(r)
        advance(State(),2,law,r,max_events=1)
    except OverflowError:rejected=old==deepcopy_state(r)
    check('event_guard_rejects_transactionally',rejected)
    # Nonzero reset variance is a declared truncated Gaussian, not finite-bin folding.
    lsd=replace(law,reset_sd=.096,reset_minus=-.2,reset_plus=.2)
    mc_sd=samples(lsd,2.,max(1000,nmc//2),0xBE23)
    ref_sd=pde(lsd,2,n=240,count=True)
    check('truncated_reset_PDE_count',abs(mc_sd['mean'][4]-ref_sd['event_count'])<6*mc_sd['se'][4]+.005,
          mc=mc_sd['mean'][4],reference=ref_sd['event_count'])
    raw_evidence=None
    if raw_path is not None:
        with raw_path.open('w',newline='') as stream:
            writer=csv.writer(stream)
            writer.writerow(['condition','sample','lower_refractory','upper_refractory','active','voltage','event_count','at_least_two_events','first_hit_time'])
            for condition,mc in [('whole',whole),('split',split),('truncated_reset',mc_sd)]:
                for i,row in enumerate(mc['raw']):
                    writer.writerow([condition,i,*row.tolist(),mc['first_hit_times'][i]])
        raw_evidence=dict(file=raw_path.name,rows=nmc*2+max(1000,nmc//2),sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest())
    details=dict(primary_law=asdict(law),reference=ref,coarse_reference=coarse,
      whole={k:v for k,v in whole.items() if k not in ('raw','first_hit_times')},
      split={k:v for k,v in split.items() if k not in ('raw','first_hit_times')},
      resolved_first_hits=whole['first_hit_times'][:30],maximum_killed_PDE_error=max(errors))
    return dict(schema='continuous-renewal-validation-v1',baseline_commit=BASELINE_COMMIT,
      implementation=VERSION,passed=all(c['passed'] for c in checks),checks=checks,details=details,raw_sample_evidence=raw_evidence,
      wall_seconds=time.perf_counter()-started,process_cpu_seconds=time.process_time()-cpu_started,mc_samples=nmc,
      scope='bounded numerical reference; no task, gradient, Rust deployment or production qualification')


def deepcopy_state(r):return json.dumps(r.bit_generator.state,sort_keys=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--samples',type=int,default=4000)
    p.add_argument('--out',type=Path,default=Path(__file__).with_name('continuous_renewal_evidence.json'))
    args=p.parse_args();res=run(args.samples,args.out.with_name('continuous_renewal_samples.csv'))
    res['source_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
        (Path(__file__),Path(__file__).with_name('continuous_renewal.py'))}
    args.out.write_text(json.dumps(res,indent=2,sort_keys=True)+'\n')
    print(json.dumps(dict(passed=res['passed'],checks=len(res['checks']),failed=[c for c in res['checks'] if not c['passed']],wall_seconds=res['wall_seconds'],details=res['details']),indent=2))
    raise SystemExit(0 if res['passed'] else 1)
