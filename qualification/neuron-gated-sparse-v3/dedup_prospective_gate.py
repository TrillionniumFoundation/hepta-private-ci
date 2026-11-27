#!/usr/bin/env python3
"""Collapse physical model aliases before independently signed future scoring.

Structural/diagnostic research only. Signed outcome checks are delegated to
precommit_future.score; byte-level model identity is reverified here. A genuine
selected A0 Owner, trusted witness clock, native Q24 parity and future NDU still
require independent external attestations. NEVER auto-select or promote.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from matched_train import sha_file, unique_json
from realized_budget_audit import CAPS, ARMS, audit as physical_audit, require
from precommit_future import SEAL_SCHEMA, score as signed_future_score

from physical_tensor_identity import canonical_tensor_sha

SCHEMA = 'hepta.neuron.deduplicated-future-model-review.v1'


def review(root: Path, training_sha: str, seal_path: Path, seal_sha: str,
           scored: dict, *, synthetic_canary: bool = False) -> dict[str, Any]:
    """Review an already independently verified signed score (not a raw claim).

    The public CLI invokes signed_future_score(...) itself, never accepts a
    user-provided unsigned statistics file. Unit tests inject synthetic stats
    to test this pure reducer; they cannot attest signers or target-host time.
    """
    root = Path(root)
    audited = physical_audit(root,training_sha,
                             synthetic_fixture_only=synthetic_canary)
    receipt = unique_json((root/'training-receipt.json').read_bytes())
    sha_file(Path(seal_path), seal_sha)
    seal = unique_json(Path(seal_path).read_bytes())
    require(type(seal) is dict and seal.get('schema') == SEAL_SCHEMA and
            seal.get('ndu_eligible') is False and
            seal.get('production_qualification') is False,
            'untrusted precommit seal version/authority')
    require(seal.get('train_receipt_sha256') == training_sha and
            seal.get('cell_id') == receipt['cell_id'] and
            seal.get('encoder_digest_claimed') == receipt['encoder_digest_claimed'] and
            seal.get('training_cutoff_utc') == receipt['training_cutoff_utc'] and
            seal.get('frozen_v1_artifact_sha256') ==
                receipt['no_change_v1_selected_sha256'],
            'physical training, selected frozen V1 and future seal not joined')
    require(seal.get('a0_evidence_class') == receipt.get('evidence_class') and
            (synthetic_canary or
             seal.get('a0_evidence_class') ==
               'SIGNED_A0_FORMAT_ONLY_NOT_HOST_EXECUTION'),
            'synthetic/owner A0 evidence class drift')
    require(type(scored) is dict and scored.get('seal_sha256') == seal_sha and
            scored.get('decision') == 'NO_PRODUCTION_PROMOTION' and
            scored.get('ndu_eligible') is False and
            scored.get('production_qualification') is False and
            scored.get('native_q24_parity_verified') is False and
            scored.get('trusted_host_time_independently_proven') is False and
            scored.get('a0_evidence_class') == seal.get('a0_evidence_class'),
            'signed scorer result had wrong seal or fabricated model authority')
    require(type(scored.get('partitions')) is dict and
            set(scored['partitions']) == {'future','ood'},
            'missing signed future or OOD results')
    declared = seal.get('model_sha256')
    require(type(declared) is dict and len(declared) == len(CAPS)*len(ARMS),
            'wrong frozen candidate inventory in precommit seal')
    models = {}
    for item in receipt['models']:
        cap,arm = item['cap'],item['arm']
        key = f'{cap}:{arm}'
        require(key not in models and declared.get(key) == item['weight_sha256'],
                'physical model weight SHA not bound to sealed prediction')
        models[key] = item
    require(set(models) == set(declared), 'missing or extra physically staged candidate')
    case_rows = seal.get('rows')
    require(type(case_rows) is list and 2 <= len(case_rows) <= 8192,
            'missing bounded precommit prediction cohort')
    seen_ids = set()
    cases = {'future':[], 'ood':[]}
    for row in case_rows:
        require(type(row) is dict and type(row.get('case_id')) is str and
                row['case_id'] not in seen_ids and
                row.get('partition') in cases and
                type(row.get('candidates')) is dict and
                set(row['candidates']) == set(models),
                'incomplete, duplicate, or unpaired sealed case')
        seen_ids.add(row['case_id'])
        require(all(type(v) is int and 0 <= v <= 1000000
                    for v in row['candidates'].values()),
                'unbounded or malformed sealed candidate score')
        cases[row['partition']].append(row)
    require(all(cases.values()), 'both future and OOD cases are mandatory')
    for partition, summary in scored['partitions'].items():
        require(type(summary) is dict and
                set(summary) == {'owner_v1','candidates'} and
                set(summary['candidates']) == set(models),
                f'{partition} independently scored model cohort missing')
        require(summary['owner_v1']['count'] == len(cases[partition]),
                f'{partition} no-change baseline sample count drift')
        for key in models:
            require(summary['candidates'][key]['count'] == len(cases[partition]),
                    f'{partition} signed candidate sample count drift')

    group_by_tensor = {}
    for key,model in models.items():
        tensor_digest = canonical_tensor_sha(
            root/model['weight_file'], model['weight_sha256'])
        group = (model['arm'],tensor_digest)
        group_by_tensor.setdefault(group,[]).append(key)
    groups = []
    for (arm,tensor_digest),aliases in sorted(group_by_tensor.items()):
        aliases.sort(key=lambda key:int(key.split(':')[0]))
        for rows in cases.values():
            for row in rows:
                values = {row['candidates'][key] for key in aliases}
                require(len(values) == 1,
                        'identical physical model tensor weights gave divergent future prediction')
        for part in ('future','ood'):
            stats = scored['partitions'][part]['candidates']
            for alias in aliases[1:]:
                require(stats[alias] == stats[aliases[0]],
                        'duplicated physical tensor model had inconsistent signed metrics')
        first = models[aliases[0]]
        groups.append({
            'arm':arm, 'canonical_tensor_sha256':tensor_digest,
            'canonical_candidate_id':aliases[0],
            'nominal_budget_aliases':aliases,
            'nominal_ceiling_alias_count':len(aliases),
            'realized_private_parameters':first['parameter_count'],
            'physical_weight_bytes':(root/first['weight_file']).stat().st_size,
            'future_brier_ppm_signed_claim':scored['partitions']['future'][
                'candidates'][aliases[0]]['brier_ppm'],
            'ood_brier_ppm_signed_claim':scored['partitions']['ood'][
                'candidates'][aliases[0]]['brier_ppm'],
        })
    # Newly sealed studies pin the exact executed tensor groups *before*
    # independent future outcomes exist. This reviewer recomputes them
    # from physical bytes instead of trusting caller-supplied reuse counts.
    reuse = seal.get('physical_tensor_reuse_observation')
    if reuse is not None:
        require(type(reuse) is dict and set(reuse) == {
            'schema','nominal_candidate_slots',
            'actual_distinct_models_executed_per_sequence_group',
            'source_sequence_group_count',
            'actual_surrogate_forward_calls_total',
            'redundant_surrogate_forward_calls_avoided',
            'redundant_model_graph_loads_avoided',
            'alias_groups','native_q24_parity_verified','ndu_eligible',
            'production_qualification',
        } and
            reuse['schema'] == 'hepta.neuron.forecast-physical-reuse.v2' and
            reuse['native_q24_parity_verified'] is False and
            reuse['ndu_eligible'] is False and
            reuse['production_qualification'] is False,
            'untrusted physical forecast reuse evidence schema/authority')
        expected_aliases = [{
            'arm':item['arm'],
            'canonical_tensor_sha256':item['canonical_tensor_sha256'],
            'canonical_model_key':item['canonical_candidate_id'],
            'alias_candidate_keys':item['nominal_budget_aliases'],
        } for item in groups]
        require(
            reuse['nominal_candidate_slots'] == len(models) and
            reuse['actual_distinct_models_executed_per_sequence_group'] == len(groups) and
            reuse['source_sequence_group_count'] ==
                len({row['source_group_sha256'] for row in seal['rows']}) and
            reuse['actual_surrogate_forward_calls_total'] ==
                len(groups)*reuse['source_sequence_group_count'] and
            reuse['redundant_surrogate_forward_calls_avoided'] ==
                (len(models)-len(groups))*reuse['source_sequence_group_count'] and
            reuse['redundant_model_graph_loads_avoided'] == len(models)-len(groups) and
            reuse['alias_groups'] == expected_aliases,
            'sealed physical tensor reuse claims differ from real weight bytes')
    # Descriptive Pareto only: minimizing physical private parameter count,
    # future Brier and OOD Brier. These are not independently proven causal
    # utilities or measured inference CPU/GPU latency and cannot select a Cell.
    frontier = []
    for item in groups:
        costs = (item['realized_private_parameters'],
                 item['future_brier_ppm_signed_claim'],
                 item['ood_brier_ppm_signed_claim'])
        dominated = any(
            all(other <= own for other,own in zip(
                (peer['realized_private_parameters'],
                 peer['future_brier_ppm_signed_claim'],
                 peer['ood_brier_ppm_signed_claim']),costs)) and
            any(other < own for other,own in zip(
                (peer['realized_private_parameters'],
                 peer['future_brier_ppm_signed_claim'],
                 peer['ood_brier_ppm_signed_claim']),costs))
            for peer in groups if peer is not item)
        if not dominated:
            frontier.append(item['canonical_candidate_id'])
    # Validate bytes again after all identity and metric comparisons. No
    # research output should bind mutable model files via stale SHA claims.
    for model in models.values():
        sha_file(root/model['weight_file'], model['weight_sha256'])
    return {
        'schema':SCHEMA,
        'evidence_class':'SYNTHETIC_SIGNED_CLAIM_ONLY' if synthetic_canary
                         else 'SIGNED_FORMAT_NOT_TRUSTED_HOST',
        'training_receipt_sha256':training_sha,'seal_sha256':seal_sha,
        'nominal_candidate_slots':len(models),
        'unique_physical_tensor_models_per_arm':len(groups),
        'redundant_ceiling_alias_count':len(models)-len(groups),
        'preoutcome_physical_forward_reuse_claim_verified':reuse is not None,
        'actual_distinct_physical_tensor_groups':len(groups),
        'unique_model_groups':groups,
        'descriptive_pareto_candidate_ids_only':frontier,
        'future_case_count':len(cases['future']),
        'ood_case_count':len(cases['ood']),
        'frozen_no_change_v1_scored_as_separate_baseline':True,
        'signed_chronology_is_not_trusted_host_time':True,
        'equal_realized_parameter_design_valid':audited[
            'five_tier_exact_realized_parameter_design_valid'],
        'paired_numerical_results_are_not_independent_training_replications':True,
        'independent_future_ndu_causality_verified':False,
        'f32_native_q24_parity_verified':False,
        'ndu_eligible':False,'production_qualification':False,
        'decision':'NO_MODEL_PROMOTION',
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('trained-root','training-receipt-sha256','seal-file','seal-sha256',
                'signed-witness','witness-pubkey','signed-outcomes','outcome-pubkey',
                'report'):
        parser.add_argument('--'+arg,required=True)
    parser.add_argument('--synthetic-canary',action='store_true')
    args = parser.parse_args()
    try:
        # The verified score is recomputed inside this process with the two
        # separately provisioned signing public keys, never read as an
        # unauthenticated cached statistics JSON file.
        scored = signed_future_score(args)
        result = review(Path(args.trained_root),args.training_receipt_sha256,
                        Path(args.seal_file),args.seal_sha256,scored,
                        synthetic_canary=args.synthetic_canary)
        with Path(args.report).open('x',encoding='utf-8') as f:
            json.dump(result,f,indent=2,sort_keys=True)
            f.write('\n')
            f.flush()
        print(json.dumps({'status':'DEDUP_FUTURE_SHADOW_ONLY',
                          'distinct_models':result['unique_physical_tensor_models_per_arm'],
                          'ndu_eligible':False,'production_qualification':False}))
        return 0
    except (ValueError,TypeError,KeyError,OSError,ImportError) as exc:
        print(json.dumps({'status':'BLOCKED_DEDUP_FUTURE_EVIDENCE',
                          'reason':str(exc),'production_qualification':False}),
              file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
