"""Learned-belief NDU verification, through the existing frozen tracking gate.

No benchmark fitting, no claim that a numerical BSDE residual proves semantics.
This pairs alternative schedulers on the SAME physically measured gate proposals.
"""
from itertools import combinations
import math
from pathlib import Path
import random
import time

from four_gate_common import digest, require, write_once
from fbsde_tracking import generated_cases, parse, slot_text, execute
from fbsde_tracking_audit import reference
from fbsde_tracking_control import ARMS, BeliefProblem, pair_law, fit_temperature, plan
from fbsde_tracking_records import RecordBuffer

CALIBRATION_SEED = 67867979
TEST_SEED = 86028121
COST = .02


def decision(problem, task, arm):
    """The numerical planner never receives task, true pairs, text or final label."""
    started = time.process_time_ns()
    known = (); trace = []; decisions = []; remaining = 2
    if arm == 'exact_reverse':
        holder = task['query']
        for event in reversed(task['events']):
            a, b = event['pair']
            holder = b if holder == a else a if holder == b else holder
        distribution = [float(i == holder) for i in range(problem.actors)]
        action = f'answer:{holder}'
    elif arm == 'greedy_no_checks':
        greedy = tuple((i, max(range(len(problem.pairs)), key=lambda j: (p[j], -j)))
                       for i, p in enumerate(problem.laws))
        distribution = problem.marginal(greedy)
        action = f'answer:{distribution.index(max(distribution))}'
    else:
        for _ in range(len(problem.laws)+1):
            distribution = problem.marginal(known)
            unverified = [i for i in range(len(problem.laws)) if i not in dict(known)]
            if arm == 'verify_all' and unverified:
                action = f'verify:{unverified[0]}'
            elif arm == 'confidence_verify' and unverified and remaining and max(distribution) < .95:
                i = min(unverified, key=lambda k: (max(problem.laws[k]), k))
                action = f'verify:{i}'
            else:
                depth = min(remaining, 1 if arm == 'myopic_verify' else 2) if arm in ('myopic_verify','ndu_two_step') else 0
                value = plan(problem, known, horizon=depth, cost=COST)
                decisions.append(value)
                action = value['action']
            if not action.startswith('verify:'):
                break
            i = int(action.split(':')[1])
            require(i in unverified and (arm == 'verify_all' or remaining > 0), 'illegal verification')
            # Only this chosen action reveals one original operation, not a label.
            pair = tuple(sorted(task['events'][i]['pair']))
            index = problem.pairs.index(pair)
            trace.append({'event': i, 'pair_index': index, 'source_event_sha256': digest(task['events'][i]['text']),
                          'known_before': known, 'modeled_cost': COST})
            known = tuple(sorted(known+((i, index),)))
            remaining -= 1
        else:
            raise ValueError('verification horizon exhausted')
    answer = None if action == 'abstain' else int(action.split(':')[1])
    text = 'Insufficient evidence; abstain.' if answer is None else task['values'][answer]
    option = None if answer is None else '('+next(k for k,v in task['options'] if v == text)+')'
    return {'arm': arm, 'answer': option, 'text': text, 'holder': answer,
            'probabilities': distribution, 'verifications': trace, 'decisions': decisions,
            'cpu_ns': time.process_time_ns()-started, 'modeled_cost': COST*len(trace),
            'problem_sha256': problem.identity, 'semantic_certificate': arm in ('verify_all','exact_reverse'),
            'model_law_not_independently_validated': True, 'production_promotion_permitted': False}


def run(output, gate, store, *, tracking_source, publisher_root, started, fit):
    import torch
    from four_gate_capture import tensor_digest
    from fbsde_tracking_study import load_originals
    output = Path(output)
    write_once(output/'controller-plan.json', {'schema': 'hepta.tracking-control.plan.v1',
        'arms': ARMS, 'calibration_seed': CALIBRATION_SEED, 'test_seed': TEST_SEED,
        'temperature_grid': [.25,.5,1.,2.,4.], 'cost_per_check': COST, 'max_ndu_checks': 2,
        'confidence_threshold': .95, 'max_planner_nodes': 20000, 'planner_cpu_limit_ns': 100_000_000,
        'proposal_cpu_limit_ns': 100_000_000, 'source': tracking_source,
        'gate_sha256': fit['gate_sha256'], 'feature_binding': store.binding,
        'independent_event_errors_assumed_not_proved': True,
        'calibration_is_simulator_only_not_risk_qualification': True,
        'semantic_parser_cost_shared_no_physical_check_saving_claim': True,
        'controller_is_planning_over_learned_beliefs_not_a_trained_policy_net': True,
        'production_promotion_permitted': False})
    budget = {'used': 0, 'limit': 256*1024*1024}
    proposals = RecordBuffer(budget); priors = RecordBuffer(budget)
    outputs = {arm: RecordBuffer(budget) for arm in ARMS}
    active = {}; calibration = []; common_cpu = 0; parsing_cpu = 0

    def logits(sentence, names):
        nonlocal common_cpu
        begin = time.process_time_ns()
        keys = [slot_text(sentence, names, i) for i in range(len(names))]
        vectors, receipt = store.get(keys, store.binding)
        with torch.inference_mode(): scores = gate(vectors).tolist()
        require(all(math.isfinite(x) for x in scores), 'nonfinite gate')
        cost = time.process_time_ns()-begin
        proposals.append({**active, 'scores': scores, 'source_slot_texts': keys,
                          'features': receipt, 'cpu_ns': cost, 'returned': cost <= 100_000_000})
        common_cpu += cost
        require(cost <= 100_000_000, 'proposal CPU budget exhausted')
        return scores

    try:
        # Generated held-out operation labels only; no BBH input opened yet.
        for case in generated_cases(seed=CALIBRATION_SEED, count=72):
            task = parse(case['input'])
            for i,event in enumerate(task['events']):
                active.update(split='calibration', source_id=case['source_id'], event_index=i)
                calibration.append({'scores': logits(event['text'], task['names']), 'pair': event['pair']})
        cal_start = time.process_time_ns()
        temperature = fit_temperature(calibration)
        temperature['selection_cpu_ns'] = time.process_time_ns()-cal_start
        write_once(output/'controller-calibration.json', {'fit': temperature, 'rows': calibration,
            'gate_sha256': fit['gate_sha256'], 'benchmark_rows_used': False})
        if tracking_source == 'bbh':
            examples, inventory = load_originals(publisher_root or output/'publisher')
        else:
            examples, inventory = generated_cases(seed=TEST_SEED), {'generated': True}
        write_once(output/'controller-inputs.json', [{k:v for k,v in row.items() if k != 'target'} for row in examples])
        for case in examples:
            begin = time.process_time_ns(); task = parse(case['input'])
            parsing_cpu += time.process_time_ns()-begin
            laws = []
            for i,event in enumerate(task['events']):
                active.update(split='evaluation', source_id=case['source_id'], event_index=i)
                _, law = pair_law(logits(event['text'], task['names']), temperature['selected'])
                laws.append(law)
            binding = {'source': task['input_sha256'], 'model': fit['gate_sha256'],
                       'calibration': digest(temperature), 'scope': 'tracking-control-research', 'generation': 1}
            problem = BeliefProblem(len(task['names']), task['query'], laws, binding)
            priors.append({'source_id': case['source_id'], 'laws': laws, 'binding': binding,
                           'problem_sha256': problem.identity})
            order = list(ARMS); random.Random(104729+len(priors)).shuffle(order)
            for arm in order:
                result = decision(problem, task, arm)
                outputs[arm].append({**result, 'source_id': case['source_id']})
        require(fit['gate_sha256'] == digest({k:tensor_digest(v) for k,v in gate.state_dict().items()}),
                'controller changed selected Head')
    except Exception as error:
        write_once(output/'controller-failure.json', {'type':type(error).__name__, 'message':str(error),
            'active':active, 'budget_evidence':getattr(error, 'evidence', None),
            'complete':False, 'production_promotion_permitted':False})
        raise
    finally:
        retention = {name: rows.write_once(output/('controller-'+name+'.json'))
                     for name,rows in [('proposals',proposals),('priors',priors),*outputs.items()]}
        write_once(output/'controller-encoding.json', {'batches':store.batches, 'records':store.records})
        write_once(output/'controller-retention.json', {'streams':retention, 'payload_bytes':budget['used']})
    # Every arm's predictions are sealed before targets are read for scoring.
    targets = {case['source_id']: case.get('target', reference(case['input'])) for case in examples}
    write_once(output/'controller-targets.json', targets)
    summary = {}
    for arm,rows in outputs.items():
        items = list(rows); answered = sum(r['answer'] is not None for r in items)
        correct = sum(r['answer'] == targets[r['source_id']] for r in items)
        cost = sum(r['modeled_cost'] for r in items)
        summary[arm] = {'tasks':len(items), 'answered':answered, 'correct':correct,
            'accepted_error':(answered-correct)/answered if answered else None,
            'mean_external_score_minus_cost':(2*correct-answered-cost)/len(items),
            'verification_calls':sum(len(r['verifications']) for r in items),
            'controller_cpu_ns':sum(r['cpu_ns'] for r in items),
            'semantic_certificate':arm in ('verify_all','exact_reverse')}
    result = {'schema':'hepta.tracking-control.results.v1', 'summary':summary,
        'temperature':temperature, 'inventory':inventory, 'gate_parameters':fit['parameters'],
        'shared_proposal_cpu_ns':common_cpu, 'shared_parse_cpu_ns':parsing_cpu,
        'fit_cpu_ns':fit['fit_cpu_including_encoding_ns'], 'load_cpu_ns':fit['load_cpu_ns'],
        'study_cpu_before_audit_ns':time.process_time_ns()-started,
        'comparison_is_paired_fixed_proposals_not_separate_model_invocations':True,
        'standalone_full_lifecycle_costs_available':False, 'learned_ndu_superiority_claimed':False,
        'pretrained':fit['physical'].get('real_pretrained', True),
        'production_promotion_permitted':False}
    write_once(output/'controller-results.json', result)
    from fbsde_tracking_control_audit import audit
    write_once(output/'controller-audit.json', audit(output))
    write_once(output/'controller-completion.json', {'cpu_ns':time.process_time_ns()-started,
        'includes_audit_excludes_this_write_and_startup':True, 'production_promotion_permitted':False})
    return result
