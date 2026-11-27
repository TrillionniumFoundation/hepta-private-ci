"""Time local inverse methods with identical post-write tolerances and frozen keys."""
import argparse,json,math,os,platform,random,sys,time
from pathlib import Path
import numpy as np
import torch
from batch_edit import zero_drift_preactivations,write_rows


def case(count,ref):
    rng=torch.Generator().manual_seed(20261127129+count)
    dtype=torch.float64
    k=torch.randn(count,64,generator=rng,dtype=dtype);w=torch.randn(count,64,generator=rng,dtype=dtype)/8
    variances=.5+torch.rand(64,generator=rng,dtype=dtype)*1.5
    precision_keys=k/variances;dirs=precision_keys/(precision_keys*k).sum(1,keepdim=True)
    bias=torch.zeros(count,dtype=dtype);before=(w*k).sum(1)+bias
    drives=-1.4+1.85*torch.rand(count,generator=rng,dtype=dtype)
    v=ref.B0*math.exp(.17);p=ref.p.P0;intercept=ref.bc*ref.p.C;slope=ref.bp;fraction=.28;sig=.23;horizon=.25;n=2
    def forward(a):
        bound=intercept+slope*p*(1+fraction*torch.tanh(a));dist=torch.log(v/bound).clamp_min(0)
        risk=torch.erfc(dist/(math.sqrt(2*horizon)*sig));return risk*(2-risk)
    target=forward(drives);tol=1e-11
    def solve(method):
        if method=='closed':return zero_drift_preactivations(target,v,p,intercept,slope,fraction,sig,horizon,n),1
        lower=torch.full_like(target,-8);upper=torch.full_like(target,8);x=torch.zeros_like(target)
        for iteration in range(1,90):
            if method=='autodiff_newton':
                x=x.detach().requires_grad_(True);q=forward(x);d,=torch.autograd.grad(q.sum(),x);q=q.detach();x=x.detach();d=d.detach()
            else:q=forward(x)
            errors=q-target
            if float(errors.abs().max())<=tol:return x,iteration
            upper=torch.where(errors>0,x,upper);lower=torch.where(errors<0,x,lower);midpoint=(lower+upper)*.5
            if method=='autodiff_newton':
                proposal=x-errors/torch.where(d.abs()>1e-14,d,torch.ones_like(d))
                valid=(d.abs()>1e-14)&(proposal>lower)&(proposal<upper)&torch.isfinite(proposal)
                update=torch.where(valid,proposal,midpoint)
            else:update=midpoint
            x=torch.where(errors.abs()<=tol,x,update)
        raise RuntimeError('solver missed target tolerance')
    def run(method):
        drive,it=solve(method);new=write_rows(w,dirs,before,drive);error=float((forward((new*k).sum(1)+bias)-target).abs().max())
        if error>1.01*tol:raise ValueError(('inaccurate write',method,error))
        return new,it,error
    methods=['closed','bisection','autodiff_newton'];results={m:{'elapsed_ms':[],'iterations':[],'max_probability_error':0.} for m in methods}
    for m in methods:
        for _ in range(3):run(m)
    ordering=random.Random(20261127129+count);cost_check={}
    for _ in range(31):
        order=methods.copy();ordering.shuffle(order)
        for m in order:
            start=time.perf_counter_ns();new,it,error=run(m);elapsed=(time.perf_counter_ns()-start)/1e6
            results[m]['elapsed_ms'].append(elapsed);results[m]['iterations'].append(it);results[m]['max_probability_error']=max(error,results[m]['max_probability_error'])
            cost_check[m]=((new-w).square()*variances).sum(1)
    for m in methods:
        cost_error=float((cost_check[m]-cost_check['closed']).abs().max());assert cost_error<1e-7
        results[m]['max_cost_diff_from_closed']=cost_error;results[m]['p10_median_p90_ms']=np.quantile(results[m]['elapsed_ms'],[.1,.5,.9]).tolist()
    for m in methods:results[m]['median_time_over_closed']=results[m]['p10_median_p90_ms'][1]/results['closed']['p10_median_p90_ms'][1]
    return {'rows':count,'dimensions':64,'target_range':[float(target.min()),float(target.max())],'methods':results}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('out',type=Path);ap.add_argument('--reference-dir',type=Path,default=Path(__file__).resolve().parent.parent);a=ap.parse_args()
    sys.path.insert(0,str(a.reference_dir));from parent_cell import Published,Law
    torch.set_num_threads(1);torch.set_num_interop_threads(1);ref=Published(Law(payout=.08-.5*.23**2))
    cpu='unknown'
    try:cpu=next(l.split(':',1)[1].strip() for l in Path('/proc/cpuinfo').read_text().splitlines() if l.startswith('model name'))
    except (OSError,StopIteration):pass
    r={'scope':'independent local row writes, shared keys and covariance setup','threads':1,'torch':str(torch.__version__),'cpu':cpu,'machine':platform.machine(),'affinity_count':len(os.sched_getaffinity(0)),'rounds':31,'warmups':3,'tolerance':1e-11,'cases':[case(n,ref) for n in [1,1024]]}
    a.out.write_text(json.dumps(r,sort_keys=True,indent=2)+'\n')
    for c in r['cases']:print(c['rows'],[(m,d['p10_median_p90_ms'],d['median_time_over_closed'],max(d['iterations'])) for m,d in c['methods'].items()])


if __name__=='__main__':main()
