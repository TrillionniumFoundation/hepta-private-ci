"""Deterministic reference, regularity, exact bridge Monte Carlo and edit checks."""
import argparse,json,math,sys
from pathlib import Path
import numpy as np
import torch
from microdomain import IndependentFirstHit,invert_local_probability,minimum_cost_write


def check_regular(reference):
    sigma=reference.p.sigma;mu=reference.mu;rho=.30;T=.25
    xs=torch.tensor([-.3,0.,1e-9,.001,.03,.075,.16,.27,.48,1.,2.],dtype=torch.float64)
    baseline=IndependentFirstHit(1,mu,sigma,T,rho)(xs)
    stopped=torch.where(xs>0,reference.passage(xs.clamp_min(0),T),1.)
    err=[float((baseline.release-stopped).abs().max()),float((baseline.next_margin-reference.move_mean(xs,T,rho)).abs().max())]
    assert max(err)<3e-14
    differences={};boundary={};checks={}
    for n in (1,2,3,4):
        f=IndependentFirstHit(n,mu,sigma,T,rho)
        grid=torch.tensor([.011,.086,.27,.57],dtype=torch.float64,requires_grad=True)
        val=f(grid);eps=1e-6
        residual=[]
        for i in (0,1):
            grad,=torch.autograd.grad(val[i].sum(),grid,retain_graph=True)
            fd=(f(grid.detach()+eps)[i]-f(grid.detach()-eps)[i])/(2*eps)
            residual.append(float((fd-grad).abs().max()))
        assert max(residual)<1e-7;differences[n]=residual
        slopes={}
        for x in [-.0001,-1e-6,0.,1e-6,.0001]:
            t=torch.tensor(x,dtype=torch.float64,requires_grad=True);v=f(t)
            a,=torch.autograd.grad(v.release,t,retain_graph=True);b,=torch.autograd.grad(v.next_margin,t)
            slopes[str(x)]=[float(a),float(b)]
        boundary[n]=slopes
        if n>1:assert max(abs(y) for y in slopes['1e-06'])<.0002
        else:assert slopes['1e-06'][0]<-7 and abs(slopes['1e-06'][1])>1.
        grid=torch.linspace(-.2,2.,513,dtype=torch.float64);s=f(grid)
        assert torch.isfinite(s.release).all() and (s.release>=0).all() and (s.release<=1).all() and (s.next_margin>=0).all()
        checks[str(n)]={'max_violation_of_decreasing_hit':float(torch.diff(s.release).max()),'min_reset_mean':float(s.next_margin.min())}
        assert checks[str(n)]['max_violation_of_decreasing_hit']<=1e-13
    return {'source_n1_release_and_reset_max_abs':err,'finite_difference_gradient_max_abs':differences,'one_sided_release_reset_gradients':boundary,'grid_checks':checks}


def mc():
    # Exact conditional hitting for drifted Brownian endpoints using independent bridges.
    rng=np.random.default_rng(2026112713);draws=140000;table=[]
    for mu in [-.035,.03355]:
        for n in [1,2,4]:
            for x in [.075,.22]:
                sig=.23;t=.25;rho=.3
                end=x+mu*t+sig*math.sqrt(t)*rng.normal(size=(draws,n))
                bridge=np.where(end>0,-np.expm1(-2*x*end.clip(min=0)/(sig**2*t)),0.)
                survivors=(rng.random((draws,n))<bridge).all(axis=1)
                observed=np.column_stack((~survivors,np.where(survivors,end.mean(axis=1),rho)))
                mean=observed.mean(axis=0);se=observed.std(axis=0,ddof=1)/math.sqrt(draws)
                v=IndependentFirstHit(n,mu,sig,t,rho)(torch.tensor(x,dtype=torch.float64));truth=np.array([v.release.item(),v.next_margin.item()])
                z=(mean-truth)/se;assert max(abs(z))<5.5
                table.append(dict(mu=mu,n=n,x=x,closed_form=truth.tolist(),simulation=mean.tolist(),standard_errors=se.tolist(),standardized_errors=z.tolist()))
    return {'draws_per_cell':draws,'seed':2026112713,'rows':table,'max_abs_standardized_error':max(abs(a) for r in table for a in r['standardized_errors'])}


def edits(reference):
    law=IndependentFirstHit(2,0.,.23,.25,.30);t=lambda x:torch.tensor(x,dtype=torch.float64)
    C=t([[2.,.3,.15],[.3,1.1,.2],[.15,.2,1.7]])
    w=t([.13,-.28,.21]);z=t([.8,-.2,.3]);protected=t([.1,.9,-.2]);unseen=t([-.3,.17,.75]);offset=.17
    p0=reference.p.P0;a=reference.bc*reference.p.C;b=reference.bp;rho=.28;V=reference.B0*math.exp(.17)
    def probability(pre):
        B=a+b*p0*(1+rho*math.tanh(pre));return law(t(math.log(V/B))).release.item()
    before=float(w@z)+offset;q=probability(.63)
    inv=invert_local_probability(q,V,p0,a,b,rho,law,before)
    keys=torch.stack([z,protected]);rhs=t([inv.preactivation-before,0.]);w1=minimum_cost_write(w,keys,rhs,C)
    after=float(w1@z)+offset;target_err=abs(probability(after)-q)
    assert abs(after-.63)<1e-13 and target_err<1e-13 and abs(float((w1-w)@protected))<1e-14
    d=w1-w;null=torch.linalg.cross(z,protected);null_cost=[]
    for alpha in [-2.,-.3,.3,2.]:
        other=d+alpha*null;assert torch.allclose(keys@other,rhs);null_cost.append(float(other@C@other))
    assert min(null_cost)>float(d@C@d)
    same=minimum_cost_write(w,torch.stack([z,z]),t([rhs[0],rhs[0]]),C)
    assert abs(float((same-w)@z)-float(rhs[0]))<1e-13
    failures={}
    for name,fn in {
        'conflicting_duplicate':lambda: minimum_cost_write(w,torch.stack([z,z]),t([rhs[0],0.]),C),
        'unreachable_positive_probability':lambda: invert_local_probability(.999999999,10*V,p0,a,b,rho,law),
        'zero_probability':lambda: invert_local_probability(0.,V,p0,a,b,rho,law),
        'out_of_range_probability':lambda: invert_local_probability(1.1,V,p0,a,b,rho,law),
        'nonzero_drift':lambda: invert_local_probability(q,V,p0,a,b,rho,IndependentFirstHit(2,.02,.23,.25,.3)),
        'indefinite_cost':lambda: minimum_cost_write(w,keys,rhs,torch.diag(t([1.,-1.,2.])))}.items():
        try:fn()
        except ValueError as e:failures[name]=str(e)
        else:raise AssertionError(name)
    saturated=invert_local_probability(1.,.9*reference.B0,p0,a,b,rho,law,1.2)
    assert saturated.preactivation==1.2 and saturated.margin<0
    wall=invert_local_probability(1.,reference.B0,p0,a,b,rho,law,-.4);assert abs(wall.margin)<1e-15
    unseen_change=float(d@unseen);assert abs(unseen_change)>1e-4
    # The inverse is assembled through the affine boundary, tanh and Gaussian special functions, once per key.
    round_trips={}
    for n in [1,2,4,8]:
        candidate=IndependentFirstHit(n,0.,.23,.25,.30);errors=[]
        for pre in np.linspace(-1.7,.5,25):
            boundary=a+b*p0*(1+rho*math.tanh(pre));x=math.log(V/boundary)
            target=candidate(t(x)).release.item();r=invert_local_probability(target,V,p0,a,b,rho,candidate)
            errors.append(abs(r.preactivation-pre))
        round_trips[n]=max(errors);assert max(errors)<3e-9
    return {'target_q':q,'before_q':probability(before),'after_q':probability(after),'target_error':target_err,'target_preactivation':inv.preactivation,'boundary':inv.boundary,'principal':inv.principal,'margin':inv.margin,'protected_logit_change':float(d@protected),'unseen_logit_change':unseen_change,'unseen_before_q':probability(float(w@unseen)+offset),'unseen_after_q':probability(float(w1@unseen)+offset),'minimum_covariance_cost':float(d@C@d),'feasible_null_perturbation_costs':null_cost,'roundtrip_max_preactivation_error':round_trips,'unreachable_and_conflict_checks':failures,'already_stopped_preserved':saturated.preactivation,'from_live_to_wall':wall.preactivation}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--reference-dir',type=Path,default=Path(__file__).resolve().parent.parent);ap.add_argument('output',type=Path);args=ap.parse_args()
    sys.path.insert(0,str(args.reference_dir));from parent_cell import Published,Law
    torch.set_num_threads(1)
    reference=Published();zero_reference=Published(Law(payout=.08-.5*.23**2))
    result={'torch':str(torch.__version__),'precision':'float64','regularity':check_regular(reference),'brownian_bridge_mc':mc(),'exact_key_write':edits(zero_reference)}
    args.output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print('verified native, bridge and edit',result['regularity']['source_n1_release_and_reset_max_abs'],result['brownian_bridge_mc']['max_abs_standardized_error'],result['exact_key_write']['target_error'])


if __name__=='__main__':main()
