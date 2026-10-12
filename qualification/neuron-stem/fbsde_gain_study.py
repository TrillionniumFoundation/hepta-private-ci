"""Outcome magnitude ablation, using the original executor and prepared gates.

Each arm pays its own pilot/continuation. Reuse is frozen semantic parameters,
not someone else's answer. Simulator truth is not human or future evidence.
"""
import hashlib
import math
from pathlib import Path
import random
import time
from four_gate_common import digest, require, strict_loads, write_once
from fbsde_outcome_audit import audit as audit_source
from fbsde_outcome_policy import ARMS as OLD_ARMS, PRICE, execute, select
from fbsde_gain_policy import OBJECTIVES, fit, counterexample
from fbsde_gain_data import PROFILE, SEED, FRAMES, generate, operation, target
from fbsde_depth_policy import scalar_score
from fbsde_depth_data import construct
from fbsde_tracking_control import pair_law
from fbsde_tracking import make_gate, lexical_vector, slot_text
from fbsde_prepared_gate import PreparedOutcomeGate
from fbsde_tracking_records import RecordBuffer

ARMS=OLD_ARMS+('frequency_half','frequency_selected','signed_half','signed_selected')


def run(output,evidence_dir):
    import torch
    root=Path(output); source=Path(evidence_dir);root.mkdir(parents=True,exist_ok=False)
    started=time.process_time_ns();torch.set_num_threads(2)
    def read(name):
        p=source/(name+'.json')
        require(p.is_file() and not p.is_symlink() and p.stat().st_size<64*1024*1024,'bounded source')
        return strict_loads(p.read_bytes())
    write_once(root/'source-audit.json',audit_source(source))
    snapshot=read('frozen-model');cal=read('frozen-calibration');old=read('policy');numeric=read('parent-router')
    train=read('teacher-train');selection=read('teacher-selection');rows=generate(read('inputs'))
    model_id=digest(snapshot);cal_id=digest(cal)
    write_once(root/'plan.json',{'profile':PROFILE,'seed':SEED,'frames':FRAMES,'arms':ARMS,
        'objectives':OBJECTIVES,'fit_seed':982451653,'fit_steps':160,'lr':.01,'price':PRICE,
        'verification_price':.02,'max_checks':2,'cpu_ns_limit':100_000_000,'max_nodes':20000,
        'weighted_loss':'sum(abs(gain-price)*BCE)/sum(abs(gain-price))',
        'model_sha256':model_id,'calibration_sha256':cal_id,'new_frames_before_first_score':True,
        'source_code':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('fbsde_gain*.py')},
        'parent_files':{n:hashlib.sha256((source/(n+'.json')).read_bytes()).hexdigest() for n in
            ('teacher-train','teacher-selection','policy','frozen-model','frozen-calibration','inputs')},
        'observations_are_generated_not_independent_humans':True,'production_promotion_permitted':False})
    write_once(root/'inputs.json',rows);write_once(root/'mechanism.json',counterexample())
    jobs=[]; fits={}
    for objective in OBJECTIVES:
        fits[objective]=fit(torch,train,objective)
        jobs.append({'phase':'fit','objective':objective,'cpu_ns':fits[objective]['cpu_ns']})
    require(len({r['initial_sha256'] for r in fits.values()})==1,'matched initialization')
    began=time.process_time_ns();selectors={}
    for objective,f in fits.items():
        selectors[objective]=select(selection,[scalar_score(f['state'],r['features']) for r in selection],'outcome')
    jobs.append({'phase':'selection','cpu_ns':time.process_time_ns()-began})
    policy={'fits':fits,'selectors':selectors,'parent_policy_sha256':digest(old)}
    pin=digest(policy);write_once(root/'policy.json',policy)
    context=dict(model=model_id,calibration=cal_id,scope='signed-gain-routing',generation=3)
    specs={};gates={};preparation=[]
    for arm in ARMS:
        if arm in ('no_checks','one_step','two_step','best_fixed','verify_all_unique','exact_reverse'):continue
        if arm.startswith(('frequency_','signed_')):
            objective=OBJECTIVES[0] if arm.startswith('frequency_') else OBJECTIVES[1]
            state=fits[objective]['state']; threshold=.5 if arm.endswith('_half') else selectors[objective]['selected']
        elif arm=='numeric_router': state=numeric['fit']['state'];threshold=numeric['complete']['selected']
        else:
            state=None if arm=='confidence_outcome' else old['routers'][arm.split('_')[0]]['state']
            threshold=old['selectors'][arm]['selected']
        specs[arm]={'state':state,'threshold':threshold}
        begin=time.process_time_ns()
        gates[arm]=PreparedOutcomeGate(state,threshold,context,kind='confidence' if state is None else 'learned')
        preparation.append({'arm':arm,'cpu_ns':time.process_time_ns()-begin,'identity':gates[arm].identity})
    write_once(root/'preparation.json',preparation)
    members=[]
    for state in snapshot['base']:
        m=make_gate(torch);m.load_state_dict({k:torch.tensor(v) for k,v in state.items()},strict=True)
        members.append(m.eval().requires_grad_(False))
    residual=torch.nn.Linear(128,1)
    residual.load_state_dict({k:torch.tensor(v) for k,v in snapshot['residual'].items()},strict=True)
    residual.eval().requires_grad_(False)
    budget={'used':0,'limit':256*1024*1024};buffers={n:RecordBuffer(budget) for n in ('proposals','priors',*ARMS)}
    cache={};proposal_cpu=build_cpu=0;active={}
    try:
        for src in rows:
            active={'phase':'proposal','source_id':src['source_id']};components=[[],[],[]]
            for event,text in enumerate(src['events']):
                begin=time.process_time_ns();keys=[slot_text(text,src['names'],j) for j in range(3)]
                for key in keys:
                    if key not in cache:
                        require(len(cache)<4096,'bounded feature cache');cache[key]=torch.tensor(lexical_vector(key))
                x=torch.stack([cache[k] for k in keys])
                with torch.inference_mode():scores=(torch.stack([m(x) for m in members])+residual(x).squeeze(-1)[None]).tolist()
                elapsed=time.process_time_ns()-begin;proposal_cpu+=elapsed
                buffers['proposals'].append({'source_id':src['source_id'],'event':event,'text_sha256':digest(text),
                    'scores':scores,'cpu_ns':elapsed,'returned':elapsed<=100_000_000})
                require(elapsed<=100_000_000,'proposal CPU budget exhausted')
                for m,s in enumerate(scores):components[m].append(list(pair_law(s,cal['selected'])[1]))
            prior={'source_id':src['source_id'],'query':src['query'],'components':components,'weights':[1/3]*3,
                'keys':[digest([t,src['names'],model_id,cal_id]) for t in src['events']]}
            begin=time.process_time_ns();problem=construct(prior,model_id,cal_id,scope=context['scope'])
            request=dict(source=digest(prior),**context);build_cpu+=time.process_time_ns()-begin
            buffers['priors'].append({**prior,'problem_sha256':problem.identity,'binding':problem.binding})
            order=list(ARMS);random.Random(SEED+int(hashlib.sha256(src['source_id'].encode()).hexdigest()[:8],16)).shuffle(order)
            def reveal(event):return ((0,1),(0,2),(1,2)).index(operation(src['events'][event],src['names']))
            for arm in order:
                active={'phase':'evaluation','source_id':src['source_id'],'arm':arm};begin=time.process_time_ns()
                if arm=='exact_reverse':
                    holder=src['query']
                    for text in reversed(src['events']):
                        a,b=operation(text,src['names']);holder=b if holder==a else a if holder==b else holder
                    result={'holder':holder,'text':('amber','blue','coral')[holder],'checks':[],'decisions':[],
                        'probabilities':[float(j==holder) for j in range(3)],'route':None,'depth2_requested':False,
                        'problem_sha256':problem.identity}
                else:
                    effective=('two_step' if old['selectors']['best_fixed']==2 else 'one_step') if arm=='best_fixed' else (
                        'outcome_outcome' if arm.startswith(('frequency_','signed_')) else arm)
                    result=execute(problem,effective,reveal,prepared=gates.get(arm),context=request if arm in gates else None)
                result.update(arm=arm,source_id=src['source_id'],cpu_ns=time.process_time_ns()-begin,policy_sha256=pin)
                buffers[arm].append(result)
        require(digest(policy)==pin,'evaluation changed frozen policy')
    except Exception as error:
        write_once(root/'failure.json',{'active':active,'error':str(error),'type':type(error).__name__,
            'evidence':getattr(error,'evidence',None),'complete':False});raise
    finally:
        write_once(root/'streams.json',{k:b.write_once(root/(k+'.json')) for k,b in buffers.items()})
    targets={r['source_id']:target(r) for r in rows};write_once(root/'targets.json',targets)
    by_id={r['source_id']:r for r in rows};summary={}
    for split in ('test','retention'):
        summary[split]={}
        for arm in ARMS:
            sub=[r for r in buffers[arm] if by_id[r['source_id']]['split']==split]
            correct=sum(r['holder']==targets[r['source_id']] for r in sub);answered=sum(r['holder'] is not None for r in sub)
            checks=sum(len(r['checks']) for r in sub);deep=sum(r['depth2_requested'] for r in sub)
            summary[split][arm]={'cases':len(sub),'correct':correct,'answered':answered,'checks':checks,'deep':deep,
                'utility':(2*correct-answered-.02*checks-PRICE*deep)/len(sub),'cpu_ns':sum(r['cpu_ns'] for r in sub),
                'nodes':sum(d['nodes'] for r in sub for d in r['decisions'])}
    result={'profile':PROFILE,'summary':summary,'jobs_once':jobs,'proposal_cpu_ns':proposal_cpu,
        'belief_build_cpu_ns':build_cpu,'preparation_cpu_ns':sum(p['cpu_ns'] for p in preparation),
        'cpu_before_audit_ns':time.process_time_ns()-started,'component_jobs_may_overlap':False,
        'parent_teacher_costs_not_reexecuted':True,'unallocated_shared_costs':True,
        'new_pretrained_forward':False,'risk_certified':False,'production_promotion_permitted':False}
    write_once(root/'results.json',result)
    from fbsde_gain_audit import audit
    write_once(root/'audit.json',audit(root,source))
    write_once(root/'completion.json',{'cpu_through_audit_ns':time.process_time_ns()-started,
        'excludes_startup_and_final_write':True})
    return result
