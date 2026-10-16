"""Independent V14 original *candidate-only* private-output consistency review.

Software-only journal/token/citation reconstruction. No model invocation,
model-host signature, official tokenizer parity, human adjudication, reference
Reader execution or FinalUse. Original raw model answers remain PRIVATE.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import stat

from v14_reader_original_request_review import review as source_replay
from v14_reader_sufficiency_gate import (
    ARMS, SCHEMA, load_json, require, sha_obj,
)

MODEL_SHA = '5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c'
TOKEN_SHA = '9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224cfd888e47c'
# Original checksum MUST be exact. This is intentionally a literal domain
# independent of the model-execution producer's constants.
TOKEN_SHA = '9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224cfd888e47c'.replace('cfd', 'cfd')
CITATION = re.compile(r'\[([A-Za-z0-9._:/-]{1,128})\]')
SCHEMA_PACKET = SCHEMA + '.original-candidate-physical-partial.v1'
JOURNAL_MAX = 4 * 1024 * 1024


def file_sha(path):
    h = sha256()
    with Path(path).open('rb') as reader:
        for chunk in iter(lambda: reader.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def private_file(path, max_bytes):
    target = Path(path)
    require(target.is_file() and not target.is_symlink()
            and 1 <= target.stat().st_size <= max_bytes, 'private file missing/oversized')
    if hasattr(stat, 'S_IMODE'):
        require(stat.S_IMODE(target.stat().st_mode) & 0o077 == 0,
                'private output visible outside owner')
    return target


def journal_rows(path):
    target = private_file(path, JOURNAL_MAX)
    results = []
    for raw in target.read_bytes().splitlines():
        require(bool(raw), 'empty journal entry')
        def unique(pairs):
            d = {}
            for key, value in pairs:
                require(key not in d, 'duplicate original attempt field')
                d[key] = value
            return d
        def invalid(value):
            raise ValueError('nonfinite original attempt: ' + value)
        results.append(json.loads(raw, object_pairs_hook=unique,
                                  parse_constant=invalid))
    return results


def exact(obj, fields, label):
    require(type(obj) is dict and set(obj) == set(fields), label + ' fields')


def review(original, plan, private, candidate, journal, journal_file):
    source = source_replay(original, plan, private)
    expected_model = plan['models']['candidate']
    require(expected_model['weights_sha256'] == MODEL_SHA, 'wrong candidate weights')
    require(candidate['schema'] == SCHEMA_PACKET, 'wrong physical candidate schema')
    exact(candidate, (
        'schema','source_sha256','plan_sha256','private_prompt_packet_sha256',
        'original_model_weights_sha256','original_model_tokenizer_sha256',
        'original_model_config_sha256','original_runtime_sha256','journal_sha256',
        'candidate_only','reference_reader_executed',
        'independent_host_attestation_verified','official_hf_operator_tokenizer_parity',
        'reader_source_claimed_original','model_forward_calls','model_calls_completed',
        'model_cpu_ms','model_wall_ms','private_raw_original_answers',
        'independent_semantic_correctness','production_authorized','decision',
    ), 'original candidate packet')
    require(candidate['source_sha256'] == source['source_sha256']
            and candidate['plan_sha256'] == source['plan_sha256']
            and candidate['private_prompt_packet_sha256'] == source['private_packet_sha256']
            and candidate['original_model_weights_sha256'] == expected_model['weights_sha256']
            and candidate['original_model_tokenizer_sha256'] == expected_model['tokenizer_sha256']
            and candidate['original_runtime_sha256'] == expected_model['runtime_sha256']
            and candidate['journal_sha256'] == file_sha(journal_file),
            'source/model/runtime/journal material drift')
    for field, required in (
        ('candidate_only', True),('reference_reader_executed', False),
        ('independent_host_attestation_verified', False),
        ('official_hf_operator_tokenizer_parity', False),
        ('reader_source_claimed_original', True),
        ('independent_semantic_correctness', None),
        ('production_authorized', False),('decision','HOLD_NO_GO'),
    ):
        require(candidate[field] is required if required is None or type(required) is bool
                else candidate[field] == required, 'false original/authority claim: ' + field)

    originals = candidate['private_raw_original_answers']
    require(type(originals) is list and
            len(originals) == 4 * len(plan['cases']) and len(originals) <= 256,
            'complete original candidate-only attempt census')
    require(type(journal) is list and len(journal) == len(originals),
            'original fsynced pre-attempt census')
    outputs = []
    total_calls = 0
    for index, (row, attempt) in enumerate(zip(originals, journal)):
        case = plan['cases'][index // 4]
        arm = ARMS[index % 4]
        prompt = private['requests'][case['id']][arm]
        delivered = case['arms'][arm]['evidence_ids']
        exact(attempt, ('case_id','arm','request_sha256','original_model_sha256',
                        'original_input_token_ids_sha256','original_input_tokens',
                        'physical_original_model_started','production_authorized'),
              'attempt')
        exact(row, ('case_id','arm','request_sha256','input_token_ids_sha256',
                    'input_tokens','original_generated_token_ids','output_tokens',
                    'original_raw_answer','answer_sha256','cited_evidence_ids',
                    'unregistered_citation_ids','abstention_semantics_independently_verified',
                    'cpu_ms','wall_ms'), 'physical response')
        require(row['case_id'] == attempt['case_id'] == case['id']
                and row['arm'] == attempt['arm'] == arm
                and row['request_sha256'] == attempt['request_sha256']
                    == prompt['request_sha256']
                and attempt['original_model_sha256'] == MODEL_SHA
                and attempt['physical_original_model_started'] is True
                and attempt['production_authorized'] is False,
                'original model attempt detached from frozen Reader plan')
        require(row['input_token_ids_sha256'] == attempt['original_input_token_ids_sha256']
                and type(row['input_tokens']) is int
                and row['input_tokens'] == attempt['original_input_tokens']
                and 1 <= row['input_tokens'] <= 1000,
                'original model input token/length drift')
        tokens = row['original_generated_token_ids']
        require(type(tokens) is list and type(row['output_tokens']) is int
                and len(tokens) == row['output_tokens']
                and 1 <= len(tokens) <= plan['max_output_tokens']
                and all(type(i) is int and 0 <= i < 49152 for i in tokens)
                and 2 not in tokens[:-1], 'generated original token shape or EOS')
        total_calls += len(tokens) + (0 if tokens[-1] == 2 else 1)
        answer = row['original_raw_answer']
        require(type(answer) is str
                and sha256(answer.encode('utf-8')).hexdigest() == row['answer_sha256'],
                'original response SHA')
        ids = list(dict.fromkeys(CITATION.findall(answer)))
        require(row['cited_evidence_ids'] == [x for x in ids if x in delivered]
                and row['unregistered_citation_ids'] == [x for x in ids if x not in delivered],
                'model original answer citation not faithfully recorded')
        require(row['abstention_semantics_independently_verified'] is False,
                'unsupported model-based abstention truth')
        for field in ('cpu_ms','wall_ms'):
            require(type(row[field]) is int and 0 <= row[field] <= 3_600_000,
                    'original physical cost counter')
        outputs.append({
            'case_id': case['id'], 'arm': arm,
            'original_answer_sha256': row['answer_sha256'],
            'unregistered_citation_count': len(row['unregistered_citation_ids']),
        })
    require(type(candidate['model_calls_completed']) is int
            and candidate['model_calls_completed'] == len(originals)
            and type(candidate['model_forward_calls']) is int
            and candidate['model_forward_calls'] == total_calls,
            'original physical complete request/forward count')
    for name in ('model_cpu_ms','model_wall_ms'):
        require(type(candidate[name]) is int and candidate[name] >= 0
                and candidate[name] + len(originals) >= sum(row[name.replace('model_', '')] for row in originals),
                'invalid full-model cost conservation')
    return {
        'schema': SCHEMA + '.original-candidate-independent-structural-review.v1',
        'source_sha256': source['source_sha256'],
        'plan_sha256': source['plan_sha256'],
        'candidate_output_sha256': sha_obj(candidate),
        'original_attempt_journal_sha256': file_sha(journal_file),
        'candidate_requests_claimed': len(originals),
        'independently_recounted_model_forward_calls': total_calls,
        'source_bound_answer_digests': outputs,
        'original_tokenizer_retoked_against_checkpoint': False,
        'actual_model_inference_independently_replayed': False,
        'independent_host_attestation_verified': False,
        'reference_reader_executed': False,
        'human_semantic_accuracy_verified': False,
        'production_authorized': False,
        'decision': 'HOLD_NO_GO',
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for field in ('source','plan','private-requests','candidate-output','journal'):
        cli.add_argument('--'+field,required=True)
    a = cli.parse_args()
    candidate_path = private_file(a.candidate_output, 16 * 1024 * 1024)
    precommit = journal_rows(a.journal)
    out = review(load_json(a.source), load_json(a.plan),
                 load_json(a.private_requests), load_json(candidate_path),
                 precommit, a.journal)
    print(json.dumps(out,sort_keys=True,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
