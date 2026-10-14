#!/usr/bin/env python3
"""CPU-only, physically persisted research training of four Q24-inspired arms.

The selected no-change V1 model is not trained or fabricated here. This is a
restricted, differentiable shadow profile, NOT native Rust Q24 inference or A4.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import random
import resource
import sys
import time
from typing import Any

Q = 1 << 24
H = 8 * Q
CAPS = (2048, 8192, 16384, 65536, 262144)
ARMS = ('v2', 'v3', 'ssm', 'min_gru')
SCHEMA = 'hepta.neuron.frozen-q24-train-input.v1'
TIME_QUANTUM_MICROS = 1_000_000


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def unique_json(data: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path, wanted: str) -> str:
    require(path.is_file() and not path.is_symlink(), 'missing/symlink input')
    before = path.stat()
    require(0 < before.st_size <= 256 * 1024 * 1024, 'unbounded physical file')
    actual = sha_bytes(path.read_bytes())
    after = path.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
             before.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size,
             after.st_mtime_ns, after.st_ctime_ns), 'input changed during hash')
    require(len(wanted) == 64 and wanted == actual, 'physical SHA256 mismatch')
    return actual


def utc(raw: str) -> datetime:
    require(type(raw) is str and raw.endswith('Z'), 'expected strict UTC timestamp')
    try:
        dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('invalid UTC timestamp') from exc
    require(dt.utcoffset().total_seconds() == 0, 'invalid UTC offset')
    return dt


def training_input(payload: Any) -> tuple[int, list[list[dict[str, Any]]]]:
    require(isinstance(payload, dict) and set(payload) ==
            {'schema', 'encoder_digest', 'cell_id', 'train_cutoff_utc', 'samples'}, 'wrong train schema')
    require(payload['schema'] == SCHEMA, 'wrong training schema version')
    enc = payload['encoder_digest']
    require(type(enc) is str and len(enc) == 64 and enc != '0' * 64 and
            all(c in '0123456789abcdef' for c in enc), 'invalid encoder digest')
    require(type(payload['cell_id']) is str and 0 < len(payload['cell_id']) <= 128, 'invalid cell')
    cutoff = utc(payload['train_cutoff_utc'])
    rows = payload['samples']
    require(isinstance(rows, list) and 2 <= len(rows) <= 8192, 'training sample count')
    seen = set()
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    width = None
    for row in rows:
        require(isinstance(row, dict) and set(row) ==
                {'case_id', 'source_group', 'sequence', 'event_time_utc', 'feature_q24', 'label'},
                'unrecognized training field (future label leakage?)')
        ident, group = row['case_id'], row['source_group']
        require(type(ident) is str and 0 < len(ident) <= 128 and ident not in seen, 'bad case ID')
        require(type(group) is str and 0 < len(group) <= 128, 'bad source group')
        seen.add(ident)
        require(type(row['sequence']) is int and row['sequence'] > 0, 'bad sequence')
        require(utc(row['event_time_utc']) < cutoff, 'training event beyond frozen cutoff')
        require(type(row['label']) is int and row['label'] in (0, 1), 'binary label required')
        features = row['feature_q24']
        require(isinstance(features, list) and 5 <= len(features) <= 256, 'invalid input width')
        require(all(type(x) is int and -H <= x <= H for x in features), 'invalid Q24 input')
        width = len(features) if width is None else width
        require(len(features) == width, 'input width drift')
        groups[group].append(row)
    require(len(groups) <= 128, 'too many independent groups')
    for group in groups.values():
        require(len(group) <= 256, 'unbounded sequence history')
        group.sort(key=lambda r: r['sequence'])
        require(all(group[i]['sequence'] < group[i+1]['sequence'] and
                    utc(group[i]['event_time_utc']) < utc(group[i+1]['event_time_utc'])
                    for i in range(len(group)-1)), 'sequence or clock regression')
    return width, [groups[key] for key in sorted(groups)]


def rank_for_budget(width: int, cap: int) -> int:
    # Includes common physical identity projection, actual head and both biases.
    space = cap - (width + 1) - width - 2 * width
    rank = min(width, space // (4 * width))
    require(rank >= 1, 'minGRU rank cannot fit complete private tier')
    return rank



def require_selected_owner_a0(args, cell_id: str, baseline_sha: str) -> dict:
    """Never call a source-tree fixture a live selected V1 owner."""
    if getattr(args, 'synthetic_canary', False):
        return {'evidence_class': 'SYNTHETIC_FIXTURE_ONLY', 'a0_registry_sha256': None}
    root = getattr(args, 'a0_evidence_root', None)
    key = getattr(args, 'a0_trusted_public_key', None)
    host = getattr(args, 'a0_expected_host_id', None)
    require(bool(root and key and host), 'A0 signed live owner census is mandatory')
    from a0_deployment_evidence import evaluate, load_public_key, verify_signed
    attested = evaluate(Path(root), Path(key), expected_host_id=host,
                        max_age_seconds=getattr(args, 'a0_max_age_seconds', 300))
    selected = [x for x in attested['cells'] if x['cell_id'] == cell_id]
    require(len(selected) == 1 and selected[0]['mechanism'] == 'sparse-v1',
            'selected scoped V1 Cell missing from A0 registry')
    public, fingerprint = load_public_key(Path(key))
    evidence = verify_signed(Path(root) / 'cells' / (cell_id + '.json'),
                             public, fingerprint, 'hepta.neuron.deployed-cell-evidence.a0.v1')
    require(evidence['weights_sha256'] == baseline_sha,
            'selected V1 artifact SHA differs from signed A0 model')
    return {'evidence_class': 'SIGNED_A0_FORMAT_ONLY_NOT_HOST_EXECUTION',
            'a0_registry_sha256': attested['registry_sha256'],
            'a0_host_id': attested['host_id'],
            'a0_checkpoint_digest_claimed': selected[0]['reopen_checkpoint_digest'],
            'a0_generation_claimed': selected[0]['generation']}


def make_model(kind: str, width: int, rank: int, torch):
    class Temporal(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.kind = kind
            self.head = torch.nn.Linear(width, 1)
            if kind == 'v3':
                self.gate_bias = torch.nn.Parameter(torch.full((width,), .5))
                self.input_gain = torch.nn.Parameter(torch.full((width,), .1))
                self.change_gain = torch.nn.Parameter(torch.full((width,), .1))
            elif kind == 'ssm':
                self.decay_per_step = torch.nn.Parameter(torch.full((width,), .8))
                self.input_gain = torch.nn.Parameter(torch.full((width,), .5))
            elif kind == 'min_gru':
                self.gate_input = torch.nn.Parameter(torch.randn((rank, width)) * .01)
                self.gate_output = torch.nn.Parameter(torch.zeros((width, rank)))
                self.candidate_input = torch.nn.Parameter(torch.randn((rank, width)) * .01)
                self.candidate_output = torch.nn.Parameter(torch.zeros((width, rank)))
                self.gate_bias = torch.nn.Parameter(torch.zeros(width))
                self.candidate_bias = torch.nn.Parameter(torch.zeros(width))

        def forward(self, x, event_micros):
            h = torch.zeros(width, dtype=x.dtype)
            out = []
            prior_time = None
            for i in range(x.shape[0]):
                value = x[i]
                if kind == 'v2':
                    h = (.5 * h + value).clamp(-8, 8)
                elif kind == 'v3':
                    gate = (self.gate_bias + self.input_gain * value.abs() / 8 +
                            self.change_gain * (value-h).abs() / 16).clamp(0, 1)
                    h = ((1-gate) * h + gate * value).clamp(-8, 8)
                elif kind == 'ssm':
                    dt = 1 if prior_time is None else min(65535, max(1, (event_micros[i]-prior_time)//TIME_QUANTUM_MICROS))
                    h = (self.decay_per_step.clamp(0, 1).pow(dt) * h +
                         self.input_gain.clamp(-1, 1) * value).clamp(-8, 8)
                else:
                    gate = (.5 + self.gate_bias + self.gate_output @ (self.gate_input @ value)).clamp(0, 1)
                    cand = (value + self.candidate_bias +
                            self.candidate_output @ (self.candidate_input @ value)).clamp(-8, 8)
                    h = ((1-gate) * h + gate * cand).clamp(-8, 8)
                prior_time = event_micros[i]
                # Training surrogate: native V2 inhibition, threshold drift,
                # eligibility and exact Q24 rounding MUST be replayed separately.
                scores = h.clamp(min=0)
                split = width // 2
                k = max(1, width // 10)
                candidates = []
                for start, end, local_k in ((0, split, (k+1)//2), (split, width, max(1, k//2))):
                    ranked = sorted(range(start, end), key=lambda j: (-float(scores[j].detach()), j))
                    candidates.extend(j for j in ranked[:local_k] if scores[j].detach().item() > 0)
                chosen = sorted(candidates, key=lambda j: (-float(scores[j].detach()), j))[:k]
                mask = torch.zeros_like(scores)
                mask[chosen] = 1
                out.append(self.head(scores * mask).squeeze(-1))
            return torch.stack(out)
    return Temporal()


def train(args: argparse.Namespace) -> dict[str, Any]:
    # Never receive a future/heldout data path. External A0 owner evidence is
    # a required separate admission step and is NOT inferred from this runner.
    train_path = Path(args.train_data)
    train_sha = sha_file(train_path, args.train_sha256)
    baseline = Path(args.selected_v1)
    baseline_sha = sha_file(baseline, args.selected_v1_sha256)
    spec = unique_json(train_path.read_bytes())
    width, sequences = training_input(spec)
    a0_info = require_selected_owner_a0(args, spec['cell_id'], baseline_sha)
    require(1 <= args.steps <= 512 and 1 <= args.window <= 128, 'invalid training work budget')
    require(0 < args.max_train_cpu_seconds <= 3600, 'invalid per-arm CPU training ceiling')
    import torch
    from safetensors.torch import save_file, load_file
    torch.set_num_threads(1)
    torch.manual_seed(args.seed)
    torch.use_deterministic_algorithms(True)
    schedule = [random.Random(args.seed + j).randrange(len(sequences)) for j in range(args.steps)]
    schedule_sha = sha_bytes(json.dumps(schedule, separators=(',', ':')).encode())
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    report: dict[str, Any] = {
        'schema': 'hepta.neuron.five-arm-differentiable-shadow-train.v1',
        **a0_info,
        'source_train_sha256': train_sha, 'encoder_digest_claimed': spec['encoder_digest'],
        'cell_id': spec['cell_id'], 'training_cutoff_utc': spec['train_cutoff_utc'],
        'train_source_group_hashes': [sha_bytes(group[0]['source_group'].encode()) for group in sequences],
        'no_change_v1_selected_sha256': baseline_sha, 'no_change_optimizer_steps': 0,
        'candidate_optimizer_steps': args.steps, 'cpu_only': True,
        'uniform_per_arm_cpu_ceiling_seconds': args.max_train_cpu_seconds,
        'preregistered_window': args.window, 'seed': args.seed, 'schedule_sha256': schedule_sha,
        'target_host_attested': False, 'native_q24_parity_verified': False,
        'training_provenance_independently_verified': False,
        'future_utility_verified': False, 'ndu_eligible': False,
        'production_qualification': False, 'decision': 'NO_PROMOTION', 'models': []
    }
    for cap in CAPS:
        rank = rank_for_budget(width, cap)
        for arm in ARMS:
            torch.manual_seed(args.seed)
            model = make_model(arm, width, rank if arm == 'min_gru' else 0, torch)
            params = sum(p.numel() for p in model.parameters())
            private_projection_params = width  # frozen identity projection, charged, not free
            total = params + private_projection_params
            require(total <= cap, 'private parameters exceed capped budget')
            optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
            cpu0, wall0 = time.process_time(), time.perf_counter()
            last_loss = None
            for group_index in schedule:
                group = sequences[group_index][:args.window]
                values = torch.tensor([r['feature_q24'] for r in group], dtype=torch.float32) / Q
                y = torch.tensor([r['label'] for r in group], dtype=torch.float32)
                tm = [int(utc(r['event_time_utc']).timestamp() * 1_000_000) for r in group]
                logits = model(values, tm)
                loss = torch.nn.functional.binary_cross_entropy_with_logits(logits, y)
                require(bool(torch.isfinite(loss).item()), 'nonfinite training loss')
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                optimizer.step()
                require(time.process_time()-cpu0 <= args.max_train_cpu_seconds,
                        'shared per-arm CPU training ceiling exceeded')
                last_loss = float(loss.detach())
            saved = {'structure.projection': torch.full((width,), Q, dtype=torch.int64)}
            quant_saturations = 0
            for name, value in model.named_parameters():
                key = ('head.' + name.split('.', 1)[1]) if name.startswith('head.') else 'temporal.' + name
                raw = value.detach().cpu().contiguous()
                require(bool(torch.isfinite(raw).all().item()), 'trained weight not finite')
                if name.startswith('head.'):
                    saved[key] = raw.to(dtype=torch.float32)
                else:
                    quant_saturations += int((raw.abs() > 1).sum())
                    saved[key] = torch.round(raw.clamp(-1, 1) * Q).to(torch.int64)
            fname = f'{cap}/{arm}.safetensors'
            path = root / fname
            path.parent.mkdir(parents=True, exist_ok=True)
            save_file(saved, str(path))
            observed = load_file(str(path), device='cpu')
            require(set(observed) == set(saved) and all(torch.equal(observed[k],v) for k,v in saved.items()),
                    'physical safetensors roundtrip mismatch')
            actual_count = sum(t.numel() for t in observed.values())
            require(actual_count == total, 'materialized private parameter mismatch')
            report['models'].append({
                'cap': cap, 'arm': arm, 'width': width, 'rank': rank if arm == 'min_gru' else None,
                'parameter_count': actual_count, 'weight_file': fname,
                'weight_sha256': sha_bytes(path.read_bytes()),
                'optimizer_steps': args.steps, 'train_loss_last': last_loss,
                'cpu_seconds': round(time.process_time()-cpu0, 6),
                'wall_seconds': round(time.perf_counter()-wall0, 6),
                'quantization_saturations': quant_saturations,
                'optimizer_state_bytes_estimate': params * 8,
            })
    report['peak_process_rss_kib_not_arm_comparable'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    receipt = root / 'training-receipt.json'
    with receipt.open('x', encoding='utf-8') as dest:
        json.dump(report, dest, indent=2, sort_keys=True)
        dest.write('\n')
        dest.flush()
        os.fsync(dest.fileno())
    return report


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--train-data', required=True)
    p.add_argument('--train-sha256', required=True)
    p.add_argument('--selected-v1', required=True)
    p.add_argument('--selected-v1-sha256', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--a0-evidence-root')
    p.add_argument('--a0-trusted-public-key')
    p.add_argument('--a0-expected-host-id')
    p.add_argument('--a0-max-age-seconds', type=int, default=300)
    p.add_argument('--synthetic-canary', action='store_true',
                   help='unit-test fixture ONLY; denies real A0/model proof')
    p.add_argument('--steps', type=int, default=64)
    p.add_argument('--window', type=int, default=32)
    p.add_argument('--max-train-cpu-seconds', type=float, default=300.0)
    p.add_argument('--seed', type=int, default=7347)
    p.add_argument('--lr', type=float, default=.01)
    args = p.parse_args()
    try:
        require(0 < args.lr <= .1 and 0 <= args.seed < 2**32, 'invalid optimizer')
        result = train(args)
        print(json.dumps({'status': 'RESEARCH_TRAINED_SHADOW_ONLY', 'models':len(result['models']),
                          'production_qualification':False,'ndu_eligible':False}))
        return 0
    except (ValueError, OSError, ImportError, RuntimeError) as exc:
        print(json.dumps({'status':'BLOCKED_REAL_FIVE_ARM_TRAIN','error':str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
