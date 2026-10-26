"""Actual fixed allocation and previously selected strong nonfeedback requests."""

import argparse
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
import torch

from ....abc_followup.control.features import ExactFeatureCache
from ....abc_next.compact_tree import scores
from ....abc_next.sensor_run import load_sensor
from ....abc_next.value import load_controller
from ....abc_recovery.base_recovery import file_sha, write_json
from ....abc_recovery.control import PLANS
from ....abc_recovery.emission import output_digests
from ....abc_recovery.runtime import initialize, public_digest, public_frame, transition
from ....abc_recovery.trees import stable_seed
from ....v6.data import Observation, Target
from ....v7.data import VIEWS, make_batch
from ....v7.evaluation import load_reward
from ...sources import load_registered
from ..registry import HERE, load_model
from ..rollout import PAYLOAD_SIZE, decode, emit_json


@torch.inference_mode()
def request(model, observation, old, sensor, *, policy, reference, seed, case, view, draw, evaluation, media, commitments):
    if type(observation) is not Observation or policy not in ('strong_nonfeedback', 'fixed_allocation'):
        raise ValueError('Only registered public baseline requests are permitted')
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    work, path, decisions = Counter(), [], []
    row = dict(seed=seed, case=case, view=view, draw=draw, policy=policy, status='failed')
    run = None
    try:
        initial = torch.Generator().manual_seed(stable_seed(evaluation['initial_namespace'], seed, case, view))
        run = initialize(model, observation, generator=initial)
        cache = ExactFeatureCache(model, sensor, observation, work)
        plan = ('refine_image', 'refine_text') if policy == 'fixed_allocation' or reference['selected_nonfeedback'] == 'fixed' else None
        if policy == 'strong_nonfeedback' and reference['selected_nonfeedback'] == 'static':
            plan = PLANS[reference['static_plan_index']]
        while not run.done:
            frame = public_frame(run)
            features = cache.read(frame)
            if plan is None:
                if reference['selected_nonfeedback'] != 'one_shot' or path:
                    raise ValueError('Frozen initial-only plan violated')
                plan = PLANS[int(old.choose_plan(features)[0])]
                work['route_head_calls'] += 1
            action = plan[len(path)] if len(path) < len(plan) else 'stop'
            detail = {'action': action, 'remaining': frame.remaining, 'public_sha256': public_digest(frame),
                      'initial_plan': list(plan), 'observed_full_features': True, 'decision_index': len(decisions)}
            emit_json(commitments, {**{k: v for k, v in row.items() if k != 'status'}, **detail})
            decisions.append(detail)
            future = torch.Generator().manual_seed(stable_seed(evaluation['future_namespace'], seed, case, view, draw, tuple((*path, action))))
            run = transition(model, run, action, generator=future)
            if action != 'stop':
                path.append(action)
            if len(decisions) > 2:
                raise ValueError('H2 request budget exceeded')
        if not ((run.pixels == 0) | (run.pixels == 1)).all() or (run.tokens < 0).any() or (run.tokens >= 24).any():
            raise ValueError('Actual media outside lossless encoding range')
        raw = np.packbits(run.pixels.to(torch.uint8).numpy().reshape(-1)).tobytes() + run.tokens.to(torch.uint8).numpy().tobytes()
        offset = media.seek(0, os.SEEK_END); media.write(raw); media.flush(); os.fsync(media.fileno())
        media.seek(offset); restored = media.read(PAYLOAD_SIZE)
        pixels, tokens, _ = decode(restored)
        if restored != raw or not torch.equal(pixels, run.pixels) or not torch.equal(tokens, run.tokens):
            raise ValueError('Actual media durable readback differs')
        row.update({'status': 'completed', 'offset': offset, 'payload_sha256': hashlib.sha256(raw).hexdigest(),
                    'output_sha256': output_digests(run.pixels, run.tokens)[0]})
    except Exception as error:
        row['error'] = {'type': type(error).__name__, 'message': str(error)}
    if run is not None:
        for entry in run.ledger:
            work.update(entry.get('work', {}))
    row.update({'wall_ns': time.perf_counter_ns() - wall, 'cpu_ns': time.process_time_ns() - cpu,
                'path': path, 'decisions': decisions, 'work': dict(work)})
    return row


def run(asset, protocol, output):
    spec = json.loads(protocol.read_text()); evaluation = spec['evaluation']
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    write_json(output / 'registration.json', {'protocol_sha256': file_sha(protocol), 'started_unix_ns': time.time_ns(),
                'scope': spec['status'], 'requests': spec['requests'], 'source_pairs': spec['pair_count']})
    manifest = asset / 'abc2-runs/source-recovery-001/source-manifest.json'
    corpus = load_registered(asset / 'abc2-assets/mnist', manifest, HERE.parent / 'SOURCE_ALLOCATION.json', 'control', protocol)
    public, targets, identities = {}, {}, {}
    for view in VIEWS:
        batch = make_batch(corpus, 'closure_control', 256, stable_seed(evaluation['observation_namespace'], 0, 256), view=view, offset=0)
        for case in range(256):
            public[view, case] = Observation(*(getattr(batch.observation, k)[case:case + 1].clone() for k in ('pixels', 'mask', 'text_tokens')))
            targets[view, case] = Target(*(getattr(batch.target, k)[case:case + 1].clone() for k in ('pixels', 'text_tokens', 'labels')))
            identities[case] = batch.source_ids[case]
    sensor = load_sensor(asset / 'abc3-runs/public-sensor-001/sensor.pt')
    judges = {name: load_reward(asset / path, expected_file_sha256=sha)[0] for name, path, sha in (
        ('primary', 'abc2-runs/base-recovery-001/reward-observer.pt', '8cfca1b0cd0a69bcfcc6a9d34d0a672c07c28f3342823ef8a3f6763e9430a003'),
        ('secondary', 'abc2-runs/qualification-001/secondary-observer.pt', 'b0851ce56189d159b53449cfc914cf84b9b63e82a6f0050228096666752595fe'))}
    setup_ns = time.perf_counter_ns() - wall
    rows, group, loads = [], 0, []
    with (output / 'actual-media.bin').open('x+b') as media, gzip.open(output / 'requests.jsonl.gz', 'xt', compresslevel=3) as log, gzip.open(output / 'commitments.jsonl.gz', 'xt', compresslevel=3) as commitments:
        for seed in spec['seeds']:
            started = time.perf_counter_ns()
            snapshot = load_model(asset, seed)
            old = load_controller(asset / f'abc3-runs/controllers-001/seed-{seed}/output_ndu/controller.pt')
            loads.append({'seed': seed, 'wall_ns': time.perf_counter_ns() - started})
            for view in VIEWS:
                for case in range(256):
                    for draw in range(2):
                        policies = spec['policies'] if group % 2 == 0 else list(reversed(spec['policies']))
                        for policy in policies:
                            row = request(snapshot._model, public[view, case], old, sensor, policy=policy,
                                reference=spec['reference'][str(seed)], seed=seed, case=case, view=view, draw=draw,
                                evaluation=evaluation, media=media, commitments=commitments)
                            row.update({'source_ids': identities[case], 'group': group})
                            rows.append(row); emit_json(log, row)
                        group += 1
                print(json.dumps({'seed': seed, 'view': view, 'rows': len(rows), 'failed': sum(r['status'] != 'completed' for r in rows)}), flush=True)
            snapshot.verify_integrity()
    scoring = time.perf_counter_ns()
    with (output / 'actual-media.bin').open('rb') as media, gzip.open(output / 'scored.jsonl.gz', 'xt', compresslevel=3) as log:
        for row in rows:
            row['scores'] = {}
            if row['status'] == 'completed':
                media.seek(row['offset']); raw = media.read(PAYLOAD_SIZE)
                if hashlib.sha256(raw).hexdigest() != row['payload_sha256']:
                    raise ValueError('Closed actual media changed')
                pixels, _, captions = decode(raw)
                values = scores(judges, pixels, captions, targets[row['view'], row['case']])
                row['scores'] = {name: {k: float(value[0]) for k, value in metrics.items()} for name, metrics in values.items()}
            log.write(json.dumps({k: row[k] for k in ('seed', 'case', 'view', 'draw', 'policy', 'status', 'scores')}, sort_keys=True, allow_nan=False) + '\n')
        log.flush(); os.fsync(log.fileno())
    if len(rows) != spec['requests'] or any(file_sha(Path(p)) != expected for p, expected in spec['frozen_candidate_sha256'].items()):
        raise ValueError('Frozen census or implementation changed')
    write_json(output / 'completion.json', {'status': 'completed', 'rows': len(rows), 'failed': sum(r['status'] != 'completed' for r in rows),
        'scope': spec['status'], 'source_pairs': 256, 'additional_independent_sources': 0, 'setup_ns': setup_ns,
        'model_loads': loads, 'scoring_ns': time.perf_counter_ns() - scoring,
        'wall_ns': time.perf_counter_ns() - wall, 'cpu_ns': time.process_time_ns() - cpu,
        'files_sha256': {name: file_sha(output / name) for name in ('actual-media.bin', 'requests.jsonl.gz', 'scored.jsonl.gz', 'commitments.jsonl.gz')},
        'output_bytes': sum(p.stat().st_size for p in output.iterdir() if p.is_file()), 'completed_unix_ns': time.time_ns()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asset-root', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); run(args.asset_root, args.protocol, args.output)
