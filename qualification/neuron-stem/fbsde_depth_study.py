"""Train a tiny computation router, then compare it on frozen semantic beliefs.

The teacher labels are extra MODEL value, not external task correctness. This
study cannot certify the approximate routing policy or general language risk.
"""
import hashlib
import math
from pathlib import Path
import random
import time
from four_gate_common import digest, require, write_once
from fbsde_tracking_control import pair_law, plan, TEMPERATURES
from fbsde_tracking_tied import InputTiedBelief
from fbsde_tracking_records import RecordBuffer
from fbsde_tracking_feedback import (load_base, validate_feedback, fit_candidates,
    states_json, candidate_scores, identity, PAIRS)
from fbsde_tracking_feedback_data import FAMILIAR, REPAIR, CALIBRATION, HELDOUT, local_rows, generate, task
from fbsde_tracking import lexical_vector, slot_text
from fbsde_depth_policy import (PROFILE, GAIN_PRICE, THRESHOLDS, features, fit_router,
    select_threshold, scalar_score, allocate)

MODES = ('no_checks','myopic','full','confidence','frozen','learned','learned_complete','confidence_complete','verify_all_unique','exact_reverse')


from fbsde_depth_data import numeric_inputs, construct

def teacher_row(row):
    problem = construct(row,'numerical-teacher','not-a-calibrated-posterior')
    one = plan(problem,horizon=1); two = plan(problem,horizon=2)
    require(two['value'] >= one['value']-1e-10, 'extra available computation decreased optimal value')
    return {'input':row,'features':features(problem,(),one),'gain':max(0.,two['value']-one['value']),
            'one':one,'two':two,'problem_sha256':problem.identity}


def execute(problem, public, mode, bundle):
    started = time.process_time_ns(); known = (); remaining = 2; routes = []; decisions = []; checks = []
    if mode == 'exact_reverse':
        t = task(public); holder = t['query']
        for event in reversed(t['events']):
            a,b = event['pair']; holder = b if holder == a else a if holder == b else holder
        distribution = [float(i==holder) for i in range(3)]
    else:
        for _ in range(len(problem.laws)+1):
            available = problem.available_events(known)
            if mode == 'verify_all_unique' and available:
                action = f'verify:{available[0]}'
            elif mode in ('no_checks','verify_all_unique'):
                d = plan(problem,known,horizon=0); decisions.append(d); action = d['action']
            else:
                d, route = allocate(problem,known,remaining,mode,bundle)
                decisions.append(d); routes.append(route); action = d['action']
            if not action.startswith('verify:'):
                holder = None if action == 'abstain' else int(action.split(':')[1]); break
            event = int(action.split(':')[1])
            require(event in available and (mode=='verify_all_unique' or remaining>0),'legal selected verification')
            # Only this action reveals this source operation. Not an OS boundary.
            original = task(public)['events'][event]; outcome = PAIRS.index(tuple(original['pair']))
            checks.append({'event':event,'outcome':outcome,'source_event_sha256':digest(original['text']),
                           'known_before':known,'modeled_cost':.02})
            known = tuple(sorted(known+((event,outcome),))); remaining -= 1
        else: raise ValueError('unfinished required decision')
        distribution = problem.marginal(known)
    text = 'Insufficient evidence; abstain.' if holder is None else ('amber','blue','coral')[holder]
    return {'source_id':public['source_id'],'mode':mode,'holder':holder,'text':text,
        'probabilities':distribution,'verifications':checks,'routes':routes,'decisions':decisions,
        'cpu_ns':time.process_time_ns()-started,'problem_sha256':problem.identity,
        'production_promotion_permitted':False}


def run(output, evidence_dir):
    import torch
    output = Path(output); output.mkdir(parents=True,exist_ok=False)
    start = time.process_time_ns(); torch.set_num_threads(2)
    write_once(output/'plan.json', {'profile':PROFILE,'modes':MODES,'teacher_counts':[256,64,64],
        'teacher_seeds':[15485863,15485917,15485933],'router_seed':982451653,
        'selection_profiles':['registered_coarse_v1','validation_breakpoints_v2'],
        'complete_grid_added_after_coarse_run_but_uses_selection_rows_only':True,
        'router_steps':160,'router_lr':.01,'gain_price':GAIN_PRICE,'thresholds':THRESHOLDS,
        'max_checks':2,'check_cost':.02,'cpu_limit_ns':100_000_000,
        'semantic_evaluation':'inherited_feedback_frames_exploratory_reuse',
        'router_teacher':'label_free_numerical_beliefs_not_real_world_rewards',
        'sources':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('fbsde_depth*.py')},
        'production_promotion_permitted':False})
    budget = {'used':0,'limit':256*1024*1024}
    proposals = RecordBuffer(budget); priors = RecordBuffer(budget); rows = {m:RecordBuffer(budget) for m in MODES}
    teachers = {s:RecordBuffer(budget) for s in ('train','selection','model_test')}
    active = {}; jobs = []; model_test = []; shared_cpu = build_cpu = 0
    try:
        for split,seed,count in zip(teachers,(15485863,15485917,15485933),(256,64,64)):
            began = time.process_time_ns()
            for item in numeric_inputs(seed,count,split):
                active = {'phase':'teacher','source_id':item['source_id']}
                teachers[split].append(teacher_row(item))
            jobs.append({'phase':'teacher_'+split,'cpu_ns':time.process_time_ns()-began,'rows':count})
        fit = fit_router(torch,list(teachers['train'])); jobs.append({'phase':'router_fit','cpu_ns':fit['cpu_ns']})
        began = time.process_time_ns()
        selected = select_threshold(list(teachers['selection']),fit['state'],'learned')
        heuristic = select_threshold(list(teachers['selection']),fit['state'],'confidence')
        complete = select_threshold(list(teachers['selection']),fit['state'],'learned','validation_breakpoints_v2')
        complete_heuristic = select_threshold(list(teachers['selection']),fit['state'],'confidence','validation_breakpoints_v2')
        jobs.append({'phase':'router_selection','cpu_ns':time.process_time_ns()-began})
        write_once(output/'router.json',{'fit':fit,'selected':selected,'heuristic':heuristic,'complete':complete,'complete_heuristic':complete_heuristic})
        for item in teachers['model_test']:
            score = scalar_score(fit['state'],item['features']); deep = score >= selected['selected']
            model_test.append({'source_id':item['input']['source_id'],'score':score,'deeper':deep,
                'gain':item['gain'],'missed_model_value':0. if deep else item['gain'],
                'complete_deeper':score>=complete['selected'],
                'complete_missed_model_value':0. if score>=complete['selected'] else item['gain']})
        members,parent = load_base(torch,evidence_dir); write_once(output/'base-fit.json',parent)
        feedback = local_rows(FAMILIAR+REPAIR); before = []
        def vector(text,names): return torch.tensor([lexical_vector(slot_text(text,names,j)) for j in range(3)])
        for i,r in enumerate(feedback):
            with torch.inference_mode(): raw = [m(vector(r['text'],r['names'])).tolist() for m in members]
            before.append({'index':i,'source':{k:r[k] for k in ('text','names','source_id')},'scores':raw,'phase':'before_feedback'})
        write_once(output/'before-feedback.json',before)
        receipts = [{'source':p['source'],'pair':r['pair'],'prediction_sha256':digest(p),
                     'observer':'simulator_source_verifier','sequence':2*i+1} for i,(p,r) in enumerate(zip(before,feedback))]
        validate_feedback(receipts,before,{digest(r['text']) for r in local_rows(HELDOUT)})
        write_once(output/'feedback.json',receipts)
        models,adapt_jobs = fit_candidates(torch,members,receipts)
        snapshot = states_json(models); snapshot_id = digest(snapshot)
        write_once(output/'candidate-weights.json',snapshot)
        write_once(output/'adaptation.json',adapt_jobs)
        def predict(text,names):
            nonlocal shared_cpu
            began = time.process_time_ns(); x = vector(text,names)
            with torch.inference_mode(): scores = candidate_scores(torch,'residual',models,x).tolist()
            cpu = time.process_time_ns()-began; shared_cpu += cpu
            proposals.append({**active,'text':text,'names':list(names),'scores':scores,'cpu_ns':cpu,'returned':cpu<=100_000_000})
            require(cpu<=100_000_000,'proposal CPU budget exhausted')
            return scores
        cal = []
        for r in local_rows(CALIBRATION):
            active = {'phase':'calibration','source_id':r['source_id']}
            cal.append({**r,'scores':predict(r['text'],r['names'])})
        grid = []
        for t in TEMPERATURES:
            p = [math.fsum(pair_law(s,t)[1][PAIRS.index(tuple(r['pair']))] for s in r['scores'])/3 for r in cal]
            grid.append({'temperature':t,'nll':-math.fsum(math.log(max(q,1e-300)) for q in p)/len(p)})
        temperature = min(grid,key=lambda x:(x['nll'],x['temperature']))['temperature']
        calibration = {'rows':cal,'grid':grid,'selected':temperature}; cal_id = digest(calibration)
        write_once(output/'calibration.json',calibration)
        public = generate(); write_once(output/'inputs.json',public)
        for i,src in enumerate(public):
            active = {'phase':'evaluation','source_id':src['source_id']}; components = [[],[],[]]
            for e,text in enumerate(src['events']):
                active['event'] = e; raw = predict(text,src['names'])
                for m,s in enumerate(raw): components[m].append(list(pair_law(s,temperature)[1]))
            prior = {'source_id':src['source_id'],'query':src['query'],'components':components,
                     'weights':[1/3]*3,'keys':[digest([t,src['names'],snapshot_id,cal_id]) for t in src['events']]}
            began = time.process_time_ns(); problem = construct(prior,snapshot_id,cal_id)
            build_cpu += time.process_time_ns()-began
            bundle = {'model':snapshot_id,'calibration':cal_id,
                'context':{'source':digest(prior),'model':snapshot_id,'calibration':cal_id,'scope':'depth-research','generation':3},
                'problem_binding':problem.binding,'state':fit['state'],'initial':fit['initial'],
                'threshold':selected['selected'],'confidence_threshold':heuristic['selected'],
                'complete_threshold':complete['selected'],'complete_confidence_threshold':complete_heuristic['selected']}
            priors.append({**prior,'model':snapshot_id,'calibration':cal_id,'bundle':bundle,'problem_sha256':problem.identity})
            order = list(MODES); random.Random(32452867+i).shuffle(order)
            for mode in order:
                active = {'phase':'planning','source_id':src['source_id'],'mode':mode}
                rows[mode].append(execute(problem,src,mode,bundle))
        require(snapshot_id==digest(states_json(models)) and [identity(m) for m in members]==parent['members'],
                'inference changed immutable models')
    except Exception as error:
        write_once(output/'failure.json', {'active':active,'type':type(error).__name__,'error':str(error),
            'evidence':getattr(error,'evidence',None),'complete':False}); raise
    finally:
        streams = {n:r.write_once(output/(n+'.json')) for n,r in
                   [('proposals',proposals),('priors',priors),*rows.items(),*[(f'teacher-{s}',v) for s,v in teachers.items()]]}
        write_once(output/'retention.json',{'streams':streams,'bytes':budget['used']})
    targets = {}
    for src in public:
        state = list(range(3)); t = task(src)
        for event in t['events']:
            a,b = event['pair']; state[a],state[b] = state[b],state[a]
        targets[src['source_id']] = state[src['query']]
    write_once(output/'targets.json',targets); write_once(output/'model-test.json',model_test)
    split_of = {r['source_id']:r['split'] for r in public}; summary = {}
    for split in ('known_replay','heldout'):
        summary[split] = {}
        for mode,records in rows.items():
            sub = [r for r in records if split_of[r['source_id']]==split]
            correct = sum(r['holder']==targets[r['source_id']] for r in sub)
            answered = sum(r['holder'] is not None for r in sub); checks = sum(len(r['verifications']) for r in sub)
            summary[split][mode] = {'cases':len(sub),'correct':correct,'answered':answered,'checks':checks,
                'utility':(2*correct-answered-.02*checks)/len(sub),'cpu_ns':sum(r['cpu_ns'] for r in sub),
                'depth2_calls':sum(q['selected_depth']==2 for r in sub for q in r['routes']),
                'planner_nodes':sum(q['planner_nodes'] for r in sub for q in r['routes'])+
                    sum(d['nodes'] for r in sub if not r['routes'] for d in r['decisions'])}
    result = {'profile':PROFILE,'summary':summary,'router_parameters':fit['parameters'],
        'jobs_once':jobs,'adaptation_jobs_once':adapt_jobs,'shared_proposal_cpu_ns':shared_cpu,
        'belief_build_cpu_ns':build_cpu,'cpu_before_audit_ns':time.process_time_ns()-start,
        'model_test_deep_calls':sum(r['deeper'] for r in model_test),
        'model_test_complete_deep_calls':sum(r['complete_deeper'] for r in model_test),
        'model_test_complete_missed_value':math.fsum(r['complete_missed_model_value'] for r in model_test)/len(model_test),
        'model_test_missed_value':math.fsum(r['missed_model_value'] for r in model_test)/len(model_test),
        'risk_certified':False,'equal_actual_cost_claimed':False,'real_pretrained_executed':False,
        'unallocated_common_work_present':True,'production_promotion_permitted':False}
    write_once(output/'results.json',result)
    from fbsde_depth_audit import audit
    write_once(output/'audit.json',audit(output))
    write_once(output/'completion.json',{'cpu_through_audit_ns':time.process_time_ns()-start,
        'excludes_startup_and_final_write':True,'production_promotion_permitted':False})
    return result
