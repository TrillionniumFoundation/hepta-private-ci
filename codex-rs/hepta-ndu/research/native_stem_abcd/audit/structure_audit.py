"""Post-seal verification and disclosed training-family approximation-floor diagnostic.

This audit never trains, selects or edits a model. The floor analysis is post hoc.
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--runs', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.source.resolve()))
    import torch
    from models import assign, vector
    from problem import decimal_oracle, make_world, terminals
    from run import digest, predictions, scores, write_json
    from structured import StructuredStem, new_terminals, panel_specs, panel_world, priced_decisions
    from structure_sweep import run_specs
    from structure_trial import make_model, source_hashes

    started = time.process_time(), time.perf_counter()
    args.out.mkdir(parents=True, exist_ok=False)
    root = args.runs
    plan = json.loads((root / 'PLAN.json').read_text())
    complete = json.loads((root / 'COMPLETE.json').read_text())
    assert complete['plan_sha256'] == digest((root / 'PLAN.json').read_bytes())
    assert plan['source_sha256'] == source_hashes()
    assert plan['runs'] == run_specs()
    assert len(complete['census']) == len(plan['runs']) == 40
    assert complete['completed'] == 40 and complete['failed'] == 0
    expected = [f"{s['family']}-{s['optimizer']}-s{s['seed']}-b{s['cpu_seconds']}" for s in plan['runs']]
    assert expected == [r['name'] for r in complete['census']]
    reports, rows, truths = {}, [], {}
    scalar_values, replay_panels, replay_max = 0, 0, 0.0
    # One new Decimal reference per panel; all 40 archived oracle copies must match.
    for name, family, bits, horizon, intervention in panel_specs():
        world = panel_world(bits, intervention)
        truths[name] = decimal_oracle(world, new_terminals(world, family), horizon)
    for entry in complete['census']:
        folder = root / entry['name']
        assert entry['status'] == 'completed'
        report_bytes = (folder / 'REPORT.json').read_bytes()
        assert digest(report_bytes) == entry['report_sha256']
        report = json.loads(report_bytes)
        child_plan = json.loads((folder / 'PLAN.json').read_text())
        assert report['plan_sha256'] == digest((folder / 'PLAN.json').read_bytes())
        assert child_plan['source_sha256'] == plan['source_sha256']
        for field in ('family', 'optimizer', 'seed'):
            assert report[field] == child_plan[field] == entry[field]
        assert report['cpu_cap'] == entry['cpu_seconds']
        pred_bytes = (folder / 'PREDICTIONS.npz').read_bytes()
        seal = json.loads((folder / 'PREDICTIONS_SEAL.json').read_text())
        assert digest(pred_bytes) == seal['sha256'] == report['prediction_sha256']
        pred = np.load(folder / 'PREDICTIONS.npz', allow_pickle=False)
        oracle = np.load(folder / 'ORACLES.npz', allow_pickle=False)
        model = None
        if entry['family'] != 'direct':
            model = make_model(entry['family'], entry['seed'])
            initial = np.load(folder / 'INITIAL.npy', allow_pickle=False)
            weights = np.load(folder / 'WEIGHTS.npy', allow_pickle=False)
            np.testing.assert_array_equal(vector(model), initial)
            assert digest(initial.tobytes()) == report['initial_sha256']
            assert digest(weights.tobytes()) == report['selected_sha256'] == seal['weights']
            assert report['parameter_count'] == weights.size
            if entry['family'] in ('raw', 'structured'):
                assert weights.size == 65
            if entry['optimizer'] != 'none':
                assert not np.array_equal(initial, weights)
                assert report['fit']['initial_weights_sha256'] == report['initial_sha256']
            else:
                np.testing.assert_array_equal(initial, weights)
            assign(model, weights)
        reports[entry['name']] = report
        for name, family, bits, horizon, intervention in panel_specs():
            world = panel_world(bits, intervention)
            terminal = new_terminals(world, family)
            np.testing.assert_array_equal(pred[name + '_terminal'], terminal)
            np.testing.assert_array_equal(oracle[name], truths[name])
            assert digest(pred[name].tobytes()) == report['panels'][name]['prediction_sha256']
            assert np.isfinite(pred[name]).all()
            recalculated = scores(pred[name], truths[name], world, name == 'probability_joint')
            recalculated.update(priced_decisions(pred[name], truths[name]))
            for key, value in recalculated.items():
                if value is None or isinstance(value, (bool, str)):
                    assert value == report['metrics'][name][key], (entry['name'], name, key)
                else:
                    assert np.isclose(value, report['metrics'][name][key], rtol=1e-12, atol=1e-14)
            again = predictions(model, 'D' if model is None else 'B', world.tensor(), terminal, horizon)
            error = float(np.max(np.abs(again - pred[name])))
            assert error <= 1e-13
            replay_max = max(replay_max, error)
            replay_panels += 1
            scalar_values += int(pred[name][1:].size)
            rows.append(dict(run=entry['name'], family=entry['family'], optimizer=entry['optimizer'],
                             seed=entry['seed'], cpu_cap=entry['cpu_seconds'], panel=name,
                             rmse=recalculated['rmse'], max_error=recalculated['final_max_error'],
                             priced_regret=recalculated['priced_decision_regret'],
                             priced_accuracy=recalculated['priced_decision_accuracy'],
                             invalid_probability=recalculated.get('probability_invalid_fraction'),
                             training_cpu=report['fit']['training_cpu_seconds'],
                             whole_child_cpu=entry['whole_child_cpu_seconds'],
                             whole_child_wall=entry['whole_child_wall_seconds'],
                             peak_rss=report['process_peak_rss_bytes']))
    pairs = []
    for family in ('raw', 'structured'):
        for cap in (2, 8):
            for seed in (11, 23, 47):
                b = reports[f'{family}-adam-s{seed}-b{cap}']
                c = reports[f'{family}-trf-s{seed}-b{cap}']
                assert b['initial_sha256'] == c['initial_sha256']
                pairs.append(dict(family=family, seed=seed, cap=cap,
                                  B_composed=b['metrics']['new_composed']['rmse'],
                                  C_composed=c['metrics']['new_composed']['rmse'],
                                  B_over_C_composed=b['metrics']['new_composed']['rmse'] /
                                  c['metrics']['new_composed']['rmse']))
    # Relax the gate to one independent scalar per state, constant across tasks.
    # This superset can only lower the first-step error. The full three-step
    # squared defect is >= first-step optimum / 3. This is not a global solver
    # certificate, and FP evaluation is not an outward-rounded interval proof.
    world = make_world()
    g = torch.tensor(terminals(world, 'train'), dtype=torch.float64)
    w = world.tensor()
    a, b = g[:, w['left']], g[:, w['right']]
    low = w['c'] + w['gamma'] * StructuredStem.certainty(a, b, w['p'], w['risk'] / 2)
    high = w['c'] + w['gamma'] * StructuredStem.certainty(a, b, w['p'], 1.5 * w['risk'])
    target = decimal_oracle(world, g.numpy(), 1)[1]
    d, y = (low - high).numpy(), target - high.numpy()
    denominator = np.sum(d * d, axis=0)
    gate = np.clip(np.divide(np.sum(d * y, axis=0), denominator,
                            out=np.zeros_like(denominator), where=denominator > 0), 0, 1)
    first_mse = float(np.mean((d * gate - y) ** 2))
    floor = dict(posthoc=True, first_step_mse_relaxed_minimum=first_mse,
                 full_three_step_mse_lower_bound=first_mse / 3,
                 relaxed_gate_per_state=gate.tolist(), interval_certified=False,
                 claim='analytic lower-bound formula evaluated numerically; not an optimization/selection input')
    for name, report in reports.items():
        if report['family'] == 'structured':
            assert report['training_mse'] + 1e-14 >= first_mse / 3
    with open(args.out / 'SCORES.csv', 'x', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write_json(args.out / 'PAIRED.json', pairs)
    write_json(args.out / 'APPROXIMATION_FLOOR.json', floor)
    receipt = dict(runs_verified=40, source_sha256=source_hashes(), complete_census_verified=True,
                   independent_reference_panels=10, saved_prediction_panels_replayed=replay_panels,
                   maximum_replay_error=replay_max, verified_scalar_predictions=scalar_values,
                   bc_initialization_pairs_verified=len(pairs), metric_rows=len(rows),
                   extra_audit_cpu_seconds=time.process_time() - started[0],
                   extra_audit_wall_seconds=time.perf_counter() - started[1],
                   no_training_or_selection=True, production_authorized=False)
    write_json(args.out / 'AUDIT.json', receipt)
    print(json.dumps(receipt, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
