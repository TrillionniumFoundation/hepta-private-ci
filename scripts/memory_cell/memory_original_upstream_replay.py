#!/usr/bin/env python3
"""Original CPython test methods against immutable Git http.client, offline.

This diagnostic verifies execution, fault sensitivity, and a clean-process
rollback control. It does not execute the full CPython suite, fix a real bug,
run a pretrained Reader, or measure MemoryCell learning/task benefit.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import resource
import subprocess
import sys
import tempfile

from memory_original_upstream_worker import CASES, FAULTS, MODULE_SHA, SCHEMA, TEST_SHA
from real_source_reader_probe import (
    REOPEN_SHA,
    SOURCE_SHA,
    canonical,
    digest,
    real_source,
    require,
    write_once,
)

PROFILE = 'hepta.memory.original-cpython-upstream-diagnosis.v1'
WORKER_SHA256 = '1c183ce9e378796bd102f627d77059ac387e2cb6564ea908751155fa54fbb887'
SRC_MODULE = ('python/cpython', 'Lib/http/client.py')
SRC_TEST = ('python/cpython', 'Lib/test/test_httplib.py')
EXPECTED_FAULTS = {
    'corrupt-header': ['HeaderTests.test_putheader'],
    'corrupt-send': ['BasicTest.test_send'],
}
PROFILES = ('none', 'corrupt-header', 'corrupt-send', 'none', 'none')
PHASES = ('baseline', 'header-fault', 'send-fault', 'rollback-header', 'rollback-send')


def _bounds():
    # Linux child only: run original verified Git source under a fixed CPU budget.
    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def method_provenance(original_test_bytes: bytes) -> list[dict]:
    require(digest(original_test_bytes) == TEST_SHA,
            'original CPython upstream unit-test SHA mismatch')
    tree = ast.parse(original_test_bytes)
    definitions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name in ('HeaderTests', 'BasicTest')
    }
    require(set(definitions) == {'HeaderTests', 'BasicTest'},
            'original upstream test class inventory incomplete')
    text = original_test_bytes.decode('utf-8')
    records = []
    for name, method in CASES:
        original = [node for node in definitions[name].body
                    if isinstance(node, ast.FunctionDef) and node.name == method]
        require(len(original) == 1 and not original[0].decorator_list,
                'upstream test method missing/ambiguous/changed')
        records.append(dict(case=name + '.' + method,
                            start_line=original[0].lineno,
                            method_sha256=digest(ast.get_source_segment(text, original[0]).encode())))
    return sorted(records, key=lambda row: (0 if row["case"].startswith("HeaderTests.") else 1, row["start_line"]))


def independent_check(payload: dict, phase: str, upstream: list[dict]):
    require(phase in PHASES and isinstance(payload, dict), 'invalid original execution phase')
    expected_fault = {'baseline': 'none', 'header-fault': 'corrupt-header',
                      'send-fault': 'corrupt-send',
                      'rollback-header': 'none', 'rollback-send': 'none'}[phase]
    expected_ids = [f'{a}.{b}' for a, b in CASES]
    expected_failed = EXPECTED_FAULTS.get(expected_fault, [])
    expected_passes = [x for x in expected_ids if x not in expected_failed]
    require(payload.get('schema') == SCHEMA
            and payload.get('original_source_sha256') == MODULE_SHA
            and payload.get('original_upstream_tests_sha256') == TEST_SHA
            and payload.get('original_test_method_sources') == upstream
            and payload.get('planned_original_test_ids') == expected_ids
            and payload.get('exact_original_test_methods') == len(expected_ids)
            and payload.get('executed_original_test_methods') == len(expected_ids)
            and payload.get('fault') == expected_fault
            and payload.get('passed') == expected_passes
            and payload.get('failed') == expected_failed
            and payload.get('errors') == []
            and payload.get('skipped') == []
            and payload.get('original_module_loaded') is True
            and payload.get('original_test_methods_unmodified') is True
            and payload.get('actual_original_upstream_test_source_executed') is True
            and payload.get('entire_original_upstream_test_suite_executed') is False
            and payload.get('tests_rewritten_to_pass') is False
            and payload.get('network_permitted') is False
            and payload.get('pretrained_reader_calls') == 0
            and payload.get('production_qualified') is False,
            'source-backed original CPython execution or fault detection changed')
    return dict(phase=phase, fault=expected_fault, run=len(expected_ids),
                passed=len(expected_passes), failed=expected_failed,
                original_method_ids=expected_ids,
                source_receipt_sha256=digest(canonical(payload) + b'\n'))


def execute(sources: tuple, worker_path: Path | None = None,
            journal_dir: Path | None = None):
    files, blobs = sources
    by_file = {(row['repo'], row['path']): row for row in files}
    require(SRC_MODULE in by_file and SRC_TEST in by_file,
            'two original Git source entries required')
    for identity, expected in ((SRC_MODULE, MODULE_SHA), (SRC_TEST, TEST_SHA)):
        value = blobs.get(identity)
        require(isinstance(value, bytes) and digest(value) == expected
                and by_file[identity]['sha256'] == expected
                and by_file[identity]['partition'] == 'evaluation',
                'original evaluation Git snapshot mutated')
    provenance = method_provenance(blobs[SRC_TEST])
    worker = worker_path or Path(__file__).with_name('memory_original_upstream_worker.py')
    require(worker.is_file() and not worker.is_symlink()
            and digest(worker.read_bytes()) == WORKER_SHA256,
            'execution worker differs from pre-registered SHA')
    executions = []
    if journal_dir is not None:
        require(not journal_dir.exists() and not journal_dir.is_symlink(),
                'create-only original journal directory required')
        journal_dir.mkdir(parents=False)
    with tempfile.TemporaryDirectory(prefix='hepta-original-cpython-selected-') as tmp:
        td = Path(tmp)
        module_path = td / 'pinned_original_http_client.py'
        upstream_path = td / 'pinned_original_test_httplib.py'
        module_path.write_bytes(blobs[SRC_MODULE])
        upstream_path.write_bytes(blobs[SRC_TEST])
        for phase, fault in zip(PHASES, PROFILES, strict=True):
            # Independent fresh child per arm; a fault cannot persist into rollback.
            args = [sys.executable, '-I', '-S', '-B', str(worker.resolve()),
                    str(module_path), str(upstream_path), fault]
            completed = subprocess.run(
                args, cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=18, check=False, preexec_fn=_bounds,
                env={'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': '1'},
            )
            require(completed.returncode == 0 and completed.stderr == b''
                    and 0 < len(completed.stdout) < 64_000
                    and completed.stdout.endswith(b'\n')
                    and len(completed.stdout.splitlines()) == 1,
                    'original upstream worker failed/overflowed/ambiguous')
            # JSON decoder rejects duplicate keys and nonfinite numbers.
            from real_source_reader_probe import strict_json
            receipt = strict_json(completed.stdout)
            executions.append(independent_check(receipt, phase, provenance))
            if journal_dir is not None:
                write_once(journal_dir / (phase + '.json'), completed.stdout)
    require(len(executions) == 5, 'five original upstream causal/rollback phases required')
    return _report(provenance, executions)


def _report(provenance: list[dict], executions: list[dict]):
    require(len(executions) == 5 and [v['phase'] for v in executions] == list(PHASES),
            'missing or reordered original test execution evidence')
    return dict(
        schema=PROFILE,
        original_source_zip_sha256=SOURCE_SHA,
        independent_binary_reopen_zip_sha256=REOPEN_SHA,
        original_module_sha256=MODULE_SHA,
        original_test_file_sha256=TEST_SHA,
        frozen_test_worker_sha256=WORKER_SHA256,
        predeclared_original_upstream_tests=provenance,
        unique_original_test_methods=len(CASES),
        executable_phases=PHASES,
        per_phase_original_test_invocations=len(CASES),
        total_original_test_invocations=len(CASES) * len(PROFILES),
        executions=executions,
        baseline_original_tests_passed=len(CASES),
        injected_behavioral_faults_detected=2,
        injected_behavioral_faults_total=2,
        clean_process_rollback_controls_passed=2,
        clean_process_rollback_controls_total=2,
        original_source_and_tests_unchanged=True,
        original_upstream_test_methods_rewritten=False,
        original_upstream_full_suite_executed=False,
        fault_detection_is_not_autonomous_repair=True,
        real_program_bug_repair_success=None,
        independent_future_task_families=0,
        pretrained_model_calls=0,
        learned_memory_task_gain=None,
        semantic_citation_judgement=None,
        maintenance_cost=None,
        revocation_cost=None,
        complete_lifecycle_tco=None,
        production_qualified=False,
    )


def independent_rescore(sources: tuple, journal_dir: Path) -> dict:
    require(journal_dir.is_dir() and not journal_dir.is_symlink(),
            'original sealed journal directory required')
    require({p.name for p in journal_dir.iterdir()} == {phase + '.json' for phase in PHASES},
            'complete original five-phase journal set required')
    files, blobs = sources
    by_file = {(row['repo'], row['path']): row for row in files}
    require(all(identity in by_file and identity in blobs
                and by_file[identity]['partition'] == 'evaluation'
                and digest(blobs[identity]) == expected
                for identity, expected in ((SRC_MODULE, MODULE_SHA), (SRC_TEST, TEST_SHA))),
            'original evaluator source files changed')
    provenance = method_provenance(blobs[SRC_TEST])
    worker = Path(__file__).with_name('memory_original_upstream_worker.py')
    require(worker.is_file() and not worker.is_symlink()
            and digest(worker.read_bytes()) == WORKER_SHA256,
            'original worker code SHA changed before independent scoring')
    executions = []
    from real_source_reader_probe import strict_json
    for phase in PHASES:
        path = journal_dir / (phase + '.json')
        require(path.is_file() and not path.is_symlink() and path.stat().st_size < 64_000,
                'original receipt file unavailable/oversized')
        raw = path.read_bytes()
        payload = strict_json(raw)
        require(canonical(payload) + b'\n' == raw,
                'original receipt bytes modified or ambiguous')
        executions.append(independent_check(payload, phase, provenance))
    return _report(provenance, executions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('run', 'score'))
    parser.add_argument('--source-zip', type=Path, required=True)
    parser.add_argument('--reopen-zip', type=Path, required=True)
    parser.add_argument('--journals', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sources = real_source(args.source_zip, args.reopen_zip)
    report = (execute(sources, journal_dir=args.journals) if args.mode == 'run'
              else independent_rescore(sources, args.journals))
    write_once(args.output, canonical(report) + b'\n')
    print(json.dumps(dict(original_tests=len(CASES), actual_faults_detected=2,
                          complete_original_upstream_suite=False,
                          pretrained_model_calls=0, production_qualified=False),
                     sort_keys=True))


if __name__ == '__main__':
    main()
