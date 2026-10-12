"""Frozen shared Heads -> disjoint calibration frames -> new held-out frames.

Consumes a byte-bound tiny-Head artifact from input_tied_challenge_v1; no new
pretrained forward, benchmark fitting or risk admission. All cheap controls stay.
"""
from itertools import combinations
import hashlib
import math
from pathlib import Path
import random
import shutil
import time
from four_gate_common import digest, require, strict_loads, write_once
from four_gate_capture import tensor_digest
from fbsde_tracking import make_gate, lexical_vector, slot_text, training_rows
from fbsde_tracking_control import pair_law, TEMPERATURES
from fbsde_tracking_control_study import decision
from fbsde_tracking_records import RecordBuffer
from fbsde_tracking_tied import InputTiedBelief
from fbsde_tracking_novelty import (PROFILE, support_from_training, features, alpha_for, smooth, fit_gate)
from fbsde_tracking_novelty_data import FAMILIAR, CALIBRATION, HELDOUT, SEED, local_rows, generate, task

ARMS = {'base_no_checks': ('base','posterior_no_checks'), 'base_ndu': ('base','ndu_two_step'),
        'temperature_ndu': ('temperature','ndu_two_step'), 'constant_ndu': ('constant','ndu_two_step'),
        'novelty_no_checks': ('novelty','posterior_no_checks'), 'novelty_myopic': ('novelty','myopic_verify'),
        'novelty_ndu': ('novelty','ndu_two_step'), 'uniform_ndu': ('uniform','ndu_two_step'),
        'verify_all': ('novelty','verify_all'), 'exact_reverse': ('base','exact_reverse')}
CONSTANTS = (0., .25, .5, .75, 1.)
PAIRS = tuple(combinations(range(3),2))


def run(output, evidence_dir):
    import torch
    started = time.process_time_ns(); torch.set_num_threads(2)
    output = Path(output); output.mkdir(parents=True, exist_ok=False); root = Path(evidence_dir)
    for name in ('heads.pt','fit.json','calibration.json','design.json'):
        p = root/name
        require(p.is_file() and not p.is_symlink() and p.stat().st_size < 1_000_000, 'bounded frozen source')
    oldfit = strict_loads((root/'fit.json').read_bytes()); oldcal = strict_loads((root/'calibration.json').read_bytes())
    require(strict_loads((root/'design.json').read_bytes())['profile'] == 'input_tied_challenge_v1', 'explicit source profile')
    raw = (root/'heads.pt').read_bytes(); source_hash = hashlib.sha256(raw).hexdigest()
    require(source_hash == oldfit['heads_bytes_sha256'] and oldfit['training_sha256'] == digest(training_rows()),
            'original training and weight binding')
    write_once(output/'plan.json', {'profile': PROFILE, 'frozen_heads_sha256': source_hash,
        'familiar_frames': FAMILIAR, 'calibration_frames': CALIBRATION, 'heldout_frames': HELDOUT,
        'seed': SEED, 'arms': ARMS, 'temperature_grid': TEMPERATURES, 'constant_grid': CONSTANTS,
        'max_checks': 2, 'cost_per_check': .02, 'cpu_limit_ns': 100_000_000,
        'gate_steps': 160, 'gate_lr': .05, 'calibration_is_not_final_risk_validation': True,
        'pretrained_execution': False, 'source_kind': 'generated_closed_grammar',
        'sources': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in Path(__file__).parent.glob('fbsde_tracking_novelty*.py')},
        'production_promotion_permitted': False})
    shutil.copyfile(root/'heads.pt', output/'frozen-heads.pt')
    write_once(output/'frozen-fit.json', oldfit); write_once(output/'frozen-calibration.json', oldcal)
    members = []
    states = torch.load(root/'heads.pt', weights_only=True, map_location='cpu')
    require(type(states) is list and len(states) == 3, 'three shared Head states')
    for s in states:
        m = make_gate(torch); m.load_state_dict(s, strict=True); m.eval().requires_grad_(False); members.append(m)
    def member_ids(): return [digest({k:tensor_digest(v) for k,v in m.state_dict().items()}) for m in members]
    ids = member_ids(); require(ids == oldfit['members'], 'frozen tensor identity')
    training_texts = [t for t,_ in training_rows()]; support = support_from_training(training_texts)
    write_once(output/'support-training-texts.json', training_texts); write_once(output/'support.json', support)
    temps = [t['selected'] for t in oldcal['temperatures']]
    budget = {'used':0,'limit':256*1024*1024}; proposals = RecordBuffer(budget); priors = RecordBuffer(budget)
    outputs = {a:RecordBuffer(budget) for a in ARMS}; active = {}; common_cpu = build_cpu = 0
    fitrows = []; calibration_records = []
    def predict(text,names):
        nonlocal common_cpu
        began = time.process_time_ns(); slots = [slot_text(text,names,i) for i in range(3)]
        v = torch.tensor([lexical_vector(t) for t in slots])
        with torch.inference_mode(): scores = [m(v).tolist() for m in members]
        require(all(all(type(x) is float and math.isfinite(x) for x in row) for row in scores), 'finite frozen logits')
        cost = time.process_time_ns()-began; common_cpu += cost
        proposals.append({**active,'text':text,'names':list(names),'scores':scores,
                          'vectors_sha256':tensor_digest(v),'cpu_ns':cost,'returned':cost<=100_000_000})
        require(cost<=100_000_000,'proposal CPU budget exhausted')
        return scores
    def laws(scores,ts): return [list(pair_law(s,t)[1]) for s,t in zip(scores,ts)]
    def nll(rows): return -math.fsum(math.log(max(p,1e-300)) for p in rows)/len(rows)
    try:
        for i,row in enumerate(local_rows(FAMILIAR+CALIBRATION)):
            active = {'phase':'calibration','source_id':f'cal:{i}','event':0}
            scores = predict(row['text'],row['names']); q = laws(scores,temps)
            feat = features(row['text'],row['names'],q,support); j = PAIRS.index(tuple(row['pair']))
            fitrows.append({'features':feat,'laws':q,'pair_index':j,'source_sha256':digest(row['text'])})
            calibration_records.append({**row,'scores':scores})
        gate = fit_gate(torch,fitrows); selection_start = time.process_time_ns()
        temperatures = []
        for t in TEMPERATURES:
            ps = [math.fsum(x[r['pair_index']] for x in laws(c['scores'],[t]*3))/3
                  for r,c in zip(fitrows,calibration_records)]
            temperatures.append({'temperature':t,'nll':nll(ps)})
        constants = [{'alpha':a,'nll':nll([math.fsum(x[r['pair_index']] for x in smooth(r['laws'],a))/3
                                         for r in fitrows])} for a in CONSTANTS]
        temperature = min(temperatures,key=lambda r:(r['nll'],r['temperature']))['temperature']
        constant = min(constants,key=lambda r:(r['nll'],r['alpha']))['alpha']
        selected = {'gate':gate,'temperature':temperature,'constant':constant,
                    'temperature_candidates':temperatures,'constant_candidates':constants,
                    'source_rows':calibration_records,'fit_rows':fitrows,
                    'selection_cpu_ns':time.process_time_ns()-selection_start}
        write_once(output/'calibration.json',selected); cal_id = digest(selected); weight_id = digest(gate['weights'])
        public = generate(); write_once(output/'inputs.json',public)
        # Holdout has different anonymized frames, not merely new actor names.
        from fbsde_tracking_novelty import tokens
        cal_forms = {tokens(r['text'],r['names']) for r in calibration_records}
        require(all(tokens(t,row['names']) not in cal_forms for row in public if row['split']=='heldout'
                    for t in row['events']), 'calibration/heldout syntax overlap')
        for row in public:
            comp = {k:[[],[],[]] for k in ('base','temperature','constant','novelty','uniform')}; annotations = []
            for i,text in enumerate(row['events']):
                active = {'phase':'evaluation','source_id':row['source_id'],'event':i}
                scores = predict(text,row['names']); q = laws(scores,temps)
                feat = features(text,row['names'],q,support); alpha = alpha_for(feat,gate)
                variants = {'base':q,'temperature':laws(scores,[temperature]*3),
                            'constant':smooth(q,constant),'novelty':smooth(q,alpha),'uniform':smooth(q,1.)}
                for kind,values in variants.items():
                    for m,values_m in enumerate(values): comp[kind][m].append(values_m)
                annotations.append({'features':feat,'alpha':alpha})
            binding = {'source':digest(row),'model':digest(ids),'calibration':cal_id,
                       'scope':'novelty-calibration-research','generation':1}
            keys = [digest([s,row['names'],binding]) for s in row['events']]
            began = time.process_time_ns()
            problems = {k:InputTiedBelief(3,row['query'],v,[1/3]*3,keys,binding) for k,v in comp.items()}
            build_cpu += time.process_time_ns()-began
            priors.append({'source_id':row['source_id'],'components':comp,'binding':binding,'keys':keys,
                           'annotations':annotations,'problem_ids':{k:p.identity for k,p in problems.items()}})
            source_task = task(row); order = list(ARMS); random.Random(SEED+len(priors)).shuffle(order)
            for arm in order:
                kind,policy = ARMS[arm]; active = {'phase':'planning','source_id':row['source_id'],'arm':arm}
                outputs[arm].append({**decision(problems[kind],source_task,policy),'source_id':row['source_id']})
        require(member_ids()==ids and digest(gate['weights'])==weight_id,'evaluation changed weights')
    except Exception as e:
        write_once(output/'failure.json',{'active':active,'type':type(e).__name__,'message':str(e),
            'evidence':getattr(e,'evidence',None),'complete':False})
        raise
    finally:
        retention = {n:r.write_once(output/(n+'.json')) for n,r in [('proposals',proposals),('priors',priors),*outputs.items()]}
        write_once(output/'retention.json',{'streams':retention,'payload_bytes':budget['used']})
    targets = {}; splits = {r['source_id']:r['split'] for r in public}
    for row in public:
        source_task = task(row); state = list(range(3))
        for e in source_task['events']:
            a,b = e['pair']; state[a],state[b] = state[b],state[a]
        targets[row['source_id']] = state[row['query']]
    write_once(output/'targets.json',targets)
    summary = {}
    for split in ('retention','heldout'):
        summary[split] = {}
        for arm,rs in outputs.items():
            rows = [r for r in rs if splits[r['source_id']]==split]; n = len(rows)
            c = sum(r['holder']==targets[r['source_id']] for r in rows); answered = sum(r['holder'] is not None for r in rows)
            checks = sum(len(r['verifications']) for r in rows)
            summary[split][arm] = {'cases':n,'correct':c,'answered':answered,'checks':checks,
                'mean_utility':(2*c-answered-.02*checks)/n,'cpu_ns':sum(r['cpu_ns'] for r in rows)}
    result = {'profile':PROFILE,'summary':summary,'shared_proposal_cpu_ns':common_cpu,
        'problem_build_cpu_ns':build_cpu,'gate_fit_cpu_ns':gate['fit_cpu_ns'],
        'cpu_before_audit_ns':time.process_time_ns()-started,'standalone_lifecycle_available':False,
        'new_pretrained_execution':False,'risk_certified':False,'production_promotion_permitted':False}
    write_once(output/'results.json',result)
    from fbsde_tracking_novelty_audit import audit
    write_once(output/'arithmetic-audit.json',audit(output))
    write_once(output/'completion.json',{'cpu_through_audit_ns':time.process_time_ns()-started,
        'excludes_this_write_and_interpreter_startup':True,'production_promotion_permitted':False})
    return result
