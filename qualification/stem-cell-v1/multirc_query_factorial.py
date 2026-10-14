"""Blinded 2x2 question/answer swap on one trained MultiRC Reader.

For each passage, the original two (question, candidate-answer) pairs yield a
factorial table. The two cross-pairs are deliberately counterfactual and do NOT
have human ground-truth labels. Only probability movement is reported.

This is a separate fully charged execution: no free Encoder or query inference,
no retraining, no label loading, and no claim that a constructed question/answer
cross-pair represents a valid reading-comprehension item.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import torch

from execution_meter import WorkLedger, validate_policy
from matrix_bank import state_digest
from matrix_materials import strict_json, file_sha256
from matrix_runtime import write_json_exclusive
from multirc_materials import validate_panel_bundles
from multirc_reader_study import POLICY, _question_text, check_seal, safe_encoder
from multirc_evidence_stress import _positive_probability, _logits, load_conditioned_bank
from next_round_matrix import _digest
from paired_execution import PHASES

SCHEMA = 'hepta.multirc.blind-question-answer-factorial.v1'
INSENSITIVITY_PROBE_EPSILON = 0.001  # descriptive, not a success/failure gate


def audit_question_answer_factors(train, evaluation, observation, reader, *,
                                  encoder, question_encoder, checkpoint_sha256,
                                  original_stress=None, policy=POLICY,
                                  replay_abs_tolerance=1e-5,
                                  max_feature_bytes=8*1024*1024):
    """Distinguish question and answer effects while holding evidence fixed."""
    validate_panel_bundles(train, evaluation)
    validate_policy(policy)
    if (not isinstance(observation, dict)
            or observation.get('schema')!='hepta.multirc.real-question-reader.v1'
            or observation.get('observation_id') != _digest({
                k:v for k,v in observation.items() if k!='observation_id'})
            or observation.get('panel_id')!=evaluation['panel_id']
            or observation.get('model_snapshot_sha256')!=checkpoint_sha256
            or not isinstance(reader, torch.nn.Module) or reader.training
            or state_digest(reader)!=observation['training']['conditioned']['weights_sha256']
            or type(replay_abs_tolerance) not in (float,int)
            or not math.isfinite(replay_abs_tolerance)
            or not 0<=replay_abs_tolerance<=1e-4
            or type(max_feature_bytes) is not int
            or not 1024<=max_feature_bytes<=256*1024*1024):
        raise ValueError('one sealed frozen trained Reader and exact labeled-blind panel required')
    weight_identity=state_digest(reader)
    for parameter in reader.parameters():
        if (parameter.dtype!=torch.float32 or parameter.device.type!='cpu'
                or not torch.isfinite(parameter).all().item()):
            raise ValueError('CPU FP32 finite Reader is required')
    frozen=observation['predictions'].get('conditioned')
    expected=[(row['source_group'],q['task_id'])
              for row in evaluation['rows'] for q in row['questions']]
    if (not isinstance(frozen,list) or len(expected)!=len(frozen)
            or len(expected)!=observation['eval_examples']
            or [(r.get('source_group'),r.get('task_id')) for r in frozen]!=expected):
        raise ValueError('complete ordered frozen prediction inventory required')
    if original_stress is not None:
        if (not isinstance(original_stress,dict)
                or original_stress.get('schema')!='hepta.multirc.blind-evidence-stress.v1'
                or original_stress.get('stress_id')!=_digest({
                    k:v for k,v in original_stress.items() if k!='stress_id'})
                or original_stress.get('source_observation_id')!=observation['observation_id']
                or original_stress.get('source_panel_id')!=evaluation['panel_id']
                or original_stress.get('source_snapshot_sha256')!=checkpoint_sha256
                or original_stress.get('trained_reader_weights_sha256')!=weight_identity
                or original_stress.get('task_count')!=len(expected)
                or len(original_stress.get('observations',[]))!=len(expected)):
            raise ValueError('original blinded evidence stress does not match sealed owner')
    meter=WorkLedger(policy, dict.fromkeys(PHASES,10**14))
    rows=[]
    paired_index=0
    peak_feature_bytes=0
    for passage in evaluation['rows']:
        with meter.scope('inference','encoder'),torch.inference_mode():
            states=encoder(passage['evidence'])
        if (not isinstance(states,torch.Tensor) or states.ndim!=2
                or not 1<=states.shape[0]<=512 or states.shape[1]!=reader.width
                or states.dtype!=torch.float32 or states.device.type!='cpu'
                or states.requires_grad or not torch.isfinite(states).all().item()):
            raise ValueError('invalid frozen passage feature tensor')
        pair=passage['questions']
        if len(pair)!=2:
            raise ValueError('two registered questions per passage required')
        all_queries={}
        byte_count=states.untyped_storage().nbytes()
        for qid in range(2):
            for aid in range(2):
                # Changing only question or only candidate has no valid
                # ground-truth label. Compute a genuine alternative embedding.
                candidate={'question':pair[qid]['question'],'answer':pair[aid]['answer']}
                with meter.scope('inference','material'),torch.inference_mode():
                    feature=question_encoder(_question_text(candidate))
                if (not isinstance(feature,torch.Tensor) or feature.shape!=(reader.width,)
                        or feature.dtype!=torch.float32 or feature.device.type!='cpu'
                        or feature.requires_grad or not torch.isfinite(feature).all().item()):
                    raise ValueError('invalid newly embedded question/answer factor')
                byte_count+=feature.untyped_storage().nbytes()
                if byte_count>max_feature_bytes:
                    raise ValueError('one source passage and its query factors exceed cap')
                all_queries[qid,aid]=feature
        peak_feature_bytes=max(peak_feature_bytes,byte_count)
        logits={key:_logits(reader,states,q,meter) for key,q in all_queries.items()}
        p={key:_positive_probability(val) for key,val in logits.items()}
        for slot in range(2):
            original=logits[slot,slot]
            other=1-slot
            match=frozen[paired_index]
            if (match.get('weights_sha256')!=weight_identity
                    or not isinstance(match.get('logits'),list)
                    or len(match['logits'])!=2
                    or any(type(v) not in (int,float) or not math.isfinite(v) for v in match['logits'])
                    or any(abs(a-b)>replay_abs_tolerance for a,b in zip(original,match['logits'],strict=True))):
                raise ValueError('trained Reader did not replay original sealed prediction')
            if original_stress is not None:
                old=original_stress['observations'][paired_index]
                if (old.get('task_id')!=match['task_id']
                        or old.get('source_group')!=passage['source_group']
                        or old.get('question_slot')!=slot
                        or not isinstance(old.get('other_question_logits'),list)
                        or len(old['other_question_logits'])!=2
                        or any(abs(a-b)>replay_abs_tolerance for a,b in zip(
                            logits[other,other],old['other_question_logits'],strict=True))):
                    raise ValueError('old cross-question stress does not replay')
            original_probability=p[slot,slot]
            row=dict(task_id=match['task_id'],source_group=passage['source_group'],
                question_slot=slot,positive_probability_original=original_probability,
                abs_change_question_only=abs(p[other,slot]-original_probability),
                abs_change_answer_only=abs(p[slot,other]-original_probability),
                abs_change_question_and_answer=abs(p[other,other]-original_probability))
            rows.append(row)
            paired_index+=1
    if paired_index!=len(frozen) or state_digest(reader)!=weight_identity:
        raise ValueError('trained Reader or paired inventory changed after interventions')
    observed=meter.report()
    if observed['unknown_operators'] or observed['phase_flops']['inference'] is None:
        raise ValueError('cannot publish unknown or incomplete intervention costs')
    effects=('abs_change_question_only','abs_change_answer_only','abs_change_question_and_answer')
    means={name:sum(row[name] for row in rows)/len(rows) for name in effects}
    near_zero={name:sum(row[name]<=INSENSITIVITY_PROBE_EPSILON for row in rows)
               for name in effects}
    report=dict(schema=SCHEMA,source_observation_id=observation['observation_id'],
        source_panel_id=evaluation['panel_id'],source_snapshot_sha256=checkpoint_sha256,
        trained_reader_weights_sha256=weight_identity,
        related_blinded_stress_id=original_stress['stress_id'] if original_stress is not None else None,
        passage_count=len(evaluation['rows']),question_count=len(rows),
        physical_encoder_calls=len(evaluation['rows']),
        newly_computed_question_embeddings=4*len(evaluation['rows']),
        conditioned_reader_calls=4*len(evaluation['rows']),
        maximum_one_passage_feature_storage_bytes=peak_feature_bytes,
        records=rows,mean_absolute_positive_probability_change=means,
        insensitive_epsilon=INSENSITIVITY_PROBE_EPSILON,
        insensitive_question_counts=near_zero,
        work_observation=observed,work_separate_from_original_inference=True,
        cross_question_answer_combinations_have_no_valid_labels=True,
        counterfactual_accuracy=None,independent_question_understanding_established=False,
        source_group_independence_verified=False,statistical_superiority_established=False,
        native_or_production_authorized=False)
    report['factorial_id']=_digest(report)
    return report


def _verified_original_stress(root, expected_seal):
    root=Path(root)
    seal=strict_json(root/'COMMITTED.json')
    if (seal.get('schema')!='hepta.multirc.blind-evidence-stress-seal.v1'
            or seal.get('seal_id')!=expected_seal
            or _digest({k:v for k,v in seal.items() if k!='seal_id'})!=expected_seal
            or (root/'FAILED.json').exists()
            or file_sha256(root/'stress.json')!=seal.get('stress_sha256')):
        raise ValueError('exact original stress artifact seal required')
    report=strict_json(root/'stress.json')
    if report.get('stress_id')!=seal.get('stress_id'):
        raise ValueError('stress artifact identity differs from seal')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('train-bundle','blind-eval-bundle','run-dir','expected-seal-id',
                 'stress-dir','expected-stress-seal-id','snapshot','output'):
        p.add_argument('--'+name,required=True)
    args=p.parse_args()
    out=Path(args.output)
    out.mkdir(exist_ok=False)
    try:
        frozen=check_seal(args.run_dir,args.expected_seal_id)
        train=strict_json(args.train_bundle)
        evaluation=strict_json(args.blind_eval_bundle)
        stress=_verified_original_stress(args.stress_dir,args.expected_stress_seal_id)
        encoder,query,verify,ckpt,full,loading=safe_encoder(args.snapshot)
        reader=load_conditioned_bank(Path(args.run_dir)/'conditioned.safetensors',frozen)
        result=audit_question_answer_factors(train,evaluation,frozen,reader,
            encoder=encoder,question_encoder=query,checkpoint_sha256=ckpt,
            original_stress=stress)
        verify()
        write_json_exclusive(out/'factorial.json',result)
        manifest=dict(schema='hepta.multirc.blind-factorial-seal.v1',
            owner_prediction_seal=args.expected_seal_id,
            source_stress_seal=args.expected_stress_seal_id,
            factorial_id=result['factorial_id'],
            factorial_sha256=file_sha256(out/'factorial.json'),
            externally_labeled_answers_used=False,
            weights_uploaded=False,production_authorized=False)
        manifest['seal_id']=_digest(manifest)
        write_json_exclusive(out/'COMMITTED.json',manifest)
        print(json.dumps(dict(factorial_id=result['factorial_id'],production_authorized=False)))
    except Exception as error:
        write_json_exclusive(out/'FAILED.json',dict(schema='hepta.multirc.blind-factorial-failure.v1',
            error_type=type(error).__name__,production_authorized=False))
        raise


if __name__=='__main__':
    main()
