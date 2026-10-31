"""Small analytic enumeration of the unqualified finite joint-evidence interface."""

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path

from .unique_evidence import EvidenceError, EvidenceFilter, JointEvidenceModel, Outcome, Receipt


def close(actual, expected):
    if isinstance(actual, dict):
        assert set(actual) == set(expected)
        return close(tuple(actual.values()), tuple(expected[key] for key in actual))
    if isinstance(actual, (tuple, list)):
        assert len(actual) == len(expected)
        for a, b in zip(actual, expected):
            close(a, b)
    else:
        assert math.isclose(actual, expected, rel_tol=0., abs_tol=1e-12), (actual, expected)


def rejects(operation):
    try:
        operation()
    except EvidenceError:
        return
    raise AssertionError('Invalid evidence or probability law was accepted')


def run():
    # Every coupling is supplied explicitly, including distinct-recording rows.
    outcomes = (Outcome((0, 0), (0, 0)), Outcome((0, 0), (1, 1)),
                *(Outcome((0, 1), values) for values in itertools.product((0, 1), repeat=2)))
    law = {0: [.8, .2, 0, 0, 0, 0], 1: [0, 0, .08, .72, .02, .18],
           10: [0, 0, .08, .02, .72, .18], 11: [.1, .9, 0, 0, 0, 0]}
    model = JointEvidenceModel((0, 1, 10, 11), ('left', 'right'), outcomes, law)
    prior = {target: .25 for target in model.targets}
    state = EvidenceFilter(model, prior)
    forecast = state.forecast_complete_arrival()
    close(sum(p for outcome, p in forecast if outcome.aliases == (0, 0)), .5)
    close(state.posterior(), prior)
    assert state.history == {}
    left = Receipt('left', 'opaque-wave-A', 0)
    alias = Receipt('right', 'opaque-wave-A', 0)
    distinct = Receipt('right', 'opaque-wave-B', 0)
    first = state.update([left])
    close(first, {0: 4 / 9, 1: 4 / 9, 10: 1 / 18, 11: 1 / 18})
    first_mass = state.evidence_probability()
    close(state.update([left, left]), first)
    close(state.evidence_probability(), first_mass)
    alias_posterior = state.update([alias])
    close(alias_posterior, {0: 8 / 9, 1: 0, 10: 0, 11: 1 / 9})
    close(state.evidence_probability(), .225)
    close(state.update([left, alias, alias]), alias_posterior)
    assert not math.isclose(alias_posterior[0], .8 ** 2 / (.8 ** 2 + .1 ** 2))
    for order in itertools.permutations((left, alias)):
        sequential = EvidenceFilter(model, prior)
        for item in order:
            sequential.update([item])
        close(sequential.posterior(), alias_posterior)
    close(EvidenceFilter(model, prior).update([left, alias]), alias_posterior)
    close(EvidenceFilter(model, prior).update([left, distinct]), {0: 0, 1: .5, 10: .5, 11: 0})
    history = state.history
    rejects(lambda: state.update([Receipt('right', 'opaque-wave-A', 1)]))
    rejects(lambda: state.update([Receipt('right', 'opaque-wave-B', 0)]))
    assert state.history == history
    close(state.posterior(), alias_posterior)
    fresh = EvidenceFilter(model, prior)
    rejects(lambda: fresh.update([Receipt('left', 'new-wave', 7)]))
    rejects(lambda: fresh.update([left, Receipt('right', 'opaque-wave-A', 1)]))
    assert fresh.history == {}
    rejects(lambda: Outcome((0, 0), (0, 1)))
    rejects(lambda: Outcome((1, 1), (0, 0)))
    rejects(lambda: JointEvidenceModel(model.targets, model.slots, outcomes, None))
    rejects(lambda: JointEvidenceModel((0,), model.slots, outcomes, {0: [0] * 6}))
    rejects(lambda: JointEvidenceModel((0,), model.slots, outcomes, {0: [float('nan')] + [0] * 5}))

    # Counterexample 1: identical 0.5 marginals can give opposite posteriors.
    distinct_outcomes = outcomes[2:]
    coupled = (.5, 0, 0, .5)
    anticoupled = (0, .5, .5, 0)
    posteriors = []
    for rows in ({'H0': coupled, 'H1': anticoupled}, {'H0': anticoupled, 'H1': coupled}):
        other = JointEvidenceModel(('H0', 'H1'), ('left', 'right'), distinct_outcomes, rows)
        for row in other.likelihood:
            close((row[0] + row[1], row[0] + row[2]), (.5, .5))
        posteriors.append(EvidenceFilter(other, {'H0': .5, 'H1': .5}).update([left, distinct]))
    close(posteriors[0], {'H0': 1., 'H1': 0.})
    close(posteriors[1], {'H0': 0., 'H1': 1.})

    # Counterexample 2: same 0.9 correctness marginals, success 0.9 vs 0.8.
    success_rows = ((.9, 0., 0., .1), (.8, .1, .1, 0.))
    both_correct = []
    for row in success_rows:
        close(sum(row), 1.)
        close((row[0] + row[1], row[0] + row[2]), (.9, .9))
        both_correct.append(row[0])
    assert both_correct == [.9, .8]
    return {'checks': ['arrival forecast leaves prior unchanged', 'unobserved alias integrated',
        'normalized sequential and batch posteriors', 'duplicate receipts idempotent',
        'alias event counted once', 'contradictory event or slot rejected atomically',
        'zero-support arrival rejected atomically', 'invalid law or alias support rejected',
        'no joint law inferred from marginals', 'two explicit coupling counterexamples'],
        'initial_alias_probability': .5, 'alias_posterior': alias_posterior,
        'same_marginal_opposite_posteriors': posteriors,
        'same_marginal_joint_success': both_correct}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run()
    paths = (Path(__file__), Path(__file__).with_name('unique_evidence.py'))
    result.update(schema='hepta.followup.finite-evidence-identity-verification.v1', status='passed',
        scope='Synthetic analytic probability identities only; no learned joint law or qualification claim',
        model_or_new_source_execution=False, frozen_candidate_modified=False, production_authority=False,
        source_sha256={str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
    print(json.dumps({'status': result['status'], 'checks': len(result['checks']), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
