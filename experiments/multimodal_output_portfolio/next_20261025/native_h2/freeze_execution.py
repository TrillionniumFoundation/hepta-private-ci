"""Bind a locally exercised, truly qualified H2 executable before fresh owners."""

import argparse
import json
from pathlib import Path
import time

from .common import AREA, ALLOCATION, pins, qualified_dependencies, sha, write


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for n in ('binary', 'package', 'smoke', 'output'):
        p.add_argument('--' + n, required=True, type=Path)
    a = p.parse_args()
    package = json.loads(a.package.read_text())
    qualified_dependencies(package['predictor_path'], package['calibration_path'])
    verified = json.loads(Path(package['verification_path']).read_text())
    smoke = json.loads((a.smoke / 'results.json').read_text())
    if (not verified['study_qualified'] or not all(verified['gates'].values())
            or smoke['registration']['mode'] != 'smoke'
            or smoke['registration']['binary_sha256'] != sha(a.binary)
            or smoke['registration']['package_sha256'] != sha(a.package)
            or smoke['max_native_numpy_moment_error'] > 1e-10
            or smoke['max_native_original_teacher_error'] > 3e-6
            or smoke['max_native_correctness_raw_error'] > 1e-10
            or any(row['result']['ok'] or not row['owner_state_unchanged'] for row in smoke['negative_cases'])):
        raise ValueError('New actual qualification and successful mechanism development required')
    for policy in ('ndu', 'correctness'):
        kinds = {row['kind'] for row in smoke['recoveries'] if row['policy'] == policy}
        if kinds != {'abrupt_pending_H2_decision', 'graceful_observed_H2_before_H1'}:
            raise ValueError('Both pending and H2-to-H1 recovery must actually execute on old data')
    files = [a.binary, a.binary.parent / 'build.json', a.package,
             a.smoke / 'results.json', a.smoke / 'registration.json', a.smoke / 'rollouts.jsonl',
             AREA / 'QUALIFICATION_PROTOCOL.json', ALLOCATION,
             AREA.parent / 'h2_sources.py', AREA.parent / 'sources.py', AREA.parent / 'xnist_sources.py']
    files += [Path(package[name]) for name in ('weights_path', 'predictor_path', 'calibration_path', 'verification_path')]
    record = {'schema': 'hepta.next.native-h2-confirmation.v1', 'study': 'native_h2_execution',
              'source_allocation_sha256': sha(ALLOCATION), 'registered_unix_ns': time.time_ns(),
              'frozen_candidate_sha256': pins(files), 'binary_sha256': sha(a.binary), 'package_sha256': sha(a.package),
              'pair_count': 128, 'writer_count': 64, 'pairs_per_writer': 2,
              'views': 'one ID view cycling by fixed pair index plus both_missing',
              'policies': ['ndu', 'correctness'], 'seed_base': 83360017,
              'primary_comparison': 'native NDU versus same-admission correctness argmax',
              'primary_quality': 'ID terminal CE(gamma2) after .002 per actual continuation action',
              'secondary_metrics': ['joint_correct', 'raw utility', 'selected-step ECE', 'public request cost'],
              'bootstrap': {'unit': 'writer', 'draws': 4096, 'seed': 261026909, 'interval': [.025, .975],
                            'all_two_pairs_and_all_views_and_policies_stay_together': True},
              'online_feedback': 'existing public sensor, caption legality and image/text agreement',
              'private_GT': 'separate audit after all owner processes close',
              'runtime_scope': 'original AgentdNeuronOwner and resource/admission gates; research model-service host',
              'semantic_H1': 'masked as pointwise dominated; root H2 semantic remains feasible',
              'price_superiority_claim': 'requires corresponding uncertainty interval; no all-price guarantee',
              'after_outcomes': 'No changes or expansion; retain each rejection, resource failure, and model failure',
              'production_authority': False, 'whole_agentd_daemon_claimed': False}
    write(a.output, record)
    print(json.dumps({'protocol_sha256': sha(a.output), 'pins': len(record['frozen_candidate_sha256'])}))


if __name__ == '__main__':
    main()
