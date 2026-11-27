"""Independent six-cohort aggregation of already reviewed real 2x2 results.

This tool NEVER invokes a model, chooses a winning policy or grants promotion.
Seeds are repeated training/evaluation experiments, not independent future
source families. All raw original single-run receipts remain separately owned.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from group_checkpoint_audit import strict_json_file

SEEDS = (41, 47, 53)
PROFILES = ('sgd_v1', 'adam_v1')
FACTORS = ('legacy_oracle', 'legacy_no_verifier', 'guarded_oracle', 'guarded_no_verifier')
COHORTS = ('test', 'long', 'deleted', 'composition')
MODES = ('attention', 'attention_fixed', 'attention_ndu')


def valid_sha(value):
    return (type(value) is str and len(value) == 64 and value != '0' * 64
            and all(c in '0123456789abcdef' for c in value))


def audit_six(cohorts):
    """Consume exactly 6 external-recheck.json independent summary files."""
    wanted = {(seed, profile) for seed in SEEDS for profile in PROFILES}
    if type(cohorts) is not dict or set(cohorts) != wanted:
        raise ValueError('all six preregistered source/optimizer cells required')
    rows, costs = {}, {}
    for (seed, profile), filename in sorted(cohorts.items()):
        result = strict_json_file(filename, max_bytes=8_000_000)
        if (type(result) is not dict or result.get('schema') != 'hepta.group.feedback-factorial-independent.v1'
                or result.get('passed') is not True or result.get('authority') != 'DENY_ALL'
                or result.get('production_promotion_permitted') is not False
                or result.get('independently_future_tested') is not False
                or result.get('causal_quality_or_10t_equivalence_proven') is not False
                or result.get('equal_total_compute_demonstrated') is not False
                or result.get('real_host_execution_independently_attested', False) is not False
                or result.get('protocol_seed') != seed or result.get('training_profile') != profile
                or set(result.get('arm_protocol_sha256', {})) != set(FACTORS)
                or any(not valid_sha(v) for v in result['arm_protocol_sha256'].values())
                or len(set(result['arm_protocol_sha256'].values())) != 4
                or result.get('reference') != 'legacy_oracle'):
            raise ValueError('unqualified or mismatched original four-arm independent result')
        data = result.get('descriptive_paired')
        if type(data) is not dict or set(data) != set(COHORTS):
            raise ValueError('source cohort audit incomplete')
        for cohort in COHORTS:
            cases = data[cohort]
            if type(cases) is not dict or set(cases) != set(MODES):
                raise ValueError('all three registered System2 comparisons required')
            for mode in MODES:
                controls = cases[mode]
                if type(controls) is not dict or set(controls) != set(FACTORS):
                    raise ValueError('original four-factor measurements missing')
                n = None
                values = {}
                for factor in FACTORS:
                    record = controls[factor]
                    if (type(record) is not dict or
                            any(type(record.get(k)) is not int for k in
                                ('cases', 'correct', 'rescued', 'harmed', 'online_cpu_ns',
                                 'measured_steps', 'verifier_calls'))):
                        raise ValueError('typed measured factor receipts required')
                    count = record['cases']
                    if (count <= 0 or not 0 <= record['correct'] <= count
                            or not 0 <= record['rescued'] <= count
                            or not 0 <= record['harmed'] <= count
                            or record['rescued'] + record['harmed'] > count
                            or record['online_cpu_ns'] <= 0 or record['measured_steps'] <= 0
                            or record['verifier_calls'] < 0):
                        raise ValueError('impossible four-arm physical outcome')
                    if n is None:
                        n = count
                    elif n != count:
                        raise ValueError('misaligned heldout case count')
                    values[factor] = record['correct']
                base = values['legacy_oracle']
                for factor, x in values.items():
                    if ((controls[factor]['rescued'] - controls[factor]['harmed']) != x - base):
                        raise ValueError('forged paired rescue/harm arithmetic')
                rows[(seed, profile, cohort, mode)] = dict(
                    cases=n, correct=values,
                    guard_effect_oracle=(values['guarded_oracle'] - values['legacy_oracle']),
                    guard_effect_no_verifier=(values['guarded_no_verifier'] - values['legacy_no_verifier']),
                    oracle_effect_legacy=(values['legacy_oracle'] - values['legacy_no_verifier']),
                    oracle_effect_guarded=(values['guarded_oracle'] - values['guarded_no_verifier']),
                    interaction=(values['guarded_no_verifier'] - values['legacy_no_verifier'])
                                -(values['guarded_oracle'] - values['legacy_oracle']))
        charge = result.get('costs')
        if type(charge) is not dict or set(charge) != set(FACTORS):
            raise ValueError('every four-arm physical lifecycle charge required')
        for factor in FACTORS:
            val = charge[factor]
            for k in ('actual_lifecycle_cpu_ns', 'encoder_cpu_ns', 'teacher_cpu_ns',
                      'critic_cpu_ns', 'train_cpu_ns', 'oracle_feedback_calls',
                      'terminal_supervised_steps', 'terminal_withheld_steps'):
                if type(val.get(k)) is not int or val[k] < 0:
                    raise ValueError('missing finite CPU or observable TRAIN cost')
            if val['actual_lifecycle_cpu_ns'] == 0 or val['encoder_cpu_ns'] == 0:
                raise ValueError('full pretrained CPU and Encoder must be paid')
            if (factor.endswith('no_verifier') and val['oracle_feedback_calls'] != 0) or (
                    factor.endswith('oracle') and val['oracle_feedback_calls'] <= 0):
                raise ValueError('TRAIN oracle callback count does not match factorial policy')
            if (factor.startswith('guarded') and val['terminal_withheld_steps'] <= 0) or (
                    factor.startswith('legacy') and val['terminal_withheld_steps'] != 0):
                raise ValueError('terminal guard did not actually withhold TRAIN labels')
            costs[(seed, profile, factor)] = val['actual_lifecycle_cpu_ns']
    return dict(schema='hepta.group.factorial-six-cohort-review.v1',
        authority='DENY_ALL', passed=True,
        production_promotion_permitted=False, winner_selected=False,
        future_natural_task_efficacy_proven=False, equal_compute_demonstrated=False,
        retained_source_independence_unverified=True,
        repeated_seed_measurements_not_independent_future_tasks=True,
        six_source_optimizer_blocks=len(wanted), physical_training_arms=len(costs),
        total_prep_and_execution_cpu_ns=sum(costs.values()),
        by_block=[dict(seed=seed, optimizer=profile, cohort=cohort, mode=mode, **value)
                  for (seed, profile, cohort, mode), value in sorted(rows.items())])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(args.root)
    inputs = {}
    for seed in SEEDS:
        for profile in PROFILES:
            matches = list(root.glob(f'hepta-group-2x2-{seed}-{profile}-*/external-recheck.json'))
            if len(matches) != 1:
                raise ValueError(f'exactly one sealed original group 2x2 result required for {seed}/{profile}')
            inputs[(seed, profile)] = matches[0]
    result = audit_six(inputs)
    with Path(args.output).open('x') as out:
        json.dump(result, out, allow_nan=False, sort_keys=True)


if __name__ == '__main__':
    main()
