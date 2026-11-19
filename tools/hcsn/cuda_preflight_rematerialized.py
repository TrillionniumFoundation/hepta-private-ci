#!/usr/bin/env python3
"""Candidate-only rematerialized B full-shape CUDA step; not a 170-run result.

Root must separately establish original full-shape B OOM and the fixed
CPU/CUDA parity receipts before launching this probe. This script pins and
executes the candidate; it does not certify those prior eligibility gates.
"""
import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import tempfile
import time
import traceback


SEGMENT_STEPS = 1
BASE_PREFLIGHT_SHA256 = '70331f392c9695e0522da52817b3511b544304a6f4e23a169a016a07ea9f1285'
CANDIDATE_PINS = {
    'qualification/hcsn/rematerialization.py': 'ea0be5db010342050437fc5aa5d0458b8601b744670a4d7e3abd84cfbc52ae38',
    'CANDIDATE.json': 'd864fdb4819a7f21c7e1a8178686b6bf9ec82df92cf88609240faa918876f51b',
    'check_rematerialization.py': '664a508d7e1c70ee81efe077225b5f4f751bb790efc83cecfc6f1494a09bb509',
}


class Unavailable(RuntimeError):
    """The requested CUDA runtime is absent."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(root):
    return {str(p.relative_to(root)): digest(p.read_bytes())
            for p in sorted(root.rglob('*.py'))}


def publish(path, record, *, replace=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name+'.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(record, stream, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--remat-root', type=Path, required=True)
    parser.add_argument('--model', choices=('population_flux', 'population_flux_no_recovery'), default='population_flux')
    parser.add_argument('--task', choices=('delayed_recall', 'adding'), default='delayed_recall')
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--device', default='cuda:0')
    parser.add_argument('--max-memory-fraction', type=float)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output already exists; use a new receipt path')
    root = args.repo_root.resolve()/'qualification'/'hcsn'
    config_path = root/'configs'/'full.json'
    record = dict(schema_version=1, status='running', model=args.model, task=args.task,
                  seed=args.seed, pid=os.getpid(), started_utc=datetime.now(timezone.utc).isoformat(),
                  probe_sha256=digest(Path(__file__).read_bytes()), repo_root=str(args.repo_root.resolve()),
                  scope='candidate-only rematerialized B; one random-initialized FP32 CUDA training step, same registered first batch',
                  base_preflight_sha256=BASE_PREFLIGHT_SHA256,
                  comparison_scope='candidate only; no simultaneous original full-shape graph',
                  rematerialization=dict(segment_steps=SEGMENT_STEPS, use_reentrant=False,
                                         preserve_rng_state=True, full_bptt=True),
                  eligibility_checked_by_probe=False,
                  required_external_eligibility=['original full-shape B OOM', 'fixed CPU and CUDA parity receipts passed'],
                  candidate_expected_sha256=CANDIDATE_PINS,
                  counts_toward_170_runs=False, heldout_evaluated=False, optimizer_steps_completed=0,
                  training_examples_submitted=0, training_tokens_submitted=0, peak_reset_before_step=False,
                  stage='initialization', stages={}, finite={}, software={}, hardware={},
                  memory_fraction=args.max_memory_fraction,
                  memory_limit_scope='PyTorch process allocator only; not GPU reservation or a limit on external CUDA allocations',
                  memory_scope='training split and model resident; one Adam step; no validation/test tensors or best-state copies',
                  energy={'joules_by_physical_counter': None, 'missing_reason': 'measurement not started'})
    publish(args.output, record, replace=False)
    torch, device, meter, initialized = None, None, None, False
    start = time.perf_counter()

    def interrupted(signum, frame):
        raise InterruptedError(f'received signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)

    @contextmanager
    def stage(name, sync=True):
        record['stage'] = name
        publish(args.output, record)
        began, outcome = time.perf_counter(), 'failed'
        try:
            yield
            if sync:
                torch.cuda.synchronize(device)
            outcome = 'completed'
        finally:
            record['stages'][name] = dict(status=outcome, seconds=time.perf_counter()-began)

    try:
        if args.max_memory_fraction is not None and not 0 < args.max_memory_fraction <= 1:
            raise ValueError('memory fraction must be in (0, 1]')
        config_bytes = config_path.read_bytes()
        config = json.loads(config_bytes)
        record.update(config=config, config_sha256=digest(config_bytes), source_files_sha256=snapshot(root))
        expected_source = '13860b933a93966e880e64840efa0ac26b70ab62cbe7e38bf71587575d9831a3'
        expected_config = '7fa3d05b8c04a918043afdfa1c266a17beccb814351258d0555a753baf13777a'
        actual_source = digest(json.dumps(record['source_files_sha256'], sort_keys=True, separators=(',', ':')).encode())
        record.update(expected_source_map_sha256=expected_source, actual_source_map_sha256=actual_source,
                      expected_config_sha256=expected_config, base_commit='28a61d14ea7d4c3b3c515ab57b29c98de22e5673')
        if actual_source != expected_source or record['config_sha256'] != expected_config:
            raise ValueError('source or full config differs from pinned baseline')
        expected = dict(batch_size=64, length=64, hidden_size=64, data_seed=271828, train_count=4096, train_steps=400)
        if any(config.get(k) != v for k, v in expected.items()):
            raise ValueError('full.json differs from frozen full-shape/data/budget configuration')
        if args.seed not in config['seeds'] or args.task not in config['tasks'] or args.model not in config['models']:
            raise ValueError('request is not in the registered matrix')
        candidate_root = args.remat_root.resolve()
        record['candidate_files_sha256'] = {name: digest((candidate_root/name).read_bytes())
                                            for name in CANDIDATE_PINS}
        record['candidate_pins_valid'] = record['candidate_files_sha256'] == CANDIDATE_PINS
        if not record['candidate_pins_valid']:
            raise ValueError('candidate module, manifest or checker differs from frozen pins')
        sys.path.insert(0, str(args.repo_root.resolve()))
        for package in ('torch', 'numpy', 'scipy', 'ncps', 'mamba-ssm', 'triton', 'causal-conv1d', 'nvidia-ml-py'):
            try:
                record['software'][package] = metadata.version(package)
            except metadata.PackageNotFoundError:
                record['software'][package] = None
        import torch
        record['software'].update(python=sys.version, platform=platform.platform(), cuda_runtime=torch.version.cuda)
        record['hardware'].update(cuda_available=torch.cuda.is_available(), cuda_device_count=torch.cuda.device_count())
        device = torch.device(args.device)
        if device.type != 'cuda':
            raise ValueError('CUDA is required; no CPU fallback')
        if not torch.cuda.is_available():
            raise Unavailable('CUDA requested but unavailable; no CPU fallback')
        with stage('cuda_setup', sync=False):
            torch.cuda.set_device(device)
            initialized = True
            if args.max_memory_fraction is not None:
                torch.cuda.set_per_process_memory_fraction(args.max_memory_fraction, device)
            props = torch.cuda.get_device_properties(device)
            uuid = str(props.uuid) if getattr(props, 'uuid', None) is not None else None
            record['hardware'].update(device=str(device), name=props.name, uuid=uuid,
                                      capability=[props.major, props.minor], total_memory_bytes=props.total_memory)
            try:
                if uuid is None:
                    raise RuntimeError('CUDA did not expose a UUID; refusing ordinal-based NVML mapping')
                info = subprocess.run(['nvidia-smi', '-i', uuid, '--query-gpu=uuid,driver_version',
                                       '--format=csv,noheader'], capture_output=True, text=True, timeout=15, check=True)
                record['hardware']['nvidia_smi_uuid_driver'] = info.stdout.strip()
            except Exception as exc:
                record['hardware']['driver_missing_reason'] = f'{type(exc).__name__}: {exc}'
        from qualification.hcsn import baselines, benchmark
        if Path(baselines.__file__).resolve().parent != root or Path(benchmark.__file__).resolve().parent != root:
            raise RuntimeError('imported research package is outside requested repository')
        candidate_path = candidate_root/'qualification/hcsn/rematerialization.py'
        spec = importlib.util.spec_from_file_location('qualification.hcsn.rematerialization', candidate_path)
        candidate_module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = candidate_module
        spec.loader.exec_module(candidate_module)
        torch.set_num_threads(config['cpu_threads'])
        torch.use_deterministic_algorithms(True, warn_only=True)
        torch.manual_seed(args.seed)
        torch.cuda.manual_seed_all(args.seed)
        with stage('construction'):
            encoder = candidate_module.RematerializedPopulationFluxEncoder(
                2, config['hidden_size'], dt=config['dt'],
                recovery=args.model == 'population_flux', segment_steps=SEGMENT_STEPS)
            class Regressor(torch.nn.Module):
                def __init__(self):
                    super().__init__()
                    self.encoder, self.readout = encoder, torch.nn.Linear(config['hidden_size'], 1)
                def forward(self, x):
                    return self.readout(self.encoder(x, dt=config['dt'])[:, -1])
            model = Regressor().to(device)
            optimizer = torch.optim.Adam(model.parameters(), lr=config['learning_rate'])
            record.update(encoder_class=type(encoder).__name__, parameters=sum(p.numel() for p in model.parameters()))
            if hasattr(encoder, 'population'):
                record['population_config'] = asdict(encoder.population.config)
                if encoder.population.config.bins != 32:
                    raise ValueError('B must retain 32 bins')
        with stage('training_data', sync=False):
            x, y = benchmark.make_dataset(args.task, config['train_count'], config['length'], config['data_seed'])
            draws = benchmark.np.random.default_rng(args.seed+1729).integers(0, len(x), config['batch_size'])
            record.update(training_split_sha256=digest(x.tobytes()+y.tobytes()), batch_indices=draws.tolist(),
                          batch_sha256=digest(x[draws].tobytes()+y[draws].tobytes()),
                          input_shape=list(x[draws].shape), input_dtype=str(x.dtype))
            if record['input_shape'] != [64, 64, 2] or record['input_dtype'] != 'float32':
                raise ValueError('actual selected batch differs from original FP32 full shape')
        with stage('data_transfer'):
            train_x, train_y = torch.from_numpy(x).to(device), torch.from_numpy(y).to(device)
            indices = torch.as_tensor(draws, device=device)
        model.train()
        optimizer.zero_grad(set_to_none=True)
        torch.cuda.reset_peak_memory_stats(device)
        record['peak_reset_before_step'] = True
        record['resident_allocated_bytes'] = torch.cuda.memory_allocated(device)
        record['device_free_before_step_bytes'] = torch.cuda.mem_get_info(device)[0]
        meter = benchmark.EnergyCounter(str(device))
        meter.start()
        record.update(training_examples_submitted=64, training_tokens_submitted=4096)
        with stage('forward'):
            prediction = model(train_x[indices])
            record['finite']['prediction'] = bool(torch.isfinite(prediction).all())
            if prediction.shape != (64, 1) or not record['finite']['prediction']:
                raise FloatingPointError('invalid prediction shape or nonfinite prediction')
        with stage('loss'):
            loss = (prediction-train_y[indices]).square().mean()
            record['finite']['loss'] = bool(torch.isfinite(loss))
            if not record['finite']['loss']:
                raise FloatingPointError('nonfinite loss')
            record['training_batch_mse_before_step'] = float(loss.detach())
        with stage('backward'):
            loss.backward()
        with stage('gradient_validation'):
            record['missing_gradients'] = [n for n, p in model.named_parameters() if p.requires_grad and p.grad is None]
            record['finite']['gradients'] = all(bool(torch.isfinite(p.grad).all()) for p in model.parameters() if p.grad is not None)
            if record['missing_gradients'] or not record['finite']['gradients']:
                raise FloatingPointError('missing or nonfinite trainable gradients')
        with stage('clip'):
            norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            if not bool(torch.isfinite(norm)):
                raise FloatingPointError('nonfinite gradient norm')
            record['gradient_norm_before_clip'] = float(norm)
        with stage('optimizer_step'):
            optimizer.step()
        record['optimizer_steps_completed'] = 1
        with stage('parameter_validation'):
            record['finite']['updated_parameters'] = all(bool(torch.isfinite(p).all()) for p in model.parameters())
            if not record['finite']['updated_parameters']:
                raise FloatingPointError('nonfinite updated parameters')
        record['status'] = 'completed'
    except (ImportError, Unavailable) as exc:
        record.update(status='unavailable', reason=f'{type(exc).__name__}: {exc}')
    except BaseException as exc:
        unavailable = type(exc).__name__ == 'UnavailableBaseline'
        record.update(status='unavailable' if unavailable else 'interrupted' if isinstance(exc, (InterruptedError, KeyboardInterrupt)) else 'failed',
                      reason=f'{type(exc).__name__}: {exc}', failure_stage=record['stage'],
                      oom=type(exc).__name__ == 'OutOfMemoryError', traceback=traceback.format_exc())
    finally:
        record['terminal_cuda_synchronized'] = False
        if initialized:
            try:
                torch.cuda.synchronize(device)
                record['terminal_cuda_synchronized'] = True
            except Exception as exc:
                record['terminal_cuda_sync_error'] = f'{type(exc).__name__}: {exc}'
        if meter is not None:
            try:
                record['energy'] = meter.stop()
                record['energy']['scope'] = 'instrumented single-step wall interval; whole device/package, not process attribution'
            except Exception as exc:
                record['energy'] = dict(joules_by_physical_counter=None, missing_reason=f'{type(exc).__name__}: {exc}')
        if initialized:
            try:
                record.update(peak_allocated_bytes=torch.cuda.max_memory_allocated(device),
                              peak_reserved_bytes=torch.cuda.max_memory_reserved(device), device_free_after_step_bytes=torch.cuda.mem_get_info(device)[0])
            except Exception as exc:
                record['memory_missing_reason'] = f'{type(exc).__name__}: {exc}'
        if 'source_files_sha256' in record:
            try:
                record['source_unchanged'] = snapshot(root) == record['source_files_sha256'] and digest(config_path.read_bytes()) == record['config_sha256']
                if not record['source_unchanged']:
                    record.update(status='invalidated', reason='research source or full.json changed during probe')
            except Exception as exc:
                record.update(status='invalidated', source_unchanged=False, reason=f'source verification failed: {exc}')
        if 'candidate_files_sha256' in record:
            try:
                record['candidate_unchanged'] = {name: digest((args.remat_root.resolve()/name).read_bytes())
                                                 for name in CANDIDATE_PINS} == record['candidate_files_sha256']
                if not record['candidate_unchanged']:
                    record.update(status='invalidated', reason='candidate files changed during probe')
            except Exception as exc:
                record.update(status='invalidated', candidate_unchanged=False, reason=f'candidate source verification failed: {exc}')
        record['probe_unchanged'] = digest(Path(__file__).read_bytes()) == record['probe_sha256']
        if not record['probe_unchanged']:
            record.update(status='invalidated', reason='probe source changed during execution')
        record['energy']['interval_completion'] = ('synchronized' if record['terminal_cuda_synchronized']
                                                   else 'incomplete_or_not_started')
        counters = record['energy'].get('joules_by_physical_counter') or {}
        record.update(gpu_energy_counter_measured=any(k.startswith('nvml_') for k in counters),
                      finished_utc=datetime.now(timezone.utc).isoformat(), wall_seconds=time.perf_counter()-start)
        publish(args.output, record)
        print(json.dumps({'output': str(args.output), 'status': record['status'], 'stage': record['stage']}))
    return 0 if record['status'] == 'completed' else 2 if record['status'] == 'unavailable' else 1


if __name__ == '__main__':
    raise SystemExit(main())
