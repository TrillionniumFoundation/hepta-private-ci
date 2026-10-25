"""Fit and freeze paired/actor candidates on previously observed sources only."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from ...abc_next.value import load_controller
from ...abc_recovery.base_recovery import file_sha, write_json
from ...abc_recovery.control import PLANS
from ...abc_next.sensor_run import load_sensor
from .features import from_tree, assemble
from .models import Bundle, CONFIG, action_values, actor_values, fit_head, fit_pair, h1_examples, save
from .registry import HERE, pins, asset_pins, load_model


def ce(values):
    return float(-torch.logsumexp(-2 * values.double(), 0) / 2 + np.log(len(values)) / 2)


@torch.no_grad()
def actions(bundle, cheap, full, old, remaining, policy):
    if policy == 'teacher' or (policy == 'gate' and bundle.threshold is None):
        return old.choose(full, remaining), torch.zeros(len(full), dtype=torch.bool)
    actor, pair, accept, _, _ = bundle.propose(cheap, remaining)
    if policy == 'pair':
        return pair, torch.ones_like(accept)
    if policy == 'actor':
        return actor, torch.ones_like(accept)
    selected = actor.clone()
    if (~accept).any():
        selected[~accept] = old.choose(full[~accept], remaining)
    return selected, accept


@torch.no_grad()
def select_paths(bundle, cheap, full, old, policy):
    first, cheap_used = actions(bundle, cheap[:, 0], full[:, 0], old, 2, policy)
    paths = torch.zeros(len(first), dtype=torch.long)
    calls = torch.ones(len(first), dtype=torch.long)
    cheap_calls = cheap_used.long()
    for action in range(1, 5):
        rows = torch.nonzero(first == action).flatten()
        if len(rows):
            second, use = actions(bundle, cheap[rows, action], full[rows, action], old, 1, policy)
            paths[rows] = torch.where(second == 0, action, 5 + (action - 1) * 4 + second - 1)
            calls[rows] += 1; cheap_calls[rows] += use.long()
    return paths, calls, cheap_calls


def evaluate(data, path, calls, cheap_calls, *, cheap_ms, teacher_ms, gate_enabled):
    rows = torch.arange(len(path)); metric = data['metrics']['primary']
    utility = metric['utility'][rows, path].double()
    success = metric['joint_fact_correct'][rows, path].double()
    lengths = torch.tensor([len(PLANS[p]) for p in path.tolist()]).double()
    quote = calls * cheap_ms + (calls - cheap_calls) * teacher_ms if gate_enabled else calls * teacher_ms
    return {"raw_CE": ce(utility), "success": float(success.mean()),
            "quoted_net_CE": ce(utility - .002 * lengths - .002 * quote),
            "cheap_decisions": int(cheap_calls.sum()), "decisions": int(calls.sum()),
            "quoted_ms": float(quote.double().mean())}


@torch.no_grad()
def cost_quote(asset, seed, bundle, data, folder, old):
    """Declared kernels, not an invented request/energy accounting unit."""
    snapshot = load_model(asset, seed)
    sensor = load_sensor(asset / 'abc3-runs/public-sensor-001/sensor.pt')
    with np.load(folder / 'clean.npz', allow_pickle=False) as archive:
        bits = archive['pixels_bits'][0, :128]
        tokens = torch.from_numpy(archive['tokens'][0, :128].astype(np.int64))
    pixels = torch.from_numpy(np.unpackbits(bits, axis=1, count=1568).copy()).reshape(-1, 1, 28, 56).float()
    full = data['features'][:128, 0]
    cheap_times, teacher_times = [], []
    for i in range(len(full)):
        panel = pixels[i:i + 1].reshape(1, 1, 28, 2, 28).permute(0, 3, 1, 2, 4).flatten(0, 1)
        start = time.perf_counter_ns()
        snapshot._model.pixel_encoder(torch.cat((panel, torch.ones_like(panel)), 1))
        sensor(panel, torch.ones_like(panel)); old.choose(full[i:i + 1], 2)
        teacher_times.append((time.perf_counter_ns() - start) / 1e6)
        start = time.perf_counter_ns()
        x = assemble(full[i:i + 1, :384], pixels[i:i + 1], tokens[i:i + 1], torch.ones(1, 1))
        bundle.propose(x, 2)
        cheap_times.append((time.perf_counter_ns() - start) / 1e6)
    return {"teacher_ms": float(np.median(teacher_times)), "cheap_ms": float(np.median(cheap_times)),
            "n": len(full), "all_teacher_ms": teacher_times, "all_cheap_ms": cheap_times,
            "scope": "historical draft kernels only; selection quote, actual request measured separately"}


@torch.no_grad()
def diagnostics(bundle, cheap, full, data, old):
    x, difference, _ = h1_examples(cheap, data['metrics']['primary']['utility'])
    predicted = bundle.critic(x)
    actual = torch.cat((torch.zeros(len(x), 1), difference), 1)
    actual[:, 1] = float('inf')
    choice = action_values(bundle.critic, x, 1).argmin(-1)
    chosen = actual[torch.arange(len(x)), choice]
    predicted_selected = torch.cat((torch.zeros(len(x), 1), predicted), 1)[torch.arange(len(x)), choice]
    empirical_best = actual.min(-1).values
    rich = full.clone(); rich[:, 0, -1] = .5
    teacher = old.choose(rich.flatten(0, 1), 1)
    actor = actor_values(bundle.actor, x, 1).argmax(-1)
    bins = []
    for lo, hi in ((-10., -.1), (-.1, -.025), (-.025, 0.), (0., 10.)):
        ids = (predicted_selected >= lo) & (predicted_selected < hi)
        bins.append({'predicted_moment_difference_interval': [lo, hi], 'n': int(ids.sum()),
                     'mean_predicted': float(predicted_selected[ids].mean()) if ids.any() else None,
                     'mean_realized': float(chosen[ids].mean()) if ids.any() else None})
    return {"paired_difference_MSE": float((predicted - difference).square().mean()),
            "paired_difference_zero_MSE": float(difference.square().mean()),
            "selected_action_prediction_bias": float((predicted_selected - chosen).mean()),
            "selected_action_prediction_MSE": float((predicted_selected - chosen).square().mean()),
            "selected_action_calibration_bins": bins,
            "hindsight_available_mean_moment_gain_vs_stop": float(-empirical_best.mean()),
            "selected_mean_moment_gain_vs_stop": float(-chosen.mean()),
            "hindsight_selected_moment_regret": float((chosen - empirical_best).mean()),
            "hindsight_action_match": float((choice == actual.argmin(-1)).float().mean()),
            "actor_teacher_action_agreement": float((actor == teacher).float().mean()),
            "scope": "single-realization potential outcomes; hindsight optimum, not conditional oracle or regret bound"}


def run(asset, output, seeds):
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    spec = json.loads((HERE / 'PROTOCOL.json').read_text())
    source = pins(); assets = asset_pins(asset); start = time.perf_counter_ns(); cpu = time.process_time_ns()
    write_json(output / 'registration.json', {"source_sha256": source, "seeds": seeds,
               "asset_sha256": assets, "started_unix_ns": time.time_ns(), "source_scope": spec['scope']})
    historical = json.loads((asset / 'hepta-ndu-recovery/experiments/multimodal_output_portfolio/abc_followup/control/DEVELOPMENT.json').read_text())
    entries = {r['seed']: r for r in historical['controllers']}
    records = []
    for seed in seeds:
        folder = asset / f'abc4-control-runs/development-001/seed-{seed}'
        record = entries[seed]
        for group in ('fit', 'selection'):
            if file_sha(folder / f'{group}/data.pt') != record[f'{group}_data_sha256']:
                raise ValueError('Historical data bytes differ')
        data = torch.load(folder / 'fit/data.pt', map_location='cpu', weights_only=True)
        if (data['role'], data['pair_start'], data['pair_count']) != ('forecast_fit', 480, 256):
            raise ValueError('Only registered historical fit role permitted')
        cheap = from_tree(data, folder / 'fit')
        old_path = asset / f'abc3-runs/controllers-001/seed-{seed}/output_ndu/controller.pt'
        if file_sha(old_path) != record['old_controller_sha256']:
            raise ValueError('Frozen teacher identity differs')
        old = load_controller(old_path)
        pair, pair_report = fit_pair(cheap, data['metrics']['primary']['utility'], torch.tensor(data['cases']), 2026102500 + seed)
        with torch.no_grad():
            labels = torch.cat((old.choose(data['features'][:, 0], 2)[:, None],
                               old.choose(data['features'][:, 1:].flatten(0, 1), 1).reshape(-1, 4)), 1).flatten()
        actor, actor_trace = fit_head(cheap.flatten(0, 1), labels, width=CONFIG['actor_hidden'], outputs=5,
                                     seed=2026103500 + seed, steps=CONFIG['steps'], actor=True)
        bundle = Bundle(pair, actor, .95)
        quote = cost_quote(asset, seed, bundle, data, folder / 'fit', old)
        del data, cheap
        data = torch.load(folder / 'selection/data.pt', map_location='cpu', weights_only=True)
        if (data['role'], data['pair_start'], data['pair_count']) != ('forecast_calibration', 448, 128):
            raise ValueError('Only registered historical selection role permitted')
        cheap = from_tree(data, folder / 'selection')
        teacher_result = evaluate(data, *select_paths(bundle, cheap, data['features'], old, 'teacher'),
                                 cheap_ms=quote['cheap_ms'], teacher_ms=quote['teacher_ms'], gate_enabled=False)
        candidates = [{"threshold": None, "eligible": True, **teacher_result}]
        for threshold in spec['selection']['thresholds']:
            bundle.threshold = threshold
            value = evaluate(data, *select_paths(bundle, cheap, data['features'], old, 'gate'),
                             cheap_ms=quote['cheap_ms'], teacher_ms=quote['teacher_ms'], gate_enabled=True)
            eligible = value['raw_CE'] >= teacher_result['raw_CE'] and value['success'] >= teacher_result['success']
            candidates.append({"threshold": threshold, "eligible": eligible, **value})
        selected = max((i for i, c in enumerate(candidates) if c['eligible']), key=lambda i: (candidates[i]['quoted_net_CE'], -i))
        bundle.threshold = candidates[selected]['threshold']
        directory = output / f'seed-{seed}'; directory.mkdir()
        save(bundle, directory / 'bundle.pt')
        report = {"seed": seed, "pair_fit": pair_report, "actor_trace": actor_trace, "cost_quote": quote,
                  "selection_candidates": candidates, "selected_index": selected, "threshold": bundle.threshold,
                  "diagnostics": diagnostics(bundle, cheap, data['features'], data, old),
                  "bundle_sha256": file_sha(directory / 'bundle.pt'), "teacher_sha256": file_sha(old_path),
                  "fit_sha256": record['fit_data_sha256'], "selection_sha256": record['selection_data_sha256'],
                  "fit_media_receipt_sha256": file_sha(folder / 'fit/summary.json'),
                  "selection_media_receipt_sha256": file_sha(folder / 'selection/summary.json')}
        write_json(directory / 'report.json', report); records.append(report)
        print(json.dumps({"seed": seed, "threshold": bundle.threshold, "diagnostics": report['diagnostics']}), flush=True)
    if source != pins():
        raise ValueError('Source changed during registered fit')
    write_json(output / 'result.json', {"schema": "hepta.closure.control-development.v1", "status": "completed",
               "records": records, "source_sha256": source, "asset_sha256": assets, "wall_ns": time.perf_counter_ns() - start,
               "cpu_ns": time.process_time_ns() - cpu, "completed_unix_ns": time.time_ns(),
               "new_rollout_outcomes_opened": False})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asset-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seeds', type=int, nargs='+', default=[17, 29, 43, 59, 71])
    args = parser.parse_args(); run(args.asset_root, args.output, args.seeds)
