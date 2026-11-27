"""Real five-parameter residual Head SGD and label-separated investment controls.

Cached pretrained Reader logits are inputs, NOT fresh Encoder execution.
Horizon is a declared reuse scenario, NOT newly observed future tasks.
"""
from __future__ import annotations
import argparse
import math
import statistics
import sys
import time
from fractions import Fraction as Q
from pathlib import Path
from material import canonical, sha, strict_loads, write_new
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from portfolio import aggregate

ARMS=('no_update','fixed_32','budget_neutral','risk_fixed','ndu_discrete','augmented_same_profile')
STEPS=(0,8,32,128)
HORIZONS=(1,8,64)
RATE=0.1
CPU_PRICE=Q(1,1000)  # utility units per measured CPU millisecond, NOT dollars
SOURCES=('material.py','learning.py','audit_real.py','test_real.py','README.md')


def spec():
    return {'schema':'hepta.merton.real-head.spec.v1','parent':'778bb8a32e725b00db59e16cdcdc38fd777ae964',
            'arms':list(ARMS),'steps':list(STEPS),'horizons':list(HORIZONS),'learning_rate':RATE,
            'cpu_utility_price_per_ms':str(CPU_PRICE),'head_parameter_count':5,
            'loss':'question-balanced two-class Brier','initial_weights':[0.0]*5,
            'features':'4 original logit margins centered inside each complete question; TRAIN-only RMS floor 1e-6',
            'base':'frozen mean_pool_query_fused margin; zero residual exactly matches frozen output',
            'primary':'complete native question success; candidate accuracy and Brier descriptive only',
            'selector':'3 inner passage-held calibration folds; refit only selected steps on 3 outer-training passages',
            'recursive_profile':'one-step (1-alpha) mean of passage accuracies + alpha minimum passage accuracy',
            'preference':'start 1/4; frozen-control observed full-question success => -1/8 else +1/4; clip [0,1/2]',
            'cost':'charge ALL executed pilot fitting/scoring, selection and final refit/inference; no refunds for zero selection',
            'future_reuse_is_hypothetical':True,'fresh_encoder_forwards':0,
            'general_fbsde':False,'neural_preference_training':False,'authority':'DENY_ALL'}


def sigmoid(z):
    if not math.isfinite(z): raise ValueError('nonfinite logit')
    if z>=0: return 1/(1+math.exp(-z))
    e=math.exp(z); return e/(1+e)


def validate_fold(f):
    if f.get('schema')!='hepta.merton.real-head.fold.v1': raise ValueError('fold schema')
    train,held=f['train'],f['held_inputs']
    if not train or not held: raise ValueError('empty split')
    if len({r['group'] for r in train})!=3: raise ValueError('three nonheldout passages required')
    for rows,labelled in ((train,True),(held,False)):
        required={'id','group','question','base','x'} | ({'label'} if labelled else set())
        for r in rows:
            if set(r)!=required: raise ValueError('unknown field or heldout label leak')
            if type(r['question']) is not int or len(r['x'])!=4: raise ValueError('feature shape')
            if any(type(v) not in (int,float) or not math.isfinite(v) for v in [r['base']]+r['x']):
                raise ValueError('nonfinite or nonnumeric feature')
            if labelled and (type(r['label']) is not int or r['label'] not in (0,1)): raise ValueError('invalid label')
    if len({r['id'] for r in train+held})!=len(train+held): raise ValueError('duplicate or overlapping ID')
    if any(r['group']==f['held_group'] for r in train) or any(r['group']!=f['held_group'] for r in held):
        raise ValueError('passage leakage')


def feature(row, scales):
    return [v/s for v,s in zip(row['x'],scales)]+[1.0]


def predict(head, rows):
    return [sigmoid(r['base']+sum(w*x for w,x in zip(head['weights'],feature(r,head['scales'])))) for r in rows]


def fit(rows, steps):
    if type(steps) is not int or steps not in STEPS: raise ValueError('unregistered step budget')
    c,w=time.process_time_ns(),time.perf_counter_ns()
    if not steps:
        head={'weights':[0.0]*5,'scales':[1.0]*4}
        return head,{'steps':0,'train_ids':[],'train_label_digest':None,'train_rows':0,
                     'cpu_ns':time.process_time_ns()-c,'wall_ns':time.perf_counter_ns()-w,'loss_trace':[]}
    if not rows or any('label' not in r for r in rows): raise ValueError('training labels required')
    scales=[max(1e-6,math.sqrt(sum(r['x'][j]**2 for r in rows)/len(rows))) for j in range(4)]
    X=[feature(r,scales) for r in rows]
    questions={(r['group'],r['question']) for r in rows}
    counts={q:sum((r['group'],r['question'])==q for r in rows) for q in questions}
    mass=[1/(len(questions)*counts[r['group'],r['question']]) for r in rows]
    weights=[0.0]*5; trace=[]
    for _ in range(steps):
        gradient=[0.0]*5; loss=0.0
        for r,x,m in zip(rows,X,mass):
            p=sigmoid(r['base']+sum(a*b for a,b in zip(weights,x)))
            d=p-r['label']; loss+=m*2*d*d
            g=m*4*d*p*(1-p)
            for j in range(5): gradient[j]+=g*x[j]
        weights=[a-RATE*b for a,b in zip(weights,gradient)];trace.append(loss)
    if any(not math.isfinite(v) for v in weights): raise ValueError('nonfinite fit')
    head={'weights':weights,'scales':scales}
    return head,{'steps':steps,'train_ids':[r['id'] for r in rows],
                 'train_label_digest':sha(canonical([[r['id'],r['label']] for r in rows])),
                 'train_rows':len(rows),'cpu_ns':time.process_time_ns()-c,
                 'wall_ns':time.perf_counter_ns()-w,'loss_trace':trace}


def full_questions(rows, probs):
    if len(rows)!=len(probs): raise ValueError('prediction count')
    groups=sorted({(r['group'],r['question']) for r in rows})
    return [int(all(int(p>0.5)==r['label'] for r,p in zip(rows,probs)
                    if (r['group'],r['question'])==g)) for g in groups]


def alpha_from(observations):
    p=Q(1,4)
    for success in observations:
        if type(success) is not int or success not in (0,1): raise ValueError('invalid observed outcome')
        p=min(Q(1,2),max(Q(0),p+(Q(-1,8) if success else Q(1,4))))
    return p


def select(candidates, horizon, alpha):
    if horizon not in HORIZONS or type(horizon) is not int: raise ValueError('unregistered horizon')
    if not 0<=alpha<=Q(1,2): raise ValueError('preference bound')
    values={}
    for k in STEPS:
        d=candidates[str(k)]
        quality=aggregate(tuple((Q(1,len(d['passage_success'])),Q(v)) for v in d['passage_success']),alpha)
        # All already-executed bank work is sunk. It is charged in ledger, not refunded here.
        cost_ns=Q(d['estimated_refit_cpu_ns'])+horizon*Q(d['observed_inference_cpu_ns_per_question'])
        values[k]=horizon*quality-CPU_PRICE*cost_ns/1_000_000
    choice=max(STEPS,key=lambda k:(values[k],-k))
    return choice,{str(k):str(v) for k,v in values.items()}


def augmented_select(candidates,horizon,alpha):
    # Ordinary one-decision augmented-state enumeration with exactly the same objective.
    values={}
    for k in STEPS:
        c=candidates[str(k)]; gains=[Q(v) for v in c['passage_success']]
        utility=(1-alpha)*sum(gains,Q(0))/len(gains)+alpha*min(gains)
        fee=CPU_PRICE*(Q(c['estimated_refit_cpu_ns'])+Q(horizon)*Q(c['observed_inference_cpu_ns_per_question']))/1_000_000
        values[k]=Q(horizon)*utility-fee
    return sorted(STEPS,key=lambda k:(-values[k],k))[0]


def execute(fold, arm, horizon):
    if arm not in ARMS: raise ValueError('arm')
    validate_fold(fold)
    if type(horizon) is not int or horizon not in HORIZONS: raise ValueError('horizon')
    start_c,start_w=time.process_time_ns(),time.perf_counter_ns()
    train,held=fold['train'],fold['held_inputs']
    fits=[]; calibration=[]; candidates={}; values={}; alpha=Q(0); reference=None
    stages={'pilot_cpu_ns':0,'selection_cpu_ns':0,'final_fit_cpu_ns':0,'inference_cpu_ns':0}
    if arm=='no_update': selected=0
    elif arm=='fixed_32': selected=32
    else:
        pc=time.process_time_ns()
        groups=sorted({r['group'] for r in train})
        for group in groups:
            a=[r for r in train if r['group']!=group]
            b=[r for r in train if r['group']==group]
            for steps in STEPS:
                head,receipt=fit(a,steps)
                receipt.update(role='pilot',validation_group=group,head=head)
                fits.append(receipt)
                c=time.process_time_ns();probs=predict(head,b);q=full_questions(b,probs)
                elapsed=time.process_time_ns()-c
                calibration.append({'group':group,'steps':steps,'ids':[r['id'] for r in b],
                    'probabilities':probs,'complete_questions':q,'scoring_cpu_ns':elapsed})
        for steps in STEPS:
            cr=[r for r in calibration if r['steps']==steps]
            fr=[r for r in fits if r['steps']==steps]
            # Refit cost estimate scales actual pilot time by row exposure; NOT a measured final fit.
            estimate=Q(0) if steps==0 else sum((Q(r['cpu_ns']*len(train),r['train_rows']) for r in fr),Q(0))/len(fr)
            candidates[str(steps)]={'passage_success':[str(Q(sum(r['complete_questions']),len(r['complete_questions']))) for r in cr],
                 'estimated_refit_cpu_ns':str(estimate),
                 'observed_inference_cpu_ns_per_question':str(sum((Q(r['scoring_cpu_ns'],len(r['complete_questions'])) for r in cr),Q(0))/len(cr))}
        observed=[v for r in calibration if r['steps']==0 for v in r['complete_questions']]
        alpha=Q(0) if arm=='budget_neutral' else Q(1,4) if arm=='risk_fixed' else alpha_from(observed)
        stages['pilot_cpu_ns']=time.process_time_ns()-pc
        sc=time.process_time_ns(); selected,values=select(candidates,horizon,alpha)
        reference=augmented_select(candidates,horizon,alpha)
        if selected!=reference: raise ValueError('same-profile augmented reference mismatch')
        if arm=='augmented_same_profile': selected=reference
        stages['selection_cpu_ns']=time.process_time_ns()-sc
    head,receipt=fit(train,selected);receipt.update(role='final',head=head);fits.append(receipt)
    stages['final_fit_cpu_ns']=receipt['cpu_ns']
    c=time.process_time_ns(); probs=predict(head,held);stages['inference_cpu_ns']=time.process_time_ns()-c
    return {'fold':fold['fold'],'arm':arm,'horizon_scenario':horizon,'held_group':fold['held_group'],
        'selected_steps':selected,'selected_head':head,'preference':str(alpha),
        'candidate_quotes':candidates,'selection_values':values,'same_profile_reference_steps':reference,
        'calibration':calibration,'fits':fits,'update_steps_actually_executed':sum(r['steps'] for r in fits),
        'test_probabilities':[{'id':r['id'],'p':p} for r,p in zip(held,probs)],
        'stages':stages,'lifecycle_cpu_ns':time.process_time_ns()-start_c,
        'lifecycle_wall_ns':time.perf_counter_ns()-start_w,
        'policy_loaded_heldout_labels':False,'neural_preference_updates':0,'fresh_encoder_forwards':0,
        'source_fold_sha256':sha(canonical(fold))}


def run(material_dir, output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    sources={n:sha(Path(__file__).with_name(n).read_bytes()) for n in SOURCES}
    s=spec();write_new(output/'spec.json',s)
    start_c,start_w=time.process_time_ns(),time.perf_counter_ns()
    rows=[]
    for i in range(4):
        raw=(Path(material_dir)/f'fold-{i}.json').read_bytes(); f=strict_loads(raw)
        validate_fold(f)
        # The worker opens fold files only. scorer-labels.json is not read here.
        for horizon in HORIZONS:
            for arm in ARMS: rows.append(execute(f,arm,horizon))
    report={'schema':'hepta.merton.real-head.seal.v1','spec_sha256':sha(canonical(s)),
        'source_sha256':sources,'rows':rows,'python':sys.version,'authority':'DENY_ALL',
        'worker_cpu_ns':time.process_time_ns()-start_c,'worker_wall_ns':time.perf_counter_ns()-start_w,
        'actual_update_steps':sum(r['update_steps_actually_executed'] for r in rows),
        'new_encoder_forwards':0,'new_original_reader_forwards':0,'new_residual_heads_trained':sum(f['steps']>0 for r in rows for f in r['fits']),
        'historical_source_family_count':1,'independent_passage_count':4,'new_future_sources':0}
    write_new(output/'sealed.json',report)
    print({'sealed_rows':len(rows),'actual_update_steps':report['actual_update_steps'],'new_residual_heads_trained':report['new_residual_heads_trained']})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--material',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path); a=p.parse_args();run(a.material,a.output)
