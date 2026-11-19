"""Registered dependence ambiguity and a separately paid independent witness.

The witness is new information, not a way to recover an unobserved label from
four jointly wrong reports. Its allowed fallback rule emits the witness class;
the finite robust policy compares this rule to each direct output portfolio.
No claim of a globally optimal arbitrary post-query strategy is made.
"""

import hashlib
import time

import numpy as np
import torch

from control import CalibrationModel, portfolio_grid
from controlled_model import ControlledOutputModel, external_loss_tensor
from metrics import score_outputs, summarize
from model import MODALITIES, encode, mac_counts
from world import render, sample_worlds


def observed_reports(model, raw):
    rows = len(raw['text'])
    reports = np.empty((rows, 4), dtype=np.int64)
    work = 0
    for j, name in enumerate(MODALITIES):
        if len(raw[name]) != rows:
            raise ValueError('unaligned input modalities')
        present = np.any(np.asarray(raw[name]) != 0, axis=1)
        reports[:, j] = 8
        if present.any():
            reports[present, j] = encode(model, name, raw[name][present])[0]
            work += int(present.sum()) * mac_counts(model)['encoder'][name]
    return reports, work


def report_indices(reports):
    reports = np.asarray(reports)
    if reports.ndim != 2 or reports.shape[1] != 4 or reports.dtype.kind not in 'iu' or np.any((reports < 0) | (reports > 8)):
        raise ValueError('four public encoded reports in 0..8 required')
    return np.ravel_multi_index(reports.T, (9, 9, 9, 9))


def compile_source_policy(model, targets, seed, settings, namespace):
    wall, cpu = time.perf_counter(), time.process_time()
    joint, costs, calibration = [], 0, []
    for index, scenario in enumerate(settings['scenarios']):
        data = sample_worlds(settings['calibration_worlds_per_regime'],
                1200000 + 100 * seed + index, namespace + '-source-calibration-' + scenario, scenario)
        reports, work = observed_reports(model, data['raw'])
        table = CalibrationModel(data['truth'], reports, smoothing=32.).joint
        joint.append(table)
        costs += work
        calibration.append({'scenario': scenario, 'examples': len(data['truth']),
                            'truth_sha256': hashlib.sha256(data['truth'].tobytes()).hexdigest(),
                            'reports_sha256': hashlib.sha256(reports.tobytes()).hexdigest(),
                            'ideal_linear_macs': work})
    joint = np.stack(joint)
    # All 9^4 observable histories are compiled before new evaluation worlds.
    masses = joint.reshape(len(joint), 8, -1).transpose(0, 2, 1)
    posterior = masses / masses.sum(-1, keepdims=True)
    grid = portfolio_grid()
    with torch.inference_mode():
        wrapper = ControlledOutputModel(model, copy_model=False)
        # Explicit max_depth=0 performs one initial map and one four-decoder exit.
        losses = external_loss_tensor(wrapper, grid, targets, max_depth=0)[0].numpy()
    gamma = 2.
    exponential_loss = np.exp(gamma * losses)
    values = -np.log(posterior @ exponential_loss.T) / gamma
    nominal = values[0].argmax(-1)
    robust_values = values.min(0)
    robust = robust_values.argmax(-1)
    rows = np.arange(len(robust))
    stop = robust_values[rows, robust]
    vertices = np.array([np.flatnonzero(np.all(grid == np.eye(8)[j], axis=1))[0]
                         for j in range(8)])
    error = settings['independent_verifier_error']
    channel = np.full((8, 8), error / 7.)
    np.fill_diagonal(channel, 1 - error)  # [true class, observed witness class]
    # Text nuisance has exactly two possibilities (last token now/today).
    # Exhaustively compose the declared witness channel with the actual frozen
    # encoder. Its mistakes are never silently treated as perfect decoding.
    witness_classes = np.repeat(np.arange(8), 2)
    witness_support = render(witness_classes, seed=0, nuisance=False)['text'].reshape(16, 4, 10)
    witness_support[:, 3] = 0
    witness_support[np.arange(16), 3, np.tile([7, 8], 8)] = 1
    encoded = encode(model, 'text', witness_support.reshape(16, 40))[0]
    encoder_channel = np.zeros((8, 8))
    np.add.at(encoder_channel, (witness_classes, encoded), .5)
    channel = channel @ encoder_channel
    costs += 16 * mac_counts(model)['encoder']['text']
    # Fixed allowed fallback: emit witness vertex. Never select using evaluator truth.
    terminal = losses[vertices].T  # [truth, witness]
    witness_exponential = (channel * np.exp(gamma * terminal)).sum(-1)
    query_values = (-np.log(posterior @ witness_exponential) / gamma).min(0)
    query_values -= settings['verifier_proxy_cost'] * settings['verifier_utility_penalty']
    query = query_values > stop + 1e-12
    profile = mac_counts(model)
    offline_macs = costs + len(grid) * (8 * 64 + sum(profile['decoder'].values()))
    return {'grid': grid, 'joint': joint, 'losses': losses, 'nominal': nominal,
            'robust': robust, 'query': query, 'stop_values': stop,
            'query_values': query_values, 'vertices': vertices,
            'receipt': {'calibration': calibration, 'compiled_histories': len(query),
                        'query_fraction_of_all_support': float(query.mean()),
                        'witness_encoder_exhaustive_support': 16,
                        'witness_encoder_channel': encoder_channel.tolist(),
                        'effective_witness_channel': channel.tolist(),
                        'offline_forward_linear_macs': offline_macs,
                        'wall_seconds': time.perf_counter() - wall,
                        'process_cpu_seconds': time.process_time() - cpu,
                        'scope': 'finite direct portfolios or fixed witness fallback; known regime set',
                        'new_information_required_for_witness': True}}


class PaidWitness:
    """Only exposes a selected raw observation; labels/scenario are absent."""
    def __init__(self, raw):
        self._raw = np.array(raw, copy=True)
        self.queried = np.zeros(len(raw), dtype=bool)

    def query(self, selected):
        selected = np.asarray(selected)
        if selected.dtype != np.bool_ or selected.shape != self.queried.shape or np.any(self.queried & selected):
            raise ValueError('one nonrepeated paid query per selected world')
        self.queried |= selected
        return self._raw[selected].copy()


def source_inputs(count, seed, namespace, scenario, error):
    """Evaluator-only world constructor; model-facing interface is raw+witness."""
    world = sample_worlds(count, seed, namespace + '-' + scenario, scenario)
    rng = np.random.default_rng(seed ^ 0x639812)
    wrong = (world['truth'] + rng.integers(1, 8, count)) % 8
    witness_report = np.where(rng.random(count) < error, wrong, world['truth'])
    witness_raw = render(witness_report, seed ^ 0x51777, nuisance=True)['text']
    return world, witness_raw


def source_rollout(model, raw, witness, policy, arm):
    """Inference never accepts truth, world IDs, scenario or calibration labels."""
    count = len(raw['text'])
    if arm not in ('nominal', 'robust', 'robust_verified', 'verifier_only'):
        raise ValueError('unknown source-control arm')
    if arm == 'verifier_only':
        indices = np.zeros(count, dtype=np.int64)
        chosen = np.ones(count, dtype=bool)
        portfolios = np.zeros(count, dtype=np.int64)
        work = 0
    else:
        reports, work = observed_reports(model, raw)
        indices = report_indices(reports)
        portfolios = policy['nominal' if arm == 'nominal' else 'robust'][indices].copy()
        chosen = policy['query'][indices] if arm == 'robust_verified' else np.zeros(count, dtype=bool)
    if chosen.any():
        result, _ = encode(model, 'text', witness.query(chosen))
        portfolios[chosen] = policy['vertices'][result]
        work += int(chosen.sum()) * mac_counts(model)['encoder']['text']
    q = torch.tensor(policy['grid'][portfolios], dtype=torch.float32)
    with torch.inference_mode():
        latent = model.initial_latent(q)
        output = {name: model.decoders[name](latent).numpy() for name in MODALITIES}
    work += count * (8 * 64 + sum(mac_counts(model)['decoder'].values()))
    receipt = {'examples': count, 'queried': int(chosen.sum()),
               'query_fraction': float(chosen.mean()), 'forward_linear_macs': work,
               'all_four_outputs': set(output) == set(MODALITIES),
               'output_sha256': {name: hashlib.sha256(value.tobytes()).hexdigest() for name, value in output.items()},
               'no_evaluator_metadata_argument': True,
               'new_information': arm in ('robust_verified', 'verifier_only')}
    return output, portfolios, chosen, receipt


def run_sources(model, targets, seed, settings, namespace, save):
    policy = compile_source_policy(model, targets, seed, settings, namespace)
    save('source-compilation.json', policy['receipt'])
    summaries, records = [], []
    for index, scenario in enumerate(settings['scenarios']):
        world, raw_witness = source_inputs(settings['heldout_worlds_per_scenario'],
            1300000 + 100 * seed + index, namespace + '-source-heldout', scenario,
            settings['independent_verifier_error'])
        for arm in settings['arms']:
            outputs, portfolios, queries, receipt = source_rollout(
                model, world['raw'], PaidWitness(raw_witness), policy, arm)
            scores = score_outputs(outputs, world['truth'], targets)
            summaries.append({'seed': seed, 'scenario': scenario, 'arm': arm,
                              **summarize(scores), **receipt})
            for row in range(len(world['truth'])):
                records.append({'seed': seed, 'scenario': scenario, 'arm': arm,
                    'world_id': str(world['ids'][row]), 'truth': int(world['truth'][row]),
                    'portfolio_index': int(portfolios[row]), 'queried': bool(queries[row]),
                    **{name: float(value[row]) for name, value in scores.items()}})
    return summaries, records
