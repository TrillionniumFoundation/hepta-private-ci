"""E24 retrospective MultiRC question-worst-Brier learner (SHADOW / DENY_ALL).

One source-group is held out per fold.  The only train targets are the previously
sealed ORIGINAL E15 training-only material, never the held group's truth.
All four arms have the same five physical scalar parameters and 48 CPU SGD
updates.  Temperatures are an *exploratory grid on a previously inspected*
source family, NOT preregistered future-efficacy hypotheses.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from math import exp, isfinite
from pathlib import Path
from time import process_time_ns

from e14_multirc_route import ARCHIVE_SHA, OBS_ID, read_prelabel, strict_json, write_once
from e15_reader_crossfit import digest, sigmoid, verify_train, STEPS, LR, L2
from e16_answer_centered import features, scales, design, train as original_brier_train

SCHEMA = 'hepta.e24.retrospective-whole-question-brier-student.v1'
METHODS = ('e16_scaled_brier_5', 'question_softworst_tau_001',
           'question_softworst_tau_010', 'question_softworst_tau_050')
# These are fixed in source before *this* code is pushed but chosen with
# historical question outcomes already visible. NO prospective claim.
TAU = dict(zip(METHODS[1:], (0.01, 0.10, 0.50)))
PARAMS = 5
MAX_ABS_WEIGHT = 128.0


def question_groups(rows: list[dict], labels: dict[str,int]) -> tuple[tuple[tuple[float,...],int], ...]:
    """Training-only complete candidate sets, grouped by original (source,question)."""
    if type(labels) is not dict or any(type(y) is not int or y not in (0,1) for y in labels.values()):
        raise ValueError('original TRAIN labels must be exact typed 0/1')
    ids = {r['task_id'] for r in rows}
    if not 20 <= len(labels) <= 30 or not set(labels).issubset(ids):
        raise ValueError('training-only original candidate inventory invalid')
    units = scales(rows,set(labels))
    grouped = defaultdict(list)
    for row in rows:
        if row['task_id'] in labels:
            key = (row['group'],row['question'])
            grouped[key].append((design(row,'centered_scaled_5',units),labels[row['task_id']]))
    if len(grouped) != 6 or len({k[0] for k in grouped}) != 3 or any(not 2 <= len(v) <= 8 for v in grouped.values()):
        raise ValueError('exact six train questions / three original passages required')
    if set(labels) != {r['task_id'] for r in rows if (r['group'],r['question']) in grouped}:
        raise ValueError('partial original training question or leaked held labels')
    return tuple(tuple(grouped[k]) for k in sorted(grouped))


def _weights_gradient(groups, weights: list[float], tau: float) -> list[float]:
    """Actual training loss: equally weighted questions, smooth worst Brier.

    L = mean_q tau*log(mean_i exp((p_i-y_i)^2 / tau)).
    A source with more candidates gets NO additional weight just from size.
    """
    grad = [0.0] * PARAMS
    for question in groups:
        rows=[]
        for x,y in question:
            if type(y) is not int or y not in (0,1):raise ValueError('invalid train target')
            p=sigmoid(sum(w*v for w,v in zip(weights,x,strict=True)))
            b=(p-y)*(p-y)
            rows.append((x,y,p,b))
        peak=max(z[3] for z in rows)
        exp_weights=[exp((b-peak)/tau) for _,_,_,b in rows]
        total=sum(exp_weights)
        if not isfinite(total) or total<=0:raise ValueError('unstable question-level gradient')
        for idx,(x,y,p,b) in enumerate(rows):
            derivative=(exp_weights[idx]/total)*2*(p-y)*p*(1-p)/len(groups)
            for j in range(PARAMS): grad[j]+=derivative*x[j]
    if any(not isfinite(x) or abs(x)>1024 for x in grad):
        raise ValueError('invalid finite group-risk gradient')
    return grad


def fit_group_risk(rows: list[dict], labels: dict[str,int], tau: float) -> tuple[list[float],int]:
    if type(tau) is not float or tau not in tuple(TAU.values()):
        raise ValueError('registered retrospective temperature required')
    grouped = question_groups(rows,labels)
    weights=[0.0]*PARAMS
    start=process_time_ns()
    for _ in range(STEPS):
        g=_weights_gradient(grouped,weights,tau)
        # Same 0.5 learning rate + nonbias L2 as original E16 Brier Head.
        for j in range(PARAMS):weights[j]-=LR*(g[j]+(L2*weights[j] if j else 0.0))
        if any(not isfinite(x) or abs(x)>MAX_ABS_WEIGHT for x in weights):
            raise ValueError('nonfinite learned Head')
    cpu=process_time_ns()-start
    if cpu<=0:raise ValueError('no actual SGD CPU work')
    return weights,cpu


def fit_one(obs: dict, train_only: dict) -> dict:
    """Four matched physical CPU Heads fitted without heldout truth."""
    labels = verify_train(obs,train_only)
    rows = features(obs)
    units=scales(rows,set(labels))
    held=[r for r in rows if r['group']==train_only['held_group']]
    if not 3<=len(held)<=10 or set(labels)&{r['task_id'] for r in held}:
        raise ValueError('held original-source leakage')
    groups=question_groups(rows,labels)
    if len(groups)!=6:raise ValueError('training group census changed')
    fitted={};meters={};held_probs={}
    for name in METHODS:
        if name==METHODS[0]:
            w,fit_ns=original_brier_train(rows,labels,'centered_scaled_5',units)
        else:
            w,fit_ns=fit_group_risk(rows,labels,float(TAU[name]))
        start=process_time_ns()
        pp=[sigmoid(sum(z*v for z,v in zip(w,design(r,'centered_scaled_5',units),strict=True))) for r in held]
        eval_ns=process_time_ns()-start
        if eval_ns<=0 or any(not 0.0<p<1.0 for p in pp):raise ValueError('invalid actual held CPU readout')
        fitted[name]=w
        held_probs[name]=pp
        meters[name]={'train_cpu_ns':fit_ns,'held_cpu_ns':eval_ns,
                      'physical_parameter_count':PARAMS,'optimizer_updates':STEPS,
                      'training_question_count':6,'training_candidate_count':len(labels)}
    return {
        'schema':SCHEMA,'authority':'DENY_ALL','production_accepted':False,
        'model_selected':False,'incremental_system2_admitted':False,
        'original_model_archive_sha256':ARCHIVE_SHA,
        'original_model_observation_id':OBS_ID,
        'fold':train_only['fold'],'held_source_group':train_only['held_group'],
        'train_only_material_sha256':digest(train_only),
        'held_human_truth_read':False,'real_pretrained_model_forwards_new':0,
        'original_three_group_training_question_count':6,
        'training_steps':STEPS,'temperature_grid_exploratory_after_observing_historical_family':True,
        'methods':list(METHODS),'training_only_scale':list(units),
        'weights':fitted,'meters':meters,
        'held_predictions':[{'task_id':r['task_id'],'source_group':r['group'],
                             'question_slot':r['question'],'candidate_id':r['candidate_id'],
                             'probabilities':{name:held_probs[name][i] for name in METHODS}}
                            for i,r in enumerate(held)],
        'whole_service_cost_certified':False,'future_source_family_gain':False,
        'original_training_label_owner_authenticates_independent_human_rater':False,
    }


def blind_identity(obs:dict) -> dict:
    """Freeze source geometry before any train-label file is opened."""
    rows=features(obs)
    if len(rows)!=33 or len({r['group'] for r in rows})!=4 or len({(r['group'],r['question']) for r in rows})!=8:
        raise ValueError('original 4x8x33 source census changed')
    return {'schema':'hepta.e24.original-pretrained-label-blind-source.v1',
      'authority':'DENY_ALL','production_accepted':False,'label_read':False,
      'source_sha256':ARCHIVE_SHA,'observation_id':OBS_ID,
      'original_groups':sorted({r['group'] for r in rows}),
      'task_ids':[r['task_id'] for r in rows],
      'questions':[{'group':g,'slot':q,'n':sum(r['group']==g and r['question']==q for r in rows)}
                   for g,q in sorted({(r['group'],r['question']) for r in rows})],
      'new_pretrained_forwards':0,'future_generalization_claim':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='mode',required=True)
    a=sub.add_parser('blind');a.add_argument('--archive',required=True);a.add_argument('--output',required=True)
    b=sub.add_parser('train');b.add_argument('--archive',required=True);b.add_argument('--train-only',required=True);b.add_argument('--output',required=True)
    args=p.parse_args();obs=read_prelabel(args.archive)
    if args.mode=='blind':rec=blind_identity(obs)
    else:rec=fit_one(obs,strict_json(Path(args.train_only).read_bytes()))
    print(write_once(args.output,rec),'DENY_ALL')

if __name__=='__main__':main()
