"""Score presealed Granite paired-world predictions in a separate research process.

Preflight binds all twelve exact pretrained inference seals *before* loading
any fresh outcome labels. A source/label-independent actor is not attested:
this is process-phase separation and immutable evidence, NOT cryptographic
blind custody or trusted production authorization.
"""
import argparse
import hashlib
import json
from pathlib import Path

from cross_fact_granite_campaign import (
    ARMS, SEEDS, _digest, _write_once, matched_fresh_gate,
)
from cross_fact_granite_review import read, require

ROLES = ('fresh_combinations', 'fresh_vocabulary')


def check_sealed_panel(root, role, seed, arm, frozen_weight, case_ids):
    """Reject a missing, tampered, duplicated or incorrectly ordered seal."""
    path = root / f'sealed-{role}-{seed}-{arm}.json'
    sealed = read(path)
    require(sealed['weights_sha256'] == frozen_weight,
            'model weight identity changed before fresh scoring')
    require(sealed['labels_entered_model'] is False and sealed['scoring_started'] is False,
            'prediction seal not label-blind')
    require(sealed['case_ids'] == case_ids and len(case_ids) == 128,
            'wrong or incomplete original fresh case roster')
    require(len(sealed['probabilities']) == len(case_ids)
            and all(type(p) in (int, float) and 0 <= p <= 1 for p in sealed['probabilities']),
            'probability count or numeric range invalid')
    batches = sealed['batches']
    require(isinstance(batches, list) and len(batches) == 8,
            'expected eight physical inference batches')
    require([cid for batch in batches for cid in batch['case_ids']] == case_ids,
            'real inference batch identities do not match prediction order')
    require(all(batch['steps'] == 3 and batch['proposal_steps'] == len(batch['case_ids']) * 3
                and type(batch['cpu_ns']) is int and batch['cpu_ns'] >= 0
                and type(batch['wall_ns']) is int and batch['wall_ns'] >= 0 for batch in batches),
            'incomplete actual inference budget observation')
    return path, sealed


def check_campaign_gates(root):
    """Verify fixed training/opening receipts without importing outcome labels."""
    root = Path(root).resolve()
    plan = read(root / 'plan.json')
    summary = read(root / 'fit-summary.json')
    decision = read(root / 'opening-decision.json')
    terminal = read(root / 'terminal.json')
    require(plan['seeds'] == list(SEEDS) and plan['arms'] == list(ARMS)
            and plan['production_authorized'] is False, 'frozen design changed')
    allowed = matched_fresh_gate(summary)
    require(allowed and decision['matched_fresh_gate_passed'] is True
            and decision['all_model_fit_gates_passed'] is True
            and decision['all_actual_training_budgets_equal'] is True,
            'all six equal-investment training fits are required')
    require(terminal['status'] == 'all_frozen_predictions_sealed_pending_independent_scoring'
            and terminal['fresh_prediction_seals_complete'] is True
            and terminal['fresh_scoring_authorized'] is False,
            'no fully sealed independent-scoring boundary')
    frozen = read(root / 'all-models-frozen.json')
    require(set(frozen) == {str(seed) for seed in SEEDS}, 'missing frozen seeds')
    for seed in SEEDS:
        require(frozen[str(seed)] == {arm: summary[str(seed)][arm]['model_file_sha256'] for arm in ARMS},
                'frozen model identity differs from trained weights')
    expected = {f'sealed-{role}-{seed}-{arm}.json'
                for role in ROLES for seed in SEEDS for arm in ARMS}
    require({x.name for x in root.glob('sealed-*.json')} == expected
            and not list(root.glob('score-*.json'))
            and not (root / 'scoring-completion.json').exists(),
            'missing or unexpected scored/duplicate fresh results')
    return frozen


def case_roster_digest(case_ids):
    return hashlib.sha256(json.dumps(case_ids, separators=(',', ':')).encode()).hexdigest()


def check_prelabel_seals(root):
    """Check the full sealed result inventory BEFORE loading any outcome labels."""
    root = Path(root).resolve()
    frozen = check_campaign_gates(root)
    plan = read(root / 'plan.json')
    rosters = plan.get('fresh_case_roster_sha256')
    require(isinstance(rosters, dict) and set(rosters) == set(ROLES),
            'missing frozen prelabel source roster digests')
    result = {}
    for role in ROLES:
        first = read(root / f'sealed-{role}-{SEEDS[0]}-{ARMS[0]}.json')
        ids = first['case_ids']
        require(isinstance(ids, list) and len(ids) == 128
                and len(set(ids)) == len(ids)
                and all(isinstance(cid, str) and 0 < len(cid) <= 1024 for cid in ids)
                and case_roster_digest(ids) == rosters[role],
                'prelabel source roster does not match frozen original design')
        for seed in SEEDS:
            for arm in ARMS:
                path, sealed = check_sealed_panel(root, role, seed, arm,
                        frozen[str(seed)][arm], ids)
                result[f'{role}/{seed}/{arm}'] = dict(
                    file=path.name, digest=_digest(path), predictions=sealed['probabilities'])
    return result


def check_global_seals(root, case_ids_by_role):
    """Verify every original case/feature seal without examining labels."""
    root = Path(root).resolve()
    require(set(case_ids_by_role) == set(ROLES), 'all roles required')
    # The first pass verified every seal without importing labels at all.
    sealed = check_prelabel_seals(root)
    plan = read(root / 'plan.json')
    for role in ROLES:
        roster = case_ids_by_role[role]
        require(case_roster_digest(roster) == plan['fresh_case_roster_sha256'][role],
                'original scorer role roster differs from the frozen prelabel manifest')
        for seed in SEEDS:
            for arm in ARMS:
                path = root / sealed[f'{role}/{seed}/{arm}']['file']
                require(read(path)['case_ids'] == roster,
                        'fresh scorer reordered or replaced the original prelabel roster')
    return sealed


def score_sealed(root):
    """Two-phase scores: lock all public predictions before revealing labels.

    All label scoring is executed only after preflight has validated all twelve
    registered proof files. A crash after some writes is intentionally fatal:
    never silently resume, drop a failed arm, or replace a prior score.
    """
    root = Path(root).resolve()
    require(root.is_dir() and not root.is_symlink(), 'regular evidence directory required')
    # The whole training and exact-seal set must qualify first. Only then may
    # the separate phase load the frozen outcome protocol at all.
    check_prelabel_seals(root)
    # The coordinator's fit-summary and opening flags are NOT evidence of real
    # training. Reconstruct original TRAIN truth, all six optimizer receipts,
    # weight file digests, old-task retention and bounded work independently
    # before the scoring process is allowed to import fresh-domain labels.
    from cross_fact_granite_review import review
    audited = review(root)
    require(audited['receipt_consistency_passed'] is True
            and audited['all_training_gates_passed'] is True
            and audited['matched_training_budget_observed'] is True
            and audited['separate_scoring_completed'] is False
            and audited['fresh_scoring_permitted_under_existing_rule'] is True
            and audited['production_authorized'] is False,
            'independent original training/model audit rejected fresh scoring')
    from binding_protocol import build_binding_protocol, score_binding_probabilities

    # Only the fixed original protocol supplies case ordering and truth. The
    # infer/Head/optimizer modules are never imported into this process.
    parts = build_binding_protocol(seed=41)
    cases = {role: tuple(parts[role]) for role in ROLES}
    sealed = check_global_seals(root, {role: [c.case_id for c in cases[role]] for role in ROLES})
    results = {}
    for role in ROLES:
        for seed in SEEDS:
            for arm in ARMS:
                tag = f'{role}/{seed}/{arm}'
                entry = sealed[tag]
                scores = score_binding_probabilities(cases[role], entry['predictions'])
                results[tag] = dict(predictions_sha256=entry['digest'], metrics=scores)
    for tag, result in results.items():
        role, seed, arm = tag.split('/')
        _write_once(root / f'score-{role}-{seed}-{arm}.json', result)
    _write_once(root / 'scoring-completion.json', {
        'schema': 'hepta.cross-fact.separate-score.v1',
        'completed_roles': list(ROLES), 'seeds': list(SEEDS), 'arms': list(ARMS),
        'scored_count': len(results),
        'score_files': {f'score-{tag.replace("/", "-")}.json':
                        _digest(root / f'score-{tag.replace("/", "-")}.json')
                        for tag in results},
        'score_from_frozen_prelabel_seals': True,
        'independent_host_attested': False,
        'production_authorized': False,
    })
    return len(results)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    print(json.dumps({'sealed_fresh_panels_scored': score_sealed(args.root),
                      'production_authorized': False}, sort_keys=True))
