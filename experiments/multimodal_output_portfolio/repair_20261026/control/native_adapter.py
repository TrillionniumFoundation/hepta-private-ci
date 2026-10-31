"""Opt-in bridge to the original agentd owner, without rewriting frozen studies.

Current-only execution uses the existing H1/fixed_initial path. Full dynamic
episodes can be measured, but are never represented as validated future-owner
forecasts. The importer checks original ordered ticks, state continuity,
admission and the actually committed selection before exposing a finite model.
"""

import hashlib
import json
import math
from pathlib import Path

from .calibration import execution_identity
from .execution import Action, ExecutionState, Outcome, Tick, backup, digest, require

ORIGINAL_OWNER_SHA256 = '4d56cc99d0edb1018734aebf70dc715de8df7846a2a9c4f2edb4230a0fc87faf'


def read(path):
    return json.loads(Path(path).read_text())


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_owner_source(repository):
    path = Path(repository) / 'codex-rs/hepta-agentd/src/neuron_runtime.rs'
    actual = file_sha(path)
    require(actual == ORIGINAL_OWNER_SHA256, 'Original agentd owner source identity changed')
    return {'source': str(path), 'sha256': actual, 'exact_original_owner_source_available': True,
            'same_binary_or_dependency_objects_implied': False}


def owner_identity(anchor, sequence, eligibility):
    return digest({'checkpoint': anchor, 'sequence': sequence, 'eligibility_q24': eligibility})


def import_decision(directory, phase='H2'):
    directory = Path(directory)
    require(phase in ('H2', 'H1'), 'Only actual recorded native decision phases are supported')
    descriptor = read(directory / 'descriptor.json')
    decision_path = directory / f'DECISION_{phase}.json'
    envelope = read(decision_path)
    decision = envelope['decision']
    before = (read(directory / 'PUBLIC_ENCODING.json')['fresh_owner']['status'] if phase == 'H2'
              else read(directory / 'COMMITTED_EXTERNAL_AUDIO.json')['status'])
    probability = [float(v) for v in decision['calibrated_success']]
    moments = [float(v) for v in decision['moments']]
    require(len(probability) == len(moments) == 102 and all(math.isfinite(p) and 0 <= p <= 1 for p in probability)
            and all(math.isfinite(m) and m > 0 for m in moments), 'Invalid actual native forecast')
    q = 1 << 24
    confidence = [(1_000_000 - abs(q - math.floor(p * q + .5)) * 1_000_000 // q) for p in probability]
    eligible = [a for a in range(102) if a != 100 and confidence[a] >= 750000 and
                (a != 101 or decision['remaining'] == 2 and decision['initial'] and descriptor['policy'] != 'fixed_initial')]
    ticks = decision['ticks']
    require([t['action'] for t in ticks] == (eligible or [0]), 'Actual candidate scanning order differs from original policy')
    actual_mask = [False] * 102
    sequence, anchor, eligibility = before['native_sequence'], before['anchor'], before['eligibility_q24']
    model_ticks = []
    for tick in ticks:
        require(tick['sequence'] == sequence + 1 and tick['eligibility_before_q24'] == eligibility,
                'Native owner sequence/eligibility continuity failed')
        require(type(tick['admitted']) is bool and (not tick['admitted'] or not tick['native_abstain']),
                'Native abstention cannot become admission')
        old = owner_identity(anchor, sequence, eligibility)
        sequence, anchor, eligibility = tick['sequence'], tick['anchor'], tick['eligibility_after_q24']
        admitted = tick['admitted'] and tick['action'] in eligible
        actual_mask[tick['action']] = admitted
        model_ticks.append(Tick(f"code{tick['action']:03d}", old,
                                owner_identity(anchor, sequence, eligibility), admitted))
    require(decision['actual_mask'] == actual_mask, 'Reported current mask differs from actual native ticks')
    feasible = [a for a, allowed in enumerate(actual_mask) if allowed]
    selected = min(feasible, key=lambda a: (moments[a], a)) if feasible else None
    if descriptor['policy'] == 'fixed_late' and actual_mask[101]:
        selected = 101
    require(selected == decision['selected_action'], 'Committed selection differs from actual mask and declared policy')
    require(envelope['status']['native_sequence'] == sequence and envelope['status']['anchor'] == anchor,
            'Decision status does not match the completed native tick sequence')
    spent = sum(t['native_execution_us'] for t in ticks)
    return {'schema': 'hepta.repair.native-execution-import.v1',
            'execution_sha256': execution_identity(descriptor), 'decision_sha256': file_sha(decision_path),
            'native_checkpoint_binding': owner_identity(before['anchor'], before['native_sequence'], before['eligibility_q24']),
            'history_sha256': digest(before['history_digest']), 'evidence_sha256': digest({
                'prefix': decision['prefix_digest'], 'parent_outcome': decision['parent_outcome_digest'],
                'late_label': before['late_audio_label']}),
            'remaining_native_ticks': descriptor['max_native_ticks'] - before['native_sequence'],
            'ticks': model_ticks, 'selected': selected, 'actual_mask': actual_mask,
            'belief': [float(v) for v in decision['law']], 'native_moments': moments,
            'actual_costs': {'native_execution_us': spent, 'owner_execution_us': sum(t['owner_us'] for t in ticks),
                'planning_us': decision['planning_us'], 'owner_peak_bytes': max(t['owner_peak_bytes'] for t in ticks),
                'native_tick_count': len(ticks)},
            'future_owner_law': 'unmodelled; receipt identities do not identify future transition probabilities',
            'host_wide_resource_SLA': False}


def current_terminal_backup(snapshot, binding, utility, strict, *, emit_cost):
    """Use the real current owner mask and public posterior, with a frozen table.

An acquire candidate needs an independently supplied future law and is refused
here. Native timing remains measured timing, not an invented utility price.
This validates the measured canonical renderer model, not future host failures.
"""
    require(all(t.action != 'code101' for t in snapshot['ticks']),
            'Unknown future owner law: use current-only execution or collect complete policy rollouts')
    require(binding.resource_names == ('native_ticks',) and len(utility) == len(strict) == 100
            and all(len(row) == 100 for row in utility) and all(len(row) == 100 for row in strict),
            'Native tick resource dimension and fixed 100-endpoint tables required')
    belief = snapshot['belief']
    require(len(belief) == 100 and all(math.isfinite(p) and p >= 0 for p in belief)
            and math.isclose(sum(belief), 1., rel_tol=0., abs_tol=1e-10), 'Normalized public posterior required')
    actions = {}
    for tick in snapshot['ticks']:
        code = int(tick.action[4:])
        actions[tick.action] = Action((0,), tuple(Outcome(p, emit_cost, (0,), 'terminal_delivery',
            utility=float(utility[code][target]), strict_success=float(strict[code][target]))
            for target, p in enumerate(belief)))
    state = ExecutionState(1, snapshot['native_checkpoint_binding'], snapshot['history_sha256'],
        snapshot['evidence_sha256'], (snapshot['remaining_native_ticks'],), tuple(actions),
        tuple(snapshot['ticks']), actions, screening_cost=0., screening_resources=(len(snapshot['ticks']),))
    plan = backup({'current': state}, binding, 'current')
    selected = None if snapshot['selected'] is None else f"code{snapshot['selected']:03d}"
    require(plan['actions']['current'] == selected, 'Finite backup disagrees with actually committed native action')
    if selected is not None:
        require(math.isclose(plan['moment'], snapshot['native_moments'][snapshot['selected']], rel_tol=1e-10),
                'Finite backup differs from frozen native endpoint/cost arithmetic')
    return {'plan': plan, 'actual_costs': snapshot['actual_costs'], 'actual_owner_mask_consumed': True,
            'future_native_resources_fitted': False, 'host_delivery_failure_law_fitted': False}


def run_current_only(host, public_task, *, binary, expected_binary_sha256, template, directory,
                     case_id, source_group, numeric=True, missing=False):
    """Execute the actual original owner with H1; no future-owner assumption."""
    from ...advance_20261026.native.episode import run_episode
    require(file_sha(binary) == expected_binary_sha256, 'Native binary identity differs')
    result = run_episode(host, public_task, binary=binary, template=template, directory=directory,
        case_id=case_id, source_group=source_group, policy='fixed_initial', mode='development',
        source_audio_root=None, source_audio_rows=None, numeric=numeric, missing=missing)
    require(result['actual_external_acquisitions'] == 0, 'Current-only execution acquired future evidence')
    snapshot = import_decision(directory)
    receipt = {'schema': 'hepta.repair.current-only-native-run.v1', 'binary_sha256': expected_binary_sha256,
        'execution_sha256': snapshot['execution_sha256'], 'selected': snapshot['selected'],
        'actual_costs': snapshot['actual_costs'], 'whole_episode_wall_ns': result['whole_episode_wall_ns'],
        'actual_original_owner_executed': True, 'future_owner_assumptions_used': False,
        'empirical_qualification_claimed': False, 'host_wide_resource_SLA': False}
    with (Path(directory) / 'CONTROL_EXECUTION.json').open('x') as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    return result, snapshot


def measure_complete_policy(host, public_task, *, binary, expected_binary_sha256, template, directory,
                            case_id, source_group, policy, source_audio_root, source_audio_rows):
    """Measure complete real continuation; confidence-only forecasts remain unqualified."""
    from ...advance_20261026.native.episode import run_episode
    require(file_sha(binary) == expected_binary_sha256 and policy in ('dynamic', 'fixed_late'),
            'Pinned original binary and registered measurement policy required')
    result = run_episode(host, public_task, binary=binary, template=template, directory=directory,
        case_id=case_id, source_group=source_group, policy=policy, mode='qualification_collection',
        source_audio_root=source_audio_root, source_audio_rows=source_audio_rows)
    snapshots = [import_decision(directory)]
    if result['actual_external_acquisitions']:
        snapshots.append(import_decision(directory, 'H1'))
    return {'episode': result, 'actual_decisions': snapshots,
            'measurement_only': True, 'future_law_validated': False,
            'terminal_label_source': 'Score only after closure; load_native retains refusal/failure as zero success.'}
