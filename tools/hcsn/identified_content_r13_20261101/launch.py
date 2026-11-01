"""Whole-child CPU accounting includes interpreter/imports and all data preparation."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent


def identity():
    paths = [ROOT/n for n in ['PROTOCOL.json', 'content.py', 'contract.py', 'data.py',
                              'models.py', 'training.py', 'controller.py']]
    paths += [ROOT/'propagation'/n for n in ['api.py', 'finite_volume.py', 'bounds.py']]
    paths += [ROOT.parent/'unified_cell_r12_20261031/contract.py',
              ROOT.parent/'unified_cell_r12_20261031/control/controller.py',
              ROOT.parent/'unified_cell_r12_20261031/tie_resolution/candidate.py',
              ROOT.parent/'calibrated_operator_r11_20261031/numerics/kernel.py']
    return {str(p.relative_to(ROOT.parent)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}


def run_child(arguments, log_path, receipt_path):
    log_path, receipt_path = Path(log_path), Path(receipt_path)
    if log_path.exists() or receipt_path.exists():
        raise FileExistsError('Never overwrite an execution receipt')
    log_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    for name in ['OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS']:
        env[name] = '1'
    before = identity()
    tick = time.perf_counter()
    with log_path.open('w') as handle:
        child = subprocess.Popen([sys.executable, *map(str, arguments)], env=env,
                                 stdout=handle, stderr=subprocess.STDOUT)
        _, status, usage = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
    receipt = {'arguments': list(map(str, arguments)), 'returncode': child.returncode,
        'child_user_cpu_seconds': usage.ru_utime, 'child_system_cpu_seconds': usage.ru_stime,
        'whole_process_cpu_seconds': usage.ru_utime+usage.ru_stime,
        'wall_seconds': time.perf_counter()-tick, 'max_rss_kib': usage.ru_maxrss,
        'source_before': before, 'source_unchanged': before == identity()}
    receipt_path.write_text(json.dumps(receipt, indent=2)+'\n')
    if child.returncode or not receipt['source_unchanged']:
        raise RuntimeError(f'Child failed or source changed: {log_path}')
    return receipt
