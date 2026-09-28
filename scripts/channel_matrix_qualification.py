#!/usr/bin/env python3
"""Derive per-scenario native evidence; never promote target/operator acceptance."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import xml.etree.ElementTree as ET

from channel_matrix_evidence import file_digest, read_object, write_json
from channel_matrix_status import summarize

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = 'docs/modules/channel.matrix/QUALIFICATION_SCENARIOS.json'
SCENARIO_IDS = tuple(f'MATRIX-Q{i:02}' for i in range(1, 30))
MAX_JUNIT_BYTES = 32 * 1024 * 1024


def load_registry(path: Path) -> dict:
    row = read_object(path)
    if row.get('schema') != 'hepta.channel-matrix-scenarios.v1':
        raise ValueError('unsupported scenario registry')
    scenarios = row.get('scenarios')
    if not isinstance(scenarios, list):
        raise ValueError('scenario registry must contain a list')
    observed_ids = []
    seen = set()
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise ValueError('scenario must be an object')
        identity = scenario.get('id')
        if not isinstance(identity, str) or not re.fullmatch(r'MATRIX-Q\d{2}', identity) or identity in seen:
            raise ValueError('invalid or duplicate scenario')
        seen.add(identity)
        observed_ids.append(identity)
        if not isinstance(scenario.get('scenario'), str) or not scenario['scenario']:
            raise ValueError('scenario description is required')
        external = scenario.get('external_gates')
        tests = scenario.get('tests')
        if not isinstance(external, list) or not isinstance(tests, list):
            raise ValueError('scenario must declare both native and external scope')
        if any(not isinstance(gate, str) or not gate for gate in external) or len(external) != len(set(external)):
            raise ValueError('invalid or duplicate external gate')
        if not tests and not external:
            raise ValueError('scenario has neither native nor external evidence')
        for test in tests:
            if set(test) != {'binary', 'test', 'source'} or not all(isinstance(v, str) and v for v in test.values()):
                raise ValueError('invalid native test identity')
            source = Path(test['source'])
            if source.is_absolute() or '..' in source.parts or not source.as_posix().startswith('codex-rs/hepta-'):
                raise ValueError('unsafe test source')
    if tuple(observed_ids) != SCENARIO_IDS:
        raise ValueError('scenario inventory is incomplete, out of order or open-ended')
    return row


def parse_junit(payload: bytes) -> dict[tuple[str, str], str]:
    # XML expansion and alternate encodings are unnecessary for nextest output.
    if len(payload) > MAX_JUNIT_BYTES:
        raise ValueError('JUnit exceeds budget')
    text = payload.decode('utf-8')
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise ValueError('DTD/entity declarations are forbidden')
    root = ET.fromstring(text)
    if root.tag != 'testsuites':
        raise ValueError('expected nextest testsuites')
    observed = {}
    for suite in root.findall('testsuite'):
        binary = suite.get('name')
        if not binary:
            raise ValueError('missing binary identity')
        for test in suite.findall('testcase'):
            name = test.get('name')
            key = (binary, name)
            if not name or key in observed or len(observed) >= 100_000:
                raise ValueError('missing/duplicate test or test budget exceeded')
            tags = {child.tag for child in test}
            if tags & {'failure', 'error', 'rerunFailure', 'rerunError'}:
                state = 'failed'
            elif 'skipped' in tags:
                state = 'skipped'
            elif tags & {'flakyFailure', 'flakyError'}:
                state = 'flaky'
            else:
                state = 'passed'
            observed[key] = state
    if not observed:
        raise ValueError('zero executed or reported tests')
    return observed


def ledger(directory: Path, registry_path: Path) -> dict:
    registry = load_registry(registry_path)
    status = summarize(directory)  # Validates command argv, SHA, source and log hashes.
    observed = {}
    junit_evidence = None
    command_evidence = None
    source_evidence = None
    source = None
    if (directory / 'source.json').is_file():
        source_path = directory / 'source.json'
        source = read_object(source_path)
        registry_rows = [item for item in source.get('files', []) if item.get('path') == REGISTRY]
        if len(registry_rows) != 1 or registry_rows[0].get('sha256') != file_digest(registry_path):
            raise ValueError('registry is not bound to tested source')
        source_evidence = {
            'path': source_path.name,
            'bytes': source_path.stat().st_size,
            'sha256': file_digest(source_path),
        }
    command = directory / 'focused-tests.command.json'
    if command.exists():
        receipt = read_object(command)
        command_evidence = {
            'path': command.name,
            'bytes': command.stat().st_size,
            'sha256': file_digest(command),
        }
        junit_evidence = receipt.get('junit')
        if junit_evidence is not None:
            if (source is None or status['states']['native_tests'] not in ('passed', 'failed')
                    or receipt.get('sourceUnchanged') is not True
                    or file_digest(directory / 'source.json') != file_digest(directory / 'source-after.json')):
                raise ValueError('JUnit without completed exact-candidate command')
            report = directory / 'focused-tests.junit.xml'
            expected = {'path': report.name, 'bytes': report.stat().st_size, 'sha256': file_digest(report)}
            if junit_evidence != expected:
                raise ValueError('JUnit does not match command receipt')
            observed = parse_junit(report.read_bytes())
    candidate = None if source is None else {'commit': source['testedSha'], 'tree': source['testedTree']}
    rows = []
    for scenario in registry['scenarios']:
        tests = []
        for test in scenario['tests']:
            # Missing fixtures never inherit an aggregate green command.
            state = observed.get((test['binary'], test['test']), 'not_executed')
            if source is not None and not any(item.get('path') == test['source'] for item in source['files']):
                raise ValueError('test source is outside the tested inventory')
            evidence = None
            if state != 'not_executed' and junit_evidence is not None:
                evidence = {
                    'artifact': junit_evidence,
                    'testcase': {'binary': test['binary'], 'test': test['test']},
                }
            tests.append({**test, 'result': state, 'evidence': evidence})
        results = [test['result'] for test in tests]
        native = ('failed' if 'failed' in results else 'flaky' if 'flaky' in results else
                  'skipped' if 'skipped' in results else
                  'passed' if results and all(result == 'passed' for result in results) else 'not_executed')
        rows.append({'id': scenario['id'], 'candidate': candidate,
                     'native_required': bool(tests), 'native_fixture_result': native, 'tests': tests,
                     'external_gates': scenario['external_gates'],
                     'external_qualification': 'not_proved' if scenario['external_gates'] else 'not_applicable'})
    blockers = [row['id'] for row in rows
                if row['native_required'] and row['native_fixture_result'] != 'passed']
    command_state = status['states']['native_tests']
    native_completion = ('passed' if candidate is not None and command_state == 'passed' and not blockers
                         else 'incomplete')
    external_gates = sorted({gate for row in rows for gate in row['external_gates']})
    return {'schema': 'hepta.channel-matrix-scenario-ledger.v2',
            'scope': 'exact_candidate_native_fixture_results_not_target_acceptance',
            'candidate': candidate,
            'lane': None if source is None else source['lane'],
            'registry_sha256': file_digest(registry_path),
            'evidence': {'source_snapshot': source_evidence,
                         'focused_command': command_evidence,
                         'junit': junit_evidence},
            'command_states': status['states'],
            'native_completion': native_completion,
            'native_blockers': blockers,
            'external_gates_remaining': external_gates,
            'scenarios': rows,
            'independent_acceptance': False, 'activation': False, 'release': False,
            'authority_granted': False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--registry', type=Path, default=ROOT / REGISTRY)
    args = parser.parse_args()
    try:
        row = ledger(args.directory, args.registry)
        write_json(args.directory / 'scenario-ledger.json', row)
        # Every registry-mapped native case is required in both exact-candidate lanes.
        return 0 if row['native_completion'] == 'passed' else 1
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError):
        write_json(args.directory / 'scenario-ledger.json', {
            'schema': 'hepta.channel-matrix-scenario-ledger.v2', 'status': 'invalid_evidence',
            'authority_granted': False, 'release': False})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
