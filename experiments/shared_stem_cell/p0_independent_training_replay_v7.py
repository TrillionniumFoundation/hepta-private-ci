#!/usr/bin/env python3
"""Independent, original-human TRAIN-only, frozen-Encoder Head SGD replay.

Requires original V5 full Head/feature numerical replay and the V6 second-host
cold-Encoder receipt. Re-optimizes the *actual* original evidence and question-
only training tensors in an independent process, without the producing trainer,
pretrained model weights, held test labels, or external effect authority.

This tests reproducibility of the declared 40-step optimization from immutable
frozen initial tensors. It does NOT authenticate model provenance, original
machine execution, hidden train-label ownership, or generalization.
"""
from __future__ import annotations

import argparse
import math
import resource
import time
from pathlib import Path

from p0_multirc_semantic_material import Invalid, canonical, read, save, sha, validate
from p0_multirc_semantic_review import REVISIONS
from p0_physical_replay_v5 import (MODEL_WIDTHS,HEADS,independent_numeric_replay)

SCHEMA='hepta.p0.independent-original-head-sgd-replay.v1'
ALL_SCHEMA='hepta.p0.three-head-sgd-replay.v1'
STEPS=40
SEED=20261015
LR=0.1
TEMPS=(0.5,0.75,1.0,1.5,2.0,3.0)
MAX_TRAINED_DIFFERENCE=3e-5  # predeclared FP32 cross-host BLAS tolerance
MAX_CALIBRATION_CE_GAP=2e-4


def _calibration_loss(x, y, weight, bias, temperature):
    import numpy as np
    logits=(x @ weight.T + bias).astype(np.float64)/temperature
    logits-=logits.max(axis=1,keepdims=True)
    logsum=np.log(np.exp(logits).sum(axis=1))
    return float((logsum-logits[np.arange(len(y)),y]).mean())


def _numpy_independent_first_update(x, labels, weight, bias):
    """Independent analytic cross-entropy SGD step, not Torch autograd/SGD."""
    import numpy as np
    a=np.asarray(x,dtype=np.float64)
    w=np.asarray(weight,dtype=np.float64)
    b=np.asarray(bias,dtype=np.float64)
    y=np.asarray(labels,dtype=np.int64)
    if (a.ndim!=2 or w.shape!=(2,a.shape[1]) or b.shape!=(2,) or
            len(y)!=len(a) or not 0<len(y)<=1024 or
            not np.isfinite(a).all() or not np.isfinite(w).all() or
            not np.isfinite(b).all() or not np.isin(y,[0,1]).all()):
        raise Invalid('independent analytical SGD input invalid')
    logits=a @ w.T + b
    logits-=logits.max(axis=1,keepdims=True)
    probs=np.exp(logits)
    probs/=probs.sum(axis=1,keepdims=True)
    probs[np.arange(len(y)),y]-=1.0
    probs/=len(y)
    next_w=w-LR*(probs.T @ a)
    next_b=b-LR*probs.sum(axis=0)
    return np.asarray(next_w,dtype=np.float32),np.asarray(next_b,dtype=np.float32)


def _proper_training_groups(fit, blind):
    """Build feature-case indices independently of the producing optimizer."""
    validate(fit,blind)
    rows=fit['cases'] + blind['cases']
    ids=[r['case_id'] for r in rows]
    if len(ids)!=len(set(ids)):
        raise Invalid('duplicated full original frozen Encoder feature bank')
    idx={name:i for i,name in enumerate(ids)}
    evidence={}
    question={}
    # Independently reconstruct question/candidate pair identity; do not import
    # the producing trainer's matched_pairs routine as the sole witness.
    paired={}
    for row in rows:
        key=(row['split'],row['source_group'],row['question_id'],row['answer_id'])
        slot=paired.setdefault(key,{})
        if row['condition'] in slot:
            raise Invalid('duplicate source/intervention pair in optimizer input')
        slot[row['condition']]=row
    for slot in paired.values():
        if set(slot)!={'original','no_evidence'}:
            raise Invalid('incomplete paired intervention in optimizer input')
        a,b=slot['original'],slot['no_evidence']
        if (a['joint_input']['question']!=b['joint_input']['question'] or
                a['source_id']!=b['source_id'] or
                a['candidate_text']!=b['candidate_text']):
            raise Invalid('retraining matched mismatched question/evidence task')
    for split in ('train','calibration'):
        original=[r for r in fit['cases'] if r['split']==split and r['condition']=='original']
        ordered_pair={slot['original']['case_id']:slot['no_evidence']
                      for key,slot in paired.items() if key[0]==split}
        if set(ordered_pair)!={r['case_id'] for r in original}:
            raise Invalid('question-only matching did not preserve original label census')
        if any(type(r.get('label')) is not int or r['label'] not in (0,1) for r in original):
            raise Invalid('original train/calibration human labels missing')
        y=[r['label'] for r in original]
        if set(y)!={0,1} or (split=='train' and len(y)<24) or (split=='calibration' and len(y)<8):
            raise Invalid('incomplete original training/calibration target groups')
        evidence[split]=([idx[r['case_id']] for r in original],list(y),[r['case_id'] for r in original])
        question[split]=([idx[ordered_pair[r['case_id']]['case_id']] for r in original],list(y),
                         [ordered_pair[r['case_id']]['case_id'] for r in original])
    return evidence,question,ids


def _check_upstream(upstream_head,upstream_cold,model,source_count):
    if (type(upstream_head) is not dict or
            upstream_head.get('schema')!='hepta.p0.three-pretrained-head-numeric-replay.v1' or
            upstream_head.get('authority')!='DENY_ALL' or
            upstream_head.get('production_promotion_permitted') is not False or
            type(upstream_head.get('models')) is not dict or
            set(upstream_head['models'])!=set(MODEL_WIDTHS)):
        raise Invalid('no complete independently admitted original Head numeric replay')
    if (type(upstream_cold) is not dict or
            upstream_cold.get('schema')!='hepta.p0.three-real-cold-encoder-replay.v1' or
            upstream_cold.get('authority')!='DENY_ALL' or
            upstream_cold.get('production_promotion_permitted') is not False or
            upstream_cold.get('new_original_human_labels_accessed') is not False or
            type(upstream_cold.get('models')) is not dict or
            set(upstream_cold['models'])!=set(MODEL_WIDTHS)):
        raise Invalid('missing independent complete original model cold-forward evidence')
    a=upstream_head['models'][model];b=upstream_cold['models'][model]
    if (a.get('model')!=model or a.get('source_case_count')!=source_count or
            a.get('replayed_original_and_question_head_predictions',0)<=0 or
            a.get('tolerance')!=3e-5 or
            type(a.get('max_probability_disagreement')) not in (int,float) or
            not 0<=a['max_probability_disagreement']<=3e-5 or
            a.get('authority')!='DENY_ALL' or a.get('production_promotion_permitted') is not False or
            b.get('model')!=model or b.get('revision')!=REVISIONS[model] or
            b.get('cold_probed_case_count')!=12 or
            b.get('selection_protocol')!='sha256-panel-source-pair-2-groups-per-split-v1' or
            b.get('registered_max_q24_difference')!=2 or
            type(b.get('max_q24_disagreement')) is not int or
            not 0<=b['max_q24_disagreement']<=2 or
            b.get('source_distinct_pairs_per_split')!=2 or
            b.get('actual_original_checkpoint_loader_invoked_in_second_process') is not True or
            b.get('original_human_held_labels_accessed') is not False or
            b.get('authority')!='DENY_ALL' or b.get('production_promotion_permitted') is not False):
        raise Invalid('prior physical source/head replay census absent or incompatible')


def independently_refit(fit,blind,report,model,replay_dir,upstream_head,upstream_cold):
    """Validate originals, then independently run Torch SGD and NumPy CE checks."""
    import numpy as np
    import torch
    import torch.nn.functional as F
    from safetensors.numpy import load_file

    validate(fit,blind)
    if model not in MODEL_WIDTHS or type(report) is not dict or report.get('model')!=model:
        raise Invalid('refuse unspecified original frozen pretrained Encoder')
    evidence,question,ids=_proper_training_groups(fit,blind)
    _check_upstream(upstream_head,upstream_cold,model,len(ids))
    independent_numeric_replay(replay_dir,fit,blind,report,model=model)
    width=MODEL_WIDTHS[model]
    training=report.get('training')
    prior_report=report.get('matched_question_only_control')
    if type(training) is not dict or type(prior_report) is not dict:
        raise Invalid('missing original SGD or matched prior training record')
    for name,groups,actual_train_key,actual_cal_key in (
        ('evidence',evidence,'fit_train_case_ids_sha256','calibration_case_ids_sha256'),
        ('question_only',question,'train_question_case_ids_sha256','calibration_question_case_ids_sha256')):
        saved=training if name=='evidence' else prior_report
        if (saved.get(actual_train_key)!=sha(canonical(groups['train'][2])) or
                saved.get(actual_cal_key)!=sha(canonical(groups['calibration'][2]))):
            raise Invalid('original or question-only training data inventory does not match frozen material')
    width=MODEL_WIDTHS[model]
    base=Path(replay_dir)
    features=load_file(str(base/'features.safetensors'))['features_q24_fp32']
    heads=load_file(str(base/'heads.safetensors'))
    if features.dtype!=np.float32 or features.shape!=(len(ids),width):
        raise Invalid('missing exact original Q24-derived FP32 feature matrix')
    for head in HEADS:
        if heads[head+'.weight'].dtype!=np.float32 or heads[head+'.bias'].dtype!=np.float32:
            raise Invalid('retraining input Head tensor precision mismatch')
    # Both original and prior Heads must truly share exactly the same original
    # initialization; independently check original RNG state against Torch 2.10.
    torch.set_num_threads(1)
    torch.manual_seed(SEED)
    seeded=torch.nn.Linear(width,2)
    seeded_weight=seeded.weight.detach().cpu().contiguous().numpy()
    seeded_bias=seeded.bias.detach().cpu().contiguous().numpy()
    for head in ('evidence_frozen','question_frozen'):
        if (not np.array_equal(seeded_weight,heads[head+'.weight']) or
                not np.array_equal(seeded_bias,heads[head+'.bias'])):
            raise Invalid('frozen Head is not the actual registered seeded initialization')
    if (not np.array_equal(heads['evidence_frozen.weight'],heads['question_frozen.weight']) or
            not np.array_equal(heads['evidence_frozen.bias'],heads['question_frozen.bias'])):
        raise Invalid('two candidate arms did not actually start from identical Head parameters')
    results={}
    began=time.perf_counter_ns();begin_cpu=time.process_time_ns()
    for name,groups,ref in (('evidence',evidence,report.get('control')),
                            ('question_only',question,(report.get('matched_question_only_control') or {}).get('complete_prior_controls'))):
        if not isinstance(ref,dict):raise Invalid('missing recorded real learning comparison')
        train_indices,train_labels,train_ids=groups['train']
        cal_indices,cal_labels,cal_ids=groups['calibration']
        x_train=torch.from_numpy(features[train_indices].copy())
        x_cal=torch.from_numpy(features[cal_indices].copy())
        y_train=torch.tensor(train_labels,dtype=torch.long)
        y_cal=torch.tensor(cal_labels,dtype=torch.long)
        torch.manual_seed(SEED)
        layer=torch.nn.Linear(width,2)
        old_w=layer.weight.detach().cpu().numpy().copy()
        old_b=layer.bias.detach().cpu().numpy().copy()
        if not np.array_equal(old_w,heads[name.replace('question_only','question')+'_frozen.weight']) or not np.array_equal(old_b,heads[name.replace('question_only','question')+'_frozen.bias']):
            raise Invalid('fresh independent initialization differs from original')
        optimizer=torch.optim.SGD(layer.parameters(),lr=LR)
        t0=time.perf_counter_ns()
        losses=[]
        independent_first=_numpy_independent_first_update(features[train_indices],train_labels,old_w,old_b)
        first_gradient_difference=None
        for step in range(STEPS):
            optimizer.zero_grad(set_to_none=True)
            loss=F.cross_entropy(layer(x_train),y_train)
            if not bool(torch.isfinite(loss).item()):
                raise Invalid('replayed original-training step went nonfinite')
            losses.append(float(loss.detach().cpu()))
            loss.backward()
            optimizer.step()
            if step==0:
                first_gradient_difference=max(float(np.max(np.abs(layer.weight.detach().cpu().numpy()-independent_first[0]))),
                                              float(np.max(np.abs(layer.bias.detach().cpu().numpy()-independent_first[1]))))
                if not math.isfinite(first_gradient_difference) or first_gradient_difference>MAX_TRAINED_DIFFERENCE:
                    raise Invalid('independent analytic SGD gradient disagrees with Torch actual first update')
        train_ms=(time.perf_counter_ns()-t0)/1e6
        prefix='evidence' if name=='evidence' else 'question'
        final_w=layer.weight.detach().cpu().contiguous().numpy()
        final_b=layer.bias.detach().cpu().contiguous().numpy()
        deviations=[float(np.max(np.abs(final_w-heads[prefix+'_trained.weight']))),
                    float(np.max(np.abs(final_b-heads[prefix+'_trained.bias'])))]
        maximum=max(deviations)
        if not math.isfinite(maximum) or maximum>MAX_TRAINED_DIFFERENCE:
            raise Invalid('stored final Head not reproducible by an independent forty-step original-target SGD')
        # Validate the reported temperature against ALL original calibration
        # rows. Nearly equal temperatures remain permissible within the pre-
        # declared cross-host FP32 numerical CE tolerance.
        calibr=ref['trained_head' if name=='evidence' else 'question_trained_head']
        saved_temp=calibr.get('temperature')
        if type(saved_temp) not in (int,float) or saved_temp not in TEMPS:
            raise Invalid('calibration temperature outside registered TRAIN-only grid')
        x=features[cal_indices].astype(np.float32,copy=False)
        y=np.asarray(cal_labels,dtype=np.int64)
        losses_cal={str(t):_calibration_loss(x,y,final_w,final_b,t) for t in TEMPS}
        if losses_cal[str(float(saved_temp))]>min(losses_cal.values())+MAX_CALIBRATION_CE_GAP:
            raise Invalid('recorded calibration temperature inconsistent with actual independent SGD')
        control=ref['frozen_head' if name=='evidence' else 'question_frozen_head']
        if control.get('head_sha256')==calibr.get('head_sha256') or maximum<0:
            raise Invalid('failed genuine learned/frozen distinction')
        results[name]={'training_original_labels_only':True,'training_case_count':len(train_indices),
                       'calibration_case_count':len(cal_indices),'steps_replayed':STEPS,
                       'optimizer':'torch.optim.SGD','registered_learning_rate':LR,
                       'train_source_case_ids_sha256':sha(canonical(train_ids)),
                       'calibration_source_case_ids_sha256':sha(canonical(cal_ids)),
                       'max_original_final_head_parameter_difference':maximum,
                       'max_torch_vs_analytic_first_update_difference':first_gradient_difference,
                       'registered_tolerance':MAX_TRAINED_DIFFERENCE,
                       'loss_at_step_1':losses[0], 'loss_at_step_40':losses[-1],
                       'recorded_temperature':float(saved_temp),
                       'recomputed_min_calibration_cross_entropy':min(losses_cal.values()),
                       'replay_train_wall_ms':train_ms}
    return {'schema':SCHEMA,'model':model,'revision':REVISIONS[model],
            'original_feature_count':len(ids),
            'independently_replayed_optimizer_proposals':2,
            'stored_training_updates_replayed':2*STEPS,
            'model_weights_reloaded_by_this_optimizer_replay':False,
            'held_original_human_labels_opened':False,
            'source_and_training_labels_independently_signed':False,
            'optimizer_origin_physically_attested':False,
            'full_pretrained_effectiveness_proven':False,
            'independent_torch_version':torch.__version__,
            'independent_numpy_version':np.__version__,
            'retraining_audit_cpu_ms':(time.process_time_ns()-begin_cpu)/1e6,
            'retraining_audit_wall_ms':(time.perf_counter_ns()-began)/1e6,
            'retraining_audit_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            'arms':results,'production_promotion_permitted':False,
            'authority':'DENY_ALL'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('fit','blind','granite-97m-r2','mmbert-small','embeddinggemma-2-text',
              'head-replay','cold-replay','output'):
        p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--replay-root',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():raise FileExistsError('optimizer replay output must be create-only')
    fit,blind=read(args.fit),read(args.blind)
    validate(fit,blind)
    head=read(args.head_replay);cold=read(args.cold_replay)
    files={'granite_97m_r2':args.granite_97m_r2,
           'mmbert_small':args.mmbert_small,
           'embeddinggemma_2_text':args.embeddinggemma_2_text}
    result={}
    for model,path in files.items():
        result[model]=independently_refit(fit,blind,read(path),model,
                           args.replay_root/f'{model}.replay',head,cold)
    save(args.output,{'schema':ALL_SCHEMA,'models':result,
                      'independent_original_human_held_labels_opened':False,
                      'real_model_weights_loaded_by_this_job':False,
                      'original_training_actor_self_attested':False,
                      'model_winner_selected':False,'production_promotion_permitted':False,
                      'authority':'DENY_ALL'})

if __name__=='__main__':main()
