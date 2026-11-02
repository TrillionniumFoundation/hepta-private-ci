"""Linux single-process inference worker; seal before numerical imports."""

import argparse
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import resource
import time


def seal():
    if len(list(Path('/proc/self/task').iterdir())) != 1:
        raise RuntimeError('A single initial task is required')
    lib = ctypes.CDLL('libseccomp.so.2', use_errno=True)
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_attr_set.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32]
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    context = lib.seccomp_init(0x7fff0000)
    if not context:
        raise RuntimeError('seccomp_init failed')
    rules = []
    try:
        result = lib.seccomp_attr_set(context, 4, 1)  # Synchronize all tasks.
        if result != 0:
            raise OSError(-result, 'seccomp TSYNC failed')
        for name in ('fork', 'vfork', 'clone', 'clone3', 'execve', 'execveat'):
            syscall = lib.seccomp_syscall_resolve_name(name.encode())
            if syscall < 0:
                raise RuntimeError('Required syscall unavailable: ' + name)
            result = lib.seccomp_rule_add(context, 0x00050000 | errno.EPERM, syscall, 0)
            if result != 0:
                raise OSError(-result, name)
            rules.append(dict(name=name, syscall=syscall))
        result = lib.seccomp_load(context)
        if result != 0:
            raise OSError(-result, 'seccomp_load failed')
    finally:
        lib.seccomp_release(context)
    try:
        pid = os.fork()
    except OSError as error:
        if error.errno != errno.EPERM:
            raise
    else:
        if pid == 0:
            os._exit(91)
        os.waitpid(pid, 0)
        raise RuntimeError('Unexpected successful fork')
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines())
    if status['NoNewPrivs'].strip() != '1' or status['Seccomp'].strip() != '2':
        raise RuntimeError('Kernel filter state missing')
    return dict(rules=rules, fork_denied=True, no_new_privs=1, seccomp=2,
                phase='Before Torch/NumPy/model import; all clone calls and exec are denied')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--task', choices=('mqar', 'binding'), required=True)
    parser.add_argument('--core', choices=('flow', 'diagonal'), required=True)
    parser.add_argument('--condition', choices=('base', 'long_tokens_128'), required=True)
    parser.add_argument('--batch', type=int, choices=(1,24), required=True)
    parser.add_argument('--sealed', choices=('yes', 'no'), required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    guard = seal() if args.sealed == 'yes' else None
    import numpy as np
    import torch
    from experiments.hcsn_missing_answers_20261101 import campaign
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    root = Path(__file__).resolve().parents[2]
    checkpoint = root / f'experiments/hcsn_missing_answers_20261101/results/run001/fits/{args.task}_{args.core}_17/checkpoint.pt'
    model = campaign.model(args.core, 17).eval()
    model.load_state_dict(torch.load(checkpoint, map_location='cpu', weights_only=True))
    arrays = campaign.batch(args.task, args.batch, 923417, 'dev', args.condition)
    inputs = [torch.from_numpy(arrays[key]) for key in ('x', 'dt', 'observed')]
    samples = []
    started = time.process_time()
    with torch.no_grad():
        for _ in range(5):
            begin = time.perf_counter_ns()
            output = model(*inputs).numpy()
            samples.append((time.perf_counter_ns() - begin) / 1e9)
    usage = resource.getrusage(resource.RUSAGE_SELF)
    child_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    children = Path(f'/proc/self/task/{os.getpid()}/children').read_text().split()
    if children or len(list(Path('/proc/self/task').iterdir())) != 1:
        raise RuntimeError('Unexpected child or additional task')
    mask = arrays['y'] >= 0
    result = dict(task=args.task, core=args.core, condition=args.condition, batch=args.batch,
        sealed=guard, torch=torch.__version__, output_sha256=hashlib.sha256(output.tobytes()).hexdigest(),
        checkpoint_sha256=campaign.sha(checkpoint), accuracy=float((output.argmax(-1)[mask] == arrays['y'][mask]).mean()),
        raw_latency_seconds=samples, body_cpu_seconds=time.process_time()-started,
        peak_rss_before_result_write_bytes=usage.ru_maxrss * 1024,
        waited_child_cpu_seconds=child_usage.ru_utime+child_usage.ru_stime,
        live_children=children, final_tasks=1, energy_joules=None, production_activation=False,
        scope='Internal RSS is through inference; authoritative lifetime highwater including this final write is parent wait4. Sealed worker has no descendants or extra threads; supervisor and filesystem cache are separate.')
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(core=args.core, sealed=args.sealed, peak_rss_before_result_write_bytes=result['peak_rss_before_result_write_bytes'])))


if __name__ == '__main__':
    main()
