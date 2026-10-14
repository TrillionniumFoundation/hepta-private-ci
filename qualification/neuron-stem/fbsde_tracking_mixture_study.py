"""Shared Encoder + three small Heads; common-Head versus product-law control.

Only simulator operations fit/temperature-calibrate the Heads. The uniform member
prior is declared, not a calibrated posterior over all possible world models.
Original BBH is evaluation only; this is a restricted-grammar research profile.
"""
import hashlib
import math
from pathlib import Path
import random
import time
from four_gate_common import digest, require, write_once
from fbsde_tracking import training_rows, generated_cases, make_gate, parse, slot_text
from fbsde_tracking_audit import reference
from fbsde_tracking_control import BeliefProblem, pair_law, fit_temperature
from fbsde_tracking_control_study import decision, CALIBRATION_SEED, TEST_SEED, COST
from fbsde_tracking_features import audit_features
from fbsde_tracking_mixture import SharedHeadBelief, PROFILE
from fbsde_tracking_records import RecordBuffer

MEMBER_SEEDS = (32453852, 32454861)
SPECS = {'single_no_checks': ('single','posterior_no_checks'),
         'single_ndu': ('single','ndu_two_step'),
         'pooled_no_checks': ('pooled','posterior_no_checks'),
         'pooled_ndu': ('pooled','ndu_two_step'),
         'joint_no_checks': ('joint','posterior_no_checks'),
         'joint_myopic': ('joint','myopic_verify'),
         'joint_ndu': ('joint','ndu_two_step'),
         'verify_all': ('joint','verify_all'),
         'exact_reverse': ('pooled','exact_reverse')}


def run(output, gate, store, *, tracking_source, publisher_root, started, fit):
    import torch
    from four_gate_capture import tensor_digest
    from fbsde_tracking_study import load_originals
    output = Path(output)
    write_once(output/'mixture-plan.json', {'schema':'hepta.tracking-mixture.plan.v1',
        'profile':PROFILE,'arms':SPECS,'member_seeds':MEMBER_SEEDS,'member_weights':[1/3]*3,
        'bootstrap_unit':'three actor rows of one simulated event','steps':160,'learning_rate':.01,
        'calibration_seed':CALIBRATION_SEED,'test_seed':TEST_SEED,'temperature_grid':[.25,.5,1.,2.,4.],
        'cost_per_check':COST,'max_checks':2,'cpu_limit_ns':100_000_000,
        'parent_gate_sha256':fit['gate_sha256'],'feature_binding':store.binding,'source':tracking_source,
        'conditional_event_independence_within_member':True,'member_prior_risk_calibrated':False,
        'same_source_repetitions_are_not_independent':True,'production_promotion_permitted':False})
    budget = {'used':0,'limit':256*1024*1024}
    proposals, priors = RecordBuffer(budget), RecordBuffer(budget)
    outputs = {arm:RecordBuffer(budget) for arm in SPECS}
    members, jobs, calibration = [gate], [], []
    active = {}; common_cpu = 0; parse_cpu = 0
    def weights_id(model):
        return digest({k:tensor_digest(v) for k,v in model.state_dict().items()})
    def logits(sentence,names):
        nonlocal common_cpu
        begin=time.process_time_ns();keys=[slot_text(sentence,names,i) for i in range(len(names))]
        vectors, receipt=store.get(keys,store.binding)
        with torch.inference_mode():scores=[m(vectors).tolist() for m in members]
        require(all(all(type(v) is float and math.isfinite(v) for v in row) for row in scores),'finite ensemble logits')
        cpu=time.process_time_ns()-begin
        proposals.append({**active,'scores':scores,'source_slot_texts':keys,'features':receipt,
                          'cpu_ns':cpu,'returned':cpu<=100_000_000})
        common_cpu+=cpu
        require(cpu<=100_000_000,'ensemble proposal CPU budget exhausted')
        return scores
    try:
        prepare_start=time.process_time_ns();training=training_rows()
        x=torch.stack([store.get([t],store.binding)[0][0] for t,_ in training])
        y=torch.tensor([v for _,v in training])
        # Bootstrap whole simulator events, not their three correlated actor labels.
        for seed in MEMBER_SEEDS:
            begin=time.process_time_ns();torch.manual_seed(seed);m=make_gate(torch,store.width)
            indices=[];rng=random.Random(seed)
            for _ in range(len(training)//3):
                event=rng.randrange(len(training)//3);indices.extend(range(3*event,3*event+3))
            optimizer=torch.optim.AdamW(m.parameters(),lr=.01);first=last=None
            for _ in range(160):
                optimizer.zero_grad();loss=torch.nn.functional.binary_cross_entropy_with_logits(m(x[indices]),y[indices])
                require(torch.isfinite(loss).item(),'finite ensemble fitting loss')
                if first is None:first=float(loss.detach())
                loss.backward();optimizer.step();last=float(loss.detach())
                require(time.process_time_ns()-begin<=15_000_000_000,'additional Head fit CPU budget exhausted')
            m.eval().requires_grad_(False);members.append(m)
            jobs.append({'seed':seed,'indices_sha256':digest(indices),'first_loss':first,'last_loss':last,
                         'cpu_ns':time.process_time_ns()-begin,'weights_sha256':weights_id(m)})
        member_ids=[weights_id(m) for m in members]
        torch.save([m.state_dict() for m in members],output/'mixture-gates.pt')
        member_fit={'members':member_ids,'jobs':jobs,'training_sha256':digest(training),
            'training_rows':len(training),'total_parameters':sum(sum(p.numel() for p in m.parameters()) for m in members),
            'additional_fit_and_features_cpu_ns':time.process_time_ns()-prepare_start,
            'weights_file_sha256':hashlib.sha256((output/'mixture-gates.pt').read_bytes()).hexdigest()}
        write_once(output/'mixture-fit.json',member_fit)
        for case in generated_cases(seed=CALIBRATION_SEED,count=72):
            task=parse(case['input'])
            for i,event in enumerate(task['events']):
                active.clear();active.update(split='calibration',source_id=case['source_id'],event_index=i)
                calibration.append({'scores':logits(event['text'],task['names']),'pair':event['pair']})
        begin=time.process_time_ns()
        temperatures=[fit_temperature([{'scores':r['scores'][m],'pair':r['pair']} for r in calibration])
                      for m in range(len(members))]
        cal={'rows':calibration,'temperatures':temperatures,'members':member_ids,
             'selection_cpu_ns':time.process_time_ns()-begin,'benchmark_rows_used':False}
        write_once(output/'mixture-calibration.json',cal)
        if tracking_source=='bbh':examples,inventory=load_originals(publisher_root or output/'publisher')
        else:examples,inventory=generated_cases(seed=TEST_SEED),{'generated':True}
        write_once(output/'mixture-inputs.json',[{k:v for k,v in r.items() if k!='target'} for r in examples])
        for case in examples:
            begin=time.process_time_ns();task=parse(case['input']);parse_cpu+=time.process_time_ns()-begin
            components=[[] for _ in members]
            for i,event in enumerate(task['events']):
                active.clear();active.update(split='evaluation',source_id=case['source_id'],event_index=i)
                scores=logits(event['text'],task['names'])
                for j,s in enumerate(scores):components[j].append(pair_law(s,temperatures[j]['selected'])[1])
            binding={'source':task['input_sha256'],'model':digest(member_ids),'calibration':digest(temperatures),
                     'scope':'tracking-mixture-research','generation':1}
            joint=SharedHeadBelief(len(task['names']),task['query'],components,[1/3]*3,binding)
            problems={'joint':joint,'single':BeliefProblem(joint.actors,joint.query,components[0],binding),
                      'pooled':BeliefProblem(joint.actors,joint.query,joint.laws,binding)}
            priors.append({'source_id':case['source_id'],'components':components,'weights':joint.weights,
                'binding':binding,'problem_ids':{k:p.identity for k,p in problems.items()}})
            order=list(SPECS);random.Random(104729+len(priors)).shuffle(order)
            for name in order:
                kind,policy=SPECS[name];problem=problems[kind]
                active.clear();active.update(split='evaluation',source_id=case['source_id'],
                    phase='planning',comparison_arm=name,problem_sha256=problem.identity)
                result=decision(problem,task,policy)
                histories=[()]
                for event in result['verifications']:
                    histories.append(tuple(sorted(histories[-1]+((event['event'],event['pair_index']),))))
                result.update(comparison_arm=name,source_id=case['source_id'],
                    member_weight_history=
                    [joint.member_posterior(h) for h in histories] if kind=='joint' else None)
                outputs[name].append(result)
        require(member_ids==[weights_id(m) for m in members],'ensemble mutated during evaluation')
    except Exception as error:
        write_once(output/'mixture-failure.json',{'type':type(error).__name__,'message':str(error),
            'active':active,'budget_evidence':getattr(error,'evidence',None),'complete':False,
            'production_promotion_permitted':False})
        raise
    finally:
        retention={name:rows.write_once(output/('mixture-'+name+'.json'))
                   for name,rows in [('proposals',proposals),('priors',priors),*outputs.items()]}
        write_once(output/'mixture-encoding.json',{'batches':store.batches,'records':store.records})
        write_once(output/'mixture-retention.json',{'streams':retention,'payload_bytes':budget['used']})
    # All prediction arrays are closed before final target scoring.
    targets={r['source_id']:r['target'] if 'target' in r else reference(r['input']) for r in examples}
    write_once(output/'mixture-targets.json',targets)
    summary={}
    for arm,rows in outputs.items():
        correct=answered=checks=cpu=0
        for row in rows:
            answered+=row['answer'] is not None;correct+=row['answer']==targets[row['source_id']]
            checks+=len(row['verifications']);cpu+=row['cpu_ns']
        summary[arm]={'tasks':len(rows),'correct':correct,'answered':answered,'verification_calls':checks,
                     'controller_cpu_ns':cpu,'mean_external_score_minus_cost':(2*correct-answered-COST*checks)/len(rows)}
    result={'schema':'hepta.tracking-mixture.results.v1','summary':summary,'inventory':inventory,
        'members':member_ids,'ensemble_parameters':member_fit['total_parameters'],
        'shared_proposal_cpu_ns':common_cpu,'shared_parse_cpu_ns':parse_cpu,
        'parent_fit_cpu_ns':fit['fit_cpu_including_encoding_ns'],'load_cpu_ns':fit['load_cpu_ns'],
        'additional_fit_and_features_cpu_ns':member_fit['additional_fit_and_features_cpu_ns'],
        'temperature_selection_cpu_ns':cal['selection_cpu_ns'],
        'study_cpu_before_audit_ns':time.process_time_ns()-started,
        'pretrained':fit['physical'].get('real_pretrained',True),'standalone_full_cost_available':False,
        'joint_model_risk_calibrated':False,'within_member_errors_still_independent':True,
        'learned_ndu_superiority_claimed':False,'production_promotion_permitted':False}
    result['features']=audit_features({'feature_binding':store.binding,'feature_profile':store.profile},store.batches,proposals)
    write_once(output/'mixture-results.json',result)
    from fbsde_tracking_mixture_audit import audit
    write_once(output/'mixture-audit.json',audit(output))
    write_once(output/'mixture-completion.json',{'cpu_through_audit_ns':time.process_time_ns()-started,
        'excludes_this_write_and_startup':True,'production_promotion_permitted':False})
    return result
