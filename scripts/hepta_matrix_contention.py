"""Fixed diagnostic experiment, not a release qualification or a retry loop."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import unquote, urlparse

import hepta_ci_candidate

TARGET = '//codex-rs/hepta-matrix-sdk:hepta-matrix-sdk-sdk_store_upgrade-test'
PHASES = (('isolated-before', 1, 1), ('contended-three', 3, 3), ('isolated-after', 1, 1))
MAX_LOG = 32 * 1024**2
MAX_BEP = 16 * 1024**2
MAX_TEST_FILE = 4 * 1024**2


def source_identity() -> dict:
    changed = subprocess.check_output(['git', 'diff', '--name-only', 'd3c488569dfa23145172f7acff323ca861f1df8f', 'HEAD'], text=True).splitlines()
    if set(changed) != {'.github/workflows/windows-matrix-sdk-contention.yml', 'scripts/hepta_matrix_contention.py'}:
        raise ValueError('unexpected source delta from exact diagnostic control')
    if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal']):
        raise ValueError('source must remain clean')
    return hepta_ci_candidate.candidate_plan(source=os.environ['SOURCE_SHA'], tested=os.environ['TESTED_SHA'], lane='source-head')


def command(verb: str, evidence: Path, runs: int = 1, concurrent: int = 1) -> list[str]:
    bash = Path(os.environ['HEPTA_BAZEL_BASH'])
    if bash.name.lower() == 'bash':
        bash = bash.with_name(bash.name + '.exe')
    if not bash.is_absolute() or bash.name.lower() != 'bash.exe' or not bash.is_file():
        raise ValueError('captured native Git Bash is required')
    result = [str(bash), '.github/scripts/run-bazel-ci.sh', '--windows-msvc-host-platform',
              '--remote-download-toplevel', '--', verb, '--platforms=//:windows_x86_64_msvc',
              '--jobs=3', '--local_resources=cpu=4',
              '--build_metadata=COMMIT_SHA=' + os.environ['TESTED_SHA'],
              '--build_event_json_file=' + (evidence / 'events.jsonl').as_posix()]
    if verb == 'test':
        result += ['--nocache_test_results', '--flaky_test_attempts=1', f'--runs_per_test={runs}',
                   f'--local_test_jobs={concurrent}', '--test_output=all',
                   '--test_env=HEPTA_MATRIX_STARTUP_DIAGNOSTICS=1',
                   '--test_tag_filters=-argument-comment-lint']
    return [*result, '--', TARGET]


def run_command(argv: list[str], destination: Path) -> dict:
    destination.mkdir(exist_ok=False)
    before = source_identity()
    record = {'source_before': before, 'command': argv, 'state': 'running', 'started_unix_ms': time.time_ns() // 1_000_000}
    receipt = destination / 'command.json'
    receipt.write_text(json.dumps(record))
    start = time.monotonic()
    kept = 0
    truncated = False
    with (destination / 'command.log').open('xb') as log, subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as child:
        while chunk := os.read(child.stdout.fileno(), 65536):
            saved = chunk[:max(0, MAX_LOG - kept)]
            log.write(saved)
            kept += len(saved)
            truncated |= len(saved) != len(chunk)
            sys.stdout.buffer.write(saved)
            sys.stdout.buffer.flush()
        code = child.wait()
    record.update(state='completed', exit_code=code, elapsed_seconds=time.monotonic() - start,
                  capture_bytes=kept, capture_truncated=truncated, source_after=source_identity())
    receipt.write_text(json.dumps(record))
    if record['source_after'] != before or truncated:
        raise ValueError('source drift or truncated command evidence')
    return record


def overlap_count(intervals: list[tuple[int, int]]) -> int:
    events = [(start, 1) for start, end in intervals if end > start]
    events += [(end, -1) for start, end in intervals if end > start]
    active = maximum = 0
    for _, delta in sorted(events):
        active += delta
        maximum = max(maximum, active)
    return maximum


def retain_results(directory: Path, expected_runs: int) -> dict:
    bep = directory / 'events.jsonl'
    if bep.stat().st_size > MAX_BEP:
        raise ValueError('BEP exceeds retention bound')
    outputs = []
    summaries = []
    intervals = []
    runs = set()
    output_base = Path(os.environ['BAZEL_OUTPUT_BASE']).resolve()
    with bep.open(encoding='utf-8') as stream:
        for line in stream:
            if len(line) > 1024**2:
                raise ValueError('BEP event exceeds bound')
            event = json.loads(line)
            if event.get('id', {}).get('testSummary', {}).get('label') == TARGET:
                summaries.append(event['testSummary'])
            identity = event.get('id', {}).get('testResult', {})
            if identity.get('label') != TARGET:
                continue
            result = event['testResult']
            run = identity['run']
            if run in runs or identity.get('attempt', 1) != 1 or identity.get('shard', 1) != 1:
                raise ValueError('unexpected duplicate run, retry or shard')
            runs.add(run)
            if result.get('cachedLocally', False) or result.get('executionInfo', {}).get('cachedRemotely', False):
                raise ValueError('cached result cannot establish experiment')
            start = int(result['testAttemptStartMillisEpoch'])
            end = start + int(result['testAttemptDurationMillis'])
            intervals.append((start, end))
            saved = {}
            for output in result.get('testActionOutput', []):
                if output.get('name') not in ('test.log', 'test.xml'):
                    continue
                uri = urlparse(output['uri'])
                if uri.scheme != 'file' or uri.netloc:
                    raise ValueError('nonlocal test evidence')
                raw = unquote(uri.path)
                if re.match(r'^/[A-Za-z]:/', raw):
                    raw = raw[1:]
                path = Path(raw)
                if not path.resolve().is_relative_to(output_base) or not path.is_file() or path.is_symlink():
                    raise ValueError('unsafe test output path')
                with path.open('rb') as source:
                    data = source.read(MAX_TEST_FILE + 1)
                if len(data) > MAX_TEST_FILE:
                    raise ValueError('test output exceeds bound')
                target = directory / f'run-{run}-{output["name"]}'
                target.write_bytes(data)
                saved[output['name']] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
            outputs.append({'run': run, 'status': result['status'], 'start_unix_ms': start,
                            'end_unix_ms': end, 'outputs': saved})
    if len(summaries) != 1 or summaries[0].get('totalRunCount') != expected_runs or summaries[0].get('totalNumCached', 0) != 0:
        raise ValueError('missing summary, wrong count or cached summary')
    if runs != set(range(1, expected_runs + 1)) or any(set(x['outputs']) != {'test.log', 'test.xml'} for x in outputs):
        raise ValueError('missing exact test runs or raw log/XML')
    record = {'runs': outputs, 'maximum_observed_overlap': overlap_count(intervals),
              'all_passed': all(x['status'] == 'PASSED' for x in outputs)}
    (directory / 'results.json').write_text(json.dumps(record))
    return record



def summarize_experiment(results: dict) -> tuple[dict, int]:
    valid = set(results) == {name for name, _, _ in PHASES}
    for name, copies, concurrent in PHASES:
        evidence = results.get(name, {}).get('evidence', {})
        valid &= len(evidence.get('runs', [])) == copies
        valid &= evidence.get('maximum_observed_overlap') == concurrent
        valid &= 'evidence_error_category' not in evidence
        valid &= isinstance(evidence.get('all_passed'), bool)
    all_passed = all(
        results.get(name, {}).get('command_exit') == 0
        and results.get(name, {}).get('evidence', {}).get('all_passed') is True
        for name, _, _ in PHASES
    )
    if not valid:
        classification = 'invalid-or-incomplete-experiment'
    elif all_passed:
        classification = 'valid-experiment-no-failure-reproduced'
    elif any(results[name]['command_exit'] != 0 or not results[name]['evidence']['all_passed']
             for name in ('isolated-before', 'isolated-after')):
        classification = 'valid-experiment-isolated-control-failure'
    else:
        classification = 'valid-experiment-middle-phase-failure'
    summary = {'experiment_valid': valid, 'all_tests_passed': all_passed,
               'classification': classification, 'phases': results,
               'scope': 'diagnostic experiment only; prior full-shard causality remains unproven'}
    return summary, 0 if valid and all_passed else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['build', 'exercise', 'stage'])
    args = parser.parse_args()
    root = Path(os.environ['SDK_EVIDENCE']).resolve()
    if root.is_relative_to(Path.cwd().resolve()):
        raise ValueError('evidence must be outside source')
    if args.phase == 'stage':
        upload = root / 'upload'
        upload.mkdir(exist_ok=False)
        manifest = {}
        total = 0
        for phase in ('build', *(x[0] for x in PHASES)):
            allowed = ['command.json', 'command.log', 'events.jsonl', 'results.json']
            allowed += [f'run-{run}-{name}' for run in range(1, 4) for name in ('test.log', 'test.xml')]
            for name in allowed:
                source = root / phase / name
                limit = MAX_LOG if source.name == 'command.log' else MAX_BEP if source.name == 'events.jsonl' else MAX_TEST_FILE
                if not source.is_file() or source.is_symlink() or not source.resolve().is_relative_to(root):
                    continue
                with source.open('rb') as stream:
                    data = stream.read(limit + 1)
                name = phase + '/' + source.name
                if len(data) > limit:
                    manifest[name] = {'retained': False, 'reason': 'over bound'}
                    continue
                total += len(data)
                if total > 240 * 1024**2:
                    raise ValueError('aggregate upload bound exceeded')
                target = upload / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                manifest[name] = {'retained': True, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        for name in ('host.json', 'experiment.json', 'native-security-policy.json'):
            source = root / name
            if source.is_file() and source.stat().st_size <= 1024**2:
                (upload / name).write_bytes(source.read_bytes())
        (upload / 'manifest.json').write_text(json.dumps(manifest))
        return 0
    if os.cpu_count() != 4:
        raise ValueError('experiment requires exactly four logical CPUs; no automatic host changes')
    host = {'logical_cpus': os.cpu_count(), 'image_os': os.environ.get('ImageOS'),
            'image_version': os.environ.get('ImageVersion'), 'platform': sys.platform,
            'scheduler_cpu_budget': 4, 'maximum_simultaneous_test_copies': 3}
    host_file = root / 'host.json'
    if host_file.exists() and json.loads(host_file.read_text()) != host:
        raise ValueError('host properties changed between phases')
    host_file.write_text(json.dumps(host))
    if args.phase == 'build':
        return run_command(command('build', root / 'build'), root / 'build')['exit_code']
    results = {}
    for name, copies, concurrent in PHASES:
        directory = root / name
        record = run_command(command('test', directory, copies, concurrent), directory)
        try:
            evidence = retain_results(directory, copies)
        except (OSError, ValueError, KeyError) as error:
            evidence = {'evidence_error_category': type(error).__name__}
        results[name] = {'command_exit': record['exit_code'], 'evidence': evidence}
    summary, code = summarize_experiment(results)
    (root / 'experiment.json').write_text(json.dumps(summary))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
