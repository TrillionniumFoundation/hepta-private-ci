#!/usr/bin/env python3
"""Train, calibrate and evaluate SAME-BUDGET option-scoring heads over frozen encoders.

Exact checkpoint files must exist locally. Dependencies: numpy, torch, psutil,
sentence-transformers. This is a research adapter, not a Hepta effect authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as inp:
        for block in iter(lambda: inp.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def read_dataset(path: Path) -> list[dict]:
    data = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not data or len({r['case_id'] for r in data}) != len(data):
        raise ValueError('empty or duplicate dataset')
    groups = {split: {r['group_id'] for r in data if r['split'] == split}
              for split in ('train', 'calibration', 'test', 'future')}
    for left in groups:
        for right in groups:
            if left != right and groups[left] & groups[right]:
                raise ValueError('group leakage across splits')
    return data


def row_texts(row: dict) -> list[str]:
    criteria = row.get('criteria') or {label: label for label in row['labels']}
    if set(criteria) != set(row['labels']):
        raise ValueError('criteria differ from labels')
    return [json.dumps({'state': row['state'], 'question': row['question'],
                        'option': criteria[label]}, sort_keys=True, ensure_ascii=False)
            for label in row['labels']]


def encode(encoder, rows: list[dict], projection, device: str):
    import numpy as np
    features = []
    for row in rows:
        vecs = encoder.encode(row_texts(row), normalize_embeddings=True,
                              show_progress_bar=False, convert_to_numpy=True)
        if vecs.ndim != 2 or vecs.shape[1] != projection.shape[0]:
            raise ValueError('encoder output width drift')
        features.append(np.asarray(vecs, dtype=np.float32) @ projection)
    return features


def options():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('train', 'calibrate', 'eval'))
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--encoder-dir', type=Path, required=True)
    parser.add_argument('--weights-file', type=Path, required=True)
    parser.add_argument('--weights-sha256', required=True)
    parser.add_argument('--device', choices=('cpu', 'cuda', 'mps'), required=True)
    parser.add_argument('--host-id', required=True)
    parser.add_argument('--target-dim', type=int, default=256)
    parser.add_argument('--projection-seed', type=int, default=42)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--steps', type=int, default=512)
    parser.add_argument('--batch-size', type=int, default=16)
    parser.add_argument('--head-file', type=Path, required=True)
    parser.add_argument('--calibration-file', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reviewed-local-code', action='store_true',
                        help='Only after independent source audit of checkpoint custom Python')
    return parser.parse_args()


def main() -> int:
    args = options()
    try:
        if args.target_dim != 256 or args.batch_size < 1 or args.steps < 1:
            raise ValueError('invalid or unregistered training budget')
        root = args.encoder_dir.resolve(strict=True)
        weights = args.weights_file.resolve(strict=True)
        if not weights.is_relative_to(root) or sha_file(weights) != args.weights_sha256:
            raise ValueError('weights identity mismatch')
        if not args.host_id or args.output.exists():
            raise ValueError('host required; existing output must not be overwritten')
        from sentence_transformers import SentenceTransformer
        import numpy as np
        import torch
        import psutil
        data = read_dataset(args.dataset)
        required = {'train': 'train', 'calibrate': 'calibration', 'eval': None}[args.stage]
        rows = [r for r in data if r['split'] == required] if required else [
            r for r in data if r['split'] in ('test', 'future')]
        if not rows:
            raise ValueError('no rows for requested stage')
        torch.manual_seed(args.seed)
        np.random.seed(args.seed)
        encoder = SentenceTransformer(str(root), device=args.device,
                                      trust_remote_code=args.reviewed_local_code)
        dim = encoder.get_sentence_embedding_dimension()
        if type(dim) is not int or dim < 256:
            raise ValueError('frozen encoder output too narrow')
        rng = np.random.default_rng(args.projection_seed)
        projection = rng.standard_normal((dim, args.target_dim)).astype(np.float32) / math.sqrt(args.target_dim)
        features = encode(encoder, rows, projection, args.device) if args.stage != 'eval' else None
        head = torch.nn.Linear(args.target_dim, 1).to(args.device)
        if args.stage == 'train':
            if args.head_file.exists():
                raise ValueError('head artifact already exists')
            optimizer = torch.optim.AdamW(head.parameters(), lr=1e-3)
            order = np.random.default_rng(args.seed)
            trainable = [torch.tensor(f, dtype=torch.float32, device=args.device) for f in features]
            for _ in range(args.steps):
                selected = order.integers(0, len(trainable), size=args.batch_size)
                optimizer.zero_grad()
                total = 0
                for idx in selected:
                    truth = rows[int(idx)]
                    position = truth['labels'].index(truth['label'])
                    scores = head(trainable[int(idx)]).flatten()
                    total = total + torch.nn.functional.cross_entropy(scores[None, :],
                                                                       torch.tensor([position], device=args.device))
                (total / args.batch_size).backward()
                optimizer.step()
            # Save only raw tensors, never pickle an executable model object.
            with args.head_file.open('xb') as output:
                np.savez(output, weight=head.weight.detach().cpu().numpy(), bias=head.bias.detach().cpu().numpy(),
                         projection=projection)
            train_rows = sorted(rows, key=lambda r: r['case_id'])
            optimizer_digest = hashlib.sha256(canonical({'optimizer': 'AdamW',
                'lr': 0.001, 'weight_decay': 0.01, 'betas': [0.9, 0.999], 'eps': 1e-8})).hexdigest()
            report = {'stage': 'train', 'steps': args.steps, 'batch_size': args.batch_size,
                      'optimizer_sha256': optimizer_digest,
                      'examples_seen': args.steps * args.batch_size, 'seed': args.seed,
                      'target_dim': args.target_dim, 'projection_seed': args.projection_seed,
                      'training_dataset_sha256': hashlib.sha256(canonical(train_rows)).hexdigest(),
                      'head_sha256': sha_file(args.head_file), 'encoder_weights_sha256': args.weights_sha256}
        else:
            if not args.head_file.is_file():
                raise ValueError('selected trained head artifact missing')
            with np.load(args.head_file, allow_pickle=False) as obj:
                if obj['projection'].shape != projection.shape or not np.array_equal(obj['projection'], projection):
                    raise ValueError('projection binding mismatch')
                head.weight.data = torch.tensor(obj['weight'], device=args.device)
                head.bias.data = torch.tensor(obj['bias'], device=args.device)
            head.eval()
            raw = ([head(torch.tensor(f, dtype=torch.float32, device=args.device)).flatten().detach().cpu().numpy()
                   for f in features] if args.stage == 'calibrate' else [])
            if args.stage == 'calibrate':
                if args.calibration_file is None or args.calibration_file.exists():
                    raise ValueError('new calibration-file required')
                # Select temperature using ONLY independent calibration examples.
                temperatures = (0.5, 0.75, 1., 1.5, 2., 3., 5.)
                def loss(t):
                    return sum(float(-torch.nn.functional.log_softmax(
                        torch.tensor(logits / t), dim=0)[row['labels'].index(row['label'])])
                        for row, logits in zip(rows, raw)) / len(rows)
                temperature = min(temperatures, key=loss)
                probs = [torch.softmax(torch.tensor(logits / temperature), 0).numpy()
                         for logits in raw]
                candidates = [float(i) / 100 for i in range(0, 101, 5)]
                # A calibrated threshold minimizing false acceptance on OOD while
                # keeping at least 50% in-domain coverage; otherwise abstain always.
                in_domain = [p for row, p in zip(rows, probs) if not row['ood']]
                ood = [p for row, p in zip(rows, probs) if row['ood']]
                def coverage(t, samples):
                    return sum(int(float(np.max(p)) >= t) for p in samples) / len(samples) if samples else 0.
                admissible = [t for t in candidates if in_domain and coverage(t, in_domain) >= .5 and
                              (not ood or coverage(t, ood) <= .05)]
                threshold = min(admissible) if admissible else 1.0
                config = {'schema': 'hepta.bakeoff.calibration.v1', 'temperature': temperature,
                          'threshold': threshold, 'head_sha256': sha_file(args.head_file),
                          'encoder_weights_sha256': args.weights_sha256,
                          'calibration_sha256': hashlib.sha256(canonical(sorted(rows, key=lambda r: r['case_id']))).hexdigest()}
                args.calibration_file.write_bytes(canonical(config))
                report = {'stage': 'calibrate', 'calibration_sha256': sha_file(args.calibration_file),
                          'calibration_samples': len(rows), 'temperature': temperature, 'threshold': threshold}
            else:
                if args.calibration_file is None or not args.calibration_file.is_file():
                    raise ValueError('precommitted calibration artifact required')
                config = json.loads(args.calibration_file.read_text())
                if config['head_sha256'] != sha_file(args.head_file) or config['encoder_weights_sha256'] != args.weights_sha256:
                    raise ValueError('calibration artifact identity mismatch')
                calibration_rows = sorted([r for r in data if r['split'] == 'calibration'], key=lambda r: r['case_id'])
                if config['calibration_sha256'] != hashlib.sha256(canonical(calibration_rows)).hexdigest():
                    raise ValueError('calibration split lineage mismatch')
                observations = []
                process = psutil.Process(os.getpid())
                for row in rows:
                    if args.device == 'cuda':
                        torch.cuda.synchronize()
                    start = time.perf_counter()
                    vec = encoder.encode(row_texts(row), normalize_embeddings=True,
                                         show_progress_bar=False, convert_to_numpy=True)
                    if vec.shape[1] != projection.shape[0]:
                        raise ValueError('encoder width changed at inference')
                    projected = np.asarray(vec, dtype=np.float32) @ projection
                    logits = head(torch.tensor(projected, dtype=torch.float32, device=args.device)).flatten()
                    prob = torch.softmax(logits / float(config['temperature']), dim=0).detach().cpu().numpy()
                    if args.device == 'cuda':
                        torch.cuda.synchronize()
                    elapsed = (time.perf_counter() - start) * 1000
                    observations.append({'case_id': row['case_id'],
                                         'probabilities': {label: float(prob[i]) for i, label in enumerate(row['labels'])},
                                         'abstained': bool(float(max(prob)) < float(config['threshold'])),
                                         'latency_ms': max(1e-6, elapsed), 'rss_bytes': process.memory_info().rss,
                                         'gpu_peak_bytes': None, 'host_id': args.host_id, 'device': args.device,
                                         'model_weights_sha256': args.weights_sha256,
                                         'head_sha256': sha_file(args.head_file),
                                         'calibration_sha256': sha_file(args.calibration_file)})
                # End-to-end local sequential inference includes the encoder, projection and head.
                # Queue age, loading, host GPU device memory and multi-cell contention are
                # still separate workload measurements and must never be inferred here.
                args.output.write_text(''.join(json.dumps(x, ensure_ascii=False, allow_nan=False) + '\n'
                                               for x in observations), encoding='utf-8')
                return 0
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    except (ValueError, OSError, KeyError, ImportError, RuntimeError) as exc:
        print('BLOCKED:', exc, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
