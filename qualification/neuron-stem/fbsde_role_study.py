"""Expand interpretation hypotheses; never retrain on the new evaluation frames."""
import hashlib
import math
from pathlib import Path
import random
import time
from four_gate_common import digest, require, strict_loads, write_once
from fbsde_outcome_audit import audit as audit_source
from fbsde_outcome_policy import execute
from fbsde_depth_data import construct
from fbsde_tracking import make_gate, lexical_vector, slot_text
from fbsde_tracking_control import BeliefProblem, pair_law, PlanningBudgetError
from fbsde_tracking_records import RecordBuffer
from fbsde_role_program import PROFILE, PAIRS, RoleProgramBelief, describe
from fbsde_role_data import SEED, FRAMES, generate, operation

ARMS = ('old_none','old_one','old_two','independent_role_two','program_head_none',
        'program_head_one','program_head_two','program_uniform_one','program_uniform_two','uniform_probe',
        'verify_all_inputs','exact_reverse')


def probe(problem, reveal):
    """Cheap family-matched control: check first unresolved frame until support agrees."""
    start=time.process_time_ns(); h=(); checks=[]; decisions=[]
    for _ in range(3):
        begin=time.process_time_ns(); holder=problem.identified_holder(h)
        available=problem.available_events(h)
        action=('abstain' if len(checks)==2 or not available else f'verify:{available[0]}') if holder is None else f'answer:{holder}'
        elapsed=time.process_time_ns()-begin
        if elapsed>100_000_000: raise PlanningBudgetError('role probe CPU budget exhausted',problem,0,begin)
        decisions.append(dict(action=action,known=h,nodes=0,cpu_ns=elapsed,plan=None))
        if not action.startswith('verify:'): break
        e=int(action.split(':')[1]); o=reveal(e)
        require(type(o) is int and o in range(3),'typed source observation')
        checks.append(dict(event=e,outcome=o,known_before=h));h=tuple(sorted(h+((e,o),)))
    return dict(holder=holder,text='Insufficient evidence; abstain.' if holder is None else ('amber','blue','coral')[holder],
                probabilities=problem.marginal(h),checks=checks,decisions=decisions,route=None,
                problem_sha256=problem.identity,cpu_ns=time.process_time_ns()-start)


def run(output, evidence_dir):
    import torch
    root=Path(output); source=Path(evidence_dir); root.mkdir(parents=True,exist_ok=False)
    started=time.process_time_ns(); torch.set_num_threads(2)
    def read(name):
        p=source/(name+'.json'); require(p.is_file() and not p.is_symlink() and p.stat().st_size<64*1024*1024,'bounded source')
        return strict_loads(p.read_bytes())
    write_once(root/'source-audit.json',audit_source(source))
    snapshot=read('frozen-model'); cal=read('frozen-calibration'); model=digest(snapshot); calibration=digest(cal)
    rows=generate(read('inputs'))
    write_once(root/'plan.json',dict(profile=PROFILE,arms=ARMS,seed=SEED,frames=FRAMES,
        model=model,calibration=calibration,check_price=.02,depth_price=.002,max_checks=2,cpu_limit_ns=100_000_000,max_nodes=20000,
        prior='arithmetic_opinion_pool_not_independent_evidence',source_files={n:hashlib.sha256((source/(n+'.json')).read_bytes()).hexdigest()
            for n in ('frozen-model','frozen-calibration','inputs')},source_code={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path(__file__).parent.glob('fbsde_role*.py')},new_frames_defined_before_first_run=True,uniform_one_added_after_initial_run=True,
        diagnostic_replay_is_posthoc=True,hypothesis_family_assumed=True,production_promotion_permitted=False))
    write_once(root/'inputs.json',rows)
    members=[]
    for st in snapshot['base']:
        m=make_gate(torch); m.load_state_dict({k:torch.tensor(v) for k,v in st.items()}); members.append(m.eval().requires_grad_(False))
    residual=torch.nn.Linear(128,1); residual.load_state_dict({k:torch.tensor(v) for k,v in snapshot['residual'].items()})
    residual.eval().requires_grad_(False)
    budget={'used':0,'limit':256*1024*1024}; buffers={a:RecordBuffer(budget) for a in (*ARMS,'proposals','priors')}
    active={}; proposal_cpu=build_cpu=0; cache={}
    try:
        for src in rows:
            sid=src['source_id']; components=[[],[],[]]; descriptions=[]
            for event,text in enumerate(src['events']):
                active=dict(phase='proposal',source_id=sid,event=event); begin=time.process_time_ns()
                keys=[slot_text(text,src['names'],j) for j in range(3)]
                for k in keys:
                    if k not in cache:
                        require(len(cache)<4096,'feature capacity'); cache[k]=torch.tensor(lexical_vector(k))
                x=torch.stack([cache[k] for k in keys])
                with torch.inference_mode(): scores=(torch.stack([m(x) for m in members])+residual(x).squeeze(-1)[None]).tolist()
                elapsed=time.process_time_ns()-begin; proposal_cpu+=elapsed
                buffers['proposals'].append(dict(source_id=sid,event=event,scores=scores,cpu_ns=elapsed,returned=elapsed<=100_000_000))
                require(elapsed<=100_000_000,'proposal CPU budget exhausted')
                for m,s in enumerate(scores): components[m].append(list(pair_law(s,cal['selected'])[1]))
                descriptions.append(describe(text,src['names']))
            begin=time.process_time_ns()
            oldrow=dict(source_id=sid,query=src['query'],components=components,weights=[1/3]*3,
                keys=[digest([t,src['names'],model,calibration]) for t in src['events']])
            old=construct(oldrow,model,calibration,scope='role-program-research')
            binding=dict(source=digest([src,descriptions]),model=model,calibration=calibration,scope='role-program-research',generation=3)
            laws=[[math.fsum(components[m][i][j] for m in range(3))/3 for j in range(3)] for i in range(len(descriptions))]
            head=RoleProgramBelief(src['query'],descriptions,laws,binding)
            uniform=RoleProgramBelief(src['query'],descriptions,[(1/3,)*3]*len(laws),binding,prior='uniform')
            independent=BeliefProblem(3,src['query'],head.laws,binding)
            build_cpu+=time.process_time_ns()-begin
            buffers['priors'].append(dict(source_id=sid,old=oldrow,descriptions=descriptions,binding=binding,
                head_priors=head.priors,uniform_priors=uniform.priors,
                identities=dict(old=old.identity,head=head.identity,uniform=uniform.identity,independent=independent.identity)))
            order=list(ARMS); random.Random(SEED+int(hashlib.sha256(sid.encode()).hexdigest()[:8],16)).shuffle(order)
            def reveal(e): return PAIRS.index(operation(src['events'][e],src['names']))
            for arm in order:
                active=dict(phase='execute',source_id=sid,arm=arm);begin=time.process_time_ns()
                if arm=='exact_reverse':
                    holder=src['query']
                    for text in reversed(src['events']):
                        a,b=operation(text,src['names']);holder=b if holder==a else a if holder==b else holder
                    result=dict(holder=holder,text=('amber','blue','coral')[holder],probabilities=[float(j==holder) for j in range(3)],
                                checks=[],decisions=[],route=None,problem_sha256=old.identity)
                elif arm=='uniform_probe': result=probe(uniform,reveal)
                else:
                    problem=independent if arm=='independent_role_two' else uniform if arm.startswith('program_uniform_') else head if arm.startswith('program_') else old
                    mode='verify_all_unique' if arm=='verify_all_inputs' else 'no_checks' if arm.endswith('none') else 'one_step' if arm.endswith('one') else 'two_step'
                    result=execute(problem,mode,reveal)
                result.update(arm=arm,source_id=sid,cpu_ns=time.process_time_ns()-begin,semantic_certificate=False,
                    depth2_requested=arm in ('old_two','independent_role_two','program_head_two','program_uniform_two'))
                buffers[arm].append(result)
    except Exception as error:
        write_once(root/'failure.json',dict(active=active,error=str(error),type=type(error).__name__,evidence=getattr(error,'evidence',None),complete=False)); raise
    finally:
        write_once(root/'streams.json',{a:b.write_once(root/(a+'.json')) for a,b in buffers.items()})
    targets={}
    for src in rows:
        state=list(range(3))
        for text in src['events']: a,b=operation(text,src['names']);state[a],state[b]=state[b],state[a]
        targets[src['source_id']]=state[src['query']]
    write_once(root/'targets.json',targets)
    byid={r['source_id']:r for r in rows}; summary={}
    for split in ('test','diagnostic_replay','retention'):
        summary[split]={}
        for arm in ARMS:
            sub=[r for r in buffers[arm] if byid[r['source_id']]['split']==split]
            correct=sum(r['holder']==targets[r['source_id']] for r in sub); answered=sum(r['holder'] is not None for r in sub);checks=sum(len(r['checks']) for r in sub)
            deep=sum(r['depth2_requested'] for r in sub)
            summary[split][arm]=dict(cases=len(sub),correct=correct,answered=answered,checks=checks,deep=deep,
                utility=(2*correct-answered-.02*checks-.002*deep)/len(sub),cpu_ns=sum(r['cpu_ns'] for r in sub))
    write_once(root/'results.json',dict(profile=PROFILE,summary=summary,proposal_cpu_ns=proposal_cpu,
        build_cpu_ns=build_cpu,cpu_before_audit_ns=time.process_time_ns()-started,no_new_fit=True,new_pretrained_forward=False,
        independent_sources=False,standalone_lifecycle_allocation_complete=False,production_promotion_permitted=False))
    from fbsde_role_audit import audit
    write_once(root/'audit.json',audit(root,source))
    write_once(root/'completion.json',dict(cpu_through_audit_ns=time.process_time_ns()-started,excludes_startup_and_final_write=True))
