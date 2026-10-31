"""Register a larger, explicitly historical development-only calibration stage."""

import argparse
import hashlib
import json
from pathlib import Path
import pickletools
import time
import zipfile

from .common import AREA, SHARED, pins, sha, write


MANIFEST = SHARED / 'abc2-runs/source-recovery-001/source-manifest.json'
MANIFEST_SHA = '60c24d44e12eb3defb3b1b8146d91879b84918b057e0524117137d7e4f793058'
PREDICTOR_SHA = '2ea073f7de0cf0a134c94cb0a683e3924733dd7206cf619264e370bbce2f37f8'
SALT = 'hepta-native-h2-expanded-old-calibration-20261026-v1'


def stored_source_ids(path):
    """Inspect only pickle string opcodes, without executing pickle or Torch."""
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith('/data.pkl') or name == 'data.pkl']
        if len(names) != 1: raise ValueError('Unexpected historical tensor archive')
        return {arg for _, arg, _ in pickletools.genops(archive.read(names[0]))
                if isinstance(arg, str) and arg.startswith('mnist:')}


def register(predictor, first_failure, second_failure, output):
    if sha(MANIFEST) != MANIFEST_SHA or sha(predictor) != PREDICTOR_SHA:
        raise ValueError('Original source manifest or fixed full-public predictor changed')
    failures = [json.loads(path.read_text()) for path in (first_failure, second_failure)]
    if any(row['new_source_candidate_admitted'] is not False for row in failures):
        raise ValueError('Preserve both original failures, do not overwrite their stopping decisions')
    if failures[1]['predictor_sha256'] != PREDICTOR_SHA:
        raise ValueError('The expanded stage must keep the failed second candidate weights and cuts')
    manifest = json.loads(MANIFEST.read_text())
    paths = [SHARED / f'abc4-control-runs/development-001/seed-17/{part}/data.pt' for part in ('fit', 'selection')]
    fit, pilot = [stored_source_ids(path) for path in paths]
    if (fit != set(manifest['roles']['forecast_fit']['source_ids'][960:1472])
            or pilot != set(manifest['roles']['forecast_calibration']['source_ids'][896:1152])):
        raise ValueError('Historical predictor fitting or pilot source identity changed')
    source_ids = manifest['roles']['forecast_calibration']['source_ids']
    eligible = [i for i in range(len(source_ids) // 2) if not (set(source_ids[2 * i:2 * i + 2]) & (fit | pilot))]
    if len(eligible) != 872:
        raise ValueError('Expected exactly 872 non-pilot historical calibration pairs')
    def rank(case):
        return hashlib.sha256((SALT + ':' + '|'.join(source_ids[2 * case:2 * case + 2])).encode()).digest()
    ordered = sorted(eligible, key=rank)
    roles = {phase: [{'pair_index': case, 'source_ids': source_ids[2 * case:2 * case + 2]}
                     for case in ordered[start:start + 400]]
             for phase, start in (('calibration', 0), ('validation', 400))}
    deps = [MANIFEST, predictor, first_failure, second_failure, *paths]
    write(output, {'schema': 'hepta.next.native-h2-expanded-old-protocol.v1',
          'registered_unix_ns': time.time_ns(), 'source_manifest_sha256': MANIFEST_SHA,
          'predictor_path': str(predictor.resolve()), 'predictor_sha256': PREDICTOR_SHA,
          'frozen_candidate_sha256': pins(deps), 'salt': SALT, 'roles': roles,
          'source_role': 'forecast_calibration', 'eligible_old_pairs': 872,
          'excluded_current_predictor_fit_source_ids': len(fit), 'excluded_previous_pilot_source_ids': len(pilot),
          'pair_count_per_phase': 400, 'unallocated_old_pairs': ordered[800:],
          'ID_view': 'one fixed cycling ID view by within-phase rank', 'OOD_view': 'both_missing',
          'future_draws': 1, 'decision_states': 5, 'actions_per_state': 5, 'actual_outputs': 40000,
          'predictor_retraining': False, 'cut_or_bin_changes': False,
          'old_feasibility_gates': {'ECE_point_max': .03, 'ID_acceptance_min': .25, 'OOD_false_pairs': 0},
          'native_original_four_gates_changed': False,
          'new_source_roles_or_gates_changed': False, 'new_XNIST_outcomes_opened': False,
          'independent_writer_or_new_confirmation_claimed': False,
          'after_outcomes': 'No reselection, extra old72, new sources, head/cut/bin changes or threshold relaxation',
          'purpose': 'Isolate calibration sample-size/transfer instability on additional old development pairs'})


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('predictor', 'first-failure', 'second-failure', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    a = p.parse_args(); register(a.predictor, a.first_failure, a.second_failure, a.output)
    print(json.dumps({'protocol_sha256': sha(a.output), 'old_pairs': 800, 'actual_outputs': 40000}))
