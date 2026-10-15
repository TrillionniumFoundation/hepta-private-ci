"""Train physical Top-1 sparse Cell Heads against a fully trained single-Head control.

Research-only; V1 pinned source owners, public retrospective AG News, DENY_ALL.
Each learned arm performs exactly one 7,434p expert forward per training row,
20 old-source and 20 mixed-source SGD steps. The *resident* budget is 14,868
parameters, including unused/dormant capacity in the single-Head baseline.
This does NOT mean equal backward FLOPs, router operations or lifecycle cost.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import resource
import sys
import time
from pathlib import Path

import torch
from torch.nn import functional as F

import p1_real_granite_cohort as p1
import p2_real_cell_split as p2

SCHEMA='hepta.p2.physically-trained-one-active-equal-resident.v1'
ARMS=('frozen_single','single_active','fixed_top1','adaptive_top1')
MATCHED=('single_active','fixed_top1','adaptive_top1')
MAC_PER_EXPERT=384*8+64*8+8*384+384*2
HEAD_ROWS_TRAIN=20*64+20*128
HEAD_ROWS_DIAGNOSTIC=128
HEAD_ROWS_EVAL=96
TOLERANCE=4e-5


def require(cond, reason):
    if not cond: raise ValueError(reason)


def digest(doc):
    return hashlib.sha256(json.dumps(doc,sort_keys=True,separators=(',',':'),
            ensure_ascii=False,allow_nan=False).encode('utf8')).hexdigest()


def resident(model):
    return sum(x.numel() for x in model.parameters())


def expert_bytes(model, index):
    h=hashlib.sha256()
    for name,p in sorted(model.named_parameters()):
        h.update(name.encode()+b'\0')
        h.update(p.detach()[index].cpu().contiguous().numpy().astype('<f4',copy=False).tobytes())
    return h.hexdigest()


def trained_weights(model):
    result={}
    for name,p in model.named_parameters():
        v=p.detach().cpu().contiguous().numpy().astype('<f4',copy=False)
        result[name]={'shape':list(v.shape),'bytes_le_hex':v.tobytes().hex()}
    return result


def sparse_head(model, inputs, *, selected):
    """Autograd-preserving grouped expert dispatch; NEVER calls model.forward().

    A missing expert has no activation, no bias call and no differentiable edge.
    `index_copy` scatters each physical selected group to the original row order.
    """
    require(isinstance(model,p2.TwoHeads) and isinstance(inputs,torch.Tensor)
        and inputs.ndim==2 and inputs.shape[1]==384 and inputs.dtype==torch.float32
        and inputs.device.type=='cpu' and not inputs.requires_grad
        and bool(torch.isfinite(inputs).all()),'frozen 384D FP32 feature and physical two-Head bank required')
    require(isinstance(selected,torch.Tensor) and selected.shape==(len(inputs),)
        and selected.dtype==torch.long and selected.device.type=='cpu'
        and bool(torch.all((selected==0)|(selected==1))),
        'bounded registered exactly-one-expert selection required')
    out=torch.empty((len(inputs),2),dtype=torch.float32)
    counts=[0,0]; calls=0
    for expert in range(2):
        indices=(selected==expert).nonzero(as_tuple=False).flatten()
        if indices.numel()==0:continue
        xx=inputs.index_select(0,indices)
        down=xx @ model.down[expert]
        gate=torch.sigmoid(xx[:,:64] @ model.gate[expert]+model.g_bias[expert])
        delta=(F.silu(down)*gate) @ model.up[expert]
        output=(xx+delta) @ model.out[expert]+model.out_bias[expert]
        out=out.index_copy(0,indices,output)
        counts[expert]=len(indices);calls+=1
    require(sum(counts)==len(inputs) and 1<=calls<=2,
            'missing or repeated physical single-expert Head rows')
    return out,counts,calls


def select_indices(x, mode, *, cutoff, split):
    require(mode in ARMS and type(split) is bool,'registered trained Head arm only')
    if mode=='fixed_top1' or (mode=='adaptive_top1' and split):
        return (x[:,0]>=cutoff).long()
    return torch.zeros(len(x),dtype=torch.long)


def train_arm(initial, x, y, heldout, *, mode, cutoff):
    require(mode in ARMS and x.shape==(128,384) and y.shape==(128,)
            and heldout.shape==(96,384) and not x.requires_grad
            and x.dtype==heldout.dtype==torch.float32 and type(cutoff) is float
            and math.isfinite(cutoff),'exact 128/96 source-bound learning material required')
    model=copy.deepcopy(initial)
    require(resident(model)==14868,'exact two 7434-scalar resident Head slots required')
    initial_sha=p2.shape_hash(dict(model.named_parameters()))
    before_slot1=expert_bytes(model,1)
    optimizer=torch.optim.SGD(model.parameters(),lr=.15)
    split=(mode=='fixed_top1'); updates=0;exposures=0
    train_counts=[0,0]; diagnostic_counts=[0,0]; loss_trace=[];train_calls=0;diag_calls=0
    begin_cpu=time.process_time_ns();begin_wall=time.perf_counter_ns()

    def fit_batch(bx,by):
        nonlocal updates,exposures,train_calls
        optimizer.zero_grad(set_to_none=True)
        ix=select_indices(bx,mode,cutoff=cutoff,split=split)
        logits,rows,calls=sparse_head(model,bx,selected=ix)
        loss=F.cross_entropy(logits,by)
        require(bool(torch.isfinite(loss)),'nonfinite trained Top-1 loss')
        loss.backward()
        # Required: inactive expert never receives effective gradient.
        for expert in range(2):
            if rows[expert]==0:
                for p in model.parameters():
                    g=p.grad
                    require(g is None or bool(torch.all(g[expert]==0)),
                            'unselected expert received nonzero gradient')
        optimizer.step()
        updates+=1;exposures+=len(bx);train_calls+=calls
        for expert in range(2):train_counts[expert]+=rows[expert]
        loss_trace.append(float(loss.detach()))

    if mode!='frozen_single':
        for _ in range(20):fit_batch(x[:64],y[:64])
    with torch.no_grad():
        probs=[]
        for bx in (x[:64],x[64:]):
            selected=select_indices(bx,mode,cutoff=cutoff,split=split)
            logits,count,calls=sparse_head(model,bx,selected=selected)
            diag_calls+=calls
            diagnostic_counts[0]+=count[0];diagnostic_counts[1]+=count[1]
            probs.append(torch.softmax(logits,dim=1)[:,1])
        old=float(((probs[0]-y[:64].float())**2).mean())
        new=float(((probs[1]-y[64:].float())**2).mean())
    excess=new-old
    parent_copy=0.0;migration_bytes=0;parity_head_rows=0;parity_head_calls=0
    if mode=='adaptive_top1' and excess>p2.SPLIT_THRESHOLD:
        with torch.no_grad():
            sample=x[:4]
            old_logits,old_rows,old_calls=sparse_head(model,sample,selected=torch.zeros(4,dtype=torch.long))
            for p in model.parameters():p[1].copy_(p[0])
            new_logits,new_rows,new_calls=sparse_head(model,sample,selected=torch.ones(4,dtype=torch.long))
            parity_head_rows=sum(old_rows)+sum(new_rows);parity_head_calls=old_calls+new_calls
            parent_copy=float((old_logits-new_logits).abs().max())
            require(parent_copy==0.0,'clone changed original learned parent function')
            migration_bytes=7434*4
        split=True
    if mode!='frozen_single':
        for _ in range(20):fit_batch(x,y)
    train_cpu=max(1,time.process_time_ns()-begin_cpu)
    train_wall=max(1,time.perf_counter_ns()-begin_wall)
    heldout_cpu_start=time.process_time_ns();heldout_wall_start=time.perf_counter_ns()
    with torch.no_grad():
        heldout_select=select_indices(heldout,mode,cutoff=cutoff,split=split)
        logits,eval_counts,eval_calls=sparse_head(model,heldout,selected=heldout_select)
    heldout_cpu=max(1,time.process_time_ns()-heldout_cpu_start)
    heldout_wall=max(1,time.perf_counter_ns()-heldout_wall_start)
    end_sha=p2.shape_hash(dict(model.named_parameters()))
    slot1=expert_bytes(model,1)
    if mode in ('single_active','frozen_single') or (mode=='adaptive_top1' and not split):
        require(slot1==before_slot1,'unselected or dormant Head changed after sparse SGD')
    require((mode=='frozen_single' and updates==0 and initial_sha==end_sha) or
            (mode!='frozen_single' and updates==40 and initial_sha!=end_sha),
            'frozen/learned byte identity or optimizer step contract failed')
    require(sum(train_counts)==(0 if mode=='frozen_single' else HEAD_ROWS_TRAIN)
            and sum(diagnostic_counts)==HEAD_ROWS_DIAGNOSTIC and sum(eval_counts)==HEAD_ROWS_EVAL,
            'physical selected expert-row totals inconsistent')
    return dict(arm=mode,parameter_count=resident(model),active_head_parameters=7434,
        initial_weights_sha256=initial_sha,final_weights_sha256=end_sha,
        expert_one_before_sha256=before_slot1,expert_one_after_sha256=slot1,
        weights=trained_weights(model),split_proposed=split,
        train_only_split_excess_brier=float(excess),split_threshold=p2.SPLIT_THRESHOLD,
        parent_clone_logits_max_abs=parent_copy,migration_copied_fp32_bytes=migration_bytes,
        split_parity_actual_head_forward_rows=parity_head_rows,
        split_parity_actual_head_batch_calls=parity_head_calls,
        split_parity_forward_linear_mac=parity_head_rows*MAC_PER_EXPERT,
        train_updates=updates,train_examples_exposed=exposures,
        train_physical_selected_expert_rows=train_counts,training_head_batch_calls=train_calls,
        train_diagnostic_selected_expert_rows=diagnostic_counts,
        diagnostic_head_batch_calls=diag_calls,
        heldout_selected_expert_rows=eval_counts,heldout_head_batch_calls=eval_calls,
        original_training_labels_only=True,heldout_labels_opened_before_seal=False,
        train_forward_linear_mac=MAC_PER_EXPERT*sum(train_counts),
        diagnostic_forward_linear_mac=MAC_PER_EXPERT*sum(diagnostic_counts),
        heldout_forward_linear_mac=MAC_PER_EXPERT*sum(eval_counts),
        train_cpu_ns=train_cpu,train_wall_ns=train_wall,
        heldout_cpu_ns=heldout_cpu,heldout_wall_ns=heldout_wall,
        train_loss_history=loss_trace,
        heldout_selected_expert_ids=heldout_select.tolist(),
        heldout_logits=logits.cpu().tolist())


def execute(training,blind,backend,*,seed=7347,weight_origin='fixture',parent_p2=None):
    p1.verify_material(training,blind)
    require(type(seed) is int and 0<seed<2**31
            and weight_origin in ('fixture','pinned_public_research'),
            'source-approved seed and model profile required')
    require(isinstance(parent_p2,dict) and parent_p2.get('schema')==p2.SCHEMA
           and parent_p2.get('report_sha256')==digest({k:v for k,v in parent_p2.items() if k!='report_sha256'})
           and parent_p2.get('authority')=='DENY_ALL'
           and parent_p2.get('selection_authorized') is False,
           'original sealed equal-capacity P2 source receipt required')
    torch.set_num_threads(1)
    model_sha,count=p1.backend_digest(backend)
    if weight_origin=='pinned_public_research':
        require(count>=90_000_000 and getattr(backend,'revision',None)==p1.GRANITE_REVISION
                and getattr(backend,'model_id',None)==p1.GRANITE_MODEL
                and getattr(backend,'device',None)=='cpu',
                'actual original pinned Granite97 required: no random fallback')
    require(parent_p2.get('frozen_model_weights_sha256')==model_sha
            and parent_p2.get('model_parameter_count')==count
            and parent_p2.get('public_panel_sha256')==p1.PANEL_SHA
            and parent_p2.get('model_revision')==p1.GRANITE_REVISION
            and parent_p2.get('frozen_pretrained_source_execution_claimed')==(weight_origin=='pinned_public_research')
            and parent_p2.get('original_train_count')==128
            and parent_p2.get('original_test_count')==64
            and parent_p2.get('per_arm_parameter_budget')==14868,
            'real pretrained model and parent P2 material identity mismatch')
    began=time.process_time_ns();vectors={};counter={'calls':0,'model_encode_wall_ns':0}
    for item in training['rows']+blind['rows']:
        vectors[item['case_id']]=p1.encode(backend,item,call_stats=counter)
    require(counter['calls']==224 and len(vectors)==224,'physical frozen-Encoder case inventory incomplete')
    materialization_cpu_ns=max(1,time.process_time_ns()-began)
    x=torch.stack([vectors[r['case_id']] for r in training['rows']])
    y=torch.tensor([r['label'] for r in training['rows']],dtype=torch.long)
    evaluation=torch.stack([vectors[r['case_id']] for r in blind['rows']])
    cutoff=float(torch.median(x[:,0]))
    require(parent_p2['cutoff_feature0_train_median']==cutoff,
            'train-only threshold differs from exact original source')
    heldout_q24={r['case_id']:[int(round(float(z)*(1<<24))) for z in vectors[r['case_id']]]
                 for r in blind['rows']}
    require(heldout_q24==parent_p2['source_features_q24'],
            're-encoded same original pretrained Stem features differ from pinned P2')
    initial=p2.TwoHeads(seed)
    base_init=p2.shape_hash(dict(initial.named_parameters()))
    require(base_init==parent_p2['compared_arms']['frozen_no_change']['initial_weights_sha256'],
            'initial source-locked equal-parameter Head digest mismatch')
    records={a:train_arm(initial,x,y,evaluation,mode=a,cutoff=cutoff) for a in ARMS}
    after,count2=p1.backend_digest(backend)
    require((model_sha,count)==(after,count2),'frozen 97M/fixture Stem parameters changed during training')
    source_identity=[dict(case_id=r['case_id'],group_id=r['group_id'],split=r['split'],
                joint_input_digest=r['joint_input_digest']) for r in blind['rows']]
    out=dict(schema=SCHEMA,authority='DENY_ALL',production_promotion_permitted=False,
         original_p2_report_sha256=parent_p2['report_sha256'],
         source_panel_sha256=p1.PANEL_SHA,model_revision=p1.GRANITE_REVISION,
         original_model_weights_sha256=model_sha,model_parameter_count=count,
         pretrained_weight_execution_claimed=weight_origin=='pinned_public_research',
         independent_model_origin_authenticated=False,
         independently_sourced_future_tasks_verified=False,
         source_cohorts_are_chronological=False,
         exact_backward_flops_matched=False,actual_equal_forward_expert_rows_on_train=True,
         population_4096_training_executed=False,ndu_system2_superiority_established=False,
         signed_final_use_verified=False,production_model_selected=False,
         one_model_load_in_this_execution=True,
         original_pretrained_encoder_forward_calls=224,
         additional_model_load_vs_original_p2_job=(weight_origin=='pinned_public_research'),
         encoding_cpu_ns=materialization_cpu_ns,
         encoding_wall_ns=counter['model_encode_wall_ns'],
         train_count=128,heldout_calibration_count=32,heldout_test_count=64,
         seed=seed,original_frozen_two_head_initial_sha256=base_init,
         train_cutoff_feature0_median=cutoff,private_head_resident_count=14868,
         common_train_updates=40,common_train_example_exposures=3840,
         source_heldout_cases=source_identity,source_features_q24=heldout_q24,
         compared_arms=records,
         observed_process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
    out['report_sha256']=digest(out)
    return out


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('train-material','blind-material','compact-source','original-p2-report','output'):
        ap.add_argument('--'+name,required=True)
    args=ap.parse_args()
    require(not Path(args.output).exists(),'create-only experimental receipt required')
    training=p1.read_json(args.train_material)
    evaluation=p1.read_json(args.blind_material)
    parent=p1.read_json(args.original_p2_report)
    sys.path.insert(0,str(Path(args.compact_source)/'qualification/neuron-stem'))
    from compact_stem_trial import FrozenCompactStem
    real=FrozenCompactStem(p1.GRANITE_MODEL,p1.GRANITE_REVISION,device='cpu',max_tokens=512)
    result=execute(training,evaluation,real,weight_origin='pinned_public_research',parent_p2=parent)
    p1.write_exclusive(args.output,result)

if __name__=='__main__':main()
