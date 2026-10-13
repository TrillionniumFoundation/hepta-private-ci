"""Prototype-routed frozen Cells with separate old-retention and new-usefulness.

All fourteen inherited controls remain. Prior gates retain their own decisions;
this stage adds a stricter descriptive selector, never a production promotion.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
from pathlib import Path
import time

import torch
from safetensors.torch import load

from cell_conditional_study import (ALL_ARMS as INHERITED, close_tree, implementation,
    load_references, review as review_parent, score_rows, tensor_file)
from cell_consolidation_study import source_features
from cell_prototype_gate import (ARMS, FOLDS, SHRINKAGES, TEMPERATURES, JointFloor,
    fit_geometry_candidates, geometry_logits, joint_select)
from development_study import prepare_views
from development_study_data import digest, phase, write_once
from development_study_replay import read_bytes, record

ALL_ARMS = INHERITED + ARMS


def references(rows, features, origin, baseline, anchor_run, conditional_run):
    hidden = [{k:v for k,v in r.items() if k!='label' or phase(r)!='held_out'} for r in rows]
    report = review_parent(hidden, features, origin, baseline, anchor_run, conditional_run, score_held_out=False)
    teachers, _, config, source = load_references(hidden, features, origin, baseline, anchor_run)
    run, sha = record(Path(conditional_run)/'run.json')
    selection, selection_sha = record(Path(conditional_run)/'selection.json')
    preds, pred_sha = record(Path(conditional_run)/'predictions.json', 16_777_216)
    if sha != report['run_sha256'] or pred_sha != run['predictions_sha256'] or selection_sha != run['selection_sha256']:
        raise ValueError('conditional source changed after review')
    source.update(conditional_run_sha256=sha, conditional_costs=selection['costs'])
    logits = {n:torch.tensor([p['logits'] for p in preds if p['arm']==n]) for n in INHERITED}
    return {n:teachers[n] for n in ('frozen','new_only')}, config, source, logits


def packets(candidates):
    return {n:({k:v for k,v in candidates['all_old' if n.endswith('all_old') else 'memory'].items()
                 if n.startswith('prototype_') or k.startswith('routing_')}) for n in ARMS}


def evidence_rows(logits, inputs, ids):
    return [{'arm':n, 'sample_id':inputs[i]['sample_id'], 'input_fingerprint':inputs[i]['input_fingerprint'], 'logits':v}
            for n in ALL_ARMS for i,v in zip(ids,logits[n].tolist())]


def execute(rows, features, origin, baseline, anchor_run, conditional_run, output):
    start = time.process_time_ns(), time.perf_counter_ns()
    teachers, config, source, inherited = references(rows, features, origin, baseline, anchor_run, conditional_run)
    inputs,_ = prepare_views(rows); truth = {r['sample_id']:r['label'] for r in rows if phase(r) in ('base','adapt')}
    folder = Path(output); folder.mkdir(parents=True, exist_ok=False)
    plan_sha = write_once(folder/'plan.json', {'schema':'hepta.cell.prototype-plan.v1', 'source':source,
        'config':asdict(config), 'arms':ALL_ARMS, 'shrinks':SHRINKAGES, 'temperatures':TEMPERATURES,
        'folds':FOLDS, 'joint_floor':asdict(JointFloor()), 'input_digest':digest(inputs),
        'implementation':implementation(), 'production_authorized':False})
    try:
        models, mean, scale, costs = fit_geometry_candidates(inputs, truth, features, config, teachers)
        models = packets(models)
        # Seal train-only parameters/CV before ANY new calibration decision or held-out prediction.
        inventory = {n:tensor_file(folder,n,t) for n,t in models.items()}
        training_sha = write_once(folder/'training.json', costs)
        ids = [i for i,r in enumerate(rows) if phase(r) in ('calibration','held_out')]
        cal = [j for j,i in enumerate(ids) if phase(rows[i])=='calibration']; ci = [ids[j] for j in cal]
        cal_logits = {n:v[cal] for n,v in inherited.items()}
        for n,t in models.items(): cal_logits[n] = geometry_logits(t,(features[ci]-mean)/scale,config,conditional=n.startswith('prototype_'))
        scores = score_rows(cal_logits,rows,ci,config); decision = joint_select(scores,config)
        selection_sha = write_once(folder/'selection.json', {**decision, 'calibration_metrics':scores, 'checkpoints':inventory})
        logits = dict(inherited)
        for n,t in models.items(): logits[n] = geometry_logits(t,(features[ids]-mean)/scale,config,conditional=n.startswith('prototype_'))
        result = {'schema':'hepta.cell.prototype-run.v1', 'plan_sha256':plan_sha,
            'training_sha256':training_sha, 'selection_sha256':selection_sha,
            'predictions_sha256':write_once(folder/'predictions.json',evidence_rows(logits,inputs,ids)),
            'current_encoder_calls':0, 'production_authorized':False,
            'cpu_ns':time.process_time_ns()-start[0], 'wall_ns':time.perf_counter_ns()-start[1]}
        write_once(folder/'run.json',result); return result
    except Exception as error:
        write_once(folder/'FAILED.json', {'error_type':type(error).__name__,'message':str(error)}); raise


def independent_forward(t, x, config, conditional):
    """Separate affine/log-normalization expression; does not call the new forward."""
    routing = x @ t['routing_weight'].T+t['routing_bias']
    if not torch.isfinite(routing).all(): raise ValueError('nonfinite replayed routing')
    if not conditional: return routing
    expert = x @ t['weight'].T+t['bias']
    columns = (list(config.old_classes),[i for i in range(config.classes) if i not in config.old_classes])
    mass = torch.stack([torch.logsumexp(routing[:,cols],-1) for cols in columns],1)
    mass = mass-mass.max(1,keepdim=True).values
    mass = mass-torch.logsumexp(mass,1,keepdim=True)
    out = torch.empty_like(routing)
    for j,cols in enumerate(columns):
        block = expert[:,cols]
        block = block-block.max(1,keepdim=True).values
        out[:,cols] = block-torch.logsumexp(block,-1,keepdim=True)+mass[:,j,None]
    if not torch.isfinite(out).all(): raise ValueError('nonfinite replayed probabilities')
    return out


def review(rows, features, origin, baseline, anchor_run, conditional_run, output):
    start = time.process_time_ns(), time.perf_counter_ns(); folder = Path(output)
    if (folder/'FAILED.json').exists(): raise ValueError('failed prototype run')
    teachers, config, source, inherited = references(rows,features,origin,baseline,anchor_run,conditional_run)
    run,run_sha = record(folder/'run.json'); plan,plan_sha = record(folder/'plan.json')
    selection,sel_sha = record(folder/'selection.json'); training,training_sha = record(folder/'training.json')
    preds,pred_sha = record(folder/'predictions.json',16_777_216); inputs,_ = prepare_views(rows)
    if (run['schema']!='hepta.cell.prototype-run.v1' or plan['schema']!='hepta.cell.prototype-plan.v1'
        or run['production_authorized'] is not False or plan['production_authorized'] is not False or run['current_encoder_calls']!=0
        or (plan_sha,sel_sha,training_sha,pred_sha)!=(run['plan_sha256'],run['selection_sha256'],run['training_sha256'],run['predictions_sha256'])
        or plan['source']!=source or plan['input_digest']!=digest(inputs) or plan['implementation']!=implementation()
        or digest(plan['config'])!=digest(asdict(config)) or plan['arms']!=list(ALL_ARMS)
        or plan['shrinks']!=list(SHRINKAGES) or plan['temperatures']!=list(TEMPERATURES) or plan['folds']!=FOLDS
        or plan['joint_floor']!=asdict(JointFloor()) or set(selection['checkpoints'])!=set(ARMS)):
        raise ValueError('prototype source or protocol binding changed')
    truth = {r['sample_id']:r['label'] for r in rows if phase(r) in ('base','adapt')}
    # Training replay uses the SAME deterministic statistics routine, explicitly not an independent algorithm.
    expected,mean,scale,costs = fit_geometry_candidates(inputs,truth,features,config,teachers); expected = packets(expected)
    if set(training)!=set(costs) or set(training['arms'])!=set(costs['arms']): raise ValueError('training census changed')
    for scope in (training,*training['arms'].values()):
        for key in ('cpu_ns','wall_ns'):
            if type(scope[key]) is not int or scope[key]<0: raise ValueError('invalid measured time')
    for name,cost in costs['arms'].items():
        for key,value in cost.items():
            if key not in ('cpu_ns','wall_ns'): close_tree(training['arms'][name][key],value)
    close_tree(training['current_encoder_calls'],0)
    ids = [i for i,r in enumerate(rows) if phase(r) in ('calibration','held_out')]
    x = (features[ids]-mean)/scale; logits = dict(inherited)
    for name in ARMS:
        raw = read_bytes(folder/f'{name}.safetensors',1_048_576)
        if hashlib.sha256(raw).hexdigest()!=selection['checkpoints'][name]: raise ValueError('prototype checkpoint changed')
        t = load(raw)
        if set(t)!=set(expected[name]) or any(not torch.equal(v,expected[name][n]) or v.dtype!=torch.float32 for n,v in t.items()):
            raise ValueError('training-derived prototype tensors do not reproduce')
        logits[name] = independent_forward(t,x,config,name.startswith('prototype_'))
    expected_rows = evidence_rows(logits,inputs,ids)
    if type(preds) is not list or len(preds)!=len(expected_rows): raise ValueError('prediction census changed')
    maximum = 0.
    for p,e in zip(preds,expected_rows):
        if type(p) is not dict or set(p)!=set(e) or any(p[k]!=e[k] for k in e if k!='logits') or type(p['logits']) is not list or any(type(v) not in (int,float) for v in p['logits']):
            raise ValueError('prediction identity changed')
        a,b = torch.tensor(p['logits']),torch.tensor(e['logits'])
        if a.shape!=b.shape or not torch.isfinite(a).all(): raise ValueError('invalid stored logits')
        error = float((a-b).abs().max()); maximum = max(maximum,error)
        if error>1e-5 or a.argmax()!=b.argmax(): raise ValueError('prototype prediction does not reproduce')
    scores = {}
    for part in ('calibration','held_out'):
        js = [j for j,i in enumerate(ids) if phase(rows[i])==part]
        scores[part] = score_rows({n:v[js] for n,v in logits.items()},rows,[ids[j] for j in js],config)
    decision = joint_select(scores['calibration'],config)
    close_tree(selection, {**decision,'calibration_metrics':scores['calibration'],'checkpoints':selection['checkpoints']})
    return {'schema':'hepta.cell.prototype-review.v1','run_sha256':run_sha,**decision,'scores':scores,
        'prediction_rows':len(preds),'unique_held_out_inputs':sum(phase(r)=='held_out' for r in rows),
        'max_abs_logit_error':maximum,'argmax_reversals':0,'current_encoder_calls':0,
        'verification_cpu_ns':time.process_time_ns()-start[0], 'verification_wall_ns':time.perf_counter_ns()-start[1]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-run','dataset','consolidation-run','anchor-run','conditional-run','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--review-run',type=Path)
    args = parser.parse_args(); torch.set_num_threads(2)
    rows,features,origin = source_features(args.source_run,args.dataset)
    values = (rows,features,origin,args.consolidation_run,args.anchor_run,args.conditional_run)
    if args.review_run: write_once(args.output,review(*values,args.review_run))
    else: execute(*values,args.output)
