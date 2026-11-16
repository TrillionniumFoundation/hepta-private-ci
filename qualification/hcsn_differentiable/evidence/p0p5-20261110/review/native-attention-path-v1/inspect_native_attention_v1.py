"""One native CPU attention forward/backward trace, with no optimizer step.

Adapted from the retained cloud attention-cpu-path-review-v4 inspector. Uses an
already completed native v8 checkpoint and the exact first 32 ABC windows.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import subprocess
import sys
import time
import traceback
import zipfile

BASE = Path('/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training')
SOURCE = BASE / 'run-source-v8'
OUT = BASE / 'native-attention-path-v1'
PARENT = BASE / 'campaign-v2/attention-s101-lr0.003'
PREPARED = Path('/home/qian-qi/hepta-hcsn-discriminative-20261109-7e8f70f19cba/execution/data')
PARENT_RESULT_SHA = '83f6d0bb4af2707a1e7257d5eb9b72dbc31ba9ffec8259ad672abbb13269285b'
SOURCE_ZIP_SHA = '288283cae2b2cf4e7b68432e040e643a5e1b00a7de961fc848dd5cf20eb46102'
DATA_SHA = '0eb233da8d0b766c35356ba450d0572f1e6a87a47f1d8a17cd32c2ae6f25a1cb'


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def write(path, data):
    with path.open('x') as stream:
        stream.write(json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + '\n')


def worker():
    started, own_cpu = time.monotonic(), time.process_time()
    report = {'schema': 'hcsn-native-attention-operator-path-v1', 'passed': False,
        'started_utc': datetime.now(timezone.utc).isoformat(), 'scientific_admission': 'HOLD',
        'optimizer_steps': 0, 'confirmation_access': False, 'energy_joules': None,
        'scope': 'single FP64 CPU training-mode forward/backward; instrumentation overhead included; no speed or energy comparison',
        'cloud_predecessor_source_sha256': '9d621145eb29bd463c90b73a3120ea87dfbf5889c2cbdce805dd202c1b625201',
        'driver_sha256': sha(Path(__file__)), 'loaded_parent_result_sha256': PARENT_RESULT_SHA}
    try:
        resource.setrlimit(resource.RLIMIT_AS, (8 * 1024**3, 8 * 1024**3))
        sys.path.insert(0, str(SOURCE / 'proposals/localization-v3'))
        import torch
        from cores import CoreStudyModel, tensor_digest
        from hcsn_study_support import batches, backward_effective_batch, sources
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        assert sha(BASE / 'training-source-v8.zip') == SOURCE_ZIP_SHA
        with zipfile.ZipFile(BASE / 'training-source-v8.zip') as capsule:
            for name in capsule.namelist():
                assert sha(SOURCE / name) == hashlib.sha256(capsule.read(name)).hexdigest()
        assert sha(PARENT / 'result.json') == PARENT_RESULT_SHA
        parent = json.loads((PARENT / 'result.json').read_bytes())
        assert parent['status'] == 'completed_development' and parent['source_unchanged']
        assert parent['common_weights_unchanged'] and parent['training_adequacy_established']
        checkpoint = PARENT / 'best.pt'
        checkpoint_sha = sha(checkpoint)
        assert checkpoint_sha == parent['best_checkpoint_sha256']
        state = torch.load(checkpoint, weights_only=False)
        assert state['model_configuration'] == parent['model_configuration']
        model = CoreStudyModel(**state['model_configuration'])
        assert model.arm == 'attention' and model.width == 16 and model.learn_core_adapter and model.freeze_shared
        model.load_state_dict(state['model'])
        source_before = sources(model)
        assert source_before == parent['source_before'] == parent['source_after']
        assert tensor_digest(model.frontend) == parent['initial_frontend_sha256']
        assert tensor_digest(model.head) == parent['initial_head_sha256']
        assert sha(PREPARED / 'data-manifest.json') == DATA_SHA
        manifest = json.loads((PREPARED / 'data-manifest.json').read_bytes())
        selected = [row for row in manifest['episodes'] if row['partition'] == 'train'][:32]
        episodes = []
        for row in selected:
            path = PREPARED / row['path']
            assert sha(path) == row['sha256']
            episode = json.loads(path.read_bytes())
            assert episode['partition'] == 'train' and 0 < len(episode['y']) <= 256
            episodes.append(episode)
        ids, x, dt, y = next(batches(episodes, list(range(32)), 32))
        assert list(x.shape) == [32, 256, 25] and x.dtype == torch.float64
        assert sha(PREPARED / 'frontend.json') == manifest['frontend_sha256']
        frontend = json.loads((PREPARED / 'frontend.json').read_bytes())
        counts = torch.tensor([frontend['class_counts'][str(i)] for i in range(11)], dtype=torch.float64)
        assert int(counts.sum()) == 89216
        weights = counts.rsqrt(); weights /= weights.mean()
        torch.save({'x': x, 'dt': dt, 'y': y, 'episode_ids': ids, 'class_weights': weights}, OUT / 'fixed-abc-input.pt')
        shutil.copyfile(checkpoint, OUT / 'used-best.pt')
        shutil.copyfile(PARENT / 'result.json', OUT / 'parent-result.json')
        masks, outputs = [], []

        def before_attention(module, args, kwargs):
            # Store references only; tensor inspection occurs after profiling.
            masks.append({'query_shape': list(args[0].shape), 'attn_mask': kwargs.get('attn_mask'),
                'key_padding_mask': kwargs.get('key_padding_mask'), 'is_causal': kwargs.get('is_causal'),
                'need_weights': kwargs.get('need_weights')})

        handle = model.core.layer.self_attn.register_forward_pre_hook(before_attention, with_kwargs=True)
        output_handle = model.register_forward_hook(lambda module, args, result: outputs.append(result))
        model.train()
        initial_digest = tensor_digest(model)
        model.zero_grad(set_to_none=True)
        tick, cpu_tick = time.monotonic(), time.process_time()
        with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU],
                record_shapes=True, profile_memory=True) as prof:
            with torch.profiler.record_function('exact_v8_attention_full32_forward_backward_no_step'):
                receipt = backward_effective_batch(model, x, dt, y, weights, micro_batch_size=32)
        profile_wall, profile_cpu = time.monotonic() - tick, time.process_time() - cpu_tick
        handle.remove(); output_handle.remove()
        assert len(outputs) == len(masks) == 1 and torch.isfinite(outputs[0]).all()
        trainable = [(name, p) for name, p in model.named_parameters() if p.requires_grad]
        assert all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for _, p in trainable)
        assert tensor_digest(model) == initial_digest and sha(checkpoint) == checkpoint_sha
        assert sha(PARENT / 'result.json') == PARENT_RESULT_SHA and source_before == sources(model)
        mask = masks[0]['attn_mask']
        expected = torch.ones(256, 256, dtype=torch.bool).triu(1)
        assert mask is not None and list(mask.shape) == [256, 256]
        if mask.dtype == torch.bool:
            mask_matches = torch.equal(mask, expected)
        else:
            mask_matches = bool(torch.isneginf(mask[expected]).all() and (mask[~expected] == 0).all())
        assert mask_matches and masks[0]['key_padding_mask'] is None
        torch.save({'attention_mask': mask, 'valid_label_mask': y >= 0}, OUT / 'actual-masks.pt')
        mask_observation = {k:v for k,v in masks[0].items() if k not in ('attn_mask', 'key_padding_mask')}
        mask_observation.update(dtype=str(mask.dtype), shape=list(mask.shape), strict_causal_upper_triangle=True,
            key_padding_mask=None, mask_tensor_sha256=hashlib.sha256(mask.contiguous().numpy().tobytes()).hexdigest())
        prof.export_chrome_trace(str(OUT / 'trace.json'))
        operators = [{'operator': e.key, 'count': e.count, 'input_shapes': e.input_shapes,
            'self_cpu_time_us': e.self_cpu_time_total, 'cpu_time_us': e.cpu_time_total,
            'self_cpu_memory_bytes': e.self_cpu_memory_usage, 'cpu_memory_bytes': e.cpu_memory_usage}
            for e in prof.key_averages(group_by_input_shape=True)]
        write(OUT / 'operators.json', operators)
        names = {item['operator'] for item in operators}
        selected_ops = [item for item in operators if 'scaled_dot_product' in item['operator'] or
            item['operator'] in {'aten::mm', 'aten::addmm', 'aten::bmm', 'aten::matmul', 'aten::linear'}]
        cpuinfo = Path('/proc/cpuinfo').read_text()
        cpu_summary = {}
        for line in cpuinfo.splitlines():
            key, _, value = line.partition(':')
            if key.strip() in ('vendor_id', 'model name', 'cpu family', 'model', 'stepping', 'flags'):
                cpu_summary.setdefault(key.strip(), value.strip())
        report.update(passed=True, python=sys.version, torch=torch.__version__, torch_git=torch.version.git_version,
            platform=platform.platform(), hostname=platform.node(), cpu=cpu_summary,
            affinity=sorted(os.sched_getaffinity(0)), load_average=os.getloadavg(),
            torch_build_configuration=torch.__config__.show(), torch_parallel_info=torch.__config__.parallel_info(),
            cpu_capability=torch.backends.cpu.get_cpu_capability(), threads=torch.get_num_threads(),
            interop_threads=torch.get_num_interop_threads(), model_configuration=state['model_configuration'],
            checkpoint_sha256=checkpoint_sha, model_tensor_sha256=initial_digest, model_unchanged=True,
            source_before=source_before, source_after=sources(model), source_unchanged=True,
            source_capsule_sha256=SOURCE_ZIP_SHA, data_manifest_sha256=DATA_SHA, selected_episodes=selected,
            input_shape=list(x.shape), output_shape=list(outputs[0].shape), valid_events=int((y >= 0).sum()),
            input_file_sha256=sha(OUT / 'fixed-abc-input.pt'), mask_observation=mask_observation,
            dtype=str(x.dtype), device=str(x.device), trainable_gradient_tensors=len(trainable), backward_receipt=receipt,
            profiled_forward_backward_wall_seconds=profile_wall, profiled_forward_backward_cpu_seconds=profile_cpu,
            observed_operators=selected_ops, cpu_flash_forward_observed='aten::_scaled_dot_product_flash_attention_for_cpu' in names,
            cpu_flash_backward_observed='aten::_scaled_dot_product_flash_attention_for_cpu_backward' in names,
            trace_sha256=sha(OUT / 'trace.json'), operators_sha256=sha(OUT / 'operators.json'),
            BLAS_scope='actual MKL_VERBOSE stdout retained; ATen trace plus runtime/build data do not identify a particular assembly microkernel',
            optimized_GPU_baseline_established=False, comparative_speed_or_energy_claim=False)
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        report.update(worker_wall_seconds_including_imports_and_profiler=time.monotonic() - started,
            worker_cpu_delta_seconds=time.process_time() - own_cpu,
            peak_rss_bytes_linux=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            finished_utc=datetime.now(timezone.utc).isoformat())
        write(OUT / 'worker-result.json', report)
        print(json.dumps({k:report.get(k) for k in ('passed', 'error', 'cpu_flash_forward_observed',
            'cpu_flash_backward_observed', 'valid_events', 'worker_wall_seconds_including_imports_and_profiler')}), flush=True)
    return 0 if report['passed'] else 2


def main():
    OUT.mkdir(exist_ok=False)
    started, own_cpu = time.monotonic(), time.process_time()
    report = {'schema': 'hcsn-native-attention-profile-controller-v1', 'status': 'started',
        'started_utc': datetime.now(timezone.utc).isoformat(), 'optimizer_steps': 0,
        'new_training_fit': False, 'scientific_admission': 'HOLD', 'energy_joules': None,
        'driver_sha256': sha(Path(__file__)), 'one_worker_only': True, 'automatic_retry': False}
    write(OUT / 'PLAN.json', {'source': str(SOURCE), 'source_capsule_sha256': SOURCE_ZIP_SHA,
        'parent': str(PARENT), 'parent_result_sha256': PARENT_RESULT_SHA, 'manifest_sha256': DATA_SHA,
        'batch': 'first32 ABC episodes in exact manifest order; preserve padded256 window',
        'dtype': 'float64', 'device': 'cpu', 'threads': 1, 'forward_backward_calls': 1,
        'optimizer_steps': 0, 'MKL_VERBOSE': '1', 'scope': 'native dispatch evidence only'})
    try:
        argv = [sys.executable, '-B', str(Path(__file__).resolve()), '--worker']
        tick = time.monotonic()
        with (OUT / 'worker.stdout').open('xb') as stdout, (OUT / 'worker.stderr').open('xb') as stderr:
            try:
                result = subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=120,
                    env=dict(os.environ, OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
                             MKL_VERBOSE='1', PYTHONDONTWRITEBYTECODE='1'))
                report['returncode'] = result.returncode
            finally:
                report['whole_worker_process_wall_seconds'] = time.monotonic() - tick
        worker_report = json.loads((OUT / 'worker-result.json').read_bytes())
        report['worker_result_sha256'] = sha(OUT / 'worker-result.json')
        raw = (OUT / 'worker.stdout').read_text(errors='replace')
        verbose = [line for line in raw.splitlines() if line.startswith('MKL_VERBOSE')]
        write(OUT / 'blas-verbose-observations.json', {'raw_stdout_sha256': sha(OUT / 'worker.stdout'),
            'mkl_verbose_lines': verbose, 'dgemm_lines': [line for line in verbose if 'DGEMM' in line],
            'interpretation': 'actual logged MKL calls/configuration; exact assembly microkernel remains unidentified'})
        assert result.returncode == 0 and worker_report['passed']
        report.update(status='native_dispatch_evidence_completed',
            cpu_flash_forward_observed=worker_report.get('cpu_flash_forward_observed'),
            cpu_flash_backward_observed=worker_report.get('cpu_flash_backward_observed'),
            mkl_verbose_lines=len(verbose), mkl_dgemm_lines=sum('DGEMM' in line for line in verbose))
    except Exception:
        report.update(status='failed_no_blind_retry', error=traceback.format_exc())
    finally:
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        report.update(children_cpu_seconds=usage.ru_utime + usage.ru_stime,
            controller_cpu_seconds=time.process_time() - own_cpu,
            whole_controller_wall_seconds=time.monotonic() - started,
            finished_utc=datetime.now(timezone.utc).isoformat(),
            cost_scope='controller wall and child full-process wall overlap; one child rusage includes imports/profiler/serialization, no optimizer step')
        write(OUT / 'RESULT.json', report)
        print(json.dumps(report, sort_keys=True), flush=True)
    return 0 if report['status'] == 'native_dispatch_evidence_completed' else 2


if __name__ == '__main__':
    raise SystemExit(worker() if '--worker' in sys.argv else main())
