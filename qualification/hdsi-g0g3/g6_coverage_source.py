"""Source-only, sealed whole-evidence LoCoMo handoff; TRAIN support only.

No HELD publisher labels, answers, or evidence addresses cross the model-worker
boundary. Whole-corpus text is public but never committed into this repository.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from g5_original_evidence import source_packet, read_publisher, verify_packet
from real_minilm_reference import CHECKSUMS

SCHEMA = 'hepta.hdsi.g6.coverage-first-source.v1'
DOMAIN = b'hepta.hdsi.g6.source.v1\0'
HELD = ('conv-47', 'conv-48', 'conv-49', 'conv-50')
TRAIN = ('conv-26', 'conv-30', 'conv-41', 'conv-42', 'conv-43', 'conv-44')
SCORES = ('bm25_full', 'bm25_64', 'cosine_64', 'rank8_64', 'sham_64', 'rrf_64')


def deny(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def strict_pairs(pairs):
    out = {}
    for k, v in pairs:
        deny(k not in out, 'duplicate JSON key')
        out[k] = v
    return out


def full_docs(record: dict) -> list[dict]:
    """Publisher dialogue IDs; no selection based on answer/evidence labels."""
    docs = {}
    conversation = record['conversation']
    deny(type(conversation) is dict, 'wrong original conversation')
    for section, turns in conversation.items():
        if not section.startswith('session_') or type(turns) is not list:
            continue
        for row in turns:
            if type(row) is not dict:
                continue
            name, content, person = row.get('dia_id'), row.get('text'), row.get('speaker')
            if (type(name) is not str or re.fullmatch('D[0-9]+:[0-9]+', name) is None
                    or type(content) is not str or not content.strip()
                    or len(content.encode('utf-8')) > 8192
                    or type(person) is not str or not person or len(person) > 80):
                continue
            text = person + ': ' + content
            deny(name not in docs, 'duplicate source dialogue address')
            docs[name] = {'id': name, 'text': text, 'text_sha': sha(text.encode('utf-8'))}
    deny(300 <= len(docs) <= 2000, 'original full evidence corpus size')
    return sorted(docs.values(), key=lambda d: d['id'])


def build(raw: bytes) -> dict:
    deny(len(raw) < 4_000_000 and sha(raw) == CHECKSUMS['locomo.json'], 'publisher original SHA')
    g5 = source_packet(raw)
    verify_packet(g5)
    originals = {r['sample_id']: r for r in read_publisher(raw)}
    roots = []
    for item in g5['roots']:
        if item['root'] in TRAIN:
            roots.append(item)
        else:
            deny(item['root'] in HELD and item['split'] == 'HELD', 'source root split')
            # Retain exactly the same 24 unlabelled questions as frozen G5.
            roots.append({'root': item['root'], 'split': 'HELD',
                          'docs': full_docs(originals[item['root']]),
                          'questions': item['questions']})
    packet = {'schema': SCHEMA, 'original_sha': CHECKSUMS['locomo.json'],
              'model_sha': CHECKSUMS['encoder/model.safetensors'],
              'original_g5_packet_digest': g5['digest'],
              'train_documents_per_root': 256, 'candidate_documents': 'all_held_original_dialogues',
              'questions_per_root': 24, 'rerank_shortlist': 64,
              'roots': roots, 'research_only': True, 'production_authorized': False,
              'disposition': 'HOLD_NO_GO'}
    packet['digest'] = sha(DOMAIN + canonical(packet))
    validate(packet)
    return packet


def validate(packet: dict) -> None:
    fields = {'schema', 'original_sha', 'model_sha', 'original_g5_packet_digest',
              'train_documents_per_root', 'candidate_documents', 'questions_per_root',
              'rerank_shortlist', 'roots', 'research_only', 'production_authorized',
              'disposition', 'digest'}
    deny(type(packet) is dict and set(packet) == fields, 'source envelope keys')
    deny(packet['schema'] == SCHEMA and packet['original_sha'] == CHECKSUMS['locomo.json']
         and packet['model_sha'] == CHECKSUMS['encoder/model.safetensors']
         and packet['train_documents_per_root'] == 256
         and packet['candidate_documents'] == 'all_held_original_dialogues'
         and packet['questions_per_root'] == 24 and packet['rerank_shortlist'] == 64
         and packet['research_only'] is True and packet['production_authorized'] is False
         and packet['disposition'] == 'HOLD_NO_GO', 'false source/authority')
    deny(type(packet['digest']) is str and packet['digest'] ==
         sha(DOMAIN + canonical({k: v for k, v in packet.items() if k != 'digest'})), 'source changed')
    deny(type(packet['roots']) is list and len(packet['roots']) == 10, 'missing roots')
    deny(type(packet['original_g5_packet_digest']) is str
         and re.fullmatch('[0-9a-f]{64}', packet['original_g5_packet_digest']) is not None,
         'unbound original G5 packet')
    deny([x['root'] for x in packet['roots']] == sorted(TRAIN + HELD), 'root ordering')
    seen_questions = set()
    for r in packet['roots']:
        name = r['root']
        expected_split = 'TRAIN' if name in TRAIN else 'HELD'
        deny(type(r) is dict and set(r) == {'root','split','docs','questions'}
             and r['split'] == expected_split, 'bad root')
        deny(type(r['docs']) is list and (len(r['docs']) == 256 if name in TRAIN else 300 <= len(r['docs']) <= 2000)
             and type(r['questions']) is list and len(r['questions']) == 24, 'root bounds')
        doc_ids = set()
        for d in r['docs']:
            deny(type(d) is dict and set(d) == {'id','text','text_sha'}
                 and type(d['id']) is str and d['id'] not in doc_ids
                 and type(d['text']) is str and sha(d['text'].encode()) == d['text_sha'], 'doc source identity')
            doc_ids.add(d['id'])
        deny(len(doc_ids) == len(r['docs']), 'duplicate source documents')
        for q in r['questions']:
            allowed = {'id','text','text_sha','train_support'} if name in TRAIN else {'id','text','text_sha'}
            deny(type(q) is dict and set(q) == allowed and type(q['id']) is str
                 and (name,q['id']) not in seen_questions
                 and type(q['text']) is str and sha(q['text'].encode()) == q['text_sha'],
                 'question identity or HELD gold leak')
            seen_questions.add((name, q['id']))
            if name in TRAIN:
                deny(type(q['train_support']) is list and len(q['train_support']) < 30
                     and all(type(k) is str for k in q['train_support']), 'TRAIN evidence shape')


def write_new(path: Path, obj: dict) -> None:
    deny(not path.exists() and not path.is_symlink(), 'no overwriting or symlink')
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical(obj) + b'\n'
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'wb') as fh:
        fh.write(raw)
        fh.flush()
        os.fsync(fh.fileno())


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--original', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    packet = build(args.original.read_bytes())
    write_new(args.output, packet)
    print(json.dumps({'source_digest':packet['digest'], 'held_gold_exported': False}, sort_keys=True))

if __name__ == '__main__':
    main()
