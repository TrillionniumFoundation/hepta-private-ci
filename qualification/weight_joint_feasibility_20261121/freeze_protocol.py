"""Zero-neural-forward preflight and later single create-only protocol freeze."""
import ast
import datetime
import importlib.metadata
import os
from pathlib import Path
import platform
import sys
import time
import numpy as np
from common import ROOT,OLD,MLP,CAUSAL,LAST,FITS,read,save,identity,specs,verify_pin_map,load_fit


SOURCE_PATHS=[CAUSAL/'PROTOCOL_FROZEN.json',CAUSAL/'causal_core.py',CAUSAL/'experiment.py',
    OLD/'task_graph.py',OLD/'vendor/planning.py',OLD/'vendor/frozen_joint/joint_task.py',
    OLD/'vendor/frozen_joint/joint_deploy.py',OLD/'vendor/frozen_joint/legacy_task.py',
    MLP/'mlp_math.py',MLP/'run_full_mlp_experiment.py',MLP/'PROTOCOL_FROZEN.json',
    LAST/'discovery.py',LAST/'PROTOCOL_FROZEN.json',LAST/'RECORD_REVIEW.json']


def preflight():
    if (ROOT/'PREFLIGHT.json').exists() or (ROOT/'attempt001').exists():raise ValueError('preflight/attempt already exists')
    start=time.process_time();inputs={str(f):specs(f) for f in FITS};pins={};rows=0;support=[]
    for fit in FITS:
        spec=inputs[str(fit)]
        for path in spec.values():pins[path]=identity(path)
        d=load_fit(spec);rows+=len(d['X']);occ=d['normocc']>0;blocked=~np.isfinite(d['previous']['fixed_Q147_lower_bound'])
        support.append(dict(fit=fit,rows=len(d['X']),occupied=int(occ.sum()),
            blocked_occupied=int(np.count_nonzero(occ&blocked)),occupied_target_counts=np.bincount(d['target'][occ],minlength=6).tolist()))
        del d
    assert rows==144397
    for path in SOURCE_PATHS:pins[str(path)]=identity(path)
    # Pin the very source bytes already admitted by the original source chain.
    oldprotocols=[(CAUSAL,read(CAUSAL/'PROTOCOL_FROZEN.json')),(MLP,read(MLP/'PROTOCOL_FROZEN.json')),(LAST,read(LAST/'PROTOCOL_FROZEN.json'))]
    checked=[]
    for source in (CAUSAL/'causal_core.py',CAUSAL/'experiment.py',OLD/'task_graph.py',OLD/'vendor/planning.py',MLP/'mlp_math.py',LAST/'discovery.py'):
        matches=[]
        for root,protocol in oldprotocols:
            for name,pin in protocol['files'].items():
                candidate=Path(name) if Path(name).is_absolute() else root/name
                if candidate.resolve()==source.resolve():matches.append(pin)
        if not matches or any(pin!=identity(source) for pin in matches):raise ValueError('old pinned source mismatch: '+str(source))
        checked.append(str(source))
    for path in ROOT.glob('*.py'):
        ast.parse(path.read_text(),filename=str(path));pins[str(path)]=identity(path)
    pins[str(ROOT/'DRAFT_PROTOCOL.md')]=identity(ROOT/'DRAFT_PROTOCOL.md')
    import joint_solver as solver
    A=np.eye(2);b=np.array([1.,2.]);x,z,info=solver.invoke(A,b,2.)
    if info['status']!='Solved' or np.max(np.abs(x-b))>1e-6 or np.max(np.abs(z-b))>1e-6:
        raise ArithmeticError('tiny feasible solver interface differs from analytic optimum')
    synthetic=[dict(problem='two-coordinate analytic feasible',x=x.tolist(),dual=z.tolist(),**info)]
    A=np.array([[1.],[-1.]]);b=np.array([1.,0.]);x,z,info=solver.invoke(A,b,2.)
    indication=solver.infeasibility_indication(A,b,z)
    if info['status']!='PrimalInfeasible' or not indication.get('checked_numeric_indication'):
        raise ArithmeticError('tiny infeasible solver interface differs')
    synthetic.append(dict(problem='one-coordinate analytic inconsistent',x=x.tolist(),dual=z.tolist(),indication=indication,**info))
    result=dict(status='PASS_ZERO_NEURAL_FORWARD_PREFLIGHT',created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        inputs=inputs,files=pins,support=support,source_generation_pins_rechecked=checked,
        rows_metadata=rows,model_forwards=0,optimizer_real_data_calls=0,
        synthetic_solver_interface_calls=2,synthetic_cases=synthetic,
        packages={name:importlib.metadata.version(name) for name in ('numpy','scipy','clarabel','osqp')},
        python=sys.version,machine=platform.machine(),allowed_cpus=sorted(os.sched_getaffinity(0)),
        CPU_seconds=time.process_time()-start,
        preparation_issue='Earlier metadata inventory attempted unavailable private numpy.lib.format._read_array_header; public header API follow-up was metadata-only; no model/solver study attempted.')
    save(ROOT/'PREFLIGHT.json',result)
    print({'status':result['status'],'CPU_seconds':result['CPU_seconds'],'input_rows':rows},flush=True)


def freeze():
    if (ROOT/'PROTOCOL_FROZEN.json').exists() or (ROOT/'attempt001').exists():raise ValueError('protocol/attempt already exists')
    p=read(ROOT/'PREFLIGHT.json');assert p['status']=='PASS_ZERO_NEURAL_FORWARD_PREFLIGHT'
    verify_pin_map(p['files'])
    review=read(ROOT/'PEER_STATIC_REVIEW.json')
    if review['status']!='PASS_AFTER_REVIEW':raise ValueError('peer static review must precede freeze')
    files=p['files'].copy()
    for name in ('PREFLIGHT.json','PEER_STATIC_REVIEW.json'):files[str(ROOT/name)]=identity(ROOT/name)
    protocol=dict(schema='hepta-fixed-hidden-joint-policy-feasibility-v1',
        status='FROZEN_BEFORE_FIRST_REAL_MODEL_FORWARD_OR_SOLVE',
        created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),fits=list(FITS),inputs=p['inputs'],files=files,
        target='checkpoint own-law optimal Bellman policy from sealed own_optimal_targets and own_posterior',
        scopes=['all structural TRAIN support','original positive eligible occupancy','occupancy times own-action gap'],
        cases=['occ_lex','occ_margin','full_repairable_lex','belief_sign','joint_sequential'],
        parameters=dict(Q=147,belief=49,hidden_fixed=True,radius_fraction_original_Q=.5,
            lex_lower_index_margin=1e-6,editable_robust_margin=1e-3,belief_terminal_margin=1e-4,belief_logit_guard=1e-7),
        solver=dict(name='Clarabel',version=p['packages']['clarabel'],threads=1,direct_solver='qdldl',
            max_iter=100,feasibility_tolerance=1e-9,objective_tolerances=1e-9,
            max_cut_rounds=8,max_active_rows=2048,worst_new_per_ordered_action_pair=8,
            no_fallback=True,automatic_retry=False,minimum_scope='declared epsilon QP; strict policy infimum bounded separately'),
        resources=dict(main_CPU_hard_seconds=120,main_CPU_soft_seconds=105,fit_CPU_soft_seconds=18,
            main_wall_hard_seconds=180,address_space_bytes=536870912,threads=1,affinity_CPU=7,
            reader_CPU_hard_seconds=15,reader_wall_hard_seconds=30,
            solver_wall_caps=dict(occ_lex=3,occ_margin=2,full_repairable_lex=6,belief_sign=2,joint_sequential=2),
            preparation_CPU_separate=p['CPU_seconds'],reader_CPU_separate=True),
        new_DEV=0,new_CONF=0,gradient_updates=0,production_writes=0,
        own_CTMC_or_DAG_regenerated=False,original_input_and_output_contracts_unchanged=True,
        future_compute_contract=None,NDU_default='KEEP_ORIGINAL_AND_STOP',
        external_preregistration=False,exact_arithmetic_certificate_claimed=False,
        scientific_scope='single bounded discovery study on exposed TRAIN; candidate vectors not deployed or evaluated on new data')
    save(ROOT/'PROTOCOL_FROZEN.json',protocol)
    print(dict(status=protocol['status'],**identity(ROOT/'PROTOCOL_FROZEN.json')),flush=True)


if __name__=='__main__':
    if sys.argv[1:] == ['--preflight']:preflight()
    elif sys.argv[1:] == ['--freeze']:freeze()
    else:raise SystemExit('use --preflight or --freeze')
