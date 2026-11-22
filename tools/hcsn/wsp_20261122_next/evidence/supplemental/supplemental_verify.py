"""Read-only closure of retained value-study seals, schedules and contrasts.

No model forward, graph construction, policy DP, optimizer, entropy draw or
source experiment import is permitted by this supplemental verifier.
"""
from pathlib import Path
from decimal import Decimal, localcontext
import argparse
import gzip
import hashlib
import json
import math
import os
import sys
import time


START_CPU = time.process_time()
START_WALL = time.monotonic()
READ_PINS = {}


def check(condition, message):
    if not condition:
        raise ValueError(message)


def budget():
    check(time.process_time() - START_CPU < 9.0, 'supplemental CPU soft cap')
    check(time.monotonic() - START_WALL < 28.0, 'supplemental wall soft cap')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def pin(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    result = dict(path=str(path), bytes=len(raw), sha256=digest(raw))
    READ_PINS[str(path)] = result
    budget()
    return result


def verify(path, expected):
    observed = pin(path)
    check(all(observed[key] == expected[key] for key in ('bytes', 'sha256')),
          'identity mismatch: ' + str(path))
    return observed


def pairs(rows):
    result = {}
    for key, value in rows:
        check(key not in result, 'duplicate JSON key: ' + key)
        result[key] = value
    return result


def read(path, expected=None):
    path = Path(path).resolve()
    raw = path.read_bytes()
    observed = dict(path=str(path), bytes=len(raw), sha256=digest(raw))
    if expected is not None:
        check(all(observed[k] == expected[k] for k in ('bytes', 'sha256')),
              'JSON identity mismatch: ' + str(path))
    READ_PINS[str(path)] = observed
    if path.suffix == '.gz':
        raw = gzip.decompress(raw)
    def invalid(value):
        raise ValueError('nonfinite JSON token: ' + value)
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    budget()
    return value


def close(actual, expected, label, tolerance=2e-12):
    check(math.isfinite(actual) and math.isfinite(expected), 'nonfinite ' + label)
    check(abs(actual - expected) <= tolerance, 'numeric mismatch: ' + label)


def replay_public(generator, domain, distances, identifier):
    # Independently transcribed draw order from authenticated public_sampling.py.
    # This regenerates existing recorded public schedules only; no entropy call.
    return dict(schema='joint-current-at-due-fixed-deadline-v1', id=identifier,
                deadline=6, initial_budget=3, target_tick=6,
                duration=generator.choice(domain['durations'], 6).tolist(),
                drive=generator.choice(domain['drives'], 6).tolist(),
                reliability=generator.choice(domain['reliabilities'], 6).tolist(),
                read_price=generator.choice(domain['prices'], 6).tolist(),
                read_delay=generator.choice(domain['delays'], 6).tolist(),
                prior_distance=float(generator.choice(distances)),
                latency_price=domain['latency_price'], repair_price=domain['repair_price'],
                failure_probability=domain['failure_probability'],
                packets=[f'not_opened_{i}.json' for i in range(6)],
                packet_sha256=['0' * 64] * 6)


def independent_t4_critical():
    # For t>=0, u=t/sqrt(t^2+4), CDF(t)=1/2+3u/4-u^3/4.
    # Invert that cubic at the six-comparison two-sided Bonferroni probability.
    with localcontext() as context:
        context.prec = 70
        target = Decimal(1) - Decimal('0.05') / Decimal(12)
        lo, hi = Decimal(0), Decimal(1)
        for _ in range(240):
            u = (lo + hi) / 2
            cdf = Decimal('0.5') + 3 * u / 4 - u ** 3 / 4
            if cdf < target:
                lo = u
            else:
                hi = u
        u = (lo + hi) / 2
        return float(2 * u / (1 - u * u).sqrt())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    spec = read(args.spec)
    check(spec['schema'] == 'hepta-value-supplemental-readonly-v1', 'supplemental spec schema')
    verify(__file__, spec['verifier_pin'])
    source = Path(spec['source_root']).resolve()
    run = Path(spec['run_root']).resolve()
    inputs = Path(spec['input_root']).resolve()
    protocol = read(source / 'PROTOCOL_FROZEN.json', spec['protocol_pin'])
    protocol_sha = spec['protocol_pin']['sha256']
    check(protocol['fit_ids'] == [11, 23, 37, 53, 71], 'five frozen checkpoint identities')
    check(protocol['confirmation_inference'] ==
          '6 Bonferroni-adjusted paired-t contrasts, checkpoint n=5; new confirmation cannot trigger retry',
          'frozen inference specification')
    check(sorted(os.sched_getaffinity(0)) == [7] and sys.dont_write_bytecode,
          'supplemental admitted process environment')
    verify(sys.executable, protocol['numeric']['python_executable'])
    for entry in protocol['source_pins']:
        path = (source / entry['path']).resolve()
        check(path.is_relative_to(source), 'source path confinement')
        verify(path, entry)
    by_hash = {}
    for entry in protocol['input_pins']:
        path = (inputs / entry['path']).resolve()
        check(path.is_relative_to(inputs), 'input path confinement')
        actual = verify(path, entry)
        by_hash[actual['sha256']] = actual
    import numpy as np
    verify(np._core._multiarray_umath.__file__,
           dict(bytes=Path(np._core._multiarray_umath.__file__).stat().st_size,
                sha256=protocol['numeric']['numpy_sha256']))
    check(np.__version__ == protocol['numeric']['numpy_version'], 'NumPy version')

    phases = ('generation', 'selection', 'confirmation', 'verification')
    results, processes, directories = {}, {}, {}
    for phase in phases:
        attempts = sorted(p.name for p in run.glob(phase + '_attempt*') if p.is_dir())
        check(attempts == [phase + '_attempt001'], 'exactly one retained ' + phase + ' attempt')
        directory = run / attempts[0] / 'output'
        directories[phase] = directory
        process = read(directory.parent / 'PROCESS.json')
        check(process['phase'] == phase and process['status'] == 'COMPLETED' and
              process['returncode'] == 0 and not process['wall_timeout'] and process['protocol_unchanged'],
              'successful phase supervisor: ' + phase)
        verify(source / 'PROTOCOL_FROZEN.json', process['protocol_pin'])
        expected_entry = source / ('verify_run.py' if phase == 'verification' else 'run_value_study.py')
        verify(expected_entry, process['entry_pin'])
        result = read(directory / 'RESULTS.json', process['result_pin'])
        check(result['protocol_sha256'] == protocol_sha, 'phase protocol binding')
        check(result['status'] == ('PASS' if phase == 'verification' else 'COMPLETED'),
              'phase result status')
        if phase != 'verification':
            check(result['phase'] == phase, 'phase result identity')
            check(Path(result['original_run_root']).resolve() == run, 'current run root identity')
        processes[phase], results[phase] = process, result

    def resolve(entry):
        old = Path(entry['path']).resolve()
        if old.is_relative_to(run):
            verify(old, entry)
            return old
        check(entry['sha256'] in by_hash, 'unrecognized external artifact')
        actual = by_hash[entry['sha256']]
        check(actual['bytes'] == entry['bytes'], 'external artifact byte count')
        return Path(actual['path'])

    generation, selection, confirmation = (results[x] for x in phases[:3])
    candidate_path = directories['generation'] / 'CANDIDATES_FROZEN.json'
    selected_path = directories['selection'] / 'SELECTION_FROZEN.json'
    candidate = read(candidate_path, generation['candidate_seal_pin'])
    selected = read(selected_path, selection['selection_seal_pin'])
    verify(candidate_path, selected['candidate_seal_pin'])
    for seal in (candidate, selected):
        check(seal['protocol_sha256'] == protocol_sha and
              Path(seal['original_run_root']).resolve() == run, 'seal identity')
    check(candidate['primary_candidates'] == ['KEEP', 'DIRECT', 'BP'], 'primary candidate names')
    fit_keys = [str(f) for f in protocol['fit_ids']]
    for row in (candidate, selected, generation, selection, confirmation):
        check(set(row['fits']) == set(fit_keys), 'exact sealed fit set')
    for fit in fit_keys:
        original_models = candidate['fits'][fit]['models']
        for row in (generation, selection, selected, confirmation):
            check(row['fits'][fit]['models'] == original_models, 'cross-phase sealed models: ' + fit)
        check(selected['fits'][fit] == selection['fits'][fit], 'selection full-row seal: ' + fit)
        check(confirmation['fits'][fit]['choices'] == selected['fits'][fit]['choices'],
              'confirmation choices bind selection seal: ' + fit)
        for entry in original_models.values():
            resolve(entry['model_pin'])

    known = protocol['known_schedule_hashes']
    check(len(known) == len(set(known)) == 3796, '3796 unique historical schedules')
    check(protocol['historical_schedule_count'] + protocol['prior_confirmation_schedule_count'] == 3796,
          'historical schedule count decomposition')
    used = set(known)
    schedules = {}
    for phase, prior_seal in (('selection', candidate_path), ('confirmation', selected_path)):
        directory = directories[phase]
        worlds = read(directory / 'WORLDS_FROZEN.json', results[phase]['worlds_pin'])
        entropy = read(directory / 'ENTROPY.json', worlds['entropy_pin'])
        verify(prior_seal, entropy['previous_seal_pin'])
        check(entropy['source'] ==
              'single os.urandom(32) after authenticated seal; no external custodian',
              'entropy provenance declaration')
        raw_entropy = bytes.fromhex(entropy['entropy_hex'])
        check(len(raw_entropy) == 32 and len(entropy['entropy_hex']) == 64, '32-byte retained entropy')
        check(worlds['stage'] == phase and set(worlds['groups']) == set(fit_keys), 'world stage/fit set')
        domains = ('iid',) if phase == 'selection' else ('iid', 'ood')
        count = protocol['selection_worlds_per_fit'] if phase == 'selection' else protocol['confirmation_worlds_per_domain']
        stage_count = 0
        for fit in protocol['fit_ids']:
            check(set(worlds['groups'][str(fit)]) == set(domains), 'world domain set')
            for domain in domains:
                group = worlds['groups'][str(fit)][domain]
                seed = int.from_bytes(hashlib.sha256(raw_entropy + canonical(
                    [protocol['namespace'], phase, pin(prior_seal)['sha256'], fit, domain]).encode()).digest(), 'big')
                check(group['seed'] == str(seed), 'retained entropy-derived seed')
                generator = np.random.Generator(np.random.PCG64(seed))
                check(len(group['worlds']) == count, 'frozen world count')
                for index, world in enumerate(group['worlds']):
                    public = replay_public(generator, protocol['public_domains'][domain],
                        protocol['public_domains']['prior_distances'],
                        f'value_next_{phase}_{fit}_{domain}_{index}')
                    check(canonical(world['public']) == canonical(public), 'retained entropy schedule replay')
                    fingerprint = digest(canonical({key: public[key] for key in protocol['schedule_fields']}).encode())
                    check(world['schedule_sha256'] == fingerprint, 'schedule fingerprint')
                    check(fingerprint not in used, 'historical/interstage/intrastage schedule collision')
                    used.add(fingerprint)
                    schedules[(phase, str(fit), domain, index)] = world
                    stage_count += 1
        check(worlds['schedule_count'] == stage_count == 80, 'eighty stage schedules')

    aggregates = {}
    counts = dict(raw_policy_records=0, bound_phase_records=0, bound_new_graphs=0,
                  historical_schedules=len(known), replayed_existing_schedules=len(schedules),
                  bound_confirmation_choices=0, recomputed_contrasts=0)
    for phase in phases[:3]:
        aggregates[phase] = {}
        for fit in fit_keys:
            row = results[phase]['fits'][fit]
            aggregates[phase][fit] = {}
            records = {'gen': row['GEN_record_pin']} if phase == 'generation' else row['records']
            expected_domains = {'gen'} if phase == 'generation' else ({'iid'} if phase == 'selection' else {'iid', 'ood'})
            check(set(records) == expected_domains, 'exact phase domains')
            for domain, record_pin in records.items():
                record = read(resolve(record_pin), record_pin)
                check(record['phase'] == ('GEN' if phase == 'generation' else phase.upper()) and
                      record['fit'] == int(fit) and record['domain'] == (None if phase == 'generation' else domain) and
                      record['protocol_sha256'] == protocol_sha, 'raw record task identity')
                check(record['models'] == candidate['fits'][fit]['models'], 'raw record sealed candidate identities')
                arms = record['arm_order']
                check(len(arms) == len(set(arms)) and set(arms) == set(record['models']) and arms[0] == 'KEEP',
                      'exact arm identity/order set')
                resolve(record['arrays_pin'])
                if phase == 'generation':
                    graph_specs = protocol['fits'][fit]['graphs']
                    expected_indices = [entry['world_index'] for entry in graph_specs]
                    graph_by_index = {entry['world_index']: entry for entry in graph_specs}
                else:
                    count = protocol['selection_worlds_per_fit'] if phase == 'selection' else protocol['confirmation_worlds_per_domain']
                    expected_indices = list(range(count))
                check(record['world_indices'] == expected_indices, 'raw record complete world index list')
                check([world['world_index'] for world in record['worlds']] == expected_indices,
                      'one-to-one raw record world coverage')
                utilities = {arm: [] for arm in arms}
                for world in record['worlds']:
                    check(set(world['arms']) == set(arms), 'raw record complete arm set')
                    index = world['world_index']
                    if phase == 'generation':
                        expected = graph_by_index[index]
                        actual = READ_PINS[str(resolve(world['graph_pin']))]
                        check(actual['sha256'] == expected['graph']['sha256'] and
                              actual['bytes'] == expected['graph']['bytes'] and
                              world['state_order_sha256'] == expected['state_order_sha256'], 'GEN graph alignment')
                    else:
                        graph = read(resolve(world['graph_pin']), world['graph_pin'])
                        schedule = schedules[(phase, fit, domain, index)]
                        check(canonical(graph['public']) == canonical(schedule['public']), 'graph to frozen public schedule')
                        check(world['world_id'] == graph['public']['id'] and
                              world['state_order_sha256'] == graph['state_order_sha256'] and
                              world['rows'] == len(graph['states']), 'raw world id/state binding')
                        fingerprint = digest(canonical({key: graph['public'][key] for key in protocol['schedule_fields']}).encode())
                        check(fingerprint == schedule['schedule_sha256'], 'graph schedule fingerprint')
                        resolve(world['features_pin'])
                        counts['bound_new_graphs'] += 1
                    for arm in arms:
                        utility = world['arms'][arm]['metrics']['utility']
                        check(math.isfinite(utility), 'finite raw policy utility')
                        utilities[arm].append(utility)
                        counts['raw_policy_records'] += 1
                summary = {}
                for arm in arms:
                    mean = math.fsum(utilities[arm]) / len(utilities[arm])
                    delta = [a - b for a, b in zip(utilities[arm], utilities['KEEP'])]
                    summary[arm] = dict(utility=mean, delta_original=math.fsum(delta) / len(delta),
                                        delta_original_min=min(delta), per_world_utilities=utilities[arm])
                    check(record['means'][arm]['worlds'] == len(utilities[arm]), 'aggregate world count')
                    check(record['means'][arm]['per_world_utilities'] == utilities[arm], 'aggregate raw utility vector')
                    saved = row['GEN_means'][arm] if phase == 'generation' else row['means'][domain][arm]
                    for key in ('utility', 'delta_original', 'delta_original_min'):
                        close(summary[arm][key], record['means'][arm][key], 'record ' + key)
                        close(summary[arm][key], saved[key], 'phase ' + key)
                    close(mean, results['verification']['values'][phase][fit][domain][arm],
                          'existing independent hard reader mean')
                aggregates[phase][fit][domain] = summary
                counts['bound_phase_records'] += 1
            if phase in ('selection', 'confirmation'):
                for family in ('DIRECT', 'BP'):
                    selected_metrics = aggregates['selection'][fit]['iid'][family]
                    passed = (selected_metrics['delta_original'] > protocol['mean_improvement_threshold'] and
                              selected_metrics['delta_original_min'] >= -protocol['maximum_selection_world_loss'])
                    choice = family if passed else 'KEEP'
                    check(row['choices'][family] == choice, 'raw selection-derived choice')
                    if phase == 'confirmation':
                        counts['bound_confirmation_choices'] += 1

    critical = independent_t4_critical()
    contrasts, improvements = {}, {}
    for domain in ('iid', 'ood'):
        values = {'KEEP': [], 'DIRECT': [], 'BP': []}
        for fit in fit_keys:
            by_arm = aggregates['confirmation'][fit][domain]
            values['KEEP'].append(by_arm['KEEP']['utility'])
            for family in ('DIRECT', 'BP'):
                values[family].append(by_arm[selected['fits'][fit]['choices'][family]]['utility'])
        contrasts[domain] = {}
        for a, b in (('DIRECT', 'KEEP'), ('BP', 'KEEP'), ('DIRECT', 'BP')):
            deltas = [x - y for x, y in zip(values[a], values[b])]
            mean = math.fsum(deltas) / 5
            variance = math.fsum((x - mean) ** 2 for x in deltas) / 4
            half = critical * math.sqrt(variance / 5)
            contrast = dict(mean=mean, lower=mean - half, upper=mean + half,
                            checkpoint_deltas=deltas, n=5, familywise_target=.95, comparisons=6)
            name = a + '_MINUS_' + b
            observed = confirmation['contrasts'][domain][name]
            for key in ('mean', 'lower', 'upper'):
                close(contrast[key], observed[key], 'independent paired contrast ' + key)
            check(observed['n'] == 5 and observed['familywise_target'] == .95 and observed['comparisons'] == 6,
                  'contrast inferential metadata')
            check(len(observed['checkpoint_deltas']) == 5, 'contrast checkpoint count')
            for actual, expected in zip(deltas, observed['checkpoint_deltas']):
                close(actual, expected, 'contrast checkpoint delta')
            contrasts[domain][name] = contrast
            counts['recomputed_contrasts'] += 1
    for family in ('DIRECT', 'BP'):
        improvements[family] = all(
            contrasts[domain][family + '_MINUS_KEEP']['lower'] > 0 and
            min(aggregates['confirmation'][fit][domain][selected['fits'][fit]['choices'][family]]['delta_original_min']
                for fit in fit_keys) >= -protocol['maximum_selection_world_loss']
            for domain in ('iid', 'ood'))
    check(improvements == confirmation['improvement_claim'], 'independent improvement claim')
    check(counts['bound_new_graphs'] == len(schedules) == 160, 'complete new schedule graph binding')
    # All authenticated bytes must remain unchanged throughout this read-only audit.
    before = list(READ_PINS.values())
    for entry in before:
        verify(entry['path'], entry)
    output = dict(schema='hepta-value-supplemental-readonly-receipt-v1', status='PASS',
        spec_pin=pin(args.spec), protocol_sha256=protocol_sha, counts=counts,
        source_scope=spec['source_scope'], independent_t4_critical=critical,
        contrasts=contrasts, improvement_claim=improvements,
        choices={fit: confirmation['fits'][fit]['choices'] for fit in fit_keys},
        retained_phase_costs={phase: {key: processes[phase][key] for key in
            ('child_CPU_seconds', 'supervisor_CPU_seconds', 'wall_seconds')} for phase in phases},
        input_pins=sorted(READ_PINS.values(), key=lambda row: row['path']),
        quality_work=dict(new_candidates=0, new_worlds=0, new_entropy_draws=0,
                          model_forwards=0, policy_DPs=0, optimizer_steps=0),
        limits=spec['limits'], CPU_seconds_from_entry=time.process_time()-START_CPU,
        wall_seconds=time.monotonic()-START_WALL,
        scope='Supplemental verification of retained bytes, schedules, selections and arithmetic. '
              'No new confirmation or model-quality evidence; existing frozen hard reader supplies policy-DP verification.',
        entropy_limit='One retained entropy record per frozen phase is source-bound and deterministically replayed. '
                      'There is no independent external entropy custodian or proof about unrecorded entropy draws.',
        inference_limit='Prespecified paired-t intervals use five checkpoint clusters and their parametric assumptions; '
                        'arithmetic verification does not establish those assumptions or market transfer.')
    with (args.output / 'RESULTS.json').open('x') as handle:
        json.dump(output, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')
    print(json.dumps({key: output[key] for key in ('status', 'counts', 'quality_work', 'CPU_seconds_from_entry')}))


if __name__ == '__main__':
    main()
