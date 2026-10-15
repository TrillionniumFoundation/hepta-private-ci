"""Matched-update, train-only authentic MultiRC answers versus first-answer controls.

Separate, prospective research arm atop V1. Four equal-parameter trained Readers:
first-answer/complete-answer training x conditioned/mean-pool Reader. Only
source-validated TRAIN labels enter fitting. Material-owner TEST labels are not
read until a sealed scoring step. No empirical result is inferred by this code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import torch

from conditional_evidence import ConditionedReader, TrainingCase, fit_reader
from execution_meter import WorkLedger, validate_policy
from matrix_bank import state_digest
from matrix_materials import strict_json, file_sha256
from matrix_runtime import write_json_exclusive
from multirc_candidate_slate import validate_candidate_slate, LABEL_SCHEMA
from multirc_materials import _group_inputs, _digest, validate_panel_bundles, load_parquet, _typed_int, _string
from multirc_reader_study import _features, _question_text, POLICY, safe_encoder
from paired_execution import PHASES

MATERIAL_SCHEMA='hepta.multirc.train-native-slate.v1'
PREDICTION_SCHEMA='hepta.multirc.matched-native-learning.v1'
SCORE_SCHEMA='hepta.multirc.matched-native-score.v1'
TRAIN_SCHEDULES=('first', 'all_native')
READOUTS=('conditioned','mean_pool_query_fused')
ARM_KEYS=tuple(f'{schedule}_{readout}' for schedule in TRAIN_SCHEDULES for readout in READOUTS)


def prepare_train_slate(train, source_rows):
    """All genuine alternatives for EXACTLY the train-side selected questions.

    No label is used to choose a paragraph, question, answer, or count. Only
    previously selected train sources and fixed ascending candidate IDs enter.
    """
    if not isinstance(train,dict) or train.get('schema')!='hepta.multirc.two-question-material.v1' or train.get('split')!='train':
        raise ValueError('original train-only bundle required')
    admitted=_group_inputs(source_rows,'train')
    index={}
    for pid,text,items in admitted:
        sid=hashlib.sha256(f'train:passage:{pid}:{_digest(text)}'.encode()).hexdigest()[:32]
        if sid in index: raise ValueError('source group SHA collision')
        index[sid]=(pid,text,items)
    included={group['source_group'] for group in train['rows']}
    if len(included)!=len(train['rows']) or not included <= set(index):
        raise ValueError('training passage was not admitted by original source')
    # Every admitted original paragraph is known complete; preserve its precise
    # (question ID, answer ID) identities and label values, never sample by y.
    selected_pid={index[g][0] for g in included}
    actual={}
    for row in source_rows:
        pid=row['idx']['paragraph']
        if pid not in selected_pid: continue
        key=(pid,row['idx']['question'])
        q=actual.setdefault(key,dict(text=row['question'],answers={}))
        aid=row['idx']['answer']
        if q['text']!=row['question'] or aid in q['answers']:
            raise ValueError('source training answer/question identity duplicated')
        q['answers'][aid]=(row['answer'],row['label'])
    expanded=[]
    for original in train['rows']:
        sid=original['source_group'];pid,text,items=index[sid]
        if original['evidence']!=text or len(original['questions'])!=2:
            raise ValueError('selected source group differs from original train panel')
        groups=[]
        for slot,(qid,first_aid,question,first_answer,first_label) in enumerate(items):
            anchor=original['questions'][slot]
            q=actual.get((pid,qid))
            if (q is None or q['text']!=question or anchor['question']!=question
                    or anchor['answer']!=first_answer or anchor['label']!=first_label):
                raise ValueError('first original training candidate changed')
            ans=[]
            for aid in sorted(q['answers']):
                value,target=q['answers'][aid]
                task=hashlib.sha256(f'{sid}:q{qid}:a{aid}'.encode()).hexdigest()[:32]
                ans.append(dict(task_id=task,candidate_id=aid,answer=value,label=target))
            if (not 2<=len(ans)<=8 or ans[0]['task_id']!=anchor['task_id']
                    or ans[0]['answer']!=anchor['answer'] or ans[0]['label']!=anchor['label']
                    or ans[0]['candidate_id']!=first_aid):
                raise ValueError('incomplete native training answer slate or changed first candidate')
            groups.append(dict(question_slot=slot,question=question,original_task_id=anchor['task_id'],candidates=ans))
        expanded.append(dict(source_group=sid,evidence=text,questions=groups))
    result=dict(schema=MATERIAL_SCHEMA,source_panel_id=train['panel_id'],
        source_sha256_train=train['source_sha256_train'],rows=expanded,
        selected_passage_count=len(expanded),candidate_count=sum(len(q['candidates']) for r in expanded for q in r['questions']),
        original_training_candidate_count=len(expanded)*2,
        candidate_inclusion='all-label-blind-genuine-train-alternatives',
        only_training_labels_present=True,production_authorized=False)
    result['material_id']=_digest(result)
    validate_train_slate(train,result)
    return result


def validate_train_slate(train,material):
    if (not isinstance(material,dict) or material.get('schema')!=MATERIAL_SCHEMA
            or material.get('material_id')!=_digest({k:v for k,v in material.items() if k!='material_id'})
            or material.get('source_panel_id')!=train.get('panel_id')
            or material.get('source_sha256_train')!=train.get('source_sha256_train')
            or material.get('candidate_inclusion')!='all-label-blind-genuine-train-alternatives'
            or material.get('only_training_labels_present') is not True
            or material.get('production_authorized') is not False
            or material.get('selected_passage_count')!=len(train.get('rows',[]))
            or not isinstance(material.get('rows'),list) or len(material['rows'])!=len(train['rows'])):
        raise ValueError('sealed selected native training material required')
    count=0;seen=set()
    for source,entry in zip(train['rows'],material['rows'],strict=True):
        if (not isinstance(entry,dict) or set(entry)!={'source_group','evidence','questions'}
                or entry['source_group']!=source['source_group'] or entry['evidence']!=source['evidence']
                or not isinstance(entry['questions'],list) or len(entry['questions'])!=2):
            raise ValueError('training source/order drift')
        for slot,(q,anchor) in enumerate(zip(entry['questions'],source['questions'],strict=True)):
            if (not isinstance(q,dict) or set(q)!={'question_slot','question','original_task_id','candidates'}
                    or q['question_slot']!=slot or q['question']!=anchor['question']
                    or q['original_task_id']!=anchor['task_id']
                    or not isinstance(q['candidates'],list) or not 2<=len(q['candidates'])<=8):
                raise ValueError('incomplete train question and answer counts')
            aids=[]
            for c in q['candidates']:
                if (not isinstance(c,dict) or set(c)!={'task_id','candidate_id','answer','label'}
                        or not _typed_int(c['candidate_id']) or not _string(c['answer'],4096)
                        or type(c['label']) is not int or c['label'] not in (0,1)
                        or not _string(c['task_id'],64) or c['task_id'] in seen):
                    raise ValueError('invalid original training answer')
                aids.append(c['candidate_id']);seen.add(c['task_id']);count+=1
            if aids!=sorted(set(aids)) or q['candidates'][0]['task_id']!=anchor['task_id'] or q['candidates'][0]['label']!=anchor['label'] or q['candidates'][0]['answer']!=anchor['answer']:
                raise ValueError('train anchor mismatch or unsorted/duplicate alternatives')
    if material.get('candidate_count')!=count or material.get('original_training_candidate_count')!=len(train['rows'])*2:
        raise ValueError('native training denominator changed')
    return True


def fit_and_evaluate(train, train_slate, evaluation_loader, *, encoder, question_encoder,
                     checkpoint_sha256, seed=7347, steps=64, policy=POLICY,
                     max_feature_bytes=32*1024*1024,max_total_feature_bytes=256*1024*1024):
    """Fit four matched-update Readers before calling evaluation_loader once.

    Study comparisons are paired on the exact same genuine validation slate.
    Fixed updates DO NOT imply equal work; all source, fit and eval work is kept.
    """
    validate_train_slate(train,train_slate)
    validate_policy(policy)
    if (not callable(evaluation_loader) or type(seed) is not int or seed<1
            or type(steps) is not int or not 1<=steps<=512
            or any(type(x) is not int or x<1024 for x in (max_feature_bytes,max_total_feature_bytes))
            or not isinstance(checkpoint_sha256,str) or len(checkpoint_sha256)!=64):
        raise ValueError('bounded preregistered native learning comparison required')
    caps=dict.fromkeys(PHASES,10**14)
    acquisition=WorkLedger(policy,caps)
    source_features=[];num_train_queries=0;storage_total=0;width=None
    for group in train_slate['rows']:
        with acquisition.scope('train','encoder'),torch.inference_mode():
            raw=encoder(group['evidence'])
        if (not isinstance(raw,torch.Tensor) or raw.ndim!=2 or not 1<=raw.shape[0]<=512
                or raw.dtype!=torch.float32 or raw.device.type!='cpu' or raw.requires_grad
                or not torch.isfinite(raw).all().item()):
            raise ValueError('untrusted frozen training evidence geometry')
        if width is None: width=raw.shape[1]
        if raw.shape[1]!=width or raw.untyped_storage().nbytes()>max_feature_bytes:
            raise ValueError('encoder width or feature budget changed')
        with torch.inference_mode(False): stable=raw.detach().clone()
        storage_total+=stable.untyped_storage().nbytes()
        for question in group['questions']:
            for item in question['candidates']:
                with acquisition.scope('train','material'),torch.inference_mode():
                    q=question_encoder(_question_text(dict(question=question['question'],answer=item['answer'])))
                if (not isinstance(q,torch.Tensor) or q.shape!=(width,) or q.dtype!=torch.float32
                        or q.device.type!='cpu' or q.requires_grad or not torch.isfinite(q).all().item()
                        or q.untyped_storage().nbytes()>max_feature_bytes):
                    raise ValueError('untrusted native candidate question feature')
                with torch.inference_mode(False): query=q.detach().clone()
                storage_total+=query.untyped_storage().nbytes()
                if storage_total>max_total_feature_bytes:
                    raise ValueError('retained native training feature budget exceeded')
                source_features.append((group['source_group'],question['question_slot'],item['candidate_id'],
                                        stable,query,item['label']))
                num_train_queries+=1
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        start=ConditionedReader(width,2).eval()
    banks={}; training={}; projections={}
    for schedule in TRAIN_SCHEDULES:
        for readout in READOUTS:
            key=f'{schedule}_{readout}'
            chosen=[row for row in source_features if schedule=='all_native' or row[2]==min(
                c['candidate_id'] for g in train_slate['rows'] if g['source_group']==row[0]
                for q in g['questions'] if q['question_slot']==row[1] for c in q['candidates'])]
            projector=WorkLedger(policy,caps)
            with projector.scope('train','bank'):
                cases=[TrainingCase(*_features(s,q,readout),label,group,5)
                       for group,slot,cid,s,q,label in chosen]
            projections[key]=projector.report()
            meter=WorkLedger(policy,caps)
            fitted,receipt=fit_reader(start,cases,cutoff_ns=10,seed=seed,
                steps=steps,learning_rate=.003,meter=meter)
            banks[key]=fitted
            training[key]=dict(**receipt,observed_formula_work=meter.report(),
                case_count=len(cases),sample_policy=schedule,
                parameter_count=sum(p.numel() for p in fitted.parameters()),
                weights_sha256=state_digest(fitted))
    if len({v['parameter_count'] for v in training.values()})!=1:
        raise ValueError('matched Reader parameter precondition failed')
    # Read of heldout candidates and evidence deliberately delayed until ALL
    # fits, never permitted to use heldout labels or score-dependent stopping.
    eval_bundle,slate=evaluation_loader()
    validate_candidate_slate(train,eval_bundle,slate)
    inference=WorkLedger(policy,caps)
    meta=[];pred={arm:[] for arm in ARM_KEYS}; eval_q=0;eval_e=0
    for passage in slate['rows']:
        with inference.scope('inference','encoder'),torch.inference_mode():
            states=encoder(passage['evidence']);eval_e+=1
        if (not isinstance(states,torch.Tensor) or states.ndim!=2 or not 1<=states.shape[0]<=512
                or states.shape[1]!=width or states.dtype!=torch.float32
                or states.device.type!='cpu' or states.requires_grad or not torch.isfinite(states).all().item()
                or states.untyped_storage().nbytes()>max_feature_bytes):
            raise ValueError('heldout evidence feature invalid')
        for question in passage['questions']:
            for item in question['candidates']:
                with inference.scope('inference','material'),torch.inference_mode():
                    q=question_encoder(_question_text(dict(question=question['question'],answer=item['answer'])));eval_q+=1
                if (not isinstance(q,torch.Tensor) or q.shape!=(width,) or q.dtype!=torch.float32
                        or q.device.type!='cpu' or q.requires_grad or not torch.isfinite(q).all().item()):
                    raise ValueError('heldout genuine answer representation invalid')
                meta.append(dict(task_id=item['task_id'],source_group=passage['source_group'],
                                 question_slot=question['question_slot']))
                for arm,reader in banks.items():
                    with inference.scope('inference','bank'),torch.inference_mode():
                        s,qq=_features(states,q,arm.split('_',1)[1] if arm.startswith('first_') else arm[len('all_native_'):])
                        out=reader(s,qq)
                    if out.shape!=(2,) or not torch.isfinite(out).all().item():
                        raise ValueError('Reader logits invalid')
                    pred[arm].append(dict(task_id=item['task_id'],logits=[float(v) for v in out],
                                          weights_sha256=training[arm]['weights_sha256']))
    if (len(meta)!=sum(len(q['candidates']) for r in slate['rows'] for q in r['questions'])
            or any(state_digest(banks[a])!=training[a]['weights_sha256'] for a in ARM_KEYS)):
        raise ValueError('native candidate count or fitted weight changed')
    reports=dict(source=acquisition.report(),inference=inference.report())
    if any(x['unknown_operators'] or x.get('stopped') or any(x['phase_flops'].get(phase) is None for phase in {'train','inference'} if any(row['phase']==phase for row in x['scopes'])) for x in reports.values()):
        raise ValueError('uncovered native learning inference or feature acquisition work')
    obs=dict(schema=PREDICTION_SCHEMA,source_panel_id=train['panel_id'],training_slate_id=train_slate['material_id'],
             evaluation_slate_id=slate['slate_id'],checkpoint_sha256=checkpoint_sha256,
             fixed_updates=steps,seed=seed,training=training,training_projection=projections,
             training_sources=len(train_slate['rows']),training_all_native_candidates=num_train_queries,
             training_first_candidate_count=len(train_slate['rows'])*2,
             shared_train_encoder_calls=len(train_slate['rows']),shared_eval_encoder_calls=eval_e,
             train_question_encoder_calls=num_train_queries,eval_question_encoder_calls=eval_q,
             measured_acquisition_and_inference_work=reports,
             per_arm_train_work_paid_in_fits=True,full_system_compute_parity_established=False,
             evaluation_labels_loaded_before_seal=False,trained_model_selected=False,
             rows=meta,predictions=pred,production_authorized=False)
    obs['observation_id']=_digest(obs)
    return obs,banks


def score_native_training(observation,slate,labels,*,expected_observation_id,expected_label_digest):
    """Scoring-only use of registered human labels AFTER model prediction seal."""
    if (not isinstance(observation,dict) or observation.get('schema')!=PREDICTION_SCHEMA
            or observation.get('observation_id')!=expected_observation_id
            or _digest({k:v for k,v in observation.items() if k!='observation_id'})!=expected_observation_id
            or not isinstance(slate,dict) or observation.get('evaluation_slate_id')!=slate.get('slate_id')
            or not isinstance(labels,dict) or labels.get('schema')!=LABEL_SCHEMA
            or _digest(labels)!=expected_label_digest or labels.get('slate_id')!=slate.get('slate_id')):
        raise ValueError('separately sealed real candidate predictions and human labels required')
    gold=labels.get('labels')
    tasks=[a['task_id'] for a in observation['rows']]
    if (not isinstance(gold,dict) or len(set(tasks))!=len(tasks) or set(gold)!=set(tasks)
            or any(type(v) is not int or v not in (0,1) for v in gold.values())
            or len(tasks)!=sum(len(q['candidates']) for p in slate['rows'] for q in p['questions'])):
        raise ValueError('incomplete genuine candidate labels')
    expected_flat=[dict(task_id=c['task_id'],source_group=p['source_group'],question_slot=q['question_slot'])
                   for p in slate['rows'] for q in p['questions'] for c in q['candidates']]
    if observation.get('rows')!=expected_flat or observation.get('source_panel_id')!=slate.get('source_panel_id'):
        raise ValueError('unsealed or reordered source/question/candidate attribution')
    summaries={};correctness={}
    for arm in ARM_KEYS:
        rows=observation['predictions'].get(arm)
        if not isinstance(rows,list) or len(rows)!=len(tasks) or [r.get('task_id') for r in rows]!=tasks:
            raise ValueError('candidate inventory changed')
        correct=[]; brier=0.; within={}
        for i,row in enumerate(rows):
            if row['weights_sha256']!=observation['training'][arm]['weights_sha256']:
                raise ValueError('candidate fitted weight identity drift')
            logits=row['logits']
            if (not isinstance(logits,list) or len(logits)!=2
                    or any(type(z) not in (float,int) or not math.isfinite(z) for z in logits)):
                raise ValueError('nonfinite candidate prediction')
            y=gold[tasks[i]];peak=max(logits);a,b=(math.exp(z-peak) for z in logits)
            p1=b/(a+b);hit=int(logits.index(peak)==y)
            correct.append(hit)
            brier+=(p1-y)**2+((1-p1)-(1-y))**2
            meta=observation['rows'][i]
            key=(meta['source_group'],meta['question_slot'])
            within.setdefault(key,[]).append(p1)
        summaries[arm]=dict(correct=sum(correct),total=len(correct),accuracy=sum(correct)/len(correct),
            brier=brier/len(correct),native_answer_mean_probability_span=sum(max(p)-min(p) for p in within.values())/len(within),
            question_count=len(within),statistical_superiority_established=False)
        correctness[arm]=correct
    paired={}
    for readout in READOUTS:
        first=correctness['first_'+readout];full=correctness['all_native_'+readout]
        recovered=sum(int(a and not b) for a,b in zip(full,first,strict=True))
        lost=sum(int(b and not a) for a,b in zip(full,first,strict=True))
        paired[readout]=dict(all_native_recovered=recovered,all_native_lost=lost,
            descriptive_accuracy_delta=(recovered-lost)/len(tasks))
    return dict(schema=SCORE_SCHEMA,observation_id=expected_observation_id,
        external_labels_sha256=expected_label_digest,source_slate_id=slate['slate_id'],
        results=summaries,paired_update_matched=paired,
        fixed_updates_are_not_fixed_compute=True,independent_source_groups_verified=False,
        statistical_superiority_established=False,official_multirc_qualification=False,
        training_all_native_superiority_established=False,model_selected=False,production_authorized=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='cmd',required=True)
    prep=sub.add_parser('prepare')
    for key in ('train-bundle','train-parquet','train-sha256','output'):prep.add_argument('--'+key,required=True)
    run=sub.add_parser('run')
    for key in ('train-bundle','native-train','blind-eval-bundle','native-eval-slate','snapshot','output'):
        run.add_argument('--'+key,required=True)
    run.add_argument('--steps',type=int,default=64)
    score=sub.add_parser('score')
    for key in ('run-dir','expected-seal-id','native-eval-slate','owner-labels','expected-label-sha256','output'):
        score.add_argument('--'+key,required=True)
    args=p.parse_args()
    dest=Path(args.output);dest.mkdir(exist_ok=False)
    try:
        if args.cmd=='prepare':
            bundle=strict_json(args.train_bundle)
            rows=load_parquet(args.train_parquet,expected_sha256=args.train_sha256)
            if bundle.get('source_sha256_train')!=args.train_sha256:
                raise ValueError('source training bytes differ from original panel')
            material=prepare_train_slate(bundle,rows)
            write_json_exclusive(dest/'train-native.json',material)
            write_json_exclusive(dest/'COMMITTED.json',dict(schema=MATERIAL_SCHEMA,
                material_id=material['material_id'],sha256=file_sha256(dest/'train-native.json'),
                production_authorized=False))
        elif args.cmd=='run':
            train=strict_json(args.train_bundle)
            native=strict_json(args.native_train)
            evidence,query,verify,checkpoint,full,_=safe_encoder(args.snapshot)
            obs,_=fit_and_evaluate(train,native,
                lambda:(strict_json(args.blind_eval_bundle),strict_json(args.native_eval_slate)),
                encoder=evidence,question_encoder=query,checkpoint_sha256=checkpoint,
                seed=train['seed'],steps=args.steps)
            verify()
            write_json_exclusive(dest/'predictions.json',obs)
            seal=dict(schema=PREDICTION_SCHEMA,observation_id=obs['observation_id'],
                sha256=file_sha256(dest/'predictions.json'),no_heldout_labels_loaded=True)
            seal['seal_id']=_digest(seal)
            write_json_exclusive(dest/'COMMITTED.json',seal)
        else:
            manifest=strict_json(Path(args.run_dir)/'COMMITTED.json')
            if (manifest.get('schema')!=PREDICTION_SCHEMA
                    or manifest.get('seal_id')!=args.expected_seal_id
                    or _digest({k:v for k,v in manifest.items() if k!='seal_id'})!=args.expected_seal_id
                    or (Path(args.run_dir)/'FAILED.json').exists()
                    or file_sha256(Path(args.run_dir)/'predictions.json')!=manifest.get('sha256')
                    or file_sha256(args.owner_labels)!=args.expected_label_sha256):
                raise ValueError('prediction seal or independent owner labels changed')
            obs=strict_json(Path(args.run_dir)/'predictions.json')
            slate=strict_json(args.native_eval_slate)
            labels=strict_json(args.owner_labels)
            result=score_native_training(obs,slate,labels,
                expected_observation_id=manifest['observation_id'],expected_label_digest=_digest(labels))
            write_json_exclusive(dest/'scores.json',result)
            write_json_exclusive(dest/'COMMITTED.json',dict(schema=SCORE_SCHEMA,
                score_sha256=file_sha256(dest/'scores.json'),source_seal=args.expected_seal_id))
    except Exception as exc:
        write_json_exclusive(dest/'FAILED.json',dict(schema='hepta.multirc.native-training-failed.v1',
            error_type=type(exc).__name__,production_authorized=False))
        raise

if __name__=='__main__':main()
