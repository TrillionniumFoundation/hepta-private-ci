"""Outcome-vs-model depth-teacher factorial study through the existing entry.

Frozen lexical encoder/semantic snapshot; generated verifier-labelled text, NOT
human outcomes or new pretrained inference. All pilot, teacher, selector, training,
verification and recording work is retained; utility prices are not CPU prices.
"""
import hashlib
import math
from pathlib import Path
import random
import time
from four_gate_common import digest, require, write_once, strict_loads
from fbsde_tracking import lexical_vector, slot_text, make_gate
from fbsde_tracking_records import RecordBuffer
from fbsde_tracking_control import pair_law
from fbsde_depth_policy import features, scalar_score
from fbsde_depth_data import construct
from fbsde_planning_workspace import PlanningWorkspace
from fbsde_outcome_data import PROFILE, SEED, FRAMES, PER_FRAME, generate, operation, target, reward
from fbsde_outcome_policy import PRICE, TEACHERS, ARMS, execute, fit, select


def run(output, evidence_dir):
    import torch
    root=Path(output); root.mkdir(parents=True,exist_ok=False); source=Path(evidence_dir)
    start=time.process_time_ns(); torch.set_num_threads(2)
    def read(name):
        path=source/(name+'.json')
        require(path.is_file() and not path.is_symlink() and path.stat().st_size<32*1024*1024,'bounded source')
        return strict_loads(path.read_bytes())
    # Independently check the original complete saved model study before reuse.
    from fbsde_depth_audit import audit
    original_audit=audit(source)
    snapshot=read('candidate-weights'); calibration=read('calibration'); old_router=read('router')
    model_id=digest(snapshot); cal_id=digest(calibration); rows=generate()
    write_once(root/'plan.json', {'profile':PROFILE,'seed':SEED,'frames':FRAMES,'per_frame':PER_FRAME,
        'arms':ARMS,'route_steps':160,'route_seed':982451653,'route_lr':.01,
        'gain_price':PRICE,'check_cost':.02,'max_checks':2,'cpu_limit_ns':100_000_000,
        'model_sha256':model_id,'calibration_sha256':cal_id,
        'source_files':{n:hashlib.sha256((source/(n+'.json')).read_bytes()).hexdigest()
                        for n in ('candidate-weights','calibration','router')},
        'source_code':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in Path(__file__).parent.glob('fbsde_outcome*.py')},
        'teacher_is_simulator_outcome_not_human':True,'same_process_verifier_not_OS_isolation':True,
        'generated_before_scores':True,'new_pretrained_forward':False,'production_promotion_permitted':False})
    write_once(root/'inputs.json',rows); write_once(root/'frozen-model.json',snapshot)
    write_once(root/'frozen-calibration.json',calibration); write_once(root/'parent-router.json',old_router)
    write_once(root/'parent-audit.json',original_audit)
    write_once(root/'frozen-source-results.json',read('results'))
    members=[]
    for state in snapshot['base']:
        m=make_gate(torch); m.load_state_dict({k:torch.tensor(v) for k,v in state.items()},strict=True)
        members.append(m.eval().requires_grad_(False))
    residual=torch.nn.Linear(128,1)
    residual.load_state_dict({k:torch.tensor(v) for k,v in snapshot['residual'].items()},strict=True)
    residual.eval().requires_grad_(False)
    budget={'used':0,'limit':256*1024*1024}; buffers={k:RecordBuffer(budget) for k in
        ('proposals','priors','teacher-predictions','teacher-train','teacher-selection',*ARMS)}
    jobs=[]; vectors={}; proposal_cpu=0; construction_cpu=0; targets={}; active={}
    def problem_for(src):
        nonlocal proposal_cpu,construction_cpu
        components=[[],[],[]]
        for i,text in enumerate(src['events']):
            begin=time.process_time_ns()
            keys=[slot_text(text,src['names'],j) for j in range(3)]
            for key in keys:
                if key not in vectors:
                    require(len(vectors)<4096,'bounded lexical cache')
                    vectors[key]=torch.tensor(lexical_vector(key))
            x=torch.stack([vectors[k] for k in keys])
            with torch.inference_mode(): scores=(torch.stack([m(x) for m in members])+residual(x).squeeze(-1)[None]).tolist()
            cpu=time.process_time_ns()-begin; proposal_cpu+=cpu
            buffers['proposals'].append({'source_id':src['source_id'],'event':i,'scores':scores,
                'cpu_ns':cpu,'returned':cpu<=100_000_000,'text_sha256':digest(text)})
            require(cpu<=100_000_000,'proposal CPU budget exhausted')
            for m,s in enumerate(scores):components[m].append(list(pair_law(s,calibration['selected'])[1]))
        prior={'source_id':src['source_id'],'query':src['query'],'components':components,'weights':[1/3]*3,
               'keys':[digest([t,src['names'],model_id,cal_id]) for t in src['events']]}
        begin=time.process_time_ns(); p=construct(prior,model_id,cal_id,scope='outcome-depth-research')
        construction_cpu+=time.process_time_ns()-begin
        buffers['priors'].append({**prior,'binding':p.binding,'problem_sha256':p.identity})
        return p
    def reveal(src,event):
        # Only a previously CHOSEN action accesses this simulator operation label.
        return ((0,1),(0,2),(1,2)).index(operation(src['events'][event],src['names']))
    try:
        teacher={}
        for split in ('train','selection'):
            begin=time.process_time_ns(); teacher[split]=[]
            for src in [r for r in rows if r['split']==split]:
                active={'phase':'teacher','source_id':src['source_id']}; p=problem_for(src)
                shallow=execute(p,'one_step',lambda event:reveal(src,event))
                deep=execute(p,'two_step',lambda event:reveal(src,event))
                before_label={'source_id':src['source_id'],'shallow':shallow,'deep':deep}
                # Saved predictions precede source scoring in the logical journal.
                buffers['teacher-predictions'].append(before_label)
                prediction_pin=digest(before_label)
                with PlanningWorkspace(p) as w:
                    one=w.solve(horizon=1); x=features(p,(),one,workspace=w)
                label=target(src)
                record={**before_label,'prediction_sha256':prediction_pin,'features':x,'label':label,
                    'model_gain':deep['decisions'][0]['plan']['value']-shallow['decisions'][0]['plan']['value'],
                    'outcome_gain':reward(deep,label)-reward(shallow,label)}
                buffers['teacher-'+split].append(record); teacher[split].append(record)
            jobs.append({'phase':'teacher_'+split,'cpu_ns':time.process_time_ns()-begin})
        routers={k:fit(torch,teacher['train'],k) for k in TEACHERS}
        require(routers['model']['initial_sha256']==routers['outcome']['initial_sha256'],'matched initialization')
        selector_start=time.process_time_ns(); selectors={}
        for trained in TEACHERS:
            scores=[scalar_score(routers[trained]['state'],r['features']) for r in teacher['selection']]
            for objective in TEACHERS:selectors[trained+'_'+objective]=select(teacher['selection'],scores,objective)
        selectors['confidence_outcome']=select(teacher['selection'],[1-r['features'][0] for r in teacher['selection']],'outcome')
        selectors['best_fixed']=2 if math.fsum(r['outcome_gain']-PRICE for r in teacher['selection'])>0 else 1
        jobs.append({'phase':'selector','cpu_ns':time.process_time_ns()-selector_start})
        policy={'routers':routers,'selectors':selectors,'new_frames_not_used_in_fit_or_selection':True}
        policy_pin=digest(policy); write_once(root/'policy.json',policy)
        for src in [r for r in rows if r['split'] in ('test','retention')]:
            active={'phase':'evaluate','source_id':src['source_id']}; p=problem_for(src)
            order=list(ARMS);random.Random(SEED+int(hashlib.sha256(src['source_id'].encode()).hexdigest()[:8],16)).shuffle(order)
            for arm in order:
                active['arm']=arm; bundle=None
                if arm=='numeric_router':
                    bundle={'binding':p.binding,'state':old_router['fit']['state'],'threshold':old_router['complete']['selected']}
                elif arm in selectors and arm!='best_fixed':
                    bundle={'binding':p.binding,'threshold':selectors[arm]['selected'],
                            'state':None if arm=='confidence_outcome' else routers[arm.split('_')[0]]['state']}
                if arm=='exact_reverse':
                    begin=time.process_time_ns(); holder=src['query']
                    for text in reversed(src['events']):
                        a,b=operation(text,src['names']); holder=b if holder==a else a if holder==b else holder
                    result={'arm':arm,'holder':holder,'text':('amber','blue','coral')[holder],
                            'checks':[],'decisions':[],'route':None,'probabilities':[float(j==holder) for j in range(3)],
                            'depth2_requested':False,'cpu_ns':time.process_time_ns()-begin,'problem_sha256':p.identity}
                else:
                    effective=('two_step' if selectors['best_fixed']==2 else 'one_step') if arm=='best_fixed' else arm
                    result=execute(p,effective,lambda event:reveal(src,event),bundle)
                    result['effective_arm']=effective; result['arm']=arm
                buffers[arm].append({**result,'source_id':src['source_id'],'policy_sha256':policy_pin})
        require(digest(policy)==policy_pin,'evaluation changed policy')
    except Exception as error:
        write_once(root/'failure.json',{'active':active,'type':type(error).__name__,'error':str(error),
            'evidence':getattr(error,'evidence',None),'complete':False}); raise
    finally:
        write_once(root/'streams.json',{name:b.write_once(root/(name+'.json')) for name,b in buffers.items()})
    # Evaluate all test labels only after every candidate output has been sealed.
    targets={r['source_id']:target(r) for r in rows if r['split'] in ('test','retention')}
    write_once(root/'targets.json',targets); summary={}; source_by_id={r['source_id']:r for r in rows}
    for split in ('test','retention'):
        summary[split]={}
        for arm in ARMS:
            sub=[r for r in buffers[arm] if source_by_id[r['source_id']]['split']==split]
            correct=sum(r['holder']==targets[r['source_id']] for r in sub); answered=sum(r['holder'] is not None for r in sub)
            checks=sum(len(r['checks']) for r in sub); escalations=sum(r['depth2_requested'] for r in sub)
            summary[split][arm]={'cases':len(sub),'correct':correct,'answered':answered,'checks':checks,'escalations':escalations,
                'utility':(2*correct-answered-.02*checks-PRICE*escalations)/len(sub),
                'cpu_ns':sum(r['cpu_ns'] for r in sub),'nodes':sum(d['nodes'] for r in sub for d in r['decisions'])}
    result={'profile':PROFILE,'summary':summary,'jobs_once':jobs,'shared_proposal_cpu_ns':proposal_cpu,
        'belief_build_cpu_ns':construction_cpu,'cached_lexical_vectors':len(vectors),'router_fit_cpu_ns':sum(r['cpu_ns'] for r in routers.values()),
        'cpu_envelope_before_audit_ns':time.process_time_ns()-start,'unallocated_shared_costs_present':True,'job_components_may_overlap':True,
        'pretrained_execution':False,'risk_certified':False,'source_independence_authenticated':False,
        'production_promotion_permitted':False}
    write_once(root/'results.json',result)
    from fbsde_outcome_audit import audit as audit_outcomes
    write_once(root/'audit.json',audit_outcomes(root))
    write_once(root/'completion.json',{'cpu_through_audit_ns':time.process_time_ns()-start,
        'prior_model_fit_is_recorded_not_reexecuted':True,'excludes_import_startup_and_final_write':True})
    return result
