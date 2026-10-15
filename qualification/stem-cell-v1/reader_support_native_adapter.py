"""Source-bound V1 ModernBERT Reader → externally marked premise study.

No annotations are invented from heldout labels. This is an opt-in companion to
existing MultiRC V1, not a replacement for native-answer Reader training.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from reader_support_causal import PLAN, digest, hex64, validate_plan, run_blind, review

ANNOTATION = 'hepta.reader.external-source-spans.v1'


def build_plan(blind_eval, frozen, annotations):
    if (not isinstance(blind_eval, dict)
        or blind_eval.get('schema') != 'hepta.multirc.two-question-material.v1'
        or blind_eval.get('split') != 'validation'
        or not hex64(blind_eval.get('panel_id'))
        or not isinstance(frozen, dict)
        or frozen.get('schema') != 'hepta.multirc.real-question-reader.v1'
        or frozen.get('panel_id') != blind_eval['panel_id']
        or not hex64(frozen.get('model_snapshot_sha256'))
        or not isinstance(annotations, dict)
        or set(annotations) != {'schema', 'panel_id', 'original_observation_id',
                                 'rows', 'labels_exposed', 'support_independently_verified',
                                 'annotation_id'}
        or annotations['schema'] != ANNOTATION
        or annotations['panel_id'] != blind_eval['panel_id']
        or annotations['original_observation_id'] != frozen.get('observation_id')
        or annotations['labels_exposed'] is not False
        or annotations['support_independently_verified'] is not False
        or annotations['annotation_id'] != digest({k:v for k,v in annotations.items() if k!='annotation_id'})):
        raise ValueError('sealed, label-blind source annotation and original frozen Reader required')
    source = []
    for passage in blind_eval['rows']:
        for q in passage['questions']:
            if 'label' in q:
                raise ValueError('heldout annotation path may not load labels')
            source.append(dict(task_id=q['task_id'], source_group=passage['source_group'],
                               evidence=passage['evidence'],question=q['question'],answer=q['answer']))
    owner = annotations['rows']
    if not isinstance(owner, list) or len(owner)!=len(source):
        raise ValueError('source annotator must cover all frozen questions')
    rows = []
    for target, annotation in zip(source, owner, strict=True):
        if (not isinstance(annotation, dict) or set(annotation) != {
                'task_id','source_group','support_spans','critical_span_index'}
            or annotation['task_id'] != target['task_id']
            or annotation['source_group'] != target['source_group']):
            raise ValueError('external span annotator reordered or relabeled tasks')
        rows.append(dict(**target, support_spans=annotation['support_spans'],
                         critical_span_index=annotation['critical_span_index']))
    if ([v['task_id'] for v in frozen['predictions']['conditioned']] != [v['task_id'] for v in source]
        or frozen['task_ids'] != [v['task_id'] for v in source]
        or frozen['source_groups'] != [v['source_group'] for v in source]):
        raise ValueError('frozen original prediction / source order drift')
    plan = dict(schema=PLAN, panel_sha256=blind_eval['panel_id'],
                model_sha256=frozen['model_snapshot_sha256'], rows=rows,
                labels_available_to_runner=False, support_independently_verified=False)
    plan['plan_id'] = digest(plan)
    validate_plan(plan)
    return plan


def _references(frozen):
    return [dict(task_id=row['task_id'], source_group=row['source_group'],
                 logits=row['logits'], weights_sha256=row['weights_sha256'])
            for row in frozen['predictions']['conditioned']]


def main():
    # Late imports preserve dependency-free plan review and no automatic HF fetch.
    from matrix_materials import file_sha256, strict_json
    from matrix_runtime import write_json_exclusive
    from multirc_reader_study import check_seal, safe_encoder
    from multirc_evidence_stress import load_conditioned_bank

    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode',required=True)
    for name in ('prepare','run','score'):
        sub = modes.add_parser(name)
        sub.add_argument('--output', required=True)
        if name == 'prepare':
            for flag in ('blind-eval-bundle','run-dir','expected-v1-seal-id','external-spans'):
                sub.add_argument('--'+flag,required=True)
        elif name == 'run':
            for flag in ('plan','run-dir','expected-v1-seal-id','snapshot'):
                sub.add_argument('--'+flag,required=True)
        else:
            for flag in ('plan','observations-dir','expected-observation-id',
                         'owner-labels','expected-owner-label-file-sha256'):
                sub.add_argument('--'+flag,required=True)
    args = parser.parse_args()
    dest=Path(args.output)
    dest.mkdir(exist_ok=False)
    try:
        if args.mode == 'prepare':
            frozen=check_seal(args.run_dir,args.expected_v1_seal_id)
            plan=build_plan(strict_json(args.blind_eval_bundle), frozen,
                            strict_json(args.external_spans))
            write_json_exclusive(dest/'plan.json',plan)
            write_json_exclusive(dest/'COMMITTED.json',dict(schema=PLAN,
                plan_id=plan['plan_id'],plan_file_sha256=file_sha256(dest/'plan.json'),
                semantic_sufficiency_certified=False,production_authorized=False))
        elif args.mode == 'run':
            frozen=check_seal(args.run_dir,args.expected_v1_seal_id)
            plan=strict_json(args.plan)
            validate_plan(plan)
            if (plan['panel_sha256']!=frozen['panel_id']
                or plan['model_sha256']!=frozen['model_snapshot_sha256']):
                raise ValueError('model/panel identity changed after external annotation')
            encoder,question,verify,ckpt,_,_=safe_encoder(args.snapshot)
            if ckpt!=plan['model_sha256']:
                raise ValueError('model revision differs from original frozen Reader')
            reader=load_conditioned_bank(Path(args.run_dir)/'conditioned.safetensors',frozen)
            result=run_blind(plan,encoder=encoder,question_encoder=question,
                reader=reader,weight_sha256=frozen['training']['conditioned']['weights_sha256'],
                reference_rows=_references(frozen))
            verify()
            write_json_exclusive(dest/'observations.json',result)
            write_json_exclusive(dest/'COMMITTED.json',dict(schema=result['schema'],
                observation_id=result['observation_id'],
                source_v1_seal=args.expected_v1_seal_id,
                observation_file_sha256=file_sha256(dest/'observations.json'),
                semantic_sufficiency_certified=False,production_authorized=False))
        else:
            plan=strict_json(args.plan)
            current=Path(args.observations_dir)
            commitment=strict_json(current/'COMMITTED.json')
            if (commitment.get('schema')!='hepta.reader.support-causal-observation.v1'
                or commitment.get('observation_id')!=args.expected_observation_id
                or file_sha256(current/'observations.json')!=commitment.get('observation_file_sha256')
                or (current/'FAILED.json').exists()
                or file_sha256(args.owner_labels)!=args.expected_owner_label_file_sha256):
                raise ValueError('immutable observation or label file identity mismatch')
            raw=strict_json(args.owner_labels)
            if (raw.get('schema')!='hepta.multirc.external-eval-labels.v1'
                or raw.get('panel_id')!=plan['panel_sha256']):
                raise ValueError('original Material owner labels required')
            label_receipt=dict(schema='hepta.reader.support-label-owner.v1',
                               plan_id=plan['plan_id'],labels=raw['labels'])
            scored=review(plan,strict_json(current/'observations.json'),label_receipt,
                expected_observation_id=args.expected_observation_id,
                expected_labels_sha256=digest(label_receipt))
            write_json_exclusive(dest/'scores.json',scored)
            write_json_exclusive(dest/'COMMITTED.json',dict(schema=scored['schema'],
                observation_id=args.expected_observation_id,
                score_file_sha256=file_sha256(dest/'scores.json'),
                production_authorized=False))
    except Exception as error:
        write_json_exclusive(dest/'FAILED.json',dict(
            schema='hepta.reader.support-causal-failure.v1',
            error_type=type(error).__name__,production_authorized=False))
        raise


if __name__=='__main__':
    main()
