#!/usr/bin/env python3
"""Reproduce the *local* P0/P1 subset, preserving fail-closed admission.

This is not the actual five-seed neural generator, a signed observer or native
Hepta deployment. No network, rustc or pretrained multimodal weights required.
"""
from pathlib import Path
import json
import platform
import subprocess
import sys
import hashlib
import os

ROOT = Path(__file__).resolve().parent


def execute(cmd, file):
    environment = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    proc = subprocess.run(cmd, cwd=ROOT, env=environment,
                          capture_output=True, text=True, check=False)
    (ROOT / file).write_text(proc.stdout + proc.stderr)
    return {'command':cmd, 'exit_code':proc.returncode, 'stdout_sha256':hashlib.sha256(
        (proc.stdout+proc.stderr).encode()).hexdigest(), 'log_file':file}


def main():
    cases = [
        execute([sys.executable, '-m', 'pytest', '-q', '--disable-warnings'], 'pytest_current.log'),
        execute([sys.executable, 'p0_recompute.py'], 'p0_run_current.log'),
        execute([sys.executable, 'verify.py', 'qualification.json'], 'gate_expected_rejection.log'),
    ]
    checks = (cases[0]['exit_code']==0 and cases[1]['exit_code']==0
              and cases[2]['exit_code']==1)
    receipt = {
        'schema': 'hepta.mgp.local-subset-replay.v2',
        'scope': 'isolated_chatgpt_container_only_not_user_dot_host',
        'scientific_model_training_completed': False,
        'full_repository_compiled': False,
        'original_external_holdout_complete': False,
        'production_qualified': False,
        'admission': 'HOLD_NO_GO',
        'authority': 'DENY_ALL',
        'python': platform.python_version(),
        'platform': platform.platform(),
        'executions': cases,
        'local_subset_reproduced': checks,
        'limits': ['P0 is independent published known-LQ recomputation only',
                   'P1 comparisons are synthetic previously assembled fixtures',
                   'No pretrained multimodal/diffusion weights or trusted observer',
                   'Python audit cannot grant signed production or scientific proof',
                   'Local source is recovered prior research subset, not the full GitHub tree'],
    }
    (ROOT/'current_receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt, indent=2))
    return 0 if checks else 1

if __name__ == '__main__':
    raise SystemExit(main())
