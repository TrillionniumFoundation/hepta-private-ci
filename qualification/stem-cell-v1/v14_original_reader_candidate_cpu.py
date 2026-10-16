"""V14 original archived 135M Reader *candidate* physical CPU runner.

The only supported original model is the SHA-pinned V12 manual-FP32 Reader,
which is explicitly NOT certified as official HF operator/tokenizer parity.
Its output is private, partial (candidate only), and NEVER a full V14 result,
independent evaluator, selected Stem, or FinalUse permission.

Refuses source/plan/prompt drift before opening model tensors. No synthetic
fallback, no substitute weights, no hosted secret download, no gold scoring.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
import time

from v14_reader_original_request_review import review as source_replay
from v14_reader_sufficiency_gate import ARMS, SCHEMA, load_json, require, sha_obj

MODEL_SHA = '5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c'
TOKEN_SHA = '9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c'
CONFIG_SHA = '8eb740e8bbe4cff95ea7b4588d17a2432deb16e8075bc5828ff7ba9be94d982a'
OUTPUT_SCHEMA = SCHEMA + '.original-candidate-physical-partial.v1'
MAX_CASES_PER_RUN = 64
MAX_INPUT_TOKENS = 1000
MAX_GENERATED_TOKENS = 24
CITATION = re.compile(r'\[([A-Za-z0-9._:/-]{1,128})\]')


def file_sha(path):
    digest = sha256()
    with Path(path).open('rb') as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_file():
    return Path(__file__).resolve().with_name('v12_reader_runtime.py')


def check_manifest(source, plan, private):
    """Pure stdlib original-input preflight, no tensors/model/torch loaded."""
    prior = source_replay(source, plan, private)
    require(1 <= len(plan['cases']) <= MAX_CASES_PER_RUN, 'bounded original case batch')
    manifest = plan['models']['candidate']
    require(manifest['weights_sha256'] == MODEL_SHA
            and manifest['tokenizer_sha256'] == TOKEN_SHA
            and manifest['runtime_sha256'] == file_sha(runtime_file()),
            'original candidate weights/tokenizer/runtime must match exact pinned source')
    require(plan['max_output_tokens'] <= MAX_GENERATED_TOKENS, 'output cap > original Reader')
    jobs = []
    seen = set()
    for case in plan['cases']:
        cid = case['id']
        for arm in ARMS:
            row = private['requests'][cid][arm]
            prompt = row['raw_original_model_input']
            prompt_sha = sha256(prompt.encode('utf-8')).hexdigest()
            require(prompt_sha == case['arms'][arm]['request_sha256']
                    and prompt_sha == row['request_sha256'],
                    'physical Reader request detached from source-first manifest')
            identifier = (cid, arm, prompt_sha)
            require(identifier not in seen, 'duplicate original model job')
            seen.add(identifier)
            jobs.append((cid, arm, prompt, prompt_sha,
                         tuple(case['arms'][arm]['evidence_ids'])))
    require(len(jobs) == 4 * len(plan['cases']), 'incomplete candidate Reader input')
    return prior, jobs


def pin_original_material(root):
    """Hash original material BEFORE importing PyTorch or touching output."""
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), 'original Reader directory invalid')
    material = {
        'model.safetensors': MODEL_SHA,
        'tokenizer.json': TOKEN_SHA,
        'config.json': CONFIG_SHA,
    }
    for name, expected in material.items():
        p = root / name
        require(p.is_file() and not p.is_symlink() and file_sha(p) == expected,
                'original model material unavailable or differs: ' + name)
    return root


def open_private_once(path):
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError('private original output already exists')
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    return os.fdopen(os.open(target, flags, 0o600), 'w', encoding='utf-8')


def run(source_path, plan_path, private_path, reader_dir, output_path):
    source = load_json(source_path)
    plan = load_json(plan_path)
    private = load_json(private_path)
    prior, jobs = check_manifest(source, plan, private)
    target = Path(output_path)
    starts = Path(str(target) + '.starts.jsonl')
    require(target != starts and not target.exists() and not starts.exists()
            and not target.is_symlink() and not starts.is_symlink(),
            'original output/journal must be create-only')
    original_root = pin_original_material(reader_dir)

    # Import heavy original pretrained dependencies only AFTER source + weight
    # identity is accepted. No fake/fixture-model execution alternative exists.
    from v12_reader_runtime import (
        OriginalCandidateBPE, OriginalCandidateLlama, check_original,
    )
    import torch

    check_original(original_root)
    torch.set_num_threads(2)
    tokenizer = OriginalCandidateBPE(original_root)
    pretokenized = []
    for case_id, arm, prompt, request_sha, ids in jobs:
        original_ids = tokenizer.encode(prompt)
        require(1 <= len(original_ids) <= MAX_INPUT_TOKENS,
                'untruncated original Reader prompt exceeds declared budget')
        pretokenized.append((case_id, arm, request_sha, ids, original_ids))
    # Readable exact material cannot drift between preflight and model use.
    pin_original_material(original_root)
    reader = OriginalCandidateLlama(original_root)

    records = []
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    with open_private_once(starts) as journal:
        for case_id, arm, request_sha, source_ids, input_ids in pretokenized:
            attempt = {
                'case_id': case_id,
                'arm': arm,
                'request_sha256': request_sha,
                'original_model_sha256': MODEL_SHA,
                'original_input_token_ids_sha256': sha_obj(input_ids),
                'original_input_tokens': len(input_ids),
                'physical_original_model_started': True,
                'production_authorized': False,
            }
            journal.write(json.dumps(attempt, sort_keys=True) + '\n')
            journal.flush()
            os.fsync(journal.fileno())
            before_cpu, before_wall = time.process_time(), time.perf_counter()
            output_ids = reader.generate(input_ids, max_tokens=plan['max_output_tokens'])
            answer = tokenizer.decode(output_ids)
            cpu_ms = max(0, round(1000 * (time.process_time() - before_cpu)))
            wall_ms = max(0, round(1000 * (time.perf_counter() - before_wall)))
            require(1 <= len(output_ids) <= plan['max_output_tokens'],
                    'physical original model output cap')
            cited_raw = list(dict.fromkeys(CITATION.findall(answer)))
            delivered = set(source_ids)
            records.append({
                'case_id': case_id,
                'arm': arm,
                'request_sha256': request_sha,
                'input_token_ids_sha256': sha_obj(input_ids),
                'input_tokens': len(input_ids),
                'original_generated_token_ids': output_ids,
                'output_tokens': len(output_ids),
                'original_raw_answer': answer,
                'answer_sha256': sha256(answer.encode('utf-8')).hexdigest(),
                'cited_evidence_ids': [x for x in cited_raw if x in delivered],
                'unregistered_citation_ids': [x for x in cited_raw if x not in delivered],
                'abstention_semantics_independently_verified': False,
                'cpu_ms': cpu_ms,
                'wall_ms': wall_ms,
            })

    require(len(records) == len(jobs), 'incomplete physical candidate roster')
    # Retain raw answer source only in PRIVATE output, never in public CI docs.
    payload = {
        'schema': OUTPUT_SCHEMA,
        'source_sha256': prior['source_sha256'],
        'plan_sha256': sha_obj(plan),
        'private_prompt_packet_sha256': prior['private_packet_sha256'],
        'original_model_weights_sha256': MODEL_SHA,
        'original_model_tokenizer_sha256': TOKEN_SHA,
        'original_model_config_sha256': CONFIG_SHA,
        'original_runtime_sha256': file_sha(runtime_file()),
        'journal_sha256': file_sha(starts),
        'candidate_only': True,
        'reference_reader_executed': False,
        'independent_host_attestation_verified': False,
        'official_hf_operator_tokenizer_parity': False,
        'reader_source_claimed_original': True,
        'model_forward_calls': reader.calls,
        'model_calls_completed': len(records),
        'model_cpu_ms': round(1000 * (time.process_time() - started_cpu)),
        'model_wall_ms': round(1000 * (time.perf_counter() - started_wall)),
        'private_raw_original_answers': records,
        'independent_semantic_correctness': None,
        'production_authorized': False,
        'decision': 'HOLD_NO_GO',
    }
    pin_original_material(original_root)
    require(payload['original_runtime_sha256'] == plan['models']['candidate']['runtime_sha256'],
            'Reader code changed during model execution')
    with open_private_once(target) as file:
        json.dump(payload, file, sort_keys=True, ensure_ascii=False, allow_nan=False)
        file.write('\n')
        file.flush()
        os.fsync(file.fileno())
    return {
        'schema': SCHEMA + '.original-candidate-source-free-physical-receipt.v1',
        'original_output_sha256': file_sha(target),
        'source_sha256': prior['source_sha256'],
        'plan_sha256': sha_obj(plan),
        'model_sha256': MODEL_SHA,
        'original_candidate_requests': len(records),
        'original_model_forward_calls': reader.calls,
        'original_total_model_cpu_ms': payload['model_cpu_ms'],
        'original_total_model_wall_ms': payload['model_wall_ms'],
        'real_model_output_claim_requires_external_attestation': True,
        'reference_reader_executed': False,
        'human_semantic_correctness_verified': False,
        'stem_winner_verified': False,
        'production_authorized': False,
        'decision': 'HOLD_NO_GO',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--private-requests', required=True)
    parser.add_argument('--original-reader-root', required=True)
    parser.add_argument('--private-output', required=True)
    args = parser.parse_args()
    receipt = run(args.source, args.plan, args.private_requests,
                  args.original_reader_root, args.private_output)
    print(json.dumps(receipt, sort_keys=True, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
