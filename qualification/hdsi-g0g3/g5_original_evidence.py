"""Original-publisher LoCoMo evidence-retrieval Cell study; research only.

Freeze one SHA-verified MiniLM Encoder, source-first source-root split, and a
low-rank neural query/document Cell. The held publisher evidence and answer never
enter this process after the source-owner's label-free source packet is sealed.
No natural answer generation, causal NDU advantage or production permission.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time

from feature_bus import Borrow, Scope, SharedFeatureBus, Denied
from real_minilm_reference import CHECKSUMS
from g5_batched_encoder import BatchedMiniLM, verified_encoder_only

SCHEMA = 'hepta.hdsi.g5.locomo-original-source.v1'
RUN_SCHEMA = 'hepta.hdsi.g5.real-minilm-evidence-study.v1'
TRAIN_ROOTS = ('conv-26', 'conv-30', 'conv-41', 'conv-42', 'conv-43', 'conv-44')
HELD_ROOTS = ('conv-47', 'conv-48', 'conv-49', 'conv-50')
DOCS = 256
QUESTIONS = 24
RANK = 8
STEPS = 100
SEED = 7347
HEX = re.compile(r'[0-9a-f]{64}\Z')
WORD = re.compile(r'(?u)\b\w+\b')
ARMS = ('bm25', 'cosine', 'rank8', 'sham_rank8', 'zero_features', 'shuffled_question')


def must(pred: object, desc: str) -> None:
    if pred is not True:
        raise Denied(desc)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canon(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def _sealed(payload: dict, identity: str) -> dict:
    out = dict(payload)
    out['digest'] = sha(identity.encode() + b'\0' + canon(out))
    return out


def read_publisher(raw: bytes) -> list[dict]:
    must(0 < len(raw) < 4_000_000 and sha(raw) == CHECKSUMS['locomo.json'],
         'original LoCoMo publisher bytes do not match frozen SHA')
    records = json.loads(raw, object_pairs_hook=_unique_pairs)
    must(type(records) is list and len(records) == 10, 'invalid original roots')
    must({r.get('sample_id') for r in records} == set(TRAIN_ROOTS + HELD_ROOTS),
         'wrong publisher root identities')
    return records


def _unique_pairs(pairs):
    out = {}
    for k, v in pairs:
        must(k not in out, 'duplicate JSON key')
        out[k] = v
    return out


def _doc_rank(root: str, doc_id: str) -> str:
    return sha(('hdsi.g5.doc.v1\0' + root + '\0' + doc_id).encode())


def _question_rank(root: str, question: str, index: int) -> str:
    return sha(('hdsi.g5.question.v1\0' + root + '\0' + str(index) + '\0' + question).encode())


def source_packet(raw: bytes) -> dict:
    roots = read_publisher(raw)
    out = []
    for r in sorted(roots, key=lambda z: z['sample_id']):
        root = r['sample_id']
        sources = {}
        for key, turns in r['conversation'].items():
            if not key.startswith('session_') or type(turns) is not list:
                continue
            for turn in turns:
                if type(turn) is not dict:
                    continue
                sentence = turn.get('text')
                if (type(sentence) is not str or not 12 <= len(sentence) <= 180
                        or len(sentence.encode('utf-8')) > 240):
                    continue
                doc_id = turn.get('dia_id')
                speaker = turn.get('speaker')
                if type(doc_id) is not str or not re.fullmatch(r'D\d+:\d+', doc_id):
                    continue
                if type(speaker) is not str or not 1 <= len(speaker) <= 64:
                    continue
                text = speaker + ': ' + sentence
                must(doc_id not in sources, 'duplicate publisher dialogue ID')
                sources[doc_id] = {'id': doc_id, 'text': text,
                                   'text_sha': sha(text.encode())}
        docs = sorted(sources.values(), key=lambda d: (_doc_rank(root, d['id']), d['id']))[:DOCS]
        must(len(docs) == DOCS, 'not enough source-first valid utterances')
        valid_q = []
        for ix, record in enumerate(r['qa']):
            q = record.get('question') if type(record) is dict else None
            if type(q) is not str or not 4 <= len(q.strip()) <= 350 or len(q.encode()) > 800:
                continue
            valid_q.append((_question_rank(root, q, ix), {'id': f'q{ix}', 'text': q,
                                                          'text_sha': sha(q.encode())}, record))
        valid_q.sort(key=lambda z: z[0])
        must(len(valid_q) >= QUESTIONS, 'not enough original source-first questions')
        selected = valid_q[:QUESTIONS]
        name = 'TRAIN' if root in TRAIN_ROOTS else 'HELD'
        packet = {'root': root, 'split': name, 'docs': docs,
                  'questions': [v[1] for v in selected]}
        if name == 'TRAIN':
            # Training gold is legal only for the named TRAIN roots.
            for q, (_, _, original) in zip(packet['questions'], selected):
                raw_evidence = original.get('evidence')
                must(type(raw_evidence) is list, 'publisher evidence type changed')
                q['train_support'] = sorted({str(x) for x in raw_evidence if type(x) is str})
        out.append(packet)
    must(sum(z['split'] == 'TRAIN' for z in out) == 6
         and sum(z['split'] == 'HELD' for z in out) == 4, 'wrong source-root split')
    return _sealed({'schema': SCHEMA, 'original_sha': CHECKSUMS['locomo.json'],
                    'model_sha': CHECKSUMS['encoder/model.safetensors'],
                    'doc_cap': DOCS, 'questions_per_root': QUESTIONS,
                    'train_root_count': 6, 'held_root_count': 4,
                    'roots': out, 'production_authorized': False,
                    'disposition': 'HOLD_NO_GO'}, 'hepta.hdsi.g5.original-source')


def verify_packet(packet: dict) -> None:
    must(type(packet) is dict and set(packet) ==
         {'schema', 'original_sha', 'model_sha', 'doc_cap', 'questions_per_root',
          'train_root_count', 'held_root_count', 'roots', 'production_authorized',
          'disposition', 'digest'}, 'strict source packet')
    must(packet['schema'] == SCHEMA and packet['original_sha'] == CHECKSUMS['locomo.json']
         and packet['model_sha'] == CHECKSUMS['encoder/model.safetensors']
         and packet['doc_cap'] == DOCS and packet['questions_per_root'] == QUESTIONS
         and packet['train_root_count'] == 6 and packet['held_root_count'] == 4
         and packet['production_authorized'] is False
         and packet['disposition'] == 'HOLD_NO_GO', 'source authority or scope')
    must(packet['digest'] == _sealed({k: v for k, v in packet.items() if k != 'digest'},
                                    'hepta.hdsi.g5.original-source')['digest'], 'source seal mismatch')
    must(type(packet['roots']) is list and len(packet['roots']) == 10, 'root count')
    for item in packet['roots']:
        must(type(item) is dict and set(item) == {'root', 'split', 'docs', 'questions'}, 'root shape')
        root = item['root']
        must(item['split'] == ('TRAIN' if root in TRAIN_ROOTS else 'HELD')
             and root in TRAIN_ROOTS + HELD_ROOTS, 'root split substitution')
        must(type(item['docs']) is list and len(item['docs']) == DOCS
             and type(item['questions']) is list and len(item['questions']) == QUESTIONS, 'bank bounds')
        for d in item['docs']:
            must(type(d) is dict and set(d) == {'id', 'text', 'text_sha'}
                 and sha(d['text'].encode()) == d['text_sha'], 'wrong document')
        for q in item['questions']:
            expected = {'id', 'text', 'text_sha', 'train_support'} if item['split'] == 'TRAIN' else {'id', 'text', 'text_sha'}
            must(type(q) is dict and set(q) == expected
                 and sha(q['text'].encode()) == q['text_sha'], 'held label leaked or question changed')
            if 'train_support' in q:
                must(type(q['train_support']) is list and len(q['train_support']) < 30, 'malformed TRAIN support')


def bm25(q: str, texts: list[str]) -> list[float]:
    query = WORD.findall(q.casefold())
    docs = [WORD.findall(t.casefold()) for t in texts]
    n = len(docs)
    avg = sum(len(d) for d in docs) / max(n, 1)
    from collections import Counter
    dfs = Counter(word for tokens in docs for word in set(tokens))
    score = []
    for tokens in docs:
        counts = Counter(tokens)
        length_norm = 0.25 + 0.75 * len(tokens) / max(avg, 1)
        total = 0.0
        for word in set(query):
            tf = counts.get(word, 0)
            if tf:
                idf = math.log1p((n - dfs[word] + 0.5) / (dfs[word] + 0.5))
                total += idf * (tf * 2.2) / (tf + 1.2 * length_norm)
        score.append(total)
    return score


def _weights_sha(module) -> str:
    h = hashlib.sha256(b'hepta.hdsi.g5.low-rank-head.fp32.v1\0')
    for key, tensor in sorted(module.state_dict().items()):
        h.update(key.encode() + b'\0')
        h.update(tensor.detach().cpu().contiguous().numpy().astype('<f4', copy=False).tobytes())
    return h.hexdigest()


def train_rank8(records: list[dict], features: dict, *, shuffled: bool):
    import torch
    import torch.nn.functional as F
    torch.manual_seed(SEED)
    A = torch.nn.Parameter(torch.randn(384, RANK, dtype=torch.float32) * 0.05)
    B = torch.nn.Parameter(torch.randn(384, RANK, dtype=torch.float32) * 0.05)
    parameters = torch.nn.ParameterDict({'a': A, 'b': B})
    before = _weights_sha(parameters)
    optimizer = torch.optim.AdamW(parameters.parameters(), lr=0.005, weight_decay=0.0001)
    prepared = []
    for item in records:
        if item['split'] != 'TRAIN':
            continue
        docs = item['docs']
        bank = {d['id']: i for i, d in enumerate(docs)}
        indices = []
        for q in item['questions']:
            pos = sorted({bank[i] for i in q['train_support'] if i in bank})
            if shuffled and pos:
                # Same number of fake supervised positives from the SAME source root.
                # Precommitted SHA shift never consults HELD labels or evaluations.
                shift = 1 + int(sha((item['root'] + '\0' + q['id']).encode())[:8], 16) % (DOCS - 1)
                pos = sorted({(j + shift) % DOCS for j in pos})
            indices.append(pos)
        qmat, dmat = features[item['root']]
        prepared.append((qmat, dmat, indices))
    supported = sum(bool(p) for _, _, indices in prepared for p in indices)
    must(supported > 0, 'no actually supervised TRAIN source support')
    started = time.perf_counter()
    for _ in range(STEPS):
        optimizer.zero_grad(set_to_none=True)
        losses = []
        for qmat, dmat, positives in prepared:
            # Frozen original backbone; only two small rank-8 matrices learn.
            base = qmat @ dmat.T
            score = base + 8.0 * ((qmat @ A) @ (dmat @ B).T)
            for idx, pos in enumerate(positives):
                if pos:
                    losses.append(torch.logsumexp(score[idx], dim=-1)
                                  - torch.logsumexp(score[idx, pos], dim=-1))
        loss = torch.stack(losses).mean()
        must(bool(torch.isfinite(loss).item()), 'non-finite genuine SGD loss')
        loss.backward()
        torch.nn.utils.clip_grad_norm_(parameters.parameters(), 1.0)
        optimizer.step()
    seconds = time.perf_counter() - started
    after = _weights_sha(parameters)
    must(before != after, 'no actual low-rank gradient learning')
    return parameters, {'initial_sha': before, 'trained_sha': after, 'steps': STEPS,
                        'train_supported': supported,
                        'parameters': sum(t.numel() for t in parameters.parameters()),
                        'training_elapsed_wall_seconds': seconds,
                        'training_loss_final': float(loss.item())}


def produce(root: Path, packet: dict) -> dict:
    # This admission check is deliberately before importing any optional model
    # runtime. Source-only CI has no Torch; it must still reject exposed gold.
    verify_packet(packet)
    must(not (root/'locomo.json').exists() and not (root/'reader').exists(),
         'untrusted model runner can access raw original QA/Reader')
    verified_encoder_only(root)
    import torch
    import resource
    torch.set_num_threads(1)
    started, cpu_started = time.perf_counter(), time.process_time()
    enc = BatchedMiniLM(root)
    # Separate feature-cache roots prevent cross-root aliasing in the research reference.
    features, raw_vectors, physical = {}, {}, {}
    preproc = sha(b'hepta.hdsi.g5.original-minilm-384d-mean-unit.wordpiece-v1')
    for source in packet['roots']:
        r = source['root']
        scope = Scope('original-' + r, 'evidence-head-p0', 1, 0,
                      sha(('frozen-g5-scope:' + r).encode()),
                      CHECKSUMS['encoder/model.safetensors'], preproc)
        bus = SharedFeatureBus(384, lambda payload, modality: enc.encode(payload.decode('utf-8')),
                               lambda b: b.scope == scope and b.approved_use == 'original-source-study',
                               batch_encode=enc.encode_batch)
        material = source['docs'] + source['questions']
        borrows = [Borrow(scope, 'text', z['text'].encode(),
                          'source-' + str(i), 'original-source-study')
                   for i, z in enumerate(material)]
        prev = enc.calls
        receipts = bus.fanout(borrows)
        must(enc.calls - prev == bus.physical_calls
             and 1 <= bus.physical_calls <= DOCS + QUESTIONS, 'unaccounted real Encoder forwards')
        x = torch.tensor([o.values for o in receipts], dtype=torch.float32)
        must(tuple(x.shape) == (DOCS + QUESTIONS, 384), 'bad original pretrained width')
        features[r] = (x[DOCS:], x[:DOCS])
        raw_vectors[r] = [v.key for v in receipts]
        print('g5_encoded_original_root', r, 'calls', bus.physical_calls, 'batches', enc.actual_batches, 'wall_sec', round(time.perf_counter()-started, 3), flush=True)
        physical[r] = {'actual_completed_forward_sequences': enc.calls - prev,
                       'logical_fanout_borrows': len(borrows),
                       'unique_feature_keys': len(set(raw_vectors[r])),
                       'root_split': source['split']}
    fit_start = time.perf_counter()
    print('g5_completed_all_original_encoder_forwards', enc.calls, 'wall_sec', round(time.perf_counter()-started,3),flush=True)
    learned, trained = train_rank8(packet['roots'], features, shuffled=False)
    print('g5_trained_head',trained['train_supported'], 'elapsed',round(time.perf_counter()-started,3),flush=True)
    sham, sham_trained = train_rank8(packet['roots'], features, shuffled=True)
    print('g5_shuffled_head_done',round(time.perf_counter()-started,3),flush=True)
    model_fit_wall = time.perf_counter() - fit_start
    outputs = []
    with torch.inference_mode():
        for source in packet['roots']:
            if source['split'] != 'HELD':
                continue
            root_id = source['root']
            qvec, dvec = features[root_id]
            cos = (qvec @ dvec.T).tolist()
            base = qvec @ dvec.T
            learned_scores = (base + 8 * (qvec @ learned['a']) @ (dvec @ learned['b']).T).tolist()
            sham_scores = (base + 8 * (qvec @ sham['a']) @ (dvec @ sham['b']).T).tolist()
            shuffle_ix = [(i + 1) % QUESTIONS for i in range(QUESTIONS)]
            shuffled_scores = (qvec[shuffle_ix] @ dvec.T
                               + 8 * (qvec[shuffle_ix] @ learned['a']) @ (dvec @ learned['b']).T).tolist()
            # Entirely feature-blinded lesion, rank8 weights stay unchanged.
            # Identical scores -> deterministic source-index ranking, not semantic inference.
            zero_scores = [0.0] * DOCS
            for i, q in enumerate(source['questions']):
                b = bm25(q['text'], [d['text'] for d in source['docs']])
                scores = {'bm25': b, 'cosine': cos[i], 'rank8': learned_scores[i],
                          'sham_rank8': sham_scores[i], 'zero_features': zero_scores,
                          'shuffled_question': shuffled_scores[i]}
                order = {}
                for arm, nums in scores.items():
                    must(len(nums) == DOCS and all(math.isfinite(float(x)) for x in nums),
                         'bad evaluation scores')
                    rank = sorted(range(DOCS), key=lambda j: (-float(nums[j]), source['docs'][j]['id']))
                    order[arm] = [source['docs'][j]['id'] for j in rank]
                outputs.append({'root': root_id, 'qid': q['id'],
                                'question_sha': q['text_sha'], 'ranks': order})
    print('g5_held_scores_done',round(time.perf_counter()-started,3),flush=True)
    raw_count = sum(z['actual_completed_forward_sequences'] for z in physical.values())
    must(raw_count == enc.calls and enc.calls > 0, 'forward costs not conserved')
    receipt = {'schema': RUN_SCHEMA, 'source_digest': packet['digest'],
               'model_sha': CHECKSUMS['encoder/model.safetensors'],
               'source_sha': CHECKSUMS['locomo.json'], 'training': trained,
               'shuffled_supervision_training': sham_trained,
               'roots': physical, 'actual_full_encoder_forward_sequences': enc.calls,
               'encoder_token_positions': enc.tokens,
               'actual_batched_model_calls': enc.actual_batches,
               'original_hidden_dimension': 384,
               'held_predictions': outputs,
               'cost': {'elapsed_wall_seconds': time.perf_counter() - started,
                        'elapsed_cpu_seconds': time.process_time() - cpu_started,
                        'head_fit_wall_seconds': model_fit_wall,
                        'maxrss_bytes_unattested': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                        'energy_joules': None, 'target_host_p99_ms': None},
               'original_model_forward': True, 'independent_human_answer_scored': False,
               'future_generalization_verified': False, 'ndu_incremental_utility_verified': False,
               'source_family_holdout_verified': True, 'production_authorized': False,
               'disposition': 'HOLD_NO_GO'}
    return _sealed(receipt, 'hepta.hdsi.g5.physical-prelabel')


def read_small_json(path: Path, limit: int) -> dict:
    must(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= limit,
         'unsafe source envelope')
    return json.loads(path.read_bytes(), object_pairs_hook=_unique_pairs)


def write_new(path: Path, data: dict) -> None:
    must(not path.is_symlink() and not path.exists(), 'create-only immutable evidence')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, 'wb') as w:
            w.write(canon(data) + b'\n')
            w.flush()
            os.fsync(w.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='mode', required=True)
    prep = sub.add_parser('prepare'); prep.add_argument('--locomo', type=Path, required=True)
    prep.add_argument('--output', type=Path, required=True)
    infer = sub.add_parser('infer'); infer.add_argument('--root', type=Path, required=True)
    infer.add_argument('--source', type=Path, required=True)
    infer.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.mode == 'prepare':
        out = source_packet(args.locomo.read_bytes())
    else:
        out = produce(args.root, read_small_json(args.source, 2_000_000))
    write_new(args.output, out)
    print(canon({'sha256': sha(canon(out) + b'\n'), 'mode': args.mode,
                 'production_authorized': False}).decode())

if __name__ == '__main__':
    main()
