"""Fresh-process round-2 fits. Reuses frozen round-1 fit/residual without rewriting history."""
import argparse
import json
import os
import platform
import resource
import sys
import time
from pathlib import Path

import numpy as np
import scipy
import torch

from models import StateStem, TransformerStem, assign, vector
from problem import decimal_oracle, make_world, terminals
from run import digest, fit, predictions, residual, scores, write_json
from structured import (StructuredStem, invariant_probe, new_terminals, panel_specs,
                        panel_world, priced_decisions)


def source_hashes():
    root = Path(__file__).resolve().parent
    return {p.name: digest(p.read_bytes()) for p in sorted(root.glob('*.py'))}


def make_model(family, seed):
    if family == 'raw':
        return StateStem(seed)
    if family == 'structured':
        return StructuredStem(seed)
    if family == 'transformer':
        return TransformerStem(seed)
    raise ValueError('unknown model family')


def save_npz(path, arrays):
    with open(path, 'xb') as f:
        np.savez_compressed(f, **arrays)


def execute(args):
    begun = time.perf_counter(), time.process_time()
    args.out.mkdir(parents=True, exist_ok=False)
    plan = dict(schema='hepta.native-stem.structure.r2', family=args.family, optimizer=args.optimizer,
                seed=args.seed, cpu_cap=args.cpu_seconds, source_sha256=source_hashes(),
                training='unchanged round-1 full 12x12x3 collocation law', panels=panel_specs(),
                holdout_selects_weights=False, new_training_coverage=False,
                parent_archive_sha256='99fcd4caa91320dafdc99483f120eec5a1f60c1039934bdf708dce39c4cd88c1')
    plan_hash = write_json(args.out / 'PLAN.json', plan)
    write_json(args.out / 'STARTED.json', dict(plan_sha256=plan_hash, pid=os.getpid()))
    train = make_world()
    g = torch.tensor(terminals(train, 'train'), dtype=torch.float64)
    w = train.tensor()
    model = None if args.family == 'direct' else make_model(args.family, args.seed)
    initialized = time.process_time()
    initial = None if model is None else vector(model)
    if initial is not None:
        with open(args.out / 'INITIAL.npy', 'xb') as f:
            np.save(f, initial, allow_pickle=False)
    if args.optimizer == 'none':
        fitting = dict(status='untrained_control', training_cpu_seconds=0.0, counts={})
    else:
        arm = {'adam': 'A' if args.family == 'transformer' else 'B',
               'trf': 'C', 'lbfgs': 'B_LBFGS'}[args.optimizer]
        fitting = fit(model, arm, w, g, 3, args.cpu_seconds)
    fit_peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    selected = None if model is None else vector(model)
    selected_hash = None if selected is None else digest(selected.tobytes())
    if selected is not None:
        with open(args.out / 'WEIGHTS.npy', 'xb') as f:
            np.save(f, selected, allow_pickle=False)
    # Freeze selected bytes before any new panel is created or examined.
    write_json(args.out / 'WEIGHT_SEAL.json', dict(weight_sha256=selected_hash))
    raw, timings = {}, {}
    prediction_start = time.process_time()
    arm = 'D' if model is None else 'B'
    for name, family, bits, horizon, intervention in panel_specs():
        world = panel_world(bits, intervention)
        terminal = new_terminals(world, family)
        t = time.process_time()
        raw[name] = predictions(model, arm, world.tensor(), terminal, horizon)
        if not np.isfinite(raw[name]).all():
            raise FloatingPointError('nonfinite prediction: ' + name)
        raw[name + '_terminal'] = terminal
        timings[name] = dict(cpu_seconds=time.process_time() - t,
                             terminal_sha256=digest(terminal.tobytes()),
                             prediction_sha256=digest(raw[name].tobytes()))
    save_npz(args.out / 'PREDICTIONS.npz', raw)
    prediction_hash = digest((args.out / 'PREDICTIONS.npz').read_bytes())
    write_json(args.out / 'PREDICTIONS_SEAL.json', dict(sha256=prediction_hash, weights=selected_hash))
    prediction_cpu = time.process_time() - prediction_start
    oracle_start, metrics, oracles = time.process_time(), {}, {}
    for name, family, bits, horizon, intervention in panel_specs():
        world = panel_world(bits, intervention)
        truth = decimal_oracle(world, raw[name + '_terminal'], horizon)
        out = scores(raw[name], truth, world, probability=name == 'probability_joint')
        out.update(priced_decisions(raw[name], truth))
        metrics[name] = out
        oracles[name] = truth
    save_npz(args.out / 'ORACLES.npz', oracles)
    oracle_cpu = time.process_time() - oracle_start
    check_start = time.process_time()
    invariants, training_mse, replay_error = {}, 0.0, 0.0
    if model is not None:
        invariants = invariant_probe(model, train)
        with torch.no_grad():
            training_mse = float(residual(model, w, g, 3).square().sum())
        restored = make_model(args.family, args.seed)
        saved = np.load(args.out / 'WEIGHTS.npy', allow_pickle=False)
        assign(restored, saved)
        for name, family, bits, horizon, intervention in panel_specs():
            world = panel_world(bits, intervention)
            again = predictions(restored, 'B', world.tensor(), raw[name + '_terminal'], horizon)
            replay_error = max(replay_error, float(np.max(np.abs(again - raw[name]))))
        if selected_hash != digest(vector(model).tobytes()) or replay_error > 1e-13:
            raise AssertionError('weight mutation or saved-composition replay drift')
    if plan['source_sha256'] != source_hashes():
        raise AssertionError('source mutated during trial')
    report = dict(plan_sha256=plan_hash, family=args.family, optimizer=args.optimizer, seed=args.seed,
                  cpu_cap=args.cpu_seconds, fit=fitting, panels=timings, metrics=metrics,
                  parameter_count=0 if selected is None else selected.size,
                  initial_sha256=None if initial is None else digest(initial.tobytes()),
                  selected_sha256=selected_hash, prediction_sha256=prediction_hash,
                  trained_parameter_change_norm=0.0 if selected is None else float(np.linalg.norm(selected - initial)),
                  training_mse=training_mse, invariant_probes=invariants, replay_max_error=replay_error,
                  replay_panels=0 if model is None else len(panel_specs()),
                  training_peak_rss_bytes=fit_peak,
                  process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                  phases_cpu_seconds=dict(initialization_and_plan=initialized - begun[1],
                                          predictions_and_seal=prediction_cpu,
                                          oracle_scoring_and_save=oracle_cpu,
                                          diagnostic_and_replay=time.process_time() - check_start),
                  total_cpu_from_main=time.process_time() - begun[1],
                  total_wall_from_main=time.perf_counter() - begun[0],
                  environment=dict(python=sys.version, torch=torch.__version__, numpy=np.__version__,
                                   scipy=scipy.__version__, platform=platform.platform(),
                                   torch_threads=torch.get_num_threads()),
                  total_flops=None, energy_joules=None, peak_gpu_bytes=None,
                  production_authorized=False, project_cloud_execution=False,
                  general_pmp_solver=False, exact_compute_matched=False)
    write_json(args.out / 'REPORT.json', report)
    print(json.dumps(dict(family=args.family, optimizer=args.optimizer, seed=args.seed,
                          new=metrics['new_uniform']['rmse'], composed=metrics['new_composed']['rmse'],
                          probability=metrics['probability_joint']['rmse'])), flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--family', choices=['raw', 'structured', 'transformer', 'direct'], required=True)
    p.add_argument('--optimizer', choices=['adam', 'trf', 'lbfgs', 'none'], required=True)
    p.add_argument('--seed', type=int, default=11)
    p.add_argument('--cpu-seconds', type=float, default=8)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    if not np.isfinite(args.cpu_seconds) or args.cpu_seconds <= 0 or args.seed < 0:
        p.error('invalid budget or seed')
    if (args.family == 'direct' and args.optimizer != 'none') or (
            args.family == 'transformer' and args.optimizer != 'adam'):
        p.error('unsupported family/optimizer')
    execute(args)


if __name__ == '__main__':
    main()
