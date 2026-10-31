"""Old-development choice of one strong fixed same-access reference policy."""

import argparse
import json
import math
from pathlib import Path

import numpy as np

from .calibrate import calibrated
from .common import sha, write


def run(args):
    public = np.load(args.calibration / 'old-development-public.npz')
    offline = json.loads((args.calibration / 'old-development-offline-labels.json').read_text())
    calibration = json.loads((args.calibration / 'calibration.json').read_text())
    labels = np.asarray(offline['labels'])
    outcomes = {p: [] for p in ('fixed_initial', 'fixed_late', 'dynamic')}
    for row in offline['acquisitions']:
        i = row['index']
        law = public['law'][i]
        code = int(law.argmax())
        emit_admitted = calibrated(law[code], calibration['roles']['emit']) >= .75
        acquire_admitted = calibrated(row['raw'], calibration['roles']['acquire']) >= .75
        emit_moment = math.exp(.004) * (1 - (1 - math.exp(-2)) * law[code])
        for policy in outcomes:
            use_audio = bool(acquire_admitted and (policy == 'fixed_late' or policy == 'dynamic'
                             and (not emit_admitted or row['moment'] < emit_moment)))
            if use_audio:
                accepted = row['continuation'] >= 0
                utility = row['success'] if accepted else -1
                cost = .002 + (.002 if accepted else 0.)
            else:
                accepted = bool(emit_admitted)
                utility = int(code == labels[i]) if accepted else -1
                cost = .002 if accepted else 0.
            outcomes[policy].append((utility, cost, use_audio, accepted))
    results = {}
    for policy, rows in outcomes.items():
        array = np.asarray(rows, dtype=float)
        results[policy] = {'cases': len(rows), 'certainty_equivalent': float(-np.log(np.exp(-2 * (array[:, 0] - array[:, 1])).mean()) / 2),
            'strict_task_success_including_rejection_as_failure': float((array[:, 0] == 1).mean()),
            'mean_registered_cost': float(array[:, 1].mean()), 'actual_cached_source_CNN_acquisitions': int(array[:, 2].sum()),
            'terminal_rejections': int((1 - array[:, 3]).sum())}
    selected = max(('fixed_initial', 'fixed_late'), key=lambda p: (results[p]['certainty_equivalent'], p == 'fixed_initial'))
    result = {'schema': 'hepta.advance.native-reference-selection.v1', 'selection_rule': 'Max old-development realized entropic CE; fixed_initial wins exact ties',
        'selected_reference': selected, 'primary_contrast': 'dynamic minus ' + selected,
        'candidate_references': ['fixed_initial', 'fixed_late'], 'old_development': results,
        'source_scope': 'Previously selected old image/video sources; actual frozen CNN observation cache; no new source',
        'original_owner_resource_refusals_in_this_selection': 'not simulated; independently measured during real owner evaluation',
        'future_waveform_read_online_before_acquire': False, 'calibration_sha256': sha(args.calibration / 'calibration.json'),
        'source_record_sha256': sha(args.calibration / 'old-development-offline-labels.json'), 'new_confirmation_used': False}
    write(args.output, result)
    print(json.dumps(result))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--calibration', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    run(p.parse_args())
