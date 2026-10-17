"""Full V14 data-only original source→prompt→Reader→judgment reconciler.

Does not call pretrained models, authenticate a host or reviewer, or promote
a model. Reconciles independently rematerialized source bytes and complete
frozen candidate/reference Reader-output matrices before ANY diagnostic.
"""
from __future__ import annotations

import argparse
import json

from v14_reader_sufficiency_gate import load_json, report, require, sha_obj
from v14_reader_original_request_review import review as independently_rebuild


def reconcile(source, plan, private, predictions, adjudication):
    original = independently_rebuild(source, plan, private)
    counted = report(plan, predictions, adjudication)
    require(original['source_replay_equal'] is True
            and original['plan_sha256'] == counted['plan_sha256']
            and original['case_count'] == counted['case_count'],
            'original prompt/input/answer identity mismatch')
    require(counted['decision'] == 'HOLD_NO_GO'
            and counted['production_authorized'] is False
            and counted['independent_human_attestation_verified'] is False,
            'untrusted model promotion request')
    expected = original['recomputed_actual_four_arm_prompts'] * 2
    totals = {
        reader: {arm: dict(
            cases=data['cases'],
            raw_correct=data['correct'],
            grounded_correct=data['grounded_correct'],
            input_tokens=data['input_tokens'],
            output_tokens=data['output_tokens'],
            cpu_ms=data['cpu_ms'],
            wall_ms=data['wall_ms'],
        ) for arm, data in arms.items()}
        for reader, arms in counted['per_reader_arm'].items()
    }
    require(sum(t['cases'] for a in totals.values() for t in a.values()) == expected,
            'original dual-Reader dispatch census')
    return {
        'schema': 'hepta.stem.v14.complete-original-source-evidence-reconciliation.v1',
        'source_sha256': original['source_sha256'],
        'plan_sha256': original['plan_sha256'],
        'private_packet_sha256': original['private_packet_sha256'],
        'original_source_replay_sha256': sha_obj(original),
        'predictions_sha256': counted['predictions_sha256'],
        'adjudication_sha256': counted['adjudication_sha256'],
        'complete_chain_sha256': sha_obj({
            'source': original['source_sha256'],
            'plan': original['plan_sha256'],
            'prompts': original['private_packet_sha256'],
            'model_outputs': counted['predictions_sha256'],
            'review': counted['adjudication_sha256'],
        }),
        'case_count': counted['case_count'],
        'source_first_original_prompts_reconstructed': expected // 2,
        'two_reader_arm_outcomes_seen': expected,
        'reported_per_reader_arm': totals,
        'grounding_and_capacity_diagnostics': counted['diagnostics'],
        'per_claimed_family_not_authenticated':
            counted['per_claimed_family_paired_not_authenticated'],
        'source_owner_authenticated': False,
        'physical_pretrained_reader_calls_verified': False,
        'independent_human_semantic_review_verified': False,
        'new_prospective_source_families_verified': False,
        'stem_winner_verified': False,
        'system2_verified': False,
        'production_authorized': False,
        'decision': 'HOLD_NO_GO',
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--source', required=True)
    cli.add_argument('--plan', required=True)
    cli.add_argument('--private-requests', required=True)
    cli.add_argument('--predictions', required=True)
    cli.add_argument('--adjudication', required=True)
    a = cli.parse_args()
    out = reconcile(load_json(a.source), load_json(a.plan),
                    load_json(a.private_requests), load_json(a.predictions),
                    load_json(a.adjudication))
    print(json.dumps(out, indent=2, ensure_ascii=False, sort_keys=True,
                     allow_nan=False))


if __name__ == '__main__':
    main()
