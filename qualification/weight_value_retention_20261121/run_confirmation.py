"""One fresh postselection public queue, evaluated only under the pinned own law."""
from pathlib import Path
from datetime import datetime
import argparse
import gc
import math
import os
import time
import traceback
import numpy as np
from scipy.stats import t
import own_context
import value_graph as graph_math
from data_contract import (FITS, FAMILIES, HEAD_IDS, canonical, pin, read, save,
                           save_arrays, verify)
from evaluation_io import run_phase
from input_contract import schedule_hash
from public_sampling import NAMESPACE, seed_for, public_world
from run_support import authenticate_protocol, bounded, resource_record, utc, verify_originals


def completed_main(main_path, protocol_sha256):
    result_pin = pin(Path(main_path) / 'RESULTS.json')
    result = read(result_pin['path'])
    process_pin = pin(Path(main_path).parent / 'PROCESS.json')
    process = read(process_pin['path'])
    if (process['schema'] != 'hepta-value-process-receipt-v1' or process['phase'] != 'main'
            or process['status'] != 'COMPLETED' or process['returncode'] != 0
            or process['wall_timeout'] or process['error'] is not None
            or not process['protocol_and_entry_unchanged'] or process['result_pin'] != result_pin
            or process['protocol_pin']['sha256'] != protocol_sha256
            or process['CPU_soft_seconds'] != 145 or process['CPU_hard_seconds'] != 150
            or not math.isfinite(process['child_CPU_seconds']) or not 0 <= process['child_CPU_seconds'] <= 150
            or process['wall_seconds'] != 240 or not math.isfinite(process['child_wall_seconds'])
            or not 0 <= process['child_wall_seconds'] <= 240
            or process['address_space_bytes'] != 536870912 or process['affinity'] != [7]
            or process['threads'] != 1
            or process['entry_pin'] != pin(Path(__file__).with_name('run_main.py'))
            or process['supervisor_pin'] != pin(Path(__file__).with_name('supervise.py'))):
        raise ValueError('successful complete MAIN process envelope is mandatory before entropy')
    if (result['status'] != 'COMPLETED' or result['protocol_sha256'] != protocol_sha256
            or not result['source_inputs_unchanged'] or set(result['fits']) != set(map(str, FITS))):
        raise ValueError('complete successful MAIN is mandatory before entropy')
    verify(result['candidate_selection_seal_pin'])
    verify(result['diagnostic_seal_pin'])
    seal = read(result['candidate_selection_seal_pin']['path'])
    diagnostics = read(result['diagnostic_seal_pin']['path'])
    if seal['protocol_sha256'] != protocol_sha256 or diagnostics['candidate_selection_seal_pin'] != result['candidate_selection_seal_pin']:
        raise ValueError('candidate/diagnostic seals differ')
    seal_time = datetime.fromisoformat(seal['created_utc'])
    diagnostic_time = datetime.fromisoformat(diagnostics['created_utc'])
    if diagnostic_time < seal_time:
        raise ValueError('diagnostic definitions preceded selection seal')
    if datetime.fromisoformat(result['completed_utc']) > datetime.fromisoformat(process['completed_utc']):
        raise ValueError('MAIN process receipt predates MAIN completion')
    for fit in FITS:
        row, sealed = result['fits'][str(fit)], seal['fits'][str(fit)]
        if set(row['candidate_slots']) != set(HEAD_IDS) or any(row[key] != sealed[key] for key in
                ('models', 'candidate_slots', 'family_choice', 'global_choice', 'graph_manifest_pin', 'hidden_pin')):
            raise ValueError('main candidate identities differ from prior seal')
        if row['diagnostic_models'] != diagnostics['fits'][str(fit)]['models']:
            raise ValueError('main diagnostics differ from prior seal')
        for entry in list(row['models'].values()) + list(row['diagnostic_models'].values()):
            verify(entry['model_pin'])
        for phase, expected in row['phase_records'].items():
            verify(expected)
            record = read(expected['path'])
            if record['phase'] != phase or record['protocol_sha256'] != protocol_sha256:
                raise ValueError('phase record role/source mismatch')
            verify(record['arrays_pin'])
            if phase == 'TRAIN_AUDIT' and datetime.fromisoformat(record['started_utc']) < diagnostic_time:
                raise ValueError('AUDIT began before complete selection/diagnostic seal')
            if datetime.fromisoformat(record['completed_utc']) > datetime.fromisoformat(result['completed_utc']):
                raise ValueError('MAIN result predates a required phase')
        if set(row['phase_records']) != {'GEN', 'SELECT', 'TRAIN_AUDIT'}:
            raise ValueError('MAIN lacks a required completed phase')
        if datetime.fromisoformat(read(row['SELECT_record_pin']['path'])['completed_utc']) > seal_time:
            raise ValueError('selection result completed after selection seal')
        verify(row['restore_pin'])
    return result, result_pin, seal, diagnostics


def confirmation_worlds(output, protocol, result, result_pin, ctx):
    # There is exactly one entropy acquisition. Any later collision is terminal.
    entropy = os.urandom(32)
    entropy_pin = save(output / 'CONF_ENTROPY.json', dict(
        schema='hepta-value-confirmation-entropy-v1', created_utc=utc(), entropy_hex=entropy.hex(),
        namespace=NAMESPACE, candidate_selection_seal_pin=result['candidate_selection_seal_pin'],
        main_results_pin=result_pin, main_process_pin=pin(Path(result_pin['path']).parent.parent / 'PROCESS.json'),
        protocol_sha256=protocol['_sha256'], external_custodian=False))
    known, collection = set(protocol['known_schedule_hashes']), {}
    used = set(known)
    for fit in FITS:
        collection[str(fit)] = {}
        for domain in ('iid', 'ood'):
            seed = seed_for(entropy, result['candidate_selection_seal_pin']['sha256'], fit, domain)
            rng = np.random.Generator(np.random.PCG64(seed))
            worlds, hashes = [], []
            for index in range(8):
                public = public_world(rng, protocol['public_domains'][domain],
                    protocol['public_domains']['prior_distances'], f'value_CONF_{domain}_{fit}_{index}')
                ctx.validate_public(public)
                key = schedule_hash(public, protocol['schedule_fields'])
                if key in used:
                    save(output / 'CONF_FAILED_COLLISION.json', dict(fit=fit, domain=domain, index=index,
                        schedule_sha256=key, public=public, prior_generated=collection, entropy_pin=entropy_pin,
                        generated_current_group=worlds, replacement_permitted=False))
                    raise ValueError('schedule collision; resampling forbidden')
                used.add(key)
                worlds.append(public)
                hashes.append(key)
            collection[str(fit)][domain] = dict(seed_decimal=str(seed), worlds=worlds, schedule_hashes=hashes)
    worlds_seal = dict(schema='hepta-value-confirmation-worlds-v1', created_utc=utc(),
        entropy_pin=entropy_pin, candidate_selection_seal_pin=result['candidate_selection_seal_pin'],
        protocol_sha256=protocol['_sha256'], known_hash_count=len(known), world_count=len(used) - len(known), fits=collection)
    return collection, entropy_pin, save(output / 'CONF_WORLDS_FROZEN.json', worlds_seal)


def arm_models(row):
    models = {'KEEP': dict(row['models']['KEEP'], selected_candidate_id='KEEP')}
    aliases = {'KEEP': 'KEEP'}
    for family in FAMILIES:
        chosen = row['family_choice'][family]
        name = family + '_SELECTED'
        models[name] = dict(row['models'][chosen], selected_candidate_id=chosen)
        aliases.setdefault(chosen, name)
    for name in ('G_WITH_ORIGINAL_B', 'G_WITH_ORIGINAL_Q'):
        models[name] = dict(row['diagnostic_models'][name], selected_candidate_id=name)
    return models, aliases[row['global_choice']]


def primary_contrasts(fits):
    critical = float(t.ppf(1 - 0.05 / (2 * 4), 4))
    reports = []
    for domain in ('iid', 'ood'):
        for reference in ('KEEP', 'T_SELECTED'):
            differences = [fits[str(fit)][domain]['summary']['G_SELECTED']['utility'] -
                           fits[str(fit)][domain]['summary'][reference]['utility'] for fit in FITS]
            mean = float(np.mean(differences))
            sd = float(np.std(differences, ddof=1))
            se = sd / np.sqrt(5)
            reports.append(dict(candidate='G_SELECTED', reference=reference, domain=domain,
                fits=list(FITS), differences=differences, n_fits=5, mean=mean, sample_SD=sd, SE=float(se),
                minimum=min(differences), maximum=max(differences), df=4, family_comparisons=4,
                critical=critical, familywise95_interval=[mean - critical * se, mean + critical * se],
                assumption='Conditional five-fit paired-t approximation; states/worlds are not independent replicate fits'))
    return reports


def main(args):
    wall_start, created_utc = time.perf_counter(), utc()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    save(output / 'STARTED.json', dict(created_utc=created_utc, phase='CONFIRMATION', protocol_pin=pin(args.protocol)))
    try:
        protocol, protocol_sha = authenticate_protocol(args.protocol)
        budget = bounded(protocol, 'confirmation')
        protocol['_sha256'] = protocol_sha
        verify_originals(protocol)
        result, result_pin, seal, diagnostics = completed_main(args.main, protocol_sha)
        ctx = own_context.load(protocol['semantic_sources'])
        collection, entropy_pin, worlds_pin = confirmation_worlds(output, protocol, result, result_pin, ctx)
        fits = {}
        for fit in FITS:
            row = result['fits'][str(fit)]
            base = read(row['models']['KEEP']['model_pin']['path'])
            model = ctx.NumpyPolicy(base)
            models, global_alias = arm_models(row)
            fits[str(fit)] = {}
            for domain in ('iid', 'ood'):
                items = []
                for index, public in enumerate(collection[str(fit)][domain]['worlds']):
                    budget()
                    graph = graph_math.build(ctx, public, base, 4096, budget)
                    graph_pin = save(output / 'graphs' / f'fit_{fit}_{domain}_{index:03d}.json.gz', graph)
                    X, feature_counts = graph_math.semantic_inputs(ctx, public, model, graph['states'], budget)
                    H = graph_math.strict_hidden(base, X)
                    feature_pin = save_arrays(output / 'features' / f'fit_{fit}_{domain}_{index:03d}.npz', X=X, H=H)
                    items.append(dict(world_index=index, graph=graph, graph_pin=graph_pin, H=H,
                                      features_pin=feature_pin, feature_counts=feature_counts))
                record, record_pin = run_phase(output / 'records' / f'fit_{fit}_{domain}.json',
                    'SEALED_OWN_LAW_CONFIRMATION', fit, models, items, protocol_sha, budget, domain=domain)
                fits[str(fit)][domain] = dict(phase_record_pin=record_pin, global_alias=global_alias, summary=record['means'])
                del items, X, H, graph, record
                gc.collect()
        verify_originals(protocol)
        completed_main(args.main, protocol_sha)
        verify(result_pin)
        report = dict(schema='hepta-value-confirmation-results-v1', status='COMPLETED',
            created_utc=created_utc, completed_utc=utc(), protocol_sha256=protocol_sha,
            main_results_pin=result_pin, candidate_selection_seal_pin=result['candidate_selection_seal_pin'],
            diagnostic_seal_pin=result['diagnostic_seal_pin'], entropy_pin=entropy_pin, worlds_seal_pin=worlds_pin,
            fits=fits, primary=primary_contrasts(fits), work=dict(graph_math.WORK), resources=resource_record(wall_start),
            source_inputs_and_selected_models_unchanged=True,
            scope='Fresh postselection public schedules under the same supplied checkpoint law; no truth or financial-label efficacy')
        save(output / 'RESULTS.json', report)
        print(canonical(dict(status='COMPLETED', results_pin=pin(output / 'RESULTS.json'))), flush=True)
    except BaseException as error:
        save(output / 'FAILED.json', dict(status='FAILED', created_utc=utc(), error_type=type(error).__name__,
            error=str(error), traceback=traceback.format_exc(), resources=resource_record(wall_start),
            work=dict(graph_math.WORK), retry_permitted=False))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--main', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args())
