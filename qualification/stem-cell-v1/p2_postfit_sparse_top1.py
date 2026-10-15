"""Physical *post-training* Top-1 forwarding of original P2 equal-parameter Cells.

Never fits, changes or selects model parameters, observes heldout labels, downloads
weights, changes CellSplit owners, or implies full-system resource superiority.
The unfused P2 dense train path remains the immutable quality reference.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import time

import torch

import p2_real_cell_split as p2

SCHEMA = 'hepta.p2.postfit-physical-sparse-top1.v1'
MODES = ('frozen_no_change', 'unrouted_equal_parameter',
         'wide_single_equal_parameter','fixed_two_cell','adaptive_train_only')
EXPERT_MAC = 384*8 + 64*8 + 8*384 + 384*2
WIDE_MAC = 384*16 + 64*16 + 16*384 + 384*2 + 384*2
MAX_ABS = 4e-5


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def sha(doc):
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(',', ':'),
          ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def restore(arm, *, seed=41):
    """Build only original P2 registered tensors; no optimizer, gradients or training."""
    mode=arm.get('arm')
    require(mode in MODES, 'unregistered original P2 Head')
    wide=mode=='wide_single_equal_parameter'
    model=p2.WideSingleHead(seed) if wide else p2.TwoHeads(seed)
    expected=set(dict(model.named_parameters()))
    packed=arm.get('weights')
    require(isinstance(packed,dict) and set(packed)==expected, 'complete original trained FP32 tensors required')
    with torch.no_grad():
        for name,value in model.named_parameters():
            item=packed[name];shape=list(value.shape)
            require(isinstance(item,dict) and set(item)=={'shape','bytes_le_hex'}
                    and item['shape']==shape and isinstance(item['bytes_le_hex'],str),
                    'original P2 weight shape/fields changed')
            hx=item['bytes_le_hex']
            require(len(hx)==value.numel()*8 and all(c in '0123456789abcdef' for c in hx),
                    'original tensor bytes malformed')
            import numpy as np
            loaded=np.frombuffer(bytes.fromhex(hx),dtype='<f4').reshape(value.shape).copy()
            require(bool(np.isfinite(loaded).all()),'original trained tensor nonfinite')
            value.copy_(torch.from_numpy(loaded))
    require(p2.shape_hash(dict(model.named_parameters()))==arm.get('final_weights_sha256'),
            'actual original trained weight bytes mismatch')
    model.eval()
    model.requires_grad_(False)
    return model


def physical_sparse(model,x,cutoff,split):
    """Do not compute logits for an unselected expert: group by selected index."""
    require(type(split) is bool and isinstance(model,p2.TwoHeads),
            'physical sparse Top-1 requires original two-Head bank')
    require(x.ndim==2 and x.shape[1]==384 and x.dtype==torch.float32
            and x.device.type=='cpu' and not x.requires_grad
            and bool(torch.isfinite(x).all()),'exact bounded CPU frozen Q24 input required')
    chosen=(x[:,0]>=cutoff).long() if split else torch.zeros(len(x),dtype=torch.long)
    out=torch.empty(len(x),2,dtype=torch.float32)
    actual_rows=0;physical_batches=0
    for expert in (0,1):
        ids=torch.nonzero(chosen==expert,as_tuple=False).flatten()
        if not ids.numel():continue
        xx=x.index_select(0,ids)
        with torch.no_grad():
            d=xx @ model.down[expert]
            g=torch.sigmoid(xx[:,:64] @ model.gate[expert] + model.g_bias[expert])
            delta=(torch.nn.functional.silu(d)*g) @ model.up[expert]
            yy=(xx+delta) @ model.out[expert] + model.out_bias[expert]
            out.index_copy_(0,ids,yy)
        actual_rows+=len(ids);physical_batches+=1
    require(actual_rows==len(x) and 1<=physical_batches<=2,
            'not exactly one actual Head forward per item')
    return out,chosen.tolist(),actual_rows,physical_batches


def forward_dense(model,x,kind,cutoff,split):
    if kind=='wide_single_equal_parameter': return model(x)
    return p2.routing(model(x),x,kind,split=split,threshold=cutoff)


def run(original, *, repetitions=100, warmups=5):
    """Measure real full-batch CPU requests, in alternating orders.

    All trained tensors and 96 original features are read from original sealed P2.
    No validation labels are accessed. Retain slow and negative timing results.
    """
    require(isinstance(original,dict) and original.get('schema')==p2.SCHEMA
            and original.get('authority')=='DENY_ALL'
            and original.get('production_promotion_permitted') is False
            and original.get('report_sha256')==sha({k:v for k,v in original.items() if k!='report_sha256'})
            and original.get('per_arm_parameter_budget')==14868
            and original.get('original_test_count')==64 and original.get('original_calibration_count')==32,
            'exact immutable original P2 report required')
    require(type(repetitions) is int and 20<=repetitions<=200
            and type(warmups) is int and 0<=warmups<=20,'bounded request sample census required')
    require(type(original.get('cutoff_feature0_train_median')) is float and
            math.isfinite(original['cutoff_feature0_train_median']),
            'original train-only router boundary missing')
    tasks=original.get('source_heldout_cases');features=original.get('source_features_q24')
    require(isinstance(tasks,list) and len(tasks)==96 and isinstance(features,dict)
            and len(features)==96 and set(features)=={t.get('case_id') for t in tasks},
            'exact 96 original source-group identities required')
    require({t.get('split') for t in tasks}=={'calibration','test'}
            and all(set(t)=={'case_id','group_id','split','joint_input_digest'}
                    for t in tasks), 'original source labels/identities changed')
    material=[]
    for t in tasks:
        row=features[t['case_id']]
        require(isinstance(row,list) and len(row)==384 and
                all(type(v) is int and abs(v)<=8*(1<<24) for v in row),
                'Q24 features missing or changed')
        material.append([v/(1<<24) for v in row])
    torch.set_num_threads(1)
    x=torch.tensor(material,dtype=torch.float32)
    require(not x.requires_grad,'frozen feature required')
    expected=original.get('compared_arms')
    require(isinstance(expected,dict) and set(expected)==set(MODES),'complete existing five-arm census required')
    cutoff=original['cutoff_feature0_train_median']
    observations={}
    for name in MODES:
        arm=expected[name]
        require(isinstance(arm,dict) and arm.get('arm')==name
                and arm.get('parameter_count')==14868
                and type(arm.get('split_proposed')) is bool,
                'untrusted original fitted Head state')
        model=restore(arm)
        split=arm['split_proposed']
        is_routed=name in ('fixed_two_cell','adaptive_train_only')
        dense_head_rows=96 if name=='wide_single_equal_parameter' else 2*96
        active_head_rows=96 if is_routed or name=='wide_single_equal_parameter' else 2*96
        registered_mac=WIDE_MAC*96 if name=='wide_single_equal_parameter' else EXPERT_MAC*dense_head_rows
        active_mac=WIDE_MAC*96 if name=='wide_single_equal_parameter' else EXPERT_MAC*active_head_rows
        def calc_sparse():
            if is_routed:
                return physical_sparse(model,x,cutoff,split)
            result=forward_dense(model,x,name,cutoff,split)
            return result,[],active_head_rows,1 if name=='wide_single_equal_parameter' else 2
        with torch.inference_mode():
            reference=forward_dense(model,x,name,cutoff,split)
            physically,route,rows,batches=calc_sparse()
        stored=arm.get('logits')
        require(isinstance(stored,list) and len(stored)==96
                and all(isinstance(r,list) and len(r)==2 for r in stored),
                'original pre-score complete logits required')
        archived=torch.tensor(stored,dtype=torch.float32)
        reference_error=float((reference-archived).abs().max().item())
        sparse_error=float((reference-physically).abs().max().item())
        require(reference_error<=MAX_ABS and sparse_error<=MAX_ABS,
                'physical sparse result does not reproduce frozen original P2 predictions')
        require(rows==active_head_rows,'Head expert forward row count drift')
        # Counterbalance cold and warm calculations rather than only time the favorable arm.
        measured_dense=[];measured_active=[];process_dense=[];process_active=[]
        for rep in range(warmups+repetitions):
            pair=('dense','active') if rep%2==0 else ('active','dense')
            for mode in pair:
                before_cpu=time.process_time_ns();before_wall=time.perf_counter_ns()
                with torch.inference_mode():
                    result=forward_dense(model,x,name,cutoff,split) if mode=='dense' else calc_sparse()[0]
                wall=max(1,time.perf_counter_ns()-before_wall)
                cpu=max(1,time.process_time_ns()-before_cpu)
                if rep>=warmups:
                    if mode=='dense':measured_dense.append(wall);process_dense.append(cpu)
                    else:measured_active.append(wall);process_active.append(cpu)
        require(len(measured_dense)==len(measured_active)==repetitions,'complete request measurement missing')
        source_identity=[dict(case_id=t['case_id'],group_id=t['group_id'],split=t['split'],
                     joint_input_digest=t['joint_input_digest']) for t in tasks]
        observations[name]=dict(arm=name,split_proposed=split,
            final_weights_sha256=arm['final_weights_sha256'],
            total_resident_parameter_count=14868,source_heldout_count=96,
            source_heldout_identity_sha256=sha(source_identity),
            physical_selected_head_indices=route,registered_dense_head_rows=dense_head_rows,
            physical_active_head_rows=rows,physical_active_batch_calls=batches,
            declared_linear_mac_dense=registered_mac,declared_linear_mac_active=active_mac,
            dense_vs_original_p2_logits_max_abs=reference_error,
            sparse_vs_dense_logits_max_abs=sparse_error,
            sparse_heldout_logits=physically.detach().cpu().tolist(),
            dense_batch_wall_ns=measured_dense,active_batch_wall_ns=measured_active,
            dense_batch_process_cpu_ns=process_dense,active_batch_process_cpu_ns=process_active)
    report=dict(schema=SCHEMA,original_p2_report_sha256=original['report_sha256'],
          original_frozen_model_sha256=original['frozen_model_weights_sha256'],
          original_source_panel_sha256=original['public_panel_sha256'],
          original_model_revision=original['model_revision'],repetitions=repetitions,
          warmups=warmups,source_heldout_count=96,request_unit='96-row-full-batch',
          time_measurements_self_reported=True,
          original_training_compute_and_model_load_not_remeasured=True,
          strict_equal_online_mac_across_arms=False,
          independent_future_task_utility_established=False,
          native_worker_request_p99_qualified=False,
          production_promotion_permitted=False,authority='DENY_ALL',
          arms=observations)
    report['report_sha256']=sha(report)
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--p2-report',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--repetitions',type=int,default=100)
    args=ap.parse_args()
    import p1_real_granite_review as source
    original=source.read_strict(args.p2_report,limit=8*1024*1024)
    result=run(original,repetitions=args.repetitions)
    with args.output.open('x',encoding='utf8') as f:
        json.dump(result,f,sort_keys=True,separators=(',',':'),allow_nan=False);f.write('\n')

if __name__=='__main__':main()
