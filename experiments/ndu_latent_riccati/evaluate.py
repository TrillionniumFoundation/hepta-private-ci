"""Measured inference, validation-only selection, and externally fixed scoring."""

import hashlib
import time

import numpy as np
import torch

from codec import semantic_metrics
from control import rollout
from data import subset


def cvar(values, alpha=0.90):
    values = np.asarray(values, dtype=np.float64)
    return float(np.sort(values)[-max(1, int(np.ceil((1 - alpha) * len(values)))):].mean())


def spec(variant, arm, steps, strength=2.0):
    return {'variant': variant, 'arm': arm, 'steps': steps, 'strength': strength,
            'name': f'{variant}__{arm}__n{steps}' + (f'__g{strength:g}' if arm == 'guidance' else '')}


def core_specs(config):
    steps = config['primary_steps']
    out = [spec(v, a, steps) for v in ('flow_trained', 'ndu_trained') for a in ('flow', 'ndu')]
    out += [spec(v, 'free_joint', steps) for v in ('free_equal_updates', 'free_trained')]
    out += [spec('ndu_trained', a, steps) for a in ('fixed_valuation_mpc', 'ndu_no_cross', 'ndu_rank3')]
    return out


def baseline_specs(config):
    out = [spec('flow_trained', 'direct', 0)]
    for steps in config['baseline_candidate_steps']:
        out += [spec(v, 'free_joint', steps) for v in ('free_equal_updates', 'free_trained')]
        out += [spec(v, 'guidance', steps, g) for v in ('flow_trained', 'ndu_trained')
                for g in config['guidance_strengths']]
    return out


@torch.no_grad()
def inference(decoder, model, public, noise, choice, config):
    """Input schema contains no truth, targets, output style, or corrupt flags."""
    started, cpu_started = time.perf_counter(), time.process_time()
    context, target = model['encoder'](public['inputs'], public['masks'])
    encoded = time.perf_counter()
    draws = config['draws_per_world']
    context, target = context.repeat_interleave(draws, 0), target.repeat_interleave(draws, 0)
    if choice['arm'] == 'direct':
        result = {'state': torch.cat((target, torch.where(noise[:, -1:] >= 0, 1., -1.)), -1),
                  'p': target.new_zeros((len(target), 6)), 'effort': target.new_zeros(len(target))}
    else:
        result = rollout(model['flow'], context, target, noise, steps=choice['steps'],
                         arm=choice['arm'], actor=model['actor'], strength=choice['strength'],
                         lookahead=config['riccati_lookahead_steps'])
    controlled = time.perf_counter()
    raw = decoder(result['state'])
    finished = time.perf_counter()
    timing = {'wall_seconds': finished - started, 'cpu_seconds': time.process_time() - cpu_started,
              'encoder_seconds': encoded - started, 'generation_control_seconds': controlled - encoded,
              'decoder_seconds': finished - controlled}
    return raw, result, timing


def summarize(arrays, draws):
    losses = arrays['factual_loss'].reshape(-1, draws)
    lawful = arrays['lawful_consistent'].reshape(-1, draws)
    style = arrays['style_positive'].reshape(-1, draws)
    # Invalid draws contribute neither positive nor negative lawful style mass.
    pos = (lawful * style).mean(1)
    neg = (lawful * (1 - style)).mean(1)
    mass = pos + neg
    fraction = np.divide(pos, mass, out=np.full_like(pos, 0.5), where=mass > 0)
    entropy = -(fraction * np.log2(np.maximum(fraction, 1e-12))
                + (1 - fraction) * np.log2(np.maximum(1 - fraction, 1e-12))) * mass
    report = {'world_cvar90': cvar(losses.mean(1)), 'draw_cvar90': cvar(losses.ravel()),
              'factual_loss': float(losses.mean()), 'conditional_lawful_style_entropy': float(entropy.mean()),
              'lawful_two_style_coverage': float(((pos > 0) & (neg > 0)).mean())}
    for key in ('correct', 'resolved', 'correct_resolved', 'disagreement', 'style_lawful',
                'style_consistent', 'lawful_consistent', 'effort', 'p_norm'):
        report[key] = float(arrays[key].mean())
    return report


def evaluate(decoder, models, worlds, choice, config, noise_seed, timing_repeats=1):
    draws, n = config['draws_per_world'], len(worlds['facts'])
    rng = torch.Generator().manual_seed(noise_seed)
    noise = torch.randn((n * draws, 7), generator=rng)
    model = models[choice['variant']]
    # A fixed small warmup is outside measured inference; its time is recorded.
    warm = subset(worlds, torch.arange(min(n, 8)))
    warm_public = {'inputs': warm['inputs'], 'masks': warm['masks']}
    warm_started = time.perf_counter()
    inference(decoder, model, warm_public, noise[:len(warm['facts']) * draws], choice, config)
    warm_seconds = time.perf_counter() - warm_started
    parts, timings, raw_samples = {}, [], {}
    for start in range(0, n, 128):
        current = subset(worlds, torch.arange(start, min(start + 128, n)))
        public = {'inputs': current['inputs'], 'masks': current['masks']}
        samples = noise[start * draws:(start + len(current['facts'])) * draws]
        repeats = []
        for _ in range(timing_repeats):
            raw, result, timing = inference(decoder, model, public, samples, choice, config)
            repeats.append(timing)
        timing = {key: float(np.median([r[key] for r in repeats])) for key in repeats[0]}
        timings.append(timing)
        if start == 0:
            sample_count = min(2, n) * draws
            raw_samples = {f'sample_raw_{key}': value[:sample_count].numpy().copy()
                           for key, value in raw.items()}
        metrics = semantic_metrics(raw, current['facts'].repeat_interleave(draws, 0))
        metrics.update({'latent': result['state'], 'p': result['p'], 'effort': result['effort'],
                        'p_norm': result['p'].square().sum(-1).sqrt()})
        for key, tensor in metrics.items():
            parts.setdefault(key, []).append(tensor.numpy())
    arrays = {key: np.concatenate(chunks) for key, chunks in parts.items()}
    arrays['world_index'] = np.repeat(np.arange(n), draws)
    arrays['draw_index'] = np.tile(np.arange(draws), n)
    arrays.update(raw_samples)
    report = summarize(arrays, draws)
    totals = {key: sum(t[key] for t in timings) for key in timings[0]}
    local = 'ndu' in choice['arm'] or 'mpc' in choice['arm']
    report.update({'timing': totals, 'seconds_per_world': totals['wall_seconds'] / n,
                   'cpu_seconds_per_world': totals['cpu_seconds'] / n,
                   'warmup_seconds': warm_seconds, 'timing_repeats': timing_repeats,
                   'worlds': n, 'draws_per_world': draws, 'choice': choice,
                   'noise_seed': noise_seed, 'noise_sha256': hashlib.sha256(noise.numpy().tobytes()).hexdigest(),
                   'facts_sha256': hashlib.sha256(worlds['facts'].numpy().tobytes()).hexdigest(),
                   'work': {'encoder_worlds': n, 'decoded_draws': n * draws,
                            'vector_field_draw_evaluations': n * draws * choice['steps'] * (2 if local else 1),
                            'local_linearizations': n * draws * choice['steps'] if local else 0,
                            'linear_solves': 2 * n * draws * sum(min(config['riccati_lookahead_steps'], choice['steps'] - i) for i in range(choice['steps'])) if local else 0,
                            'riccati_lookahead_max': config['riccati_lookahead_steps']}})
    return report, arrays


def choose_baseline(reports, reference, config):
    cap = reference['cpu_seconds_per_world'] * 1.10
    eligible = [r for r in reports if r['cpu_seconds_per_world'] <= cap]
    same_actuator = [r for r in eligible if r['choice']['arm'] == 'free_joint']
    if not same_actuator:
        return {'fairness_gate': False, 'reason': 'No free joint controller fits measured CPU inference budget',
                'cpu_seconds_cap': cap, 'choice': min(reports, key=lambda r: r['world_cvar90'])['choice']}
    best = min(eligible, key=lambda r: (r['world_cvar90'], r['cpu_seconds_per_world']))
    return {'fairness_gate': True, 'cpu_seconds_cap': cap, 'choice': best['choice'],
            'eligible_names': [r['choice']['name'] for r in eligible],
            'same_actuator_eligible_names': [r['choice']['name'] for r in same_actuator]}
