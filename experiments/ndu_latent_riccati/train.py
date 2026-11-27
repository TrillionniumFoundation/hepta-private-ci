"""Shared codec/foundation training and matched-initialization continuations."""

import copy
import math
import time

import torch
import torch.nn.functional as F

from codec import Decoder, Encoder, loss_decoder
from control import Flow, FreeController, rollout
from data import render, subset


def _update(loss, optimizer, parameters):
    if not torch.isfinite(loss):
        raise FloatingPointError('Nonfinite training loss')
    optimizer.zero_grad(set_to_none=True)
    loss.backward()
    norm = torch.nn.utils.clip_grad_norm_(parameters, 10.0)
    if not torch.isfinite(norm):
        raise FloatingPointError('Nonfinite training gradient')
    optimizer.step()


def flow_loss(flow, context, facts, style, generator, initial_facts):
    target = torch.cat((facts, style), -1)
    epsilon = torch.randn(target.shape, generator=generator)
    noise = torch.cat((initial_facts + 0.5 * epsilon[:, :6], epsilon[:, 6:]), -1)
    t = torch.rand((len(target), 1), generator=generator)
    state = (1 - t) * noise + t * target
    return F.mse_loss(flow(state, t, context), target - noise)


def train_seed(worlds, seed, config, output):
    """Return three model continuations; all supervision is confined to training."""
    torch.manual_seed(seed)
    n, batch = len(worlds['facts']), config['batch_size']
    rng = torch.Generator().manual_seed(seed + 31)
    decoder = Decoder()
    params = list(decoder.parameters())
    optimizer = torch.optim.AdamW(params, lr=config['learning_rate'])
    log = []
    started = time.perf_counter()
    for step in range(config['decoder_updates']):
        fraction = step / max(1, config['decoder_updates'] - 1)
        codec_lr = config['decoder_min_learning_rate'] + 0.5 * (config['learning_rate'] - config['decoder_min_learning_rate']) * (1 + math.cos(math.pi * fraction))
        for group in optimizer.param_groups:
            group['lr'] = codec_lr
        indices = torch.randint(n, (batch,), generator=rng)
        current = subset(worlds, indices)
        state = torch.cat((current['facts'], current['style']), -1)
        loss = loss_decoder(decoder(state), current['targets'])
        _update(loss, optimizer, params)
        if step % 100 == 0 or step == config['decoder_updates'] - 1:
            log.append({'stage': 'codec', 'step': step, 'loss': float(loss.detach())})
    codec_seconds = time.perf_counter() - started
    decoder.eval().requires_grad_(False)
    encoder, flow = Encoder(), Flow()
    params = list(encoder.parameters()) + list(flow.parameters())
    optimizer = torch.optim.AdamW(params, lr=config['learning_rate'])
    started = time.perf_counter()
    for step in range(config['foundation_updates']):
        indices = torch.randint(n, (batch,), generator=rng)
        current = subset(worlds, indices)
        context, predicted = encoder(current['inputs'], current['masks'])
        fm = flow_loss(flow, context, current['facts'], current['style'], rng, predicted)
        loss = fm + 4 * F.mse_loss(predicted, current['facts'])
        _update(loss, optimizer, params)
        if step % 100 == 0 or step == config['foundation_updates'] - 1:
            log.append({'stage': 'foundation', 'step': step, 'loss': float(loss.detach())})
    foundation_seconds = time.perf_counter() - started
    foundation = {'encoder': copy.deepcopy(encoder), 'flow': copy.deepcopy(flow)}
    models = {}
    durations = {}
    updates = {}
    # NDU is trained first solely to set the measured compute budget for the
    # free-controller comparator. No validation/heldout metrics set this budget.
    for variant in ('ndu_trained', 'flow_trained', 'free_trained'):
        enc, field = copy.deepcopy(encoder), copy.deepcopy(flow)
        enc.eval().requires_grad_(False)
        actor = FreeController() if variant == 'free_trained' else None
        params = list(field.parameters())
        if actor is not None:
            params += list(actor.parameters())
        optimizer = torch.optim.AdamW(params, lr=config['learning_rate'])
        # Each continuation starts the same minibatch/noise stream.
        batch_stream = torch.Generator().manual_seed(seed + 1009)
        fm_stream = torch.Generator().manual_seed(seed + 1013)
        rollout_stream = torch.Generator().manual_seed(seed + 1019)
        started = time.perf_counter()
        step = 0
        minimum = config['continued_updates']
        maximum = config['free_controller_compute_match']['maximum_updates'] if actor is not None else minimum
        while step < maximum:
            if step >= minimum and time.perf_counter() - started >= durations['ndu_trained']:
                break
            indices = torch.randint(n, (batch,), generator=batch_stream)
            current = subset(worlds, indices)
            context, predicted = enc(current['inputs'], current['masks'])
            fm = flow_loss(field, context, current['facts'], current['style'], fm_stream, predicted)
            loss = fm + 4 * F.mse_loss(predicted, current['facts'])
            if variant != 'flow_trained':
                noise = torch.randn((batch, 7), generator=rollout_stream)
                arm = 'ndu' if variant == 'ndu_trained' else 'free_joint'
                generated = rollout(field, context, predicted, noise,
                                    steps=config['training_rollout_steps'], arm=arm,
                                    actor=actor, lookahead=config['riccati_lookahead_steps'])
                # Both legal styles are supervised using a function of sampled
                # initial noise, never a style target disclosed at inference.
                style = torch.where(noise[:, -1:] >= 0, 1., -1.)
                factual = F.mse_loss(generated['state'][:, :6], current['facts'])
                style_loss = F.mse_loss(generated['state'][:, 6:], style)
                raw = loss_decoder(decoder(generated['state']), render(current['facts'], style))
                loss = loss + 3 * factual + 0.15 * style_loss + 0.20 * raw + 0.05 * generated['effort'].mean()
            _update(loss, optimizer, params)
            if step % 100 == 0 or step == minimum - 1:
                log.append({'stage': variant, 'step': step, 'loss': float(loss.detach())})
            step += 1
            if actor is not None and step == minimum:
                models['free_equal_updates'] = {'encoder': copy.deepcopy(enc).eval(),
                                                'flow': copy.deepcopy(field).eval(),
                                                'actor': copy.deepcopy(actor).eval()}
                durations['free_equal_updates'] = time.perf_counter() - started
                updates['free_equal_updates'] = step
        durations[variant] = time.perf_counter() - started
        updates[variant] = step
        models[variant] = {'encoder': enc.eval(), 'flow': field.eval(), 'actor': actor.eval() if actor else None}
        print(f'seed={seed} stage={variant} updates={step} seconds={durations[variant]:.2f}', flush=True)
    checkpoint = {'seed': seed, 'decoder': decoder.state_dict(),
                  'foundation': {key: model.state_dict() for key, model in foundation.items()},
                  'models': {name: {key: model.state_dict() if model is not None else None
                                    for key, model in value.items()} for name, value in models.items()}}
    torch.save(checkpoint, output / 'checkpoint.pt')
    receipt = {'codec_seconds': codec_seconds, 'foundation_seconds': foundation_seconds,
               'continuation_seconds': durations, 'continuation_updates': updates,
               'free_to_ndu_training_time_ratio': durations['free_trained'] / durations['ndu_trained'],
               'parameters': {'decoder': sum(p.numel() for p in decoder.parameters()),
                              'encoder': sum(p.numel() for p in encoder.parameters()),
                              'flow': sum(p.numel() for p in flow.parameters()),
                              'free_actor': sum(p.numel() for p in models['free_trained']['actor'].parameters())},
               'log': log}
    return decoder, models, receipt


def load_checkpoint(path):
    saved = torch.load(path, map_location='cpu', weights_only=True)
    decoder = Decoder()
    decoder.load_state_dict(saved['decoder'])
    models = {}
    for name, state in saved['models'].items():
        model = {'encoder': Encoder(), 'flow': Flow(),
                 'actor': FreeController() if state['actor'] is not None else None}
        for key, part in model.items():
            if part is not None:
                part.load_state_dict(state[key])
                part.eval()
        models[name] = model
    return decoder.eval(), models
