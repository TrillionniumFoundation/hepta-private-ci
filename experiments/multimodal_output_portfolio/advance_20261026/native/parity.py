"""Old public-cache parity and original owner admission; no renderer claim."""

import argparse
import json
from pathlib import Path
import time

import numpy as np

from ..control.dynamic import plan
from .client import Native, descriptor
from .common import sha, write


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    template = json.loads(args.template.read_text())
    head = json.loads(Path(template['weights_path']).read_text())
    calibration = json.loads(Path(template['calibration_path']).read_text())
    likelihood = json.loads(Path(template['likelihood_path']).read_text())['pair_observation_by_target']
    public = np.load(args.calibration / 'old-development-public.npz')
    # Route/source metadata are used for audit grouping; hidden target is never
    # passed to either prediction implementation or the owner.
    rows = json.loads((args.calibration / 'old-development-offline-labels.json').read_text())['source']['cases_identity']
    maximum = {'posterior': 0., 'moment': 0., 'raw_success': 0.}
    resources, choices, changed = [], [], 0
    start = time.perf_counter_ns()
    for i, row in enumerate(rows):
        if i >= args.limit: break
        remaining = 2 if row['route'] in ('image', 'video') else 1
        case = args.output / f'case-{i:04d}'
        spec = descriptor(template, case, f'old.parity.{i}', f'old.development.{row["pair"]}', 'dynamic')
        native = Native(args.binary, spec, case / 'owner')
        features = np.concatenate((public['features'][i].ravel(), public['raw_probabilities'][i].ravel())).tolist()
        result = native.decide(f'r{i}', f'e{i}', features, row['route'], remaining)
        decision = result['decision']
        q = np.asarray(decision['law'], dtype=float)
        expected = plan(head['utility_action_by_target'], head['strict_success_action_by_target'], public['law'][i],
            likelihood, calibration=calibration, current_actual_mask=decision['actual_mask'], remaining_decisions=remaining)
        moments = np.r_[expected['immediate']['code_moments'], np.exp(2), expected['acquire_moment']]
        raw = np.r_[expected['immediate']['code_strict_success'], 0., expected['acquire_strict_success_probability']]
        maximum['posterior'] = max(maximum['posterior'], float(np.max(np.abs(q - public['law'][i]))))
        maximum['moment'] = max(maximum['moment'], float(np.max(np.abs(moments - np.asarray(decision['moments'], dtype=float)))))
        maximum['raw_success'] = max(maximum['raw_success'], float(np.max(np.abs(raw - np.asarray(decision['raw_success'], dtype=float)))))
        actual_action = decision['selected_action'] if decision['selected_action'] is not None else -1
        changed += int(actual_action != expected['action'])
        choices.append(actual_action)
        resources.extend(tick['native_execution_us'] for tick in decision['ticks'])
        write(case / 'decision.json', result)
        if actual_action >= 0:
            native.checked({'kind': 'cancel', 'request_id': f'r{i}', 'decision_digest': result['decision_digest']})
        write(case / 'closed.json', native.close())
        if (i + 1) % 64 == 0: print(json.dumps({'native_independent_streams': i + 1}), flush=True)
    missing = args.output / 'old-missing-diagnostic'
    spec = descriptor(template, missing, 'old.missing.structural', 'old.source.held-identity', 'dynamic')
    native = Native(args.binary, spec, missing / 'owner')
    result = native.decide('missing', 'missing-episode', [0] * 176, 'image', missing=True)
    write(missing / 'decision.json', result)
    write(missing / 'closed.json', native.close())
    report = {'schema': 'hepta.advance.native-public-parity.v1', 'independent_owner_streams': len(choices),
        'model_weights_sha256': template['pins']['weights'], 'binary_sha256': sha(args.binary),
        'maximum_absolute_difference': maximum, 'policy_mismatches_with_actual_mask': changed,
        'native_acquire_selections': choices.count(101), 'native_rejections': choices.count(-1),
        'native_tick_count': len(resources), 'p95_native_execution_us': float(np.percentile(resources, 95)),
        'p99_native_execution_us': float(np.percentile(resources, 99)), 'maximum_native_execution_us': max(resources),
        'structural_missing_selected': result['decision']['selected_action'],
        'actual_missing_gate_ticks': len(result['decision']['ticks']),
        'four_modality_output_generated': False, 'source_scope': 'Previously used old development; cancellation after forecast',
        'new_source_qualification': False, 'wall_ns': time.perf_counter_ns() - start,
        'passed': changed == 0 and max(maximum.values()) < 1e-10 and result['decision']['selected_action'] is None}
    write(args.output / 'REPORT.json', report)
    print(json.dumps(report))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'template', 'calibration', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--limit', type=int, default=512)
    run(p.parse_args())
