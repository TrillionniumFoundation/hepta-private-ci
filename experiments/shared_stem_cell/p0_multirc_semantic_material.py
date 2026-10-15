#!/usr/bin/env python3
"""Create label-blind authentic MultiRC candidate-answer trials, research only.

No synthetic counterfactual gets the original human label. Candidate and passage
selection is strictly label-independent and linked to original pinned source.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import re

SCHEMA = 'hepta.p0.multirc-human-semantic.v1'
REPO = 'aps/super_glue'
REVISION = '4e14482c58d790d467ecfb29b6790e1917bf8756'
TRAIN = 'multirc/train-00000-of-00001.parquet'
VALID = 'multirc/validation-00000-of-00001.parquet'
COUNTS = {'train': 12, 'calibration': 4, 'test': 8}
MAX_ANSWERS = 4
MAX_SOURCE_ROWS = 100000
PROTOCOL = 'sha256-passage-first-two-questions-all-first-four-answer-ids:blind:v1'
CONDITIONS = ('original', 'no_evidence')
WORD = re.compile(r'[a-z0-9]+', re.I)

class Invalid(ValueError):
    pass


def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_pairs(pairs):
    output = {}
    for k, v in pairs:
        if k in output:
            raise Invalid('duplicate JSON object key')
        output[k] = v
    return output


def read(path, limit=16_000_000):
    b = Path(path).read_bytes()
    if not 2 < len(b) < limit:
        raise Invalid('missing or oversized material')
    return json.loads(b, object_pairs_hook=strict_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(Invalid('invalid constant')))


def save(path, data):
    with Path(path).open('xb') as h:
        h.write(canonical(data) + b'\n')


def checked_source_hash(h):
    if type(h) is not str or len(h) != 64 or any(c not in '0123456789abcdef' for c in h):
        raise Invalid('invalid original dataset SHA')
    return h


def normalized(x):
    return ' '.join(x.split()).casefold()


def tokens(x):
    return tuple(WORD.findall(x.casefold()))


def candidates(rows):
    if type(rows) is not list or not 1 <= len(rows) <= MAX_SOURCE_ROWS:
        raise Invalid('bounded original parquet rows required')
    groups = {}
    for r in rows:
        if type(r) is not dict or set(r) != {'paragraph', 'question', 'answer', 'label', 'idx'}:
            raise Invalid('unexpected MultiRC source columns')
        idx = r['idx']
        if (type(idx) is not dict or set(idx) != {'paragraph', 'question', 'answer'} or
                any(type(idx[k]) is not int or not 0 <= idx[k] <= 1_000_000_000 for k in idx)):
            raise Invalid('malformed authentic paragraph/question/answer IDs')
        if (any(type(r[k]) is not str for k in ('paragraph', 'question', 'answer')) or
                type(r['label']) is not int or r['label'] not in (0, 1)):
            raise Invalid('untyped authentic labels or source text')
        # An original full-Parquet source can contain short/blank rows that
        # will NEVER qualify for the smaller semantic panel below (passage
        # 100..950, question 10..240, answer 1..130). Refusing the entire
        # immutable file over an off-panel short row is not an eligibility
        # requirement. Retain the row for deterministic grouping; keep strict
        # upper bounds and reject malformed labels/IDs/source conflicts.
        if (len(r['paragraph']) > 65536 or
                len(r['question']) > 8192 or
                len(r['answer']) > 4096):
            raise Invalid('oversized original raw source cell')
        p = groups.setdefault(idx['paragraph'], {'paragraph': r['paragraph'], 'questions': {}})
        if p['paragraph'] != r['paragraph']:
            raise Invalid('one paragraph ID maps to different source bytes')
        q = p['questions'].setdefault(idx['question'], {'question': r['question'], 'answers': {}})
        if q['question'] != r['question'] or idx['answer'] in q['answers']:
            raise Invalid('duplicate or conflicting candidate material')
        q['answers'][idx['answer']] = (r['answer'], r['label'])
    eligible = []
    for pid, passage in groups.items():
        if not 100 <= len(passage['paragraph']) <= 950:
            continue
        qs = []
        for qid, q in sorted(passage['questions'].items()):
            if not 10 <= len(q['question']) <= 240 or len(q['answers']) < 2:
                continue
            ordered = sorted(q['answers'].items())
            if len(ordered) > MAX_ANSWERS:
                ordered = ordered[:MAX_ANSWERS]
            answers = []
            seen = set()
            for aid, (answer, label) in ordered:
                if not 1 <= len(answer) <= 130 or normalized(answer) in seen:
                    break
                seen.add(normalized(answer))
                answers.append({'id': aid, 'text': answer, 'label': label})
            if len(answers) == len(ordered) and len(answers) >= 2:
                qs.append({'id': qid, 'text': q['question'], 'answers': answers})
            if len(qs) == 2:
                break
        if len(qs) == 2:
            eligible.append({'pid': pid, 'text': passage['paragraph'], 'questions': qs})
    return eligible


def selected(source, n, split, *, exclude=()):
    # All eligibility and ordering are computed from text/IDs WITHOUT labels.
    banned = set(exclude)
    chosen = []
    for p in sorted(source, key=lambda r: (sha(f'{PROTOCOL}:{split}:{r["pid"]}:{sha(r["text"].encode())}'.encode()), r['pid'])):
        key = normalized(p['text'])
        if key not in banned:
            chosen.append(p)
            banned.add(key)
        if len(chosen) == n:
            break
    if len(chosen) != n:
        raise Invalid(f'insufficient source-disjoint passages: {split} {len(chosen)}/{n}')
    return chosen


def make_row(split, p, q, a, condition):
    original = condition == 'original'
    evidence = p['text'] if original else '(no passage evidence available)'
    # Candidate is part of the QUESTION, not looked up by the retriever; this
    # task tests label-annotated relations, not generation of a missing answer.
    question = ('Is the proposed answer supported by the original passage? '
                'Question: ' + json.dumps(q['text'], ensure_ascii=False) +
                ' Candidate answer: ' + json.dumps(a['text'], ensure_ascii=False))
    source_id = sha(p['text'].encode())
    base = f'{split}:{p["pid"]}:{q["id"]}:{a["id"]}:{source_id}'
    case_id = sha(f'{PROTOCOL}:{base}:{condition}'.encode())[:32]
    visible = {'state': evidence, 'question': question,
               'options': ['not_supported', 'supported']}
    return {'case_id': case_id, 'source_id': source_id,
            'source_group': sha(normalized(p['text']).encode()), 'split': split,
            'question_id': sha(f'{source_id}:{q["id"]}'.encode())[:32],
            'answer_id': sha(f'{base}:answer'.encode())[:32],
            'condition': condition,
            'candidate_text': a['text'], 'original_question_text': q['text'],
            'joint_input': visible, 'view_sha256': sha(canonical(visible))}


def build(train_rows, validation_rows, *, train_sha, validation_sha):
    checked_source_hash(train_sha); checked_source_hash(validation_sha)
    train = candidates(train_rows)
    validation = candidates(validation_rows)
    first = selected(train, COUNTS['train'], 'train')
    calibrate = selected(validation, COUNTS['calibration'], 'calibration')
    test = selected(validation, COUNTS['test'], 'test',
                    exclude=[normalized(p['text']) for p in calibrate])
    norm_train = {normalized(p['text']) for p in first}
    if norm_train & {normalized(p['text']) for p in calibrate + test}:
        raise Invalid('source reused across train/calibration/test')
    doc = {'train': first, 'calibration': calibrate, 'test': test}
    fit, blind, labels = [], [], {}
    for split, chosen in doc.items():
        for p in chosen:
            for q in p['questions']:
                for a in q['answers']:
                    for condition in CONDITIONS:
                        row = make_row(split, p, q, a, condition)
                        if split == 'test':
                            blind.append(row)
                            if condition == 'original':
                                labels[row['case_id']] = a['label']
                        else:
                            if condition == 'original':
                                row['label'] = a['label']
                            else:
                                row['label'] = None  # not human-labeled counterfactual
                            fit.append(row)
    if len({x['case_id'] for x in fit+blind}) != len(fit)+len(blind):
        raise Invalid('colliding original candidate IDs')
    base = {'schema': SCHEMA, 'repo': REPO, 'revision': REVISION, 'train_sha256': train_sha,
            'validation_sha256': validation_sha, 'selection_rule': PROTOCOL,
            'source_passages_by_split': COUNTS,
            'training_license_independently_approved': False,
            'contamination_ruled_out': False, 'temporal_future_windows_verified': False,
            'authority': 'DENY_ALL', 'production_promotion_permitted': False}
    panel_id = sha(canonical({'base': base, 'fit': fit, 'blind': blind}))
    meta = dict(base, panel_id=panel_id)
    outfit, outblind = {'metadata': meta, 'cases': fit}, {'metadata': meta, 'cases': blind}
    owner = {'schema': 'hepta.p0.multirc-original-human-labels.v1', 'panel_id': panel_id,
             'original_human_candidate_labels': labels,
             'generated_intervention_labels_invented': False,
             'source_signature_independently_verified': False, 'authority': 'DENY_ALL'}
    # Validator operates without access to held labels.
    validate(outfit, outblind)
    return outfit, outblind, owner


def validate(fit, blind):
    if type(fit) is not dict or type(blind) is not dict or set(fit) != {'metadata','cases'} or set(blind) != {'metadata','cases'}:
        raise Invalid('invalid split schema')
    meta = fit['metadata']
    if meta != blind['metadata'] or type(meta) is not dict or meta.get('schema') != SCHEMA:
        raise Invalid('not the same exact model/evaluation source')
    for k,v in [('repo', REPO), ('revision',REVISION), ('selection_rule',PROTOCOL),
                ('source_passages_by_split', COUNTS), ('authority','DENY_ALL'),
                ('production_promotion_permitted',False), ('temporal_future_windows_verified',False),
                ('training_license_independently_approved',False), ('contamination_ruled_out',False)]:
        if meta.get(k) != v:
            raise Invalid('research identity/authority drift')
    checked_source_hash(meta.get('train_sha256'));checked_source_hash(meta.get('validation_sha256'))
    if any(type(d.get('cases')) is not list for d in (fit,blind)):
        raise Invalid('missing cases')
    seen=set();source_by_split=defaultdict(set);shapes=defaultdict(lambda: defaultdict(set))
    for doc in (fit,blind):
        for row in doc['cases']:
            isblind = doc is blind
            allowed={'case_id','source_id','source_group','split','question_id',
                     'answer_id','condition','candidate_text','original_question_text',
                     'joint_input','view_sha256'}
            if type(row) is not dict or set(row) != (allowed if isblind else allowed|{'label'}):
                raise Invalid('missing/unexpected model fields')
            if row['case_id'] in seen or type(row['case_id']) is not str or len(row['case_id']) != 32:
                raise Invalid('duplicate/noncanonical case')
            seen.add(row['case_id'])
            if row['split'] not in COUNTS or (row['split'] == 'test') != isblind or row['condition'] not in CONDITIONS:
                raise Invalid('wrong split/condition')
            if (type(row['joint_input']) is not dict or
                    row['joint_input'].get('options') != ['not_supported','supported'] or
                    type(row['joint_input'].get('state')) is not str or
                    type(row['joint_input'].get('question')) is not str or
                    sha(canonical(row['joint_input'])) != row['view_sha256']):
                raise Invalid('tampered model input')
            if row['condition']=='no_evidence' and (row['joint_input']['state']!='(no passage evidence available)' or
                     row.get('label','absent') not in (None, 'absent')):
                raise Invalid('no-evidence acquired an invented truth label')
            if row['condition']=='original' and (len(row['joint_input']['state'])<100 or
                    (not isblind and type(row['label']) is not int)):
                raise Invalid('original positive/negative label invalid')
            if (type(row['source_id']) is not str or len(row['source_id'])!=64 or
                    type(row['source_group']) is not str or len(row['source_group'])!=64 or
                    row['source_id'] != sha(row['joint_input']['state'].encode()) and row['condition']=='original'):
                raise Invalid('original passage/source identity drift')
            if row['condition']=='original':
                source_by_split[row['split']].add(row['source_group'])
            link=(row['split'],row['question_id'],row['answer_id'])
            if row['condition'] in shapes[link][row['source_group']]:
                raise Invalid('duplicate question/answer/condition pair')
            shapes[link][row['source_group']].add(row['condition'])
    # Verify complete exact task identity across BOTH interventions. An attacker
    # must not rewrite an unscored control's question/answer while keeping the
    # IDs and re-signing self-reported content hashes.
    by_task=defaultdict(dict)
    for row in fit['cases']+blind['cases']:
        key=(row['split'],row['source_group'],row['question_id'],row['answer_id'])
        by_task[key][row['condition']]=row
        if row['condition']=='original':
            if row['source_group']!=sha(normalized(row['joint_input']['state']).encode()):
                raise Invalid('wrong normalized original passage group')
        expected_prompt=('Is the proposed answer supported by the original passage? '
                         'Question: ' + json.dumps(row['original_question_text'],ensure_ascii=False) +
                         ' Candidate answer: ' + json.dumps(row['candidate_text'],ensure_ascii=False))
        if row['joint_input']['question']!=expected_prompt:
            raise Invalid('changed candidate and question framing')
    for link, groups in shapes.items():
        if len(groups)!=1 or next(iter(groups.values())) != set(CONDITIONS):
            raise Invalid('incomplete unchanged task under no-evidence control')
    for pair in by_task.values():
        if set(pair)!=set(CONDITIONS):
            raise Invalid('missing pair member')
        orig,absent=pair['original'],pair['no_evidence']
        for k in ('source_id','source_group','split','question_id','answer_id',
                  'candidate_text','original_question_text'):
            if orig[k]!=absent[k]:
                raise Invalid('no-evidence intervention changed task identity')
        if orig['joint_input']['question']!=absent['joint_input']['question']:
            raise Invalid('no-evidence intervention changed original question')
    if any(len(source_by_split[s])!=COUNTS[s] for s in COUNTS):
        raise Invalid('missing source group census')
    if any(source_by_split[a] & source_by_split[b] for a in COUNTS for b in COUNTS if a!=b):
        raise Invalid('source leakage across splits')
    if meta.get('panel_id') != sha(canonical({'base': {k:v for k,v in meta.items() if k!='panel_id'},
                                               'fit':fit['cases'],'blind':blind['cases']})):
        raise Invalid('self-inconsistent panel identity')
    return fit['cases'],blind['cases']


def original_rows(path,expected_sha):
    checked_source_hash(expected_sha)
    if sha(Path(path).read_bytes()) != expected_sha:
        raise Invalid('wrong original parquet bytes')
    import pyarrow.parquet as pq
    t = pq.read_table(str(path), columns=['paragraph','question','answer','idx','label'])
    if t.num_rows > MAX_SOURCE_ROWS:
        raise Invalid('oversized original dataset')
    return t.to_pylist()


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--train-parquet',type=Path,required=True)
    p.add_argument('--validation-parquet',type=Path,required=True)
    p.add_argument('--train-sha256',required=True)
    p.add_argument('--validation-sha256',required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    fit,blind,owner=build(original_rows(a.train_parquet,a.train_sha256),
                          original_rows(a.validation_parquet,a.validation_sha256),
                          train_sha=a.train_sha256,validation_sha=a.validation_sha256)
    save(a.output/'fit.json',fit)
    save(a.output/'blind.json',blind)
    save(a.output/'owner-only-human-labels.json',owner)
    print(json.dumps({'schema':SCHEMA,'panel_id':fit['metadata']['panel_id'],
                      'test_candidate_observations':len(blind)//2,
                      'test_passage_groups':COUNTS['test'], 'true_human_negative_labels_in_owner':True,
                      'model_sees_evaluation_labels':False,'authority':'DENY_ALL'},sort_keys=True))

if __name__=='__main__':main()
