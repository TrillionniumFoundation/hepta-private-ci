"""Register the exact online mechanism before accessing its assigned new sources."""

import argparse
import json
from pathlib import Path
import time

from .build import sha


def freeze(args):
    area = Path(__file__).resolve().parent
    experiment = area.parents[1]
    prior = json.loads((experiment / 'abc_followup/native/PROTOCOL.json').read_text())
    packet = json.loads((Path(args.assets) / 'abc4-native-runs/future-packet-001/packet.json').read_text())
    paths = [args.binary.resolve(), args.binary.parent / 'build.json', args.allocation.resolve()]
    paths += sorted(area.glob('*.py')) + sorted(area.glob('*.rs'))
    paths += [area.parent / 'sources.py']
    paths += sorted((args.binary.parent / 'src').glob('*.rs'))
    paths += [Path(prior['paths'][name]) for name in ('model', 'observer', 'manifest')]
    paths += [Path(packet[name]) for name in ('weights_path', 'calibration_path', 'verification_path')]
    for relative in ('abc_recovery/runtime.py', 'abc_recovery/emission.py',
                     'abc_next/native/features.py', 'abc_followup/native/forecast.py', 'v6/observer.py',
                     'v6/neural.py', 'v6/data.py', 'v7/model.py', 'v7/data.py',
                     'v7/snapshot.py', 'v7/sources.py', 'v7/evaluation.py'):
        paths.append(experiment / relative)
    result = {'schema': 'hepta.closure.native-frozen-protocol.v1', 'study': 'native',
              'registered_ns': time.time_ns(), 'source_allocation_sha256': sha(args.allocation),
              'frozen_candidate_sha256': {str(p.resolve()): sha(p) for p in paths},
              'binary_sha256': sha(args.binary), 'pair_count': 64, 'seed_base': 361117,
              'source_role': 'closure_native', 'origin_role': 'unallocated_train', 'origin_pair_range': [512, 576],
              'views': ['clean', 'noise', 'occlusion', 'missing_trusted', 'conflict_untrusted', 'both_missing'],
              'prefix_action': 'refine_image', 'candidate_actions': ['refine_text', 'couple'],
              'selection': 'maximum frozen correctness probability among actions admitted by original native gates; refine_text breaks ties',
              'future_branch_rng_offset': 9000000, 'update_rule': 'no training; immutable weights and calibrator; previous observed utility bound to next owner tick',
              'carrier': '478 public preaction inputs; output [p, forecast32]; reference [1, forecast32]',
              'gate_values': {'min_confidence_ppm': 750000, 'max_ood_ppm': 500000,
                              'max_ece_ppm': 30000, 'max_false_acceptance_ppm': 4999,
                              'p95_latency_micros': 3000, 'p99_latency_micros': 8000,
                              'transient_bytes': 524288, 'checkpoint_bytes': 1048576,
                              'write_amplification_ppm': 4000000},
              'recovery_plan': ['SIGKILL first admitted pending decision; exact resume before generation',
                                'graceful resume after pair32 with committed outcomes'],
              'purpose': 'Independent-source causal owner mechanism verification',
              'inference_limits': ['64 new pairs do not requalify production or establish calibration/FAR ceilings',
                                   'No efficacy comparison or global NDU optimum is claimed',
                                   'Frozen action selection uses correctness probability; NDU is committed state binding, not an action-value optimizer',
                                   'Original Agentd owner and isolated native libraries; full daemon not built or deployed'],
              'authority': 'deny_all', 'outcomes_opened_before_registration': False}
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'protocol': str(args.output), 'sha256': sha(args.output), 'frozen_files': len(result['frozen_candidate_sha256'])}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'allocation', 'assets', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    freeze(parser.parse_args())
