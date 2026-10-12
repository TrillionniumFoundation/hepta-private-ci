"""Source-verification feedback -> separate candidate -> future-frame shadow replay.

All models see the same frozen lexical vectors. Exact operations are used only
as simulator training feedback or after a chosen verification. No BBH labels or
new pretrained weights. One-time post-feedback transfer, not live deployment.
"""
from itertools import combinations
import hashlib
import math
from pathlib import Path
import random
import time
from four_gate_common import digest, require, write_once
from four_gate_capture import tensor_digest
from fbsde_tracking import lexical_vector, slot_text
from fbsde_tracking_control import pair_law, TEMPERATURES
from fbsde_tracking_control_study import decision
from fbsde_tracking_records import RecordBuffer
from fbsde_tracking_tied import InputTiedBelief
from fbsde_tracking_feedback import (load_base, validate_feedback, candidate_scores,
    fit_candidates, states_json, identity, KINDS, PAIRS)
from fbsde_tracking_feedback_data import (PROFILE, FAMILIAR, REPAIR, CALIBRATION,
    HELDOUT, SEED, local_rows, generate, task)

ARMS = {'frozen_no_checks': ('base_raw','posterior_no_checks'),
    'temperature_ndu': ('base_temp','ndu_two_step'), 'smoothing_ndu': ('smooth','ndu_two_step'),
    'residual_no_checks': ('residual','posterior_no_checks'),
    'residual_myopic': ('residual','myopic_verify'), 'residual_ndu': ('residual','ndu_two_step'),
    'finetuned_no_checks': ('finetuned','posterior_no_checks'), 'finetuned_ndu': ('finetuned','ndu_two_step'),
    'linear_no_checks': ('linear','posterior_no_checks'), 'linear_ndu': ('linear','ndu_two_step'),
    'verify_all': ('base_raw','verify_all'), 'exact_reverse': ('base_raw','exact_reverse')}
CONSTANTS = (0., .25, .5, .75, 1.)


def run(output, evidence_dir):
    import torch
    started = time.process_time_ns(); torch.set_num_threads(2)
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    sources = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in Path(__file__).parent.glob('fbsde_tracking_feedback*.py')}
    public = generate(); feedback = local_rows(FAMILIAR+REPAIR); calibration = local_rows(CALIBRATION)
    heldout_texts = {t for r in public if r['split'] == 'heldout' for t in r['events']}
    require(not set(FAMILIAR+REPAIR) & set(CALIBRATION+HELDOUT) and not set(CALIBRATION) & set(HELDOUT),
            'disjoint anonymized frames')
    require(not {r['text'] for r in feedback+calibration} & heldout_texts, 'heldout text leaked')
    write_once(output/'plan.json', {'profile': PROFILE, 'sources': sources, 'seed': SEED,
        'feedback_frames': FAMILIAR+REPAIR, 'calibration_frames': CALIBRATION, 'heldout_frames': HELDOUT,
        'public_sha256': digest(public), 'arms': ARMS, 'steps': 160, 'lr': .01,
        'temperature_grid': TEMPERATURES, 'constant_grid': CONSTANTS,
        'cost_per_check': .02, 'max_checks': 2, 'proposal_cpu_limit_ns': 100_000_000,
        'exactly_same_feedback_for_all_trainable_candidates': True,
        'feedback_selection': 'fixed_source_quota_including_correct_and_wrong_predictions',
        'no_test_based_hyperparameter_selection': True, 'production_promotion_permitted': False})
    write_once(output/'inputs.json', public)
    budget = {'used': 0, 'limit': 256*1024*1024}
    proposals = RecordBuffer(budget); priors = RecordBuffer(budget)
    outputs = {a: RecordBuffer(budget) for a in ARMS}; active = {}; common_cpu = build_cpu = 0
    members, parent = load_base(torch, evidence_dir)
    write_once(output/'frozen-fit.json', parent)
    def vector(text, names):
        return torch.tensor([lexical_vector(slot_text(text, names, j)) for j in range(3)])
    predictions = []
    # Complete prediction file closes before feedback labels are given to any fit.
    for i, row in enumerate(feedback):
        src = {k: row[k] for k in ('text','names','source_id')}
        with torch.inference_mode(): scores = [m(vector(row['text'],row['names'])).tolist() for m in members]
        predictions.append({'index': i, 'source': src, 'scores': scores, 'phase': 'before_feedback'})
    write_once(output/'before-feedback.json', predictions)
    receipts = []
    for i, (row, p) in enumerate(zip(feedback, predictions)):
        verified = task({'names': row['names'], 'query': 0, 'events': [row['text']]})['events'][0]['pair']
        require(list(verified) == row['pair'], 'simulator feedback contradicts source')
        receipts.append({'source': p['source'], 'pair': list(verified), 'prediction_sha256': digest(p),
                         'sequence': 2*i+1, 'observer': 'simulator_source_verifier'})
    validate_feedback(receipts, predictions, {digest(t) for t in heldout_texts})
    write_once(output/'feedback.json', receipts)
    models, jobs = fit_candidates(torch, members, receipts)
    snapshot = states_json(models); snapshot_id = digest(snapshot)
    write_once(output/'candidate-weights.json', snapshot)
    write_once(output/'fit.json', {'jobs': jobs, 'parent_members': parent['members'],
        'snapshot_sha256': snapshot_id, 'feedback_sha256': digest(receipts),
        'prediction_file_sha256': hashlib.sha256((output/'before-feedback.json').read_bytes()).hexdigest(),
        'parameters_shared_not_per_story': True, 'candidate_activation_permitted': False})
    def predict(text, names):
        nonlocal common_cpu
        start = time.process_time_ns(); x = vector(text, names)
        with torch.inference_mode():
            scores = {k: candidate_scores(torch,k,models,x).tolist() for k in KINDS}
        require(all(math.isfinite(s) for v in scores.values() for m in v for s in m), 'finite candidate logits')
        cpu = time.process_time_ns()-start; common_cpu += cpu
        proposals.append({**active, 'text': text, 'names': list(names), 'scores': scores,
            'vectors_sha256': tensor_digest(x), 'cpu_ns': cpu, 'returned': cpu <= 100_000_000})
        require(cpu <= 100_000_000, 'proposal CPU budget exhausted')
        return scores
    def laws(scores, temp): return [list(pair_law(s,temp)[1]) for s in scores]
    try:
        cal = []
        for i, row in enumerate(calibration):
            active = {'split': 'calibration', 'source_id': row['source_id'], 'event': 0}
            cal.append({**row, 'scores': predict(row['text'], row['names'])})
        begin = time.process_time_ns(); selected = {}; grid = {}
        def loss(probabilities): return -math.fsum(math.log(max(p,1e-300)) for p in probabilities)/len(probabilities)
        for kind in KINDS:
            grid[kind] = [{'temperature': t, 'nll': loss([math.fsum(q[PAIRS.index(tuple(r['pair']))]
                for q in laws(r['scores'][kind],t))/3 for r in cal])} for t in TEMPERATURES]
            selected[kind] = min(grid[kind], key=lambda r:(r['nll'],r['temperature']))['temperature']
        smoothing = [{'alpha': a, 'nll': loss([(1-a)*math.fsum(q[PAIRS.index(tuple(r['pair']))]
            for q in laws(r['scores']['frozen'],selected['frozen']))/3+a/3 for r in cal])} for a in CONSTANTS]
        alpha = min(smoothing,key=lambda r:(r['nll'],r['alpha']))['alpha']
        selection = {'rows':cal,'temperatures':selected,'temperature_candidates':grid,'alpha':alpha,
                     'smoothing_candidates':smoothing,'cpu_ns':time.process_time_ns()-begin}
        write_once(output/'calibration.json', selection); cal_id = digest(selection)
        # Original frozen temperatures remain a separately identified baseline.
        import json
        oldtemps = [r['selected'] for r in json.loads((Path(evidence_dir)/'calibration.json').read_text())['temperatures']]
        write_once(output/'old-temperatures.json', oldtemps)
        for row in public:
            comp = {k: [[],[],[]] for k in ('base_raw','base_temp','smooth','residual','finetuned','linear')}
            for i, text in enumerate(row['events']):
                active = {'split': 'evaluation', 'source_id':row['source_id'], 'event':i}
                raw = predict(text, row['names']); temp = laws(raw['frozen'], selected['frozen'])
                variants = {'base_raw': [list(pair_law(s,t)[1]) for s,t in zip(raw['frozen'],oldtemps)],
                    'base_temp':temp,'smooth':[[(1-alpha)*p+alpha/3 for p in q] for q in temp],
                    **{k:laws(raw[k],selected[k]) for k in KINDS[1:]}}
                for k, values in variants.items():
                    for m, q in enumerate(values): comp[k][m].append(q)
            binding = {'source':digest(row),'model':snapshot_id,'calibration':cal_id,
                       'scope':'verified-feedback-research','generation':2}
            keys = [digest([t,row['names'],binding]) for t in row['events']]
            begin = time.process_time_ns()
            problems = {k:InputTiedBelief(3,row['query'],v,[1/3]*3,keys,binding) for k,v in comp.items()}
            build_cpu += time.process_time_ns()-begin
            priors.append({'source_id':row['source_id'],'components':comp,'keys':keys,'binding':binding,
                           'problem_ids':{k:p.identity for k,p in problems.items()}})
            source_task = task(row); order = list(ARMS); random.Random(SEED+len(priors)).shuffle(order)
            for arm in order:
                kind, policy = ARMS[arm]; active = {'split':'planning','source_id':row['source_id'],'arm':arm}
                outputs[arm].append({**decision(problems[kind],source_task,policy),'source_id':row['source_id']})
        require(digest(states_json(models)) == snapshot_id and [identity(m) for m in members] == parent['members'],
                'evaluation changed selected or parent weights')
    except Exception as e:
        write_once(output/'failure.json', {'active':active,'type':type(e).__name__,'message':str(e),
            'evidence':getattr(e,'evidence',None),'complete':False})
        raise
    finally:
        streams = {k:v.write_once(output/(k+'.json')) for k,v in [('proposals',proposals),('priors',priors),*outputs.items()]}
        write_once(output/'retention.json', {'streams':streams,'payload_bytes':budget['used']})
    targets = {}
    for row in public:
        t = task(row); holder = t['query']
        for e in reversed(t['events']):
            a,b = e['pair']; holder = b if holder == a else a if holder == b else holder
        targets[row['source_id']] = holder
    write_once(output/'targets.json', targets)
    split_of = {r['source_id']:r['split'] for r in public}; summary = {}
    for split in ('known_replay','heldout'):
        summary[split] = {}
        for arm, records in outputs.items():
            rows = [r for r in records if split_of[r['source_id']] == split]; n = len(rows)
            correct = sum(r['holder'] == targets[r['source_id']] for r in rows)
            answered = sum(r['holder'] is not None for r in rows); checks = sum(len(r['verifications']) for r in rows)
            summary[split][arm] = {'cases':n,'correct':correct,'answered':answered,'checks':checks,
                'mean_utility':(2*correct-answered-.02*checks)/n,'cpu_ns':sum(r['cpu_ns'] for r in rows)}
    result = {'profile':PROFILE,'summary':summary,'shared_proposal_cpu_ns':common_cpu,
        'problem_build_cpu_ns':build_cpu,'new_fit_cpu_ns':sum(j['cpu_ns'] for j in jobs),
        'cpu_before_audit_ns':time.process_time_ns()-started,'standalone_lifecycle_available':False,
        'base_training_cost_not_reexecuted':True,'real_pretrained_executed':False,
        'risk_certified':False,'production_promotion_permitted':False}
    write_once(output/'results.json', result)
    from fbsde_tracking_feedback_audit import audit
    write_once(output/'arithmetic-audit.json', audit(output))
    write_once(output/'completion.json', {'cpu_through_audit_ns':time.process_time_ns()-started,
        'excludes_interpreter_startup_and_this_write':True,'production_promotion_permitted':False})
    return result
