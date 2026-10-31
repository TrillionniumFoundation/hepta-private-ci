"""Randomly interleaved actual requests for the single frozen repair candidate."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import time

import torch

from ....abc_next.compact_tree import scores
from ....abc_next.sensor_run import load_sensor
from ....abc_next.value import load_controller
from ....abc_recovery.base_recovery import file_sha, write_json
from ....abc_recovery.trees import stable_seed
from ....v6.data import Observation, Target
from ....v7.data import VIEWS, make_batch
from ....v7.evaluation import load_reward
from ...supplement_sources import load_registered
from ..models import load
from ..registry import HERE, load_model
from ..rollout import PAYLOAD_SIZE, decode, emit_json, request


def run(asset, protocol, output):
    spec = json.loads(protocol.read_text()); evaluation = spec['evaluation']
    if spec['training_seed'] != 17 or spec['threshold'] != .5 or evaluation['requests'] != 3072:
        raise ValueError('Single registered repair candidate/census required')
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    write_json(output / 'registration.json', {'protocol_sha256': file_sha(protocol), 'started_unix_ns': time.time_ns(),
              'study': spec['study'], 'evaluation': evaluation, 'training_seed': 17})
    corpus = load_registered(asset / 'abc2-assets/mnist', asset / 'abc2-runs/source-recovery-001/source-manifest.json',
                              HERE.parent / 'SUPPLEMENT_ALLOCATION.json', 'control_repair', protocol)
    public, targets, identities = {}, {}, {}
    for view in VIEWS:
        batch = make_batch(corpus, 'closure_control_repair', 96,
                           stable_seed(evaluation['observation_namespace'], 0, 96), view=view, offset=0)
        for case in range(96):
            public[view, case] = Observation(*(getattr(batch.observation, k)[case:case + 1].clone() for k in ('pixels', 'mask', 'text_tokens')))
            targets[view, case] = Target(*(getattr(batch.target, k)[case:case + 1].clone() for k in ('pixels', 'text_tokens', 'labels')))
            identities[case] = batch.source_ids[case]
    sensor = load_sensor(asset / 'abc3-runs/public-sensor-001/sensor.pt')
    judges = {name: load_reward(asset / path, expected_file_sha256=sha)[0] for name, path, sha in (
        ('primary', 'abc2-runs/base-recovery-001/reward-observer.pt', '8cfca1b0cd0a69bcfcc6a9d34d0a672c07c28f3342823ef8a3f6763e9430a003'),
        ('secondary', 'abc2-runs/qualification-001/secondary-observer.pt', 'b0851ce56189d159b53449cfc914cf84b9b63e82a6f0050228096666752595fe'))}
    setup_ns = time.perf_counter_ns() - wall; model_load = time.perf_counter_ns()
    snapshot = load_model(asset, 17)
    old = load_controller(asset / 'abc3-runs/controllers-001/seed-17/output_ndu/controller.pt')
    bundle = load(Path(spec['checkpoint']))
    if bundle.threshold != .5 or bundle.actor.config['width'] != 128:
        raise ValueError('Selected trained repair bundle differs')
    load_ns = time.perf_counter_ns() - model_load
    rows, offset, group = [], 0, 0
    order_counts = {policy: 0 for policy in spec['policies']}
    with (output / 'actual-media.bin').open('x+b') as media, gzip.open(output / 'requests.jsonl.gz', 'xt', compresslevel=3) as log, gzip.open(output / 'commitments.jsonl.gz', 'xt', compresslevel=3) as commitments, gzip.open(output / 'calibration-media.bin.gz', 'xb', compresslevel=3) as calibration:
        for view in VIEWS:
            for case in range(96):
                for draw in range(2):
                    order = spec['policies'] if stable_seed(spec['order_namespace'], case, view, draw) % 2 == 0 else list(reversed(spec['policies']))
                    order_counts[order[0]] += 1
                    for position, policy in enumerate(order):
                        row, records = request(snapshot._model, public[view, case], old=old, bundle=bundle, sensor=sensor,
                            policy=policy, seed=17, case=case, view=view, draw=draw, media=media, commitments=commitments, evaluation=evaluation)
                        row['calibration_records'] = []
                        for raw in records:
                            calibration.write(raw)
                            row['calibration_records'].append({'offset': offset, 'sha256': hashlib.sha256(raw).hexdigest()})
                            offset += PAYLOAD_SIZE
                        row.update({'source_ids': identities[case], 'group': group, 'order_position': position})
                        rows.append(row); emit_json(log, row)
                    group += 1
            print(json.dumps({'view': view, 'rows': len(rows), 'failed': sum(r['status'] != 'completed' for r in rows)}), flush=True)
        snapshot.verify_integrity()
    scoring = time.perf_counter_ns()
    with (output / 'actual-media.bin').open('rb') as media, gzip.open(output / 'calibration-media.bin.gz', 'rb') as calibration, gzip.open(output / 'scored.jsonl.gz', 'xt', compresslevel=3) as log:
        for row in rows:
            row['scores'], row['selected_action_calibration'] = {}, []
            if row['status'] == 'completed':
                media.seek(row['offset']); raw = media.read(PAYLOAD_SIZE)
                if hashlib.sha256(raw).hexdigest() != row['payload_sha256']:
                    raise ValueError('Closed confirmation actual media changed')
                pixels, _, captions = decode(raw)
                values = scores(judges, pixels, captions, targets[row['view'], row['case']])
                row['scores'] = {name: {k: float(value[0]) for k, value in metrics.items()} for name, metrics in values.items()}
            for record in row['calibration_records']:
                raw = calibration.read(PAYLOAD_SIZE)
                if hashlib.sha256(raw).hexdigest() != record['sha256']:
                    raise ValueError('Closed confirmation calibration draft changed')
                pixels, _, captions = decode(raw)
                values = scores(judges, pixels, captions, targets[row['view'], row['case']])
                row['selected_action_calibration'].append({name: float(metrics['utility'][0]) for name, metrics in values.items()})
            log.write(json.dumps({k: row[k] for k in ('seed', 'case', 'view', 'draw', 'policy', 'status', 'scores', 'selected_action_calibration')}, sort_keys=True, allow_nan=False) + '\n')
        log.flush(); os.fsync(log.fileno())
    if len(rows) != 3072 or any(file_sha(Path(p)) != digest for p, digest in spec['frozen_candidate_sha256'].items()):
        raise ValueError('Confirmation census or frozen source changed')
    write_json(output / 'completion.json', {'status': 'completed', 'rows': len(rows), 'failed': sum(r['status'] != 'completed' for r in rows),
        'source_pairs': 96, 'training_seed': 17, 'first_policy_counts': order_counts,
        'setup_ns': setup_ns, 'model_load_ns': load_ns, 'scoring_ns': time.perf_counter_ns() - scoring,
        'wall_ns': time.perf_counter_ns() - wall, 'cpu_ns': time.process_time_ns() - cpu, 'completed_unix_ns': time.time_ns(),
        'files_sha256': {name: file_sha(output / name) for name in ('actual-media.bin', 'requests.jsonl.gz', 'commitments.jsonl.gz', 'calibration-media.bin.gz', 'scored.jsonl.gz')},
        'output_bytes': sum(p.stat().st_size for p in output.iterdir() if p.is_file())})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asset-root', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); run(args.asset_root, args.protocol, args.output)
