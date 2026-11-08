"""Construct explicitly fixed FP64 kernels for the separate mechanism pilot.

All arms have 81 probability coefficients and use the same learned observer
and readout. Different physical laws use different registered bases; their
projection differences are disclosed, not claimed to be continuum equality.
"""

import argparse
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import platform
import resource
import time

import numpy as np
import scipy
from scipy.linalg import expm
from scipy.special import ndtr

from .fixed_renewal import FixedDiffusion, instant_reset_transition, instant_reset_value, killed_interval


ARMS = ('regenerative_dual','smooth_dual','margin_only','call_only','risk_only',
        'endpoint','no_reset','no_refractory','uniform_tick','conditional_boundary')
DT = (.025,.05,.075,.1)
ACTIVE_CELLS, PHASE_CELLS = 64, 16
STATE_COUNT = ACTIVE_CELLS + 1 + PHASE_CELLS
MU, SIGMA, DISCOUNT = -.1,.3,.15
RESET_MARGIN, REFRACTORY, INITIAL = .25,.1,.35
ENDPOINT, TAIL_RATE = 2.,1.


def _rule(order):
    nodes,weights=np.polynomial.legendre.leggauss(order)
    return (nodes+1)/2,weights/2


def _source_map():
    root=Path(__file__).parent
    names=['__init__.py','mechanism_operators.py','fixed_renewal.py','FIXED_RENEWAL.md',
           'tensor.py','tensor_normal.py','tensor_short.py','tensor_state.py',
           'distribution.py','distribution_kernel.py','distribution_operator.py']
    return {str((root/name).relative_to(root.parent.parent)):hashlib.sha256((root/name).read_bytes()).hexdigest()
            for name in names}


def _basis(active_cells,order):
    edges=np.linspace(0,ENDPOINT,active_cells+1)
    u,w=_rule(order)
    positions=edges[:-1,None]+np.diff(edges)[:,None]*u
    positions=np.concatenate((positions,(ENDPOINT-np.log1p(-u)/TAIL_RATE)[None,:]))
    means=np.r_[(edges[:-1]+edges[1:])/2,ENDPOINT+1/TAIL_RATE]
    return edges,positions,w,means


def _endpoint_features(active_edges,phase_edges,margin,duration,order=64):
    u,w=_rule(order)
    positions=active_edges[:-1,None]+np.diff(active_edges)[:,None]*u
    positions=np.concatenate((positions,(active_edges[-1]-np.log1p(-u)/TAIL_RATE)[None,:]))
    values=list(ndtr((-positions-MU*duration)/(SIGMA*math.sqrt(duration)))@w)
    for low,high in zip(phase_edges[:-1],phase_edges[1:]):
        end=min(high,duration)
        if end<=low:
            values.append(0.)
        else:
            remaining=duration-(low+(end-low)*u)
            values.append(float((end-low)/(high-low)
                                *np.dot(w,ndtr((-margin-MU*remaining)/(SIGMA*np.sqrt(remaining))))))
    return np.asarray(values)


def regenerative_table(duration,margin=RESET_MARGIN,initial=INITIAL):
    import torch
    from .distribution import DistributionGrid,DistributionState
    from .distribution_operator import DistributionOperator
    from .tensor import TensorDiffusion,TensorReset
    active_edges=tuple(np.linspace(0,ENDPOINT,ACTIVE_CELLS+1))
    phase_edges=tuple(float(Fraction(str(REFRACTORY))*i/PHASE_CELLS) for i in range(PHASE_CELLS+1))
    grid=DistributionGrid(active_edges,phase_edges,TAIL_RATE)
    process=TensorDiffusion(*(torch.tensor(v,dtype=torch.float64) for v in (MU,SIGMA,DISCOUNT)))
    operator=DistributionOperator(process,TensorReset(margin,REFRACTORY),grid,duration,
                                  dtype=torch.float64,device='cpu',quadrature_order=32)
    matrix=operator.matrix.numpy()
    reward=operator.reward_matrix.numpy()
    initial_state=DistributionState.point(grid,initial,dtype=torch.float64)
    first=operator.advance(initial_state).state
    if first.active_atoms or first.refractory_atoms:
        raise ValueError('The pilot initial condition must project to the fixed coefficient vector')
    active=matrix[:,:grid.active_size+1].sum(-1)
    call=.4*reward[:,2]+reward[:,1]+.2*math.exp(-DISCOUNT*duration)*active
    margin_feature=np.r_[(np.asarray(active_edges[:-1])+active_edges[1:])/2,
                         ENDPOINT+1/TAIL_RATE,np.zeros(grid.refractory_size)]
    features=np.stack((margin_feature,call,reward[:,0]),axis=-1)
    endpoint=_endpoint_features(np.asarray(active_edges),np.asarray(phase_edges),margin,duration)
    return dict(matrix=matrix,first_step=first.mass.numpy(),features=features,endpoint=endpoint,
                diagnostics=operator.diagnostics,state_basis=grid.specification(),
                physical_generator=dict(mu=MU,sigma=SIGMA,discount=DISCOUNT,reset_margin=margin,refractory=REFRACTORY),
                initial_distance=initial,elapsed_duration=duration,construction_dtype='float64')


def no_reset_table(duration,order=32):
    """Absorb permanently at zero; the absorbing coefficient remains explicit."""
    process=FixedDiffusion(MU,SIGMA,DISCOUNT)

    def construct(n):
        edges,positions,w,means=_basis(STATE_COUNT-2,n)
        intervals=list(zip(edges[:-1],edges[1:]))+[(ENDPOINT,math.inf)]
        def point(x):
            risk=process.first_hit(float(x),duration)
            discounted=process.first_hit(float(x),duration,discounted=True)
            occupation=(1-discounted-math.exp(-DISCOUNT*duration)*(1-risk))/DISCOUNT
            if occupation < 0 or not math.isfinite(occupation):
                raise FloatingPointError('No-reset occupation unresolved')
            mass=[killed_interval(process,float(x),duration,float(lo),float(hi)) for lo,hi in intervals]
            mass.append(risk)
            call=.4*occupation+discounted+.2*math.exp(-DISCOUNT*duration)*(1-risk)
            return np.asarray(mass),np.asarray([call,risk])
        matrix=np.zeros((STATE_COUNT,STATE_COUNT))
        features=np.zeros((STATE_COUNT,3))
        features[:-1,0]=means
        for i,row in enumerate(positions):
            for x,weight in zip(row,w):
                mass,channels=point(x)
                matrix[i]+=weight*mass
                features[i,1:]+=weight*channels
        matrix[-1,-1]=1.
        first=point(INITIAL)[0]
        return matrix,features,first,edges
    coarse,cr,_,_=construct(order)
    fine,fr,first,edges=construct(2*order)
    difference=float(np.abs(fine-coarse).sum(-1).max())
    reward_difference=float(np.abs(fr-cr).max())
    if difference>2e-7 or reward_difference>2e-7:
        raise FloatingPointError('No-reset input-distribution quadrature unresolved')
    return dict(matrix=fine,first_step=first,features=fr,
                diagnostics=dict(row_l1_order_difference=difference,feature_order_difference=reward_difference,
                                 renewal_tail_bound=0.,no_row_normalization=True),
                state_basis=dict(active_edges=edges.tolist(),tail_density='exponential',tail_rate=TAIL_RATE,
                                 absorbing_coefficients=1,refractory_coefficients=0),
                physical_generator=dict(mu=MU,sigma=SIGMA,discount=DISCOUNT,reset='none',refractory='not_applicable'),
                initial_distance=INITIAL,elapsed_duration=duration,construction_dtype='float64')


def no_refractory_table(duration,order=32):
    """True d=0 regenerative process with bounded infinite-renewal omission."""
    process=FixedDiffusion(MU,SIGMA,DISCOUNT)
    omissions=[]
    def construct(n):
        edges,positions,w,means=_basis(STATE_COUNT-1,n)
        def point(x):
            row=instant_reset_transition(process,RESET_MARGIN,float(x),duration,edges,tolerance=1e-12)
            value=instant_reset_value(process,row,duration,active_reward=.4,terminal_reward=.2)
            omissions.append((row.omitted_active_mass,row.omitted_hit_count_bound))
            return np.r_[row.active_bins,row.upper_tail],np.array([value['value'],row.first_hit_probability])
        matrix=np.zeros((STATE_COUNT,STATE_COUNT))
        features=np.zeros((STATE_COUNT,3));features[:,0]=means
        for i,row in enumerate(positions):
            for x,weight in zip(row,w):
                mass,channels=point(x)
                matrix[i]+=weight*mass
                features[i,1:]+=weight*channels
        return matrix,features,point(INITIAL)[0],edges
    coarse,cr,_,_=construct(order)
    fine,fr,first,edges=construct(2*order)
    difference=float(np.abs(fine-coarse).sum(-1).max())
    reward_difference=float(np.abs(fr-cr).max())
    if difference>2e-7 or reward_difference>2e-7:
        raise FloatingPointError('Zero-delay input-distribution quadrature unresolved')
    return dict(matrix=fine,first_step=first,features=fr,
                diagnostics=dict(row_l1_order_difference=difference,feature_order_difference=reward_difference,
                                 maximum_omitted_state_mass=max(x[0] for x in omissions),
                                 maximum_omitted_hit_count_bound=max(x[1] for x in omissions),
                                 no_row_normalization=True),
                state_basis=dict(active_edges=edges.tolist(),tail_density='exponential',tail_rate=TAIL_RATE,
                                 refractory_coefficients=0,absorbing_coefficients=0),
                physical_generator=dict(mu=MU,sigma=SIGMA,discount=DISCOUNT,reset_margin=RESET_MARGIN,refractory=0.),
                initial_distance=INITIAL,elapsed_duration=duration,construction_dtype='float64')


def smooth_table(duration):
    """Ordinary smooth finite-state core, with matched coefficient capacity.

    A nearest-neighbor reflecting CTMC replaces the analytic regenerative
    kernel. It has no deterministic refractory clock or reset jump. Value,
    prospective entry risk, and forward state all follow this same Q.
    """
    active_edges=np.linspace(0,ENDPOINT,ACTIVE_CELLS+1)
    phase_edges=np.asarray([float(Fraction(str(REFRACTORY))*i/PHASE_CELLS) for i in range(PHASE_CELLS+1)])
    positions=np.r_[(active_edges[:-1]+active_edges[1:])/2,ENDPOINT+1/TAIL_RATE,
                    -(phase_edges[:-1]+phase_edges[1:])/2]
    active=np.r_[np.ones(ACTIVE_CELLS+1),np.zeros(PHASE_CELLS)]
    order=np.argsort(positions)
    q=np.zeros((STATE_COUNT,STATE_COUNT))
    diffusion=.5*SIGMA*SIGMA
    for k,i in enumerate(order):
        left=positions[i]-positions[order[k-1]] if k else None
        right=positions[order[k+1]]-positions[i] if k+1<len(order) else None
        if left is not None:
            rate=(2*diffusion/(left*(left+right)) if right is not None else diffusion/left**2)+max(-MU,0)/left
            q[i,order[k-1]]+=rate;q[i,i]-=rate
        if right is not None:
            rate=(2*diffusion/(right*(left+right)) if left is not None else diffusion/right**2)+max(MU,0)/right
            q[i,order[k+1]]+=rate;q[i,i]-=rate
    matrix=expm(q*duration)
    killed=q.copy();rate=np.zeros(STATE_COUNT)
    for i in np.flatnonzero(active):
        for j in np.flatnonzero(1-active):
            if q[i,j]>0:
                rate[i]+=q[i,j];killed[i,j]=0.
    augmented=np.zeros((STATE_COUNT+1,STATE_COUNT+1))
    augmented[:STATE_COUNT,:STATE_COUNT]=killed
    augmented[:STATE_COUNT,-1]=rate
    risk=expm(augmented*duration)[:STATE_COUNT,-1]
    rewards=np.zeros((STATE_COUNT+2,STATE_COUNT+2))
    rewards[:STATE_COUNT,:STATE_COUNT]=q-DISCOUNT*np.eye(STATE_COUNT)
    rewards[:STATE_COUNT,-2]=rate;rewards[:STATE_COUNT,-1]=active
    integrated=expm(rewards*duration)[:STATE_COUNT,-2:]
    call=integrated[:,0]+.4*integrated[:,1]+.2*math.exp(-DISCOUNT*duration)*(matrix@active)
    features=np.stack((positions*active,call,risk),axis=-1)
    prior=np.zeros(STATE_COUNT)
    k=int(np.searchsorted(positions[order],INITIAL))
    lo,hi=order[k-1],order[k]
    fraction=(INITIAL-positions[lo])/(positions[hi]-positions[lo])
    prior[lo]=1-fraction;prior[hi]=fraction
    return dict(matrix=matrix,first_step=prior@matrix,features=features,
                diagnostics=dict(generator_row_sum_residual=float(np.abs(q.sum(-1)).max()),
                                 matrix_mass_residual=float(np.abs(matrix.sum(-1)-1).max()),
                                 no_row_normalization=True),
                state_basis=dict(positions=positions.tolist(),active_indicator=active.tolist(),
                                 tail='finite last location, reflecting; not the analytic exponential tail',
                                 initial_projection='linear interpolation at the same initial physical distance'),
                physical_generator=dict(kind='ordinary_smooth_reflecting_finite_ctmc',mu=MU,sigma=SIGMA,discount=DISCOUNT,
                                        deterministic_refractory=False,reset_jump=False),
                initial_distance=INITIAL,elapsed_duration=duration,construction_dtype='float64')


def _validate_table(table):
    for name,shape in [('matrix',(STATE_COUNT,STATE_COUNT)),('first_step',(STATE_COUNT,)),('features',(STATE_COUNT,3))]:
        array=table[name]
        if array.shape!=shape or not np.isfinite(array).all() or np.any(array<0):
            raise FloatingPointError('Invalid fixed table '+name)
    defect=max(float(np.abs(table['matrix'].sum(-1)-1).max()),abs(float(table['first_step'].sum())-1))
    if defect>5e-9 or float(table['features'][:,-1].max())>1+5e-9:
        raise FloatingPointError('Fixed table mass/risk unresolved')
    return defect


def build(output):
    output=Path(output)
    metadata_path=output.with_suffix('.json')
    if output.suffix!='.npz' or output.exists() or metadata_path.exists():
        raise ValueError('Use a new .npz bundle and sidecar path')
    started,cpu=time.monotonic(),time.process_time()
    sources=_source_map()
    cache={}
    def get(kind,duration,margin=RESET_MARGIN,initial=INITIAL):
        key=(kind,duration,margin,initial)
        if key not in cache:
            tick=time.monotonic()
            function={'regenerative':regenerative_table,'no_reset':no_reset_table,
                      'no_refractory':no_refractory_table,'smooth':smooth_table}[kind]
            table=function(duration,margin,initial) if kind=='regenerative' else function(duration)
            table['construction_wall_seconds']=time.monotonic()-tick
            table['maximum_mass_defect']=_validate_table(table)
            cache[key]=table
        return cache[key]
    arrays={};arms={}
    for arm in ARMS:
        matrices=[];first_steps=[];features=[];details=[]
        for cohort in range(2):
            cm=[];cf=[];cx=[];cd=[]
            boundary_log=(-.025 if cohort==0 else .025) if arm=='conditional_boundary' else 0.
            for duration in DT:
                effective=.0625 if arm=='uniform_tick' else duration
                kind={'smooth_dual':'smooth','no_reset':'no_reset','no_refractory':'no_refractory'}.get(arm,'regenerative')
                table=get(kind,effective,RESET_MARGIN-boundary_log,INITIAL-boundary_log)
                value=table['features'].copy()
                if arm=='endpoint':
                    value[:,-1]=table['endpoint']
                cm.append(table['matrix']);cf.append(table['first_step']);cx.append(value)
                cd.append({k:v for k,v in table.items() if k not in ('matrix','first_step','features','endpoint')})
            matrices.append(cm);first_steps.append(cf);features.append(cx);details.append(cd)
        for name,data in [('matrix',matrices),('first_step',first_steps),('features',features)]:
            array=np.asarray(data,dtype=np.float32)
            arrays[arm+'__'+name]=array
        cast=arrays[arm+'__matrix'].astype(np.float64)
        cast_first=arrays[arm+'__first_step'].astype(np.float64)
        cast_defect=max(float(np.abs(cast.sum(-1)-1).max()),float(np.abs(cast_first.sum(-1)-1).max()))
        if cast_defect>3e-6:
            raise FloatingPointError('FP32 materialization failed mass conservation')
        channel={'margin_only':'margin','call_only':'call','risk_only':'risk'}.get(arm,'dual')
        arms[arm]=dict(channel=channel,cohort_rule='first_dt_index >= 2, fixed for the complete episode',
                       tables=details,cast_mass_defect=cast_defect,
                       state_count=STATE_COUNT,execution_dtype='float32',construction_dtype='float64')
    if sources!=_source_map():
        raise RuntimeError('Builder source changed during construction')
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('xb') as stream:
        np.savez(stream,**arrays)
    bundle_sha=hashlib.sha256(output.read_bytes()).hexdigest()
    metadata=dict(schema='hcsn-mechanism-operator-bundle-v1',arms=arms,dt_choices=list(DT),state_count=STATE_COUNT,
                  bundle_sha256=bundle_sha,source_pins=sources,source_unchanged=True,
                  array_sha256={k:hashlib.sha256(v.tobytes()).hexdigest() for k,v in arrays.items()},
                  array_bytes={k:v.nbytes for k,v in arrays.items()},
                  python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__,
                  builder_wall_seconds=time.monotonic()-started,builder_process_cpu_seconds=time.process_time()-cpu,
                  builder_process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                  shared_kernel_construction_count=len(cache),shared_construction_cost_counted_once=True,
                  cost_scope='Host construction; shared tables are built once and reused. Cached table times must not be summed once per consuming arm.',
                  physical_energy_joules=None,provider_charges=None,
                  relative_far_tail_accuracy_qualified=False,global_continuum_error_certificate=False,
                  selected_base_active_cells=ACTIVE_CELLS,selected_base_refractory_cells=PHASE_CELLS,
                  resolution_selection_scope='Smallest predeclared grid passing state L1 <= .02 and hit-count relative error <= .03 on both fixed 64-step T=4 schedules, FP32 and FP64; unconditioned base process only.',
                  capacity_scope='equal learned parameter architecture, coefficient count and FP32 dynamic-state bytes; bases differ by the intervention',
                  full_financial_hx_kernel=False,qvi_boundary=False,external_task_gain_established=False,
                  original_campaign_completion_credit=0)
    with metadata_path.open('x') as stream:
        json.dump(metadata,stream,indent=2,allow_nan=False);stream.write('\n')
    return metadata


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    result=build(args.output)
    print(json.dumps({k:result[k] for k in ('schema','bundle_sha256','state_count','shared_kernel_construction_count','builder_wall_seconds')}))


if __name__=='__main__':
    main()
