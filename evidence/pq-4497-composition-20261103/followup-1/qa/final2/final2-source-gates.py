#!/usr/bin/env python3
"""Retain one final run of the unchanged source gates on the frozen overlay."""

import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import tomllib

TASK = Path('/workspace/scratch/df0a4a720ed8')
ROOT = TASK / 'hepta-source'
OUT = TASK / 'chain-rollback/hepta-qa-followup'
PRIOR = OUT / 'final-after-fmt-source-gates.json'
RECEIPT = OUT / 'final2-source-gates.json'
assert not RECEIPT.exists(), 'Do not replace an earlier validation receipt'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT).decode().strip()


freeze = ast.parse((TASK / 'pq-audit/freeze_hepta_followup.py').read_text())
product = None
for node in freeze.body:
    if isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == 'PRODUCT'
        for target in node.targets
    ):
        product = ast.literal_eval(node.value)
assert isinstance(product, set) and len(product) == 30

prior = json.loads(PRIOR.read_text())
inputs = set(prior['input_sha256_after']) | product
inputs |= {p.relative_to(ROOT).as_posix() for p in (ROOT / 'qa/b4-no-bypass').glob('*.py')}
inputs |= {'scripts/hepta_typed_callers.py'}


def identity():
    direct = {p: sha((ROOT / p).read_bytes()) for p in sorted(inputs)}
    manifest = tomllib.loads((ROOT / 'CALLERS.toml').read_text())
    # This is only an input identity snapshot. Expected caller sets remain in
    # the unchanged independent tests, never generated from this manifest.
    files = []
    for relative in manifest['source_roots']:
        source = (ROOT / relative).resolve()
        assert source.is_relative_to(ROOT.resolve())
        for path in source.rglob('*.rs'):
            assert not path.is_symlink(), str(path)
            files.append(path)
    digest = hashlib.sha256()
    total_bytes = 0
    for path in sorted(files):
        raw = path.read_bytes()
        total_bytes += len(raw)
        record = path.relative_to(ROOT).as_posix() + '\0' + str(len(raw)) + '\0' + sha(raw) + '\n'
        digest.update(record.encode())
    return {
        'source_head': git('rev-parse', 'HEAD'),
        'source_base_tree': git('rev-parse', 'HEAD^{tree}'),
        'reviewed_overlay_source_paths': sorted(product),
        'input_sha256': direct,
        'complete_scanner_rust_input': {
            'source_roots': manifest['source_roots'],
            'files': len(files),
            'bytes': total_bytes,
            'sha256': digest.hexdigest(),
            'digest_format': 'sorted path + NUL + decimal byte length + NUL + file SHA256 + LF, UTF-8; all files from the unchanged scanner source-root enumeration, including ignored and cfg-test paths',
        },
    }


before = identity()
assert before['source_head'] == '0baf43cf4bf8f953fff079725348de1d8f26434f'
assert before['complete_scanner_rust_input']['files'] == 5604
assert all(before['input_sha256'][p] == h for p, h in prior['input_sha256_after'].items())
prior_sha = sha(PRIOR.read_bytes())
started = datetime.now(timezone.utc).isoformat()
commands = {
    'qa-suite': ['python3', '-m', 'unittest', 'discover', '-s', 'qa/b4-no-bypass', '-p', 'test_*.py'],
    'caller-self-test': ['python3', 'scripts/verify_hepta_callers.py', 'self-test'],
    'caller-verify': ['python3', 'scripts/verify_hepta_callers.py', 'verify'],
}
environment = dict(os.environ)
environment['PYTHONDONTWRITEBYTECODE'] = '1'


def run(item):
    name, command = item
    log = OUT / ('final2-' + name + '.log')
    assert not log.exists(), str(log)
    start = time.monotonic()
    with log.open('xb') as target:
        result = subprocess.run(command, cwd=ROOT, env=environment, stdout=target, stderr=subprocess.STDOUT)
    return name, {
        'command': command,
        'exit_code': result.returncode,
        'duration_seconds': time.monotonic() - start,
        'log_file': log.name,
        'log_sha256': sha(log.read_bytes()),
    }


with ThreadPoolExecutor(max_workers=3) as pool:
    results = dict(pool.map(run, commands.items()))
after = identity()
qa = (OUT / 'final2-qa-suite.log').read_text()
observed = {
    'qa_test_count': int(re.search(r'^Ran (\d+) tests in ', qa, re.M).group(1)),
    'qa_final_ok': qa.rstrip().endswith('\nOK'),
    'self_test_status': json.loads((OUT / 'final2-caller-self-test.log').read_text())['status'],
}
verification = json.loads((OUT / 'final2-caller-verify.log').read_text())
observed.update({
    'caller_status': verification['status'],
    'caller_boundaries': len(verification['boundaries']),
    'rust_files_scanned': verification['rustFilesScanned'],
    'authority_granted': verification['authorityGranted'],
})
accepted = (
    all(result['exit_code'] == 0 for result in results.values())
    and before == after
    and prior_sha == sha(PRIOR.read_bytes())
    and observed == {
        'qa_test_count': 22,
        'qa_final_ok': True,
        'self_test_status': 'PASS_HEPTA_CALLER_PROOF_SELF_TEST',
        'caller_status': 'PASS_HEPTA_CALLER_CLOSED_SET',
        'caller_boundaries': 52,
        'rust_files_scanned': 5604,
        'authority_granted': False,
    }
)
document = {
    'phase': 'final2: original Python source gates on the frozen 30-path follow-up overlay after all reviewed helper changes',
    'started_at_utc': started,
    'completed_at_utc': datetime.now(timezone.utc).isoformat(),
    'cwd': str(ROOT),
    'environment': {'PYTHONDONTWRITEBYTECODE': '1'},
    'source_is_reviewed_worktree_overlay': True,
    'source_before': before,
    'source_after': after,
    'inputs_unchanged': before == after,
    'results': results,
    'observed': observed,
    'source_gate_result': 'PASS' if accepted else 'FAIL',
    'earlier_final1_receipt': PRIOR.name,
    'earlier_final1_receipt_sha256': prior_sha,
    'earlier_final1_receipt_unchanged': prior_sha == sha(PRIOR.read_bytes()),
    'original_commands_and_assertions_unchanged': True,
    'rust_compilation_or_native_tests_executed_by_this_run': False,
    'product_qualification': False,
    'whole_chain_pq_qualification': False,
}
RECEIPT.write_text(json.dumps(document, indent=2) + '\n')
print(json.dumps({'receipt': str(RECEIPT), 'sha256': sha(RECEIPT.read_bytes()), 'source_gate_result': document['source_gate_result'], 'observed': observed, 'inputs_unchanged': before == after, 'exit_codes': {k:v['exit_code'] for k,v in results.items()}}))
raise SystemExit(0 if accepted else 1)
