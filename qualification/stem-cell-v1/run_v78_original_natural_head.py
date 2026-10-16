"""V7.8 real source-locked 1,700-parameter Natural MultiRC Cell Head trial.

The ONLY executable CLI for claiming actual Granite features: original ZIPs,
model weights and existing TokenBank are verified before any output is created.
If any material is missing, it fails CLOSED; never substitutes random tokens.
Old Bridge binding route is unchanged. Scientific results remain TRAIN/internal.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import time
import zipfile

SCHEMA='hepta.bridge.v78.real-natural-label-head.shadow.v1'


def _check(condition,message):
    if not condition:raise ValueError(message)


def preflight(args):
    from bridge_portable_v74 import originals,material_preflight,cache_preflight
    evidence=originals(args.v4,args.v5,args.v6)
    pre=material_preflight(args.snapshot,evidence['model'])
    _check(pre['ready'],'BLOCKED_MODEL_MATERIAL: authentic Granite97 checkpoint is not present')
    cache=cache_preflight(args.cache,evidence['v5_cache_sha256']) if args.cache else None
    if args.cache:_check(cache['exact'],'explicit historical TokenBank cache missing')
    _check(not args.output.exists() and not args.output.is_symlink(),
           'write-once candidate output directory required')
    return evidence,pre,cache


def _case_source(row):
    from multirc_data import ReaderCase
    fields=dict(row)
    for name in ('facts','sentence_ids','evidence_sentence_indices'):
        fields[name]=tuple(fields[name])
    return ReaderCase(**fields)


def _batches(cell,bank,cases,parent_sha,encoder_sha,preprocess_sha,*,scope='train'):
    from bridge_split_cell_v77 import RouteEvidence,NEW_TASK,feature_digest
    for i in range(0,len(cases),16):
        selected=cases[i:i+16]
        features=bank.batch(selected).features() # labels excluded from Reader arguments
        evidence=RouteEvidence(NEW_TASK,tuple(c.case_id for c in selected),
           tuple(c.source_hash for c in selected),feature_digest(features),parent_sha,
           encoder_sha,preprocess_sha,'0'*64,source_scope=scope)
        yield features,evidence


def run(args):
    evidence,material,pre_cache=preflight(args)
    from bridge_portable_v74 import SEEDS
    from bridge_v78_original_natural_head import (roster,fit_original_human_task,
        score_preexposed_tune)
    from bridge_split_cell_v77 import (SplitBridgeCell,collect_new_task_cache,
        digest_parameters,OLD_TASK)
    from bridge_reader import build_reader
    from token_features import TokenBank
    import torch
    from bridge_numpy_forward import weights_from_checkpoint,bridge_forward
    from bridge_v78_original_calibration import digest,case_id

    torch.set_num_threads(1)
    started_cpu,started_wall=time.process_time_ns(),time.perf_counter_ns()
    original=roster(args.v6)
    binding=tuple(_case_source(r) for r in original['old'])
    natural=tuple(_case_source(r) for r in original['train'])
    tune=tuple(_case_source(r) for r in original['tune'])
    bank=TokenBank.from_snapshot(args.snapshot,batch_size=16,chunk_tokens=64)
    if args.cache:
        bank.restore_local(args.cache)
        cache_scope='restored_exact_original_V5_cache'
    else:
        cache_scope='new_real_granite_encoding_with_original_source'
    missing=[c for c in (*binding,*natural,*tune) if c.case_id not in bank.bindings]
    if missing:bank.register(missing)
    _check(bank.preprocess_sha256==evidence['original_preprocess_sha256'],
           'original frozen TokenBank preprocessing ABI mismatch')
    encoder_sha=digest(bank.encoder.material['sha256'])
    preprocess_sha=bank.preprocess_sha256
    # IMPORTANT: preload and validate ALL three real frozen weights BEFORE any
    # candidate optimizer or model selection. Any accuracy mismatch fails closed.
    original_models={}
    parity={}
    with zipfile.ZipFile(args.v6) as z:
        for seed in SEEDS:
            path=f'reader-v6-bridge/seed-{seed}/bridge/'
            raw=z.read(path+'warmup.pt')
            model=build_reader('bridge',seed).eval().requires_grad_(False)
            model.load_state_dict(torch.load(io.BytesIO(raw),map_location='cpu',weights_only=True),strict=True)
            expected=original['parents'][seed]['training_parameter_sha256']
            _check(digest_parameters(model)==expected,'true historical warmup weights differ')
            old=z.read(path+'warmup-binding-train.json')
            historical=json.loads(old)['probabilities']
            _check(len(historical)==128,'old source full TRAIN probability reference missing')
            numpy_w,_=weights_from_checkpoint(raw)
            produced=[];discrepancy=0.;bit_flips=0
            for i in range(0,len(binding),16):
                data=bank.batch(binding[i:i+16]).features()
                with torch.no_grad():
                    torch_logits=model(*data,steps=3)
                    p=torch_logits.softmax(-1)[:,1].tolist()
                independent=bridge_forward(numpy_w,tuple(v.detach().numpy() for v in data[:3]),
                                          tuple(v.detach().numpy() for v in data[3:]),steps=3)
                err=float(abs(independent-torch_logits.detach().numpy()).max())
                _check(err<=.0015,'Torch/NumPy true encoded input mismatch')
                discrepancy=max(discrepancy,err)
                produced.extend(p)
            _check(all(abs(a-b)<=.001 and (a>.5)==(b>.5)
                       for a,b in zip(produced,historical)),
                   'old V6 original TRAIN logits incompatible with reencoded authentic model')
            original_models[seed]=model
            parity[str(seed)]=dict(actual_original_token_predictions=128,
                historical_max_abs_positive_probability_diff=max(abs(a-b)
                     for a,b in zip(produced,historical)),
                independent_numpy_max_abs_logit_difference=discrepancy,
                old_model_actual_granite_features=True,old_class_flips=0)

    # Features and training state live only in this process until all preflight
    # succeeds. They contain publisher labels and may never be confused with
    # independent official validation.
    args.output.mkdir(parents=True,exist_ok=False)
    from bridge_v78_original_natural_head import SAMPLING_ARMS
    records={};all_calls=0
    for seed in SEEDS:
        parent=original_models[seed]
        parent_before=digest_parameters(parent)
        cells={arm:SplitBridgeCell(parent,expected_parent_sha256=parent_before,
                    new_head_seed=seed) for arm in SAMPLING_ARMS}
        _check(cells['row_uniform'].parent is cells['source_balanced'].parent,
               'same physical frozen BridgeReader must be shared by both Cell arms')
        initial_heads={arm:digest_parameters(c.new_head) for arm,c in cells.items()}
        _check(len(set(initial_heads.values()))==1,'both source samplers must share initial head bytes')
        first=cells['row_uniform']
        train_pairs=list(_batches(first,bank,natural,parent_before,encoder_sha,preprocess_sha))
        # Single shared physical feature-bank allocation: both arms consume the
        # same 3,909 source-locked 97D states and frozen original logits.
        cache=collect_new_task_cache(first,train_pairs,
                 forbidden_old_sources=original['old_source_hashes'])
        _check(cache.encoded_reader_calls==(len(natural)+15)//16,
               'each authentic natural TRAIN minibatch must execute once')
        arm_receipts={}
        for arm,cell in cells.items():
            arm_receipts[arm]=fit_original_human_task(cell,cache,args.v6,seed=seed,
                updates=420,sampling_arm=arm)
        # Previously exposed original natural TUNE rows enter ONLY after all
        # candidate weights are fixed, never any gradient, early stop or routing.
        tunelatent=[];tunebase=[]
        for data,_ in _batches(first,bank,tune,parent_before,encoder_sha,preprocess_sha,
                                  scope='train_internal_tune'):
            h,p=first.extract(data)
            tunelatent.append(h);tunebase.append(p)
        th,tl=torch.cat(tunelatent),torch.cat(tunebase)
        sample=bank.batch(binding[:16]).features()
        with torch.no_grad():reference=parent(*sample,steps=3)
        from bridge_split_cell_v77 import RouteEvidence,feature_digest
        old_ticket=RouteEvidence(OLD_TASK,tuple(c.case_id for c in binding[:16]),
            tuple(c.source_hash for c in binding[:16]),feature_digest(sample),parent_before,
            encoder_sha,preprocess_sha,'0'*64)
        _check(digest_parameters(parent)==parent_before,
                'frozen original shared parent changed after full two-arm Head fit')
        for arm,cell in cells.items():
            result=arm_receipts[arm]
            panel=score_preexposed_tune(cell,original,th,tl,
                  case_ids=original['tune_case_ids'],
                  source_hashes=original['tune_source_hashes'])
            exact=bool(torch.equal(reference,cell.route(sample,old_ticket)))
            _check(exact and digest_parameters(parent)==parent_before,
                    'old Binding route modified by Cell Head')
            dest=args.output/f'seed-{seed}'/arm
            dest.mkdir(parents=True,exist_ok=False)
            fp=dest/'new-head.pt'
            torch.save(cell.new_head.state_dict(),fp)
            weight_sha=sha256(fp.read_bytes()).hexdigest()
            entry=dict(seed=seed,arm=arm,new_head_weight_file_sha256=weight_sha,
                original_parent_sha256=parent_before,original_old_route_exact=True,
                parent_training_updates=0,
                natural_training_uses_authentic_Granite_features=True,
                original_v6_checkpoint_not_written=True,
                physical_feature_bank_same_both_arms=True,
                source_disjoint_future_evaluated=False,
                candidate_fitting=result,internal_tune_panel=panel,
                original_natural_tune_not_used_to_choose_head=True,
                model_selected=False,production_authorized=False)
            with (dest/'receipt.json').open('x') as f:
                json.dump(entry,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')
            records[f'{seed}/{arm}']=dict(head_sha256=result['fitting']['new_head_sha256'],
              head_file_sha256=weight_sha,
              train_correct=result['fitting']['train_only_after_correct'],
              tune_scores=panel,original_old_route_bitwise=True,
              actual_cpu_ns=result['fitting']['training_cpu_ns'],
              logical_optimizer_updates=420,
              source_balanced=arm=='source_balanced')
        all_calls+=sum(c.parent_forward_calls for c in cells.values())
    complete=dict(schema=SCHEMA,status='TRAIN_SOURCE_INTERNAL_PANEL_ONLY',
        results=records,old_full_original_parity=parity,
        original_v6_zip_sha256=original['original_v6_sha256'],
        original_pretrained_snapshot_sha256=encoder_sha,
        original_token_preprocess_sha256=preprocess_sha,
        original_cache_scope=cache_scope,
        new_encoder_forward_batches=bank.forward_batches,
        total_physical_reader_forward_calls=all_calls,
        total_trainable_head_models=len(SEEDS)*len(SAMPLING_ARMS),
        original_parent_shared_between_sampler_arms=True,
        train_parameters_per_new_head=1700,
        fixed_optimizer_steps_per_head=420,
        source_groups_unchanged=True,
        whole_process_cpu_ns=time.process_time_ns()-started_cpu,
        whole_process_wall_ns=time.perf_counter_ns()-started_wall,
        model_selected=False,production_authorized=False,
        cell_split_production_authorized=False,native_ndu_admitted=False,
        independent_future_task_gain_verified=False,
        pretrained_encoder_generation_and_cache_work_not_free=True,
        full_lifecycle_matched_control_completed=False,
        original_historical_natural_internal_panel_is_preexposed=True)
    with (args.output/'completed.json').open('x') as f:
        json.dump(complete,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')
    return complete


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('v4','v5','v6','snapshot','output'):
        p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--cache',type=Path,default=None)
    args=p.parse_args()
    result=run(args)
    print(json.dumps(dict(status=result['status'],seeds=len(result['results']),
                          production_authorized=False)))

if __name__=='__main__':main()
