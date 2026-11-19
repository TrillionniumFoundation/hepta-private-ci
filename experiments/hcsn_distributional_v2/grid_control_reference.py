"""Finite-state impulse-control QVI reference, separate from the neural cell.

Q_column_forward evolves a column probability.  A_backward=Q_column_forward.T
acts on values, and row probabilities evolve by p @ exp(A_backward*t).
Natural boundary firings retain their reward rate.  Every active cell also has
an immediate FIRE action, earning center-K then entering refractory phase zero.
All refractory phases force continuation.  Positive refractory residence makes
every intervention cycle proper; zero-phase/zero-delay models are excluded.

Howard iteration chooses a discrete active set. Differentiation is certified
only through the linear equations with a fixed selected active set. The
controlled generator is also returned: substituting optimal V while retaining
the old all-CONTINUE propagation would describe the wrong process.
"""

from dataclasses import dataclass

import numpy as np
import torch
from torch.nn import functional as F

from .distribution_kernel import Grid, make_flow, initial_probability


@dataclass
class ControlProblem:
    flow: dict
    rho: torch.Tensor
    K: torch.Tensor
    Q_column_forward: torch.Tensor
    A_backward: torch.Tensor
    natural_event_rate: torch.Tensor
    natural_reward_rate: torch.Tensor
    impulse_reward: torch.Tensor


def build_problem(mu, sigma, boundary, reset, tau, rho, K,
                  grid=Grid(cells=8, lower=-2, refractory_stages=2)):
    """Construct one scalar physical problem; no batch/sequence approximation."""
    flow=make_flow(mu,sigma,boundary,reset,tau,grid)
    if flow['mu'].ndim != 0:
        raise ValueError('This control reference accepts scalar physical parameters')
    if grid.refractory_stages < 1 or not bool(flow['tau'] > 0):
        raise ValueError('Control reference requires positive refractory residence and at least one phase')
    rho=torch.as_tensor(rho,dtype=flow['mu'].dtype,device=flow['mu'].device)
    K=torch.as_tensor(K,dtype=rho.dtype,device=rho.device)
    if rho.ndim or K.ndim or not bool(torch.isfinite(rho)&torch.isfinite(K)&(rho>0)):
        raise ValueError('Finite scalar cost and strictly positive discount required')
    n,m=grid.cells,grid.refractory_stages
    size=n+m
    basis=torch.eye(size,dtype=rho.dtype,device=rho.device)
    ones=rho.new_ones(n-1);zero=rho.new_zeros(1)
    active=(flow['up']*(torch.diag(ones,-1)-torch.diag(torch.cat((ones,zero))))
            +flow['down']*(torch.diag(ones,1)-torch.diag(torch.cat((zero,ones)))))
    Q=F.pad(active,(0,m,0,m))
    Q=Q+flow['exit_rate']*torch.outer(basis[:,n]-basis[:,n-1],basis[:,n-1])
    phases=torch.diag(rho.new_ones(m-1),-1)-torch.eye(m,dtype=rho.dtype,device=rho.device)
    reset_destination=F.pad(flow['reset_weights'],(0,m))
    Q=Q+flow['phase_rate']*(F.pad(phases,(n,0,n,0))
                           +torch.outer(reset_destination,basis[:,-1]))
    event_rate=flow['exit_rate']*basis[:,n-1]
    return ControlProblem(flow,rho,K,Q,Q.T,event_rate,
                          (flow['boundary']-K)*event_rate,flow['centers']-K)


def _mask(problem, fire):
    n=problem.flow['grid'].cells
    fire=torch.as_tensor(fire,dtype=torch.bool,device=problem.rho.device)
    if fire.shape != (n,):
        raise ValueError('Exactly one Boolean FIRE/CONTINUE choice per active cell required')
    return fire


def policy_equations(problem, fire):
    """Return A_pi V = rhs_pi with correct backward orientation."""
    fire=_mask(problem,fire)
    n=problem.flow['grid'].cells
    size=problem.Q_column_forward.shape[0]
    identity=torch.eye(size,dtype=problem.rho.dtype,device=problem.rho.device)
    continuation_matrix=problem.rho*identity-problem.A_backward
    phase_zero=identity[n]
    intervention_matrix=identity-phase_zero[None,:]
    all_fire=F.pad(fire,(0,size-n))
    A=torch.where(all_fire[:,None],intervention_matrix,continuation_matrix)
    rhs=torch.where(all_fire,F.pad(problem.impulse_reward,(0,size-n)),problem.natural_reward_rate)
    return A,rhs


def evaluate_policy(problem, fire):
    """Differentiable linear policy evaluation; the Boolean active set is fixed."""
    A,rhs=policy_equations(problem,fire)
    return torch.linalg.solve(A,rhs)


def residuals(problem, value, fire=None):
    n=problem.flow['grid'].cells
    continuation=problem.natural_reward_rate+problem.A_backward@value-problem.rho*value
    obstacle=problem.impulse_reward+value[n]-value[:n]
    qvi=torch.maximum(continuation[:n],obstacle)
    result=dict(continuation=continuation,obstacle=obstacle,qvi=qvi,
        continuation_positive_violation=float(continuation.detach().clamp_min(0).max()),
        obstacle_positive_violation=float(obstacle.detach().clamp_min(0).max()),
        active_qvi_absolute_residual=float(qvi.detach().abs().max()),
        forced_phase_absolute_residual=float(continuation[n:].detach().abs().max()))
    if fire is not None:
        fire=_mask(problem,fire)
        selected=torch.where(fire,obstacle,continuation[:n])
        result['selected_equation_absolute_residual']=float(selected.detach().abs().max())
    return result


def howard(problem, initial_fire=None, tolerance=1e-10, tie_tolerance=1e-13,
           max_iterations=256):
    """Solve both sides of max(C(V), G(V)-V)=0 on active cells.

    Improvement compares the true CONTINUE alternative and immediate FIRE.
    Ties retain the current policy. Termination is accepted only when both
    inequalities, complementarity and forced-phase equations pass.
    """
    n=problem.flow['grid'].cells
    fire=(torch.zeros(n,dtype=torch.bool,device=problem.rho.device) if initial_fire is None
          else _mask(problem,initial_fire).clone())
    history=[];seen=set()
    with torch.no_grad():
        for iteration in range(max_iterations):
            key=tuple(bool(x) for x in fire.tolist())
            if key in seen:
                raise RuntimeError('Howard policy cycle; no optimum certified')
            seen.add(key)
            value=evaluate_policy(problem,fire)
            checks=residuals(problem,value,fire)
            diagonal=torch.diag(problem.A_backward)
            offdiag=problem.A_backward-torch.diag(diagonal)
            continuing=(problem.natural_reward_rate+offdiag@value)/(problem.rho-diagonal)
            firing=problem.impulse_reward+value[n]
            advantage=firing-continuing[:n]
            new=torch.where(advantage>tie_tolerance,torch.ones_like(fire),
                            torch.where(advantage < -tie_tolerance,torch.zeros_like(fire),fire))
            history.append(dict(iteration=iteration,fire_cells=torch.where(fire)[0].tolist(),
                value=value.detach().tolist(),
                residuals={k:v for k,v in checks.items() if not torch.is_tensor(v)},
                maximum_action_advantage=float(advantage.max()),
                minimum_action_advantage=float(advantage.min())))
            if bool(torch.equal(new,fire)):
                maximum=max(v for k,v in checks.items() if not torch.is_tensor(v))
                if maximum>tolerance:
                    raise RuntimeError(f'Howard stationary policy fails QVI certificate: {maximum:g}')
                break
            fire=new
        else:
            raise RuntimeError('Howard iteration cap; no optimum certified')
    # No derivative of the discrete policy choice is claimed. This recomputation
    # gives the exact fixed-policy branch derivative through the linear solve.
    value=evaluate_policy(problem,fire)
    return dict(value=value,fire=fire,history=history,iterations=len(history),
                residuals=residuals(problem,value,fire),
                derivative_scope='fixed selected active set; no derivative through policy switches')


def controlled_generator(problem, fire):
    """Eliminate instantaneous FIRE states into phase zero, carrying rewards.

    Natural firing rewards and all arrivals into intervention states are
    accumulated. Self-returning marked events still contribute to reward/count
    even if their probability transition cancels on the reduced diagonal.
    """
    fire=_mask(problem,fire)
    n=problem.flow['grid'].cells
    size=problem.Q_column_forward.shape[0]
    full_fire=F.pad(fire,(0,size-n))
    retained=torch.where(~full_fire)[0]
    fired=torch.where(full_fire)[0]
    Q=problem.Q_column_forward
    reduced=Q[retained][:,retained]
    phase_index=int(torch.where(retained==n)[0][0])
    destination=torch.eye(len(retained),dtype=Q.dtype,device=Q.device)[:,phase_index]
    incoming=Q[fired][:,retained]
    firing_rate=incoming.sum(0)
    reduced=reduced+torch.outer(destination,firing_rate)
    g=problem.natural_reward_rate[retained]+problem.impulse_reward[fired]@incoming
    events=problem.natural_event_rate[retained]+firing_rate
    # Each full row maps into the retained state after any immediate impulse.
    mapping=Q.new_zeros(size,len(retained))
    mapping[retained]=torch.eye(len(retained),dtype=Q.dtype,device=Q.device)
    mapping[fired]=destination
    initial_reward=F.pad(problem.impulse_reward,(0,size-n))*full_fire.to(Q.dtype)
    initial_count=full_fire.to(Q.dtype)
    return dict(Q_column_forward=reduced,A_backward=reduced.T,reward_rate=g,
                event_rate=events,retained_indices=retained,fire_indices=fired,
                initial_mapping=mapping,initial_reward=initial_reward,
                initial_count=initial_count,refractory_zero_reduced_index=phase_index)


def evaluate_eliminated_policy(problem, fire):
    controlled=controlled_generator(problem,fire)
    Q=controlled['Q_column_forward']
    reduced_value=torch.linalg.solve(problem.rho*torch.eye(len(Q),dtype=Q.dtype,device=Q.device)-Q.T,
                                     controlled['reward_rate'])
    value=controlled['initial_reward']+controlled['initial_mapping']@reduced_value
    return dict(value=value,reduced_value=reduced_value,controlled=controlled)


def propagate_controlled(problem, fire, probability, duration, terminal_value=None):
    """Small dense controlled-process reference, not a neural inference kernel."""
    controlled=controlled_generator(problem,fire)
    Q=controlled['Q_column_forward']
    p=torch.as_tensor(probability,dtype=Q.dtype,device=Q.device)
    dt=torch.as_tensor(duration,dtype=Q.dtype,device=Q.device)
    if (p.shape!=(problem.Q_column_forward.shape[0],) or not bool(torch.isfinite(p).all())
            or bool((p<0).any()) or abs(float(p.sum().detach())-1)>1e-10):
        raise ValueError('Unit full-state distribution required')
    if dt.ndim or not bool(torch.isfinite(dt)&(dt>=0)):
        raise ValueError('Finite nonnegative scalar duration required')
    p0=p@controlled['initial_mapping']
    count0=p@controlled['initial_count']
    reward0=p@controlled['initial_reward']
    size=len(Q)
    augmented=F.pad(Q,(0,2,0,2))
    basis=torch.eye(size+2,dtype=Q.dtype,device=Q.device)
    augmented=augmented+torch.outer(basis[:,size],F.pad(controlled['event_rate'],(0,2)))
    augmented=augmented+torch.outer(basis[:,size+1],F.pad(controlled['reward_rate'],(0,2)))
    start=torch.cat((p0,count0.reshape(1),reward0.reshape(1)))
    outcome=torch.matrix_exp(augmented*dt)@start
    discounted=F.pad(Q-problem.rho*torch.eye(size,dtype=Q.dtype,device=Q.device),(0,1,0,1))
    discounted=discounted+torch.outer(torch.eye(size+1,dtype=Q.dtype,device=Q.device)[:,-1],
                                      F.pad(controlled['reward_rate'],(0,1)))
    discounted_out=torch.matrix_exp(discounted*dt)@torch.cat((p0,reward0.reshape(1)))
    if terminal_value is None:
        terminal_value=evaluate_policy(problem,fire)
    terminal_value=torch.as_tensor(terminal_value,dtype=Q.dtype,device=Q.device)
    continuation=discounted_out[:-1]@terminal_value[controlled['retained_indices']]
    full_probability=Q.new_zeros(len(p)).scatter(0,controlled['retained_indices'],outcome[:-2])
    return dict(probability=full_probability,events=outcome[-2],reward=outcome[-1],
                discounted_reward=discounted_out[-1],discounted_terminal_value=continuation,
                discounted_reward_plus_terminal=discounted_out[-1]+continuation,
                initial_events=count0,initial_reward=reward0,controlled=controlled)


def initial_distribution(problem, initial=0.):
    return initial_probability(problem.flow,initial)


def numpy_exhaustive_policy_values(Q_column_forward, natural_reward_rate,
                                   impulse_reward, rho, phases):
    """Independent NumPy exhaustive reference using eliminated generators.

    Explicitly restricted to <=10 active states. It enumerates every Boolean
    policy, without assuming a threshold-shaped intervention region.
    """
    Q=np.asarray(Q_column_forward,dtype=float)
    g=np.asarray(natural_reward_rate,dtype=float)
    rewards=np.asarray(impulse_reward,dtype=float)
    n=len(rewards);size=len(Q)
    if n>10 or phases<1 or size!=n+phases or rho<=0:
        raise ValueError('Exhaustive reference requires <=10 cells, positive phases and discount')
    values=[];masks=[]
    for bits in range(1<<n):
        mask=np.array([bool(bits&(1<<i)) for i in range(n)])
        fired=np.flatnonzero(mask)
        retained=np.r_[np.flatnonzero(~mask),np.arange(n,size)]
        zero=int(np.flatnonzero(retained==n)[0])
        reduced=Q[np.ix_(retained,retained)].copy()
        rhs=g[retained].copy()
        for j in fired:
            for col,i in enumerate(retained):
                reduced[zero,col]+=Q[j,i]
                rhs[col]+=Q[j,i]*rewards[j]
        v=np.linalg.solve(rho*np.eye(len(retained))-reduced.T,rhs)
        full=np.empty(size)
        full[retained]=v
        full[fired]=rewards[fired]+v[zero]
        values.append(full);masks.append(mask)
    array=np.array(values)
    optimum=array.max(0)
    gaps=np.max(np.abs(array-optimum),axis=1)
    return dict(value=optimum,policy_values=array,policies=np.array(masks),
                stationary_attaining_policy_indices=np.flatnonzero(gaps<1e-9),
                minimum_joint_attainment_error=float(gaps.min()))
