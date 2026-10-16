"""Original BANKING77 second-family verification; research only and no deployment.

Reconstruct source/labels from exact original pinned PolyAI CSV bytes, never
from the producer's prediction labels. Independent scores and harm census are
strictly *descriptive* of a different ModernBERT task/Head study. Not a V20
mmBERT/fixed4 generalization or prospective evaluation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import unicodedata
from zipfile import ZipFile

BANKING_ZIP_SHA = 'fd89f174057d98bd2d4f03447d5d5dd9372723e70128ccdf2dcbe73f67a0a03a'
SOURCE_REVISION = '57ec275d8078af65b7731c2a98be812d844a6d6b'
TRAIN_CSV_SHA = 'b06e26ac675513959a63135f11b94ea7786ed02da65db93a5650d8838cbc664b'
TEST_CSV_SHA = 'd12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d'
ORIGINAL_AGNEWS_FEATURE_SHA = 'e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490'
SCHEMA = 'hepta.stem.v21.banking77-second-family-original-audit.v1'
INTENTS = ('card_arrival', 'cash_withdrawal_not_recognised', 'exchange_rate', 'lost_or_stolen_phone')
ARMS = ('dense16', 'sparse16_top2')


class Invalid(ValueError):
    pass


def require(value, reason):
    if not value:
        raise Invalid(reason)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def text_key(s):
    return ' '.join(unicodedata.normalize('NFKC', s).casefold().split())


def parse_csv(b):
    require(isinstance(b, bytes) and 0 < len(b) <= 2_000_000, 'bounded original CSV bytes')
    try:
        reader = csv.DictReader(io.StringIO(b.decode('utf-8')))
        require(reader.fieldnames == ['text', 'category'], 'publisher text/category schema changed')
        rows, duplicate_count = {}, 0
        for i, row in enumerate(reader):
            require(i < 20000 and set(row) == {'text', 'category'} and
                    all(isinstance(v, str) and v for v in row.values()), 'invalid publisher row')
            text, category = row['text'], row['category']
            key = text_key(text)
            require(0 < len(text.encode()) <= 4096 and bool(key), 'invalid publisher utterance')
            if key in rows:
                require(rows[key]['category'] == category, 'conflicting publisher label')
                duplicate_count += 1
                text = min(text, rows[key]['text'])
            rows[key] = {'text': text, 'category': category}
        require(len(rows) > 0, 'original CSV had no cases')
        return rows, duplicate_count
    except (UnicodeError, csv.Error) as exc:
        raise Invalid('invalid original CSV encoding/parser') from exc


def reconstruct(train_bytes, test_bytes):
    """Independent original four-intent source selector, no model, logits or labels from ZIP."""
    require(sha(train_bytes) == TRAIN_CSV_SHA and sha(test_bytes) == TEST_CSV_SHA,
            'publisher CSV byte SHA does not match original exact immutable dataset')
    fit_source, train_duplicates = parse_csv(train_bytes)
    held_source, test_duplicates = parse_csv(test_bytes)
    overlap = set(fit_source) & set(held_source)
    inputs = {'schema': 'hepta.banking77-four-intent-inputs.v1',
              'intents': list(INTENTS), 'fit': [], 'heldout': []}
    selected = {'fit': [], 'heldout': []}
    pools = {'fit': {}, 'heldout': {}}
    answer_rows = []
    for split, source in (('fit', fit_source), ('heldout', held_source)):
        for label, cat in enumerate(INTENTS):
            keys = [key for key, row in source.items() if row['category'] == cat
                    and (split == 'fit' or key not in fit_source)]
            keys.sort(key=lambda key: sha(('hepta-banking77-subset-v1\0' + key).encode()))
            pools[split][cat] = len(keys)
            cap = 16 if split == 'fit' else 8
            require(len(keys) >= cap, 'original source category below registered denominator')
            for key in keys[:cap]:
                identity = split + ':' + sha(key.encode())
                row = {'id': identity, 'text': source[key]['text']}
                if split == 'fit':
                    row['label'] = label
                else:
                    answer_rows.append({'id': identity, 'label': label})
                selected[split].append(identity)
                inputs[split].append(row)
    input_id = sha(canonical(inputs))
    selection = {'schema': 'hepta.banking77-subset-selection.v1',
                 'input_id': input_id,
                 'raw_sha256': {'train': TRAIN_CSV_SHA, 'test': TEST_CSV_SHA},
                 'duplicate_rows': {'train': train_duplicates, 'test': test_duplicates},
                 'excluded_test_overlap': len(overlap), 'pool_sizes': pools,
                 'selected_ids': selected, 'task_subset_not_full_benchmark': True}
    return selection, answer_rows


def _strict_json(b):
    def no_dupe(pairs):
        out = {}
        for k, v in pairs:
            require(k not in out, 'duplicate original JSON key')
            out[k] = v
        return out
    return json.loads(b, object_pairs_hook=no_dupe,
                      parse_constant=lambda _: (_ for _ in ()).throw(Invalid('nonfinite original JSON')))


def evaluate(logits, labels):
    require(isinstance(logits, list) and len(logits) == len(labels) == 32,
            '32 original four-intent heldout predictions required')
    guesses = []
    briers = []
    nlls = []
    for z, y in zip(logits, labels):
        require(isinstance(z, list) and len(z) == 4 and all(type(x) in (int, float)
                and math.isfinite(x) for x in z) and type(y) is int and 0 <= y < 4,
                'bounded original finite four-logit prediction')
        mx = max(z)
        e = [math.exp(v - mx) for v in z]
        total = sum(e)
        p = [v / total for v in e]
        briers.append(sum((p[j] - (1 if j == y else 0))**2 for j in range(4)))
        nlls.append(-math.log(p[y]))
        guesses.append(max(range(4), key=lambda j: p[j]))
    correct = sum(int(a == y) for a, y in zip(guesses, labels))
    return {'count': len(labels), 'correct': correct, 'accuracy': correct / len(labels),
            'brier': sum(briers) / len(labels), 'mean_nll': sum(nlls) / len(labels),
            'guesses': guesses}


def paired(a, b, labels):
    require(len(a) == len(b) == len(labels) == 32, '32 exact paired source identities required')
    return {'rescues': sum(x != y and z == y for x, z, y in zip(a, b, labels)),
            'harms': sum(x == y and z != y for x, z, y in zip(a, b, labels)),
            'ties': sum((x == y) == (z == y) for x, z, y in zip(a, b, labels))}


def original_audit(archive, train_csv, test_csv):
    archive = Path(archive)
    train_csv = Path(train_csv)
    test_csv = Path(test_csv)
    for p, max_size in ((archive, 5_000_000), (train_csv, 2_000_000), (test_csv, 2_000_000)):
        require(p.is_file() and not p.is_symlink() and 0 < p.stat().st_size < max_size,
                'bounded regular non-symlink original material required')
    require(sha(archive.read_bytes()) == BANKING_ZIP_SHA, 'untrusted original experiment archive')
    selection, truth = reconstruct(train_csv.read_bytes(), test_csv.read_bytes())
    ids = [r['id'] for r in truth]
    labels = [r['label'] for r in truth]
    require(len(ids) == len(set(ids)) == 32, 'unambiguous independent publisher label identities required')
    with ZipFile(archive) as z:
        names = z.namelist()
        require(len(names) == len(set(names)) and len(names) <= 28,
                'bounded original ZIP with no repeated member names required')
        registered = _strict_json(z.read('public-cell-learning/selection.json'))
        scores = _strict_json(z.read('public-cell-learning/scores.json'))
        source = _strict_json(z.read('public-cell-learning/data/SOURCE.json'))
        material = _strict_json(z.read('public-cell-learning/data/MATERIAL.json'))
        require(registered == selection, 'original independent publisher sample identity changed')
        require(source.get('revision') == SOURCE_REVISION and material.get('source') == source
                and material.get('sha256', {}).get('banking_data/test.csv') == TEST_CSV_SHA
                and material.get('sha256', {}).get('banking_data/train.csv') == TRAIN_CSV_SHA,
                'original publisher lineage did not match')
        require(scores.get('all_arms_completed') is True and scores.get('production_authorized') is False
                and scores.get('observer_independence_established') is False
                and scores.get('full_system_cost_measured') is False
                and scores.get('fitting_examples') == 64 and scores.get('heldout_examples') == 32
                and scores.get('dataset_revision') == SOURCE_REVISION,
                'original negative scientific assertions missing')
        res = {}
        private_guesses = {}
        for arm in ARMS:
            prediction = _strict_json(z.read(f'public-cell-learning/trial/{arm}/predictions.json'))
            execution = _strict_json(z.read(f'public-cell-learning/trial/{arm}/execution.json'))
            require(isinstance(prediction, list) and len(prediction) == 32 and
                    [r.get('id') for r in prediction] == ids and
                    execution.get('heldout_labels_loaded') is False and
                    execution.get('production_authorized') is False and
                    execution.get('shared_encoder_sha256') == scores['scores'][arm]['execution']['shared_encoder_sha256'],
                    'source identity, shared Encoder or physical execution mismatched')
            arm_metrics = {}
            for phase in ('before', 'after'):
                metric = evaluate([r.get(phase+'_logits') for r in prediction], labels)
                claimed = scores['scores'][arm][phase]
                require(claimed.get('count') == 32 and
                        abs(claimed['accuracy'] - metric['accuracy']) < 1e-11 and
                        abs(claimed['brier'] - metric['brier']) < 1e-11 and
                        abs(claimed['mean_nll'] - metric['mean_nll']) < 1e-11,
                        'original heldout source-bound score mismatch')
                arm_metrics[phase] = {k: metric[k] for k in ('count','correct','accuracy','brier','mean_nll')}
                private_guesses[(arm, phase)] = metric['guesses']
            arm_metrics['within_arm_change'] = paired(private_guesses[(arm, 'before')],
                                                      private_guesses[(arm, 'after')], labels)
            res[arm] = arm_metrics
        cross = paired(private_guesses[('sparse16_top2','after')],
                       private_guesses[('dense16','after')], labels)
    return {'schema': SCHEMA, 'banking_original_archive_sha256': BANKING_ZIP_SHA,
            'original_train_csv_sha256': TRAIN_CSV_SHA, 'original_test_csv_sha256': TEST_CSV_SHA,
            'original_revision': SOURCE_REVISION, 'original_selected_heldout_cases': len(labels),
            'independent_public_publisher_label_roster_reconstructed': True,
            'modernbert_banking77_original_score_recount': res,
            'dense_over_sparse_pairwise': cross,
            'comparator_agnews_model': 'mmBERT-small',
            'banking77_model': 'ModernBERT-base',
            'different_model_and_task': True,
            'same_stem_or_budget_cross_family_comparison_verified': False,
            'source_family_count_in_pair': 2,
            'independent_future_calendar_windows': 0,
            'prospective_head_learning_gain': False,
            'independent_model_issuer_signature': False,
            'full_equal_lifecycle_cost_comparison': False,
            'independent_human_task_success_verified': False,
            'automatic_cell_split_authorized': False,
            'model_selection_authorized': False,
            'final_use_authorized': False,
            'production_authorized': False,
            'decision': 'SECOND_FAMILY_DESCRIPTIVE_NOT_CROSS_MODEL_TRANSFER'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--train-csv', type=Path, required=True)
    p.add_argument('--test-csv', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    require(not a.output.exists() and a.output.parent.is_dir() and not a.output.parent.is_symlink(),
            'create-only research output required')
    result = original_audit(a.archive, a.train_csv, a.test_csv)
    with a.output.open('xb') as f:
        f.write(json.dumps(result, indent=2, sort_keys=True, allow_nan=False).encode())
        f.flush()
        os.fsync(f.fileno())
    print(json.dumps({'decision': result['decision'], 'arms': result['modernbert_banking77_original_score_recount'],
                      'different_model_and_task': result['different_model_and_task']}, sort_keys=True))


if __name__ == '__main__':
    main()
