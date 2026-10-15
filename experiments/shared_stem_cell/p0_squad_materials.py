#!/usr/bin/env python3
"""Prepare a small *real-source* answer-span intervention pilot, offline after acquisition.

This module never downloads data or chooses a candidate based on model performance.
Original human SQuAD answer spans supply the positive source fact. Negative views
are mechanical removals, NOT independent human negative-entailment judgments.
No prospective/future/independent semantic evidence is certified here.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import time

SCHEMA = 'hepta.p0.squad-span-reader.v1'
DATASET_REPO = 'rajpurkar/squad_v2'
DATASET_COMMIT = '3ffb306f725f7d2ce8394bc1873b24868140c412'
TRAIN_SHA = 'f6da32ffb482ff463ad056477740d1bb284b96a45db3a08bee6a225ca6abf291'
VALID_SHA = '0560174ab095c5ac0a8c8dc8da05f1625453c45a77e4ce9cabc6947ddfdd24cb'
WANTED = {'train': 24, 'calibration': 8, 'test': 12}
CONDITIONS = ('none', 'retrieved', 'sufficient', 'premise_removed')
RE_WORD = re.compile(r"[a-z0-9]+", re.I)
RE_SENTENCE = re.compile(r'[.!?](?:["\']|\))?\s+')


class Invalid(ValueError):
    pass


def canonical(data):
    return json.dumps(data, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def reject_duplicates(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise Invalid('duplicate JSON key')
        out[k] = v
    return out


def read(path, limit=8_000_000):
    b = Path(path).read_bytes()
    if not 2 < len(b) <= limit:
        raise Invalid('missing or oversized input')
    return json.loads(b, object_pairs_hook=reject_duplicates,
                      parse_constant=lambda _: (_ for _ in ()).throw(Invalid('nonfinite JSON')))


def write_new(path, obj):
    with Path(path).open('xb') as out:
        out.write(canonical(obj) + b'\n')


def words(text):
    return [w.lower() for w in RE_WORD.findall(text)]


def remove_answer_sentence(context, answer_start, answer):
    """Delete exactly the source sentence containing the *annotated* answer."""
    if type(context) is not str or type(answer) is not str or type(answer_start) is not int:
        raise Invalid('untyped annotated span')
    if not answer or answer_start < 0 or context[answer_start:answer_start+len(answer)] != answer:
        raise Invalid('answer bytes do not match original source')
    boundaries = [0] + [m.end() for m in RE_SENTENCE.finditer(context)] + [len(context)]
    for left, right in zip(boundaries, boundaries[1:]):
        if left <= answer_start and answer_start+len(answer) <= right:
            remainder = (context[:left] + ' ' + context[right:]).strip()
            if (not remainder or len(remainder) < 40 or
                    answer.casefold() in remainder.casefold() or remainder == context):
                raise Invalid('premise removal leaves the answer visible or empties context')
            return remainder, (left, right)
    raise Invalid('answer crosses sentence boundary')


def candidate(row):
    if type(row) is not dict or set(('id', 'title', 'context', 'question', 'answers')) - set(row):
        raise Invalid('source row lacks required annotated fields')
    if any(type(row[k]) is not str for k in ('id', 'title', 'context', 'question')):
        raise Invalid('nonstring source fields')
    title = row['title'].strip()
    context = row['context']  # SQuAD answer_start offsets are relative to these EXACT bytes
    question = row['question'].strip()
    if not title or not 100 <= len(context) <= 950 or not 8 <= len(question) <= 200:
        return None
    answers = row['answers']
    if type(answers) is not dict or set(answers) != {'text', 'answer_start'}:
        raise Invalid('unapproved answer schema')
    if type(answers['text']) is not list or type(answers['answer_start']) is not list:
        raise Invalid('bad original span lists')
    if not len(answers['text']) or len(answers['text']) != len(answers['answer_start']):
        return None  # genuine unanswerable SQuAD rows not treated as positive
    answer = answers['text'][0]
    start = answers['answer_start'][0]
    if (type(answer) is not str or not 4 <= len(answer) <= 80 or type(start) is not int or
            any(ch in answer + question for ch in ('"', '\n', '\r'))):
        return None
    try:
        removed, extent = remove_answer_sentence(context, start, answer)
    except Invalid:
        return None
    if (question.casefold() in context.casefold() or answer.casefold() in question.casefold()
            or not words(question)):
        return None
    original = {'source_id': row['id'], 'title': title,
                'context': context, 'question': question, 'answer': answer,
                'answer_start': start, 'removed': removed, 'span_range': list(extent),
                'group_id': digest(title.lower().encode()),
                'source_digest': digest(context.encode())}
    return original


def select(rows, count, *, forbidden_titles=frozenset()):
    """Fixed source-hash ranking, not label/quality/model-selected ordering."""
    by_title = defaultdict(list)
    for row in rows:
        item = candidate(row)
        if item is not None and item['title'].casefold() not in forbidden_titles:
            by_title[item['title'].casefold()].append(item)
    chosen = []
    for title in sorted(by_title, key=lambda name: digest(('hepta.p0.title:'+name).encode())):
        items = by_title[title]
        best = min(items, key=lambda o: digest(('hepta.p0.row:'+o['source_id']).encode()))
        chosen.append(best)
        if len(chosen) == count:
            break
    if len(chosen) != count:
        raise Invalid(f'insufficient independent source-title groups: {len(chosen)} != {count}')
    return chosen


def bm25_neighbors(items):
    """Question-only lexical retrieval. Never use source answer labels in query.

    The annotated answer is a training/evaluation target; reading it here would
    leak the target *before* the Reader sees evidence, invalidating the P0 arm.
    The source document remains eligible and every alternative must be measured.
    """
    if type(items) is not list or len(items) < 2:
        raise Invalid('retrieval requires at least two source candidates')
    if (any(type(x) is not dict or type(x.get('source_id')) is not str
            or type(x.get('context')) is not str or type(x.get('question')) is not str
            for x in items) or len({x['source_id'] for x in items}) != len(items)):
        raise Invalid('duplicate/malformed retrieval source corpus')
    docs = {x['source_id']: words(x['context']) for x in items}
    lengths = {k: len(v) for k, v in docs.items()}
    n = len(docs)
    avg = sum(lengths.values()) / n
    freq = {key: Counter(doc) for key, doc in docs.items()}
    df = Counter(w for doc in docs.values() for w in set(doc))
    result = {}
    for source in items:
        query = set(words(source['question']))
        if not query:
            raise Invalid('empty question-only retrieval query')
        ranked = []
        for key, counts in freq.items():
            score = 0.
            for token in query:
                occurrences = counts[token]
                if occurrences:
                    idf = math.log(1 + (n - df[token] + .5) / (df[token] + .5))
                    score += idf * occurrences * 2.2 / (occurrences + 1.2*(.25+.75*lengths[key]/avg))
            ranked.append((-score, key))
        ranked.sort()
        result[source['source_id']] = ranked[0][1]
    return result


def view(item, condition, retrieved):
    src = item['source_id']
    if condition == 'none':
        evidence, label = '(no evidence provided)', 0
    elif condition == 'sufficient':
        evidence, label = item['context'], 1
    elif condition == 'premise_removed':
        evidence, label = item['removed'], 0
    elif condition == 'retrieved':
        evidence = retrieved['context']
        # Only the original reviewed context owns this original human answer-span.
        # A different retrieved document is UNKNOWN, not a fabricated negative.
        label = 1 if retrieved['source_id'] == src else None
    else:
        raise Invalid('unregistered condition')
    prompt = ('Can the supplied passage explicitly support the proposed answer '
              f'"{item["answer"]}" to the question "{item["question"]}"?')
    joint = {'state': evidence, 'question': prompt,
             'options': ['not_supported', 'supported']}
    return {'case_id': digest(f'{src}:{condition}'.encode())[:24],
            'source_id': src, 'group_id': item['group_id'],
            'condition': condition, 'joint_input': joint,
            'view_sha256': digest(canonical(joint)),
            'evidence_sha256': digest(evidence.encode()),
            'retrieved_source_id': retrieved['source_id'] if condition == 'retrieved' else None,
            'annotated_answer_source_sha256': item['source_digest'],
            'label': label}


def build(train_rows, validation_rows):
    train_sources = select(train_rows, WANTED['train'] + WANTED['calibration'])
    train_sources_map = {x['title'].casefold() for x in train_sources}
    test_sources = select(validation_rows, WANTED['test'], forbidden_titles=train_sources_map)
    groups = {'train': train_sources[:WANTED['train']],
              'calibration': train_sources[WANTED['train']:], 'test': test_sources}
    if len({o['group_id'] for chunk in groups.values() for o in chunk}) != sum(WANTED.values()):
        raise Invalid('title-source leakage')
    flat = []
    for split, sources in groups.items():
        neighbors = bm25_neighbors(sources)
        by_id = {x['source_id']: x for x in sources}
        for item in sources:
            for condition in CONDITIONS:
                row = view(item, condition, by_id[neighbors[item['source_id']]])
                row['split'] = split
                flat.append(row)
    identifiers = [r['case_id'] for r in flat]
    if len(set(identifiers)) != len(identifiers):
        raise Invalid('repeated question/condition ids')
    blind_keys = ('case_id', 'source_id', 'group_id', 'condition', 'joint_input',
                  'view_sha256', 'evidence_sha256', 'retrieved_source_id',
                  'annotated_answer_source_sha256', 'split')
    fit = [{k: r[k] for k in blind_keys} | {'label': r['label']}
           for r in flat if r['split'] != 'test']
    unseen = [{k: r[k] for k in blind_keys} for r in flat if r['split'] == 'test']
    outcome = [{k: r[k] for k in ('case_id', 'source_id', 'group_id', 'condition',
                                  'view_sha256', 'label')} for r in flat if r['split'] == 'test']
    # No future period can be inferred from SQuAD train/validation splits.
    meta = {'schema': SCHEMA, 'dataset_repo': DATASET_REPO,
            'dataset_commit': DATASET_COMMIT, 'train_original_sha256': TRAIN_SHA,
            'validation_original_sha256': VALID_SHA, 'sample_rule': 'sha256-title-rank:answer-not-in-question:v2',
            'retriever': 'bm25:k1=1.2:b=0.75:question-only:within-partition:v2',
            'question_groups_by_split': WANTED, 'future_chronology_verified': False,
            'human_annotated_answer_spans': True,
            'negative_premise_removal_independently_reviewed': False,
            'all_four_reader_conditions_independently_semantic_scored': False,
            'production_promotion_permitted': False, 'authority': 'DENY_ALL'}
    return ({'metadata': meta, 'cases': fit},
            {'metadata': meta, 'cases': unseen},
            {'metadata': meta, 'cases': outcome})


def from_parquet(path, expected_sha):
    file = Path(path)
    if digest(file.read_bytes()) != expected_sha:
        raise Invalid('original public parquet bytes changed')
    import pyarrow.parquet as pq  # deliberately only needed for physical source build
    return pq.read_table(file).to_pylist()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--train-parquet', type=Path, required=True)
    ap.add_argument('--validation-parquet', type=Path, required=True)
    ap.add_argument('--output-directory', type=Path, required=True)
    args = ap.parse_args()
    start = time.perf_counter()
    train = from_parquet(args.train_parquet, TRAIN_SHA)
    test = from_parquet(args.validation_parquet, VALID_SHA)
    fit, blind, labels = build(train, test)
    args.output_directory.mkdir(parents=True, exist_ok=True)
    for name, doc in (('fit.json', fit), ('blind.json', blind), ('labels.json', labels)):
        write_new(args.output_directory/name, doc)
    print(json.dumps({'source_pass': True, 'fit_cases': len(fit['cases']),
                      'blind_cases': len(blind['cases']), 'elapsed_s': time.perf_counter()-start,
                      'fit_sha256': digest(canonical(fit)),
                      'blind_sha256': digest(canonical(blind)),
                      'labels_sha256': digest(canonical(labels)),
                      'labels_for_model_excluded': True,
                      'production_promotion_permitted': False}, sort_keys=True))


if __name__ == '__main__':
    main()
