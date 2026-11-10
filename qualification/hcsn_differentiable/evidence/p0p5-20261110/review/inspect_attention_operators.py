"""Identify actual CPU FP64 attention operators, not comparative timing."""
from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import platform
import resource
import sys
import time
import traceback

ROOT = Path('/workspace/scratch/c385a7439f8e')
SOURCE = ROOT/'v6-local-validation/source'
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(SOURCE/'proposals/localization-v3'))
import torch
from cores import CoreStudyModel, tensor_digest
from hcsn_study_support import batches

sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
load = lambda p: json.loads(Path(p).read_text())
started = time.perf_counter()
report = {'schema': 'hcsn-independent-attention-cpu-operator-path-v4', 'passed': False,
          'created_utc': datetime.now(timezone.utc).isoformat(),
          'BLAS_verbose_requested': 'MKL_VERBOSE=1 in process environment', 'prior_successful_profile': 'attention-cpu-path-review-v3',
          'driver_sha256': sha(Path(__file__)), 'scientific_admission': 'HOLD',
          'supersedes': {'attempts': ['attention-cpu-path-review-v1', 'attention-cpu-path-review-v2'], 'reason': 'v1 incorrectly required each window to have full length instead of permitting actual padding. v2 used the filename profile.py, which shadowed the standard-library profile module and re-executed the script during a library import. Neither attempt produced attention-operator evidence.'},
          'scope': 'One full-batch CPU FP64 training-mode forward and backward operator trace; not a speed/energy comparison or sufficient training.'}
try:
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    source_before = {str(p.relative_to(SOURCE)): sha(p) for p in SOURCE.rglob('*.py')}
    prepared = ROOT/'uci-cloud-prepared-v1'
    manifest = load(prepared/'data-manifest.json')
    assert sha(prepared/'data-manifest.json') == '0eb233da8d0b766c35356ba450d0572f1e6a87a47f1d8a17cd32c2ae6f25a1cb'
    selected = [r for r in manifest['episodes'] if r['partition'] == 'train'][:32]
    episodes = []
    for row in selected:
        path = prepared/row['path']
        assert sha(path) == row['sha256']
        episode = load(path)
        assert episode['partition'] == 'train' and 0 < len(episode['y']) <= 256
        episodes.append(episode)
    _, x, dt, y = next(batches(episodes, list(range(32)), 32))
    assert list(x.shape) == [32, 256, 25] and x.dtype == torch.float64
    frontend = load(prepared/'frontend.json')
    assert sha(prepared/'frontend.json') == manifest['frontend_sha256']
    counts = torch.tensor([frontend['class_counts'][str(i)] for i in range(11)], dtype=torch.float64)
    weights = counts.rsqrt(); weights /= weights.mean()
    model = CoreStudyModel('attention', width=16, seed=101, freeze_shared=True, learn_core_adapter=True)
    model.train()
    initial_digest = tensor_digest(model)
    model.zero_grad(set_to_none=True)
    with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU], record_shapes=True, profile_memory=True) as prof:
        with torch.profiler.record_function('full_causal_attention_forward_and_weighted_backward'):
            logits = model(x, dt)
            loss = torch.nn.functional.cross_entropy(logits[y >= 0], y[y >= 0], weight=weights)
            loss.backward()
    assert torch.isfinite(logits).all() and torch.isfinite(loss)
    trainable = [(n, p) for n, p in model.named_parameters() if p.requires_grad]
    assert all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for _, p in trainable)
    assert tensor_digest(model) == initial_digest
    prof.export_chrome_trace(str(OUT/'trace.json'))
    events = [{'operator': event.key, 'count': event.count, 'input_shapes': event.input_shapes,
               'self_cpu_time_us': event.self_cpu_time_total, 'cpu_time_us': event.cpu_time_total,
               'self_cpu_memory_bytes': event.self_cpu_memory_usage, 'cpu_memory_bytes': event.cpu_memory_usage}
              for event in prof.key_averages(group_by_input_shape=True)]
    (OUT/'operators.json').write_text(json.dumps(events, indent=2, allow_nan=False)+'\n')
    names = {r['operator'] for r in events}
    sdpa = [r for r in events if 'scaled_dot_product' in r['operator'] or 'attention' in r['operator'].lower()]
    linear = [r for r in events if r['operator'] in {'aten::mm', 'aten::addmm', 'aten::bmm', 'aten::matmul', 'aten::linear'}]
    if 'aten::_scaled_dot_product_flash_attention_for_cpu' in names:
        path = 'CPU fused scaled-dot-product flash-attention operator observed'
    elif 'aten::_scaled_dot_product_attention_math' in names:
        path = 'scaled-dot-product attention math operator observed'
    else:
        path = 'inspect retained operator names; no declared SDPA path classification'
    torch_sources = {inspect.getsourcefile(cls) for cls in [torch.nn.MultiheadAttention, torch.nn.TransformerEncoderLayer]}
    torch_sources.add(inspect.getsourcefile(torch.nn.functional.multi_head_attention_forward))
    report.update(passed=True, torch=torch.__version__, python=sys.version,
                  platform=platform.platform(), machine=platform.machine(),
                  cpu_capability=torch.backends.cpu.get_cpu_capability(),
                  torch_build_configuration=torch.__config__.show(),
                  threads=torch.get_num_threads(), interop_threads=torch.get_num_interop_threads(),
                  training=True, dtype=str(x.dtype), device=str(x.device),
                  input_shape=list(x.shape), output_shape=list(logits.shape),
                  width=16, heads=2, head_dimension=8, feedforward_width=64,
                  dropout=0.0, causal_mask='explicit boolean strictly upper triangular',
                  model_tensor_sha256=initial_digest, source_before=source_before,
                  source_after={str(p.relative_to(SOURCE)): sha(p) for p in SOURCE.rglob('*.py')},
                  torch_python_sources={str(p): sha(p) for p in torch_sources},
                  data_manifest_sha256=sha(prepared/'data-manifest.json'), episodes=selected,
                  valid_events=int((y >= 0).sum()), loss=float(loss.detach()),
                  trainable_gradient_tensors=len(trainable), detected_path=path,
                  attention_events=sdpa, linear_events=linear,
                  BLAS_interpretation='aten mm/addmm/etc are dispatch-level evidence. Build configuration identifies available BLAS; this profiler does not identify the exact vendor microkernel called.',
                  optimized_GPU_baseline_established=False, comparative_speed_or_energy_claim=False,
                  trace_sha256=sha(OUT/'trace.json'), operators_sha256=sha(OUT/'operators.json'),
                  source_unchanged=source_before == {str(p.relative_to(SOURCE)): sha(p) for p in SOURCE.rglob('*.py')})
    assert report['source_unchanged']
except Exception:
    report['error'] = traceback.format_exc()
report['wall_seconds_including_profiler_overhead'] = time.perf_counter() - started
report['peak_rss_bytes_linux'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
(OUT/'RESULT.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
print(json.dumps({k: report.get(k) for k in ['passed', 'detected_path', 'input_shape', 'valid_events', 'wall_seconds_including_profiler_overhead', 'error']}), flush=True)
raise SystemExit(0 if report['passed'] else 1)
