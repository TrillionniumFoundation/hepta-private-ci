"""Exploratory paired uncertainty for the *already sealed* V20 AG News cohort.

Run ONLY inside V20's independent heldout evaluator after source, label,
model, Head and prediction census checks. Same-case exact discordance and
class-stratified resampling are diagnostics, not model selection, prospective
utility, a deployed no-change baseline or NDU authority.
"""
from __future__ import annotations

import hashlib
import math
import random
from collections import Counter
from math import comb

SCHEMA = 'hepta.stem-paired-heldout-exploratory.v21'
CANDIDATES = ('mmbert-small', 'granite-97m-r2')
N = 64
CLASSES = 4
PER_CLASS = 16
BOOTSTRAPS = 4096
BOOTSTRAP_SEED = 20261015


class PairedEvidenceError(ValueError):
    pass


def require(test: bool, why: str) -> None:
    if not test:
        raise PairedEvidenceError(why)


def _probabilities(p):
    require(type(p) is list and len(p) == CLASSES
            and all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1
                    for v in p)
            and abs(math.fsum(p) - 1.0) <= 1e-5,
            'nonfinite, unmatched or unnormalized probability vector')
    return p


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lo = int(position)
    hi = min(len(ordered) - 1, lo + 1)
    t = position - lo
    return ordered[lo] * (1 - t) + ordered[hi] * t


def _score_row(probabilities: list[float], label: int):
    correct = int(max(range(CLASSES), key=lambda k:(probabilities[k], -k)) == label)
    brier = math.fsum((p - int(k == label)) ** 2 for k,p in enumerate(probabilities))
    log_loss = -math.log(max(probabilities[label], 1e-12))
    return correct, brier, log_loss


def paired_posthoc(truth: list[dict], predictions: dict[str, list[dict]],
                   *, plan_sha256: str, target_sha256: str) -> dict:
    """Return aggregate case-paired numerical uncertainty, never a winner.

    No label or individual row is output. Inputs are required to be exactly
    V20's frozen ordered 64-case, balanced four-class heldout set.
    """
    for h in (plan_sha256, target_sha256):
        require(type(h) is str and len(h) == 64
                and all(c in '0123456789abcdef' for c in h),
                'invalid source commitment')
    require(type(truth) is list and len(truth) == N, 'wrong original heldout size')
    require(all(type(row) is dict and set(row) == {'case_id','label'}
                and type(row['case_id']) is str
                and type(row['label']) is int and 0 <= row['label'] < CLASSES
                for row in truth), 'invalid heldout truth cohort')
    ids = [r['case_id'] for r in truth]
    labels = [r['label'] for r in truth]
    require(ids == sorted(set(ids)) and Counter(labels) == Counter({c:PER_CLASS for c in range(CLASSES)}),
            'heldout paired identity or class-strata drift')
    require(type(predictions) is dict and set(predictions) == set(CANDIDATES),
            'incomplete exact model prediction coverage')
    rows = {}
    for model in CANDIDATES:
        batch = predictions[model]
        require(type(batch) is list and len(batch) == N
                and all(type(r) is dict and set(r) == {'case_id','probabilities'}
                        for r in batch)
                and [r['case_id'] for r in batch] == ids,
                'unmatched paired case census')
        rows[model] = [_score_row(_probabilities(r['probabilities']), y)
                       for r,y in zip(batch,labels)]
    m, g = rows[CANDIDATES[0]], rows[CANDIDATES[1]]
    contingency = {
        'both_correct':sum(a[0] and b[0] for a,b in zip(m,g)),
        'mmbert_only_correct':sum(a[0] and not b[0] for a,b in zip(m,g)),
        'granite_only_correct':sum(b[0] and not a[0] for a,b in zip(m,g)),
        'both_incorrect':sum(not a[0] and not b[0] for a,b in zip(m,g)),
    }
    require(sum(contingency.values()) == N, 'paired contingency lost cases')
    b = contingency['mmbert_only_correct']
    c = contingency['granite_only_correct']
    discordant = b+c
    # Exact two-sided sign/binomial (McNemar) test on discordant PAIRS.
    exact_p = (min(1.0, 2.0 * math.fsum(comb(discordant,k) for k in
                    range(min(b,c)+1)) / (2 ** discordant)) if discordant else 1.0)
    deltas = [[a[k]-b[k] for a,b in zip(m,g)] for k in range(3)]
    strata = [[i for i,y in enumerate(labels) if y == k] for k in range(CLASSES)]
    require(all(len(s) == PER_CLASS for s in strata), 'invalid class strata')
    rng = random.Random(BOOTSTRAP_SEED)
    replicates=[[],[],[]]
    for _ in range(BOOTSTRAPS):
        # Within-class paired resampling preserves 16 source cases per class.
        indices = [s[rng.randrange(PER_CLASS)] for s in strata
                   for __ in range(PER_CLASS)]
        for j in range(3):
            replicates[j].append(math.fsum(deltas[j][i] for i in indices)/N)
    score_names=['accuracy','multiclass_brier','log_loss']
    differences={name:{'observed': math.fsum(delta)/N,
                       'class_stratified_bootstrap95':[
                           _percentile(replicates[k],0.025),
                           _percentile(replicates[k],0.975)]}
                 for k,(name,delta) in enumerate(zip(score_names,deltas))}
    return {
        'schema':SCHEMA,
        'plan_sha256':plan_sha256,
        'heldout_targets_sha256':target_sha256,
        'case_count':N,
        'sample_per_class':PER_CLASS,
        'paired_contingency':contingency,
        'discordant_case_count':discordant,
        'mcnemar_exact_two_sided_p':exact_p,
        'mmbert_minus_granite':differences,
        'bootstrap_replicates':BOOTSTRAPS,
        'bootstrap_seed':BOOTSTRAP_SEED,
        'method':'same-case class-stratified paired percentile bootstrap',
        'inference_status':'posthoc_exploratory_public_test_set',
        'corpus_temporally_prospective':False,
        'deployed_no_change_observed':False,
        'costs_causally_matched':False,
        'experiment_winner':None,
        'significance_or_model_superiority_qualified':False,
        'independent_ndu_verified':False,
        'production_accepted':False,
        'authority':'DENY_ALL',
    }
