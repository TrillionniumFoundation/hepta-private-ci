"""Independent numerical/gradient audit for the batched regenerative kernel."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import resource
import time
import unittest

import numpy as np
from scipy.integrate import quad
from scipy.linalg import expm, solve
from scipy.stats import poisson
import torch

from .distribution_kernel import (Grid, make_flow, initial_probability,
    initial_state, remap_operator, propagate, step, moments, policy_value_vectors,
    finite_generator_values, prepare_operator, collapse_active_mean,
    _poisson_tail_bounds)


RECORDS = {}


def independent_generator(mu, sigma, boundary, reset, tau, grid):
    """Independent scalar NumPy column generator, assembled by physical jumps."""
    n, m = grid.cells, grid.refractory_stages
    h = (boundary-grid.lower)/n
    centers = grid.lower+(np.arange(n)+.5)*h
    D = sigma*sigma/2
    u, d, e = D/(h*h)+max(mu, 0)/h, D/(h*h)+max(-mu, 0)/h, 2*D/(h*h)+max(mu, 0)/h
    j = min(n-2, max(0, int(np.floor((reset-centers[0])/h))))
    w = np.zeros(n)
    w[j+1] = (reset-centers[j])/h
    w[j] = 1-w[j+1]
    Q, events = np.zeros((n+m, n+m)), np.zeros(n+m)
    for i in range(n):
        if i > 0:
            Q[i-1,i] += d
            Q[i,i] -= d
        if i+1 < n:
            Q[i+1,i] += u
            Q[i,i] -= u
        else:
            Q[i,i] -= e
            events[i] = e
            if m:
                Q[n,i] += e
            else:
                Q[:n,i] += e*w
    for j in range(m):
        rate = m/tau
        Q[n+j,n+j] -= rate
        if j+1 < m:
            Q[n+j+1,n+j] += rate
        else:
            Q[:n,n+j] += rate*w
    return Q, events, centers, w


def independent_propagation(params, grid, probability, duration, K=.4):
    Q, event, _, _ = independent_generator(*params, grid)
    s = len(Q)
    A = np.zeros((s+2, s+2))
    A[:s,:s] = Q
    A[s,:s] = event
    A[s+1,:s] = (params[2]-K)*event
    p = np.r_[probability, 0., 0.]
    return expm(A*duration) @ p


def _json(value):
    if isinstance(value, torch.Tensor):
        value = value.detach().cpu().numpy()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {key:_json(item) for key,item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


class KernelTests(unittest.TestCase):
    def test_independent_dense_propagation_events_and_reward(self):
        rows = []
        cases = [((.23,.51,.91,-.17,.41), Grid(8,-2,2), .73),
                 ((-.31,.67,.83,-.21,.37), Grid(13,-3,4), 1.23),
                 ((.8,.7,.8,-.2,.15), Grid(9,-2,2), 6.),
                 ((.19,.71,1.1,-.21,0.), Grid(12,-3,0), 2.1)]
        rng = np.random.default_rng(710101)
        for params, grid, duration in cases:
            flow = make_flow(*params, grid)
            p0 = rng.dirichlet(np.ones(grid.cells+grid.refractory_stages))
            p = torch.tensor(p0, dtype=torch.float64)
            actual = propagate(p, flow, duration)
            reference = independent_propagation(params, grid, p0, duration)
            state_error = float(np.abs(actual['probability'].numpy()-reference[:-2]).sum())
            event_error = abs(float(actual['events'])-reference[-2])
            reward_error = abs(float(actual['events'])*(params[2]-.4)-reference[-1])
            self.assertLessEqual(state_error, actual['probability_l1_error_bound']+2e-12)
            self.assertLessEqual(event_error, actual['event_error_bound']+2e-11)
            self.assertLessEqual(reward_error, abs(params[2]-.4)*actual['event_error_bound']+2e-11)
            self.assertLess(abs(float(actual['probability'].sum())-1), 2e-13)
            self.assertGreaterEqual(float(actual['probability'].min()), 0)
            rows.append(dict(parameters=params, cells=grid.cells, phases=grid.refractory_stages,
                             duration=duration, state_l1_error=state_error, event_error=event_error,
                             reward_error=reward_error, expected_events=float(actual['events']),
                             solver={k:v for k,v in actual.items() if k not in ('probability','events')}))
        self.assertGreater(rows[2]['expected_events'], 2)
        RECORDS['dense_propagation'] = rows

    def test_poisson_majorants(self):
        rows=[]
        for mean in (.01,.2,1.,4.,12.):
            for terms in (math.ceil(mean)+3, math.ceil(mean)+12, math.ceil(mean)+28):
                tail, moment = _poisson_tail_bounds(mean, terms)
                true_tail = float(poisson.sf(terms, mean))
                true_moment = mean*float(poisson.sf(terms-1, mean))
                self.assertGreaterEqual(tail+1e-16, true_tail)
                self.assertGreaterEqual(moment+1e-16, true_moment)
                rows.append(dict(mean=mean, terms=terms, tail_bound=tail, exact_tail=true_tail,
                                 tail_first_moment_bound=moment, exact_tail_first_moment=true_moment))
        RECORDS['poisson_majorants']=rows

    def test_fixed_generator_time_composition(self):
        grid=Grid(12,-3,3)
        flow=make_flow(.29,.6,.97,-.19,.41,grid)
        p0=initial_probability(flow,.13)
        reference=propagate(p0,flow,1.7)
        rows=[]
        for parts in (1,4,16,64):
            p=p0
            events=p.new_zeros(())
            bound=0.
            for _ in range(parts):
                result=propagate(p,flow,1.7/parts)
                p=result['probability']
                events=events+result['events']
                bound+=result['probability_l1_error_bound']
            e=float((p-reference['probability']).abs().sum())
            ce=abs(float(events-reference['events']))
            self.assertLess(e, 3e-9)
            self.assertLess(ce, 3e-9)
            rows.append(dict(partitions=parts, probability_l1_difference=e,
                             event_difference=ce, expected_events=float(events),
                             accumulated_local_state_bound=bound))
        RECORDS['fixed_generator_composition']=rows

    def test_boundary_jump_zero_time_and_phase_identity(self):
        grid=Grid(8,-2,3)
        old_boundary=1.17
        params=(.21,.57,.431,-.19,.47)
        f=make_flow(*params,grid)
        p=torch.tensor(np.random.default_rng(710103).dirichlet(np.ones(11)),dtype=torch.float64)
        remap=remap_operator(old_boundary,f,reward_intercept=-.4)
        actual=step(p,old_boundary,*params,0.,grid,reward_intercept=-.4)
        self.assertGreater(float(actual['events']),0)
        self.assertLess(float((actual['probability'][9:]-p[9:]).abs().max()),1e-15)
        self.assertLess(abs(float(actual['probability'][8]-p[8]-actual['events'])),1e-14)
        self.assertLess(float((remap['transition'].sum(-1)-1).abs().max()),1e-14)
        old_edges=np.linspace(grid.lower,old_boundary,grid.cells+1)
        h=old_edges[1]-old_edges[0]
        active=p.numpy()[:grid.cells]
        def density(x):
            i=min(grid.cells-1,max(0,int(np.searchsorted(old_edges,x,side='right')-1)))
            return active[i]/h
        breakpoints=[x for x in old_edges if params[2]<x<old_boundary]
        count=quad(density,params[2],old_boundary,points=breakpoints,epsabs=1e-13)[0]
        reward=quad(lambda x:(x-.4)*density(x),params[2],old_boundary,
                    points=breakpoints,epsabs=1e-13)[0]
        self.assertLess(abs(count-float(actual['events'])),1e-13)
        self.assertLess(abs(reward-float(actual['reward'])),1e-13)
        unchanged=remap_operator(params[2],f)
        self.assertLess(float((unchanged['transition']-torch.eye(11)).abs().max()),2e-15)
        RECORDS['zero_time_boundary_jump']=dict(events=float(actual['events']), reward=float(actual['reward']),
                                               independent_integral_events=count, independent_integral_reward=reward,
                                               preserved_existing_nonzero_phases=True)

    def test_initial_atom_and_refractory_ineligibility(self):
        flow=make_flow(.2,.5,.9,-.2,.4,Grid(8,-2,2))
        s=initial_state(flow,1.3,reward_intercept=-.4)
        self.assertEqual(float(s['events']),1)
        self.assertAlmostEqual(float(s['reward']),.9)
        values=finite_generator_values(flow,s['probability'],.4,.4)
        self.assertEqual(float(values['G_eligible']),0)
        self.assertEqual(float(values['J_total']),float(values['G_total']))
        self.assertEqual(float(values['J_total']),float(values['J_phase']))
        RECORDS['initial_atom']=dict(events=1,reward=float(s['reward']),phase_continuation=float(values['J_phase']))

    def test_independent_dense_policy_values(self):
        rows=[]
        for params,grid in [((.23,.51,.91,-.17,.41),Grid(8,-2,2)),
                            ((-.33,.61,1.13,-.24,.39),Grid(17,-3,5)),
                            ((.17,.71,.89,-.21,0.),Grid(13,-3,0))]:
            f=make_flow(*params,grid)
            values=policy_value_vectors(f,.43,.4)
            Q,rate,centers,w=independent_generator(*params,grid)
            reference=solve(.43*np.eye(len(Q))-Q.T,(params[2]-.4)*rate)
            value_error=float(np.abs(reference-values['J'].numpy()).max())
            self.assertLess(value_error,2e-13)
            continuation=reference[grid.cells] if grid.refractory_stages else w@reference
            G=centers-.4+continuation
            g_error=float(np.abs(G-values['active_G'].numpy()).max())
            self.assertLess(g_error,2e-13)
            rows.append(dict(parameters=params,cells=grid.cells,phases=grid.refractory_stages,
                             value_max_error=value_error,intervention_max_error=g_error,
                             minimum_renewal_denominator=float(values['renewal_denominator'])))
        RECORDS['dense_value_reference']=rows

    def test_all_physical_gradients_and_solver_branches(self):
        grid=Grid(9,-2,3,tolerance=1e-12)
        names=('mu','sigma','boundary','reset','tau','rho','K')
        values=(.237,.513,.8431,-.173,.417,.437,.413)
        p=torch.tensor(np.random.default_rng(710105).dirichlet(np.ones(12)),dtype=torch.float64)
        def objective(xs):
            fwd=step(p,1.137,*xs[:5],.73,grid,reward_intercept=-xs[6])
            v=finite_generator_values(fwd['flow'],fwd['probability'],xs[5],xs[6])
            obj=(.3*fwd['mean']+.2*fwd['variance']+1.1*fwd['events']+.4*fwd['reward']
                 +.15*v['J_total']+.07*v['G_total'])
            branch={k:fwd['solver'][k] for k in ('terms','chunks','uniformization_rate','max_chunk_mean')}
            return obj,branch
        args=[torch.tensor(x,dtype=torch.float64,requires_grad=True) for x in values]
        loss,branch=objective(args)
        grads=torch.autograd.grad(loss,args)
        rows=[]
        for j,name in enumerate(names):
            epsilon=1e-5
            plus,minus=list(values),list(values)
            plus[j]+=epsilon
            minus[j]-=epsilon
            a,ba=objective(plus)
            b,bb=objective(minus)
            fd=float((a-b)/(2*epsilon))
            gradient=float(grads[j])
            error=abs(fd-gradient)
            scaled=error/max(1e-5,abs(fd))
            self.assertLess(scaled,2e-6)
            self.assertGreater(abs(gradient),1e-8)
            self.assertEqual((ba['terms'],ba['chunks']),(bb['terms'],bb['chunks']))
            rows.append(dict(parameter=name,autograd=gradient,finite_difference=fd,
                             absolute_error=error,scaled_error=scaled,plus_branch=ba,minus_branch=bb))
        RECORDS['physical_gradients']=dict(base_branch=branch,records=rows,
            scope='Local first derivatives away from overlap/interpolation/drift knots; adaptive terms/chunks unchanged in each finite-difference pair')

    def test_prepared_and_step_sequence_equivalence(self):
        dtype=torch.float64
        B,T,C=2,6,3
        rng=torch.Generator().manual_seed(710107)
        mu=(.1+.3*torch.rand(B,T,C,generator=rng,dtype=dtype)).requires_grad_()
        boundary=(.6+.8*torch.rand(B,T,C,generator=rng,dtype=dtype)).requires_grad_()
        sigma=torch.tensor([.41,.53,.59],dtype=dtype,requires_grad=True)
        reset=torch.tensor([-.21,-.13,-.17],dtype=dtype,requires_grad=True)
        tau=torch.tensor([.37,.43,.51],dtype=dtype,requires_grad=True)
        dt=.03+.09*torch.rand(B,T,1,generator=rng,dtype=dtype)
        grid=Grid(8,-2,2,tolerance=1e-12)
        old=torch.cat((boundary[:,:1],boundary[:,:-1]),1)
        prep=prepare_operator(mu,sigma,boundary,reset,tau,dt,grid,old_boundary=old,
                              rho=.43,K=.4,reward_intercept=-.4)
        f0=make_flow(mu[:,0],sigma,boundary[:,0],reset,tau,grid)
        p=initial_probability(f0)
        q=p
        e=p.new_zeros(B,C)
        e2=e.clone()
        r=e.clone()
        r2=e.clone()
        j,j2=e,e
        for t in range(T):
            out=step(p,old[:,t],mu[:,t],sigma,boundary[:,t],reset,tau,dt[:,t],grid,reward_intercept=-.4)
            p=out['probability']
            e=e+out['events']; r=r+out['reward']
            v=finite_generator_values(out['flow'],p,.43,.4)
            j=v['J_total']
            e2=e2+(q*prep['event_vector'][:,t]).sum(-1)
            r2=r2+(q*prep['reward_vector'][:,t]).sum(-1)
            q=torch.matmul(q.unsqueeze(-2),prep['transition'][:,t]).squeeze(-2)
            j2=(q*prep['values']['J'][:,t]).sum(-1)
        errors=dict(probability=float((p-q).abs().max().detach()),events=float((e-e2).abs().max().detach()),
                    rewards=float((r-r2).abs().max().detach()),values=float((j-j2).abs().max().detach()))
        for value in errors.values(): self.assertLess(value,2e-10)
        g1=torch.autograd.grad((p.square().sum()+e.sum()+r.sum()+j.sum()),
                               (mu,boundary,sigma,reset,tau),retain_graph=True)
        g2=torch.autograd.grad((q.square().sum()+e2.sum()+r2.sum()+j2.sum()),
                               (mu,boundary,sigma,reset,tau))
        errors['gradient_max_absolute']=max(float((a-b).abs().max()) for a,b in zip(g1,g2))
        self.assertLess(errors['gradient_max_absolute'],1e-8)
        RECORDS['prepared_vs_step']=dict(shape=[B,T,C,10],errors=errors,solver=prep['solver'])

    def test_active_collapse_preserves_mean_mass_and_phases(self):
        flow=make_flow(.2,.5,1.,-.2,.4,Grid(8,-2,2))
        p=torch.tensor(np.random.default_rng(710109).dirichlet(np.ones(10)),dtype=torch.float64)
        collapsed=collapse_active_mean(flow,p)
        self.assertLess(float((collapsed[8:]-p[8:]).abs().max()),1e-15)
        self.assertLess(abs(float(collapsed.sum()-p.sum())),1e-14)
        self.assertLess(abs(float(moments(flow,collapsed)['mean']-moments(flow,p)['mean'])),1e-14)
        self.assertLess(float(moments(flow,collapsed)['variance']),float(moments(flow,p)['variance']))
        RECORDS['active_collapse']=dict(mean_before=float(moments(flow,p)['mean']),
                                      mean_after=float(moments(flow,collapsed)['mean']),
                                      variance_before=float(moments(flow,p)['variance']),
                                      variance_after=float(moments(flow,collapsed)['variance']))

    def test_float32_long_sequence_and_rejections(self):
        grid=Grid(8,-2,2)
        mu=torch.full((3,4),.3,dtype=torch.float32)
        f=make_flow(mu,.5,1.,-.2,.4,grid)
        p=initial_probability(f)
        old=f['boundary']
        maximum_mass_error=0.
        for t in range(64):
            boundary=.8+.13*math.sin(t*.37)
            out=step(p,old,mu,.5,boundary,-.2,.4,.12,grid)
            p,old=out['probability'],out['boundary']
            maximum_mass_error=max(maximum_mass_error,float((p.sum(-1)-1).abs().max()))
            self.assertGreaterEqual(float(p.min()),0)
        self.assertLess(maximum_mass_error,8e-6)
        with self.assertRaises(ValueError): propagate(p*1.1,make_flow(mu,.5,old,-.2,.4,grid),.1)
        with self.assertRaises(ValueError): propagate(p,make_flow(mu,.5,old,-.2,.4,grid),-.1)
        with self.assertRaises(ValueError): make_flow(.2,.5,.9,1.2,.4,grid)
        with self.assertRaises(ValueError): make_flow(.2,.5,.9,-.2,0.,grid)
        RECORDS['float32_long_sequence']=dict(steps=64,maximum_mass_error=maximum_mass_error,
                                            minimum_final_probability=float(p.min()),
                                            unit_mass_negative_dt_invalid_reset_zero_phase_tau_rejected=True)


def finite_ctmc_monte_carlo(params,grid,initial,horizon,samples=30000,seed=710111):
    """Independent event-driven Gillespie sampler of the finite CTMC."""
    Q,event,_,_=independent_generator(*params,grid)
    rng=np.random.default_rng(seed)
    states=rng.choice(len(Q),size=samples,p=initial)
    clocks=np.zeros(samples)
    counts=np.zeros(samples)
    total_events=0
    while True:
        live=np.flatnonzero(clocks<horizon)
        if not len(live): break
        s=states[live]
        rates=-Q[s,s]
        waiting=np.divide(rng.exponential(size=len(live)),rates,
                          out=np.full(len(live),np.inf),where=rates>0)
        clocks[live]+=waiting
        accepted=live[clocks[live]<horizon]
        if not len(accepted): continue
        source=states[accepted]
        # Self-reset transitions would need a marked-event clock separate from
        # state exits; this sampler therefore uses only positive-phase cases.
        for source_state in np.unique(source):
            indexes=accepted[source==source_state]
            probs=Q[:,source_state].copy()
            probs[source_state]=0
            probs/=probs.sum()
            destination=rng.choice(len(Q),size=len(indexes),p=probs)
            counts[indexes]+=(source_state==grid.cells-1)&(destination==grid.cells)
            states[indexes]=destination
        total_events+=len(accepted)
    p=np.bincount(states,minlength=len(Q))/samples
    return dict(probability=p,mean_events=float(counts.mean()),
                event_standard_error=float(counts.std(ddof=1)/math.sqrt(samples)),
                samples=samples,seed=seed,total_markov_jumps=total_events)


def supplemental_references():
    grid=Grid(12,-3,3)
    params=(.37,.63,.91,-.19,.41)
    f=make_flow(*params,grid)
    p=initial_probability(f,.11)
    with torch.no_grad(): result=propagate(p,f,2.3)
    mc=finite_ctmc_monte_carlo(params,grid,p.numpy(),2.3)
    z=(float(result['events'])-mc['mean_events'])/mc['event_standard_error']
    if abs(z)>6: raise AssertionError('Independent CTMC MC count differs by >6 standard errors')
    RECORDS['independent_markov_mc']=dict(parameters=params,cells=12,phases=3,horizon=2.3,
        reference=_json(mc),finite_expected_events=float(result['events']),event_z_score=z,
        max_probability_difference=float(np.abs(result['probability'].numpy()-mc['probability']).max()))
    # Brownian renewal has an independent closed first-passage reference when
    # delay is zero.  Refining space here does not change the physical domain.
    from experiments.hcsn_free_boundary_v1.oracle import OracleParams
    from experiments.hcsn_free_boundary_v1.distributional_flow import exact_renewal_moments
    params=(.21,.61,.97,-.19,0.)
    initial,horizon=.11,1.7
    exact=exact_renewal_moments(initial,params[2],OracleParams(mu=params[0],sigma=params[1],rho=.4,K=.4,r=params[3],tau=0.),horizon)
    rows=[]
    for cells in (8,16,32,64,128):
        g=Grid(cells,-4,0)
        f=make_flow(*params,g)
        p0=initial_probability(f,initial)
        with torch.no_grad(): out=propagate(p0,f,horizon); mm=moments(f,out['probability'])
        rows.append(dict(cells=cells,events=float(out['events']),mean=float(mm['mean']),variance=float(mm['variance']),
                         event_error=abs(float(out['events'])-exact['events']),
                         mean_error=abs(float(mm['mean'])-exact['mean']),
                         variance_error=abs(float(mm['variance'])-exact['variance'])))
    if rows[-1]['event_error']>=rows[0]['event_error']:raise AssertionError('Spatial refinement failed count comparison')
    RECORDS['spatial_refinement']=dict(parameters=params,lower=-4,initial=initial,horizon=horizon,
                                      reference=exact,records=rows,
                                      scope='Unbounded Brownian zero-delay renewal versus finite reflecting-domain/upwind grids; not an exact equality at finite grid')


def performance_probe():
    B,T,C=8,16,4
    grid=Grid(8,-2,2,validate=False)
    def workload(prepared):
        mu=torch.linspace(-.2,.4,B*T*C).reshape(B,T,C).requires_grad_()
        boundary=(1.+.2*torch.sin(torch.arange(B*T*C)*.031)).reshape(B,T,C).requires_grad_()
        old=torch.cat((boundary[:,:1],boundary[:,:-1]),1)
        p=initial_probability(make_flow(mu[:,0],.5,boundary[:,0],-.2,.4,grid))
        total=p.new_zeros(B,C)
        if prepared:
            ops=prepare_operator(mu,.5,boundary,-.2,.4,.07,grid,old_boundary=old,rho=.4,K=.4,reward_intercept=-.4)
            for t in range(T):
                total=total+(p*ops['event_vector'][:,t]).sum(-1)
                p=torch.matmul(p.unsqueeze(-2),ops['transition'][:,t]).squeeze(-2)
                total=total+.1*(p*ops['values']['J'][:,t]).sum(-1)
        else:
            for t in range(T):
                out=step(p,old[:,t],mu[:,t],.5,boundary[:,t],-.2,.4,.07,grid,reward_intercept=-.4)
                p=out['probability']
                values=finite_generator_values(out['flow'],p,.4,.4)
                total=total+out['events']+.1*values['J_total']
        objective=p.square().sum()+total.sum()
        objective.backward()
        return float(objective.detach())
    rows={}
    for name,prepared in [('sequential_sparse_step',False),('prepared_basis_operator',True)]:
        workload(prepared)
        values=[]
        objectives=[]
        for _ in range(3):
            started=time.process_time()
            objectives.append(workload(prepared))
            values.append(time.process_time()-started)
        rows[name]=dict(cpu_seconds=values,median_cpu_seconds=float(np.median(values)),objectives=objectives)
    RECORDS['performance_probe']=dict(batch=B,steps=T,physical_channels=C,cells=8,phases=2,
        dtype='float32',mode='forward+backward; no optimizer update; fixed synthetic parameters',records=rows,
        median_ratio_sequential_over_prepared=rows['sequential_sparse_step']['median_cpu_seconds']/rows['prepared_basis_operator']['median_cpu_seconds'],
        energy_measured=False)


def main(output):
    output=Path(output)
    output.mkdir(parents=True,exist_ok=False)
    started=time.process_time(); wall=time.perf_counter()
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(KernelTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    supplemental_error=None
    if result.wasSuccessful():
        try:
            supplemental_references()
            performance_probe()
        except Exception as error:
            import traceback
            supplemental_error=traceback.format_exc()
    directory=Path(__file__).parent
    report=dict(schema='hcsn-distribution-kernel-audit.v1',passed=result.wasSuccessful() and supplemental_error is None,
        tests_run=result.testsRun,failures=[str(t) for t,_ in result.failures],errors=[str(t) for t,_ in result.errors],
        supplemental_error=supplemental_error,records=_json(RECORDS),
        elapsed_cpu_seconds=time.process_time()-started,elapsed_wall_seconds=time.perf_counter()-wall,
        process_cpu_to_receipt=time.process_time(),peak_rss_kib_linux=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        python=platform.python_version(),torch=torch.__version__,threads=torch.get_num_threads(),
        source_sha256={name:hashlib.sha256((directory/name).read_bytes()).hexdigest() for name in ('distribution_kernel.py','kernel_tests.py','MATH.md') if (directory/name).exists()},
        old_model_changed=False,scientific_scope='Finite-volume CTMC plus bounded Poisson propagation; local fixed-policy values; not task optimality')
    (output/'RESULTS.json').write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+'\n')
    if not report['passed']:raise SystemExit(1)
    print(json.dumps({'passed':True,'tests':result.testsRun,'cpu_seconds':report['elapsed_cpu_seconds'],
                      'prepared_speed_ratio':RECORDS['performance_probe']['median_ratio_sequential_over_prepared']}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    main(args.output)
