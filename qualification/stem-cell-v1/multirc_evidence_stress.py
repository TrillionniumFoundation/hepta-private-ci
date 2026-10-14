"""Label-blind evidence intervention on an already sealed MultiRC Reader.

This is a new, *separate* phase of the research experiment: it never fits a
candidate or inspects held-out labels. The same frozen trained conditioned Reader
is run on original evidence, genuinely encoded neutral evidence, another held-out
passage, and the same passage with the other registered question. The changed
inputs have no valid ground-truth labels: report **probability movement only**.

All extra Encoder/query/Reader computations have an independent strict CPU FP32
ledger. This work is never laundered into the original prediction-phase receipt.
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
from multirc_materials import validate_panel_bundles
from multirc_reader_study import POLICY, _question_text, check_seal, safe_encoder
from next_round_matrix import _digest
from paired_execution import PHASES

SCHEMA = 'hepta.multirc.blind-evidence-stress.v1'
NEUTRAL = 'Evidence is unavailable. No passage facts are supplied.'


def _logits(reader, states, question, ledger):
    with ledger.scope('inference', 'bank'), torch.inference_mode():
        values = reader(states, question)
    if values.shape != (2,) or not torch.isfinite(values).all().item():
        raise ValueError('non-finite/unexpected Reader logits in evidence stress')
    return [float(x) for x in values]


def _positive_probability(values):
    top = max(values)
    a, b = math.exp(values[0]-top), math.exp(values[1]-top)
    return b/(a+b)


def load_conditioned_bank(path, observation):
    """Safetensors only; verify the actual sealed fitted Reader, not a new clone."""
    path = Path(path)
    weights = load_file(str(path), device='cpu')
    if (not isinstance(weights, dict) or 'query.weight' not in weights
            or 'classifier.weight' not in weights):
        raise ValueError('complete conditioned Reader weights required')
    w = weights['query.weight']
    c = weights['classifier.weight']
    if (w.ndim != 2 or w.shape[0] != w.shape[1] or c.ndim != 2
            or c.shape != (2, w.shape[0])):
        raise ValueError('unsupported trained Reader geometry')
    reader = ConditionedReader(int(w.shape[0]), 2)
    reader.load_state_dict(weights, strict=True)
    reader.eval()
    if (state_digest(reader) != observation['training']['conditioned']['weights_sha256']
            or sum(p.numel() for p in reader.parameters()) != observation['arm_parameter_counts']['conditioned']):
        raise ValueError('trained Reader does not match frozen prediction owner')
    return reader


def audit_evidence(train_bundle, blind_eval_bundle, observation, reader, *,
                   encoder, question_encoder, checkpoint_sha256, policy=POLICY,
                   replay_abs_tolerance=1e-5, max_cached_bytes=32*1024*1024):
    """Actually re-encode a neutral passage and cross-passage negative control.

    Replays the original logits with the **same trained Reader** before accepting
    any intervention. No test label is passed in or inferred from the results.
    """
    validate_panel_bundles(train_bundle, blind_eval_bundle)
    validate_policy(policy)
    if (not isinstance(observation, dict)
            or observation.get('schema') != 'hepta.multirc.real-question-reader.v1'
            or _digest({k:v for k,v in observation.items() if k != 'observation_id'}) != observation.get('observation_id')
            or observation.get('panel_id') != blind_eval_bundle['panel_id']
            or observation.get('model_snapshot_sha256') != checkpoint_sha256
            or not isinstance(reader, ConditionedReader) or reader.training
            or state_digest(reader) != observation['training']['conditioned']['weights_sha256']
            or type(max_cached_bytes) is not int or not 1024 <= max_cached_bytes <= 256*1024*1024
            or type(replay_abs_tolerance) not in (float, int)
            or not math.isfinite(replay_abs_tolerance)
            or not 0 <= replay_abs_tolerance <= 1e-4):
        raise ValueError('sealed, frozen, bounded training owner and panel required')
    for p in reader.parameters():
        if p.device.type != 'cpu' or p.dtype != torch.float32 or not torch.isfinite(p).all().item():
            raise ValueError('CPU FP32 finite Reader weights required')
    original = observation['predictions'].get('conditioned')
    groups = blind_eval_bundle['rows']
    expected_tasks = [q['task_id'] for group in groups for q in group['questions']]
    if (not isinstance(original, list) or len(groups) < 2
            or expected_tasks != observation['task_ids']
            or len(original) != len(expected_tasks)
            or [r.get('task_id') for r in original] != expected_tasks):
        raise ValueError('incomplete original predictions or counterfactual groups')
    metering = WorkLedger(policy, dict.fromkeys(PHASES, 10**14))
    states = []
    encoded_bytes = 0
    for group in groups:
        with metering.scope('inference','encoder'), torch.inference_mode():
            state = encoder(group['evidence'])
        if (not isinstance(state, torch.Tensor) or state.ndim != 2
                or not 1 <= state.shape[0] <= 512 or state.shape[1] != reader.width
                or state.device.type != 'cpu' or state.dtype != torch.float32
                or not torch.isfinite(state).all().item() or state.requires_grad):
            raise ValueError('invalid frozen passage tensor')
        states.append(state)
        encoded_bytes += state.untyped_storage().nbytes()
        if encoded_bytes > max_cached_bytes:
            raise ValueError('actual retained passage storage budget exceeded')
    with metering.scope('inference','encoder'), torch.inference_mode():
        neutral = encoder(NEUTRAL)
    if (not isinstance(neutral,torch.Tensor) or neutral.ndim != 2
            or not 1 <= len(neutral) <= 512 or neutral.shape[1] != reader.width
            or neutral.device.type != 'cpu' or neutral.dtype != torch.float32
            or not torch.isfinite(neutral).all().item() or neutral.requires_grad):
        raise ValueError('invalid physically encoded neutral control')
    encoded_bytes += neutral.untyped_storage().nbytes()
    if encoded_bytes > max_cached_bytes:
        raise ValueError('neutral input exceeded materialized feature cap')
    queries=[]
    for group in groups:
        pair=[]
        for item in group['questions']:
            with metering.scope('inference','material'), torch.inference_mode():
                q = question_encoder(_question_text(item))
            if (not isinstance(q,torch.Tensor) or q.shape != (reader.width,)
                    or q.device.type != 'cpu' or q.dtype != torch.float32
                    or q.requires_grad or not torch.isfinite(q).all().item()):
                raise ValueError('invalid original query embedding')
            pair.append(q)
            encoded_bytes += q.untyped_storage().nbytes()
            if encoded_bytes > max_cached_bytes:
                raise ValueError('query input exceeded retained feature cap')
        queries.append(pair)
    before = state_digest(reader)
    rows=[]
    k=0
    for i, group in enumerate(groups):
        j = (i + 1) % len(groups)
        if groups[j]['source_group'] == group['source_group'] or groups[j]['evidence'] == group['evidence']:
            raise ValueError('donor passage must be a distinct source')
        for qid,item in enumerate(group['questions']):
            q = queries[i][qid]
            variants = {
                'original':_logits(reader,states[i],q,metering),
                'neutral_evidence':_logits(reader,neutral,q,metering),
                'different_passage':_logits(reader,states[j],q,metering),
                'other_question':_logits(reader,states[i],queries[i][1-qid],metering)}
            ref=original[k]
            if (ref.get('source_group') != group['source_group']
                    or ref.get('weights_sha256') != before
                    or len(ref.get('logits',[])) != 2
                    or any(abs(a-b) > replay_abs_tolerance for a,b in zip(variants['original'],ref['logits'],strict=True))):
                raise ValueError('replayed original Reader prediction differs from sealed logits')
            base = _positive_probability(variants['original'])
            change = {name:abs(_positive_probability(v)-base)
                      for name,v in variants.items() if name!='original'}
            rows.append(dict(task_id=item['task_id'],source_group=group['source_group'],
                question_slot=qid,original_logits=variants['original'],
                neutral_logits=variants['neutral_evidence'],
                other_passage_logits=variants['different_passage'],
                other_question_logits=variants['other_question'],
                absolute_positive_probability_change=change,
                donor_source_group=groups[j]['source_group']))
            k += 1
    if before != state_digest(reader) or k != len(expected_tasks):
        raise ValueError('Reader changed during blinded stress test')
    observed = metering.report()
    if observed['unknown_operators'] or observed['phase_flops']['inference'] is None:
        raise ValueError('unknown stress-test inference cost may not be published as complete')
    means={name:sum(row['absolute_positive_probability_change'][name] for row in rows)/len(rows)
           for name in ('neutral_evidence','different_passage','other_question')}
    report = dict(schema=SCHEMA,source_observation_id=observation['observation_id'],
        source_panel_id=blind_eval_bundle['panel_id'],source_snapshot_sha256=checkpoint_sha256,
        trained_reader_weights_sha256=before,
        task_count=len(rows),passage_count=len(groups),
        factual_original_replay_validated=True,
        encoder_calls=len(groups)+1,query_calls=len(rows),
        conditioned_reader_calls=4*len(rows),
        actual_cached_feature_bytes=encoded_bytes,
        original_evidence_correctness_not_assessed=True,
        counterfactual_answer_labels_undefined=True,
        mean_absolute_positive_probability_change=means,
        observations=rows,stress_work=observed,
        stress_work_not_in_original_phase_receipt=True,
        independent_training_gain_established=False,
        source_group_independence_authenticated=False,
        missing_premise_correctness_certified=False,
        statistical_superiority_established=False,
        production_authorized=False)
    report['stress_id']=_digest(report)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--train-bundle',required=True)
    p.add_argument('--blind-eval-bundle',required=True)
    p.add_argument('--run-dir',required=True)
    p.add_argument('--expected-seal-id',required=True)
    p.add_argument('--snapshot',required=True)
    p.add_argument('--output',required=True)
    args=p.parse_args()
    out=Path(args.output)
    out.mkdir(exist_ok=False)
    try:
        frozen=check_seal(args.run_dir,args.expected_seal_id)
        train,eval_bundle=strict_json(args.train_bundle),strict_json(args.blind_eval_bundle)
        evidence,query,verify,checkpoint,full,loading=safe_encoder(args.snapshot)
        reader=load_conditioned_bank(Path(args.run_dir)/'conditioned.safetensors',frozen)
        result=audit_evidence(train,eval_bundle,frozen,reader,
                              encoder=evidence,question_encoder=query,
                              checkpoint_sha256=checkpoint)
        verify()
        write_json_exclusive(out/'stress.json',result)
        manifest=dict(schema='hepta.multirc.blind-evidence-stress-seal.v1',
            source_prediction_seal_id=args.expected_seal_id,
            stress_id=result['stress_id'],stress_sha256=file_sha256(out/'stress.json'),
            model_weights_uploaded=False,external_labels_loaded=False,
            production_authorized=False)
        manifest['seal_id']=_digest(manifest)
        write_json_exclusive(out/'COMMITTED.json',manifest)
        print(result['stress_id'])
    except Exception as exc:
        write_json_exclusive(out/'FAILED.json',dict(schema='hepta.multirc.blind-stress-failed.v1',
            error_type=type(exc).__name__,production_authorized=False))
        raise

if __name__ == '__main__':
    main()
