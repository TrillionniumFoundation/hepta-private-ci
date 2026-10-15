"""Real annotated MultiRC: frozen document Encoder + four equal-size Readers.

Three strictly ordered actions: (1) material-owner prepare, (2) model-only run
that loads evaluation text AFTER all Readers train, (3) labels-only score after
weights and predictions are sealed. Source-only tests use explicit toy encoders;
pretrained-HF validation has its own additive CI job. No claim of parity,
statistical superiority, or independent data contamination control.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import torch
from safetensors.torch import save_file

from conditioned_panel_study import _validate_tensor
from conditional_evidence import ConditionedReader, TrainingCase, fit_reader
from execution_meter import WorkLedger, CONDITIONAL_READER_POLICY_SCHEMA
from hf_complete_checkpoint import load_complete_mlm, TIED_ALIASES
from hf_encoder_kernel import snapshot_digest, verify_loaded_safetensors
from matrix_bank import state_digest
from matrix_materials import file_sha256, strict_json
from matrix_runtime import write_json_exclusive
from multirc_materials import (load_parquet, prepare_panels,validate_panel_bundles,REPO,REVISION,
                               TRAIN_NAME,VAL_NAME)
from next_round_matrix import _digest
from paired_execution import PHASES
from reader_work_v1 import PROFILE

ARMS=('conditioned','mean_pool_query_fused','no_evidence','no_query')


def _features(states, question, arm):
    """Four semantically distinct comparators, all with equal trainable size.

    Pooling retains nontrainable query interaction; no-evidence retains query
    priors; no-query retains all passage tokens. Fixed transformations are paid.
    """
    if arm=='conditioned': return states,question
    if arm=='mean_pool_query_fused': return states.mean(dim=0,keepdim=True)*question.unsqueeze(0),question
    if arm=='no_evidence': return question.unsqueeze(0),question
    if arm=='no_query': return states,torch.zeros_like(question)
    raise ValueError('unknown registered MultiRC control')


POLICY = dict(schema=CONDITIONAL_READER_POLICY_SCHEMA,arithmetic_profile=PROFILE,
              mode='strict',wall_time_ns=1_200_000_000_000,
              max_process_rss_bytes=None,rapl_zone=None,rapl_max_power_watts=None)


def _question_text(item):
    return item['question']+'\nCandidate answer: '+item['answer']+'\nIs this candidate correct?'


def train_then_predict(train_bundle, evaluation_loader, *, encoder, question_encoder,
                       checkpoint_sha256, seed=7347, steps=64, max_feature_bytes=8*1024*1024,
                       max_cache_bytes=128*1024*1024, policy=POLICY):
    """Model sees training labels only. Evaluation loader is invoked post-fit."""
    from multirc_materials import OPTIONS
    if (not isinstance(train_bundle,dict) or train_bundle.get('split')!='train'
            or not isinstance(train_bundle.get('rows'),list) or not train_bundle['rows']
            or type(steps) is not int or not 1<=steps<=512
            or type(seed) is not int or seed<1 or not callable(evaluation_loader)
            or any(type(z) is not int or z<=0 for z in (max_feature_bytes,max_cache_bytes))):
        raise ValueError('complete train-only material and bounded resources required')
    if train_bundle.get('schema')!='hepta.multirc.two-question-material.v1':
        raise ValueError('wrong material source')
    train_groups=set()
    for row in train_bundle['rows']:
        if row['source_group'] in train_groups or len(row['questions'])!=2:
            raise ValueError('duplicate/incomplete training source groups')
        train_groups.add(row['source_group'])
        for question in row['questions']:
            if set(question)!={'task_id','question','answer','label'}:
                raise ValueError('train-only label and question required')
            if type(question['label']) is not int or question['label'] not in (0,1):
                raise ValueError('invalid training label')
    caps=dict.fromkeys(PHASES,10**14)
    encode_meter=WorkLedger(policy,caps)
    prepared=[]
    dimension=None
    retained_bytes=0
    def materialize(rows,phase):
        nonlocal dimension,retained_bytes
        output=[]
        for row in rows:
            with encode_meter.scope(phase,'encoder'),torch.inference_mode():
                states=encoder(row['evidence'])
            if not isinstance(states,torch.Tensor) or states.ndim!=2 or not 1<=len(states)<=512:
                raise ValueError('invalid typed frozen evidence geometry')
            if dimension is None:dimension=states.shape[1]
            # Keep exactly one NORMAL autograd-compatible frozen evidence copy
            # per source passage. Two different questions share that storage;
            # the Encoder is neither reexecuted nor its feature tensor doubled.
            with torch.inference_mode(False):
                stable_states=states.detach().clone()
            retained_bytes+=stable_states.untyped_storage().nbytes()
            if retained_bytes>max_cache_bytes:
                raise ValueError('retained token/query feature limit exceeded')
            for item in row['questions']:
                with encode_meter.scope(phase,'material'),torch.inference_mode():
                    q=question_encoder(_question_text(item))
                    _validate_tensor(states,q,max_feature_bytes)
                    if states.shape[1]!=dimension:
                        raise ValueError('one immutable feature width required')
                with torch.inference_mode(False):
                    stable_query=q.detach().clone()
                retained_bytes+=stable_query.untyped_storage().nbytes()
                if retained_bytes>max_cache_bytes:
                    raise ValueError('retained token/query feature limit exceeded')
                output.append((row['source_group'],item,stable_states,stable_query))
        return output
    prepared=materialize(train_bundle['rows'],'train')
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        base=ConditionedReader(dimension,2).eval()
    trained={}
    fit={}
    projection_work={}
    for arm in ARMS:
        prep_meter=WorkLedger(policy,caps)
        with prep_meter.scope('train','bank'):
            cases=[TrainingCase(*_features(s,q,arm),item['label'],g,5)
                   for g,item,s,q in prepared]
        projection_work[arm]=dict(train=prep_meter.report())
        meter=WorkLedger(policy,caps)
        reader,receipt=fit_reader(base,cases,cutoff_ns=10,seed=seed,steps=steps,
                                  learning_rate=.003,meter=meter)
        trained[arm]=reader
        fit[arm]=dict(**receipt,weights_sha256=state_digest(reader))
    # CRITICAL: Evaluation file is not even OPENED before all four fits.
    evaluation=evaluation_loader()
    validate_panel_bundles(train_bundle,evaluation)
    heldout=materialize(evaluation['rows'],'inference')
    eval_meter=WorkLedger(policy,caps)
    predictions={arm:[] for arm in ARMS}
    for group,item,states,q in heldout:
        for arm,reader in trained.items():
            with eval_meter.scope('inference','bank'),torch.inference_mode():
                features,query=_features(states,q,arm)
                logits=reader(features,query)
            if logits.shape!=(2,) or not torch.isfinite(logits).all().item():
                raise ValueError('nonfinite Reader decision')
            predictions[arm].append(dict(task_id=item['task_id'],source_group=group,
                logits=[float(v) for v in logits],weights_sha256=fit[arm]['weights_sha256']))
    if len({sum(p.numel() for p in v.parameters()) for v in trained.values()})!=1:
        raise ValueError('same-sized Reader controls changed parameter counts')
    obs=dict(schema='hepta.multirc.real-question-reader.v1',panel_id=evaluation['panel_id'],
        model_snapshot_sha256=checkpoint_sha256,train_passages=len(train_bundle['rows']),
        eval_passages=len(evaluation['rows']),train_examples=len(prepared),
        eval_examples=len(heldout),seed=seed,steps=steps,task_ids=[v[1]['task_id'] for v in heldout],
        source_groups=[v[0] for v in heldout],
        arm_parameter_counts={a:sum(p.numel() for p in v.parameters()) for a,v in trained.items()},
        training=fit,projection_work=projection_work,predictions=predictions,encoding_work=encode_meter.report(),
        final_reader_work=eval_meter.report(),
        actual_train_encoder_calls=len(train_bundle['rows']),
        actual_eval_encoder_calls=len(evaluation['rows']),
        actual_query_calls=len(prepared)+len(heldout),
        retained_feature_bytes=retained_bytes,
        labels_loaded_during_training=False,benchmark_source_group_independence_verified=False,
        pretraining_contamination_ruled_out=False,trained_reader_generalization_established=False,
        production_authorized=False)
    obs['observation_id']=_digest(obs)
    return obs,trained


def score_sealed(observation, label_receipt, *,expected_observation_id,expected_label_sha256):
    if (not isinstance(observation,dict) or observation.get('schema')!='hepta.multirc.real-question-reader.v1'
            or observation.get('observation_id')!=expected_observation_id
            or _digest({k:v for k,v in observation.items() if k!='observation_id'})!=expected_observation_id
            or not isinstance(label_receipt,dict) or _digest(label_receipt)!=expected_label_sha256
            or label_receipt.get('schema')!='hepta.multirc.external-eval-labels.v1'
            or label_receipt.get('panel_id')!=observation['panel_id']):
        raise ValueError('sealed prediction + independently retained labels required')
    ids=observation['task_ids']; groups=observation['source_groups']
    labels=label_receipt['labels']
    if (not isinstance(labels,dict) or set(labels)!=set(ids) or len(set(ids))!=len(ids)
            or len(groups)!=len(ids) or len(set(groups))!=observation['eval_passages']):
        raise ValueError('complete registered evaluation denominator required')
    result={}
    for arm in ARMS:
        rows=observation['predictions'].get(arm)
        if not isinstance(rows,list) or [r.get('task_id') for r in rows]!=ids:
            raise ValueError('candidate evaluation task inventory inconsistent')
        correct=0;brier=0.;by_group={}
        for i,(row,task_id) in enumerate(zip(rows,ids,strict=True)):
            if row.get('source_group')!=groups[i] or row.get('weights_sha256')!=observation['training'][arm]['weights_sha256']:
                raise ValueError('prediction group or trained weight identity differs')
            target=labels[task_id]
            scores=row.get('logits')
            if (type(target) is not int or target not in (0,1) or not isinstance(scores,list)
                    or len(scores)!=2 or any(type(x) not in (float,int) or not math.isfinite(x) for x in scores)):
                raise ValueError('untrusted target or probability model output')
            ex=[math.exp(z-max(scores)) for z in scores]
            p=[v/sum(ex) for v in ex]
            win=int(scores.index(max(scores))==target)
            correct+=win
            brier+=sum((p[j]-int(j==target))**2 for j in range(2))
            item=by_group.setdefault(groups[i],dict(total=0,correct=0))
            item['total']+=1;item['correct']+=win
        if set(by_group)!=set(groups) or any(v['total']!=2 for v in by_group.values()):
            raise ValueError('one independent passage two question candidates required')
        result[arm]=dict(correct=correct,total=len(ids),accuracy=correct/len(ids),
            brier=brier/len(ids),passage_groups=by_group,
            statistical_superiority_established=False)
    # The whole population, not selectively chosen success cases, determines
    # each exact paired contrast. Passage groups, not repeated answer rows, are
    # the unit that could become independent if their provenance were verified.
    paired={}
    anchor_rows=observation['predictions']['conditioned']
    for control in ARMS:
        if control=='conditioned':
            continue
        control_rows=observation['predictions'][control]
        each={}
        for i,(primary,other) in enumerate(zip(anchor_rows,control_rows,strict=True)):
            target=labels[ids[i]]
            a=int(primary['logits'].index(max(primary['logits']))==target)
            b=int(other['logits'].index(max(other['logits']))==target)
            group=groups[i]
            bucket=each.setdefault(group,dict(total=0,conditioned_recovered=0,
                conditioned_lost=0,both_correct=0,both_wrong=0))
            bucket['total']+=1
            if a and not b:bucket['conditioned_recovered']+=1
            elif b and not a:bucket['conditioned_lost']+=1
            elif a and b:bucket['both_correct']+=1
            else:bucket['both_wrong']+=1
        if set(each)!=set(groups) or any(v['total']!=2 or
            sum(v[k] for k in ('conditioned_recovered','conditioned_lost','both_correct','both_wrong'))!=2
            for v in each.values()):
            raise ValueError('paired passage outcomes incomplete')
        paired[control]=dict(by_passage=each,
            recovered=sum(v['conditioned_recovered'] for v in each.values()),
            lost=sum(v['conditioned_lost'] for v in each.values()),
            conditioned_minus_control_accuracy=(result['conditioned']['correct']-result[control]['correct'])/len(ids),
            conditioned_minus_control_brier=result['conditioned']['brier']-result[control]['brier'])
    return dict(schema='hepta.multirc.real-question-evaluation.v1',
        observation_id=expected_observation_id,label_sha256=expected_label_sha256,
        results=result,paired_controls=paired,
        repeated_answer_rows_not_independent_passages=True,
        unconditional_majority_baseline=max(
            sum(v==0 for v in labels.values()),sum(v==1 for v in labels.values()))/len(ids),
        benchmark='MultiRC_source_declared',human_annotation_origin_independently_verified=False,
        small_sample_not_rank_certified=True,real_world_qa_established=False,
        independent_source_group_sampling_verified=False,contamination_freedom_verified=False,
        resource_efficiency_established=False,model_selected=False,production_authorized=False)


def safe_encoder(snapshot):
    """One frozen local stock ModernBERT with fully verified safetensor loading."""
    from transformers import AutoTokenizer
    root=Path(snapshot).resolve()
    identity=snapshot_digest(root)
    full,encoder,loading=load_complete_mlm(root)
    if full.training or any(p.requires_grad for p in full.parameters()):
        raise ValueError('frozen weights only')
    tokenizer=AutoTokenizer.from_pretrained(str(root),local_files_only=True,trust_remote_code=False)
    embeddings=full.get_input_embeddings()
    if embeddings is None or embeddings.weight is not encoder.embeddings.tok_embeddings.weight:
        raise ValueError('checkpoint input embedding owner not matched')
    def evidence(text):
        ids=tokenizer(text,return_tensors='pt',truncation=False)
        if not 1<=ids['input_ids'].shape[1]<=256:
            raise ValueError('predeclared 256-token evidence limit exceeded')
        with torch.inference_mode():
            return encoder(**ids).last_hidden_state[0].detach().to(torch.float32).cpu()
    def query(text):
        ids=tokenizer(text,return_tensors='pt',truncation=False)
        if not 1<=ids['input_ids'].shape[1]<=128:
            raise ValueError('predeclared 128-token question limit exceeded')
        with torch.inference_mode():
            return embeddings(ids['input_ids']).mean(dim=1)[0].detach().to(torch.float32).cpu()
    def verify():
        verify_loaded_safetensors(torch,full,root,tied_aliases=TIED_ALIASES)
        if snapshot_digest(root)!=identity:
            raise ValueError('snapshot changed during training or assessment')
    return evidence,query,verify,identity,full,loading


def publish(root,observation,banks):
    root=Path(root)
    root.mkdir(exist_ok=False)
    try:
        write_json_exclusive(root/'predictions.json',observation)
        names=['predictions.json']
        for arm in ARMS:
            name=arm+'.safetensors'
            save_file({k:v.detach().cpu().contiguous() for k,v in banks[arm].state_dict().items()},str(root/name))
            names.append(name)
        manifest=dict(schema='hepta.multirc.unscored-model-seal.v1',observation_id=observation['observation_id'],
                      files={name:file_sha256(root/name) for name in names},
                      labels_loaded_during_training=False,production_authorized=False)
        manifest['seal_id']=_digest(manifest)
        write_json_exclusive(root/'COMMITTED.json',manifest)
        return manifest
    except Exception as exc:
        write_json_exclusive(root/'FAILED.json',dict(error_type=type(exc).__name__,production_authorized=False))
        raise


def check_seal(root,seal_id):
    root=Path(root)
    if (root/'FAILED.json').exists(): raise ValueError('failed study may not be rescored')
    manifest=strict_json(root/'COMMITTED.json')
    if (manifest.get('seal_id')!=seal_id or _digest({k:v for k,v in manifest.items() if k!='seal_id'})!=seal_id
            or manifest.get('schema')!='hepta.multirc.unscored-model-seal.v1'):
        raise ValueError('external seal changed')
    for name,digest in manifest['files'].items():
        if '/' in name or (root/name).is_symlink() or file_sha256(root/name)!=digest:
            raise ValueError('sealed bank or prediction changed')
    obs=strict_json(root/'predictions.json')
    if obs['observation_id']!=manifest['observation_id']:
        raise ValueError('prediction identity changed')
    return obs


def main():
    p=argparse.ArgumentParser(description=__doc__)
    commands=p.add_subparsers(dest='cmd',required=True)
    prep=commands.add_parser('prepare')
    for k in ('train-parquet','val-parquet','train-sha256','val-sha256','output'):prep.add_argument('--'+k,required=True)
    prep.add_argument('--seed',type=int,default=7347)
    prep.add_argument('--train-passages',type=int,default=8)
    prep.add_argument('--eval-passages',type=int,default=4)
    run=commands.add_parser('run')
    for k in ('train-bundle','blind-eval-bundle','snapshot','output'):run.add_argument('--'+k,required=True)
    run.add_argument('--steps',type=int,default=64)
    score=commands.add_parser('score')
    for k in ('run-dir','expected-seal-id','label-file','label-sha256','output'):score.add_argument('--'+k,required=True)
    args=p.parse_args()
    if args.cmd=='prepare':
        a=load_parquet(args.train_parquet,expected_sha256=args.train_sha256)
        b=load_parquet(args.val_parquet,expected_sha256=args.val_sha256)
        tr,ev,lb=prepare_panels(a,b,seed=args.seed,train_passages=args.train_passages,
                               val_passages=args.eval_passages,dataset_sha256_train=args.train_sha256,
                               dataset_sha256_val=args.val_sha256)
        root=Path(args.output);root.mkdir(exist_ok=False)
        write_json_exclusive(root/'train-bundle.json',tr)
        write_json_exclusive(root/'blind-eval-bundle.json',ev)
        write_json_exclusive(root/'owner-only-labels.json',lb)
        write_json_exclusive(root/'MATERIAL.json',dict(source_repo=REPO,source_revision=REVISION,
            train_sha256=args.train_sha256,val_sha256=args.val_sha256,
            panel_id=tr['panel_id'],material_admission=tr['material_admission'],
            total_selected_train_passages=len(tr['rows']),
            total_selected_validation_passages=len(ev['rows']),
            evaluation_labels_not_for_model=True))
        # Log ONLY aggregate row-admission statistics and source identity.
        # Do not disclose the human labels, raw source evidence or weight bytes.
        print(json.dumps(dict(panel_id=tr['panel_id'],
            material_admission=tr['material_admission'],
            model_training_started=False,production_authorized=False),sort_keys=True))
    elif args.cmd=='run':
        try:
            tr=strict_json(args.train_bundle)
            torch.set_num_threads(1)
            evidence,query,verify,checkpoint,full,loading=safe_encoder(args.snapshot)
            # No eval file materialized until fit_reader completes for all arms.
            obs,banks=train_then_predict(tr,lambda:strict_json(args.blind_eval_bundle),
                encoder=evidence,question_encoder=query,checkpoint_sha256=checkpoint,
                seed=tr['seed'],steps=args.steps)
            verify()
            seal=publish(args.output,obs,banks)
            print(json.dumps(dict(seal_id=seal['seal_id'],production_authorized=False)))
        except Exception as exc:
            target=Path(args.output)
            if not target.exists():target.mkdir()
            if not (target/'COMMITTED.json').exists() and not (target/'FAILED.json').exists():
                write_json_exclusive(target/'FAILED.json',dict(
                    schema='hepta.multirc.failed-attempt.v1',error_type=type(exc).__name__,
                    model_attempted=True,production_authorized=False))
            raise
    else:
        target=Path(args.output)
        target.mkdir(exist_ok=False)
        try:
            obs=check_seal(args.run_dir,args.expected_seal_id)
            if file_sha256(args.label_file)!=args.label_sha256:
                raise ValueError('owner label bytes changed')
            labels=strict_json(args.label_file)
            report=score_sealed(obs,labels,expected_observation_id=obs['observation_id'],
                                expected_label_sha256=_digest(labels))
            write_json_exclusive(target/'scores.json',report)
            write_json_exclusive(target/'COMMITTED.json',dict(
                original_prediction_seal=args.expected_seal_id,
                report_sha256=file_sha256(target/'scores.json'),production_authorized=False))
            print(json.dumps(dict(schema=report['schema'],production_authorized=False)))
        except Exception as exc:
            write_json_exclusive(target/'FAILED.json',dict(
                schema='hepta.multirc.failed-score.v1',error_type=type(exc).__name__,
                production_authorized=False))
            raise


if __name__=='__main__':main()
