"""Independent original publisher / train-only calibration replay (no V6 producer import).

All score claims are retrospective: original publisher TEST labels were already
inspected in V4 exploratory work. Never selects a Stem or permits FinalUse.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'stem-optimal-v3'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'stem-optimal-v4'))
import stem_hard_charge_review_v3 as original
import cheap_lexical_review_v4 as fixed_review

SCHEMA = 'hepta.stem.charge-lexical-calibration.v6'
ARMS = ('word_12_tfidf_centroid', 'char_345_tfidf_centroid')
GRID = [0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0]
SALT = 'hepta-hard-charge-v6-fixed-four-stratified-folds\\0'
SOURCE_SHA = '3e79b3449f3b63d1f261ae4ad9632ae4cff07262a82c5259a17d040e61929900'
RECEIPT_FIELDS = {'schema', 'source_plan_sha256', 'publisher_revision', 'cohort',
                  'fold_salt', 'stratification', 'temperature_grid', 'fit_folds',
                  'calibration', 'rows', 'cost', 'heldout_label_access', 'future_windows',
                  'independent_source_families', 'production_authorized',
                  'stem_winner_verified', 'disposition', 'authority'}


def must(condition, text):
    if not condition:
        raise ValueError(text)


def id_digest(data):
    return hashlib.sha256(data).hexdigest()


def _tokens(value, arm):
    s = value.casefold()
    if arm == ARMS[0]:
        token = re.findall('[a-z0-9]+', s)
        return token + [token[j] + '\x1f' + token[j + 1]
                        for j in range(len(token) - 1)]
    s = ' '.join(s.split())
    return [s[k:k + n] for n in (3, 4, 5)
            for k in range(max(0, len(s) + 1 - n))]


def _independent_scores(training, evaluated, arm):
    tokens = [Counter(_tokens(row['text'], arm)) for row in training + evaluated]
    df = Counter(key for row in tokens[:len(training)] for key in row.keys())
    must(0 < len(df) <= 100_000, 'independent train-only vocab bound')
    smooth = {key: 1 + math.log((len(training) + 1)/(count + 1))
              for key, count in df.items()}
    embeddings = []
    for bag in tokens:
        row = {key: count*smooth[key] for key, count in bag.items() if key in smooth}
        length = math.sqrt(sum(value ** 2 for value in row.values()))
        embeddings.append({key: v/length for key,v in row.items()} if length else {})
    prototypes = [Counter() for _ in range(4)]
    for j, row in enumerate(training):
        prototypes[row['label']].update(embeddings[j])
    centers = []
    for row in prototypes:
        magnitude = math.sqrt(sum(v**2 for v in row.values()))
        must(magnitude > 0, 'independent training class centroid missing')
        centers.append({key: v/magnitude for key,v in row.items()})
    logits = [[sum(v * p.get(k, 0.0) for k,v in obs.items()) for p in centers]
              for obs in embeddings[len(training):]]
    return logits, len(df)


def _softmax(raw, temp):
    y = [v * temp for v in raw]
    m = max(y)
    exp = [math.exp(value-m) for value in y]
    d = sum(exp)
    return [e/d for e in exp]


def independently_replay(source, receipt):
    must(type(source) is dict and source.get('schema') == 'hepta.stem.charge-stress.source.v3' and
         source.get('source_plan_sha256') == SOURCE_SHA and
         source.get('heldout_labels_excluded') is True and
         source.get('production_authorized') is False and
         len(source.get('train', [])) == 64 and len(source.get('heldout', [])) == 32,
         'different original source cohort')
    must(id_digest(json.dumps({k:v for k,v in source.items() if k != 'source_plan_sha256'},
            sort_keys=True, ensure_ascii=False, allow_nan=False,
            separators=(',',':')).encode('utf-8')) == SOURCE_SHA,
         'unsealed source text/label drift')
    unique=set()
    for split in ('train','heldout'):
        for row in source[split]:
            expected_fields={'case_id','source_sha256','text','label'} if split=='train' else {
                'case_id','source_sha256','text'}
            must(type(row) is dict and set(row) == expected_fields, 'heldout label leakage')
            h=id_digest(row['text'].encode('utf-8'))
            must(row['source_sha256'] == h and row['case_id'] ==
                 ('fit:' if split=='train' else 'heldout:') + h and h not in unique,
                 'source case digest collision or drift')
            unique.add(h)
    must(type(receipt) is dict and set(receipt) == RECEIPT_FIELDS and
         receipt['schema'] == SCHEMA and receipt['source_plan_sha256'] == SOURCE_SHA and
         receipt['publisher_revision'] == original.original.PINNED_REV and
         receipt['cohort'] == original.COHORT and
         receipt['fold_salt'] == SALT and receipt['temperature_grid'] == GRID and
         receipt['stratification'] == 'four_per_class_per_fold_fit_only',
         'invalid source/calibration material')
    must(receipt['authority'] == 'DENY_ALL' and receipt['disposition'] == 'HOLD_NO_GO' and
         receipt['production_authorized'] is False and receipt['stem_winner_verified'] is False and
         receipt['heldout_label_access'] is False and receipt['future_windows'] == 0 and
         receipt['independent_source_families'] == 1, 'falsified source authority')
    cost = receipt['cost']
    must(type(cost) is dict and set(cost) == {'wall_seconds', 'cpu_seconds',
         'process_maxrss_bytes', 'neural_forward_count', 'energy_joules', 'p99_latency_ms'} and
         cost['neural_forward_count'] == 0 and cost['energy_joules'] is None and
         cost['p99_latency_ms'] is None and type(cost['process_maxrss_bytes']) is int and
         cost['process_maxrss_bytes'] > 0 and all(type(cost[k]) in (int, float) and
         math.isfinite(cost[k]) and cost[k] >= 0 for k in ('wall_seconds','cpu_seconds')),
         'invented or missing physical cost')
    fit = source['train']
    labels = [r['label'] for r in fit]
    must(all(type(x) is int and 0 <= x <= 3 for x in labels) and
         [labels.count(k) for k in range(4)] == [16]*4, 'invalid train-only labels')
    folds = [-1]*64
    for category in range(4):
        indices = sorted((i for i,x in enumerate(labels) if x == category),
                         key=lambda i: id_digest((SALT + fit[i]['case_id']).encode()))
        for j, ix in enumerate(indices):
            folds[ix] = j%4
    must(all(folds.count(k) == 16 for k in range(4)), 'unbalanced folds')
    must(receipt['fit_folds'] == [{'case_id': row['case_id'], 'fold': folds[i]}
                                 for i,row in enumerate(fit)], 'crossfit fold identity altered')
    must(type(receipt['rows']) is list and len(receipt['rows']) == 32 and
         type(receipt['calibration']) is dict and set(receipt['calibration']) == set(ARMS),
         'incomplete calibration artifacts')
    predictions = {}
    for arm in ARMS:
        cv_loss = [0.0]*len(GRID)
        for fold in range(4):
            training = [row for i,row in enumerate(fit) if folds[i] != fold]
            validation = [row for i,row in enumerate(fit) if folds[i] == fold]
            cosines, _ = _independent_scores(training, validation, arm)
            for values, row in zip(cosines,validation):
                actual = row['label']
                for k,t in enumerate(GRID):
                    p = _softmax(values,t)
                    cv_loss[k] += sum((v - (1.0 if j == actual else 0.0))**2
                                      for j,v in enumerate(p))/64
        winner = min(range(len(GRID)), key=lambda i:(cv_loss[i],GRID[i]))
        calibration = receipt['calibration'][arm]
        must(type(calibration) is dict and
             set(calibration) == {'temperature','cv_brier_by_temp','full_train_vocabulary'} and
             calibration['temperature'] == GRID[winner] and
             type(calibration['cv_brier_by_temp']) is list and
             len(calibration['cv_brier_by_temp']) == len(GRID) and
             all(type(a) in (float,int) and math.isfinite(a) and abs(a-b) <= 1e-10
                 for a,b in zip(calibration['cv_brier_by_temp'],cv_loss)),
             'tampered/heldout-tuned calibration')
        cosines, n_vocab = _independent_scores(fit,source['heldout'],arm)
        must(type(calibration['full_train_vocabulary']) is int and
             calibration['full_train_vocabulary'] == n_vocab, 'test vocabulary exposure')
        predictions[arm] = [_softmax(x, GRID[winner]) for x in cosines]
    for i,row in enumerate(source['heldout']):
        seen = receipt['rows'][i]
        must(type(seen) is dict and set(seen) == {'case_id','source_sha256','scores'} and
             seen['case_id'] == row['case_id'] and
             seen['source_sha256'] == row['source_sha256'] and
             type(seen['scores']) is dict and set(seen['scores']) == set(ARMS),
             'test labels or receipt identity substituted')
        for arm in ARMS:
            actual = seen['scores'][arm]
            must(type(actual) is list and len(actual) == 4 and
                 all(type(v) in (int,float) and math.isfinite(v) and 0 <= v <= 1
                     for v in actual) and abs(sum(actual)-1) < 1e-10 and
                 all(abs(a-b) <= 1e-10 for a,b in zip(actual,predictions[arm][i])),
                 'independent calibrated probability replay mismatch')
    return {arm: receipt['calibration'][arm]['temperature'] for arm in ARMS}


def review_original(train_raw,test_raw,source,receipt,original_v4):
    reconstructed,gold = original.reconstruct(train_raw,test_raw,original.original.FIXED_SHA)
    must(source['train'] == reconstructed['train'] and
         source['heldout'] == reconstructed['heldout'],
         'original publisher test/train group does not match source')
    temperatures = independently_replay(source,receipt)
    fixed = fixed_review.review_original(train_raw,test_raw,source,original_v4)
    must(fixed['publisher_original_sha_verified'] is True and
         fixed['independent_algorithm_replay'] is True and
         fixed['disposition'] == 'HOLD_NO_GO', 'original fixed V4 review absent')
    scored = {}
    for arm in ARMS:
        correct=0;brier=0.0;correct_fixed=0;brier_fixed=0.0
        for calibrated,baseline in zip(receipt['rows'],original_v4['rows']):
            must(calibrated['case_id'] == baseline['case_id'], 'different original cheap case identity')
            gold_label=gold[calibrated['case_id']]
            p=calibrated['scores'][arm];q=baseline['scores'][arm]
            correct += int(max(range(4),key=lambda i:p[i]) == gold_label)
            correct_fixed += int(max(range(4),key=lambda i:q[i]) == gold_label)
            brier += sum((v-float(i == gold_label))**2 for i,v in enumerate(p))/32
            brier_fixed += sum((v-float(i == gold_label))**2 for i,v in enumerate(q))/32
        must(correct == correct_fixed, 'positive temperature unexpectedly changed rank')
        must(abs(brier_fixed - fixed['cheap_controls'][arm]['mean_multiclass_brier'])<1e-10,
             'original fixed baseline Brier identity mismatch')
        scored[arm] = {'fit_cv_temperature':temperatures[arm], 'correct':correct,
                       'mean_multiclass_brier':brier,
                       'fixed_t8_original_correct':correct_fixed,
                       'fixed_t8_original_brier':brier_fixed,
                       'delta_brier_calibrated_minus_fixed':brier-brier_fixed}
    return {'schema':'hepta.stem.charge-lexical-independent-review.v6',
            'case_count':32,'original_source_sha256':SOURCE_SHA,
            'publisher_original_sha_verified':True,
            'independent_train_only_calibration_replay':True,
            'original_v4_fixed_baseline_reverified':True,
            'calibration':scored,
            'prior_publisher_test_labels_already_inspected':True,
            'source_independent_families':1,'future_windows':0,
            'stem_winner_verified':False,'ndu_benefit_verified':False,
            'production_authorized':False,'disposition':'HOLD_NO_GO',
            'authority':'DENY_ALL'}


def main():
    parser=argparse.ArgumentParser()
    for field in ('train','test','source','receipt','original-v4','output'):
        parser.add_argument('--'+field,required=True)
    args=parser.parse_args()
    result=review_original(Path(args.train).read_bytes(),Path(args.test).read_bytes(),
        json.loads(Path(args.source).read_text()),
        json.loads(Path(args.receipt).read_text()),
        json.loads(Path(args.original_v4).read_text()))
    dest=Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open('xb') as f:
        f.write(json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n')
    print(json.dumps({'authority':'DENY_ALL','sha256':id_digest(dest.read_bytes()),
                      'disposition':'HOLD_NO_GO'},sort_keys=True))

if __name__ == '__main__':
    main()
