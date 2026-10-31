"""Posthoc constant220ms diagnostic; metadata only, never a second media emission."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import resource
import subprocess
import sys
import time
import traceback

import numpy as np


RATE, FRAME, QUANTUM = 44100, 1764, 882
POLICIES = ('fixed_timeout_240ms', 'derived_fixed_timeout_220ms', 'learned_causal_timeout')
MODULE = 'experiments.multimodal_output_portfolio.abc_recovery.temporal_static220'
MEDIA_SUFFIXES = {'.mkv', '.mpg', '.mp4', '.wav', '.pcm', '.yuv'}


def metadata_bytes(path):
    path = Path(path)
    if path.suffix.lower() in MEDIA_SUFFIXES or path.stat().st_size > 2000000:
        raise ValueError('This diagnostic only reads small metadata; original media must not be reopened')
    return path.read_bytes()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(metadata_bytes(path))


def save(path, data):
    with Path(path).open('xb') as stream:
        stream.write(data)


def save_json(path, value):
    save(path, (json.dumps(value, sort_keys=True, indent=2) + '\n').encode())


def pinned(path, expected):
    data = metadata_bytes(path)
    if digest(data) != expected:
        raise ValueError(f'Original metadata pin changed: {path}')
    return json.loads(data)


def usage():
    return time.monotonic(), time.process_time()


def cost(before):
    return {'wall_seconds': time.monotonic() - before[0], 'cpu_seconds': time.process_time() - before[1],
            'maximum_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}


def fixed_schedule(events, timeout_ms, frame_count=75, audio_samples=131328):
    """Independent closed-form fixed deadline, not the original simulator."""
    if timeout_ms not in (220, 240):
        raise ValueError('Only original240 reproduction and the sole220 diagnostic are permitted')
    if not (frame_count - 1) * FRAME < audio_samples <= frame_count * FRAME:
        raise ValueError('Every registered video slot needs its exact nonempty audio chunk')
    lookup = {(event['channel'], event['index']): event for event in events}
    expected = {(channel, index) for index in range(frame_count) for channel in ('video', 'audio')}
    if len(lookup) != len(events) or set(lookup) != expected:
        raise ValueError('Packet census must retain every registered source slot exactly once')
    for (channel, index), event in lookup.items():
        release = (index + 1) * FRAME
        if channel == 'audio':
            release = min(release, audio_samples)
        arrival = event['arrival_ticks']
        if (event['release_ticks'] != release or event['source_pts_ticks'] != index * FRAME
                or event['environment_dropped'] != (arrival is None)):
            raise ValueError('Source header or permanent drop identity changed')
        if arrival is not None and (type(arrival) is not int or not 0 <= arrival - release <= 220 * RATE // 1000):
            raise ValueError('Event outside the declared non-dropped delay bound')
    commits, delivered, previous = [], {'video': [], 'audio': []}, 0
    for index in range(frame_count):
        release, deadline = (index + 1) * FRAME, (index + 1) * FRAME + timeout_ms * RATE // 1000
        arrivals = [lookup[(channel, index)]['arrival_ticks'] for channel in ('video', 'audio')]
        if previous > deadline:
            raise ValueError('Earlier committed prefix violates the fixed deadline')
        if any(value is None for value in arrivals):
            commit = deadline
        else:
            earliest = max(previous, release, *arrivals)
            commit = min(deadline, ((earliest + QUANTUM - 1) // QUANTUM) * QUANTUM)
        commits.append(commit)
        previous = commit
        for channel, arrival in zip(('video', 'audio'), arrivals):
            delivered[channel].append(arrival is not None and arrival <= commit)
    lengths = [min(FRAME, audio_samples - index * FRAME) for index in range(frame_count)]
    q_video = sum(delivered['video']) / frame_count
    q_audio = sum(length for length, present in zip(lengths, delivered['audio']) if present) / audio_samples
    coverage = sum(a and v for a, v in zip(delivered['audio'], delivered['video'])) / frame_count
    latency = [(tick - (index + 1) * FRAME) / RATE for index, tick in enumerate(commits)]
    mean_latency = sum(latency) / frame_count
    loss = .55 * (1 - q_video * q_audio) + .25 * (1 - coverage) + .20 * mean_latency / .240
    return {'commit_ticks': commits, 'delivered': delivered, 'q_video': q_video, 'q_audio': q_audio,
            'joint_delivery_completion': q_video * q_audio, 'valid_alignment_coverage': coverage,
            'mean_simulated_delivery_latency_seconds': mean_latency,
            'simulated_delivery_latency_seconds': latency, 'loss': loss}


def same_number(left, right, name):
    if not math.isclose(left, right, rel_tol=0, abs_tol=1e-12):
        raise ValueError(f'Original240 reproduction changed {name}: {left} != {right}')


def bind_environment_to_pinned_trace(events, simulation):
    """Observed actions alone do not uniquely identify the original arrival table."""
    keys = ('channel', 'index', 'source_pts_ticks', 'release_ticks', 'arrival_ticks')
    finite = {tuple(event[key] for key in keys) for event in events if event['arrival_ticks'] is not None}
    observed = {tuple(header) for decision in simulation['public_trace']
                for header in decision['public_state']['arrived_headers']}
    if finite != observed:
        raise ValueError('Existing finite arrivals differ from complete original hash-pinned public headers')


def reproduce(schedule, simulation, row, observed, ledger):
    if schedule['commit_ticks'] != simulation['commit_ticks'] or schedule['delivered'] != simulation['delivered']:
        raise ValueError('Independent240 formula did not reproduce every actual commit/delivery choice')
    if [entry['virtual_commit_ticks'] for entry in ledger] != schedule['commit_ticks']:
        raise ValueError('Original actual commit ledger differs from the240 simulation')
    for index, entry in enumerate(ledger):
        if entry['index'] != index or any(entry['delivered'][channel] != schedule['delivered'][channel][index]
                                        for channel in ('video', 'audio')):
            raise ValueError('Original ledger delivery flags changed')
    if not row['completed_and_fidelity_passed'] or not observed['content_fidelity_passed']:
        raise ValueError('Original media were not completely emitted and verified')
    if observed['valid_alignment_clock_error_seconds'] not in (0, None):
        raise ValueError('Structural matched-source clock assumption is not satisfied')
    if observed['valid_alignment_coverage'] > 0 and observed['valid_alignment_clock_error_seconds'] is None:
        raise ValueError('Valid source alignment is missing its observed clock')
    if observed['video_frames'] != 75 or observed['audio_samples_per_channel'] != 131328:
        raise ValueError('Original media census changed')
    for name in ('q_video', 'q_audio', 'joint_delivery_completion', 'valid_alignment_coverage', 'loss'):
        same_number(schedule[name], row[name], name)
    same_number(schedule['mean_simulated_delivery_latency_seconds'],
                simulation['mean_simulated_delivery_latency_seconds'], 'mean simulated latency')
    if len(row['simulated_delivery_latency_seconds']) != 75:
        raise ValueError('Original latency census changed')
    for new, old in zip(schedule['simulated_delivery_latency_seconds'], row['simulated_delivery_latency_seconds']):
        same_number(new, old, 'per-slot simulated latency')


def descriptive_statistics(rows, speakers):
    lookup = {(row['speaker'], row['scenario'], row['policy']): row for row in rows}
    expected = {(speaker, scenario, policy) for speaker in speakers for scenario in range(4) for policy in POLICIES}
    if len(lookup) != len(rows) or set(lookup) != expected:
        raise ValueError('Descriptive inference retains complete paired speaker/scenario/policy cells')
    cubes = {name: np.array([[[lookup[(speaker, scenario, policy)][name] for policy in POLICIES]
                              for scenario in range(4)] for speaker in speakers])
             for name in ('loss', 'joint_delivery_completion')}

    def ndu(values, axes):
        scaled = 4 * values
        maximum = np.max(scaled, axis=axes, keepdims=True)
        return -np.squeeze(maximum + np.log(np.mean(np.exp(scaled - maximum), axis=axes, keepdims=True))) / 4

    resamples = np.random.default_rng(9037007).integers(0, len(speakers), size=(4000, len(speakers)))
    ndu_delta = (ndu(cubes['loss'][resamples, :, 2], (1, 2)) - ndu(cubes['loss'][resamples, :, 1], (1, 2)))
    coverage_delta = (cubes['joint_delivery_completion'][resamples, :, 2]
                      - cubes['joint_delivery_completion'][resamples, :, 1]).mean(axis=(1, 2))
    summaries = {}
    for index, policy in enumerate(POLICIES):
        selected = [row for row in rows if row['policy'] == policy]
        summaries[policy] = {'NDU': float(ndu(cubes['loss'][:, :, index], (0, 1))),
                             'mean_loss': float(cubes['loss'][:, :, index].mean()),
                             'p95_loss': float(np.quantile(cubes['loss'][:, :, index], .95)),
                             'joint_delivery_completion': float(cubes['joint_delivery_completion'][:, :, index].mean()),
                             'mean_simulated_delivery_seconds': float(np.mean([row['mean_simulated_delivery_latency_seconds'] for row in selected]))}
    return {'posthoc_descriptive_only': True, 'independent_speaker_groups': len(speakers),
            'scenarios_per_speaker': 4, 'bootstrap_replicates': 4000, 'bootstrap_seed': 9037007,
            'policy_summaries': summaries,
            'feedback_minus_220_NDU': summaries[POLICIES[2]]['NDU'] - summaries[POLICIES[1]]['NDU'],
            'feedback_minus_220_NDU_descriptive_95CI': np.quantile(ndu_delta, [.025, .975]).tolist(),
            'feedback_minus_220_joint_completion': summaries[POLICIES[2]]['joint_delivery_completion'] - summaries[POLICIES[1]]['joint_delivery_completion'],
            'feedback_minus_220_joint_completion_descriptive_95CI': np.quantile(coverage_delta, [.025, .975]).tolist(),
            'no_new_confirmatory_benefit_gate': True}


def bound_metadata(pin, root):
    path = Path(pin['path']).resolve()
    if not path.is_relative_to(root.resolve()) or path.stat().st_size != pin['bytes']:
        raise ValueError('Original metadata path/size differs from its pinned evaluation evidence')
    data = metadata_bytes(path)
    if digest(data) != pin['sha256']:
        raise ValueError('Original metadata evidence hash changed')
    return data


def worker(args):
    before = usage()
    args.output.mkdir(parents=True, exist_ok=False)
    try:
        protocol_bytes = metadata_bytes(args.protocol)
        protocol = json.loads(protocol_bytes)
        save(args.output / 'protocol.json', protocol_bytes)
        code_pins = {}
        for name in ('temporal_static220.py', 'temporal_static220_tests.py'):
            data = metadata_bytes(Path(__file__).with_name(name))
            save(args.output / name, data)
            code_pins[name] = digest(data)
        save_json(args.output / 'registration.json', {'posthoc': True, 'protocol_sha256': digest(protocol_bytes),
                  'source_code_pins': code_pins, 'new_timeout_ms': 220, 'new_actual_media_outputs': 0,
                  'original_evaluation_census_unchanged': 192})
        pins = protocol['original_pins']
        aggregate = pinned(args.original_aggregate, pins['evaluation_aggregate_sha256'])
        original_protocol = pinned(args.evaluation_root / 'protocol.json', pins['protocol_sha256'])
        original_result = pinned(args.evaluation_root / 'evaluation.json', pins['evaluation_sha256'])
        original_summary = pinned(args.evaluation_root / 'summary.json', pins['evaluation_summary_sha256'])
        original_process = pinned(args.evaluation_root.with_suffix('.process.json'), pins['evaluation_outer_process_sha256'])
        if not aggregate['artifact_audit']['passed'] or original_process['returncode'] != 0 or not original_summary['source_code_unchanged']:
            raise ValueError('The existing actual-media audit and process must have passed')
        speakers = protocol['census']['independent_speakers']
        if speakers != original_protocol['roles']['evaluation'] or len(speakers) != 16:
            raise ValueError('Original independent speaker census cannot change')
        evidence = {(row['speaker'], row['scenario'], row['policy']): row for row in aggregate['episode_evidence']}
        if len(evidence) != 192 or len(aggregate['episode_evidence']) != 192:
            raise ValueError('Original192-case evidence census changed')
        rows, maximum_advance, reference_identities = [], 0, []
        for speaker in speakers:
            for scenario in range(4):
                parent = args.evaluation_root / 'episodes' / f's{speaker}' / f'scenario-{scenario}'
                environment_bytes = metadata_bytes(parent / 'environment-private-events.json')
                environment = json.loads(environment_bytes)
                base_evidence = evidence[(speaker, scenario, POLICIES[0])]
                row = json.loads(bound_metadata(base_evidence['row'], args.evaluation_root))
                simulation = json.loads(bound_metadata(base_evidence['simulation'], args.evaluation_root))
                observed = json.loads(bound_metadata(base_evidence['readback'], args.evaluation_root))
                ledger = [json.loads(line) for line in bound_metadata(base_evidence['commit_ledger'], args.evaluation_root).splitlines()]
                expected_seed = int.from_bytes(hashlib.sha256(f"hepta-causal-av-stream-v1|{row['source_id']}|{scenario}".encode()).digest()[:8], 'big') % (2 ** 63)
                if environment['seed'] != expected_seed or environment['passed_to_policy'] is not False:
                    raise ValueError('Existing environment role or registered episode seed changed')
                media = base_evidence['media']
                if media['sha256'] != observed['actual_file_sha256'] or media['sha256'] != row['actual_file_sha256']:
                    raise ValueError('Previously verified real-media identity binding changed')
                if media['bytes'] != observed['actual_file_bytes'] or base_evidence['readback']['sha256'] != row['readback_sha256']:
                    raise ValueError('Previously verified readback identity binding changed')
                bind_environment_to_pinned_trace(environment['events'], simulation)
                base = fixed_schedule(environment['events'], 240)
                reproduce(base, simulation, row, observed, ledger)
                candidate = fixed_schedule(environment['events'], 220)
                if candidate['delivered'] != base['delivered'] or any(new > old for new, old in zip(candidate['commit_ticks'], base['commit_ticks'])):
                    raise ValueError('220 must preserve every actual payload choice and commit no later than240')
                adjusted = row['loss'] + .20 * (candidate['mean_simulated_delivery_latency_seconds'] - base['mean_simulated_delivery_latency_seconds']) / .240
                same_number(adjusted, candidate['loss'], 'independent220 loss versus latency-only update')
                candidate['loss'] = adjusted
                maximum_advance = max(maximum_advance, max(old - new for old, new in zip(base['commit_ticks'], candidate['commit_ticks'])))
                cell = {'speaker': speaker, 'scenario': scenario, 'source_id': row['source_id'],
                        'posthoc': True, 'environment_sha256': digest(environment_bytes),
                        'all_finite_arrivals_bound_to_original_public_headers': True,
                        'original240_reproduced': True, 'media_selection_identical': True,
                        'no_new_media_emission': True, 'reused_original_media': media,
                        'original_readback': base_evidence['readback'], 'original_commit_ledger': base_evidence['commit_ledger'],
                        'derived220_virtual_schedule': candidate}
                with (args.output / 'cells.jsonl').open('a') as stream:
                    stream.write(json.dumps(cell, sort_keys=True) + '\n')
                reference_identities.append({'speaker': speaker, 'scenario': scenario, 'source_id': row['source_id'], 'media_sha256': media['sha256']})
                for policy, schedule in ((POLICIES[0], base), (POLICIES[1], candidate)):
                    rows.append({'speaker': speaker, 'scenario': scenario, 'policy': policy, **schedule})
                feedback_pin = evidence[(speaker, scenario, POLICIES[2])]['row']
                feedback = json.loads(bound_metadata(feedback_pin, args.evaluation_root))
                if not feedback['completed_and_fidelity_passed']:
                    raise ValueError('The original feedback row is not a completed registered case')
                rows.append({**feedback, 'mean_simulated_delivery_latency_seconds': sum(feedback['simulated_delivery_latency_seconds']) / 75})
            print(f'posthoc diagnostic sources {len(reference_identities)//4}/16; no media generation', flush=True)
        descriptive = descriptive_statistics(rows, speakers)
        for policy in (POLICIES[0], POLICIES[2]):
            for name in ('NDU', 'mean_loss', 'p95_loss', 'joint_delivery_completion'):
                same_number(descriptive['policy_summaries'][policy][name], original_result['policy_summaries'][policy][name], 'original aggregate ' + name)
        save_json(args.output / 'derived-rows.json', rows)
        report = {'schema': 'hepta-causal-av-static220-posthoc-result-v1', 'protocol_sha256': digest(protocol_bytes),
                  'posthoc': True, 'validity_checks_passed': True, 'original240_cells_reproduced': 64,
                  'derived220_cells': 64, 'new_independent_observations': 0, 'new_actual_media_outputs': 0,
                  'new_codec_or_service_latency_measurements': 0, 'maximum_virtual_commit_advance_seconds': maximum_advance / RATE,
                  'all220_payload_choices_equal_original240': True, 'all220_commits_no_later_than240': True,
                  'all_finite_arrivals_bound_to_original_pinned_public_trace': True,
                  'descriptive_statistics': descriptive, 'original_result': original_result,
                  'original_registered_positive_gate_preserved': original_result['engineering_transport_benefit_gate_passed'],
                  'original_pins': pins, 'source_code_pins': code_pins, 'cells_sha256': digest(metadata_bytes(args.output / 'cells.jsonl')),
                  'formal_C_scientific_claim_upgraded': False,
                  'cost_scope': 'Only this metadata diagnostic and descriptive bootstrap; no new media generation/codec/service time. Original costs remain unchanged.',
                  'whole_worker_cost': cost(before),
                  'limitation': protocol['descriptive_statistics']['interpretation']}
        save_json(args.output / 'report.json', report)
        print(json.dumps(report, sort_keys=True), flush=True)
        return 0
    except BaseException as error:
        save_json(args.output / 'failure.json', {'error': f'{type(error).__name__}: {error}',
                  'traceback': traceback.format_exc(), 'cost': cost(before), 'original_results_modified': False})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('protocol', 'evaluation-root', 'original-aggregate', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    if args.worker:
        sys.exit(worker(args))
    if args.output.exists():
        raise FileExistsError('Posthoc diagnostic output cannot be overwritten')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    before, usage_before = time.monotonic(), resource.getrusage(resource.RUSAGE_CHILDREN)
    command = [sys.executable, '-m', MODULE, *sys.argv[1:], '--worker']
    with args.output.with_suffix('.process.log').open('x') as log:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            log.write(line)
            log.flush()
            print(line, end='', flush=True)
        returncode = process.wait()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    save_json(args.output.with_suffix('.process.json'), {'argv': command, 'returncode': returncode,
              'whole_child_process_wall_seconds': time.monotonic() - before,
              'whole_child_process_cpu_seconds': after.ru_utime + after.ru_stime - usage_before.ru_utime - usage_before.ru_stime,
              'child_maximum_rss_bytes': after.ru_maxrss * 1024, 'posthoc': True,
              'new_codec_or_service_latency_measurements': 0})
    sys.exit(returncode)


if __name__ == '__main__':
    main()
