"""Single final integration run after all source owners declare a freeze."""

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import unittest

REPO = Path('/workspace/scratch/f1f83ab8f2f0/hepta')
SOURCE = REPO / 'qa/stem-bakeoff'
BASE_PLAN = Path('/workspace/scratch/f1f83ab8f2f0/real-cell-run/verification/attempt2/verification_plan.json')
OUTPUT = Path('/workspace/scratch/f1f83ab8f2f0/real-cell-run/verification/final')
ADDITIONAL = ('test_summarize_cell_study', 'test_cell_prior_calibration_probe',
              'test_package_cell_evidence', 'test_cell_logical_routing', 'test_logical_routing_probe')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, value):
    (OUTPUT / name).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def source_hashes():
    paths = {p for p in SOURCE.iterdir() if p.is_file() and p.suffix in ('.py', '.json', '.txt', '.md', '.sh')}
    paths.update(p for p in (SOURCE / 'evidence/20261023-cell-next-stage/source').glob('*') if p.is_file())
    learning = REPO / 'docs/learning'
    paths.update(p for p in learning.iterdir() if p.is_file())
    paths.add(REPO / '.github/workflows/hepta-shared-stem-bakeoff-shadow.yml')
    return {str(path.relative_to(REPO)): {'bytes': path.stat().st_size, 'sha256': sha(path)}
            for path in sorted(paths)}


def git(*args):
    return subprocess.run(['git', *args], cwd=REPO, text=True, capture_output=True, check=True).stdout.strip()


OUTPUT.mkdir(parents=True, exist_ok=False)
sys.path.insert(0, str(SOURCE))
started = time.perf_counter_ns()
before = source_hashes()
write('source_hashes_before.json', before)
base = json.loads(BASE_PLAN.read_bytes())
modules = sorted(set(base['modules']) | set(ADDITIONAL))
if len(base['modules']) != 26 or base['planned_tests'] != 169 or len(modules) != 31:
    raise RuntimeError('The original 26-module plan plus five additions must be preserved')
loader = unittest.TestLoader()
suites = {name: loader.loadTestsFromName(name) for name in modules}
counts = {name: suite.countTestCases() for name, suite in suites.items()}
plan = {'schema': 'hepta.final-integrated-verification.v1', 'modules': modules,
    'module_test_counts': counts, 'planned_tests': sum(counts.values()), 'expected_minimum_tests': 195,
    'base_plan_sha256': sha(BASE_PLAN), 'runner_sha256': sha(Path(__file__)),
    'started_at_ns': time.time_ns(), 'executable': sys.executable, 'python': platform.python_version(),
    'packages': {name: importlib.metadata.version(name) for name in
                 ('numpy', 'torch', 'transformers', 'tokenizers', 'safetensors', 'librosa', 'soundfile')},
    'threads': {name: os.environ.get(name) for name in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS')},
    'source_scope': ['all direct qa/stem-bakeoff source/config files', 'all direct docs/learning files',
                     'preserved original smoke transcripts',
                     'shared Stem workflow; includes final reproduction docs and render/audit sources'],
    'loader_errors': list(loader.errors), 'authority': 'DENY_ALL', 'quality_qualification': False}
write('verification_plan.json', plan)
gate_evidence = {'git_head_before': git('rev-parse', 'HEAD'), 'baseline': '429894ac8e0818102cfdea4ad47a56e4583b2902',
                 'workflow_sha256': sha(REPO / '.github/workflows/hepta-shared-stem-bakeoff-shadow.yml'), 'gates': {}}
for name in ('evidence_gate.py', 'test_evidence_gate.py'):
    path = f'qa/stem-bakeoff/{name}'
    payload = (REPO / path).read_bytes()
    gate_evidence['gates'][path] = {'baseline_tree': git('ls-tree', gate_evidence['baseline'], '--', path),
        'head_tree': git('ls-tree', 'HEAD', '--', path), 'worktree_sha256': sha(REPO / path),
        'worktree_git_blob_sha1': hashlib.sha1(f'blob {len(payload)}\0'.encode() + payload).hexdigest()}
write('git_and_gate_evidence.json', gate_evidence)
print(json.dumps({'module_count': len(modules), 'planned_tests': sum(counts.values()),
                  'source_files_hashed': len(before)}), flush=True)
result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(suites.values()))
after = source_hashes()
write('source_hashes_after.json', after)
changed = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))
summary = {'schema': plan['schema'], 'module_count': len(modules), 'module_test_counts': counts,
    'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
    'skipped': len(result.skipped), 'expected_failures': len(result.expectedFailures),
    'unexpected_successes': len(result.unexpectedSuccesses),
    'passed': result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped)
              - len(result.expectedFailures) - len(result.unexpectedSuccesses),
    'source_files_checked': len(before), 'changed_source_files': changed,
    'git_head_after': git('rev-parse', 'HEAD'), 'finished_at_ns': time.time_ns(),
    'elapsed_seconds': (time.perf_counter_ns() - started) / 1e9,
    'success': result.wasSuccessful() and result.testsRun >= 195 and not changed and not result.skipped
               and not result.expectedFailures and not result.unexpectedSuccesses and not loader.errors,
    'failures_detail': [{'test': str(test), 'traceback': error} for test, error in result.failures],
    'errors_detail': [{'test': str(test), 'traceback': error} for test, error in result.errors],
    'skipped_detail': [{'test': str(test), 'reason': reason} for test, reason in result.skipped],
    'authority': 'DENY_ALL', 'quality_qualification': False}
write('verification_summary.json', summary)
write('manifest.json', {path.name: {'bytes': path.stat().st_size, 'sha256': sha(path)}
                        for path in sorted(OUTPUT.iterdir()) if path.is_file()})
print(json.dumps(summary, sort_keys=True), flush=True)
raise SystemExit(0 if summary['success'] else 1)
