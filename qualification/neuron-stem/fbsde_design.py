"""V2 independent-question design and descriptive source/stratum auditing.

This does not alter the historical label-balanced V1 generator. It cannot certify
independent sources or external chronology, and has no acceptance CLI.
"""
from collections import Counter
from four_gate_common import digest, require
from fbsde_encoder_cases import (TRAIN_FORMULAS, TEST_FORMULAS, leaf_count,
                                checked_probability, score_decoded)
from fbsde_tree import eval_formula
import random

LEGACY = 'label_balanced_v1'
INDEPENDENT = 'independent_targets_v2'
from fbsde_composition import PROFILE as COMPOSITION
PROFILES = (LEGACY, INDEPENDENT, COMPOSITION)


def independent_cases(inputs, split, count, seed):
    """Only opaque IDs enter public question generation; labels are not accepted."""
    require(split in ('train', 'validation', 'calibration', 'test'), 'unknown split')
    require(type(count) is int and 1 <= count <= 10000, 'bounded case count')
    require(type(seed) is int and 0 <= seed < 2**63, 'bounded seed')
    require(type(inputs) is list and 4 <= len(inputs) <= 10000, 'bounded source inventory')
    require(all(type(r) is dict and set(r) == {'id'} and type(r['id']) is str
                and 0 < len(r['id']) <= 256 for r in inputs), 'ID-only public inventory')
    ids = sorted(r['id'] for r in inputs)
    require(len(ids) == len(set(ids)), 'duplicate input identity')
    rng = random.Random(seed)
    formulas = TEST_FORMULAS if split == 'test' else TRAIN_FORMULAS
    public = []
    for i in range(count):
        formula = formulas[i % len(formulas)]
        chosen = rng.sample(ids, leaf_count(formula))
        targets = [rng.randrange(4) for _ in chosen]
        public.append({'case_id': f'{split}:v2:{i}', 'utterance_ids': chosen,
                       'target_intents': targets, 'formula': formula})
    return public


def label_cases(public, labelled_rows):
    """Scorer/fit side only. Do not pass this output to model or BSDE inputs."""
    labels = {r['id']: r['intent'] for r in labelled_rows}
    require(len(labels) == len(labelled_rows) and
            all(type(v) is int and 0 <= v < 4 for v in labels.values()), 'label inventory')
    require(len({r['case_id'] for r in public}) == len(public), 'duplicate public case')
    return {r['case_id']: bool(eval_formula(r['formula'],
            [labels[uid] == target for uid, target in zip(r['utterance_ids'], r['target_intents'])]))
            for r in public}


def balanced_target_posterior(probability):
    """Diagnostic Bayes correction for V1, not a retrospective change of its outputs.

    P(target=j|class=j)=1/2; P(target=j|class!=j)=1/6.
    Given pre-question q=P(class=j|text), post-question q*=3q/(1+2q).
    This identifies a conditioning mismatch, not observed real-model error.
    """
    p = checked_probability(probability)
    return 3*p/(1+2*p)


def source_census(public, source_hashes):
    """Connected components describe dependence; they do NOT authenticate independence."""
    require(public and len({r['case_id'] for r in public}) == len(public), 'case inventory')
    parent = {}; exposure = Counter()
    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    members = []
    for row in public:
        hashes = {source_hashes[uid] for uid in row['utterance_ids']}
        require(hashes, 'empty source case')
        require(all(type(h) is str and len(h) == 64 for h in hashes), 'source hashes')
        ordered = sorted(hashes)
        for h in ordered:
            parent[find(h)] = find(ordered[0])
            exposure[h] += 1
        members.append(ordered)
    groups = Counter(find(h[0]) for h in members)
    return {'cases': len(public), 'unique_source_texts': len(exposure),
            'source_connected_components': len(groups),
            'component_case_counts': sorted(groups.values(), reverse=True),
            'maximum_cases_per_source': max(exposure.values()),
            'public_sha256': digest(public),
            'iid_case_confidence_intervals_permitted': False,
            'independence_authenticated': False}


def stratified_metrics(records, truths, public):
    require(set(truths) == {r['case_id'] for r in public}, 'truth/public inventory')
    by_id = {r['case_id']: r for r in records}
    require(len(by_id) == len(records) and set(by_id) == set(truths), 'prediction inventory')
    groups = {}
    for row in public:
        groups.setdefault(digest(row['formula']), []).append(row['case_id'])
    report = {}
    for group, ids in groups.items():
        subset = [by_id[i] for i in ids]
        labels = {i: truths[i] for i in ids}
        require(all(type(y) is bool for y in labels.values()), 'Boolean truth required')
        m = score_decoded(subset, labels)
        positive = sum(labels.values()); negative = len(ids)-positive
        tp = sum(by_id[i]['probability'] >= .5 and labels[i] for i in ids)
        tn = sum(by_id[i]['probability'] < .5 and not labels[i] for i in ids)
        m.update({'positive_cases': positive, 'negative_cases': negative,
                  'true_positive_rate': tp/positive if positive else None,
                  'true_negative_rate': tn/negative if negative else None,
                  'balanced_accuracy': (tp/positive+tn/negative)/2 if positive and negative else None,
                  'stratum_has_both_labels': bool(positive and negative)})
        report[group] = m
    return report
