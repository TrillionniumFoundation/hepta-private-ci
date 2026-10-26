"""Freeze one seed-17 repair candidate before the final 96 source pairs open."""

import argparse
import json
from pathlib import Path
import time

from ....abc_recovery.base_recovery import file_sha, write_json
from ..registry import HERE


def run(repair, output):
    result_path = repair / 'result.json'
    result = json.loads(result_path.read_text())
    record = next(r for r in result['records'] if r['seed'] == 17 and r['candidate']['name'] == 'wide_128_2000')
    checkpoint = Path(record['checkpoint'])
    if result['status'] != 'completed' or record['development_threshold'] != .5 or file_sha(checkpoint) != record['checkpoint_sha256']:
        raise ValueError('Only the already selected seed-17/128/2000/.5 candidate is allowed')
    original = json.loads((HERE / 'FRESH_PROTOCOL.json').read_text())
    files = dict(original['frozen_candidate_sha256'])
    files.update({str(p.resolve()): file_sha(p) for p in Path(__file__).parent.glob('confirmation_*.py')})
    loader = HERE.parent / 'supplement_sources.py'
    files.update({str(loader.resolve()): file_sha(loader), str(checkpoint.resolve()): record['checkpoint_sha256'],
                  str(result_path.resolve()): file_sha(result_path)})
    if any(file_sha(Path(p)) != expected for p, expected in files.items()):
        raise ValueError('Frozen implementation/assets changed before confirmation')
    evaluation = dict(original['evaluation'])
    evaluation.update({'source_role': 'closure_control_repair', 'pair_start': 0, 'pair_count': 96, 'requests': 3072,
        'policies': ['cached_teacher', 'selected_gate'],
        'observation_namespace': 'closure-20261025-control-repair96-observation-v1',
        'initial_namespace': 'closure-20261025-control-repair96-initial-v1',
        'future_namespace': 'closure-20261025-control-repair96-future-v1',
        'statistical_scope': '96 new source-pair clusters, conditional on the single frozen seed-17 generator/teacher; no training-seed population inference'})
    allocation = HERE.parent / 'SUPPLEMENT_ALLOCATION.json'
    result = {'schema': 'hepta.closure.control-repair-confirmation-protocol.v1', 'study': 'control_repair',
              'source_allocation_sha256': file_sha(allocation), 'frozen_candidate_sha256': files,
              'frozen_unix_ns': time.time_ns(), 'new_source_outcomes_opened': False,
              'training_seed': 17, 'checkpoint': str(checkpoint.resolve()), 'checkpoint_sha256': record['checkpoint_sha256'],
              'threshold': .5, 'evaluation': evaluation, 'policies': ['cached_teacher', 'selected_gate'],
              'order_namespace': 'closure-20261025-control-repair96-order-v1',
              'order': 'Each same-source/view/draw pair uses an independently hashed random policy order; policy identity never enters the generation RNG',
              'bootstrap_seed': 202610259617, 'bootstrap_replicates': 2000,
              'primary_family': {'raw_CE_difference_lower_at_least': -.005, 'success_difference_lower_at_least': -.005,
                                 'mean_request_wall_ms_difference_upper_below': 0., 'nominal_two_sided_component_level': .975},
              'cost_prices_utility_per_ms': [0., .001, .002, .005],
              'cost_scope': 'Same immutable full request function; every feature/head/fallback, action commitment, generation, terminal fsync/readback timed; other phases and exact-child total retained',
              'scope': 'One bounded post-development confirmation, no candidate switching, no refit, no aggregate claim over the other four generator seeds'}
    if output.exists():
        raise FileExistsError('Confirmation protocol cannot be overwritten')
    write_json(output, result)
    print(json.dumps({'protocol': str(output), 'sha256': file_sha(output), 'checkpoint_sha256': record['checkpoint_sha256']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repair', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); run(args.repair, args.output)
