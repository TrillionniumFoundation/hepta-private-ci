"""Prospective frozen old-five-action execution on the shared new writer panel."""

import argparse
from contextlib import ExitStack
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from ...abc_next.compact_tree import scores
from ...abc_next.sensor_run import load_sensor
from ...abc_next.value import load_controller
from ...abc_recovery.base_recovery import file_sha, write_json
from ...abc_recovery.trees import stable_seed
from ...closure_20261025.control.registry import load_model
from ...closure_20261025.control.rollout import PAYLOAD_SIZE, decode, emit_json
from ...next_20261025.native.common import OBSERVER, SENSOR, SHARED, TEACHER
from ...v6.data import Observation, Target
from ...v7.data import VIEWS, make_batch
from ...v7.evaluation import load_reward
from ..sources import load_images
from .online import AffinePolicy, POLICIES, counterfactuals, request


def verify(spec):
    for path, expected in spec['frozen_candidate_sha256'].items():
        if file_sha(Path(path)) != expected:
            raise ValueError('Frozen dependency changed: ' + path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    spec = json.loads(args.protocol.read_text()); verify(spec)
    if spec['policies'] != list(POLICIES) or spec['seed'] != 17:
        raise ValueError('The registered selected seed-17 paired comparison is required')
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / 'registration.json', {'protocol_sha256': file_sha(args.protocol),
        'spec': spec, 'started_unix_ns': time.time_ns()})
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    corpus = load_images(Path(spec['source']['cache']), Path(spec['source']['allocation']),
        args.protocol, 'confirmation')
    role = corpus.manifest['roles']['confirmation']; count = role['pair_count']
    if count != 170 or role['writer_count'] != 85:
        raise ValueError('The complete preregistered source panel is required')
    observations, targets, identities = {}, {}, {}
    for view in VIEWS:
        batch = make_batch(corpus, role['role'], count,
            stable_seed(spec['evaluation']['observation_namespace'], count), view=view, offset=0)
        for case in range(count):
            observations[view, case] = Observation(*(getattr(batch.observation, key)[case:case + 1].clone()
                for key in ('pixels', 'mask', 'text_tokens')))
            targets[view, case] = Target(*(getattr(batch.target, key)[case:case + 1].clone()
                for key in ('pixels', 'text_tokens', 'labels')))
            identities[case] = batch.source_ids[case]
    loaded = time.perf_counter_ns()
    snapshot = load_model(SHARED, 17); teacher = load_controller(TEACHER); sensor = load_sensor(SENSOR)
    candidate = AffinePolicy(json.loads(Path(spec['candidate']).read_text()))
    predictor = json.loads(Path(spec['predictor']).read_text())
    calibration = json.loads(Path(spec['calibration']).read_text())
    load_wall = time.perf_counter_ns() - loaded
    rng = np.random.default_rng(spec['evaluation']['order_seed'])
    requests = diagnostics = failures = rejections = diagnostic_failures = offline_wall = offline_cpu = 0
    with ExitStack() as stack:
        media = stack.enter_context((args.output / 'media.bin').open('x+b'))
        logs = {name: stack.enter_context(gzip.open(args.output / (name + '.jsonl.gz'), 'xt', compresslevel=3))
                for name in ('requests', 'commitments', 'counterfactuals', 'diagnostic-commitments')}
        for view in VIEWS:
            for case in range(count):
                for draw in range(spec['draws']):
                    retained = candidate_row = None
                    for order, policy in enumerate(rng.permutation(POLICIES).tolist()):
                        row, state = request(snapshot._model, observations[view, case], teacher, candidate,
                            sensor, predictor, calibration, policy=policy, seed=17, case=case, view=view,
                            draw=draw, spec=spec['evaluation'], media=media, commitments=logs['commitments'])
                        row.update(order_index=order, source_ids=identities[case], writer=role['pair_writer_ids'][case])
                        emit_json(logs['requests'], row)
                        requests += 1; failures += row['status'] == 'failed'; rejections += row['status'] == 'rejected'
                        if policy == 'constrained_paired':
                            retained, candidate_row = state, row
                    if retained is not None and candidate_row['status'] != 'failed':
                        record = counterfactuals(snapshot._model, teacher, retained, candidate_row,
                            spec['evaluation'], media, logs['diagnostic-commitments'])
                        emit_json(logs['counterfactuals'], record); diagnostics += 1
                        offline_wall += record['offline_wall_ns']; offline_cpu += record['offline_cpu_ns']
                        diagnostic_failures += sum(row['status'] == 'failed' for row in record['alternatives'])
            print(json.dumps({'view': view, 'requests': requests, 'operational_failures': failures,
                'expected_content_rejections': rejections, 'offline_H1_nodes': diagnostics}), flush=True)
    snapshot.verify_integrity()
    expected = count * len(VIEWS) * spec['draws'] * len(POLICIES)
    if requests != expected:
        raise ValueError('The complete prospective request census differs')
    # Private targets first enter a judge after every online request has closed.
    scoring_start = time.perf_counter_ns()
    judges = {'primary': load_reward(OBSERVER, expected_file_sha256=spec['frozen_candidate_sha256'][str(OBSERVER)])[0]}
    secondary_path = SHARED / 'abc2-runs/qualification-001/secondary-observer.pt'
    judges['secondary'] = load_reward(secondary_path,
        expected_file_sha256=spec['frozen_candidate_sha256'][str(secondary_path)])[0]
    with (args.output / 'media.bin').open('rb') as media:
        @torch.inference_mode()
        def observe(saved, target):
            media.seek(saved['offset']); raw = media.read(PAYLOAD_SIZE)
            if len(raw) != PAYLOAD_SIZE or hashlib.sha256(raw).hexdigest() != saved['sha256']:
                raise ValueError('Actual emitted media changed before private observation')
            pixels, _, caption = decode(raw)
            return {name: {key: float(value[0]) for key, value in result.items()}
                    for name, result in scores(judges, pixels, caption, target).items()}

        for source_name, destination in (('requests', 'scored'), ('counterfactuals', 'counterfactual-scored')):
            with gzip.open(args.output / (source_name + '.jsonl.gz'), 'rt') as source, gzip.open(
                    args.output / (destination + '.jsonl.gz'), 'xt', compresslevel=3) as out:
                for row in map(json.loads, source):
                    target = targets[row['view'], row['case']]
                    if source_name == 'requests':
                        if row['status'] == 'completed':
                            row['scores'] = observe(row['terminal'], target)
                    else:
                        for item in row['alternatives']:
                            if item['status'] == 'completed':
                                item['scores'] = observe(item['media'], target)
                    emit_json(out, row)
    verify(spec)
    write_json(args.output / 'completion.json', {'schema': 'hepta.advance.old-five-execution.v1',
        'status': 'completed', 'source_pairs': count, 'writer_clusters': 85, 'requests': requests,
        'operational_failures': failures, 'expected_content_rejections': rejections,
        'diagnostic_nodes': diagnostics, 'diagnostic_failures': diagnostic_failures,
        'offline_counterfactual_wall_ns': offline_wall, 'offline_counterfactual_cpu_ns': offline_cpu,
        'scoring_wall_ns': time.perf_counter_ns() - scoring_start, 'model_load_wall_ns': load_wall,
        'wall_ns': time.perf_counter_ns() - began, 'cpu_ns': time.process_time_ns() - cpu,
        'torch_version': torch.__version__, 'numpy_version': np.__version__,
        'files_sha256': {path.name: file_sha(path) for path in args.output.iterdir() if path.is_file()},
        'production_authority': False, 'native_owner_executed': False})


if __name__ == '__main__':
    main()
