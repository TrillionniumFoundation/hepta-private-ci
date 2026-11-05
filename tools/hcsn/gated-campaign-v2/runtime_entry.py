#!/usr/bin/env python3
"""Record and enforce one common runtime before executing a frozen HCSN tool."""
import argparse
from datetime import datetime, timezone
import importlib.metadata as md
import json
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys
import traceback

from contracts import GPU_UUID, PINS, canonical_sha, normalize_gpu_uuid, require, sha


def publish(path, value):
    with Path(path).open('x') as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    directory_fd = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def runtime(torch, device, *, enforce_flags=True):
    distributions = {d.metadata['Name'].lower().replace('_', '-'): d.version for d in md.distributions()}
    for name, version in PINS.items():
        actual = distributions.get(name)
        require(actual == version or name in ('mamba-ssm', 'causal-conv1d')
                and actual and actual.split('+')[0] == version, f'runtime version mismatch: {name}')
    props = torch.cuda.get_device_properties(0)
    gpu_uuid_raw = str(props.uuid)
    gpu_uuid = normalize_gpu_uuid(gpu_uuid_raw)
    require(gpu_uuid == GPU_UUID and torch.version.cuda == '12.8'
            and torch._C._GLIBCXX_USE_CXX11_ABI, 'CUDA GPU/runtime/ABI mismatch')
    query = subprocess.run(['nvidia-smi', '-i', GPU_UUID, '--query-gpu=uuid,driver_version',
                            '--format=csv,noheader,nounits'], capture_output=True, text=True,
                           check=True, timeout=15)
    fields = query.stdout.strip().split(',')
    require(len(fields) == 2 and fields[0].strip() == GPU_UUID
            and fields[1].strip() == '580.178.04', 'device driver changed from the admitted runtime')
    flags = dict(deterministic_algorithms=torch.are_deterministic_algorithms_enabled(),
                 deterministic_warn_only=torch.is_deterministic_algorithms_warn_only_enabled(),
                 float32_matmul_precision=torch.get_float32_matmul_precision(),
                 cuda_matmul_allow_tf32=torch.backends.cuda.matmul.allow_tf32,
                 cudnn_allow_tf32=torch.backends.cudnn.allow_tf32,
                 cudnn_benchmark=torch.backends.cudnn.benchmark,
                 cudnn_deterministic=torch.backends.cudnn.deterministic,
                 default_dtype=str(torch.get_default_dtype()), cpu_threads=torch.get_num_threads(),
                 cublas_workspace_config=os.environ.get('CUBLAS_WORKSPACE_CONFIG'))
    expected_flags = dict(deterministic_algorithms=True, deterministic_warn_only=True,
            float32_matmul_precision='highest', cuda_matmul_allow_tf32=False,
            cudnn_allow_tf32=False, cudnn_benchmark=False, cudnn_deterministic=True,
            default_dtype='torch.float32', cpu_threads=2, cublas_workspace_config=':4096:8')
    if enforce_flags:
        require(flags == expected_flags,
                'runtime precision/determinism flags differ from the declared profile')
    fraction = torch.cuda.memory.get_per_process_memory_fraction(0) if device == 'cuda:0' else None
    require(device != 'cuda:0' or fraction == 0.5, 'actual CUDA allocator fraction differs from the declared cap')
    return dict(schema='hcsn-runtime-profile-v2', device=device, gpu_uuid=gpu_uuid,
                gpu_uuid_raw=gpu_uuid_raw,
                gpu_name=props.name, driver_version=fields[1].strip(), cuda_runtime=torch.version.cuda, python=sys.version,
                executable=sys.executable, torch=torch.__version__, flags=flags,
                installed_distributions=distributions,
                distributions_sha256=canonical_sha(distributions),
                cuda_visible_devices=os.environ.get('CUDA_VISIBLE_DEVICES'),
                allocator_fraction=fraction,
                policy_scope='PyTorch tensor runtime; custom Triton kernels retain their own implementation',
                measurement_scope='shared physical GPU; no exclusive-device or energy-attribution claim')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo-root', type=Path, required=True)
    p.add_argument('--profile', type=Path, required=True)
    p.add_argument('--device', choices=('cpu', 'cuda:0'), required=True)
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument('--module')
    target.add_argument('--script', type=Path)
    p.add_argument('arguments', nargs=argparse.REMAINDER)
    args = p.parse_args()
    require(not args.profile.exists() and not args.profile.with_suffix('.terminal.json').exists(),
            'runtime receipts already exist')
    require(os.environ.get('CUBLAS_WORKSPACE_CONFIG') == ':4096:8',
            'CUBLAS_WORKSPACE_CONFIG must be set before importing torch')
    require(os.environ.get('CUDA_VISIBLE_DEVICES') == GPU_UUID, 'physical GPU selection changed')
    require('torch' not in sys.modules, 'runtime entry requires a fresh process before Torch import')
    import torch
    require(torch.cuda.is_available() and torch.cuda.device_count() == 1, 'expected one selected CUDA device')
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True, warn_only=True)
    torch.set_float32_matmul_precision('highest')
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    if args.device == 'cuda:0':
        torch.cuda.set_device(0)
        torch.cuda.set_per_process_memory_fraction(0.5, 0)
    initial = runtime(torch, args.device)
    initial.update(started_utc=datetime.now(timezone.utc).isoformat(),
                   pid=os.getpid(), launch_environment_validated_before_torch_import=True,
                   torch_preimported_before_entry=False,
                   entry_sha256=sha(__file__), target_module=args.module,
                   target_script=str(args.script) if args.script else None,
                   target_script_sha256=sha(args.script) if args.script else None,
                   arguments=args.arguments)
    publish(args.profile, initial)
    sys.path.insert(0, str(args.repo_root.resolve()))
    sys.argv = [args.module or str(args.script)] + (args.arguments[1:]
                if args.arguments[:1] == ['--'] else args.arguments)
    code, error = 1, None
    def stop(signum, frame):
        raise KeyboardInterrupt(f'owned task received signal {signum}')
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        if args.module:
            runpy.run_module(args.module, run_name='__main__', alter_sys=True)
        else:
            runpy.run_path(str(args.script), run_name='__main__')
        code = 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 0 if exc.code is None else 1
    except BaseException:
        error = traceback.format_exc()
        traceback.print_exc()
    finally:
        try:
            terminal = runtime(torch, args.device, enforce_flags=False)
            final_flags = dict(terminal['flags'])
            fixture_threads = args.module == 'qualification.hcsn.checks' and args.device == 'cpu'
            if fixture_threads and final_flags['cpu_threads'] in (1, 2):
                final_flags['cpu_threads'] = initial['flags']['cpu_threads']
            terminal['allowed_fixture_thread_mutation'] = fixture_threads
            stable = final_flags == initial['flags'] and all(terminal[k] == initial[k] for k in ('installed_distributions',
                         'gpu_uuid', 'gpu_uuid_raw', 'driver_version', 'cuda_runtime', 'allocator_fraction'))
            if not stable:
                code, error = 1, 'runtime changed during stage'
        except BaseException:
            terminal, stable, code = {}, False, 1
            error = traceback.format_exc()
        terminal.update(runtime_profile_sha256=sha(args.profile), status='completed' if code == 0 else 'failed',
                        runtime_unchanged=stable, child_exit_code=code, error=error,
                        finished_utc=datetime.now(timezone.utc).isoformat())
        publish(args.profile.with_suffix('.terminal.json'), terminal)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
