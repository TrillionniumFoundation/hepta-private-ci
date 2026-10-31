"""Receipt import negative controls; synthetic fixtures are not native executions."""

import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import tempfile

from . import native_adapter as native
from .execution import digest
from .verify import binding, rejected


def fixture(directory):
    initial = {'native_sequence': 0, 'anchor': None, 'eligibility_q24': [0] * 33,
               'history_digest': digest('initial'), 'late_audio_label': None}
    probability, mask = [0.] * 102, [False] * 102
    probability[2] = probability[10] = .8
    mask[10] = True
    law = [0.] * 100
    law[2] = law[10] = .5
    utility = [[float(a == t) for t in range(100)] for a in range(100)]
    moments = [math.exp(.004) * sum(p * math.exp(-2 * u) for p, u in zip(law, row)) for row in utility]
    moments += [math.exp(2)] * 2
    ticks = []
    for sequence, action in enumerate((2, 10), 1):
        ticks.append({'action': action, 'sequence': sequence, 'anchor': digest(['anchor', sequence]),
            'eligibility_before_q24': [sequence - 1] * 33, 'eligibility_after_q24': [sequence] * 33,
            'admitted': action == 10, 'native_abstain': action == 2, 'native_execution_us': 8,
            'owner_us': 11, 'owner_peak_bytes': 100})
    decision = {'selected_action': 10, 'calibrated_success': probability, 'moments': moments,
        'remaining': 1, 'initial': True, 'ticks': ticks, 'actual_mask': mask,
        'law': law, 'prefix_digest': digest('input'), 'parent_outcome_digest': None, 'planning_us': 3}
    documents = {'descriptor.json': {'policy': 'fixed_initial', 'max_native_ticks': 8},
        'PUBLIC_ENCODING.json': {'fresh_owner': {'status': initial}},
        'DECISION_H2.json': {'decision': decision,
            'status': {'native_sequence': 2, 'anchor': ticks[-1]['anchor']}}}
    for name, value in documents.items():
        (directory / name).write_text(json.dumps(value))
    return utility, documents


def verify(repository):
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        utility, documents = fixture(directory)
        snapshot = native.import_decision(directory)
        checked = native.current_terminal_backup(snapshot, binding(), utility, utility, emit_cost=.002)
        assert checked['plan']['actions']['current'] == 'code010'
        assert checked['actual_costs']['native_execution_us'] == 16
        path = directory / 'DECISION_H2.json'
        altered = json.loads(json.dumps(documents[path.name]))
        altered['decision']['actual_mask'][2] = True
        path.write_text(json.dumps(altered))
        assert rejected(lambda: native.import_decision(directory))
        altered = json.loads(json.dumps(documents[path.name]))
        altered['decision']['ticks'][1]['eligibility_before_q24'][0] = 7
        path.write_text(json.dumps(altered))
        assert rejected(lambda: native.import_decision(directory))
        altered = json.loads(json.dumps(documents[path.name]))
        altered['decision']['selected_action'] = 2
        path.write_text(json.dumps(altered))
        assert rejected(lambda: native.import_decision(directory))
        future = {**snapshot, 'ticks': [replace(snapshot['ticks'][0], action='code101')]}
        assert rejected(lambda: native.current_terminal_backup(future, binding(), utility, utility, emit_cost=.002))
    return {'schema': 'hepta.repair.native-adapter-verification.v1', 'passed': True,
        'owner_source': native.verify_owner_source(repository),
        'receipt_import_scope': 'Synthetic original-format receipts; actual Rust binary was not executed.',
        'actual_current_mask_overrides_confidence': True, 'actual_selected_code': 10,
        'tampered_mask_sequence_selection_rejected': True, 'unknown_future_owner_law_rejected': True,
        'real_native_episodes_executed': 0, 'real_independent_calibration_fit': False,
        'adapter_sha256': native.file_sha(native.__file__), 'verification_sha256': native.file_sha(__file__),
        'unresolved_execution_closure': [
            'Exact advance_20261026 native binary and its same-build dependency objects',
            'Selected semantic weight export and bound operation calibration/verification',
            'Complete pinned host renderer/observer assets for that native package',
            'Actual advance_20261026 decision/owner/media execution receipts'],
        'other_task_rlib_substituted': False,
        'available_v6_assets_are_not_claimed_to_be_the_later_native_closure': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.repository)
    with args.output.open('x') as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write('\n')
    print(json.dumps(result))
