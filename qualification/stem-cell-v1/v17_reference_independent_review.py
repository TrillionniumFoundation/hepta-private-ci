"""Source-first, model-free reviewer for V17 reference and V16 candidate.

A tokenizer replay and label-separated weak-string scorer are not independent
semantic entailment or attestation that a host executed the neural model.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from v17_reference_reader_physical import (
    SCHEMA, ARMS, GROUPS, ROOTS, OUT_CAP, digest, digest_text,
    expected_plan, encode, read, verify_model_files, write_private,
)


def starts_read(path):
    p = Path(path)
    if not p.is_file() or p.is_symlink() or not 0 < p.stat().st_size <= 128 * 800:
        raise ValueError('invalid original reference start journal')
    def dup(items):
        row = {}
        for k, v in items:
            if k in row:
                raise ValueError('duplicate journal field')
            row[k] = v
        return row
    def bad(_):
        raise ValueError('nonfinite journal token')
    return [json.loads(line, object_pairs_hook=dup, parse_constant=bad)
            for line in p.read_text().splitlines()]


def audit_reference(plan, spec, receipt, starts, tokenizer):
    requests = expected_plan(plan)
    expected = {'schema', 'plan_sha256', 'model_spec_sha256', 'model_name',
                'reference_request_count', 'raw_answers', 'execution_cpu_seconds',
                'execution_wall_seconds', 'candidate_original_reader_rerun',
                'reference_model_forward_attested_independently',
                'independent_human_evidence_sufficiency', 'semantic_accuracy',
                'production_authorized', 'status'}
    if (type(receipt) is not dict or set(receipt) != expected
        or receipt['schema'] != SCHEMA + '.sealed-model-output'
        or receipt['plan_sha256'] != digest(plan)
        or receipt['model_spec_sha256'] != digest(spec)
        or receipt['model_name'] != spec['repo_id']
        or receipt['reference_request_count'] != 128
        or receipt['candidate_original_reader_rerun'] is not False
        or receipt['reference_model_forward_attested_independently'] is not False
        or receipt['independent_human_evidence_sufficiency'] is not False
        or receipt['semantic_accuracy'] is not None
        or receipt['production_authorized'] is not False
        or receipt['status'] != 'PHYSICAL_PRODUCER_ONLY_NO_GO'):
        raise ValueError('unverified reference model promotion/receipt')
    for k in ('execution_cpu_seconds', 'execution_wall_seconds'):
        if type(receipt[k]) not in (int, float) or not 0 <= receipt[k] < 86_400:
            raise ValueError('invalid measured reference cost')
    answers = receipt['raw_answers']
    if type(answers) is not dict or set(answers) != set(requests):
        raise ValueError('missing/extra reference answers')
    if type(starts) is not list or len(starts) != 128:
        raise ValueError('missing actual reference start records')
    seen = set()
    for start in starts:
        if (type(start) is not dict or set(start) != {'request_id', 'plan_sha256',
              'model_spec_sha256', 'input_ids_sha256', 'input_tokens'}):
            raise ValueError('invalid fsynced start fields')
        rid = start['request_id']
        if (rid not in requests or rid in seen or start['plan_sha256'] != digest(plan)
            or start['model_spec_sha256'] != digest(spec)):
            raise ValueError('double/missing/cross-model actual start')
        seen.add(rid)
        row = requests[rid]
        ids = encode(tokenizer, row)
        if start['input_ids_sha256'] != digest(ids) or start['input_tokens'] != len(ids):
            raise ValueError('original prompt rendered/tokenized differently')
        answer = answers[rid]
        if (type(answer) is not dict or set(answer) != {'case_id', 'family', 'arm',
            'source_ids', 'answer_text', 'answer_sha256', 'output_ids',
            'input_ids_sha256', 'input_tokens', 'output_tokens', 'cpu_seconds'}):
            raise ValueError('invented original model answer metadata')
        ids_out = answer['output_ids']
        if (type(ids_out) is not list or not 1 <= len(ids_out) <= OUT_CAP
            or any(type(i) is not int or i < 0 or i >= tokenizer.vocab_size for i in ids_out)
            or (answer['case_id'], answer['family'], answer['arm'])
                != (row['case_id'], row['family'], row['arm'])
            or answer['source_ids'] != row['source_ids']
            or answer['input_ids_sha256'] != digest(ids)
            or answer['input_tokens'] != len(ids)
            or answer['output_tokens'] != len(ids_out)
            or type(answer['answer_text']) is not str
            or answer['answer_sha256'] != digest_text(answer['answer_text'])
            or answer['answer_text'] != tokenizer.decode(ids_out, skip_special_tokens=True)
            or type(answer['cpu_seconds']) not in (int, float)
            or not 0 <= answer['cpu_seconds'] < 3600):
            raise ValueError('model source/token/answer/cost drift')
    if seen != set(requests):
        raise ValueError('unsealed partial reference reader output')
    return {'schema': SCHEMA + '.independent-byte-review',
            'plan_sha256': digest(plan), 'reference_model_spec_sha256': digest(spec),
            'reference_answer_receipt_sha256': digest(receipt),
            'verified_reference_requests': 128,
            'verified_reference_output_tokens': sum(x['output_tokens'] for x in answers.values()),
            'verified_reference_input_tokens': sum(x['input_tokens'] for x in answers.values()),
            'source_root_count': 4, 'sufficient_evidence_human_verified': False,
            'reference_model_forward_attested_independently': False,
            'independent_semantic_accuracy': None, 'production_authorized': False,
            'decision': 'RECEIPT_BYTES_ONLY_HOLD_NO_GO'}


def weak_gold_compare(plan, original_answers, reference_answers, original_source):
    # Called only after both model outputs are sealed, in a separately isolated job.
    rows = expected_plan(plan)
    if type(original_source) is not list or len(original_source) != 10:
        raise ValueError('wrong original private publisher gold')
    source_by = {s['sample_id']: s for s in original_source}
    if len(source_by) != 10 or not set(ROOTS).issubset(source_by):
        raise ValueError('duplicated publisher source root')
    if set(original_answers) != set(rows) or set(reference_answers) != set(rows):
        raise ValueError('incomplete Reader pair before unsealing gold')
    tallies = {group: {arm: {'cases': 0, 'publisher_answer_known': 0,
                             'publisher_answer_unknown': 0,
                             'candidate_substring': 0,
                             'reference_substring': 0, 'candidate_exact': 0,
                             'reference_exact': 0} for arm in ARMS} for group in GROUPS}
    for case in plan['cases']:
        fam, group = case['family'], case['cohort']
        index = int(case['id'].split('/q')[-1])
        qa = source_by[fam]['qa']
        if not 0 <= index < len(qa):
            raise ValueError('publisher question index changed')
        item = qa[index]
        if type(item) is not dict:
            raise ValueError('malformed publisher QA record')
        target = item.get('answer')
        if target is not None and type(target) is not str:
            raise ValueError('malformed publisher answer type')
        known = type(target) is str and bool(target.strip())
        needle = target.strip().casefold() if known else None
        for arm in ARMS:
            rid = case['arms'][arm]['request_id']
            c = original_answers[rid]['answer_text'].strip().casefold()
            r = reference_answers[rid]['answer_text'].strip().casefold()
            t = tallies[group][arm]
            t['cases'] += 1
            if not known:
                # An absent publisher label is not evidence that either model
                # answered incorrectly. It is censored for both matched arms.
                t['publisher_answer_unknown'] += 1
                continue
            t['publisher_answer_known'] += 1
            t['candidate_substring'] += int(needle in c)
            t['reference_substring'] += int(needle in r)
            t['candidate_exact'] += int(c == needle)
            t['reference_exact'] += int(r == needle)
    if any((t['cases'] != 16 or
            t['publisher_answer_known'] + t['publisher_answer_unknown'] != 16)
           for group in GROUPS for t in tallies[group].values()):
        raise ValueError('incomplete or incorrectly censored historical cohort')
    return {'schema': SCHEMA + '.postseal-weak-literal-comparison',
            'plan_sha256': digest(plan), 'original_historical_roots': 4,
            'per_cohort_arm': tallies,
            'answer_dependent_historical_selection': True,
            'literal_string_match_not_semantic_correctness': True,
            'human_reviewed_evidence_sufficiency': False,
            'independent_grounded_task_success': None,
            'matched_model_lifecycle_costs': False,
            'future_time_holdout_windows': 0,
            'stem_winner_selected': False, 'production_authorized': False,
            'decision': 'HOLD_NO_GO'}


def cli():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', required=True)
    ap.add_argument('--source', required=True)
    ap.add_argument('--bm25', required=True)
    ap.add_argument('--model-dir', required=True)
    ap.add_argument('--model-spec', required=True)
    ap.add_argument('--answers', required=True)
    ap.add_argument('--starts', required=True)
    ap.add_argument('--candidate', required=True)
    ap.add_argument('--review-output', required=True)
    ap.add_argument('--original-gold')
    ap.add_argument('--gold-output')
    a = ap.parse_args()
    from transformers import AutoTokenizer
    from v16_literal_witness_reader import validate, verify_answers
    plan, source, ranks = read(a.plan), read(a.source), read(a.bm25)
    spec, answers, candidate = read(a.model_spec), read(a.answers), read(a.candidate)
    validate(plan, source, ranks)
    verify_answers(plan, source, ranks, candidate)
    verify_model_files(a.model_dir, spec)
    tokenizer = AutoTokenizer.from_pretrained(a.model_dir, local_files_only=True,
                                               trust_remote_code=False, use_fast=True)
    if (a.original_gold is None) != (a.gold_output is None):
        raise ValueError('gold input and output must be requested together')
    report = audit_reference(plan, spec, answers, starts_read(a.starts), tokenizer)
    write_private(a.review_output, report)
    if a.original_gold:
        from v16_literal_witness_reader import construct
        original = read(a.original_gold)
        if construct(source, ranks, original) != plan:
            raise ValueError('after-seal source/gold/cohort drift')
        result = weak_gold_compare(plan, candidate['raw_answers'], answers['raw_answers'], original)
        write_private(a.gold_output, result)
    print(json.dumps({'decision': report['decision'],
                      'verified_reference_requests': report['verified_reference_requests']}))


if __name__ == '__main__':
    cli()
