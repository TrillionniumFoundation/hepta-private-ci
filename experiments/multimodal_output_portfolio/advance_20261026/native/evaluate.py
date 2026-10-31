"""Execute the entire frozen native qualification or confirmation census once."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import resource
import time
import traceback

import torch

from ..cases import registered_census, construct_case, prepare_task
from ..sources import load_rows
from ...next_20261025.media.ensemble_event import score_ensemble_observation
from .analysis import qualification, confirmation
from .client import feature_digest
from .common import sha, write
from .episode import run_episode
from .host import PortfolioHost


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def score_closed(directory, episode, target, identity, policy, mode, whole_wall, error=None):
    """Only here, after native lifecycle closure, attach private scoring labels."""
    first_path = directory / 'DECISION_H2.json'
    first = json.loads(first_path.read_text())['decision'] if first_path.exists() else None
    later_path = directory / 'DECISION_H1.json'
    later = json.loads(later_path.read_text())['decision'] if later_path.exists() else None
    initial = first['selected_action'] if first is not None else None
    last = later if later is not None else first
    final = last['selected_action'] if last is not None else None
    if episode is not None and episode['actual_output_bundle']:
        scores = score_ensemble_observation(episode['public_output_observation'], target)
        strict = bool(scores['joint_success'])
        utility = sum(scores['success'].values()) / 4
    else:
        scores, strict, utility = None, False, -1.
    acquire = int(initial == 101)
    emit = int(isinstance(final, int) and final < 100)
    probability = None if initial is None else next(t['confidence_ppm'] / 1e6 for t in first['ticks'] if t['action'] == initial)
    h1p = None if later is None or final is None else next(t['confidence_ppm'] / 1e6 for t in later['ticks'] if t['action'] == final)
    confidence = []
    if first is not None:
        for value in first['calibrated_success'][:100]:
            q = math.floor(float(value) * (1 << 24) + .5)
            confidence.append((1_000_000 - abs((1 << 24) - q) * 1_000_000 // (1 << 24)) / 1e6)
    decisions = [d for d in (first, later) if d is not None]
    ticks = [t for d in decisions for t in d['ticks']]
    return {'case_index': identity['case'], 'source_group': identity['source_group'], 'writer': identity['writer'],
        'speaker': identity['speaker'], 'view': identity['view'], 'route': first['route'] if first else episode['route'] if episode else identity['route'],
        'policy': policy, 'execution_mode': mode, 'initial_action': initial, 'final_action': final,
        'initial_selected_probability': probability, 'H1_selected_probability': h1p,
        'initial_code_confidence': confidence,
        'request_nonempty': bool(first and any(first['actual_mask'])), 'strict_success': strict, 'utility': utility,
        'registered_cost': .002 * (acquire + emit), 'acquire_attempts': acquire, 'emit_attempts': emit,
        'offline_target_code': 10 * target[0] + target[1], 'offline_scores': scores,
        'whole_execution_wall_ns': whole_wall, 'execution_error': error, 'actual_directory': str(directory),
        'native_ticks': len(ticks), 'native_execution_us': [t['native_execution_us'] for t in ticks],
        'planning_us': sum(d['planning_us'] for d in decisions),
        'native_abstentions': sum(t['native_abstain'] for t in ticks),
        'confidence_eligible_runtime_refusals': sum(t['confidence_ppm'] >= 750000 and not t['admitted'] for t in ticks),
        'owner_execution_us': sum(t['owner_us'] for t in ticks),
        'owner_peak_bytes': max((t['owner_peak_bytes'] for t in ticks), default=0),
        'actual_encoder_wall_ns': episode['encoder']['encoder_wall_ns'] if episode else None,
        'initial_forecast_evaluated_against_actual_terminal_outcome': True}


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1); torch.set_num_interop_threads(1); torch.use_deterministic_algorithms(True)
    began = time.perf_counter_ns()
    protocol = json.loads(args.protocol.read_text())
    # Source loader validates the full prospective dependency closure before
    # even opening registered image pixels. No source-driven configuration.
    role = 'qualification_id' if args.phase == 'qualification' else 'confirmation'
    corpus, selected = registered_census(args.cache, args.allocation, args.protocol, role)
    settings = json.loads(args.settings.read_text())
    templates = json.loads(args.templates.read_text())
    if set(templates) != {'dynamic', 'fixed_late'}:
        raise ValueError('Exactly the two registered policy templates are required')
    templates = {p: json.loads(Path(path).read_text()) for p, path in templates.items()}
    host = PortfolioHost(settings, args.output / 'event-observer')
    write(args.output / 'START.json', {'protocol_sha256': sha(args.protocol), 'phase': args.phase,
        'started_unix_ns': time.time_ns(), 'pair_count': selected['pair_count'], 'policies': list(templates),
        'host_asset_sha256': host.portfolio.asset_sha256, 'actual_ASR_observation_cache': host.speech_observer.receipt})
    rows, missing = [], []
    for pair in range(selected['pair_count']):
        case = construct_case(corpus, selected, pair, protocol['task_seed'])
        for route in ('image', 'text', 'audio', 'video'):
            policies = ['dynamic', 'fixed_late']
            if args.phase == 'confirmation':
                policies = ['dynamic'] if route in ('text', 'audio') else policies if pair % 2 == 0 else policies[::-1]
            for policy in policies:
                directory = args.output / 'ID' / f'pair-{pair:03d}' / route / policy
                directory.parent.mkdir(parents=True, exist_ok=True)
                template = templates[policy]
                mode = 'qualification_collection' if args.phase == 'qualification' else template['mode']
                begin = time.perf_counter_ns(); episode, error = None, None
                try:
                    prepared = prepare_task(case, route, args.audio_root, directory.parent / (policy + '-input'))
                    episode = run_episode(host, prepared.task, binary=args.binary, template=template,
                        directory=directory, case_id=f'{args.phase}.{pair}.{route}', source_group=case.source_group,
                        policy=policy, source_audio_root=args.audio_root, source_audio_rows=prepared.late_audio_rows, mode=mode)
                except Exception as exc:
                    error = {'type': type(exc).__name__, 'message': str(exc), 'traceback': traceback.format_exc()}
                    directory.mkdir(parents=True, exist_ok=True)
                    write(directory / 'EXECUTION_FAILURE.json', error)
                identity = {**case.identity, 'route': route}
                row = score_closed(directory, episode, case.batch.target.labels[0].tolist(), identity, policy, mode,
                                   time.perf_counter_ns() - begin, error)
                write(directory / 'OFFLINE_SCORE.json', row); rows.append(row)
        if (pair + 1) % 5 == 0:
            print(json.dumps({'phase': args.phase, 'source_pairs_completed': pair + 1, 'actual_policy_episodes': len(rows)}), flush=True)
    if args.phase == 'qualification':
        selected_ood, _ = load_rows(args.allocation, args.protocol, 'qualification_ood')
        for index, source in enumerate(selected_ood['recordings']):
            actual = args.audio_root / source['path']
            if sha(actual) != source['sha256']:
                raise ValueError('Actual absent-source waveform identity changed')
            for policy in ('dynamic', 'fixed_late'):
                directory = args.output / 'OOD' / f'source-{index:03d}' / policy
                directory.parent.mkdir(parents=True, exist_ok=True)
                episode = run_episode(host, None, binary=args.binary, template=templates[policy], directory=directory,
                    case_id=f'missing.{index}', source_group='speaker.' + source['speaker'],
                    policy=policy, mode='qualification_collection', missing=True)
                encoded = json.loads((directory / 'PUBLIC_ENCODING.json').read_text())
                first = json.loads((directory / 'DECISION_H2.json').read_text())['decision']
                initial = encoded['fresh_owner']['status']
                row = {'source_index': index, 'speaker': source['speaker'], 'policy': policy,
                    'source_waveform_sha256': source['sha256'], 'source_waveform_model_reads': 0,
                    'public_numeric_input_sha256': feature_digest(encoded['features']),
                    'actual_native_input_feature_sha256': first['ticks'][0]['feature_digest'],
                    'initial_numeric_state_sha256': digest_json({k: initial[k] for k in ('native_sequence', 'eligibility_q24', 'utility_q32')}),
                    'RNG_state_sha256': digest_json({'RNG': 'none; deterministic native forward; missing bypass'}),
                    'accepted': any(first['actual_mask']), 'real_original_owner_ticks': len(first['ticks']),
                    'closed_native_sequence': episode['closed_owner']['native_sequence'], 'actual_directory': str(directory)}
                write(directory / 'MISSING_OBSERVATION.json', row); missing.append(row)
            if (index + 1) % 100 == 0: print(json.dumps({'actual_missing_source_identities': index + 1, 'policy_requests': len(missing)}), flush=True)
        summary = {p: qualification(rows, missing, p) for p in ('dynamic', 'fixed_late')}
    else:
        summary = confirmation(rows, protocol['bootstrap_seed'], protocol['bootstrap_replicates'])
    host.portfolio.assert_frozen()
    # Recheck the same frozen closure after every actual execution, without
    # reopening source model observations or selecting a new candidate.
    load_rows(args.allocation, args.protocol, role)
    write(args.output / 'ROWS.json', rows)
    write(args.output / 'MISSING_ROWS.json', missing)
    report = {'schema': 'hepta.advance.native-evaluation.v1', 'phase': args.phase, 'summary': summary,
        'policy_episodes': len(rows), 'all_missing_physical_requests': len(missing),
        'protocol_sha256': sha(args.protocol), 'wall_ns': time.perf_counter_ns() - began,
        'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        'new_weight_training_steps': 0, 'authority': 'deny_all', 'daemon_deployment': False}
    write(args.output / 'REPORT.json', report)
    print(json.dumps(report))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--phase', choices=('qualification', 'confirmation'), required=True)
    for name in ('binary', 'templates', 'protocol', 'settings', 'cache', 'allocation', 'audio-root', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    run(p.parse_args())
