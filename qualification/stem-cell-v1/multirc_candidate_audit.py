"""Post-training, *genuine* MultiRC answer-slate audit of four frozen Readers.

The original V1 two-question training is unchanged. Only after its four
readers have been trained and sealed can this step read all genuine candidate
answer texts. Labels are never passed to model execution; score in a separate
step with externally retained material-owner labels. Not an official MultiRC
benchmark score and not causal topology or production evidence.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import torch
from safetensors.torch import load_file

from conditional_evidence import ConditionedReader
from execution_meter import WorkLedger, validate_policy
from matrix_bank import state_digest
from matrix_materials import file_sha256, strict_json
from matrix_runtime import write_json_exclusive
from multirc_candidate_slate import validate_candidate_slate, SCHEMA as SLATE_SCHEMA, LABEL_SCHEMA
from multirc_reader_study import (ARMS, POLICY, check_seal, _features, _question_text,
                                  safe_encoder)
from next_round_matrix import _digest
from paired_execution import PHASES

SCHEMA='hepta.multirc.genuine-answer-slate-frozen-readers.v1'
SCORE_SCHEMA='hepta.multirc.genuine-answer-slate-evaluation.v1'


def load_frozen_readers(run_dir, observation):
    """Verified safetensors only; do not retrain or substitute candidate banks."""
    result={}
    for arm in ARMS:
        weights=load_file(str(Path(run_dir)/(arm+'.safetensors')),device='cpu')
        w=weights.get('query.weight'); c=weights.get('classifier.weight')
        if (not isinstance(w,torch.Tensor) or not isinstance(c,torch.Tensor)
                or w.ndim!=2 or w.shape[0]!=w.shape[1] or c.shape!=(2,w.shape[0])):
            raise ValueError('trained Reader inventory or geometry unsupported')
        model=ConditionedReader(int(w.shape[0]),2)
        model.load_state_dict(weights,strict=True)
        model.eval()
        if (state_digest(model)!=observation['training'][arm]['weights_sha256']
                or sum(p.numel() for p in model.parameters())!=observation['arm_parameter_counts'][arm]
                or any(p.device.type!='cpu' or p.dtype!=torch.float32 or
                       not torch.isfinite(p).all().item() for p in model.parameters())):
            raise ValueError('trained Reader weights changed or unsupported')
        result[arm]=model
    if len(set(observation['arm_parameter_counts'].values()))!=1:
        raise ValueError('matched-parameter original training precondition failed')
    return result


def run_slate_audit(train, evaluation, slate, owner_observation, readers, *,
                    encoder, question_encoder, checkpoint_sha256, policy=POLICY,
                    replay_tolerance=1e-5,max_feature_bytes=32*1024*1024):
    """Physical one-Encoder-per-passage, all real answers, no label access."""
    validate_candidate_slate(train,evaluation,slate)
    validate_policy(policy)
    if (not isinstance(owner_observation,dict)
            or owner_observation.get('schema')!='hepta.multirc.real-question-reader.v1'
            or owner_observation.get('observation_id')!=_digest({
                k:v for k,v in owner_observation.items() if k!='observation_id'})
            or owner_observation.get('panel_id')!=evaluation['panel_id']
            or owner_observation.get('model_snapshot_sha256')!=checkpoint_sha256
            or not isinstance(readers,dict) or set(readers)!=set(ARMS)
            or type(replay_tolerance) not in (int,float)
            or not math.isfinite(replay_tolerance) or not 0<=replay_tolerance<=1e-4
            or type(max_feature_bytes) is not int or not 1024<=max_feature_bytes<=256*1024*1024):
        raise ValueError('sealed original trained reader owner required')
    reference={arm:owner_observation['predictions'][arm] for arm in ARMS}
    fingerprints={}
    for arm,reader in readers.items():
        if (not isinstance(reader,ConditionedReader) or reader.training
                or state_digest(reader)!=owner_observation['training'][arm]['weights_sha256']
                or sum(p.numel() for p in reader.parameters())!=owner_observation['arm_parameter_counts'][arm]
                or any(p.dtype!=torch.float32 or p.device.type!='cpu' or
                       not torch.isfinite(p).all().item() for p in reader.parameters())):
            raise ValueError('candidate comparison requires original finite frozen Reader')
        fingerprints[arm]=state_digest(reader)
    original_tasks=[q['task_id'] for row in evaluation['rows'] for q in row['questions']]
    if (owner_observation.get('task_ids')!=original_tasks
            or any([r.get('task_id') for r in reference[arm]]!=original_tasks for arm in ARMS)):
        raise ValueError('old original candidate prediction inventory changed')
    meter=WorkLedger(policy,dict.fromkeys(PHASES,10**14))
    results={arm:[] for arm in ARMS}
    candidate_layout=[]
    encoder_calls=query_calls=0
    max_one_passage_bytes=0
    anchors=0
    for group in slate['rows']:
        with meter.scope('inference','encoder'),torch.inference_mode():
            states=encoder(group['evidence']);encoder_calls+=1
        if (not isinstance(states,torch.Tensor) or states.ndim!=2 or not 1<=states.shape[0]<=512
                or states.dtype!=torch.float32 or states.device.type!='cpu' or states.requires_grad
                or not torch.isfinite(states).all().item()
                or any(states.shape[1]!=reader.width for reader in readers.values())):
            raise ValueError('shared genuine passage feature is invalid')
        live_bytes=states.untyped_storage().nbytes()
        for question in group['questions']:
            for candidate in question['candidates']:
                with meter.scope('inference','material'),torch.inference_mode():
                    q=question_encoder(_question_text(dict(question=question['question'],
                                                          answer=candidate['answer'])))
                    query_calls+=1
                if (not isinstance(q,torch.Tensor) or q.shape!=(states.shape[1],)
                        or q.dtype!=torch.float32 or q.device.type!='cpu' or q.requires_grad
                        or not torch.isfinite(q).all().item()):
                    raise ValueError('genuine answer query feature is invalid')
                live_bytes+=q.untyped_storage().nbytes()
                if live_bytes>max_feature_bytes:
                    raise ValueError('one-passage exact feature budget exceeded')
                original=candidate['task_id']==question['original_task_id']
                candidate_layout.append(dict(source_group=group['source_group'],
                    question_slot=question['question_slot'],task_id=candidate['task_id'],
                    candidate_id=candidate['candidate_id'],original_v1_candidate=original))
                for arm,reader in readers.items():
                    with meter.scope('inference','bank'),torch.inference_mode():
                        xx,qq=_features(states,q,arm)
                        values=reader(xx,qq)
                    if values.shape!=(2,) or not torch.isfinite(values).all().item():
                        raise ValueError('untrusted frozen candidate logits')
                    logits=[float(v) for v in values]
                    if original:
                        old=reference[arm][anchors]
                        if (old.get('task_id')!=candidate['task_id'] or
                            old.get('source_group')!=group['source_group'] or
                            old.get('weights_sha256')!=fingerprints[arm] or
                            not isinstance(old.get('logits'),list) or len(old['logits'])!=2 or
                            any(type(v) not in (int,float) or not math.isfinite(v)
                                for v in old['logits']) or
                            any(abs(a-b)>replay_tolerance for a,b in zip(logits,old['logits'],strict=True))):
                            raise ValueError('original answer logits failed frozen replay')
                    results[arm].append(dict(task_id=candidate['task_id'],
                        source_group=group['source_group'],question_slot=question['question_slot'],
                        logits=logits,weights_sha256=fingerprints[arm]))
                if original:anchors+=1
        max_one_passage_bytes=max(max_one_passage_bytes,live_bytes)
    if (anchors!=len(original_tasks) or
            any(state_digest(readers[a])!=fingerprints[a] for a in ARMS)):
        raise ValueError('original anchor denominator or model parameters changed')
    work=meter.report()
    if work['unknown_operators'] or work['phase_flops']['inference'] is None:
        raise ValueError('unknown or unmetered candidate evaluation cost')
    observation=dict(schema=SCHEMA,source_panel_id=evaluation['panel_id'],
        slate_id=slate['slate_id'],original_observation_id=owner_observation['observation_id'],
        model_snapshot_sha256=checkpoint_sha256,arm_parameter_counts=owner_observation['arm_parameter_counts'],
        rows=candidate_layout,predictions=results,
        passage_count=len(slate['rows']),question_count=2*len(slate['rows']),
        actual_candidate_count=len(candidate_layout),original_v1_anchors_replayed=anchors,
        shared_evidence_encoder_calls=encoder_calls,actual_question_encoder_calls=query_calls,
        actual_reader_calls=query_calls*len(ARMS),max_one_passage_feature_bytes=max_one_passage_bytes,
        additional_work_observation=work,additional_work_not_in_original_training=True,
        evaluation_labels_loaded=False,native_candidates_not_cross_question_fabrications=True,
        previous_v1_training_unchanged=True,statistical_superiority_established=False,
        complete_system_resource_qualification=False,production_authorized=False)
    observation['observation_id']=_digest(observation)
    return observation


def score_candidate_slate(observation,slate,owner_labels,*,expected_observation_id,
                          expected_labels_sha256):
    """Scores ONLY existing human-labeled candidates after prediction sealing."""
    if (not isinstance(observation,dict) or observation.get('schema')!=SCHEMA
            or observation.get('observation_id')!=expected_observation_id
            or _digest({k:v for k,v in observation.items() if k!='observation_id'})!=expected_observation_id
            or not isinstance(slate,dict) or slate.get('schema')!=SLATE_SCHEMA
            or _digest({k:v for k,v in slate.items() if k!='slate_id'})!=slate.get('slate_id')
            or observation['slate_id']!=slate['slate_id']
            or not isinstance(owner_labels,dict) or owner_labels.get('schema')!=LABEL_SCHEMA
            or owner_labels.get('slate_id')!=slate['slate_id']
            or _digest(owner_labels)!=expected_labels_sha256):
        raise ValueError('immutable label-blind slate prediction/owner label identity required')
    ids=[x['task_id'] for x in observation['rows']]
    registered=[dict(task_id=c['task_id'],source_group=row['source_group'],
                     question_slot=q['question_slot'],candidate_id=c['candidate_id'],
                     original_v1_candidate=c['task_id']==q['original_task_id'])
                for row in slate['rows'] for q in row['questions'] for c in q['candidates']]
    if (observation.get('rows')!=registered or ids!=[x['task_id'] for x in registered]
            or len(set(ids))!=len(ids) or set(owner_labels.get('labels',{}))!=set(ids)
            or observation.get('source_panel_id')!=slate['source_panel_id']
            or observation.get('actual_candidate_count')!=len(ids)
            or observation.get('passage_count')!=len(slate['rows'])
            or observation.get('question_count')!=2*len(slate['rows'])
            or observation.get('original_v1_anchors_replayed')!=2*len(slate['rows'])
            or observation.get('evaluation_labels_loaded') is not False):
        raise ValueError('candidate denominator, owner or source identity differs from native slate')
    labels=owner_labels['labels']; by_arm={}
    correct_vectors={}
    for arm in ARMS:
        pred=observation['predictions'].get(arm)
        if (not isinstance(pred,list) or len(pred)!=len(ids)
                or [x.get('task_id') for x in pred]!=ids):
            raise ValueError('candidate prediction count or order changed')
        predictions=[];brier=0.;by_passage={};by_question={};query_probabilities={}
        for i,item in enumerate(pred):
            meta=observation['rows'][i]
            if (item.get('source_group')!=meta['source_group']
                or item.get('question_slot')!=meta['question_slot']
                or item.get('weights_sha256')!=observation['predictions'][arm][0]['weights_sha256']):
                raise ValueError('candidate source or frozen weight identity changed')
            logits=item.get('logits');truth=labels[ids[i]]
            if (type(truth) is not int or truth not in (0,1) or not isinstance(logits,list)
                    or len(logits)!=2 or any(type(x) not in (int,float)
                                             or not math.isfinite(x) for x in logits)):
                raise ValueError('invalid human label or candidate logits')
            peak=max(logits);ex=[math.exp(x-peak) for x in logits];p=[x/sum(ex) for x in ex]
            hit=int(logits.index(peak)==truth)
            predictions.append(hit)
            brier+=sum((p[j]-int(j==truth))**2 for j in (0,1))
            source=meta['source_group']; key=source+':'+str(meta['question_slot'])
            bx=by_passage.setdefault(source,dict(correct=0,total=0));bx['correct']+=hit;bx['total']+=1
            by_question.setdefault(key,[]).append(hit)
            query_probabilities.setdefault(key,[]).append((truth,p[1]))
        spans=[max(v for _,v in probs)-min(v for _,v in probs)
               for probs in query_probabilities.values()]
        mixed=[(sum(prob for y,prob in pairs if y==1)/sum(y==1 for y,_ in pairs)
                -sum(prob for y,prob in pairs if y==0)/sum(y==0 for y,_ in pairs))
               for pairs in query_probabilities.values()
               if any(y==1 for y,_ in pairs) and any(y==0 for y,_ in pairs)]
        by_arm[arm]=dict(correct=sum(predictions),total=len(predictions),
            accuracy=sum(predictions)/len(predictions),brier=brier/len(predictions),
            complete_question_count=sum(all(vec) for vec in by_question.values()),
            registered_questions=len(by_question),
            mean_within_question_native_answer_probability_span=sum(spans)/len(spans),
            near_invariant_native_answer_question_count=sum(v<=0.001 for v in spans),
            mixed_label_question_count=len(mixed),
            mean_true_vs_false_candidate_probability_gap=(sum(mixed)/len(mixed) if mixed else None),
            complete_passage_count=sum(all(v['correct']==v['total'] for k,v in by_passage.items()
                                          if k==group['source_group']) for group in slate['rows']),
            by_passage=by_passage,statistical_superiority_established=False)
        correct_vectors[arm]=predictions
    paired={}
    for control in ARMS:
        if control=='conditioned':continue
        recovered=lost=0
        for a,b in zip(correct_vectors['conditioned'],correct_vectors[control],strict=True):
            recovered+=int(a and not b);lost+=int(b and not a)
        paired[control]=dict(recovered=recovered,lost=lost,
            other_outcomes=len(ids)-recovered-lost,
            conditioned_minus_control_accuracy=(recovered-lost)/len(ids))
    return dict(schema=SCORE_SCHEMA,slate_id=slate['slate_id'],
        observation_id=expected_observation_id,owner_labels_sha256=expected_labels_sha256,
        candidate_count=len(ids),question_count=observation['question_count'],
        independent_passage_count_not_verified=observation['passage_count'],
        results=by_arm,paired=paired,
        majority_candidate_label_accuracy=max(sum(v==0 for v in labels.values()),
                    sum(v==1 for v in labels.values()))/len(ids),
        official_multirc_score_established=False,original_v1_training_unchanged=True,
        independent_test_quality_established=False,production_authorized=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    commands=p.add_subparsers(dest='cmd',required=True)
    run=commands.add_parser('run')
    for key in ('train-bundle','blind-eval-bundle','candidate-slate','run-dir',
                'expected-seal-id','snapshot','output'):
        run.add_argument('--'+key,required=True)
    score=commands.add_parser('score')
    for key in ('candidate-slate','audit-dir','expected-audit-seal-id','owner-labels',
                'expected-label-sha256','output'):
        score.add_argument('--'+key,required=True)
    args=p.parse_args();root=Path(args.output);root.mkdir(exist_ok=False)
    try:
        slate=strict_json(args.candidate_slate)
        if args.cmd=='run':
            train=strict_json(args.train_bundle);evaluation=strict_json(args.blind_eval_bundle)
            owner=check_seal(args.run_dir,args.expected_seal_id)
            readers=load_frozen_readers(args.run_dir,owner)
            evidence,query,verify,ckpt,full,loading=safe_encoder(args.snapshot)
            record=run_slate_audit(train,evaluation,slate,owner,readers,
                                   encoder=evidence,question_encoder=query,
                                   checkpoint_sha256=ckpt)
            verify()
            write_json_exclusive(root/'audit.json',record)
            manifest=dict(schema='hepta.multirc.genuine-answer-slate-seal.v1',
                observation_id=record['observation_id'],
                observation_sha256=file_sha256(root/'audit.json'),
                source_owner_seal=args.expected_seal_id,
                model_weights_uploaded=False,labels_loaded=False,production_authorized=False)
            manifest['seal_id']=_digest(manifest)
            write_json_exclusive(root/'COMMITTED.json',manifest)
            print(manifest['seal_id'])
        else:
            manifest=strict_json(Path(args.audit_dir)/'COMMITTED.json')
            if (manifest.get('schema')!='hepta.multirc.genuine-answer-slate-seal.v1'
                    or manifest.get('seal_id')!=args.expected_audit_seal_id
                    or _digest({k:v for k,v in manifest.items() if k!='seal_id'})!=args.expected_audit_seal_id
                    or file_sha256(Path(args.audit_dir)/'audit.json')!=manifest['observation_sha256']
                    or (Path(args.audit_dir)/'FAILED.json').exists()
                    or file_sha256(args.owner_labels)!=args.expected_label_sha256):
                raise ValueError('owner sealed audit or labels changed')
            observation=strict_json(Path(args.audit_dir)/'audit.json')
            receipt=strict_json(args.owner_labels)
            scores=score_candidate_slate(observation,slate,receipt,
                expected_observation_id=manifest['observation_id'],
                expected_labels_sha256=_digest(receipt))
            write_json_exclusive(root/'scores.json',scores)
            write_json_exclusive(root/'COMMITTED.json',dict(
                schema='hepta.multirc.genuine-slate-score-seal.v1',
                source_seal=args.expected_audit_seal_id,
                scores_sha256=file_sha256(root/'scores.json'),production_authorized=False))
    except Exception as exc:
        write_json_exclusive(root/'FAILED.json',dict(schema='hepta.multirc.candidate-slate-failed.v1',
            error_type=type(exc).__name__,production_authorized=False))
        raise

if __name__=='__main__':main()
