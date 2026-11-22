"""Create-only generation, fresh selection, and sealed fresh confirmation."""
from pathlib import Path
import argparse
import json
import sys
import time
import traceback
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'vendor'))
from data_contract import read, save, save_arrays, pin, verify, head, exact_radius, model_with_head
from evaluation_io import model_entry, run_phase
import value_graph as graph_math
from soft_value import Forest, optimize
from study_io import admit, checked, gen_items, context, new_worlds, build_items, resolve_output_pin


def exact_gate(anchor, rows):
    if not exact_radius(anchor, rows)['within_shared_ball']:
        raise ArithmeticError('actual encoded head outside original exact ball')


def make_models(output, fit, base, original_pin, candidates):
    models = {'KEEP': model_entry(original_pin['path'], base, 'KEEP', 'KEEP')}
    for family in ('DIRECT', 'BP'):
        rows = candidates[family]
        if rows is None:
            models[family] = models['KEEP']
        else:
            path = output / 'models' / f'fit_{fit}_{family}.json.gz'
            save(path, model_with_head(base, rows, 'G')[0])
            models[family] = model_entry(path, base, 'G', family)
    anchor = head(base)
    primary = head(read(models['DIRECT']['model_pin']['path']))
    delta = primary - anchor
    edits = {'HALF': anchor + .5 * delta, 'OPPOSITE': anchor - delta,
             'Q_ONLY': np.vstack((primary[:3], anchor[3])),
             'B_ONLY': np.vstack((anchor[:3], primary[3]))}
    actual_norm = float(np.linalg.norm(delta))
    for seed in (11, 23, 37, 53):
        generator = np.random.Generator(np.random.PCG64(seed ^ fit))
        direction = generator.normal(size=anchor.shape)
        direction *= actual_norm / float(np.linalg.norm(direction))
        edits[f'RANDOM_{seed}'] = anchor + direction
    controls = {}
    for name, rows in edits.items():
        exact_gate(anchor, rows)
        encoded_norm = float(np.linalg.norm(rows - anchor))
        if name.startswith('RANDOM') and abs(encoded_norm - actual_norm) > 1e-15 + 1e-12 * actual_norm:
            raise ArithmeticError('encoded random control norm differs')
        path = output / 'models' / f'fit_{fit}_{name}.json.gz'
        save(path, model_with_head(base, rows, 'G')[0])
        models[name] = model_entry(path, base, 'G', name, diagnostic=True)
        controls[name] = dict(actual_encoded_norm=encoded_norm,
                              primary_encoded_norm=actual_norm,
                              zero_direction_alias=actual_norm == 0.)
    return models, controls


def oracle_diagnostics(items, anchor, budget):
    records = []
    for item in items:
        budget()
        graph = item['graph']
        scores, _, _ = graph_math.strict_scores(anchor, item['H'])
        original, obs = graph_math.evaluate(graph, scores)
        arms = {'KEEP': original}
        for name in ('Q_ORACLE', 'B_ORACLE', 'BOTH_ORACLE'):
            changed = scores.copy()
            if name in ('Q_ORACLE', 'BOTH_ORACLE'):
                changed[:, 1:4] = np.asarray(graph['qstar'])[:, 1:4]
            if name in ('B_ORACLE', 'BOTH_ORACLE'):
                changed[:, 4:6] = np.asarray(graph['terminal'])[:, 4:6]
            arms[name], _ = graph_math.evaluate(graph, changed, obs['occupancy'])
        if abs(arms['BOTH_ORACLE']['optimal_regret']) > 2e-10:
            raise ArithmeticError('joint action oracle failed to attain own optimum')
        records.append(dict(world_index=item['world_index'], graph_pin=item['graph_pin'], arms=arms))
    means = {a: {k: float(np.mean([w['arms'][a][k] for w in records]))
                  for k in ('utility', 'optimal_regret', 'terminal_gap_contribution',
                            'continuation_gap_contribution', 'expected_terminal_reward', 'expected_expense')}
             for a in ('KEEP', 'Q_ORACLE', 'B_ORACLE', 'BOTH_ORACLE')}
    return dict(scope='GEN-only score interventions, not weight edits or deployable policies', worlds=records, means=means)


def permutation_control(base, rows, items):
    permutation = np.arange(48)[::-1]
    transformed = json.loads(json.dumps(base))
    transformed['network']['w1'] = np.asarray(base['network']['w1'])[permutation].tolist()
    transformed['network']['b1'] = np.asarray(base['network']['b1'])[permutation].tolist()
    changed = np.column_stack((rows[:, :48][:, permutation], rows[:, 48]))
    maximum = broken = 0.
    action_differences = count = 0
    for item in items:
        H = graph_math.strict_hidden(base, item['X'])
        Hp = graph_math.strict_hidden(transformed, item['X'])
        scores, _, _ = graph_math.strict_scores(rows, H)
        permuted, _, _ = graph_math.strict_scores(changed, Hp)
        invalid, _, _ = graph_math.strict_scores(rows, Hp)
        masks = np.asarray(item['graph']['masks'])
        maximum = max(maximum, float(np.max(np.abs(scores - permuted))))
        broken = max(broken, float(np.max(np.abs(scores - invalid))))
        action_differences += int(np.count_nonzero(np.where(masks, scores, -np.inf).argmax(1)
                                                  != np.where(masks, permuted, -np.inf).argmax(1)))
        count += len(H)
    if maximum > 2e-12 or broken <= 1e-6:
        raise ArithmeticError('representation equivalence/broken-wire control failed')
    return dict(rows=count, maximum_score_error=maximum, action_differences=action_differences,
                broken_upstream_only_maximum_difference=broken, permutation=permutation.tolist())


def completed_previous(path, protocol_sha, phase):
    previous = read(path / 'RESULTS.json')
    process = read(path.parent / 'PROCESS.json')
    if (previous['status'] != 'COMPLETED' or previous['phase'] != phase or
            previous['protocol_sha256'] != protocol_sha or process['status'] != 'COMPLETED' or
            process['returncode'] != 0 or process['wall_timeout'] or not process['protocol_unchanged'] or
            process['protocol_pin']['sha256'] != protocol_sha or
            process['result_pin']['sha256'] != pin(path / 'RESULTS.json')['sha256']):
        raise ValueError('complete source-bound previous phase required before entropy')
    return previous


def relocate_models(models, previous, current_root):
    mapped = {}
    for name, model in models.items():
        entry = dict(model)
        source = Path(model['model_pin']['path'])
        original = Path(previous['original_run_root'])
        if source.is_relative_to(original):
            entry['model_pin'] = resolve_output_pin(model['model_pin'], original, current_root)
        else:
            # Original KEEP inputs are remapped by the caller, never guessed here.
            entry['model_pin'] = model['model_pin']
        mapped[name] = entry
    return mapped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('generation', 'selection', 'confirmation'))
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--previous', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started, wall = time.process_time(), time.monotonic()
    protocol_sha = pin(args.protocol)['sha256']
    fits = {}
    save(output / 'STARTED.json', dict(phase=args.phase, protocol_sha256=protocol_sha))
    try:
        protocol = admit(args.protocol, args.inputs)
        def budget():
            if time.process_time() - started > protocol['limits'][args.phase]['cpu_soft_seconds']:
                raise TimeoutError('frozen phase CPU limit')
        if args.phase == 'generation':
            for fit in protocol['fit_ids']:
                budget()
                base, items = gen_items(protocol, args.inputs, fit)
                setup = time.process_time()
                forest = Forest(items)
                anchor = head(base)
                settings = dict(protocol['optimization'], radius=exact_radius(anchor)['numeric_radius'])
                setup_cpu = time.process_time() - setup
                candidates, reports = {}, {}
                for family in ('DIRECT', 'BP'):
                    candidates[family], reports[family] = optimize(forest, anchor, family, settings, exact_gate, budget)
                original_pin = checked(args.inputs, protocol['fits'][str(fit)]['model'])
                models, controls = make_models(output, fit, base, original_pin, candidates)
                generation = save(output / 'generation' / f'fit_{fit}.json', dict(
                    optimizer_reports=reports, forest_setup_CPU_seconds=setup_cpu, controls=controls,
                    GEN_worlds=len(items), GEN_states=len(forest.H), family_order=['DIRECT', 'BP']))
                fits[str(fit)] = dict(models=models, generation_pin=generation)
                save(output / 'progress' / f'fit_{fit}.json', fits[str(fit)])
            seal = save(output / 'CANDIDATES_FROZEN.json', dict(protocol_sha256=protocol_sha,
                fits=fits, primary_candidates=['KEEP', 'DIRECT', 'BP'], original_run_root=str(args.run_root.resolve())))
            for fit in protocol['fit_ids']:
                base, items = gen_items(protocol, args.inputs, fit)
                row = fits[str(fit)]
                record, record_pin = run_phase(output / 'records' / f'fit_{fit}_GEN.json', 'GEN', fit,
                    row['models'], items, protocol_sha, budget)
                row['GEN_means'], row['GEN_record_pin'] = record['means'], record_pin
                row['oracle_pin'] = save(output / 'diagnostics' / f'fit_{fit}_ORACLES.json',
                    oracle_diagnostics(items, head(base), budget))
            extra = dict(candidate_seal_pin=seal)
        else:
            previous_phase = 'generation' if args.phase == 'selection' else 'selection'
            previous = completed_previous(args.previous, protocol_sha, previous_phase)
            seal_name = 'CANDIDATES_FROZEN.json' if args.phase == 'selection' else 'SELECTION_FROZEN.json'
            expected_seal = previous['candidate_seal_pin'] if args.phase == 'selection' else previous['selection_seal_pin']
            actual_seal = pin(args.previous / seal_name)
            if actual_seal['sha256'] != expected_seal['sha256']:
                raise ValueError('previous seal identity changed')
            seal_record = read(args.previous / seal_name)
            if seal_record['protocol_sha256'] != protocol_sha:
                raise ValueError('previous seal protocol mismatch')
            for fit in protocol['fit_ids']:
                if seal_record['fits'][str(fit)]['models'] != previous['fits'][str(fit)]['models']:
                    raise ValueError('models changed after seal')
                if args.phase == 'confirmation' and seal_record['fits'][str(fit)]['choices'] != previous['fits'][str(fit)]['choices']:
                    raise ValueError('choices changed after seal')
                sealed_models = relocate_models(previous['fits'][str(fit)]['models'], previous, args.run_root.resolve())
                for entry in sealed_models.values():
                    if entry['canonical_model_sha256'] == sealed_models['KEEP']['canonical_model_sha256']:
                        entry['model_pin'] = checked(args.inputs, protocol['fits'][str(fit)]['model'])
                    verify(entry['model_pin'])
            used = set(protocol['known_schedule_hashes'])
            if args.phase == 'confirmation':
                selection_worlds = read(args.previous / 'WORLDS_FROZEN.json')
                used.update(x['schedule_sha256'] for row in selection_worlds['groups'].values()
                            for domain in row.values() for x in domain['worlds'])
            worlds = new_worlds(protocol, args.phase, args.previous / seal_name, used, output)
            ctx = context(protocol)
            for fit in protocol['fit_ids']:
                base = read(checked(args.inputs, protocol['fits'][str(fit)]['model'])['path'])
                row = previous['fits'][str(fit)]
                models = relocate_models(row['models'], previous, args.run_root.resolve())
                for name, entry in models.items():
                    if entry['canonical_model_sha256'] == models['KEEP']['canonical_model_sha256']:
                        entry['model_pin'] = checked(args.inputs, protocol['fits'][str(fit)]['model'])
                fits[str(fit)] = dict(models=models, records={}, preparation={})
                domains = ('iid',) if args.phase == 'selection' else ('iid', 'ood')
                for domain in domains:
                    items, preparation = build_items(protocol, ctx, base,
                        worlds['groups'][str(fit)][domain]['worlds'], output / 'graphs' / f'{fit}_{domain}', budget)
                    record, record_pin = run_phase(output / 'records' / f'fit_{fit}_{domain}.json',
                        args.phase.upper(), fit, models, items, protocol_sha, budget, domain=domain)
                    fits[str(fit)]['records'][domain] = record_pin
                    fits[str(fit)]['preparation'][domain] = preparation
                    fits[str(fit)].setdefault('means', {})[domain] = record['means']
                    if args.phase == 'selection':
                        choices, gates = {}, {}
                        for family in ('DIRECT', 'BP'):
                            mean = record['means'][family]
                            passed = (mean['delta_original'] > protocol['mean_improvement_threshold'] and
                                      mean['delta_original_min'] >= -protocol['maximum_selection_world_loss'])
                            choices[family] = family if passed else 'KEEP'
                            gates[family] = dict(passed=passed, mean_delta=mean['delta_original'],
                                minimum_world_delta=mean['delta_original_min'])
                        fits[str(fit)].update(choices=choices, gates=gates)
                        fits[str(fit)]['permutation_control'] = permutation_control(base,
                            head(read(models['DIRECT']['model_pin']['path'])), items)
                    else:
                        fits[str(fit)]['choices'] = row['choices']
                save(output / 'progress' / f'fit_{fit}.json', fits[str(fit)])
            if args.phase == 'selection':
                seal = save(output / 'SELECTION_FROZEN.json', dict(protocol_sha256=protocol_sha,
                    fits=fits, original_run_root=str(args.run_root.resolve()), candidate_seal_pin=actual_seal))
                extra = dict(selection_seal_pin=seal, worlds_pin=pin(output / 'WORLDS_FROZEN.json'))
            else:
                from scipy.stats import t
                intervals = {}
                for domain in ('iid', 'ood'):
                    values = {'KEEP': [], 'DIRECT': [], 'BP': []}
                    for fit in protocol['fit_ids']:
                        row = fits[str(fit)]
                        values['KEEP'].append(row['means'][domain]['KEEP']['utility'])
                        for family in ('DIRECT', 'BP'):
                            values[family].append(row['means'][domain][row['choices'][family]]['utility'])
                    intervals[domain] = {}
                    for a, b in (('DIRECT', 'KEEP'), ('BP', 'KEEP'), ('DIRECT', 'BP')):
                        delta = np.asarray(values[a]) - values[b]
                        mean = float(delta.mean())
                        half = float(t.ppf(1 - .05 / 12, 4) * delta.std(ddof=1) / np.sqrt(5))
                        intervals[domain][f'{a}_MINUS_{b}'] = dict(mean=mean, lower=mean-half, upper=mean+half,
                            checkpoint_deltas=delta.tolist(), n=5, familywise_target=.95, comparisons=6)
                extra = dict(worlds_pin=pin(output / 'WORLDS_FROZEN.json'), contrasts=intervals,
                    improvement_claim={family: all(intervals[d][f'{family}_MINUS_KEEP']['lower'] > 0 and
                        min(fits[str(f)]['means'][d][fits[str(f)]['choices'][family]]['delta_original_min']
                            for f in protocol['fit_ids']) >= -protocol['maximum_selection_world_loss']
                        for d in ('iid', 'ood')) for family in ('DIRECT', 'BP')})
        result = dict(status='COMPLETED', phase=args.phase, protocol_sha256=protocol_sha, fits=fits,
            original_run_root=str(args.run_root.resolve()), **extra,
            CPU_seconds_from_entry=time.process_time()-started, wall_seconds=time.monotonic()-wall,
            work=dict(graph_math.WORK), scope=protocol['scope'])
        save(output / 'RESULTS.json', result)
        print(json.dumps(dict(status=result['status'], phase=args.phase,
                             CPU_seconds=result['CPU_seconds_from_entry'], work=result['work'])))
    except Exception as error:
        save(output / 'FAILURE.json', dict(error=repr(error), traceback=traceback.format_exc(),
             phase=args.phase, protocol_sha256=protocol_sha, completed_fits=list(fits),
             CPU_seconds_from_entry=time.process_time()-started, wall_seconds=time.monotonic()-wall))
        raise


if __name__ == '__main__':
    main()
