"""Small independent QVI/Howard audit; does not run or change neural training."""

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
from scipy.linalg import expm
import torch

from .distribution_kernel import Grid, policy_value_vectors, propagate
from .grid_control_reference import (build_problem, evaluate_policy, howard,
    controlled_generator, evaluate_eliminated_policy, propagate_controlled,
    initial_distribution, numpy_exhaustive_policy_values)


RECORDS = {}
RAW = {}
CASES = [
    ('central',(.1,.45,1.0603110959811977,-.1,.75,.45,.525)),
    ('negative_drift',(-.28,.32,.7863315537848953,-.25,1.1,.7,.65)),
    ('positive_low_discount',(.48,.32,2.0479418003514724,-.25,.35,.17,.38)),
    ('large_noise',(.3,.58,1.4293986515135693,.05,.35,.2,.38)),
    ('negative_high_noise',(-.28,.58,1.0643207208730834,.05,1.1,.2,.65)),
    ('no_upward_noise',(-.2,0.,.9,-.2,.4,.3,.4)),
]


def independent_generator(parameters, grid):
    """NumPy assembly by enumerating physical jumps, using column orientation."""
    mu,sigma,boundary,reset,tau,rho,cost=parameters
    n,m=grid.cells,grid.refractory_stages
    h=(boundary-grid.lower)/n
    centers=grid.lower+(np.arange(n)+.5)*h
    reset_weights=np.zeros(n)
    left=int(np.searchsorted(centers,reset,side='right'))-1
    left=min(n-2,max(0,left))
    reset_weights[left+1]=(reset-centers[left])/h
    reset_weights[left]=1-reset_weights[left+1]
    diffusion=sigma*sigma/(2*h*h)
    up=diffusion+max(mu,0)/h
    down=diffusion+max(-mu,0)/h
    exit_rate=2*diffusion+max(mu,0)/h
    Q=np.zeros((n+m,n+m));events=np.zeros(n+m)
    for source in range(n):
        jumps=[]
        if source>0:jumps.append((source-1,down))
        if source+1<n:jumps.append((source+1,up))
        else:
            jumps.append((n,exit_rate));events[source]=exit_rate
        for destination,rate in jumps:
            Q[destination,source]+=rate;Q[source,source]-=rate
    for phase in range(m):
        source=n+phase
        Q[source,source]-=m/tau
        if phase+1<m:Q[source+1,source]+=m/tau
        else:
            for destination,weight in enumerate(reset_weights):
                Q[destination,source]+=(m/tau)*weight
    return Q,events,(boundary-cost)*events,centers-cost


def jsonable(value):
    if torch.is_tensor(value):value=value.detach().cpu().numpy()
    if isinstance(value,np.ndarray):return value.tolist()
    if isinstance(value,np.generic):return value.item()
    if isinstance(value,dict):return {k:jsonable(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [jsonable(v) for v in value]
    return value


class ControlTests(unittest.TestCase):
    def test_generator_direction_and_all_continue_matches_kernel(self):
        rows=[]
        for name,parameters in CASES:
            for n in (4,8,17):
                grid=Grid(cells=n,lower=-2,refractory_stages=2)
                problem=build_problem(*parameters,grid)
                Q,event,g,reward=independent_generator(parameters,grid)
                error=float(np.abs(problem.Q_column_forward.numpy()-Q).max())
                self.assertLess(error,2e-13)
                self.assertLess(float(np.abs(Q.sum(0)).max()),2e-13)
                self.assertGreaterEqual(float((Q-np.diag(np.diag(Q))).min()),0.)
                fire=torch.zeros(n,dtype=torch.bool)
                value=evaluate_policy(problem,fire)
                kernel=policy_value_vectors(problem.flow,problem.rho,problem.K)['J']
                independent=np.linalg.solve(parameters[5]*np.eye(len(Q))-Q.T,g)
                kernel_error=float((value-kernel).abs().max())
                dense_error=float(np.abs(value.numpy()-independent).max())
                self.assertLess(kernel_error,2e-12)
                self.assertLess(dense_error,2e-12)
                self.assertLess(float((problem.natural_event_rate-torch.from_numpy(event)).abs().max()),2e-13)
                self.assertLess(float((problem.impulse_reward-torch.from_numpy(reward)).abs().max()),2e-13)
                rows.append(dict(case=name,cells=n,generator_max_error=error,
                    all_continue_kernel_value_max_error=kernel_error,
                    all_continue_independent_dense_value_max_error=dense_error,
                    kernel_value=kernel,value=value))
        RECORDS['orientation_and_all_continue']=rows

    def test_howard_matches_independent_exhaustive_policies(self):
        rows=[]
        for name,parameters in CASES:
            for n in (4,6,8):
                grid=Grid(cells=n,lower=-2,refractory_stages=2)
                problem=build_problem(*parameters,grid)
                solved=howard(problem)
                Q,event,g,reward=independent_generator(parameters,grid)
                exhaustive=numpy_exhaustive_policy_values(Q,g,reward,parameters[5],2)
                error=float(np.abs(exhaustive['value']-solved['value'].numpy()).max())
                self.assertLess(error,3e-10)
                self.assertLess(exhaustive['minimum_joint_attainment_error'],1e-9)
                self.assertGreater(len(exhaustive['stationary_attaining_policy_indices']),0)
                for key,item in solved['residuals'].items():
                    if not torch.is_tensor(item):self.assertLess(item,1e-10)
                restart=howard(problem,initial_fire=torch.ones(n,dtype=torch.bool))
                self.assertLess(float((restart['value']-solved['value']).abs().max()),2e-11)
                old=evaluate_policy(problem,torch.zeros(n,dtype=torch.bool))
                self.assertGreaterEqual(float((solved['value']-old).min()),-2e-11)
                initial=initial_distribution(problem,0.)
                old_initial=float(initial@old);new_initial=float(initial@solved['value'])
                rows.append(dict(case=name,parameters=parameters,cells=n,
                    policy_count=len(exhaustive['policies']),fire_cells=torch.where(solved['fire'])[0],
                    iterations=solved['iterations'],restart_iterations=restart['iterations'],
                    maximum_exhaustive_error=error,residuals=solved['residuals'],history=solved['history'],
                    old_initial_value=old_initial,optimal_initial_value=new_initial,
                    initial_improvement=new_initial-old_initial,
                    initial_relative_improvement=(new_initial-old_initial)/abs(old_initial) if old_initial else None,
                    all_continue_value=old,optimal_value=solved['value'],
                    exhaustive_stationary_attainment=exhaustive['stationary_attaining_policy_indices']))
                RAW[f'{name}_n{n}_policy_masks']=exhaustive['policies']
                RAW[f'{name}_n{n}_policy_values']=exhaustive['policy_values']
        RECORDS['exhaustive_policy_reference']=rows

    def test_controlled_process_policy_equations_and_continuation(self):
        parameters=CASES[2][1]
        grid=Grid(cells=8,lower=-2,refractory_stages=2)
        problem=build_problem(*parameters,grid)
        selected=howard(problem)['fire']
        policies=[('continue',torch.zeros(8,dtype=torch.bool)),('optimal',selected),
                  ('all_fire',torch.ones(8,dtype=torch.bool)),
                  ('disconnected',torch.tensor([True,False,True,False,False,True,False,False]))]
        p=torch.tensor(np.random.default_rng(720101).dirichlet(np.ones(10)),dtype=torch.float64)
        rows=[]
        for label,fire in policies:
            value=evaluate_policy(problem,fire)
            eliminated=evaluate_eliminated_policy(problem,fire)
            self.assertLess(float((value-eliminated['value']).abs().max()),3e-12)
            controlled=controlled_generator(problem,fire)
            Q=controlled['Q_column_forward']
            self.assertLess(float(Q.sum(0).abs().max()),1e-13)
            offdiag=Q-torch.diag(torch.diag(Q))
            self.assertGreaterEqual(float(offdiag.min()),0.)
            self.assertGreaterEqual(float(controlled['event_rate'].min()),0.)
            for duration in (0.,.17,2.1):
                out=propagate_controlled(problem,fire,p,duration,terminal_value=value)
                self.assertLess(abs(float(out['probability'].sum())-1),3e-13)
                self.assertGreaterEqual(float(out['probability'].min()),0.)
                dynamic_error=abs(float(out['discounted_reward_plus_terminal']-p@value))
                self.assertLess(dynamic_error,2e-11)
                reduced_initial=(p@controlled['initial_mapping']).numpy()
                reference=expm(Q.numpy()*duration)@reduced_initial
                state_error=float(np.abs(out['probability'][controlled['retained_indices']].numpy()-reference).max())
                self.assertLess(state_error,2e-13)
                if duration==0:
                    self.assertAlmostEqual(float(out['events']),float(p[:8]@fire.to(p.dtype)),13)
                if label=='continue':
                    old=propagate(p,problem.flow,duration)
                    self.assertLess(float((old['probability']-out['probability']).abs().max()),2e-10)
                    self.assertLess(abs(float(old['events']-out['events'])),2e-10)
                rows.append(dict(policy=label,duration=duration,
                    equation_vs_eliminated_max_error=float((value-eliminated['value']).abs().max()),
                    discounted_reward_plus_terminal_error=dynamic_error,
                    independent_expm_state_max_error=state_error,events=float(out['events']),
                    reward=float(out['reward']),initial_events=float(out['initial_events']),
                    initial_reward=float(out['initial_reward'])))
        self.assertGreater(next(x['events'] for x in rows if x['policy']=='all_fire' and x['duration']==2.1),4.)
        RECORDS['controlled_process']=rows

    def test_fixed_active_set_physical_gradients(self):
        parameters=CASES[2][1]
        grid=Grid(cells=8,lower=-2,refractory_stages=2)
        args=[torch.tensor(x,dtype=torch.float64,requires_grad=True) for x in parameters]
        problem=build_problem(*args,grid)
        solved=howard(problem)
        p=initial_distribution(problem,.1)
        objective=p@solved['value']
        gradients=torch.autograd.grad(objective,args)
        rows=[]
        for j,name in enumerate(('mu','sigma','boundary','reset','tau','rho','K')):
            plus,minus=list(parameters),list(parameters)
            plus[j]+=1e-5;minus[j]-=1e-5
            a=build_problem(*plus,grid);b=build_problem(*minus,grid)
            pa,pb=howard(a),howard(b)
            self.assertTrue(torch.equal(pa['fire'],solved['fire']))
            self.assertTrue(torch.equal(pb['fire'],solved['fire']))
            fd=float((initial_distribution(a,.1)@pa['value']-initial_distribution(b,.1)@pb['value'])/2e-5)
            derivative=float(gradients[j]);scaled=abs(fd-derivative)/max(abs(fd),1e-6)
            self.assertLess(scaled,3e-6)
            self.assertGreater(abs(derivative),1e-7)
            rows.append(dict(parameter=name,autograd=derivative,finite_difference=fd,scaled_error=scaled))
        stopped=solved['fire'];checks=solved['residuals']
        strict_margin=torch.where(stopped,-checks['continuation'][:8],-checks['obstacle'])
        RECORDS['fixed_active_set_gradients']=dict(records=rows,fire_cells=torch.where(stopped)[0],
            minimum_inactive_equation_margin=float(strict_margin.min().detach()),
            scope='Same selected Boolean active set in all finite-difference pairs; no derivative of policy switches',
            initial_position=.1,objective=float(objective.detach()))

    def test_control_domain_and_invalid_state_rejections(self):
        with self.assertRaises(ValueError):build_problem(.2,.5,.9,-.2,0.,.4,.4,Grid(8,-2,0))
        with self.assertRaises(ValueError):build_problem(.2,.5,.9,-.2,.4,0.,.4)
        p=build_problem(.2,.5,.9,-.2,.4,.4,.4)
        with self.assertRaises(ValueError):evaluate_policy(p,[False]*7)
        with self.assertRaises(ValueError):propagate_controlled(p,[False]*8,[float('nan')]*10,.2)
        with self.assertRaises(ValueError):propagate_controlled(p,[False]*8,[.1]*10,-.2)
        RECORDS['domain_rejections']=dict(zero_refractory_model=True,zero_discount=True,
            wrong_action_shape=True,nonfinite_state=True,negative_duration=True)


def independent_controlled_monte_carlo(parameters,grid,fire,initial,horizon,value,
                                     samples=20000,seed=720103):
    """Original physical CTMC paths with immediate decisions at arrivals.

    Does not simulate the eliminated generator or use its event/reward rates.
    Refractory phase residence is sampled explicitly between repeated firings.
    """
    Q,event,g,reward=independent_generator(parameters,grid)
    n=grid.cells;rho=parameters[5]
    rng=np.random.default_rng(seed)
    states=rng.choice(len(Q),size=samples,p=initial)
    times=np.zeros(samples);counts=np.zeros(samples);rewards=np.zeros(samples);discounted=np.zeros(samples)
    hit=(states<n)&fire[np.minimum(states,n-1)]
    rewards[hit]=reward[states[hit]];discounted[hit]=rewards[hit];counts[hit]=1;states[hit]=n
    initial_count=counts.copy();total_jumps=0
    while True:
        live=np.flatnonzero(times<horizon)
        if not len(live):break
        source=states[live];rates=-Q[source,source]
        waiting=np.divide(rng.exponential(size=len(live)),rates,
                          out=np.full(len(live),np.inf),where=rates>0)
        times[live]+=waiting
        accepted=live[times[live]<horizon]
        if not len(accepted):continue
        old_states=states[accepted].copy()
        for source_state in np.unique(old_states):
            ids=accepted[old_states==source_state]
            jump=Q[:,source_state].copy();jump[source_state]=0;jump/=jump.sum()
            destination=rng.choice(len(Q),size=len(ids),p=jump)
            natural=(source_state==n-1)&(destination==n)
            intervention=(destination<n)&fire[np.minimum(destination,n-1)]
            earned=np.zeros(len(ids))
            earned[natural]=parameters[2]-parameters[6]
            earned[intervention]+=reward[destination[intervention]]
            counts[ids]+=natural.astype(float)+intervention.astype(float)
            rewards[ids]+=earned;discounted[ids]+=np.exp(-rho*times[ids])*earned
            destination[intervention]=n
            states[ids]=destination
        total_jumps+=len(accepted)
    terminal=np.exp(-rho*horizon)*value[states]
    returns=discounted+terminal
    def summary(x):
        return dict(mean=float(x.mean()),standard_error=float(x.std(ddof=1)/math.sqrt(samples)))
    return dict(probability=np.bincount(states,minlength=len(Q))/samples,
        events=summary(counts),rewards=summary(rewards),discounted_return=summary(returns),
        samples=samples,seed=seed,total_markov_jumps=total_jumps,
        initial_events=summary(initial_count),raw_counts=counts,raw_rewards=rewards,
        raw_discounted_returns=returns,raw_terminal_states=states)


def monte_carlo_references():
    parameters=CASES[2][1];grid=Grid(8,-2,2)
    problem=build_problem(*parameters,grid)
    solved=howard(problem)
    p=np.random.default_rng(720105).dirichlet(np.ones(10))
    rows=[]
    for index,(label,fire,horizon) in enumerate([
            ('optimal',solved['fire'],12.),('all_fire',torch.ones(8,dtype=torch.bool),2.1)]):
        value=evaluate_policy(problem,fire)
        predicted=propagate_controlled(problem,fire,p,horizon,terminal_value=value)
        mc=independent_controlled_monte_carlo(parameters,grid,fire.numpy(),p,horizon,value.numpy(),
                                            seed=720107+index)
        event_z=(float(predicted['events'])-mc['events']['mean'])/mc['events']['standard_error']
        value_z=(float(torch.from_numpy(p)@value)-mc['discounted_return']['mean'])/mc['discounted_return']['standard_error']
        reward_z=(float(predicted['reward'])-mc['rewards']['mean'])/mc['rewards']['standard_error']
        if max(abs(event_z),abs(value_z),abs(reward_z))>6:
            raise AssertionError('Controlled-process MC differs by more than six standard errors')
        for key in tuple(mc):
            if key.startswith('raw_'):RAW[f'mc_{label}_{key}']=mc.pop(key)
        rows.append(dict(policy=label,horizon=horizon,reference=mc,event_z_score=event_z,
            reward_z_score=reward_z,value_z_score=value_z,predicted_events=float(predicted['events']),
            predicted_reward=float(predicted['reward']),predicted_value=float(torch.from_numpy(p)@value),
            probability_max_error=float(np.abs(predicted['probability'].numpy()-mc['probability']).max())))
    RECORDS['independent_controlled_path_mc']=rows


def performance_probe():
    parameters=CASES[2][1]
    rows=[]
    for n in (4,8,16,32,64):
        grid=Grid(n,-2,2)
        def workload(backward):
            args=[torch.tensor(x,dtype=torch.float64,requires_grad=backward) for x in parameters]
            problem=build_problem(*args,grid)
            solved=howard(problem,tolerance=1e-9)
            objective=initial_distribution(problem,.1)@solved['value']
            if backward:objective.backward()
            return float(objective.detach()),solved['iterations']
        by_mode={}
        for mode,backward in [('forward',False),('forward_and_backward',True)]:
            workload(backward)
            times=[];outcomes=[]
            for _ in range(5):
                start=time.process_time();outcomes.append(workload(backward));times.append(time.process_time()-start)
            by_mode[mode]=dict(cpu_seconds=times,median_cpu_seconds=float(np.median(times)),outcomes=outcomes)
        rows.append(dict(cells=n,phases=2,records=by_mode))
    RECORDS['performance_probe']=dict(records=rows,dtype='float64',batch=1,
        scope='Scalar dense reference including generator assembly, Howard selection and optional fixed-policy backward; no optimizer or training',
        energy_measured=False)


def main(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    started=time.process_time();wall=time.perf_counter()
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(ControlTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    supplemental_error=None
    if result.wasSuccessful():
        try:
            monte_carlo_references();performance_probe()
        except Exception:
            import traceback
            supplemental_error=traceback.format_exc()
    if RAW:np.savez_compressed(output/'RAW_REFERENCES.npz',**RAW)
    directory=Path(__file__).parent
    report=dict(schema='hcsn-finite-grid-control-audit.v1',passed=result.wasSuccessful() and supplemental_error is None,
        tests_run=result.testsRun,failures=[str(t) for t,_ in result.failures],errors=[str(t) for t,_ in result.errors],
        supplemental_error=supplemental_error,records=jsonable(RECORDS),
        elapsed_cpu_seconds=time.process_time()-started,elapsed_wall_seconds=time.perf_counter()-wall,
        process_cpu_to_receipt=time.process_time(),peak_rss_kib_linux=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        python=platform.python_version(),torch=torch.__version__,threads=torch.get_num_threads(),
        source_sha256={name:hashlib.sha256((directory/name).read_bytes()).hexdigest() for name in
                       ('grid_control_reference.py','grid_control_tests.py','distribution_kernel.py','model.py')},
        raw_reference_sha256=hashlib.sha256((output/'RAW_REFERENCES.npz').read_bytes()).hexdigest() if RAW else None,
        neural_training_changed=False,scientific_scope='Optimal impulse control of the fixed finite CTMC with active-cell FIRE and forced phase continuation; not continuous free-boundary or task optimality')
    (output/'RESULTS.json').write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+'\n')
    if not report['passed']:raise SystemExit(1)
    print(json.dumps(dict(passed=True,tests=result.testsRun,cpu_seconds=report['elapsed_cpu_seconds'])))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    args=parser.parse_args();torch.set_num_threads(1);torch.set_num_interop_threads(1)
    main(args.output)
