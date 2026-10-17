"""Frozen original EmbeddingGemma 2 (text only) -> 384D shared-Cell research.

No model is selected, no mutable runtime is accessed and no heldout target is
available in this producer. Physical runs require original pinned weights.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import statistics
import struct
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / 'stem-optimal-v1'))
sys.path.insert(0, str(ROOT / 'stem-optimal-v3'))

REPO = 'google/embeddinggemma-2'
REVISION = '914f7f89142e33e77833254d9c9b90c3cef7303b'
WEIGHT_SHA = '197a32965d4b1105faf060417baa899e193fb73cd401f42ec9295234d5553d79'
WEIGHT_SIZE = 1_488_915_288
SCHEMA = 'hepta.stem.embeddinggemma2.real-frozen.v4'
COHORT = 'hard-charge-four-intents-v3'
PROJECTION = 'adjacent_pair_mean_l2_768_to_384_v1'
ARM = 'eg2_text_only_768to384'
STATUS = 'HOLD_NO_GO'


def require(ok, why):
    if not ok:
        raise ValueError(why)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def _unique_pairs(pairs):
    out = {}
    for key, value in pairs:
        require(key not in out, 'duplicate JSON key')
        out[key] = value
    return out


def read_json(path: Path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 5_000_000,
            'invalid or oversized source')
    return json.loads(path.read_text('utf-8'), object_pairs_hook=_unique_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def write_private(path: Path, value):
    require(path.parent.is_dir() and not path.parent.is_symlink() and not path.is_symlink(),
            'unsafe destination')
    payload = canonical(value) + b'\n'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'wb') as out:
        out.write(payload)
        out.flush()
        os.fsync(out.fileno())


def check_source(source):
    # V3 verifies exact label-free heldout rows and source hashes against its plan.
    import stem_hard_charge_v3 as v3
    v3.verify_source(source)
    require(source['cohort'] == COHORT and len(source['train']) == 64
            and len(source['heldout']) == 32, 'wrong original case roster')
    require(all('label' not in row for row in source['heldout']), 'heldout label leak')


def verify_weight_file(path: Path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size == WEIGHT_SIZE,
            'not original pinned safetensors size')
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1_048_576), b''):
            h.update(block)
    require(h.hexdigest() == WEIGHT_SHA, 'original safetensors SHA mismatch')
    return h.hexdigest()


def project_768_to_384(x):
    """Fixed adjacent-pair projection, not MRL 384 or an optimal EG2 embedding."""
    import torch
    import torch.nn.functional as F
    require(type(x) is torch.Tensor and x.ndim == 2 and x.shape[-1] == 768,
            'expected physical 768D representations')
    require(bool(torch.isfinite(x).all()), 'nonfinite native embedding')
    y = x.float().contiguous().view(x.shape[0], 384, 2).mean(-1)
    require(bool((y.square().sum(-1) > 1e-12).all()), 'degenerate projected vector')
    return F.normalize(y, p=2, dim=-1)


def _load_text_encoder():
    import torch
    from huggingface_hub import snapshot_download
    from sentence_transformers import SentenceTransformer
    # No implicit main branch, custom remote Python, pickle weights or fp16.
    path = Path(snapshot_download(
        repo_id=REPO, revision=REVISION,
        allow_patterns=['*.json', '*.jinja', '*.safetensors', '*.model', '*.txt'],
        ignore_patterns=['*.bin', '*.pt', '*.pkl', '*.py']))
    verify_weight_file(path / 'model.safetensors')
    model = SentenceTransformer(str(path), trust_remote_code=False,
                                config_kwargs={'vision_config': None, 'audio_config': None},
                                model_kwargs={'torch_dtype': torch.float32}, device='cpu')
    model.eval()
    require(len(model) >= 1, 'no pretrained Transformer installed')
    native = getattr(model[0], 'auto_model', None)
    config = getattr(native, 'config', None)
    require(config is not None and getattr(config, 'vision_config', 'missing') is None
            and getattr(config, 'audio_config', 'missing') is None,
            'optional vision/audio towers were not demonstrably disabled')
    parameters = list(model.parameters())
    count = sum(t.numel() for t in parameters)
    require(200_000_000 <= count <= 350_000_000
            and all(t.dtype == torch.float32 for t in parameters),
            'not an authentic float32 text-only pretrained model')
    import material_census_v5 as source_census
    audit = source_census.verify_source_value_coverage(
        model, path / 'model.safetensors', expected_sha=WEIGHT_SHA)
    require(audit['runtime_parameter_elements'] == count and
            audit['source_value_coverage_verified'] is True,
            'model has a parameter without original checkpoint bytes')
    return model, audit


def physical_embedding(texts, model):
    """Count actual model[0].forward via hook; report API batches separately."""
    import torch
    calls = [0]
    def on_forward(_module, _inputs, _output):
        calls[0] += 1
    hook = model[0].register_forward_hook(on_forward)
    chunks = []
    try:
        with torch.inference_mode():
            for start in range(0, len(texts), 16):
                out = model.encode(texts[start:start+16], prompt_name='Classification',
                                   batch_size=16, normalize_embeddings=True,
                                   convert_to_tensor=True, show_progress_bar=False)
                require(type(out) is torch.Tensor and out.ndim == 2 and
                        out.shape == (min(16, len(texts)-start), 768) and
                        bool(torch.isfinite(out).all()), 'invalid actual encoder forward')
                chunks.append(project_768_to_384(out.detach().to('cpu')))
    finally:
        hook.remove()
    require(calls[0] == len(chunks), 'unaccounted pretrained forward count')
    return torch.cat(chunks), calls[0]


def physical_fleet(feature, n=4096, active=32, repetitions=64):
    """Actual individually allocated Head tensors and batched math; not 4096 users."""
    import torch
    require(n in (64, 256, 1024, 4096) and active <= n and active == 32,
            'fleet profile out of bounds')
    require(feature.shape == (384,) and bool(torch.isfinite(feature).all()),
            'real feature required')
    torch.manual_seed(20261017)
    a = torch.randn(n, 8, 384, dtype=torch.float32) * 0.01
    b = torch.randn(n, 384, 8, dtype=torch.float32) * 0.01
    gate = torch.randn(n, 384, dtype=torch.float32) * 0.01
    gate_bias = torch.zeros(n, dtype=torch.float32)
    out = torch.randn(n, 384, dtype=torch.float32) * 0.01
    out_bias = torch.zeros(n, dtype=torch.float32)
    tensors = (a, b, gate, gate_bias, out, out_bias)
    require(sum(t.numel() for t in tensors) == 6914*n, 'wrong Head inventory')
    indices = torch.arange(active)* (n // active)
    def step():
        aa, bb, gg, gb, oo, ob = (t[indices] for t in tensors)
        low = torch.einsum('d,crd->cr', feature, aa)
        res = torch.einsum('cr,cdr->cd', low, bb)
        gt = torch.sigmoid(gg@feature+gb)
        z = feature.unsqueeze(0) + gt.unsqueeze(1)*res/8.0
        logits = (z*oo).sum(-1)+ob
        require(bool(torch.isfinite(logits).all()), 'nonfinite Head output')
        return logits
    with torch.inference_mode():
        for _ in range(8):
            step()
        elapsed = []
        for _ in range(repetitions):
            start = time.perf_counter_ns()
            logits = step()
            elapsed.append((time.perf_counter_ns()-start)/1e6)
    return {'fleet_cell_count':n, 'active_heads_per_call':active,
            'head_parameter_count':6914*n, 'head_weight_bytes_fp32':6914*n*4,
            'timed_batched_calls':len(elapsed), 'head_batch_p95_ms':sorted(elapsed)[math.ceil(.95*len(elapsed))-1],
            'head_batch_p99_ms':sorted(elapsed)[math.ceil(.99*len(elapsed))-1],
            'last_logit_sha256':digest(struct.pack('<32f', *logits.detach().cpu().tolist())),
            'real_pretrained_input_feature':True, 'complete_request_p99':None,
            'energy_joules':None, 'target_host_attested':False}


def physical_run(source):
    check_source(source)
    import torch
    import stem_candidate_v1 as base
    torch.set_num_threads(2)
    begin, cpu = time.perf_counter(), time.process_time()
    model, original_parameter_audit = _load_text_encoder()
    actual_loaded_parameters = sum(p.numel() for p in model.parameters())
    load_wall = time.perf_counter()-begin
    fittexts = [r['text'] for r in source['train']]
    heldtexts = [r['text'] for r in source['heldout']]
    encode_start = time.perf_counter()
    feats, fwd = physical_embedding(fittexts + heldtexts, model)
    encoder_wall = time.perf_counter()-encode_start
    require(feats.shape == (96,384) and fwd == 6, 'physical feature mismatch')
    trained = base._torch_head_training(feats[:64], [r['label'] for r in source['train']],
                                        feats[64:], config={'seed':17,'steps':100,
                                        'learning_rate':.006,'per_cell_parameters':6914,'cells':4})
    import train_only_centroid_v5 as calibrated_baseline
    train_only_control = calibrated_baseline.calculate(
        feats[:64], [r['label'] for r in source['train']],
        feats[64:], source['heldout'])
    import fit_witness_v7
    fit_witness = fit_witness_v7.build(
        source, feats[:64], train_only_control, source_weight_sha256=WEIGHT_SHA,
        projection=PROJECTION)
    fleet = physical_fleet(feats[64])
    require(trained['total_head_parameters'] == 27656 and trained['steps'] == 100,
            'invalid trained Head budget')
    return {
        'schema':SCHEMA, 'cohort':COHORT,'candidate':ARM,
        'source_plan_sha256':source['source_plan_sha256'],
        'model_repo':REPO,'model_revision':REVISION,'actual_weight_sha256':WEIGHT_SHA,
        'model_precision':'fp32_cpu', 'actual_loaded_parameters':actual_loaded_parameters,
        'original_parameter_audit':original_parameter_audit,
        'native_width':768,'projected_width':384,
        'projection':PROJECTION,'prompt_name':'Classification',
        'initial_head_sha256':trained['initial_head_sha256'],
        'trained_head_sha256':trained['trained_head_sha256'],
        'head_parameters':trained['total_head_parameters'],'optimizer_steps':trained['steps'],
        'rows':[{'case_id':r['case_id'], 'source_sha256':r['source_sha256'],
                 'scores':{name:trained[name][i] for name in ('learned','frozen_init','centroid')}}
                for i,r in enumerate(source['heldout'])],
        'cost':{'physical_encoder_sequences':96,'physical_encoder_forward_batches':fwd,
                'model_load_seconds':load_wall,'embedding_seconds':encoder_wall,
                'head_train_seconds':trained['training_wall_seconds'],
                'complete_wall_seconds':time.perf_counter()-begin,
                'complete_cpu_seconds':time.process_time()-cpu,
                'maxrss_bytes_linux_unattested':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                'energy_joules':None,'complete_request_p99_ms':None},
        'fleet':fleet,'train_only_centroid':train_only_control,
        'fit_feature_witness_sha256':digest(canonical(fit_witness)),
        'future_windows':0,'human_verified_new_sources':0,
        'ndu_task_utility_qualified':False,'cell_split_authorized':False,
        'production_authorized':False,'authority':'DENY_ALL','disposition':STATUS,
    }, fit_witness


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--fit-witness-output',type=Path,required=True)
    args=p.parse_args()
    receipt,fit_witness=physical_run(read_json(args.source))
    # Create-only two-file set: an interrupted write is NOT an admitted receipt.
    # Both SHA-sidecars are checked on the separate original-label runner.
    write_private(args.fit_witness_output,fit_witness)
    write_private(args.output,receipt)

if __name__ == '__main__':
    main()
