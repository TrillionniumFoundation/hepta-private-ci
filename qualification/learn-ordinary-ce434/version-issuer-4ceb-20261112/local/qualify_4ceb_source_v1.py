from pathlib import Path
import hashlib
import contextlib
import json
import os
import re
import subprocess
import sys
import tomllib

repo = Path('/workspace/scratch/ce434f960ee9/learn-current-v3')
out = Path('/workspace/scratch/ce434f960ee9/qualification-local-4ceb-source-v1')
fixed = '4ceb2fa080c52e5d23ee3a7428c65515418745fd'
tree = '0c1d60e30f9b5f2ccfce799caeca437a10d471bb'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
sys.dont_write_bytecode = True

def git(*args):
    return subprocess.check_output(['git', *args], cwd=repo, text=True).strip()

assert git('rev-parse', 'HEAD') == fixed
assert git('rev-parse', 'HEAD^{tree}') == tree
assert not git('status', '--porcelain=v1', '--untracked-files=all')
manifest = tomllib.loads((repo / 'CALLERS.toml').read_text())
ids = [row['id'] for row in manifest['boundary']]
assert len(ids) == len(set(ids)) == 483
assert set(ids) == set(manifest['privileged_inventory']['required_boundary_ids'])
assert len(manifest['protected_file']) == 373
tracked_rust = [p for p in git('ls-tree', '-r', '--name-only', 'HEAD').splitlines() if p.endswith('.rs')]
assert all((repo / p).is_file() for p in tracked_rust)
assert all((repo / row['path']).is_file() for row in manifest['protected_file'])
out.mkdir(exist_ok=False)
report = {'state': 'running', 'source_sha': fixed, 'source_tree': tree,
          'scope': 'exact fixed source Python controls; no formatter, native, full caller proof or ordinary task execution',
          'tracked_rust_files_present': len(tracked_rust), 'boundaries': len(ids),
          'protected_rows': len(manifest['protected_file']), 'source_inventory': 319,
          'steps': [], 'native_tests_executed': 0, 'full_caller_proof_executed': False,
          'acceptance': {'positive_adoption': 0, 'no_update_or_fallback': 0, 'daemon_and_root_cold_restart': 0}}

def save():
    pending = out / 'result.pending'
    pending.write_text(json.dumps(report, indent=2) + '\n')
    pending.replace(out / 'result.json')

save()
sys.path.insert(0, str(repo / 'scripts'))
from hepta_ci_exec import execute_logged

os.chdir(repo)
for name, args, count in [
    ('source-closure', [sys.executable, '-m', 'unittest', 'discover', '-s', 'qa/b4-no-bypass', '-p', '*source_closure.py', '-v'], 319),
    ('observer-parser', [sys.executable, '-m', 'unittest', 'discover', '-s', 'scripts', '-p', 'test_hepta_c_observer_coverage.py', '-v'], 16),
    ('caller-self-test', [sys.executable, 'scripts/verify_hepta_callers.py', 'self-test'], None),
]:
    log = out / (name + '.log')
    with (out / (name + '.driver.log')).open('x') as driver, contextlib.redirect_stdout(driver):
        result = execute_logged(args, log, timeout_seconds=600)
    raw = log.read_bytes()
    text = raw.decode('utf-8')
    found = re.findall(r'(?m)^Ran (\d+) tests in ', text)
    passed = not result['returncode'] and not result['timed_out'] and not result['output_limit_exceeded']
    if count is not None:
        passed = passed and found == [str(count)] and re.search(r'(?m)^OK$', text) is not None
    report['steps'].append({'name': name, 'command': args, **result, 'expected_tests': count,
                            'actual_reported_test_counts': found, 'passed': passed,
                            'raw_sha256': hashlib.sha256(raw).hexdigest(), 'raw_bytes': len(raw)})
    save()
    print(json.dumps({'name': name, 'returncode': result['returncode'], 'passed': passed, 'actual_counts': found}), flush=True)
report['source_after'] = git('rev-parse', 'HEAD')
report['source_tree_after'] = git('rev-parse', 'HEAD^{tree}')
report['source_status_after'] = git('status', '--porcelain=v1', '--untracked-files=all')
report['state'] = 'passed' if all(row['passed'] for row in report['steps']) and report['source_after'] == fixed and report['source_tree_after'] == tree and not report['source_status_after'] else 'failed'
save()
print(json.dumps({'state': report['state'], 'result_path': str(out / 'result.json')}), flush=True)
raise SystemExit(0 if report['state'] == 'passed' else 1)
