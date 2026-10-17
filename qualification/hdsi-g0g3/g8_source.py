"""G8 full-corpus source-owner. Only named TRAIN gold crosses the model boundary.

G5's preselected questions are immutable. The corpus is now the *full* original
utterance set at both TRAIN and HELD, removing G7's asymmetric coverage regime.
No production authority; source owner deletes original raw QA before handoff.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from g5_original_evidence import read_publisher
from g6_coverage_source import build as g6_build, full_docs, sha, canonical, TRAIN, HELD
from real_minilm_reference import CHECKSUMS

SCHEMA = 'hepta.hdsi.g8.full-source-label-blind.v1'
DOM = b'hepta.hdsi.g8.full-original-source.v1\0'


def need(ok, why):
    if ok is not True:
        raise ValueError(why)


def pack(value):
    return hashlib.sha256(DOM + canonical(value)).hexdigest()


def build(raw: bytes) -> dict:
    original = {r['sample_id']: r for r in read_publisher(raw)}
    old = g6_build(raw)
    roots = []
    for row in old['roots']:
        full = full_docs(original[row['root']])
        if row['split'] == 'TRAIN':
            known = {d['id'] for d in full}
            need(all(set(q['train_support']) <= known and bool(q['train_support']) for q in row['questions']),
                 'original TRAIN support must be present in complete transcript')
        roots.append({'root': row['root'], 'split': row['split'],
                      'docs': full, 'questions': row['questions']})
    p = {'schema': SCHEMA, 'original_sha': CHECKSUMS['locomo.json'],
         'model_sha': CHECKSUMS['encoder/model.safetensors'],
         'predecessor_g6_digest': old['digest'],
         'corpus_mode': 'complete_original_utterances_in_both_train_and_held',
         'question_roster': 'frozen_G5_24_per_original_source',
         'shortlist_size': 64, 'roots': roots,
         'historically_public_not_prospective': True, 'held_gold_exported': False,
         'research_only': True, 'production_authorized': False, 'disposition': 'HOLD_NO_GO'}
    p['digest'] = pack(p)
    validate(p)
    return p


def validate(p: dict) -> None:
    need(type(p) is dict and set(p) == {'schema', 'original_sha', 'model_sha',
         'predecessor_g6_digest', 'corpus_mode', 'question_roster', 'shortlist_size', 'roots',
         'historically_public_not_prospective', 'held_gold_exported', 'research_only',
         'production_authorized', 'disposition', 'digest'}, 'unknown source keys')
    need(p['schema'] == SCHEMA and p['original_sha'] == CHECKSUMS['locomo.json']
         and p['model_sha'] == CHECKSUMS['encoder/model.safetensors']
         and p['corpus_mode'] == 'complete_original_utterances_in_both_train_and_held'
         and p['question_roster'] == 'frozen_G5_24_per_original_source'
         and p['shortlist_size'] == 64
         and p['historically_public_not_prospective'] is True
         and p['held_gold_exported'] is False
         and p['research_only'] is True and p['production_authorized'] is False
         and p['disposition'] == 'HOLD_NO_GO', 'false source/scope/authority')
    need(type(p['predecessor_g6_digest']) is str and len(p['predecessor_g6_digest']) == 64,
         'predecessor missing')
    need(p['digest'] == pack({k: v for k, v in p.items() if k != 'digest'}), 'source digest drift')
    need(type(p['roots']) is list and [r['root'] for r in p['roots']] == sorted(TRAIN + HELD),
         'unexpected original roots')
    seen = set()
    for r in p['roots']:
        name = r['root']
        need(type(r) is dict and set(r) == {'root', 'split', 'docs', 'questions'}
             and r['split'] == ('TRAIN' if name in TRAIN else 'HELD'), 'source root shape')
        need(type(r['docs']) is list and 300 <= len(r['docs']) <= 2000
             and type(r['questions']) is list and len(r['questions']) == 24,
             'complete source cardinality')
        dids = set()
        for d in r['docs']:
            need(type(d) is dict and set(d) == {'id', 'text', 'text_sha'}
                 and type(d['id']) is str and d['id'] not in dids
                 and type(d['text']) is str and sha(d['text'].encode()) == d['text_sha'],
                 'document source drift')
            dids.add(d['id'])
        need([d['id'] for d in r['docs']] == sorted(dids), 'original document ID order')
        for q in r['questions']:
            legal = {'id', 'text', 'text_sha', 'train_support'} if name in TRAIN else {'id', 'text', 'text_sha'}
            need(type(q) is dict and set(q) == legal
                 and (name, q['id']) not in seen and sha(q['text'].encode()) == q['text_sha'],
                 'duplicate question or leaked held label')
            seen.add((name, q['id']))
            if name in TRAIN:
                need(type(q['train_support']) is list and len(q['train_support']) <= 29
                     and bool(set(q['train_support']) & dids), 'TRAIN support not in full candidate domain')


def main() -> None:
    import argparse
    from g6_coverage_source import write_new
    pa = argparse.ArgumentParser()
    pa.add_argument('--original', type=Path, required=True)
    pa.add_argument('--output', type=Path, required=True)
    a = pa.parse_args()
    source = build(a.original.read_bytes())
    write_new(a.output, source)
    print(json.dumps({'full_train_roots': 6, 'full_held_roots': 4,
                      'source_digest': source['digest'], 'held_gold_exported': False}))

if __name__ == '__main__':
    main()
