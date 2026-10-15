#!/usr/bin/env python3
"""Research-only nested source-group budget Head learning curves (DENY_ALL).

Consumes an already independently reviewed E1 snapshot. Never accesses held
labels, retrains the original Encoder, or changes production authority.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import time
import numpy as np
import torch
from safetensors.numpy import load_file, save_file

from e1_matched_gated_head import MatchedHead, STEPS, LR, TEMPERATURES, PARAMETERS, SEEDS, state_digest

SCHEMA='hepta.e3.source-group-learning-curve.v1'
BUDGETS=(4, 8, 12)
KINDS=('additive', 'gated')


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf8')


def sha(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()


def group_plan(fit_rows, blind_rows, panel_id):
    """Use ONLY source identity, never labels, to precommit nested budgets."""
    if type(panel_id) is not str or len(panel_id)!=64:
        raise ValueError('original panel ID required')
    if type(fit_rows) is not list or type(blind_rows) is not list:
        raise ValueError('original typed fit/blind source required')
    def selected(split, rows):
        return [(i,r) for i,r in enumerate(rows)
                if r.get('split')==split and r.get('condition')=='original']
    train=selected('train',fit_rows)
    cal=selected('calibration',fit_rows)
    held=selected('test',blind_rows)
    tg={r.get('source_group') for _,r in train}
    cg={r.get('source_group') for _,r in cal}
    hg={r.get('source_group') for _,r in held}
    if (None in tg|cg|hg or len(tg)!=12 or len(cg)!=4 or len(hg)!=8 or
        tg&cg or tg&hg or cg&hg or len(train)<24 or len(cal)<8 or not held):
        raise ValueError('original passage census not complete/source-disjoint')
    # IMPORTANT: panel_id is a digest of the ENTIRE fit panel, including TRAIN
    # labels. Using it to salt budget order would make the selection implicitly
    # label-dependent. The immutable source_group is derived from original
    # passage text only; freeze a fixed, domain-separated ordering instead.
    ordered=sorted(tg,key=lambda g:(hashlib.sha256(
        b'hepta.e3.original-source-group-nolabel.v2\0' + g.encode('utf8')
    ).hexdigest(),g))
    cal_idx=[i for i,_ in cal]
    held_idx=list(range(len(fit_rows),len(fit_rows)+len(blind_rows)))
    if any(type(r.get('label')) is not int or r['label'] not in (0,1) for _,r in train+cal):
        raise ValueError('TRAIN/CAL authentic binary labels required')
    if set(r['label'] for _,r in cal)!={0,1} or set(r['label'] for _,r in train)!={0,1}:
        raise ValueError('original complete TRAIN/CAL label support insufficient')
    budgets={}
    for n in BUDGETS:
        permitted=set(ordered[:n])
        idx=[i for i,r in train if r['source_group'] in permitted]
        labels=[fit_rows[i]['label'] for i in idx]
        budgets[str(n)]={'train_indices':idx, 'train_labels':labels,
                         'train_groups':ordered[:n],
                         'status':'qualifiable' if set(labels)=={0,1} else 'missing_both_labels'}
    if budgets['12']['train_indices']!=[i for i,_ in train]:
        raise ValueError('complete budget fails original E1 TRAIN row parity')
    return {'source_group_order':ordered,'selection':'sha256(fixed-domain:source_group)-ascending-label-independent-v2',
            'calibration_indices':cal_idx,'calibration_labels':[r['label'] for _,r in cal],
            'blind_indices':held_idx,'budgets':budgets}


def forward_study(features, parent, rows, blind, panel_id):
    """Physical CPU Head training on ORIGINAL E1 frozen initial weights."""
    if (not isinstance(features,np.ndarray) or features.dtype!=np.float32 or
        features.ndim!=2 or features.shape[1] not in (256,384,768) or
        len(features)!=len(rows)+len(blind) or not np.isfinite(features).all()):
        raise ValueError('original FP32 encoded feature bank missing')
    plan=group_plan(rows,blind,panel_id)
    projection=parent.get('shared_projection')
    if (not isinstance(projection,np.ndarray) or projection.dtype!=np.float32 or
        projection.shape!=(features.shape[1],128) or not np.isfinite(projection).all()):
        raise ValueError('wrong original frozen E1 projection tensor')
    expected={'shared_projection'} | {f'seed{s}.{a}.{k}' for s in SEEDS
              for a in ('frozen_additive','trained_additive','frozen_gated','trained_gated')
              for k in ('a.weight','a.bias','b.weight','b.bias','out.weight','out.bias')}
    if set(parent)!=expected:
        raise ValueError('missing original E1 tensor inventory')
    previous_threads=torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        return _forward_study(features,parent,plan,panel_id)
    finally:
        torch.set_num_threads(previous_threads)


def _forward_study(features,parent,plan,panel_id):
    start=time.perf_counter_ns();start_cpu=time.process_time_ns()
    with torch.no_grad():
        projected=torch.from_numpy(features) @ torch.from_numpy(parent['shared_projection'])
    projection_ms=(time.perf_counter_ns()-start)/1e6
    projection_cpu_ms=(time.process_time_ns()-start_cpu)/1e6
    cal_x=projected[plan['calibration_indices']]
    cal_y=torch.tensor(plan['calibration_labels'],dtype=torch.float32)
    blind_x=projected[plan['blind_indices']]
    records=[]; saved={}
    for budget in BUDGETS:
        sub=plan['budgets'][str(budget)]
        idx=sub['train_indices']
        if sub['status']!='qualifiable':
            records.extend({'budget_source_groups':budget,'seed':seed,'architecture':kind,
                            'status':'missing_both_labels', 'training_rows':len(idx),
                            'optimizer_updates':0,'blind_predictions':None}
                           for seed in SEEDS for kind in KINDS)
            continue
        train_x=projected[idx]
        train_y=torch.tensor(sub['train_labels'],dtype=torch.float32)
        for seed in SEEDS:
            for kind in KINDS:
                head=MatchedHead(kind)
                init={key:torch.from_numpy(parent[f'seed{seed}.frozen_{kind}.{key}'].copy())
                      for key in head.state_dict()}
                head.load_state_dict(init, strict=True)
                initial_hash=state_digest(head.state_dict())
                start=time.perf_counter_ns();cpu=time.process_time_ns()
                optimizer=torch.optim.SGD(head.parameters(),lr=LR)
                for _ in range(STEPS):
                    optimizer.zero_grad(set_to_none=True)
                    loss=torch.nn.functional.binary_cross_entropy_with_logits(head(train_x),train_y)
                    if not torch.isfinite(loss).item():
                        raise ValueError('nonfinite physical HEAD training loss')
                    loss.backward()
                    if any(p.grad is None or not torch.isfinite(p.grad).all().item()
                           for p in head.parameters()):
                        raise ValueError('missing physical gradient for active Head parameter')
                    optimizer.step()
                train_ms=(time.perf_counter_ns()-start)/1e6
                train_cpu_ms=(time.process_time_ns()-cpu)/1e6
                final_hash=state_digest(head.state_dict())
                if final_hash==initial_hash:
                    raise ValueError('purported trained Head did not change')
                with torch.inference_mode():
                    cl=head(cal_x)
                    losses=[float(torch.nn.functional.binary_cross_entropy_with_logits(cl/temp,cal_y))
                            for temp in TEMPERATURES]
                    temp=TEMPERATURES[min(range(len(losses)), key=losses.__getitem__)]
                    logits=head(blind_x)
                    preds=torch.sigmoid(logits/temp)
                    if not torch.isfinite(preds).all().item():
                        raise ValueError('nonfinite original held logits')
                saved.update({f'b{budget}.seed{seed}.{kind}.{name}':value.detach().cpu().numpy().copy()
                              for name,value in head.state_dict().items()})
                if budget==12:
                    for k,v in head.state_dict().items():
                        original=parent[f'seed{seed}.trained_{kind}.{k}']
                        if not np.allclose(v.detach().numpy(),original,rtol=0,atol=1e-6):
                            raise ValueError('full-budget physical Head is NOT the original E1 result')
                records.append({'budget_source_groups':budget,'seed':seed,'architecture':kind,
                                'status':'trained', 'initial_sha256':initial_hash,
                                'final_sha256':final_hash, 'head_parameter_count':PARAMETERS,
                                'optimizer_updates':STEPS,'training_rows':len(idx),
                                'train_row_exposures':STEPS*len(idx),
                                'train_wall_ms':train_ms, 'train_cpu_ms':train_cpu_ms,
                                'temperature':temp,'blind_predictions':preds.tolist()})
    report_plan={**plan, 'budgets': {n: {k:v for k,v in b.items() if k!='train_labels'}
                                     for n,b in plan['budgets'].items()}}
    report_plan.pop('calibration_labels',None)
    return ({'schema':SCHEMA,'panel_id':panel_id,
             'original_input_features_sha256':hashlib.sha256(features.tobytes(order='C')).hexdigest(),
             'original_shared_projection_sha256':hashlib.sha256(parent['shared_projection'].tobytes(order='C')).hexdigest(),
             'plan':report_plan,'records':records,
             'projection_extra_physical_forwards':1,'projection_extra_mac':len(features)*features.shape[1]*128,
             'projection_extra_fp32_bytes':int(projected.numel()*4),
             'projection_wall_ms':projection_ms,'projection_cpu_ms':projection_cpu_ms,
             'additional_encoder_loads':0,'additional_encoder_forwards':0,
             'equal_full_lifecycle_cost_certified':False,'original_human_held_labels_read':False,
             'statistical_winner_selected':False,'production_promotion_permitted':False,
             'authority':'DENY_ALL'},saved)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for field in ('fit','blind','original-report','replay-dir','e1-probe-dir','e1-numeric-review','output-dir'):
        ap.add_argument('--'+field,type=Path,required=True)
    ap.add_argument('--model',choices=('granite_97m_r2','mmbert_small','embeddinggemma_2_text'),required=True)
    ap.add_argument('--candidate-head-sha',required=True)
    ap.add_argument('--candidate-run-id',type=int,required=True)
    a=ap.parse_args()
    from p0_multirc_semantic_material import read,validate
    from p0_physical_replay_v5 import independent_numeric_replay
    from e2_seal_blind_predictions import seal
    fit,blind,original=read(a.fit),read(a.blind),read(a.original_report)
    rows,held=validate(fit,blind)
    prior=independent_numeric_replay(a.replay_dir,fit,blind,original,model=a.model)
    e1=read(a.e1_probe_dir/'COMMITTED.json'); numeric=read(a.e1_numeric_review)
    if e1.get('original_numeric_replay')!=prior:
        raise ValueError('original E1 did not originate from pinned pretrained P0 replay')
    seal(blind,e1,numeric,a.model,a.candidate_head_sha,a.candidate_run_id)
    features=load_file(str(a.replay_dir/'features.safetensors'))['features_q24_fp32']
    e1_params=load_file(str(a.e1_probe_dir/'probe.safetensors'))
    result,trained=forward_study(features,e1_params,rows,held,fit['metadata']['panel_id'])
    result.update({'model':a.model,'original_e1_probe_sha256':sha(e1),
                   'original_e1_numeric_sha256':sha(numeric),
                   'original_fit_sha256':sha(fit),'original_blind_sha256':sha(blind),
                   'p0_original_report_sha256':sha(original),
                   'candidate_head_sha':a.candidate_head_sha,'candidate_run_id':a.candidate_run_id})
    a.output_dir.mkdir(parents=True,exist_ok=False,mode=0o700)
    weight=a.output_dir/'trained-heads.safetensors'
    save_file(trained,str(weight))
    with weight.open('rb') as fp:os.fsync(fp.fileno())
    result['e3_trained_weights_sha256']=hashlib.sha256(weight.read_bytes()).hexdigest()
    with (a.output_dir/'COMMITTED.json').open('xb') as fp:
        fp.write(canonical(result)+b'\n');fp.flush();os.fsync(fp.fileno())
    fd=os.open(a.output_dir,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


if __name__=='__main__':main()
