"""Frozen-source confirmation; paired seeds, causal reads and complete cost logs."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from contract import PROTOCOL
from contract import ROOT, N_ACTIVE
from contract import true_model
from controller import plan, resolve_action
from content import corpus, TextEncoder, TextSensor
from costs import fit_costs, attach_cost
from data import EvidenceWorld
from data import sequences
from inference import Estimator
from inference import sequence_predictions
from training import digest_data


def validate_freeze(folder):
    payload = json.loads((folder / "FREEZE.json").read_text())
    for name, expected in payload["source_sha256"].items():
        path = ROOT.parent / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Source changed after freeze: {path}")
    for name, expected in payload["fit_sha256"].items():
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Fit changed after freeze: {name}")
    if "native_library_sha256" in payload:
        binary = ROOT / "native/evidence/build/libhcsn_prepared.so"
        if hashlib.sha256(binary.read_bytes()).hexdigest() != payload["native_library_sha256"]:
            raise ValueError("Native library changed after freeze")
    return payload


def episode_run(core, control, checkpoint, shared, world, times):
    start, wall_start = time.process_time(), time.perf_counter()
    world.reset()
    count = world.count
    state = Estimator(core, count, shared, times, checkpoint)
    initialize_cpu = time.process_time() - start
    active = np.ones(count, dtype=bool)
    budget = np.full(count, PROTOCOL["read_budget"])
    utility, correct = np.zeros(count), np.zeros(count)
    history = np.full((count, 3), -1, dtype=int)
    acquired = np.full((count, 3), -1, dtype=int)
    latent_at_answer = np.full(count, -1, dtype=int)
    timing = {"initialization": initialize_cpu, "controller": 0.0,
              "state_update": 0.0, "world_read_and_recovery": 0.0,
              "answer_scoring": 0.0}
    for step in range(3):
        rows = np.flatnonzero(active)
        if not len(rows):
            break
        actions = np.full(count, -1, dtype=int)
        tick = time.process_time()
        if control == "fixed_read":
            actions[rows] = 3 if step < 2 else resolve_action(state.p[rows] @ shared["answer_rewards"])
        else:
            for j, dt in enumerate(times):
                for remaining in range(3):
                    selected = rows[(world.dt_indices[step, rows] == j) &
                                    (budget[rows] == remaining)]
                    if not len(selected):
                        continue
                    actions[selected] = plan(
                        state.p[selected], state.transitions[j], shared["emission"],
                        shared["answer_rewards"], shared["read_cost"],
                        horizon=3-step, budget=remaining, dt=dt,
                    ).action
        timing["controller"] += time.process_time() - tick
        history[rows, step] = actions[rows]
        terminal = rows[actions[rows] < 2]
        tick = time.process_time()
        reward, accuracy = world.answer(terminal, actions[terminal])
        utility[terminal] += reward
        correct[terminal] = accuracy
        latent_at_answer[terminal] = world.hidden[terminal]
        active[terminal] = False
        timing["answer_scoring"] += time.process_time() - tick
        advance = rows[actions[rows] >= 2]
        if not len(advance):
            continue
        tick = time.process_time()
        world.advance(step, advance)
        dt_indices = world.dt_indices[step, advance]
        utility[advance] -= 0.01 * np.asarray(times)[dt_indices]
        read = advance[actions[advance] == 3]
        tokens = np.zeros(count, dtype=int)
        observed = np.zeros(count, dtype=bool)
        tokens[read] = world.read(step, read)
        observed[read] = True
        acquired[read, step] = tokens[read]
        utility[read] -= world.model["read_cost"][world.hidden[read]]
        budget[read] -= 1
        timing["world_read_and_recovery"] += time.process_time() - tick
        tick = time.process_time()
        for j, dt in enumerate(times):
            selected = advance[dt_indices == j]
            if len(selected):
                state.update(selected, j, dt, tokens[selected], observed[selected])
        timing["state_update"] += time.process_time() - tick
    cache_info = state.prepared.cache_info()
    state.close()
    cpu = time.process_time() - start
    if active.any() or np.any(budget < 0):
        raise AssertionError("Incomplete episode or budget violation")
    if world.read_calls != np.sum(history == 3) or np.any((acquired >= 0) != (history == 3)):
        raise AssertionError("Unrequested payload access")
    return {
        "core": core, "control": control, "utility": utility.tolist(),
        "accuracy": correct.tolist(), "mean_utility": float(utility.mean()),
        "mean_accuracy": float(correct.mean()), "actions": history.tolist(),
        "acquired_tokens": acquired.tolist(), "latent_at_answer_for_scoring_only": latent_at_answer.tolist(),
        "read_calls": world.read_calls, "advance_calls": world.advance_calls,
        "recovery_read_calls": world.recovery_read_calls,
        "raw_text_reads": world.sensor.raw_reads,
        "text_encoder_calls": world.sensor.encoder.encode_calls,
        "text_encoder_cpu_seconds": world.sensor.encoder.encode_cpu_seconds,
        "native_cache": cache_info,
        "inference_cpu_seconds": cpu, "inference_wall_seconds": time.perf_counter()-wall_start,
        "cpu_components": timing,
        "native_parity_scope": "Prepared native batch propagation is the actual analytic execution path; generic HMM uses identical cached transition matrices.",
    }


def sequence_score(predicted, data):
    content = predicted.reshape(*predicted.shape[:-1], 2, -1).sum(-1)
    accuracy = (resolve_action(content.reshape(-1, 2)).reshape(content.shape[:-1]) == data["labels"]).mean(axis=1)
    ce = -(data["posterior"] * np.log(np.maximum(predicted, 1e-12))).sum(-1).mean(axis=1)
    marginal = data["posterior"].reshape(*predicted.shape[:-1], 2, -1).sum(-1)
    brier = ((content - marginal) ** 2).sum(-1).mean(axis=1)
    return {"accuracy": accuracy.tolist(), "posterior_ce": ce.tolist(),
            "posterior_content_brier": brier.tolist(),
            "teacher_scope": "Nominal smoothed training emissions under true physical Q; heldout emission shift is not supplied to any actor",
            "label_brier_mean": float(((content[..., 1]-data["labels"])**2).mean()),
            "mean_accuracy": float(accuracy.mean()), "mean_posterior_ce": float(ce.mean()),
            "mean_posterior_content_brier": float(brier.mean())}


def confirm(folder, development=False):
    torch.set_num_threads(1)
    # Includes interpreter imports and every global setup operation in this worker.
    # Charging once to each counterfactual arm is conservative for a shared service.
    setup_start_cpu = 0.0
    frozen = None if development else validate_freeze(folder)
    seeds = [PROTOCOL['development_seed']] if development else PROTOCOL['seeds']
    output = folder/('DEVELOPMENT_EVALUATION.json' if development else 'CONFIRMATION.json')
    if output.exists():
        raise FileExistsError('Never overwrite outcomes')
    pools, metadata = corpus(ROOT/'data/sms_spam_collection.zip')
    frontend = json.loads((ROOT/'evidence/frontend.json').read_text())
    counts = np.asarray(frontend['development_counts']['core_train'], dtype=float)
    likelihood = (counts+.5)/(counts.sum(1, keepdims=True)+3)
    # This is the true physical model plus a nominal training observation model.
    # Actual heldout text frequencies are neither estimated nor exposed to actors.
    true = true_model(likelihood)
    global_setup_cpu = time.process_time() - setup_start_cpu
    partition = 'validation' if development else 'confirmation'
    all_results = []
    for seed in seeds:
        seed_setup_start = time.process_time()
        fits = {name: json.loads((folder/'fits'/f'{seed}_{name}.json').read_text())
                for name in PROTOCOL['cores']}
        chosen = min(PROTOCOL['cores'][1:], key=lambda n: fits[n]['selected_validation']['posterior_ce'])
        if frozen is not None and frozen['ordinary_choices'][str(seed)] != chosen:
            raise AssertionError('Post-confirmation selection')
        shared = {k: np.asarray(v) for k, v in fits['hx_distribution']['shared_model'].items()}
        costs = {name: json.loads((folder/'receipts'/f'{seed}_{name}.json').read_text())
                 ['whole_process_cpu_seconds'] for name in PROTOCOL['cores']}
        frontend_cost = json.loads((ROOT/'evidence/frontend_receipt.json').read_text())['whole_process_cpu_seconds']
        seed_setup_cpu = time.process_time() - seed_setup_start
        for domain, times in [('text_iid', PROTOCOL['iid_dt']), ('text_ood_time', PROTOCOL['ood_dt'])]:
            target = folder/'outcomes'/f'{seed}_{domain}.json'
            if target.exists():
                raise FileExistsError('Outcome exists: resume requires exact prior-row verification')
            data_seed = seed+(400000 if domain == 'text_iid' else 500000)
            sensor_start = time.process_time()
            sensor = TextSensor(pools[partition], TextEncoder.load(ROOT/'evidence/frontend.json'), N_ACTIVE)
            sensor_preparation = time.process_time() - sensor_start
            seq_count = 24 if development else PROTOCOL['confirmation_sequences_per_domain']
            ep_count = 32 if development else PROTOCOL['confirmation_episodes_per_domain']
            tick = time.process_time()
            data = sequences(data_seed, seq_count, true, times, sensor, PROTOCOL['sequence_length'])
            seq_preparation = time.process_time()-tick
            tick = time.process_time()
            world = EvidenceWorld(data_seed+1000000, ep_count, true, times, sensor)
            world_preparation = time.process_time()-tick
            row = {'seed': seed, 'domain': domain, 'ordinary_choice': chosen,
                   'partition': partition, 'sequence_data_sha256': digest_data(data),
                   'sequence_generation_cpu_seconds': seq_preparation,
                   'global_setup_cpu_seconds': global_setup_cpu,
                   'seed_setup_cpu_seconds': seed_setup_cpu,
                   'sensor_preparation_cpu_seconds': sensor_preparation,
                   'sequence': {}, 'arms': {}, 'fit_costs': costs,
                   'frontend_cost': frontend_cost, 'dataset': metadata}
            predictions = {}
            for core in [*PROTOCOL['cores'], 'generic_hmm']:
                checkpoint = folder/'fits'/f'{seed}_{core}.json'
                tick = time.process_time()
                prediction, cache = sequence_predictions(core, data, shared, times, checkpoint)
                predictions[core] = prediction
                row['sequence'][core] = {**sequence_score(prediction, data),
                    'cpu_seconds': time.process_time()-tick, 'native_cache': cache}
            row['generic_hmm_native_parity_max'] = float(np.max(np.abs(
                predictions['hx_distribution']-predictions['generic_hmm'])))
            definitions = {'A': (chosen, 'fixed_read'), 'B': (chosen, 'finite_horizon_value'),
                'C': ('hx_distribution', 'fixed_read'), 'D': ('hx_distribution', 'finite_horizon_value'),
                'GRU': ('gru', 'finite_horizon_value'),
                'SSM': ('continuous_diagonal_ssm', 'finite_horizon_value'),
                'HMM': ('generic_hmm', 'finite_horizon_value')}
            ordered = list(definitions)
            if seed % 4 == 1:
                ordered.reverse()
            for arm in ordered:
                core, control = definitions[arm]
                result = episode_run(core, control, folder/'fits'/f'{seed}_{core}.json', shared, world, times)
                attach_cost(result, core, chosen, costs, frontend_cost, world.count,
                            world_preparation + sensor_preparation,
                            global_setup_cpu + seed_setup_cpu)
                if result['raw_text_reads'] != result['text_encoder_calls']:
                    raise AssertionError('Read/encode accounting mismatch')
                row['arms'][arm] = result
            row['native_hmm_actions_identical'] = row['arms']['D']['actions'] == row['arms']['HMM']['actions']
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(row, separators=(',', ':'))+'\n')
            all_results.append(row)
            print(json.dumps({'seed': seed, 'domain': domain, 'choice': chosen,
                'D_minus_B': row['arms']['D']['mean_utility']-row['arms']['B']['mean_utility'],
                'native_hmm_actions_identical': row['native_hmm_actions_identical'],
                'native_hmm_parity': row['generic_hmm_native_parity_max']}), flush=True)
    payload = {'schema': 'hcsn-r13-confirmation-v1', 'development': development,
               'freeze_sha256': None if frozen is None else hashlib.sha256((folder/'FREEZE.json').read_bytes()).hexdigest(),
               'results': all_results}
    output.write_text(json.dumps(payload, separators=(',', ':'))+'\n')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', type=Path, default=ROOT/'evidence')
    parser.add_argument('--development', action='store_true')
    args = parser.parse_args()
    print(confirm(args.folder, args.development))
