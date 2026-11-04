"""One fresh, offline model process. Invoked only by the approved supervisor."""
import argparse
import gc
import hashlib
import importlib.metadata
import io
import json
import math
import os
from pathlib import Path
import resource
import socket
import statistics
import sys
import time
from common import ROOT, nearest_rank, process_peak, read_json, validate_fixtures, verify_assets, verify_seal


def rss_snapshot():
    result = {'ru_maxrss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}
    for filename, wanted in (('status', ('VmRSS', 'VmHWM', 'Threads')),
                             ('smaps_rollup', ('Rss',))):
        try:
            for line in Path('/proc/self', filename).read_text().splitlines():
                key, _, value = line.partition(':')
                if key in wanted:
                    result[f'{filename}_{key}'] = int(value.split()[0]) * (1 if key == 'Threads' else 1024)
        except OSError:
            result[f'{filename}_unavailable'] = True
    return result


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def main():
    if sys.flags.optimize:
        raise RuntimeError('Optimized Python disables checks and is prohibited')
    parser = argparse.ArgumentParser()
    parser.add_argument('--arm', choices=['fp32', 'int8'], required=True)
    parser.add_argument('--assets', required=True)
    parser.add_argument('--admission', required=True)
    parser.add_argument('--approval', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--cpu', type=int, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    protocol = read_json(ROOT / 'protocol.json')
    seal_hash = verify_seal()
    approval = read_json(args.approval)
    assert approval['decision'] == 'GO' and approval['seal_sha256'] == seal_hash
    assert approval['independent_review'] == 'GO' and approval['primary_run_authorized'] is True
    attempt = read_json(ROOT / 'PRIMARY_ATTEMPT.json')
    assert attempt['state'] == 'STARTED' and attempt['seal_sha256'] == seal_hash
    assert attempt['supervisor_pid'] == os.getppid(), 'Worker requires the active approved supervisor'
    admission = read_json(args.admission)
    assert approval['admission_sha256'] == hashlib.sha256(Path(args.admission).read_bytes()).hexdigest()
    os.sched_setaffinity(0, {args.cpu})
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (45, 46))
    def no_network(event, _args):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo'):
            raise RuntimeError('Worker network access is prohibited')
    sys.addaudithook(no_network)
    verify_assets(args.assets, admission, protocol)
    rows = validate_fixtures(read_json(ROOT / 'fixtures.json'))
    versions = {key: importlib.metadata.version(key) for key in protocol['runtime_versions']}
    assert versions == protocol['runtime_versions'], versions
    verified_at = time.perf_counter()
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    imported_at = time.perf_counter()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    torch.use_deterministic_algorithms(True)
    assert protocol['quantized_engine'] in torch.backends.quantized.supported_engines
    torch.backends.quantized.engine = protocol['quantized_engine']
    tokenizer = AutoTokenizer.from_pretrained(args.assets, local_files_only=True, trust_remote_code=False, use_fast=True)
    model, loading_info = AutoModelForSequenceClassification.from_pretrained(
        args.assets, local_files_only=True, trust_remote_code=False, use_safetensors=True,
        torch_dtype=torch.float32, attn_implementation='eager', output_loading_info=True)
    assert not any(loading_info.get(key) for key in ('missing_keys', 'unexpected_keys', 'mismatched_keys', 'error_msgs')), loading_info
    model = model.cpu().eval()
    assert model.config.model_type == 'bert' and model.config.num_labels == 1
    assert all(p.device.type == 'cpu' and p.dtype == torch.float32 for p in model.parameters())
    original_names = [name for name, m in model.named_modules() if isinstance(m, torch.nn.Linear)]
    assert len(original_names) == protocol['expected_linear_count']
    loaded_at = time.perf_counter()
    if args.arm == 'int8':
        # Default observer, qint8 weights, every Linear, one fixed candidate only.
        # inplace=False deliberately charges the temporary FP32 copy to RSS/startup.
        model = torch.ao.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8, inplace=False).eval()
        gc.collect()
    converted_at = time.perf_counter()
    quantized_names = [name for name, m in model.named_modules() if isinstance(m, torch.ao.nn.quantized.dynamic.Linear)]
    remaining_names = [name for name, m in model.named_modules() if isinstance(m, torch.nn.Linear)]
    if args.arm == 'int8':
        assert sorted(quantized_names) == sorted(original_names) and not remaining_names
        assert all(m.weight().dtype == torch.qint8 for m in model.modules()
                   if isinstance(m, torch.ao.nn.quantized.dynamic.Linear))
    else:
        assert not quantized_names and remaining_names == original_names

    @torch.inference_mode()
    def score(row, fingerprint=False):
        before = time.perf_counter()
        encoded = tokenizer([row['query']] * 4, [p['text'] for p in row['passages']],
                            padding=True, truncation='longest_first', max_length=protocol['max_length'], return_tensors='pt')
        logits = model(**encoded).logits
        assert tuple(logits.shape) == (4, 1)
        values = logits[:, 0].tolist()
        assert all(math.isfinite(v) for v in values)
        elapsed_ms = (time.perf_counter() - before) * 1000
        token_hash = hashlib.sha256(json.dumps({k: v.tolist() for k, v in encoded.items()}, sort_keys=True).encode()).hexdigest() if fingerprint else None
        return values, elapsed_ms, token_hash

    first_scores, first_latency_ms, _ = score(rows[0])
    first_at = time.perf_counter()
    first_rss = rss_snapshot()
    for _ in range(protocol['warmup_cycles']):
        for row in rows:
            score(row)
    ready_at = time.perf_counter()
    ready_rss = rss_snapshot()
    write_json(args.output + '.ready.json', {'first_at': first_at, 'ready_at': ready_at})
    scores, fingerprints, token_lengths = [], [], []
    for row in rows:
        values, _, fingerprint = score(row, fingerprint=True)
        scores.append(values)
        fingerprints.append(fingerprint)
        lengths = tokenizer([row['query']] * 4, [p['text'] for p in row['passages']], padding=False, truncation=False)['input_ids']
        token_lengths.append([len(x) for x in lengths])
    for i in (3, 7):
        assert abs(scores[i][0] - scores[i][1]) <= protocol['tie_epsilon'], 'Identical-input tie failed'
    latencies = []
    by_stratum = {key: [] for key in ('short', 'medium', 'long')}
    gc.disable()
    for cycle in range(protocol['timed_cycles']):
        for offset in range(len(rows)):
            row = rows[(cycle + offset) % len(rows)]
            _, elapsed, _ = score(row)
            latencies.append(elapsed)
            by_stratum[row['stratum']].append(elapsed)
    gc.enable()
    inference_rss = rss_snapshot()
    serialization_start = time.perf_counter()
    buffer = io.BytesIO()
    torch.save(model.state_dict(), buffer)  # Our own state, write-only in memory; never deserialized.
    serialized_bytes = buffer.tell()
    del buffer
    serialization_ms = (time.perf_counter() - serialization_start) * 1000
    final_rss = rss_snapshot()
    assert process_peak(final_rss) <= protocol['budget']['rss_bytes'], f'Worker VmHWM {process_peak(final_rss)} exceeds {protocol["budget"]["rss_bytes"]}'
    result = {
        'arm': args.arm, 'runtime_versions': versions, 'cpu_affinity_count': len(os.sched_getaffinity(0)),
        'torch_threads': torch.get_num_threads(), 'torch_interop_threads': torch.get_num_interop_threads(),
        'quantized_engine': torch.backends.quantized.engine, 'original_linear_count': len(original_names),
        'quantized_linear_count': len(quantized_names), 'remaining_fp32_linear_count': len(remaining_names),
        'loading_diagnostics': loading_info,
        'scores': scores, 'token_fingerprints': fingerprints, 'untruncated_token_lengths': token_lengths,
        'truncated_pair_count': sum(n > protocol['max_length'] for group in token_lengths for n in group),
        'first_scores': first_scores, 'first_query_latency_ms': first_latency_ms,
        'worker_started_at': started, 'first_at': first_at, 'ready_at': ready_at,
        'worker_peak_rss_bytes': process_peak(final_rss),
        'startup_inference_peak_rss_bytes': process_peak(inference_rss),
        'torch_build_configuration': torch.__config__.show(),
        'rss_accounting': 'VmHWM is authoritative per-exec process peak; ru_maxrss is diagnostic and may be inherited; final peak includes in-memory serialization instrumentation',
        'rss_snapshots': {'first': first_rss, 'ready': ready_rss, 'after_inference': inference_rss, 'after_serialization': final_rss},
        'phase_ms': {'validation': (verified_at - started) * 1000, 'imports': (imported_at - verified_at) * 1000,
                     'tokenizer_and_fp32_load': (loaded_at - imported_at) * 1000,
                     'quantization_and_gc': (converted_at - loaded_at) * 1000,
                     'state_byte_measurement': serialization_ms},
        'state_serialized_bytes': serialized_bytes,
        'timing': {'requests': len(latencies), 'pairs': 4 * len(latencies), 'query_latency_ms': latencies,
                   'mean_query_ms': statistics.mean(latencies), 'p95_query_ms': nearest_rank(latencies, .95),
                   'pairs_per_second': 4 * len(latencies) * 1000 / sum(latencies),
                   'by_stratum': {key: {'requests': len(values), 'mean_query_ms': statistics.mean(values),
                                      'p95_query_ms': nearest_rank(values, .95)} for key, values in by_stratum.items()}}}
    write_json(args.output, result)

if __name__ == '__main__':
    main()
