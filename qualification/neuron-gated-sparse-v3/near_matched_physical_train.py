#!/usr/bin/env python3
"""Real CPU SGD + physical safetensors for 2K/8K private Hepta Cell adapters.

Uses the *existing* frozen-input and original temporal surrogate evaluator.
SYNTHETIC_CANARY is a research data kind, not a production A0 attestation.
No original V1 mutation, Q24 numerical parity or future NDU may be inferred.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import sys
import time

from matched_train import (
    ARMS, make_model, sha_file, training_input, unique_json, require, utc,
)
from near_matched_capacity_design import choose

Q = 1 << 24
CAPS = (2_048, 8_192)
SCHEMA = 'hepta.neuron.near-matched-physical-train.v1'
MODEL_KIND = 'SYNTHETIC_FIXTURE_ONLY'

def train(args: argparse.Namespace) -> dict:
    require(args.synthetic_canary is True,
            'cannot claim live A0/real Encoder without an independent signed owner')
    require(type(args.steps) is int and 1 <= args.steps <= 64, 'invalid physical optimizer steps')
    require(type(args.seed) is int and 0 <= args.seed < 2**31, 'invalid physical seed')
    frozen_sha = sha_file(Path(args.train_data), args.train_sha256)
    frozen = unique_json(Path(args.train_data).read_bytes())
    d, groups = training_input(frozen)
    require(d == 32 and len(groups) >= 2, 'exact shared 32D and two distinct training groups required')
    import torch
    from safetensors.torch import save_file, load_file
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    schedule = [random.Random(args.seed + i).randrange(len(groups)) for i in range(args.steps)]
    destination = Path(args.output)
    destination.mkdir(parents=True, exist_ok=False)
    records = []
    for ceiling in CAPS:
        for arm in ARMS:
            design = choose(32, arm, ceiling, max_rank=4)
            require(design is not None, 'unfillable new private capacity profile')
            h, rank = design['private_temporal_width'], design['min_gru_rank']
            count = design['complete_proposed_private_parameters']
            require((ceiling-count)*1_000_000 <= 20_000*ceiling,
                    'not a 2-percent physical capacity-matched candidate')
            torch.manual_seed(args.seed)
            adapter = torch.nn.Linear(32, h)
            temporal = make_model(arm, h, rank or 0, torch)
            optimizer = torch.optim.AdamW(
                list(adapter.parameters()) + list(temporal.parameters()),
                lr=0.03, weight_decay=0.0,
            )
            cpu_start = time.process_time()
            last_loss = None
            for group_no in schedule:
                group = groups[group_no][:32]
                features = torch.tensor([r['feature_q24'] for r in group], dtype=torch.float32) / Q
                labels = torch.tensor([r['label'] for r in group], dtype=torch.float32)
                clock = [int(utc(r['event_time_utc']).timestamp()*1_000_000) for r in group]
                predictions = temporal(adapter(features).clamp(-8, 8), clock)
                loss = torch.nn.functional.binary_cross_entropy_with_logits(predictions, labels)
                require(bool(torch.isfinite(loss)), 'nonfinite real optimizer loss')
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(
                    list(adapter.parameters()) + list(temporal.parameters()), 1.0,
                )
                optimizer.step()
                with torch.no_grad():
                    for value in adapter.parameters():
                        value.clamp_(-8, 8)
                    for name, value in temporal.named_parameters():
                        if name.startswith('head.'):
                            value.clamp_(-8, 8)
                        elif arm == 'ssm' and name == 'decay_per_step':
                            value.clamp_(0, 1)
                        elif arm == 'v3' and name == 'gate_bias':
                            value.clamp_(0, 1)
                        else:
                            value.clamp_(-1, 1)
                last_loss = float(loss.detach())
            saved = {
                'adapter.weight': adapter.weight.detach().cpu().contiguous().float(),
                'adapter.bias': adapter.bias.detach().cpu().contiguous().float(),
                'structure.projection': torch.full((h,), Q, dtype=torch.int64),
            }
            for name, value in temporal.named_parameters():
                tensor = value.detach().cpu().contiguous()
                if name.startswith('head.'):
                    saved[name] = tensor.float()
                else:
                    saved['temporal.' + name] = torch.round(tensor*Q).to(torch.int64)
            require(all(bool(torch.isfinite(v.float()).all()) for v in saved.values()),
                    'nonfinite physically stored model tensor')
            actual = sum(v.numel() for v in saved.values())
            require(actual == count and actual <= ceiling, 'loaded real tensor count != plan')
            target = destination / str(ceiling) / (arm + '.safetensors')
            target.parent.mkdir(parents=True, exist_ok=True)
            save_file(saved, str(target))
            reopened = load_file(str(target), device='cpu')
            require(set(reopened) == set(saved)
                    and all(torch.equal(reopened[k], v) for k, v in saved.items()),
                    'physical safetensors reload mismatch')
            raw = target.read_bytes()
            records.append({
                'arm': arm, 'cap': ceiling, 'hidden_width': h, 'rank': rank,
                'weight_file': f'{ceiling}/{arm}.safetensors',
                'weight_sha256': hashlib.sha256(raw).hexdigest(),
                'physical_bytes': len(raw), 'complete_realized_parameters': actual,
                'tensor_count': len(reopened), 'optimizer_steps': args.steps,
                'train_last_loss': last_loss,
                'cpu_training_seconds': round(time.process_time()-cpu_start, 6),
            })
    require(len(records) == 8, 'missing physically trained Cell arms')
    report = {
        'schema': SCHEMA, 'authority': 'DENY_ALL', 'decision': 'NO_MODEL_PROMOTION',
        'source_class': MODEL_KIND, 'actual_train_input_sha256': frozen_sha,
        'encoder_digest_claim_only': frozen['encoder_digest'],
        'original_selected_v1_a0_verified': False,
        'real_shared_encoder_forward_invoked': False,
        'candidate_training_step_count': args.steps, 'seed': args.seed,
        'identical_synthetic_training_schedule': schedule,
        'physical_model_file_count': len(records), 'cells': records,
        'native_Q24_adapter_head_executed': False,
        'equal_training_FLOPs_verified': False, 'future_utility_verified': False,
        'ndu_eligible': False, 'production_qualification': False,
    }
    with (destination / 'training-receipt.json').open('x', encoding='utf-8') as writer:
        json.dump(report, writer, sort_keys=True, indent=2, allow_nan=False)
        writer.write('\n')
    return report

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train-data', required=True, type=Path)
    parser.add_argument('--train-sha256', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--steps', default=8, type=int)
    parser.add_argument('--seed', default=20261015, type=int)
    parser.add_argument('--synthetic-canary', action='store_true')
    args = parser.parse_args()
    try:
        train(args)
        return 0
    except (ValueError, OSError) as e:
        print('BLOCKED_NEAR_MATCHED_PHYSICAL_TRAIN: ' + str(e), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
