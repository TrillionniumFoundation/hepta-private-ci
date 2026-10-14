"""Freeze shared Heads, then measure novel syntax and input-tied verification.

No new reviewer, pretrained run or native owner. Existing finite BSDE planner,
proposal/plan limits, exact and myopic controls are retained. Shadow research only.
"""
import math
import random
import time
from pathlib import Path
from four_gate_common import digest, require, write_once
from four_gate_capture import tensor_digest
from fbsde_tracking import make_gate, lexical_vector, slot_text, training_rows, generated_cases, parse
from fbsde_tracking_control import BeliefProblem, fit_temperature, pair_law
from fbsde_tracking_control_study import decision, CALIBRATION_SEED
from fbsde_tracking_mixture import SharedHeadBelief
from fbsde_tracking_mixture_study import MEMBER_SEEDS
from fbsde_tracking_records import RecordBuffer
from fbsde_tracking_tied import InputTiedBelief
from fbsde_tracking_challenge import TEMPLATES, SEED, generate, task, input_keys

PROFILE='input_tied_challenge_v1'
SPECS={'single_no_checks':('single','posterior_no_checks'),
       'product_no_checks':('pooled','posterior_no_checks'),
       'shared_no_checks':('shared','posterior_no_checks'),
       'shared_myopic':('shared','myopic_verify'),'shared_ndu':('shared','ndu_two_step'),
       'tied_no_checks':('tied','posterior_no_checks'),'tied_myopic':('tied','myopic_verify'),
       'tied_ndu':('tied','ndu_two_step'),'verify_all':('shared','verify_all'),
       'exact_reverse':('pooled','exact_reverse')}


def run(output):
    import torch
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    start=time.process_time_ns();torch.set_num_threads(2)
    source={p.name:digest(p.read_text()) for p in Path(__file__).parent.glob('fbsde_tracking*.py')}
    write_once(output/'design.json',{'profile':PROFILE,'source_sha256':source,'templates':TEMPLATES,
        'test_seed':SEED,'per_family':24,'training_seed':32452843,'bootstrap_seeds':MEMBER_SEEDS,
        'steps':160,'lr':.01,'temperature_grid':[.25,.5,1.,2.,4.],'calibration_seed':CALIBRATION_SEED,
        'arms':SPECS,'max_checks':2,'check_cost':.02,'proposal_cpu_limit_ns':100_000_000,
        'source_kind':'newly_generated_unseen_template_stress_not_real_observation',
        'calibration_kind':'old_simulator_no_target_template_calibration',
        'fixed_before_target_predictions':True,'production_promotion_permitted':False})
    budget={'used':0,'limit':256*1024*1024};proposals=RecordBuffer(budget);priors=RecordBuffer(budget)
    outputs={a:RecordBuffer(budget) for a in SPECS};active={};jobs=[];members=[];common_cpu=0;build_cpu=0
    def identity(m):return digest({k:tensor_digest(v) for k,v in m.state_dict().items()})
    try:
        train=training_rows();x=torch.tensor([lexical_vector(s) for s,_ in train]);y=torch.tensor([v for _,v in train])
        for k,seed in enumerate((32452843,*MEMBER_SEEDS)):
            began=time.process_time_ns();torch.manual_seed(seed);m=make_gate(torch)
            idx=list(range(len(train)))
            if k:
                rng=random.Random(seed);idx=[]
                for _ in range(len(train)//3):
                    event=rng.randrange(len(train)//3);idx.extend(range(event*3,event*3+3))
            optim=torch.optim.AdamW(m.parameters(),lr=.01);first=None
            for step in range(160):
                optim.zero_grad();loss=torch.nn.functional.binary_cross_entropy_with_logits(m(x[idx]),y[idx])
                require(torch.isfinite(loss).item(),'nonfinite training loss')
                if first is None:first=float(loss.detach())
                loss.backward();optim.step()
                require(time.process_time_ns()-began<=15_000_000_000,'Head fit CPU budget exhausted')
            m.eval().requires_grad_(False);members.append(m)
            jobs.append({'seed':seed,'bootstrap_sha256':digest(idx),'initial_loss':first,
                'final_loss':float(loss.detach()),'cpu_ns':time.process_time_ns()-began,'weights_sha256':identity(m)})
        ids=[identity(m) for m in members];torch.save([m.state_dict() for m in members],output/'heads.pt')
        import hashlib
        write_once(output/'fit.json',{'jobs':jobs,'members':ids,'training_sha256':digest(train),
            'parameters':sum(sum(p.numel() for p in m.parameters()) for m in members),
            'heads_bytes_sha256':hashlib.sha256((output/'heads.pt').read_bytes()).hexdigest()})
        def logits(text,names):
            nonlocal common_cpu
            began=time.process_time_ns();slots=[slot_text(text,names,i) for i in range(3)]
            vec=torch.tensor([lexical_vector(s) for s in slots])
            with torch.inference_mode():scores=[m(vec).tolist() for m in members]
            require(all(all(type(v) is float and math.isfinite(v) for v in s) for s in scores),'finite logits')
            cpu=time.process_time_ns()-began;common_cpu+=cpu
            proposals.append({**active,'text':text,'names':list(names),'scores':scores,
                'slots_sha256':digest(slots),'vectors_sha256':tensor_digest(vec),
                'cpu_ns':cpu,'returned':cpu<=100_000_000})
            require(cpu<=100_000_000,'proposal CPU budget exhausted')
            return scores
        calibration=[]
        # Three-actor held-out simulator operations; no held-out family wording.
        for case in generated_cases(seed=CALIBRATION_SEED,count=72):
            old=parse(case['input'])
            if len(old['names'])!=3:continue
            for i,event in enumerate(old['events']):
                active={'phase':'calibration','source_id':case['source_id'],'event':i}
                calibration.append({'scores':logits(event['text'],old['names']),'pair':event['pair']})
        cal_begin=time.process_time_ns()
        temps=[fit_temperature([{'scores':r['scores'][m],'pair':r['pair']} for r in calibration]) for m in range(3)]
        write_once(output/'calibration.json',{'rows':calibration,'temperatures':temps,'cpu_ns':time.process_time_ns()-cal_begin})
        public=generate();write_once(output/'inputs.json',public)
        # No selection on observed error/disagreement; retain every registered case.
        for row in public:
            source_task=task(row);comp=[[] for _ in members]
            # Shared deterministic proposal on each actual event; repetition is
            # charged, not counted as an independent observation or extra evidence.
            for i,text in enumerate(row['events']):
                active={'phase':'evaluation','source_id':row['source_id'],'event':i}
                scores=logits(text,row['names'])
                for m,s in enumerate(scores):comp[m].append(pair_law(s,temps[m]['selected'])[1])
            binding={'source':digest(row),'model':digest(ids),'calibration':digest(temps),
                     'scope':'unseen-input-tied-research','generation':1}
            keys=input_keys(row,binding);began=time.process_time_ns()
            shared=SharedHeadBelief(3,row['query'],comp,[1/3]*3,binding)
            tied=InputTiedBelief(3,row['query'],comp,[1/3]*3,keys,binding)
            problems={'shared':shared,'tied':tied,'pooled':BeliefProblem(3,row['query'],shared.laws,binding),
                      'single':BeliefProblem(3,row['query'],comp[0],binding)}
            build_cpu+=time.process_time_ns()-began
            priors.append({'source_id':row['source_id'],'components':comp,'weights':[1/3]*3,'keys':keys,
                           'binding':binding,'problem_ids':{k:p.identity for k,p in problems.items()}})
            order=list(SPECS);random.Random(SEED+len(priors)).shuffle(order)
            for arm in order:
                kind,policy=SPECS[arm];active={'phase':'planning','source_id':row['source_id'],'arm':arm}
                result=decision(problems[kind],source_task,policy)
                outputs[arm].append({**result,'source_id':row['source_id']})
        require(ids==[identity(m) for m in members],'inference mutated frozen Head')
    except Exception as e:
        write_once(output/'failure.json',{'active':active,'type':type(e).__name__,'message':str(e),
            'budget_evidence':getattr(e,'evidence',None),'complete':False})
        raise
    finally:
        retention={n:r.write_once(output/(n+'.json')) for n,r in [('proposals',proposals),('priors',priors),*outputs.items()]}
        write_once(output/'retention.json',{'streams':retention,'payload_bytes':budget['used']})
    # Predictive arrays are sealed before final-label scoring. Same process, not
    # an independently authenticated observer or a future-time dataset.
    targets={}
    for row in public:
        t=task(row);state=list(range(3))
        for e in t['events']:
            a,b=e['pair'];state[a],state[b]=state[b],state[a]
        targets[row['source_id']]=state[t['query']]
    write_once(output/'targets.json',targets)
    summary={}
    for arm,rows in outputs.items():
        n=len(rows);correct=sum(r['holder']==targets[r['source_id']] for r in rows)
        answered=sum(r['holder'] is not None for r in rows);checks=sum(len(r['verifications']) for r in rows)
        brier=sum(sum((p-float(j==targets[r['source_id']]))**2 for j,p in enumerate(r['probabilities']))/2 for r in rows)/n
        summary[arm]={'cases':n,'correct':correct,'answered':answered,'checks':checks,
            'brier':brier,'mean_utility':(2*correct-answered-.02*checks)/n,'cpu_ns':sum(r['cpu_ns'] for r in rows)}
    result={'profile':PROFILE,'summary':summary,'shared_proposal_cpu_ns':common_cpu,'problem_build_cpu_ns':build_cpu,
        'cpu_before_audit_ns':time.process_time_ns()-start,'test_selected_on_errors':False,
        'standalone_lifecycle_available':False,'real_pretrained_executed':False,
        'general_reasoning_proved':False,'risk_calibrated':False,'production_promotion_permitted':False}
    write_once(output/'results.json',result)
    from fbsde_tracking_tied_audit import audit
    write_once(output/'arithmetic-audit.json',audit(output))
    write_once(output/'completion.json',{'cpu_through_audit_ns':time.process_time_ns()-start,
        'excludes_this_write_and_interpreter_startup':True,'production_promotion_permitted':False})
    return result
