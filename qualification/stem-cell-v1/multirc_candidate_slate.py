"""Label-blind *complete genuine candidates* for the two pinned MultiRC questions.

Adds a separate post-training evidence test; V1's one-candidate-per-question
training study and its historical score are unchanged. The material owner has
validation labels; the Reader's input bundle does not. No fabricated cross-
question answer labels. This is not an official benchmark-wide score.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from matrix_materials import file_sha256, strict_json
from matrix_runtime import write_json_exclusive
from multirc_materials import (load_parquet, validate_panel_bundles,
                               _typed_int, _string, _norm_text, REVISION, REPO)
from next_round_matrix import _digest

SCHEMA = 'hepta.multirc.original-question-complete-candidates.v1'
LABEL_SCHEMA = 'hepta.multirc.candidate-slate-owner-labels.v1'
MAX_CANDIDATES_PER_QUESTION = 8


def prepare_candidate_slate(train, evaluation, source_rows, *, original_label_receipt):
    """Select *all* authentic answers of the two V1 questions, label blindly.

    The source has exact paragraph/question/answer IDs; chosen V1 candidates
    must reappear with the original task ID and unchanged human label. Unlike
    cross-question answer swapping, every expanded pair exists in the dataset.
    """
    validate_panel_bundles(train, evaluation)
    if (not isinstance(original_label_receipt, dict)
            or original_label_receipt.get('schema') != 'hepta.multirc.external-eval-labels.v1'
            or original_label_receipt.get('panel_id') != evaluation['panel_id']
            or not isinstance(original_label_receipt.get('labels'), dict)):
        raise ValueError('material owner must bind original external labels')
    original_ids = [q['task_id'] for row in evaluation['rows'] for q in row['questions']]
    if set(original_label_receipt['labels']) != set(original_ids):
        raise ValueError('original human label inventory incomplete')
    if (not isinstance(source_rows, list) or not 1 <= len(source_rows) <= 100000):
        raise ValueError('complete bounded validation source required')
    # Only exact original passages are retained; all candidates for their
    # registered questions must be found before anything is published.
    lookup = {row['evidence']: row for row in evaluation['rows']}
    if len(lookup) != len(evaluation['rows']):
        raise ValueError('duplicate registered passage content')
    paragraphs = {}
    for item in source_rows:
        if not isinstance(item, dict) or set(item) != {'paragraph','question','answer','label','idx'}:
            raise ValueError('full native source columns required')
        idx = item['idx']
        if (not isinstance(idx,dict) or set(idx) != {'paragraph','question','answer'}
                or not all(_typed_int(v) for v in idx.values())
                or type(item['label']) is not int or item['label'] not in (0,1)):
            raise ValueError('invalid source row label or candidate index')
        # Source-wide text anomalies cannot contaminate the registered panel;
        # only its exact pinned complete paragraphs need pass strict limits.
        # Original panel construction excluded all malformed passages.
        if not isinstance(item['paragraph'],str) or item['paragraph'] not in lookup:
            continue
        if any(not _string(item[k],limit) or not item[k].strip() for k,limit in
               (('paragraph',65536),('question',8192),('answer',4096))):
            raise ValueError('selected original MultiRC passage has invalid candidate text')
        key = idx['paragraph']
        paragraph = paragraphs.setdefault(key, {'text': item['paragraph'], 'questions': {}})
        if paragraph['text'] != item['paragraph']:
            raise ValueError('paragraph index changed evidence text')
        qid=idx['question'];aid=idx['answer']
        question=paragraph['questions'].setdefault(qid, {'text':item['question'],'answers':{}})
        if question['text']!=item['question'] or aid in question['answers']:
            raise ValueError('duplicate or conflicting actual candidate identity')
        question['answers'][aid]=(item['answer'],item['label'])
    selected={};selected_labels={}
    for pid,g in paragraphs.items():
        source_id=hashlib.sha256(f'validation:passage:{pid}:{_digest(g["text"])}'.encode()).hexdigest()[:32]
        if source_id not in {v['source_group'] for v in evaluation['rows']}:
            continue
        if source_id in selected:
            raise ValueError('original source ID collision')
        baseline=next(v for v in evaluation['rows'] if v['source_group']==source_id)
        question_ids=sorted(g['questions'])[:2]
        if len(question_ids)!=2:
            raise ValueError('registered source lost one of two questions')
        groups=[]
        for slot,qid in enumerate(question_ids):
            reference=baseline['questions'][slot]
            group=g['questions'][qid]
            if reference['question']!=group['text']:
                raise ValueError('registered question text changed')
            candidates=[]
            answer_ids=sorted(group['answers'])
            if not 2<=len(answer_ids)<=MAX_CANDIDATES_PER_QUESTION:
                raise ValueError('real question requires bounded complete candidate slate')
            for aid in answer_ids:
                answer,label=group['answers'][aid]
                task_id=hashlib.sha256(f'{source_id}:q{qid}:a{aid}'.encode()).hexdigest()[:32]
                if aid==answer_ids[0]:
                    if (task_id!=reference['task_id'] or answer!=reference['answer']
                            or label!=original_label_receipt['labels'][task_id]):
                        raise ValueError('original first candidate cannot be replayed')
                candidates.append(dict(task_id=task_id,answer=answer,candidate_id=aid))
                if task_id in selected_labels:
                    raise ValueError('candidate identity reused by different question')
                selected_labels[task_id]=label
            groups.append(dict(question_slot=slot,question=group['text'],
                               original_task_id=reference['task_id'],candidates=candidates))
        selected[source_id]=dict(source_group=source_id,evidence=g['text'],questions=groups)
    if set(selected)!={r['source_group'] for r in evaluation['rows']}:
        raise ValueError('source validation missing a complete registered passage')
    rows=[selected[r['source_group']] for r in evaluation['rows']]
    header=dict(schema=SCHEMA,source_panel_id=evaluation['panel_id'],repo=REPO,
                revision=REVISION,source_sha256_validation=evaluation['source_sha256_validation'],
                question_count_per_passage=2,max_candidates_per_question=MAX_CANDIDATES_PER_QUESTION,
                candidate_selection='all-native-answer-ids-no-label-choice',
                independent_source_authentication=False,production_material_license_approved=False)
    slate=dict(**header,rows=rows)
    slate['slate_id']=_digest(slate)
    labels=dict(schema=LABEL_SCHEMA,slate_id=slate['slate_id'],labels=selected_labels,
                original_panel_id=evaluation['panel_id'],external_observer_authenticated=False)
    validate_candidate_slate(train,evaluation,slate)
    return slate,labels


def validate_candidate_slate(train,evaluation,slate):
    """Reject missing/extra/reordered candidates and source/fingerprint drift."""
    validate_panel_bundles(train,evaluation)
    if (not isinstance(slate,dict) or slate.get('schema')!=SCHEMA
            or slate.get('slate_id')!=_digest({k:v for k,v in slate.items() if k!='slate_id'})
            or slate.get('source_panel_id')!=evaluation['panel_id']
            or slate.get('repo')!=REPO or slate.get('revision')!=REVISION
            or slate.get('source_sha256_validation')!=evaluation['source_sha256_validation']
            or slate.get('question_count_per_passage')!=2
            or slate.get('max_candidates_per_question')!=MAX_CANDIDATES_PER_QUESTION
            or slate.get('candidate_selection')!='all-native-answer-ids-no-label-choice'
            or slate.get('independent_source_authentication') is not False
            or slate.get('production_material_license_approved') is not False):
        raise ValueError('slate material or source identity changed')
    if not isinstance(slate.get('rows'),list) or len(slate['rows'])!=len(evaluation['rows']):
        raise ValueError('source slate denominator changed')
    all_tasks=set()
    for parent, row in zip(evaluation['rows'],slate['rows'],strict=True):
        if (not isinstance(row,dict) or set(row)!={'source_group','evidence','questions'}
                or row['source_group']!=parent['source_group'] or row['evidence']!=parent['evidence']
                or not isinstance(row['questions'],list) or len(row['questions'])!=2):
            raise ValueError('source passage/order changed')
        for slot, (pq,q) in enumerate(zip(parent['questions'],row['questions'],strict=True)):
            if (not isinstance(q,dict) or set(q)!={'question_slot','question','original_task_id','candidates'}
                    or q['question_slot']!=slot or q['question']!=pq['question']
                    or q['original_task_id']!=pq['task_id']
                    or not isinstance(q['candidates'],list)
                    or not 2<=len(q['candidates'])<=MAX_CANDIDATES_PER_QUESTION):
                raise ValueError('registered question or answer count changed')
            aids=[]
            for candidate in q['candidates']:
                if (not isinstance(candidate,dict)
                        or set(candidate)!={'task_id','answer','candidate_id'}
                        or not _string(candidate['task_id'],64) or not _string(candidate['answer'],4096)
                        or not _typed_int(candidate['candidate_id'])
                        or candidate['task_id'] in all_tasks):
                    raise ValueError('invalid, duplicate or unlabeled candidate identity')
                all_tasks.add(candidate['task_id'])
                aids.append(candidate['candidate_id'])
            if aids!=sorted(set(aids)) or q['candidates'][0]['task_id']!=pq['task_id'] \
                    or q['candidates'][0]['answer']!=pq['answer']:
                raise ValueError('candidate IDs, ordering or original first answer changed')
    return True


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('train-bundle','blind-eval-bundle','validation-parquet','validation-sha256',
                 'original-owner-labels','output'):
        p.add_argument('--'+name,required=True)
    args=p.parse_args()
    root=Path(args.output);root.mkdir(exist_ok=False)
    try:
        train=strict_json(args.train_bundle);eval_bundle=strict_json(args.blind_eval_bundle)
        if args.validation_sha256!=eval_bundle.get('source_sha256_validation'):
            raise ValueError('source parquet must match original locked validation file')
        raw=load_parquet(args.validation_parquet,expected_sha256=args.validation_sha256)
        original=strict_json(args.original_owner_labels)
        slate,labels=prepare_candidate_slate(train,eval_bundle,raw,original_label_receipt=original)
        write_json_exclusive(root/'blind-candidate-slate.json',slate)
        write_json_exclusive(root/'owner-only-candidate-labels.json',labels)
        write_json_exclusive(root/'COMMITTED.json',dict(schema='hepta.multirc.slate-material-owner.v1',
            slate_id=slate['slate_id'],source_panel_id=eval_bundle['panel_id'],
            blind_sha256=file_sha256(root/'blind-candidate-slate.json'),
            label_sha256=file_sha256(root/'owner-only-candidate-labels.json'),
            evaluation_labels_not_for_model=True,production_authorized=False))
    except Exception as exc:
        write_json_exclusive(root/'FAILED.json',dict(error_type=type(exc).__name__,
                                production_authorized=False))
        raise


if __name__=='__main__':main()
