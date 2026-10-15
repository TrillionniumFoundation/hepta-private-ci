"""Pinned MultiRC material -> label-blind two-question-per-passage panels.

Requires externally supplied genuine MultiRC train/validation columns. Labels are
never used to choose rows or retained in the blind evaluation input. The hash
of a pinned Hugging Face dataset revision is a material identity, not a license,
independent observation signature, or contamination exclusion.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from matrix_materials import file_sha256
from next_round_matrix import _digest

REVISION = '4e14482c58d790d467ecfb29b6790e1917bf8756'
REPO = 'aps/super_glue'
TRAIN_NAME = 'multirc/train-00000-of-00001.parquet'
VAL_NAME = 'multirc/validation-00000-of-00001.parquet'
OPTIONS = ('False', 'True')


def _typed_int(value):
    return type(value) is int and 0 <= value <= 10**9


def _string(value, maximum):
    return isinstance(value, str) and 1 <= len(value.encode('utf-8')) <= maximum


def _norm_text(value):
    return ' '.join(value.split()).casefold()


def _group_inputs(rows, split, *, max_passage_chars=900, return_stats=False):
    """Admit complete paragraphs without letting ANY answer/label select a row.

    A few genuine source records have empty/missing/oversized text. A malformed
    text record makes its entire paragraph INELIGIBLE, never just that answer.
    Well-formed source ID and 0/1-label constraints remain mandatory for ALL
    rows, including unselected paragraphs. No normalization/repaired text or
    label-based quality stopping is performed.
    """
    groups = {}
    excluded = set()
    distinct_passages = set()
    seen_candidates = set()
    invalid_fields = {'paragraph': 0, 'question': 0, 'answer': 0}
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100000:
        raise ValueError('bounded materialized MultiRC rows required')
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'paragraph', 'question', 'answer', 'label', 'idx'}:
            raise ValueError('complete actual MultiRC table schema required')
        idx = row['idx']
        if not isinstance(idx, dict) or set(idx) != {'paragraph', 'question', 'answer'} or not all(_typed_int(v) for v in idx.values()):
            raise ValueError('typed paragraph/question/answer identity required')
        # Labels are checked but are NEVER used for admission or sample choice.
        if type(row['label']) is not int or row['label'] not in (0, 1):
            raise ValueError('MultiRC label must be observed 0/1 in both input sources')
        pid = idx['paragraph']
        distinct_passages.add(pid)
        identity = (pid, idx['question'], idx['answer'])
        if identity in seen_candidates:
            raise ValueError('duplicate or contradictory question/answer identity')
        seen_candidates.add(identity)
        malformed = False
        for field, limit in (('paragraph', 65536), ('question', 8192), ('answer', 4096)):
            value = row[field]
            if value is not None and not isinstance(value, str):
                raise ValueError('untrusted MultiRC text field type')
            if isinstance(value, str) and len(value.encode('utf-8')) > 1048576:
                raise ValueError('unbounded untrusted MultiRC text field')
            if not _string(value, limit) or not value.strip():
                invalid_fields[field] += 1
                malformed = True
        if malformed:
            # Exclude the WHOLE passage, even if earlier rows were valid.
            excluded.add(pid)
        if pid in excluded:
            continue
        group=groups.setdefault(pid,dict(text=row['paragraph'],questions={}))
        if group['text']!=row['paragraph']:
            raise ValueError('one paragraph identity has conflicting evidence text')
        question=group['questions'].setdefault(idx['question'],dict(text=row['question'],answers={}))
        if question['text'] != row['question'] or idx['answer'] in question['answers']:
            raise ValueError('duplicate or contradictory question/answer identity')
        question['answers'][idx['answer']]=dict(text=row['answer'],label=row['label'])
    eligible=[]
    other_exclusions=dict(passage_too_long=0,too_few_questions=0,
                          incomplete_native_answer_slate=0)
    for pid,g in groups.items():
        if pid in excluded:
            continue
        if len(g['text'])>max_passage_chars:
            other_exclusions['passage_too_long']+=1
            continue
        if len(g['questions'])<2:
            other_exclusions['too_few_questions']+=1
            continue
        qids=sorted(g['questions'])[:2]
        # All future same-question original human alternatives must be
        # available. This is a fixed question/candidate-COUNT boundary and
        # does not consult a candidate's 0/1 label or its predicted score.
        if any(not 2<=len(g['questions'][q]['answers'])<=8 for q in qids):
            other_exclusions['incomplete_native_answer_slate']+=1
            continue
        items=[]
        for q in qids:
            question=g['questions'][q]
            answer_id=min(question['answers'])
            answer=question['answers'][answer_id]
            items.append((q,answer_id,question['text'],answer['text'],answer['label']))
        eligible.append((pid,g['text'],items))
    stats=dict(raw_rows=len(rows),raw_passages=len(distinct_passages),
               invalid_text_passages=len(excluded),
               invalid_text_fields=invalid_fields,
               excluded_by_predeclared_structure=other_exclusions,
               eligible_passages=len(eligible),
               eligible_distinct_texts=len({_norm_text(x[1]) for x in eligible}),
               admission='complete-valid-passage-and-native-slate-label-blind-v1')
    if (stats['raw_passages'] != stats['invalid_text_passages']
            + sum(other_exclusions.values()) + stats['eligible_passages']):
        raise ValueError('nonexhaustive source admission categories')
    return (eligible,stats) if return_stats else eligible


def prepare_panels(train_rows,val_rows,*,dataset_sha256_train,dataset_sha256_val,
                   seed=7347,train_passages=8,val_passages=4):
    """Choose stable source-disjoint passages; never select using answer labels.

    Output TRAIN includes labels, EVAL only input. Return labels to a separate
    caller to store privately; model APIs accept only the two blind structures.
    """
    for h in (dataset_sha256_train,dataset_sha256_val):
        if not isinstance(h,str) or len(h)!=64 or any(x not in '0123456789abcdef' for x in h):
            raise ValueError('pinned exact source SHA256 required')
    if (type(seed) is not int or seed<1 or type(train_passages) is not int
            or not 2<=train_passages<=64 or type(val_passages) is not int
            or not 2<=val_passages<=64):
        raise ValueError('bounded preregistered number of source passages required')
    a, train_admission = _group_inputs(train_rows, 'train', return_stats=True)
    b, val_admission = _group_inputs(val_rows, 'validation', return_stats=True)
    # Deny duplicate normalized evidence across train/dev, even if ID changed.
    ca={_norm_text(text) for _,text,_ in a}
    cb={_norm_text(text) for _,text,_ in b}
    if ca & cb:
        raise ValueError('source passage leaked across training and evaluation')
    def select(groups,n,split):
        # A paragraph can appear under two different source IDs. Only one
        # representative of any normalized content is eligible for inclusion;
        # otherwise duplicate data masquerades as independent source groups.
        # Selection stays label-blind and invariant to input row order.
        chosen=[]
        seen_texts=set()
        ordered=sorted(groups,key=lambda t:(hashlib.sha256(
            f'{seed}:{split}:{t[0]}:{_digest(t[1])}'.encode()).hexdigest(),t[0]))
        for item in ordered:
            norm=_norm_text(item[1])
            if norm not in seen_texts:
                chosen.append(item)
                seen_texts.add(norm)
            if len(chosen)==n:
                break
        return chosen
    ta=select(a,train_passages,'train')
    va=select(b,val_passages,'validation')
    if len(ta)!=train_passages or len(va)!=val_passages:
        raise ValueError('insufficient eligible distinct two-question passages after label-blind complete-passage admission')
    def materialize(chosen,split):
        output=[];labels={}
        for pid,text,items in chosen:
            doc_id=hashlib.sha256(f'{split}:passage:{pid}:{_digest(text)}'.encode()).hexdigest()[:32]
            questions=[]
            for qid,aid,q,answer,label in items:
                task_id=hashlib.sha256(f'{doc_id}:q{qid}:a{aid}'.encode()).hexdigest()[:32]
                entry=dict(task_id=task_id,question=q,answer=answer)
                if split=='train': entry['label']=label
                else:labels[task_id]=label
                questions.append(entry)
            output.append(dict(source_group=doc_id,evidence=text,questions=questions))
        return output,labels
    train,_=materialize(ta,'train')
    evaluation,labels=materialize(va,'validation')
    header=dict(schema='hepta.multirc.two-question-material.v1',revision=REVISION,repo=REPO,
        seed=seed,source_sha256_train=dataset_sha256_train,
        source_sha256_validation=dataset_sha256_val,
        train_passage_count=train_passages,eval_passage_count=val_passages,
        query_selection='first-two-ids-first-answer-per-question-no-label-choice',
        material_admission=dict(train=train_admission,validation=val_admission),
        training_data_license_approved=False,pretraining_contamination_ruled_out=False)
    train_bundle=dict(**header,split='train',rows=train)
    eval_bundle=dict(**header,split='validation',rows=evaluation)
    identity=_digest(dict(header=header,train=train,evaluation=evaluation))
    train_bundle['panel_id']=eval_bundle['panel_id']=identity
    # labels only returned to material owner, not embedded in model input.
    label_receipt=dict(schema='hepta.multirc.external-eval-labels.v1',panel_id=identity,
                       labels=labels,independent_observer_authenticated=False)
    validate_panel_bundles(train_bundle,eval_bundle)
    return train_bundle,eval_bundle,label_receipt


def validate_panel_bundles(train, evaluation):
    if (not isinstance(train,dict) or not isinstance(evaluation,dict)
            or set(train)!=set(evaluation) or train.get('split')!='train'
            or evaluation.get('split')!='validation'
            or train.get('schema')!='hepta.multirc.two-question-material.v1'):
        raise ValueError('complete typed split material required')
    for field in set(train)-{'rows','split'}:
        if train[field]!=evaluation[field]:
            raise ValueError('train/evaluation material identity mismatch')
    if (train.get('repo')!=REPO or train.get('revision')!=REVISION
            or train.get('training_data_license_approved') is not False
            or train.get('pretraining_contamination_ruled_out') is not False
            or train.get('query_selection')!='first-two-ids-first-answer-per-question-no-label-choice'):
        raise ValueError('benchmark provenance or research-only policy changed')
    admission=train.get('material_admission')
    if not isinstance(admission,dict) or set(admission)!={'train','validation'}:
        raise ValueError('complete admission source counts required')
    for split_name,expected_selected in (('train',train['train_passage_count']),
                                         ('validation',train['eval_passage_count'])):
        stats=admission.get(split_name)
        if (not isinstance(stats,dict) or set(stats)!={
                'raw_rows','raw_passages','invalid_text_passages',
                'invalid_text_fields','excluded_by_predeclared_structure',
                'eligible_passages','eligible_distinct_texts','admission'}
                or stats.get('admission')!='complete-valid-passage-and-native-slate-label-blind-v1'
                or any(type(stats[k]) is not int or stats[k]<0 for k in (
                    'raw_rows','raw_passages','invalid_text_passages','eligible_passages','eligible_distinct_texts'))
                or not expected_selected<=stats['eligible_distinct_texts']<=stats['eligible_passages']<=stats['raw_passages']<=stats['raw_rows']<=100000
                or stats['invalid_text_passages']>stats['raw_passages']
                or not isinstance(stats['excluded_by_predeclared_structure'],dict)
                or set(stats['excluded_by_predeclared_structure'])!={'passage_too_long','too_few_questions','incomplete_native_answer_slate'}
                or any(type(v) is not int or v<0 for v in stats['excluded_by_predeclared_structure'].values())
                or stats['raw_passages']!=stats['invalid_text_passages']+stats['eligible_passages']+sum(stats['excluded_by_predeclared_structure'].values())
                or not isinstance(stats['invalid_text_fields'],dict)
                or set(stats['invalid_text_fields'])!={'paragraph','question','answer'}
                or any(type(v) is not int or v<0 or v>stats['raw_rows']
                       for v in stats['invalid_text_fields'].values())):
            raise ValueError('invalid label-blind source admission receipt')
    groups,ids,texts=[set(),set()],[set(),set()],[set(),set()]
    for split,bundle in enumerate((train,evaluation)):
        rows=bundle['rows'];count=bundle['train_passage_count' if split==0 else 'eval_passage_count']
        if not isinstance(rows,list) or len(rows)!=count:
            raise ValueError('incomplete panel source count')
        for row in rows:
            if not isinstance(row,dict) or set(row)!={'source_group','evidence','questions'}:
                raise ValueError('invalid evidence row')
            if (not _string(row['source_group'],64) or row['source_group'] in groups[split]
                    or not _string(row['evidence'],65536) or len(row['evidence'])>900
                    or not isinstance(row['questions'],list) or len(row['questions'])!=2):
                raise ValueError('bad source identity or question denominator')
            norm=_norm_text(row['evidence'])
            if norm in texts[split]:
                raise ValueError('duplicate source evidence across passage IDs')
            groups[split].add(row['source_group']); texts[split].add(norm)
            for q in row['questions']:
                required={'task_id','question','answer'} | ({'label'} if split==0 else set())
                if not isinstance(q,dict) or set(q)!=required or not _string(q['task_id'],64) or q['task_id'] in ids[split]:
                    raise ValueError('missing/mixed evaluation labels or duplicate task')
                ids[split].add(q['task_id'])
                if not _string(q['question'],8192) or not _string(q['answer'],4096):
                    raise ValueError('invalid question or candidate answer')
                if split==0 and (type(q['label']) is not int or q['label'] not in (0,1)):
                    raise ValueError('invalid training label')
    if groups[0]&groups[1] or ids[0]&ids[1] or texts[0]&texts[1]:
        raise ValueError('training/evaluation source or task leakage')
    check=_digest(dict(header={k:train[k] for k in train if k not in ('rows','split','panel_id')},
                       train=train['rows'],evaluation=evaluation['rows']))
    if train['panel_id'] != check:
        raise ValueError('immutable panel material changed')
    return True


def load_parquet(path, *, expected_sha256):
    """No pickle, no remote code. PyArrow import is lazy for source-only CI."""
    if file_sha256(path)!=expected_sha256:
        raise ValueError('material bytes differ from externally pinned checksum')
    import pyarrow.parquet as pq
    table=pq.read_table(str(path),columns=['paragraph','question','answer','label','idx'])
    if table.num_rows>100000:
        raise ValueError('unbounded parquet sample count')
    return table.to_pylist()
