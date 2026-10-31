"""Frozen conditional evaluation with new futures and actual durable media."""

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

from ...abc_followup.control.features import ExactFeatureCache
from ...abc_next.compact_tree import scores
from ...abc_next.sensor_run import load_sensor
from ...abc_next.value import load_controller
from ...abc_recovery.base_recovery import file_sha, write_json
from ...abc_recovery.emission import output_digests
from ...abc_recovery.runtime import ACTIONS, initialize, public_digest, public_frame, transition
from ...abc_recovery.trees import stable_seed
from ...v6.data import Observation, Target, render_tokens
from ...v7.data import VIEWS, make_batch
from ...v7.evaluation import load_reward
from ...v7.sources import load_roles
from ..sources import load_registered
from .registry import HERE, pins, asset_pins, load_model
from .features import from_frame
from .models import load


POLICIES = ('cached_teacher', 'paired_critic', 'distilled_actor', 'selected_gate')
PAYLOAD_SIZE = 204


def emit_json(stream, record):
    stream.write(json.dumps(record, sort_keys=True, allow_nan=False) + '\n')
    stream.flush(); os.fsync(stream.fileno())


def decode(raw):
    if len(raw) != PAYLOAD_SIZE:
        raise ValueError('Incomplete actual terminal record')
    pixels = torch.from_numpy(np.unpackbits(np.frombuffer(raw[:196], dtype=np.uint8), count=1568).copy()).reshape(1, 1, 28, 56).float()
    tokens = torch.from_numpy(np.frombuffer(raw[196:], dtype=np.uint8).astype(np.int64)).reshape(1, 8)
    return pixels, tokens, [render_tokens(tokens[0].tolist())]


@torch.inference_mode()
def request(model, observation, *, old, bundle, sensor, policy, seed, case, view, draw, media, commitments, evaluation):
    """Actor/critic ports receive only current public features, never Target."""
    if policy not in POLICIES or type(observation) is not Observation:
        raise ValueError('Unregistered public request')
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    work, path, decisions = Counter(), [], []
    record = dict(seed=seed, case=case, view=view, draw=draw, policy=policy, status='failed')
    run = cache = None
    calibration_media = []
    try:
        initial = torch.Generator().manual_seed(stable_seed(evaluation['initial_namespace'], seed, case, view))
        run = initialize(model, observation, generator=initial)
        while not run.done:
            frame = public_frame(run)
            use_teacher = policy == 'cached_teacher' or (policy == 'selected_gate' and bundle.threshold is None)
            detail = {'remaining': frame.remaining, 'cheap': False}
            if not use_teacher:
                feature = from_frame(frame)
                actor, pair, accept, confidence, paired = bundle.propose(feature, frame.remaining)
                detail.update({'actor': int(actor[0]), 'pair': int(pair[0]), 'confidence': float(confidence[0])})
                work['cheap_feature_calls'] += 1; work['paired_head_calls'] += 1; work['actor_head_calls'] += 1
                if policy == 'paired_critic':
                    chosen = int(pair[0]); detail['cheap'] = True
                elif policy == 'distilled_actor' or bool(accept[0]):
                    chosen = int(actor[0]); detail['cheap'] = True
                else:
                    use_teacher = True
            if use_teacher:
                if cache is None:
                    cache = ExactFeatureCache(model, sensor, observation, work)
                chosen = int(old.choose(cache.read(frame), frame.remaining)[0])
                work['teacher_calls'] += 1
            if frame.remaining == 1 and not (policy == 'cached_teacher' or (policy == 'selected_gate' and bundle.threshold is None)):
                detail['paired_prediction'] = float(paired[0, chosen])
                calibration_media.append(np.packbits(frame.pixels.to(torch.uint8).numpy().reshape(-1)).tobytes() + frame.tokens.to(torch.uint8).numpy().tobytes())
            action = ACTIONS[chosen]
            detail.update({'action': action, 'public_sha256': public_digest(frame)})
            # A durable commitment precedes creation/use of this future RNG.
            emit_json(commitments, {**{k: v for k, v in record.items() if k != 'status'}, 'decision_index': len(decisions), **detail})
            decisions.append(detail)
            future = torch.Generator().manual_seed(stable_seed(evaluation['future_namespace'], seed, case, view, draw, tuple((*path, action))))
            run = transition(model, run, action, generator=future)
            if action != 'stop':
                path.append(action)
            if len(decisions) > 2:
                raise ValueError('H2 budget exceeded')
        if not ((run.pixels == 0) | (run.pixels == 1)).all() or (run.tokens < 0).any() or (run.tokens >= 24).any():
            raise ValueError('Expected actual Bernoulli pixels')
        raw = np.packbits(run.pixels.to(torch.uint8).numpy().reshape(-1)).tobytes() + run.tokens.to(torch.uint8).numpy().tobytes()
        if len(raw) != PAYLOAD_SIZE:
            raise ValueError('Actual media dimensions differ')
        offset = media.seek(0, os.SEEK_END); media.write(raw); media.flush(); os.fsync(media.fileno())
        media.seek(offset); restored = media.read(PAYLOAD_SIZE)
        if restored != raw:
            raise ValueError('Durable output readback mismatch')
        decoded_pixels, decoded_tokens, _ = decode(restored)
        if not torch.equal(run.pixels, decoded_pixels) or not torch.equal(run.tokens, decoded_tokens):
            raise ValueError('Lossless actual output roundtrip mismatch')
        record.update({'status': 'completed', 'offset': offset, 'payload_sha256': hashlib.sha256(raw).hexdigest(),
                       'output_sha256': output_digests(run.pixels, run.tokens)[0]})
    except Exception as error:
        record['error'] = {'type': type(error).__name__, 'message': str(error)}
    if run is not None:
        for entry in run.ledger:
            work.update(entry.get('work', {}))
    record.update({'wall_ns': time.perf_counter_ns() - start, 'cpu_ns': time.process_time_ns() - cpu,
                   'path': path, 'decisions': decisions, 'work': dict(work)})
    return record, calibration_media


def run(asset, development, output, fresh_protocol=None):
    spec = json.loads((HERE / 'PROTOCOL.json').read_text())
    fitted = json.loads((development / 'result.json').read_text())
    if fitted['source_sha256'] != pins() or fitted['status'] != 'completed':
        raise ValueError('Source changed after fitted candidate freeze')
    if [r['seed'] for r in fitted['records']] != spec['seeds']:
        raise ValueError('Incomplete frozen five-seed census')
    evaluation = spec['evaluation'] if fresh_protocol is None else spec['prospective_evaluation']
    scope = spec['scope'] if fresh_protocol is None else 'Prospective allocated source pairs; conditional on five trained generators and original MNIST corpus'
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    manifest = asset / 'abc2-runs/source-recovery-001/source-manifest.json'
    if file_sha(manifest) != '60c24d44e12eb3defb3b1b8146d91879b84918b057e0524117137d7e4f793058':
        raise ValueError('Original source manifest changed')
    fixed_assets = asset_pins(asset)
    write_json(output / 'registration.json', {'schema': 'hepta.closure.control-new-future.v1',
        'source_sha256': pins(), 'development_sha256': file_sha(development / 'result.json'),
        'asset_sha256': fixed_assets, 'fresh_protocol_sha256': file_sha(fresh_protocol) if fresh_protocol else None,
        'started_unix_ns': time.time_ns(), 'scope': scope, 'evaluation': evaluation})
    if fresh_protocol is None:
        corpus = load_roles(asset / 'abc2-assets/mnist', manifest, roles=('forecast_calibration',))
    else:
        declared = json.loads(fresh_protocol.read_text())
        if declared['evaluation'] != evaluation or declared['seeds'] != spec['seeds']:
            raise ValueError('Fresh evaluation differs from frozen protocol')
        corpus = load_registered(asset / 'abc2-assets/mnist', manifest, HERE.parent / 'SOURCE_ALLOCATION.json', 'control', fresh_protocol)
    pair_start, pair_count = evaluation['pair_start'], evaluation['pair_count']
    public, targets, identities = {}, {}, {}
    for view in VIEWS:
        batch = make_batch(corpus, evaluation['source_role'], pair_count,
            stable_seed(evaluation['observation_namespace'], pair_start, pair_count), view=view, offset=pair_start)
        for i in range(pair_count):
            public[view, pair_start + i] = Observation(*(getattr(batch.observation, k)[i:i + 1].clone() for k in ('pixels', 'mask', 'text_tokens')))
            targets[view, pair_start + i] = Target(*(getattr(batch.target, k)[i:i + 1].clone() for k in ('pixels', 'text_tokens', 'labels')))
            identities[pair_start + i] = batch.source_ids[i]
    sensor = load_sensor(asset / 'abc3-runs/public-sensor-001/sensor.pt')
    judges = {name: load_reward(asset / path, expected_file_sha256=sha)[0] for name, path, sha in (
        ('primary', 'abc2-runs/base-recovery-001/reward-observer.pt', '8cfca1b0cd0a69bcfcc6a9d34d0a672c07c28f3342823ef8a3f6763e9430a003'),
        ('secondary', 'abc2-runs/qualification-001/secondary-observer.pt', 'b0851ce56189d159b53449cfc914cf84b9b63e82a6f0050228096666752595fe'))}
    setup_ns = time.perf_counter_ns() - wall
    rows, loads, group = [], [], 0
    calibration_offset = 0
    with (output / 'actual-media.bin').open('x+b') as media, gzip.open(output / 'commitments.jsonl.gz', 'xt', compresslevel=3) as commitments, gzip.open(output / 'requests.jsonl.gz', 'xt', compresslevel=3) as log, gzip.open(output / 'calibration-media.bin.gz', 'xb', compresslevel=3) as calibration:
        for frozen in fitted['records']:
            seed = frozen['seed']; started = time.perf_counter_ns()
            bundle_path = development / f'seed-{seed}/bundle.pt'
            teacher_path = asset / f'abc3-runs/controllers-001/seed-{seed}/output_ndu/controller.pt'
            if file_sha(bundle_path) != frozen['bundle_sha256'] or file_sha(teacher_path) != frozen['teacher_sha256']:
                raise ValueError('Frozen actor/teacher bytes changed')
            snapshot = load_model(asset, seed)
            bundle, old = load(bundle_path), load_controller(teacher_path)
            loads.append({'seed': seed, 'wall_ns': time.perf_counter_ns() - started, 'model_sha256': snapshot.fingerprint})
            for view in VIEWS:
                for case in range(pair_start, pair_start + pair_count):
                    for draw in range(2):
                        start = group % 4; order = POLICIES[start:] + POLICIES[:start]
                        for policy in order:
                            row, calibration_records = request(snapshot._model, public[view, case], old=old, bundle=bundle, sensor=sensor,
                                          policy=policy, seed=seed, case=case, view=view, draw=draw, media=media, commitments=commitments, evaluation=evaluation)
                            row['calibration_records'] = []
                            for raw in calibration_records:
                                calibration.write(raw)
                                row['calibration_records'].append({'offset': calibration_offset, 'sha256': hashlib.sha256(raw).hexdigest()})
                                calibration_offset += PAYLOAD_SIZE
                            row['source_ids'] = identities[case]
                            row['group'] = group
                            rows.append(row); emit_json(log, row)
                        group += 1
                print(json.dumps({'seed': seed, 'view': view, 'rows': len(rows), 'failed': sum(r['status'] != 'completed' for r in rows)}), flush=True)
            snapshot.verify_integrity()
    scoring_start = time.perf_counter_ns()
    with (output / 'actual-media.bin').open('rb') as media, gzip.open(output / 'scored.jsonl.gz', 'xt', compresslevel=3) as log, gzip.open(output / 'calibration-media.bin.gz', 'rb') as calibration:
        for row in rows:
            row['scores'] = {}
            if row['status'] == 'completed':
                media.seek(row['offset']); raw = media.read(PAYLOAD_SIZE)
                if hashlib.sha256(raw).hexdigest() != row['payload_sha256']:
                    raise ValueError('Closed actual media differs')
                pixels, _, captions = decode(raw)
                values = scores(judges, pixels, captions, targets[row['view'], row['case']])
                row['scores'] = {name: {key: float(value[0]) for key, value in metrics.items()} for name, metrics in values.items()}
            row['selected_action_calibration'] = []
            for saved in row['calibration_records']:
                raw = calibration.read(PAYLOAD_SIZE)
                if hashlib.sha256(raw).hexdigest() != saved['sha256']:
                    raise ValueError('Closed calibration draft differs')
                pixels, _, captions = decode(raw)
                values = scores(judges, pixels, captions, targets[row['view'], row['case']])
                row['selected_action_calibration'].append({name: float(metrics['utility'][0]) for name, metrics in values.items()})
            compact_score = {k: row[k] for k in ('seed', 'case', 'view', 'draw', 'policy', 'status', 'scores', 'selected_action_calibration')}
            log.write(json.dumps(compact_score, sort_keys=True, allow_nan=False) + '\n')
        log.flush(); os.fsync(log.fileno())
    if len(rows) != evaluation['requests'] or fitted['source_sha256'] != pins():
        raise ValueError('Evaluation census or frozen source changed')
    write_json(output / 'completion.json', {'schema': 'hepta.closure.control-completion.v1',
        'status': 'completed', 'rows': len(rows), 'failed': sum(r['status'] != 'completed' for r in rows),
        'source_pairs': pair_count, 'new_independent_sources': pair_count if fresh_protocol else 0, 'seeds': spec['seeds'], 'setup_ns': setup_ns,
        'model_loads': loads, 'scoring_ns': time.perf_counter_ns() - scoring_start,
        'wall_ns': time.perf_counter_ns() - wall, 'cpu_ns': time.process_time_ns() - cpu,
        'completed_unix_ns': time.time_ns(), 'scored_sha256': file_sha(output / 'scored.jsonl.gz'),
        'requests_sha256': file_sha(output / 'requests.jsonl.gz'), 'commitments_sha256': file_sha(output / 'commitments.jsonl.gz'),
        'calibration_media_sha256': file_sha(output / 'calibration-media.bin.gz'),
        'output_bytes': sum(p.stat().st_size for p in output.iterdir() if p.is_file()),
        'media_sha256': file_sha(output / 'actual-media.bin')})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asset-root', type=Path, required=True)
    parser.add_argument('--development', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fresh-protocol', type=Path)
    args = parser.parse_args(); run(args.asset_root, args.development, args.output, args.fresh_protocol)
