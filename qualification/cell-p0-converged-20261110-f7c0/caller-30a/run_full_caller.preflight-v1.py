#!/usr/bin/env python3
"""One exact-source caller verification with separate raw output and costs."""

import datetime
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time


ROOT = Path('/workspace/scratch/f7c0ded86bcc/hepta-p0-learn-merge')
OUT = Path('/workspace/scratch/f7c0ded86bcc/p0_final_caller_audit_30a697c_20261111')
SOURCE = '30a697c50e10abd56e61b6b84f28ac9ae9f32f5d'
TREE = 'b2a21d98380340b1c091006f4130aafdbeabca50'
BRANCH = 'codex/cell-p0-final-caller-30a697-f7c0'
PRIOR_BRANCH = 'codex/cell-p0-final-caller-audit-f7c0'
PRIOR_SOURCE = 'cb0598a9099a0d828ce73aedb51e397e600e49d1'
PRIOR_RECEIPT = Path('/workspace/scratch/f7c0ded86bcc/p0_final_caller_audit_cb0598_20261111')
REVIEW_PATH = Path('/workspace/scratch/f7c0ded86bcc/p0_independent_ci_fix_reviews_20261111/INDEPENDENT_REVIEWS.json')
INVOCATION = 'p0-30a697c-full-caller-scan-20261111-v1'
COMMAND = ['python3', 'scripts/verify_hepta_callers.py', 'verify', '--root', str(ROOT)]


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write_json(name, value):
    destination = OUT / name
    temporary = OUT / (name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(destination)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def file_identity(path):
    raw = path.read_bytes()
    return {'bytes': len(raw), 'sha256': digest(raw)}


review = json.loads(REVIEW_PATH.read_bytes())
expected_files = {
    item['path']: {'bytes': item['bytes'], 'sha256': item['sha256']}
    for review_item in review['reviews']
    for item in review_item['files']
}


def snapshot(label):
    status = git('status', '--porcelain=v1', '-z', '--untracked-files=all')
    (OUT / (label.lower() + '-status.raw')).write_bytes(status)
    records = git('ls-tree', '-r', '-z', '--full-tree', SOURCE)
    source_files = {name: file_identity(ROOT / name) for name in sorted(expected_files)}
    prior_files = [
        {'file': path.name, **file_identity(path)}
        for path in sorted(PRIOR_RECEIPT.iterdir()) if path.is_file()
    ]
    value = {
        'schema': 'hepta_exact_source_scan_identity_v1',
        'observed_at_utc': utc_now(),
        'checkout': str(ROOT),
        'head': git('rev-parse', 'HEAD').decode().strip(),
        'tree': git('rev-parse', 'HEAD^{tree}').decode().strip(),
        'parent': git('rev-parse', 'HEAD^').decode().strip(),
        'branch': git('branch', '--show-current').decode().strip(),
        'clean': not status,
        'status_raw_file': label.lower() + '-status.raw',
        'status_bytes': len(status),
        'status_sha256': digest(status),
        'tracked_tree_records': {'command': ['git', 'ls-tree', '-r', '-z', '--full-tree', SOURCE], 'count': records.count(b'\0'), 'bytes': len(records), 'sha256': digest(records)},
        'source_files': source_files,
        'matches_prior_nine_file_reviews': source_files == expected_files,
        'callers': {'path': 'CALLERS.toml', **file_identity(ROOT / 'CALLERS.toml')},
        'verifier': {'path': 'scripts/verify_hepta_callers.py', **file_identity(ROOT / 'scripts/verify_hepta_callers.py')},
        'preserved_cb_branch': {'name': PRIOR_BRANCH, 'head': git('rev-parse', PRIOR_BRANCH).decode().strip()},
        'preserved_prior_receipt': {'path': str(PRIOR_RECEIPT), 'file_count': len(prior_files), 'files': prior_files},
    }
    write_json(label + '.json', value)
    return value


def verify_snapshot(value):
    assert value['head'] == SOURCE, 'source HEAD changed'
    assert value['tree'] == TREE, 'source tree changed'
    assert value['parent'] == PRIOR_SOURCE, 'unexpected source parent'
    assert value['branch'] == BRANCH, 'source branch changed'
    assert value['clean'], 'source worktree is not clean'
    assert value['matches_prior_nine_file_reviews'], 'reviewed source bytes differ'
    assert value['preserved_cb_branch']['head'] == PRIOR_SOURCE, 'prior branch changed'


before = snapshot('BEFORE')
verify_snapshot(before)
attempt = {
    'schema': 'hepta_single_caller_invocation_v1',
    'invocation_id': INVOCATION,
    'source': SOURCE,
    'tree': TREE,
    'cwd': str(ROOT),
    'argv': COMMAND,
    'python_command_resolves_to': shutil.which('python3'),
    'runner_python': sys.executable,
    'runner_python_version': sys.version,
    'runner_pid': os.getpid(),
    'created_at_utc': utc_now(),
    'scope': 'Complete verify command, not inventory-only. No native build/test or production authorization.',
}
with (OUT / 'ATTEMPT.json').open('x', encoding='utf-8') as stream:
    json.dump(attempt, stream, indent=2)
    stream.write('\n')

started_at = utc_now()
started_monotonic = time.monotonic()
usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
with (OUT / 'stdout.raw').open('wb') as stdout, (OUT / 'stderr.raw').open('wb') as stderr:
    child = subprocess.Popen(COMMAND, cwd=ROOT, stdout=stdout, stderr=stderr)
    attempt['verifier_pid'] = child.pid
    attempt['started_at_utc'] = started_at
    write_json('ATTEMPT.json', attempt)
    print(json.dumps({'state': 'RUNNING', 'invocation_id': INVOCATION, 'pid': child.pid, 'source': SOURCE, 'started_at_utc': started_at}), flush=True)
    with (OUT / 'HEARTBEATS.jsonl').open('a', encoding='utf-8') as heartbeats:
        while True:
            try:
                exit_code = child.wait(timeout=30)
                break
            except subprocess.TimeoutExpired:
                heartbeat = {
                    'at_utc': utc_now(),
                    'elapsed_seconds': time.monotonic() - started_monotonic,
                    'state': 'RUNNING',
                    'pid': child.pid,
                    'stdout_bytes': (OUT / 'stdout.raw').stat().st_size,
                    'stderr_bytes': (OUT / 'stderr.raw').stat().st_size,
                }
                heartbeats.write(json.dumps(heartbeat) + '\n')
                heartbeats.flush()
                print(json.dumps(heartbeat), flush=True)
    ended_monotonic = time.monotonic()
    ended_at = utc_now()
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)

costs = {
    'wall_seconds': ended_monotonic - started_monotonic,
    'child_user_cpu_seconds': usage_after.ru_utime - usage_before.ru_utime,
    'child_system_cpu_seconds': usage_after.ru_stime - usage_before.ru_stime,
    'child_cpu_seconds_total': (usage_after.ru_utime - usage_before.ru_utime) + (usage_after.ru_stime - usage_before.ru_stime),
    'measurement': 'monotonic wall time and RUSAGE_CHILDREN deltas surrounding the one verifier subprocess, before post-run Git reads',
    'excluded': ['preparation/fetch/switch', 'before/after source snapshots', 'assistant orchestration and communication', 'other agents/CI', 'archive construction'],
    'unmeasured': ['monetary cost', 'energy', 'whole-session resource cost'],
}
execution = {
    **attempt,
    'ended_at_utc': ended_at,
    'exit_code': exit_code,
    'costs': costs,
    'stdout': {'file': 'stdout.raw', **file_identity(OUT / 'stdout.raw')},
    'stderr': {'file': 'stderr.raw', **file_identity(OUT / 'stderr.raw')},
    'identity_verification': 'PENDING_POST_RUN_SNAPSHOT',
}
write_json('EXECUTION.json', execution)
after = snapshot('AFTER')
verify_snapshot(after)
same_keys = ['head', 'tree', 'parent', 'branch', 'clean', 'status_bytes', 'status_sha256', 'tracked_tree_records', 'source_files', 'callers', 'verifier', 'preserved_cb_branch', 'preserved_prior_receipt']
unchanged = {key: before[key] == after[key] for key in same_keys}
assert all(unchanged.values()), 'input identity or prior receipt changed during scan'
execution['identity_verification'] = 'PASS_EXACT_SOURCE_AND_PRESERVED_PRIOR_RECEIPT'
execution['unchanged_before_after'] = unchanged
write_json('EXECUTION.json', execution)
print(json.dumps({'state': 'COMPLETED', 'exit_code': exit_code, 'identity': execution['identity_verification'], 'costs': costs, 'stdout': execution['stdout'], 'stderr': execution['stderr']}), flush=True)
sys.exit(exit_code)
