"""Frozen V16 original question/evidence -> real Qwen3 reference, private only.

All original source text is handled on the operator's local machine. A sealed
model run is NOT a semantic evaluation, independent host attestation, proven
Reader improvement, or production admission. Never upload plan/starts/responses.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time

BASE_SCHEMA = 'hepta.stem.v16.original-literal-answer-witness.shadow.v1'
SCHEMA = 'hepta.stem.v17.physical-reference-reader.shadow.v1'
ARMS = ('none', 'retrieved', 'witness', 'lesion')
GROUPS = ('literal_in_annotated_source', 'not_literal_in_annotated_source')
ROOTS = ('conv-47', 'conv-48', 'conv-49', 'conv-50')
REPO = 'Qwen/Qwen3-0.6B'
# Exact public historical Qwen3-0.6B revision; runtime never fetches main.
REVISION = '16706fc57485378d4ffaf54139b29ccc66ae08fa'
REQUIRED = ('config.json', 'tokenizer_config.json', 'tokenizer.json', 'model.safetensors')
OPTIONAL = ('generation_config.json', 'vocab.json', 'merges.txt')
OUT_CAP = 24
INPUT_CAP = 2048
SYSTEM = 'Answer only from numbered evidence. If not supported, reply unknown. Cite supporting evidence using [E1], [E2] or [E3].'
PRE_SYS = '<|im_start|>system\n'
SEP_USER = '<|im_end|>\n<|im_start|>user\n'
END_USER = '\n<|im_end|>\n<|im_start|>assistant\n'


def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def digest(x):
    return hashlib.sha256(canonical(x)).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def pairs(items):
    obj = {}
    for k, v in items:
        if k in obj:
            raise ValueError('duplicate JSON key')
        obj[k] = v
    return obj


def read(path, cap=20_000_000):
    p = Path(path)
    if not p.is_file() or p.is_symlink() or not 0 < p.stat().st_size <= cap:
        raise ValueError('unsafe/empty/unbounded JSON file')
    return json.loads(p.read_bytes(), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def write_private(path, payload):
    p = Path(path)
    if p.is_symlink() or p.exists():
        raise FileExistsError('refuse mutable or existing receipt')
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(canonical(payload) + b'\n')
        f.flush()
        os.fsync(f.fileno())


def expected_plan(plan):
    if type(plan) is not dict or plan.get('schema') != BASE_SCHEMA + '.answer-dependent-precommitted-plan':
        raise ValueError('wrong frozen original V16 plan')
    if (plan.get('source_roots') != list(ROOTS) or plan.get('frozen_arms') != list(ARMS)
        or plan.get('answer_dependent_historical_selection') is not True
        or plan.get('label_text_entered_model_prompts') is not False
        or plan.get('literal_containment_not_human_sufficiency') is not True
        or plan.get('independent_semantic_adjudication') is not False
        or plan.get('stronger_reference_reader_executed') is not False
        or plan.get('candidate_only_reader') is not True
        or plan.get('production_authorized') is not False
        or plan.get('max_new_tokens') != OUT_CAP):
        raise ValueError('unfrozen or forged V16 experiment status')
    cases, requests = plan.get('cases'), plan.get('requests')
    if type(cases) is not list or type(requests) is not dict or len(cases) != 32 or len(requests) != 128:
        raise ValueError('incomplete original V16 case/request matrix')
    seen_cases, seen_requests = set(), set()
    groups = {(root, group): 0 for root in ROOTS for group in GROUPS}
    for c in cases:
        if type(c) is not dict or set(c) != {'id', 'family', 'cohort', 'witness_id', 'arms'}:
            raise ValueError('unbound case')
        cid, fam, cohort = c['id'], c['family'], c['cohort']
        if (not isinstance(cid, str) or not cid.startswith(fam + '/q')
            or (fam, cohort) not in groups or cid in seen_cases or set(c['arms']) != set(ARMS)):
            raise ValueError('unexpected original case identity')
        seen_cases.add(cid)
        groups[(fam, cohort)] += 1
        for arm in ARMS:
            a = c['arms'][arm]
            if type(a) is not dict or set(a) != {'request_id', 'evidence_ids'}:
                raise ValueError('unbound evidence arm')
            rid = a['request_id']
            if type(rid) is not str or rid in seen_requests or rid not in requests:
                raise ValueError('duplicate/missing original request')
            seen_requests.add(rid)
            row = requests[rid]
            if (type(row) is not dict or set(row) != {'case_id', 'family', 'arm', 'prompt', 'source_ids', 'question_sha256'}
                or (row['case_id'], row['family'], row['arm']) != (cid, fam, arm)
                or row['source_ids'] != a['evidence_ids'] or digest_text(row['prompt']) != rid):
                raise ValueError('original prompt/source substitution')
            parse_messages(row['prompt'], a['evidence_ids'])
    if any(n != 4 for n in groups.values()) or seen_requests != set(requests):
        raise ValueError('missing original source group')
    return requests


def digest_text(x):
    if type(x) is not str:
        raise ValueError('not a UTF-8 text field')
    return hashlib.sha256(x.encode('utf-8')).hexdigest()


def parse_messages(prompt, sources):
    if type(prompt) is not str or not prompt.startswith(PRE_SYS + SYSTEM + SEP_USER) or not prompt.endswith(END_USER):
        raise ValueError('original evidence prompt format changed')
    if any(marker in prompt[len(PRE_SYS + SYSTEM + SEP_USER):-len(END_USER)]
           for marker in ('<|im_start|>', '<|im_end|>')):
        raise ValueError('embedded role delimiter in source')
    user = prompt[len(PRE_SYS + SYSTEM + SEP_USER):-len(END_USER)]
    if not user.startswith('Question: ') or type(sources) is not list or len(sources) > 3:
        raise ValueError('missing question/evidence descriptor')
    headers = re.findall(r'(?m)^\[E(\d+)\] ', user)
    if headers != [str(i + 1) for i in range(len(sources))]:
        raise ValueError('question/evidence numbering mismatch')
    return [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': user}]


def verify_model_files(folder, spec):
    if type(spec) is not dict or set(spec) != {'schema', 'repo_id', 'revision', 'files_sha256',
                                               'thinking', 'decoding', 'production_authorized'}:
        raise ValueError('unfrozen model manifest')
    if (spec['schema'] != SCHEMA + '.frozen-model-v1' or spec['repo_id'] != REPO
        or spec['revision'] != REVISION or spec['thinking'] is not False
        or spec['decoding'] != 'greedy-24-new-tokens'
        or spec['production_authorized'] is not False):
        raise ValueError('wrong model revision/mode')
    hashes = spec['files_sha256']
    if type(hashes) is not dict or not set(REQUIRED).issubset(hashes) or not set(hashes).issubset(REQUIRED + OPTIONAL):
        raise ValueError('missing/foreign model file')
    path = Path(folder)
    if not path.is_dir() or path.is_symlink():
        raise ValueError('missing/symlink model snapshot')
    entries = list(path.iterdir())
    if any(not p.is_file() or p.is_symlink() for p in entries):
        raise ValueError('model snapshot contains nonregular or symlink entries')
    actual = {p.name for p in entries}
    if actual != set(hashes):
        raise ValueError('model snapshot contains unexpected/missing files')
    for name, want in hashes.items():
        p = path / name
        if (type(want) is not str or re.fullmatch('[0-9a-f]{64}', want) is None
            or not p.is_file() or p.is_symlink() or p.stat().st_size == 0
            or p.stat().st_size > 2_500_000_000 or file_sha(p) != want):
            raise ValueError('model source bytes mismatch: ' + name)
    return digest(spec)


def encode(tokenizer, row):
    messages = parse_messages(row['prompt'], row['source_ids'])
    ids = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
                                        enable_thinking=False)
    if type(ids) is not list or not 1 <= len(ids) <= INPUT_CAP or any(type(i) is not int or i < 0 for i in ids):
        raise ValueError('tokenizer output invalid/unbounded')
    return ids


def execute(plan, source, ranks, model_folder, spec, output):
    # Real V16 source/rank validator; producer cannot silently substitute evidence.
    from v16_literal_witness_reader import validate
    validate(plan, source, ranks)
    requests = expected_plan(plan)
    spec_hash = verify_model_files(model_folder, spec)
    output = Path(output)
    starts = Path(str(output) + '.starts.jsonl')
    if output.exists() or starts.exists() or output.is_symlink() or starts.is_symlink():
        raise FileExistsError('reference run already exists')
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    torch.set_num_threads(2)
    tokenizer = AutoTokenizer.from_pretrained(model_folder, local_files_only=True,
                                               trust_remote_code=False, use_fast=True)
    model = AutoModelForCausalLM.from_pretrained(model_folder, local_files_only=True,
                trust_remote_code=False, use_safetensors=True, dtype=torch.float32).eval()
    # Verify the model material again after construction to detect TOCTOU mutation.
    if verify_model_files(model_folder, spec) != spec_hash:
        raise ValueError('model material changed during loading')
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    answer_rows = {}
    fd = os.open(str(starts), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as journal, torch.inference_mode():
        for rid, row in sorted(requests.items()):
            ids = encode(tokenizer, row)
            event = {'request_id': rid, 'plan_sha256': digest(plan), 'model_spec_sha256': spec_hash,
                     'input_ids_sha256': digest(ids), 'input_tokens': len(ids)}
            journal.write(json.dumps(event, sort_keys=True) + '\n')
            journal.flush()
            os.fsync(journal.fileno())
            t0 = time.process_time()
            out = model.generate(input_ids=torch.tensor([ids], dtype=torch.long),
                                 do_sample=False, max_new_tokens=OUT_CAP,
                                 pad_token_id=tokenizer.eos_token_id)
            all_ids = out[0].tolist()
            if all_ids[:len(ids)] != ids:
                raise ValueError('model changed original token prefix')
            new_ids = all_ids[len(ids):]
            if not 1 <= len(new_ids) <= OUT_CAP:
                raise ValueError('missing/overflow reference generation')
            answer = tokenizer.decode(new_ids, skip_special_tokens=True)
            answer_rows[rid] = {
                'case_id': row['case_id'], 'family': row['family'], 'arm': row['arm'],
                'source_ids': row['source_ids'], 'answer_text': answer,
                'answer_sha256': digest_text(answer), 'output_ids': new_ids,
                'input_ids_sha256': digest(ids), 'input_tokens': len(ids),
                'output_tokens': len(new_ids), 'cpu_seconds': time.process_time()-t0,
            }
    receipt = {'schema': SCHEMA + '.sealed-model-output', 'plan_sha256': digest(plan),
               'model_spec_sha256': spec_hash, 'model_name': REPO,
               'reference_request_count': len(answer_rows), 'raw_answers': answer_rows,
               'execution_cpu_seconds': time.process_time()-start_cpu,
               'execution_wall_seconds': time.perf_counter()-start_wall,
               'candidate_original_reader_rerun': False,
               'reference_model_forward_attested_independently': False,
               'independent_human_evidence_sufficiency': False,
               'semantic_accuracy': None, 'production_authorized': False,
               'status': 'PHYSICAL_PRODUCER_ONLY_NO_GO'}
    write_private(output, receipt)
    return receipt


def cli():
    ap = argparse.ArgumentParser()
    for arg in ('plan', 'source', 'bm25', 'model-dir', 'model-spec', 'output'):
        ap.add_argument('--' + arg, required=True)
    x = ap.parse_args()
    r = execute(read(x.plan), read(x.source), read(x.bm25),
                x.model_dir, read(x.model_spec), x.output)
    print(json.dumps({'status': r['status'], 'request_count': r['reference_request_count'],
                      'cpu_seconds': r['execution_cpu_seconds']}, sort_keys=True))


if __name__ == '__main__':
    cli()
