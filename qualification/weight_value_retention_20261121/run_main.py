"""One bounded, sealed, own-law TRAIN study; no truth or confirmation input."""
from pathlib import Path
import argparse
import gc
import time
import traceback
import numpy as np
import head_candidates as candidates
import own_context
import value_graph as graph_math
from data_contract import (FITS, FAMILIES, HEAD_IDS, canonical, digest, exact_radius,
                           head, model_with_head, pin, read, save, save_arrays,
                           verify, choose)
from evaluation_io import aggregate, model_entry, run_phase
from input_contract import load_fit, authenticate_graph
from run_support import (authenticate_protocol, bounded, resource_record,
                         semantic_manifest_sha, utc, verify_originals)


def copy_original(source, destination):
    verify(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as stream:
        stream.write(Path(source['path']).read_bytes())
    observed = pin(destination)
    if any(observed[k] != source[k] for k in ('bytes', 'sha256')):
        raise ArithmeticError('original-byte copy changed')
    return observed


def prepare_fit(output, fit, protocol, ctx, budget):
    started = time.process_time()
    spec = protocol['input_specs'][str(fit)]
    data = load_fit(spec)
    base = data['base']
    H = graph_math.strict_hidden(base, data['X'])
    scores, _, _ = graph_math.strict_scores(head(base), H)
    if scores.tobytes() != data['original_scores'].tobytes():
        raise ArithmeticError('original H49 arithmetic differs from saved C scores')
    hidden_pin = save_arrays(output / 'features' / f'fit_{fit}.npz', H=H)
    items, manifest = {}, []
    for index, public in enumerate(data['publics']):
        budget()
        graph = graph_math.build(ctx, public, base, 4096, budget)
        authentication = authenticate_graph(graph, data, index)
        graph_pin = save(output / 'graphs' / f'fit_{fit}' / f'world_{index:03d}.json.gz', graph)
        bounds = data['offsets'][index]
        item = dict(world_index=index, graph=graph, graph_pin=graph_pin,
                    H=H[bounds['start']:bounds['end']])
        items[index] = item
        manifest.append(dict(world_index=index, graph_pin=graph_pin,
                             row_start=bounds['start'], row_end=bounds['end'],
                             state_order_sha256=graph['state_order_sha256'],
                             source_teacher_authentication=authentication))
    manifest_pin = save(output / 'graphs' / f'fit_{fit}' / 'MANIFEST.json', dict(
        schema='hepta-own-law-graph-manifest-v1', fit=fit, graphs=manifest,
        model_anchor_pin=spec['model'], semantic_source_manifest_sha256=semantic_manifest_sha(protocol)))
    return data, H, items, hidden_pin, manifest_pin, time.process_time() - started


def screen_gen(output, fit, protocol, data, H, items, incumbent, incumbent_pin):
    indices = protocol['splits'][str(fit)]['GEN']
    arrays = np.load(incumbent['arrays_pin']['path'], allow_pickle=False)
    rows_by_world = {r['world_index']: r for r in incumbent['worlds']}
    hidden, masks, qstar, scores, occupancy, row_ids, initials = [], [], [], [], [], [], []
    offset = 0
    for index in indices:
        graph = items[index]['graph']
        section = data['offsets'][index]
        prefix = rows_by_world[index]['arms']['KEEP']['array_prefix']
        hidden.append(items[index]['H'])
        masks.append(graph['masks'])
        qstar.append(graph['qstar'])
        scores.append(arrays[prefix + '__scores'])
        occupancy.append(arrays[prefix + '__occupancy'])
        row_ids.append(np.arange(section['start'], section['end'], dtype=np.int64))
        initials.append(offset + graph['initial'])
        offset += len(graph['states'])
    arrays.close()
    problem, report = candidates.screen(*(np.concatenate(x) for x in
        (hidden, masks, qstar, scores, occupancy)), initials, np.concatenate(row_ids))
    problem_pin = save_arrays(output / 'screening' / f'fit_{fit}.npz', **problem)
    report.update(schema='hepta-value-gen-screening-v1', fit=fit, GEN_world_indices=indices,
                  protocol_sha256=protocol['_sha256'], problem_pin=problem_pin,
                  incumbent_record_pin=incumbent_pin, source_input_pins=protocol['input_specs'][str(fit)],
                  exact_radius=exact_radius(head(data['base'])))
    screening_pin = save(output / 'screening' / f'fit_{fit}.json', report)
    return problem, screening_pin, problem_pin


def generate(output, fit, base, problem, screening_pin, problem_pin, protocol, budget):
    models, slots, generation = {}, {}, {}
    anchor = head(base)
    for family in FAMILIES:
        budget()
        started_utc, family_start, family_wall = utc(), time.process_time(), time.perf_counter()
        before = dict(graph_math.WORK)
        numerical_start = time.process_time()
        if family == 'T':
            proposed, report = candidates.gradient_reference(anchor, problem, budget)
            payloads = {}
        else:
            proposed, report, payloads = candidates.structured_family(anchor, problem, family, budget)
        numerical_call_CPU = time.process_time() - numerical_start
        artifact_start = time.process_time()
        saved, raw = {}, {}
        for name, rows in proposed.items():
            target = output / 'models' / f'fit_{fit}_{name}.json.gz'
            save(target, model_with_head(base, rows, family)[0])
            saved[name] = model_entry(target, base, family, name)
        for name, payload in payloads.items():
            if payload:
                raw.update({name + '__' + key: value for key, value in payload.items()})
        payload_pin = save_arrays(output / 'generation' / f'fit_{fit}_{family}_raw.npz', **raw) if raw else None
        artifact_CPU = time.process_time() - artifact_start
        lifecycle_CPU = time.process_time() - family_start
        record = dict(schema='hepta-value-family-generation-v1', fit=fit, family=family,
                      started_utc=started_utc, completed_utc=utc(),
                      protocol_sha256=protocol['_sha256'], source_model_pin=protocol['input_specs'][str(fit)]['model'],
                      problem_pin=problem_pin, screening_pin=screening_pin, raw_payloads_pin=payload_pin,
                      emitted_model_pins={name: entry['model_pin'] for name, entry in saved.items()},
                      readout_work_delta={key: graph_math.WORK[key] - before[key] for key in before},
                      lifecycle_CPU_through_record=lifecycle_CPU,
                      lifecycle_wall_through_record=time.perf_counter() - family_wall,
                      numerical_call_CPU_seconds=numerical_call_CPU,
                      artifact_and_revalidation_CPU_seconds=artifact_CPU,
                      other_family_bookkeeping_CPU_seconds=lifecycle_CPU - numerical_call_CPU - artifact_CPU,
                      lifecycle_scope='numerical family plus saved-model protection/radius checks and payload serialization; final JSON tail in main process total',
                      **report)
        record_pin = save(output / 'generation' / f'fit_{fit}_{family}.json', record)
        generation[family] = record_pin
        for name in HEAD_IDS:
            if name.split('_')[0] != family:
                continue
            checkpoint = report['checkpoints'][name]
            slots[name] = dict(family=family, status='VALID' if name in saved else 'UNKNOWN',
                               checkpoint_report=checkpoint, generation_record_pin=record_pin,
                               model_pin=saved[name]['model_pin'] if name in saved else None)
            if name in saved:
                saved[name]['generation_record_pin'] = record_pin
                models[name] = saved[name]
    return {name: models[name] for name in HEAD_IDS if name in models}, slots, generation


def reload_items(manifest_pin, hidden_pin, indices):
    verify(manifest_pin)
    verify(hidden_pin)
    manifest = read(manifest_pin['path'])
    with np.load(hidden_pin['path'], allow_pickle=False) as archive:
        H = archive['H']
    mapping = {row['world_index']: row for row in manifest['graphs']}
    for index in indices:
        row = mapping[index]
        verify(row['graph_pin'])
        yield dict(world_index=index, graph=read(row['graph_pin']['path']), graph_pin=row['graph_pin'],
                   H=H[row['row_start']:row['row_end']])


def main(args):
    wall_start, created_utc = time.perf_counter(), utc()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    save(output / 'STARTED.json', dict(created_utc=created_utc, phase='MAIN', protocol_pin=pin(args.protocol)))
    try:
        protocol, protocol_sha = authenticate_protocol(args.protocol)
        budget = bounded(protocol, 'main')
        protocol['_sha256'] = protocol_sha
        ctx = own_context.load(protocol['semantic_sources'])
        fits = {}
        for fit in FITS:
            budget()
            data, H, items, hidden_pin, manifest_pin, preparation_CPU = prepare_fit(output, fit, protocol, ctx, budget)
            base = data['base']
            original_pin = copy_original(protocol['input_specs'][str(fit)]['model'],
                                         output / 'models' / f'fit_{fit}_KEEP.json.gz')
            keep = model_entry(original_pin['path'], base, 'KEEP', 'KEEP')
            split = protocol['splits'][str(fit)]
            incumbent, incumbent_pin = run_phase(output / 'preparation' / f'fit_{fit}_GEN_KEEP.json',
                'GEN_INCUMBENT_ONLY', fit, {'KEEP': keep}, [items[i] for i in split['GEN']], protocol_sha, budget)
            screen_start = time.process_time()
            problem, screening_pin, problem_pin = screen_gen(output, fit, protocol, data, H, items, incumbent, incumbent_pin)
            screening_CPU = time.process_time() - screen_start
            generated, slots, generation = generate(output, fit, base, problem, screening_pin, problem_pin, protocol, budget)
            models = dict(KEEP=keep, **generated)
            gen, gen_pin = run_phase(output / 'records' / f'fit_{fit}_GEN.json', 'GEN', fit, models,
                [items[i] for i in split['GEN']], protocol_sha, budget, precomputed_keep=incumbent_pin)
            selection, selection_pin = run_phase(output / 'records' / f'fit_{fit}_SELECT.json', 'SELECT', fit,
                models, [items[i] for i in split['SELECT']], protocol_sha, budget)
            means = {name: entry['utility'] for name, entry in selection['means'].items()}
            family_choice = {family: choose(means, [name for name in HEAD_IDS
                if name.startswith(family + '_') and name in models]) for family in FAMILIES}
            finalists = set(family_choice.values())
            global_choice = choose(means, [name for name in HEAD_IDS if name in finalists])
            fits[str(fit)] = dict(models=models, candidate_slots=slots, generation=generation,
                family_choice=family_choice, global_choice=global_choice,
                GEN_record_pin=gen_pin, SELECT_record_pin=selection_pin, SELECT_means=means,
                graph_manifest_pin=manifest_pin, hidden_pin=hidden_pin, screening_pin=screening_pin,
                incumbent_GEN_record_pin=incumbent_pin,
                shared_preparation_CPU_seconds=preparation_CPU + screening_CPU + incumbent['CPU_seconds'],
                attributed_common_CPU_per_family=(preparation_CPU + screening_CPU + incumbent['CPU_seconds']) / 4,
                cost_allocation_scope='equal allocation of measured input/DAG/hidden/GEN-incumbent/screening preparation; other common I/O and seal tails remain in whole-process resource total, not zero')
            save(output / 'preselection' / f'fit_{fit}.json', fits[str(fit)])
            del data, H, items, problem, incumbent, gen, selection
            gc.collect()
        verify_originals(protocol)
        seal_pin = save(output / 'CANDIDATES_AND_SELECT_FROZEN.json', dict(
            schema='hepta-value-candidate-selection-seal-v1', created_utc=utc(), protocol_sha256=protocol_sha,
            fits=fits, source_pins_sha256=digest(canonical(protocol['source_pins']).encode())))
        diagnostics = {}
        for fit in FITS:
            row = fits[str(fit)]
            base = read(row['models']['KEEP']['model_pin']['path'])
            chosen = row['family_choice']['G']
            selected = head(read(row['models'][chosen]['model_pin']['path']))
            definitions = [('G_WITH_ORIGINAL_B', 'Q', (0, 1, 2)), ('G_WITH_ORIGINAL_Q', 'B', (3,))]
            diagnostic_models = {}
            for name, family, rows_to_copy in definitions:
                rows = head(base)
                for coordinate in rows_to_copy:
                    rows[coordinate] = selected[coordinate]
                target = output / 'models' / f'fit_{fit}_{name}.json.gz'
                save(target, model_with_head(base, rows, family)[0])
                diagnostic_models[name] = model_entry(target, base, family, name, diagnostic=True)
            diagnostics[str(fit)] = dict(G_SELECTED=chosen, models=diagnostic_models)
        diagnostic_pin = save(output / 'DIAGNOSTICS_FROZEN.json', dict(
            schema='hepta-value-component-restoration-seal-v1', candidate_selection_seal_pin=seal_pin,
            created_utc=utc(), fits=diagnostics))
        final = {}
        for fit in FITS:
            budget()
            row = fits[str(fit)]
            models = dict(row['models'], **diagnostics[str(fit)]['models'])
            audit, audit_pin = run_phase(output / 'records' / f'fit_{fit}_TRAIN_AUDIT.json', 'TRAIN_AUDIT', fit,
                models, reload_items(row['graph_manifest_pin'], row['hidden_pin'],
                    protocol['splits'][str(fit)]['TRAIN_AUDIT']), protocol_sha, budget)
            gen, selection = read(row['GEN_record_pin']['path']), read(row['SELECT_record_pin']['path'])
            all_worlds = sorted(gen['worlds'] + selection['worlds'] + audit['worlds'], key=lambda w: w['world_index'])
            restore_pin = copy_original(row['models']['KEEP']['model_pin'], output / 'restored' / f'fit_{fit}_C.json.gz')
            final[str(fit)] = dict(row, diagnostic_models=diagnostics[str(fit)]['models'],
                phase_records=dict(GEN=row['GEN_record_pin'], SELECT=row['SELECT_record_pin'], TRAIN_AUDIT=audit_pin),
                phase_summaries=dict(GEN=gen['means'], SELECT=selection['means'], TRAIN_AUDIT=audit['means']),
                all_TRAIN_summaries=aggregate(all_worlds, list(row['models'])), restore_pin=restore_pin,
                restore_scope='isolated original-byte copy verification; no live model was mutated')
            del audit, gen, selection, all_worlds
            gc.collect()
        unchanged = verify_originals(protocol)
        report = dict(schema='hepta-value-main-results-v1', status='COMPLETED', created_utc=created_utc,
            completed_utc=utc(), protocol_sha256=protocol_sha, candidate_selection_seal_pin=seal_pin,
            diagnostic_seal_pin=diagnostic_pin, fits=final,
            work=dict(value_graph=dict(graph_math.WORK), head_candidates=dict(candidates.WORK)),
            resources=resource_record(wall_start), source_inputs_unchanged=unchanged,
            scope='All GEN/SELECT/TRAIN_AUDIT worlds are exposed old TRAIN. No independent quality confirmation here.')
        save(output / 'RESULTS.json', report)
        print(canonical(dict(status='COMPLETED', results_pin=pin(output / 'RESULTS.json'))), flush=True)
    except BaseException as error:
        save(output / 'FAILED.json', dict(status='FAILED', created_utc=utc(), error_type=type(error).__name__,
            error=str(error), traceback=traceback.format_exc(), resources=resource_record(wall_start),
            work=dict(value_graph=dict(graph_math.WORK), head_candidates=dict(candidates.WORK)),
            retry_permitted=False))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args())
