"""Independent source-bound evidence-ID audit; no retrieval or pretrained model.

Reads the *original* SHA-pinned LoCoMo source only AFTER an unchanged, complete
prediction journal and seal exist. Never loads a private derived label cache.
Statistical output is exploratory; dialogue families are not independently
human-authenticated clusters and may be correlated.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import product
from pathlib import Path
import hashlib
import json
import random
import re
import sys

DATASET_SHA256 = '79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
RUN_SCHEMA = 'hepta.memory-meta-graph-source-trial.research.v1'
PUBLIC_SCHEMA = 'hepta.associative-question-conditioned-fullsource.research.v1'
ARMS = ('bm25', 'temporal_window', 'graph', 'shuffled', 'premise_deleted')
MAX_FILE = 8 * 1024 * 1024


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError('regular source-only file required')
    with path.open('rb') as f:
        raw = f.read(MAX_FILE + 1)
    if not raw or len(raw) > MAX_FILE:
        raise ValueError('invalid input size')
    return raw


def strict(raw):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError('duplicate original/journal JSON key')
            result[k] = v
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def audit(original_path, public_dir, run_dir, review_path=None):
    original_raw = read(original_path)
    if digest(original_raw) != DATASET_SHA256:
        raise ValueError('original source hash mismatch')
    original = strict(original_raw)
    if not isinstance(original, list) or len(original) != 10:
        raise ValueError('original source family count mismatch')
    roots = {v['sample_id']: v for v in original}
    if len(roots) != 10:
        raise ValueError('repeated original root')

    folder = Path(public_dir)
    if (folder / 'private.json').exists() or (folder / 'private.json').is_symlink():
        raise ValueError('public input includes private labels')
    public_raw = read(folder / 'public.json')
    public = strict(public_raw)
    manifest = strict(read(folder / 'manifest.json'))
    if (manifest.get('public_sha256') != digest(public_raw)
        or manifest.get('dataset_sha256') != DATASET_SHA256
        or manifest.get('schema') != PUBLIC_SCHEMA
        or manifest.get('production_accepted') is not False
        or public.get('schema') != PUBLIC_SCHEMA
        or public.get('dataset_sha256') != DATASET_SHA256
        or len(public.get('families', [])) != 10):
        raise ValueError('public manifest/source pin failure')

    source_ids = {}
    question_ids = {}
    for group in public['families']:
        family = group['family']
        if family not in roots or family in source_ids:
            raise ValueError('unknown or duplicate original family')
        record = roots[family]
        observed = {}
        for session, utterances in record['conversation'].items():
            if not re.fullmatch(r'session_\d+', session):
                continue
            for utterance in utterances:
                did = utterance['dia_id']
                if did in observed:
                    raise ValueError('duplicate original dialogue ID')
                observed[did] = (session, utterance['speaker'], utterance['text'])
        available = set()
        for doc in group['sources']:
            did = doc['id']
            if (did in available or did not in observed
                or observed[did] != (doc['session'], doc['speaker'], doc['text'])):
                raise ValueError('public source is not exact original dialogue')
            available.add(did)
        source_ids[family] = available
        for question in group['questions']:
            qid = question['id']
            if qid in question_ids or not re.fullmatch(re.escape(family) + r'/q\d{4}', qid):
                raise ValueError('duplicate/invalid original question ID')
            index = int(qid.rsplit('q', 1)[1])
            qa = record['qa'][index]
            if question['text'] != qa['question'] or 'evidence' in question:
                raise ValueError('question text differs from original or contains gold')
            evidence = qa.get('evidence')
            good = (isinstance(evidence, list) and all(
                isinstance(x, str) and re.fullmatch(r'D\d+:\d+', x) for x in evidence))
            question_ids[qid] = (family, set(evidence) if good else None)
    if len(question_ids) != 240 or sum(map(len, source_ids.values())) != 5804:
        raise ValueError('unregistered 240-question / 5804-source catalogue')

    journal_raw = read(Path(run_dir) / 'journal.json')
    seal = strict(read(Path(run_dir) / 'seal.json'))
    records = strict(journal_raw)
    if (seal.get('schema') != RUN_SCHEMA or seal.get('public_sha256') != digest(public_raw)
        or seal.get('journal_sha256') != digest(journal_raw)
        or seal.get('count') != 240 or seal.get('arms') != list(ARMS)
        or seal.get('input_labels_visible') is not False
        or seal.get('real_reader_executed') is not False
        or seal.get('production_accepted') is not False
        or not isinstance(records, list) or len(records) != 240):
        raise ValueError('unsealed or incomplete source journal')

    seen, hits = set(), defaultdict(lambda: defaultdict(dict))
    paired_rows = []
    counts = {'positive': 0, 'in_pool': 0, 'unresolved': 0}
    for record in records:
        if not isinstance(record, dict) or set(record) != {'family', 'question_id', 'predictions'}:
            raise ValueError('unexpected journal fields')
        qid, family = record['question_id'], record['family']
        if qid in seen or qid not in question_ids or question_ids[qid][0] != family:
            raise ValueError('repeated or wrong-family journal question')
        seen.add(qid)
        if not isinstance(record['predictions'], dict) or set(record['predictions']) != set(ARMS):
            raise ValueError('unknown or missing evidence ranking arms')
        gold = question_ids[qid][1]
        if gold is None:
            counts['unresolved'] += 1
        elif gold:
            counts['positive'] += 1
            counts['in_pool'] += int(gold <= source_ids[family])
        per_arm = {}
        for arm in ARMS:
            selected = record['predictions'][arm]
            if (not isinstance(selected, list) or len(selected) != 8
                or len(set(selected)) != 8 or not set(selected) <= source_ids[family]):
                raise ValueError('ranked evidence not in original source catalogue')
            if gold is not None and gold:
                hit = int(gold <= set(selected))
                hits[family][arm][qid] = hit
                per_arm[arm] = hit
        if per_arm:
            paired_rows.append((qid, family, per_arm, record['predictions']))
    if seen != set(question_ids) or counts != {'positive': 238, 'in_pool': 224, 'unresolved': 2}:
        raise ValueError('source-evidence denominator drift')
    all_families = sorted(source_ids)
    score = {a: sum(hits[f][a][qid] for f in all_families for qid in hits[f][a])
             for a in ARMS}
    family_score = {f: {a: sum(hits[f][a].values()) for a in ARMS} for f in all_families}
    reference = {'bm25': 107, 'temporal_window': 121, 'graph': 125,
                 'shuffled': 101, 'premise_deleted': 123}
    # Strict comparison to local audit expectation; future changed algorithm
    # must version this experimental result instead of editing historical data.
    if score != reference:
        raise ValueError('frozen original experiment score drift')

    if review_path is not None:
        previous = strict(read(review_path))
        if (previous.get('journal_sha256') != digest(journal_raw)
            or previous.get('public_sha256') != digest(public_raw)
            or {a: previous['by_arm'][a]['complete_top8'] for a in ARMS} != score
            or {f: {a: previous['by_family'][f][a]['complete_top8'] for a in ARMS}
                for f in all_families} != family_score):
            raise ValueError('independent source reviewer does not match first reviewer')

    comparisons = {}
    for control in ('bm25', 'temporal_window', 'shuffled', 'premise_deleted'):
        wins = sum(row[2]['graph'] == 1 and row[2][control] == 0 for row in paired_rows)
        losses = sum(row[2]['graph'] == 0 and row[2][control] == 1 for row in paired_rows)
        changed_sets = sum(set(row[3]['graph']) != set(row[3][control]) for row in paired_rows)
        delta = [family_score[f]['graph'] - family_score[f][control] for f in all_families]
        observed = sum(delta)
        signflip = sum(abs(sum(sign * x for sign, x in zip(signs, delta))) >= abs(observed)
                       for signs in product((-1, 1), repeat=len(delta))) / (2**len(delta))
        # Diagnostic paired *cluster* bootstrap; not a valid independent-source CI.
        rng = random.Random(20261016)
        bootstrap = sorted(sum(rng.choice(delta) for _ in delta) for _ in range(20000))
        comparisons[control] = {
            'total_delta_questions': observed, 'gained_queries': wins,
            'lost_queries': losses, 'differing_top8_sets': changed_sets,
            'family_deltas': dict(zip(all_families, delta)),
            'ten_family_sign_flip_probability_exploratory': signflip,
            'cluster_resample_delta_count_exploratory_95pct': [bootstrap[499], bootstrap[19499]],
        }
    return {'schema': 'hepta.memory-meta-graph-independent-audit.research.v1',
            'original_sha256': digest(original_raw), 'public_sha256': digest(public_raw),
            'journal_sha256': digest(journal_raw), 'dialogue_families': 10,
            'questions': 240, 'source_count': 5804,
            'positive': counts['positive'], 'available_all_sources': counts['in_pool'],
            'unresolved': counts['unresolved'], 'complete_top8_by_arm': score,
            'graph_comparisons': comparisons,
            'reader_executed': False, 'graph_learned': False,
            'source_family_independence_authenticated': False,
            'statistical_superiority_claim': False,
            'valid_citation_entailment_judged': False,
            'lifecycle_cost_matched': False,
            'production_accepted': False}


if __name__ == '__main__':
    if len(sys.argv) not in (4, 5):
        raise SystemExit('usage: ORIGINAL_LOC OMO_PUBLIC_DIR SEALED_RUN [REVIEW_REPORT]')
    print(json.dumps(audit(*sys.argv[1:]), sort_keys=True, indent=2))
