"""Encode the frozen coverage diagnostic with one cached CPU model owner."""

import argparse
import gzip
import hashlib
import importlib.metadata
import json
from pathlib import Path
import resource
import time

import numpy as np
import torch
from transformers import AutoTokenizer

from bounded_text_inputs import canonical, matched_inputs
from coverage_checkpoint import load_frozen_body


SNAPSHOT = Path('/data/hepta-decisioncell-models/LiquidAI--LFM2.5-Encoder-230M/0b649ad0c684378b03d4d8304f7577a662ab89bc')
CUSTOM_SHA = 'f171f518be2a07da48b17fdea5655cad0a2452ab548e90e8ae903143686647e2'


def sha_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def export(dataset, output):
    dataset, output = Path(dataset), Path(output)
    manifest = json.loads((dataset / 'manifest.json').read_text())
    if sha_file(dataset / 'predictors.json') != manifest['files']['predictors.json']:
        raise ValueError('predictor corpus differs from frozen selection')
    rows = json.loads((dataset / 'predictors.json').read_text())
    if len(rows) != 896 or len({r['group_id'] for r in rows}) != len(rows):
        raise ValueError('fixed complete distinct-group source cohort required')
    if sha_file(SNAPSHOT / 'modeling_lfm2_bidirectional.py') != CUSTOM_SHA:
        raise ValueError('reviewed local model implementation changed')
    output.mkdir(parents=True, exist_ok=False)
    started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
    inventory = {str(p.relative_to(SNAPSHOT)): {'sha256': sha_file(p), 'bytes': p.stat().st_size}
                 for p in sorted(SNAPSHOT.rglob('*')) if p.is_file() and '.cache' not in p.parts}
    inventory_sha = hashlib.sha256(canonical(inventory)).hexdigest()
    tokenizer = AutoTokenizer.from_pretrained(str(SNAPSHOT), local_files_only=True, trust_remote_code=True)
    prepared = matched_inputs(tokenizer, rows, max_tokens=192)
    # The prefix control must reproduce the actual native tokenizer truncation.
    for row, (inputs, _) in zip(rows, prepared['prefix'], strict=True):
        expected = tokenizer(row['text'], add_special_tokens=True, truncation=True,
                             max_length=192, return_token_type_ids=False)['input_ids']
        if inputs['input_ids'] != expected:
            raise ValueError('prefix input differs from native tokenizer truncation')
    preparation = {'wall_ns': time.perf_counter_ns() - started,
                   'cpu_ns': time.process_time_ns() - cpu_started,
                   'native_prefix_parity_rows': len(rows)}
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    model, checkpoint_parity = load_frozen_body()
    model.eval().requires_grad_(False)
    if any(p.device.type != 'cpu' for p in model.parameters()):
        raise ValueError('CPU-only frozen model required')
    load = {'wall_ns': time.perf_counter_ns() - start, 'cpu_ns': time.process_time_ns() - cpu,
            'parameters': sum(p.numel() for p in model.parameters()),
            'parameter_tensor_bytes': sum(p.numel() * p.element_size() for p in model.parameters()),
            'checkpoint_parity': checkpoint_parity}
    accounting = {policy: {'wall_ns': 0, 'cpu_ns': 0, 'forward_calls': 0,
                          'effective_tokens': 0, 'padded_tokens': 0, 'attention_length_squared': 0}
                  for policy in prepared}
    matrices = {policy: [] for policy in prepared}

    def forward(inputs):
        batch = tokenizer.pad(inputs, padding=True, return_tensors='pt')
        with torch.inference_mode():
            hidden = model(**batch, use_cache=False, return_dict=True).last_hidden_state
            mask = batch['attention_mask'].unsqueeze(-1).to(hidden.dtype)
            pooled = (hidden * mask).sum(1) / mask.sum(1).clamp_min(1)
            pooled = torch.nn.functional.normalize(pooled, dim=-1)
        if not bool(torch.isfinite(pooled).all()) or pooled.shape[1] != 1024:
            raise ValueError('native body produced invalid feature shape or values')
        return pooled.cpu().numpy().astype(np.float32), batch

    warm_start, warm_cpu = time.perf_counter_ns(), time.process_time_ns()
    for policy in prepared:
        forward([pair[0] for pair in prepared[policy][:8]])
    warmup = {'forward_calls': 2, 'wall_ns': time.perf_counter_ns() - warm_start,
              'cpu_ns': time.process_time_ns() - warm_cpu,
              'effective_tokens': sum(pair[1]['effective_model_tokens'] for pairs in prepared.values() for pair in pairs[:8]),
              'included_in_measured_features': False}
    for begin in range(0, len(rows), 8):
        order = ('prefix', 'head_tail') if (begin // 8) % 2 == 0 else ('head_tail', 'prefix')
        batch_shapes = []
        for policy in order:
            start, cpu = time.perf_counter_ns(), time.process_time_ns()
            values, batch = forward([pair[0] for pair in prepared[policy][begin:begin + 8]])
            counters = accounting[policy]
            counters['wall_ns'] += time.perf_counter_ns() - start
            counters['cpu_ns'] += time.process_time_ns() - cpu
            counters['forward_calls'] += 1
            counters['effective_tokens'] += int(batch['attention_mask'].sum())
            counters['padded_tokens'] += int(batch['input_ids'].numel())
            counters['attention_length_squared'] += int(batch['input_ids'].shape[0] * batch['input_ids'].shape[1]**2)
            batch_shapes.append(list(batch['input_ids'].shape))
            matrices[policy].append(values)
        if batch_shapes[0] != batch_shapes[1]:
            raise ValueError('paired physical padding budget drift')
        if begin % 80 == 0:
            print(json.dumps({'stage': 'encoding', 'rows_per_policy': min(begin + 8, len(rows))}), flush=True)
    for key in ('effective_tokens', 'padded_tokens', 'forward_calls', 'attention_length_squared'):
        if accounting['prefix'][key] != accounting['head_tail'][key]:
            raise ValueError('paired physical encoder work differs: ' + key)
    features = {policy: np.concatenate(parts) for policy, parts in matrices.items()}
    short = [i for i, pair in enumerate(prepared['prefix']) if not pair[1]['truncated']]
    if not np.array_equal(features['prefix'][short], features['head_tail'][short]):
        raise ValueError('unchanged short inputs produced different paired features')
    identities = {policy: {'model': 'LiquidAI/LFM2.5-Encoder-230M',
        'revision': SNAPSHOT.name, 'snapshot_sha256': inventory_sha,
        'dataset_manifest_sha256': sha_file(dataset / 'manifest.json'),
        'policy': policy, 'max_tokens': 192, 'pooling': 'masked_mean_nonpadding_then_l2',
        'width': 1024, 'dtype': 'float32'} for policy in prepared}
    with (output / 'features.npz').open('xb') as stream:
        np.savez_compressed(stream, **features)
    with gzip.open(output / 'token_receipts.json.gz', 'wt', encoding='utf-8') as stream:
        json.dump({policy: [pair[1] for pair in pairs] for policy, pairs in prepared.items()}, stream,
                  ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    report = {'schema': 'hepta.input-coverage-features.v1', 'authority': 'DENY_ALL',
        'identities': identities, 'inventory': inventory, 'preparation': preparation,
        'model_load': load, 'warmup': warmup, 'encoding': accounting,
        'feature_shapes': {p: list(x.shape) for p, x in features.items()},
        'feature_tensor_bytes': {p: x.nbytes for p, x in features.items()},
        'files': {p.name: sha_file(p) for p in output.iterdir() if p.is_file()},
        'unchanged_short_input_bitwise_parity_rows': len(short),
        'tokens': {split: {'rows': sum(r['split'] == split for r in rows),
            'truncated': sum(pair[1]['truncated'] for r, pair in zip(rows, prepared['prefix'], strict=True) if r['split'] == split),
            'original_source_tokens': sum(pair[1]['source_tokens'] for r, pair in zip(rows, prepared['prefix'], strict=True) if r['split'] == split)}
            for split in ('train', 'calibration', 'evaluation')},
        'environment': {'torch_threads': torch.get_num_threads(), 'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            'packages': {name: importlib.metadata.version(name) for name in ('numpy', 'torch', 'transformers', 'tokenizers', 'safetensors')}},
        'source_code_sha256': {p.name: sha_file(p) for p in (Path(__file__), Path(__file__).with_name('bounded_text_inputs.py'),
                                                          Path(__file__).with_name('coverage_checkpoint.py'))}}
    (output / 'report.json').write_bytes(canonical(report) + b'\n')
    print(json.dumps({'stage': 'encoded', 'encoding': accounting, 'truncation': report['tokens'],
                      'feature_report_sha256': sha_file(output / 'report.json')}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--output', required=True)
    export(**vars(parser.parse_args()))
