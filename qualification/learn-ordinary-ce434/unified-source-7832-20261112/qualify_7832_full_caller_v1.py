from pathlib import Path
import contextlib
import hashlib
import json
import os
import subprocess
import sys
import time
import tomllib

repo = Path('/workspace/scratch/ce434f960ee9/learn-current-v2')
out = Path('/workspace/scratch/ce434f960ee9/qualification-local-7832-full-caller-v1')
fixed = '7832eef16022f1af233e2a48ef46fb1ac61dcd8f'
tree = 'bfccf4de95b9b0d68a84a344c9071171edd005b1'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
sys.dont_write_bytecode = True


def git(*args):
    return subprocess.check_output(['git', *args], cwd=repo, text=True).strip()


assert git('rev-parse', 'HEAD') == fixed
assert git('rev-parse', 'HEAD^{tree}') == tree
assert not git('status', '--porcelain=v1', '--untracked-files=all')
manifest = tomllib.loads((repo / 'CALLERS.toml').read_text())
tracked = git('ls-tree', '-r', '--name-only', 'HEAD').splitlines()
rust = [path for path in tracked if path.endswith('.rs')]
assert all((repo / path).is_file() for path in rust)
assert all((repo / row['path']).is_file() for row in manifest['protected_file'])
out.mkdir(exist_ok=False)
report = {'source_sha': fixed, 'source_tree': tree, 'state': 'running',
          'scope': 'original unmodified full caller verifier, not native or ordinary acceptance',
          'tracked_rust_files_present': len(rust), 'expected_boundaries': 480,
          'expected_protected_rows': 368, 'full_chain_acceptance': {
              'positive': 0, 'no_update': 0, 'daemon_root_cold_restart': 0}}


def save():
    pending = out / 'result.pending.json'
    pending.write_text(json.dumps(report, indent=2) + '\n')
    pending.replace(out / 'result.json')


save()
sys.path.insert(0, str(repo / 'scripts'))
from hepta_ci_exec import execute_logged

os.chdir(repo)
command = [sys.executable, '-B', 'scripts/verify_hepta_callers.py', 'verify', '--root', str(repo)]
raw = out / 'full-caller-proof.log'
started = time.monotonic()
with (out / 'full-caller-proof.driver.log').open('x') as stream, contextlib.redirect_stdout(stream):
    result = execute_logged(command, raw, timeout_seconds=7200)
report.update(command=command, execution=result, elapsed_seconds=time.monotonic() - started,
              raw_bytes=raw.stat().st_size, raw_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
              source_after=git('rev-parse', 'HEAD'), source_tree_after=git('rev-parse', 'HEAD^{tree}'),
              source_status_after=git('status', '--porcelain=v1', '--untracked-files=all'))
passed = result['returncode'] == 0 and not result['timed_out'] and not result['output_limit_exceeded']
if passed:
    receipt = json.loads(raw.read_text())
    report['original_receipt'] = receipt
report['state'] = 'passed' if passed and report['source_after'] == fixed and report['source_tree_after'] == tree and not report['source_status_after'] else 'failed'
save()
print(json.dumps({'state': report['state'], 'elapsed_seconds': report['elapsed_seconds'], 'raw_bytes': report['raw_bytes'], 'raw_sha256': report['raw_sha256']}), flush=True)
raise SystemExit(0 if report['state'] == 'passed' else 1)
