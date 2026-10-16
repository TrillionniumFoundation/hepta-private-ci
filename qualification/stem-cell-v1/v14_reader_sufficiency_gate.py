"""V14 four-evidence-state Reader sufficiency audit, research-only.

Consumes original externally generated, source-bound answers and later independent
adjudication. This module NEVER runs a model, authenticates an evaluator, issues
FinalUse, selects a Stem, or treats its fixtures as task evidence.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re

SCHEMA = 'hepta.stem.v14.reader-sufficiency.v1'
ARMS = ('none', 'retrieved', 'sufficient', 'lesion')
READERS = ('candidate', 'reference')
HASH = re.compile(r'^[0-9a-f]{64}$')
MAX_CASES = 4096
MAX_JSON_BYTES = 16 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def exact(obj, keys, label):
    require(type(obj) is dict and set(obj) == set(keys), label + ' shape')


def sha_obj(obj):
    return sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def hex_sha(value):
    return type(value) is str and HASH.fullmatch(value) is not None


def load_json(path):
    p = Path(path)
    require(p.is_file() and p.stat().st_size <= MAX_JSON_BYTES, 'missing/oversized input')
    def unique(pairs):
        out = {}
        for key, value in pairs:
            require(key not in out, 'duplicated JSON property')
            out[key] = value
        return out
    def no_constant(value):
        raise ValueError('nonfinite input: ' + value)
    return json.loads(p.read_bytes(), object_pairs_hook=unique,
                      parse_constant=no_constant)


def check_plan(plan):
    exact(plan, ('schema','source_only','frozen_before_predictions',
                 'production_authorized','objective_sha256','models','max_output_tokens',
                 'cases'), 'plan')
    require(plan['schema'] == SCHEMA + '.plan'
        and plan['source_only'] is True
        and plan['frozen_before_predictions'] is True
        and plan['production_authorized'] is False, 'unfrozen/authorizing plan')
    require(hex_sha(plan['objective_sha256']), 'objective')
    require(type(plan['max_output_tokens']) is int
            and 1 <= plan['max_output_tokens'] <= 1024, 'token budget')
    exact(plan['models'], READERS, 'models')
    model_shas = []
    for reader in READERS:
        model = plan['models'][reader]
        exact(model, ('weights_sha256','tokenizer_sha256','runtime_sha256'), 'model')
        require(all(hex_sha(d) for d in model.values()), 'model identity')
        model_shas.append(model['weights_sha256'])
    require(model_shas[0] != model_shas[1], 'reference must be a distinct model')
    cases = plan['cases']
    require(type(cases) is list and 1 <= len(cases) <= MAX_CASES, 'case count')
    seen = set()
    for case in cases:
        exact(case, ('id','family','window','question_sha256','arms'), 'case')
        require(type(case['id']) is str and 1 <= len(case['id']) <= 128
                and case['id'] not in seen, 'case ID')
        seen.add(case['id'])
        require(type(case['family']) is str and 1 <= len(case['family']) <= 128,
                'family identity')
        require(type(case['window']) is str and 1 <= len(case['window']) <= 128,
                'source window')
        require(hex_sha(case['question_sha256']), 'question SHA')
        exact(case['arms'], ARMS, 'evidence arm')
        inputs = []
        for arm in ARMS:
            payload = case['arms'][arm]
            exact(payload, ('request_sha256','evidence_ids'), 'arm')
            require(hex_sha(payload['request_sha256']), 'request SHA')
            ids = payload['evidence_ids']
            require(type(ids) is list and len(ids) <= 32
                    and all(type(x) is str and 1 <= len(x) <= 128 for x in ids)
                    and len(set(ids)) == len(ids), 'evidence IDs')
            inputs.append(payload['request_sha256'])
        require(len(set(inputs)) == len(ARMS), 'arm bytes not actually changed')
        require(not case['arms']['none']['evidence_ids'], 'none contains evidence')
        require(bool(case['arms']['sufficient']['evidence_ids']), 'no sufficient evidence')
        require(bool(case['arms']['retrieved']['evidence_ids']), 'no retrieval evidence')
        require(set(case['arms']['lesion']['evidence_ids'])
                < set(case['arms']['sufficient']['evidence_ids']),
                'lesion did not delete at least one critical source')
    return {(case['id'], reader, arm):case for case in cases
            for reader in READERS for arm in ARMS}


def check_predictions(plan, predictions):
    expected = check_plan(plan)
    exact(predictions, ('schema','plan_sha256','model_output_source','records',
                        'production_authorized'), 'predictions')
    require(predictions['schema'] == SCHEMA + '.predictions'
            and predictions['plan_sha256'] == sha_obj(plan)
            and predictions['model_output_source'] == 'external_original_required'
            and predictions['production_authorized'] is False, 'prediction lineage')
    records = predictions['records']
    require(type(records) is list and len(records) == len(expected), 'prediction census')
    seen = {}
    for row in records:
        exact(row, ('case_id','reader','arm','request_sha256','model_sha256',
                    'answer_sha256','cited_evidence_ids','input_tokens',
                    'output_tokens','cpu_ms','wall_ms','abstained'), 'answer row')
        key = (row['case_id'],row['reader'],row['arm'])
        require(key in expected and key not in seen, 'foreign/duplicate prediction')
        case = expected[key]
        require(row['request_sha256'] == case['arms'][row['arm']]['request_sha256'],
                'changed prompt/source')
        require(row['model_sha256'] == plan['models'][row['reader']]['weights_sha256']
                and hex_sha(row['answer_sha256']), 'model/answer identity')
        citations = row['cited_evidence_ids']
        require(type(citations) is list and len(citations) <= 32
                and all(type(c) is str for c in citations)
                and len(set(citations)) == len(citations)
                and set(citations) <= set(case['arms'][row['arm']]['evidence_ids']),
                'answer cites undelivered evidence')
        for field, maximum in (('input_tokens',10_000_000),
                               ('output_tokens',plan['max_output_tokens']),
                               ('cpu_ms',3_600_000),('wall_ms',3_600_000)):
            value = row[field]
            require(type(value) is int and 0 <= value <= maximum,
                    'invalid resource counter: ' + field)
        require(type(row['abstained']) is bool, 'abstention flag')
        seen[key] = row
    require(len(seen) == len(expected), 'missing Reader output')
    return seen


def check_adjudication(plan, predictions, adjudication):
    outputs = check_predictions(plan, predictions)
    exact(adjudication, ('schema','plan_sha256','predictions_sha256',
                         'reviewer_id','reviewer_independence_unverified',
                         'results'), 'adjudication')
    require(adjudication['schema'] == SCHEMA + '.adjudication'
            and adjudication['plan_sha256'] == sha_obj(plan)
            and adjudication['predictions_sha256'] == sha_obj(predictions)
            and type(adjudication['reviewer_id']) is str
            and 1 <= len(adjudication['reviewer_id']) <= 128
            and adjudication['reviewer_independence_unverified'] is True,
            'reviewer is not independently authenticated')
    rows = adjudication['results']
    require(type(rows) is list and len(rows) == len(outputs), 'adjudication census')
    judged = {}
    for row in rows:
        exact(row, ('case_id','reader','arm','answer_sha256',
                    'correct','citations_entailed'), 'review row')
        key = (row['case_id'], row['reader'], row['arm'])
        require(key in outputs and key not in judged, 'foreign/duplicate judgment')
        require(row['answer_sha256'] == outputs[key]['answer_sha256'],
                'review changed original answer')
        require(type(row['correct']) is bool
                and type(row['citations_entailed']) is bool,
                'invalid correctness judgment')
        judged[key] = row
    require(len(judged) == len(outputs), 'incomplete judgment')
    return outputs, judged


def report(plan, predictions, adjudication):
    outputs, scored = check_adjudication(plan, predictions, adjudication)
    tally = defaultdict(lambda: dict(cases=0, correct=0, citations_entailed=0,
                                     abstained=0, input_tokens=0, output_tokens=0,
                                     cpu_ms=0, wall_ms=0))
    for (case_id, reader, arm), row in outputs.items():
        score = scored[(case_id,reader,arm)]
        t = tally[(reader,arm)]
        t['cases'] += 1
        t['correct'] += int(score['correct'])
        t['citations_entailed'] += int(score['citations_entailed'])
        t['abstained'] += int(row['abstained'])
        for field in ('input_tokens','output_tokens','cpu_ms','wall_ms'):
            t[field] += row[field]
    diagnosis = defaultdict(int)
    for case in plan['cases']:
        cid = case['id']
        success = lambda reader,arm: scored[(cid,reader,arm)]['correct']
        if not success('candidate','sufficient'):
            if success('reference','sufficient'):
                diagnosis['reader_capacity_candidate'] += 1
            else:
                diagnosis['even_reference_fails_sufficient'] += 1
        if success('candidate','sufficient') and not success('candidate','retrieved'):
            diagnosis['retrieval_or_evidence_selection'] += 1
        if success('candidate','sufficient') and not success('candidate','lesion'):
            diagnosis['lesion_sensitive'] += 1
        if success('candidate','none') and success('candidate','sufficient'):
            diagnosis['succeeds_without_evidence_also'] += 1
    return {
        'schema': SCHEMA + '.research-report',
        'plan_sha256': sha_obj(plan),
        'predictions_sha256': sha_obj(predictions),
        'adjudication_sha256': sha_obj(adjudication),
        'case_count': len(plan['cases']),
        'independent_families_claimed_not_authenticated':len({c['family'] for c in plan['cases']}),
        'windows_claimed_not_authenticated':sorted({c['window'] for c in plan['cases']}),
        'per_reader_arm': {reader:{arm:tally[(reader,arm)] for arm in ARMS}
                           for reader in READERS},
        'diagnostics':{name:diagnosis[name] for name in (
            'reader_capacity_candidate','even_reference_fails_sufficient',
            'retrieval_or_evidence_selection','lesion_sensitive',
            'succeeds_without_evidence_also')},
        'independent_human_attestation_verified':False,
        'original_pretrained_execution_verified_by_this_tool':False,
        'causal_learning_gain_verified':False,
        'stem_winner_verified':False,
        'system2_verified':False,
        'production_authorized':False,
        'decision':'HOLD_NO_GO'
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--predictions', required=True)
    parser.add_argument('--adjudication', required=True)
    args = parser.parse_args()
    result = report(load_json(args.plan), load_json(args.predictions),
                    load_json(args.adjudication))
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False,
                     allow_nan=False))


if __name__ == '__main__':
    main()
