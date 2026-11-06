#!/usr/bin/env python3
"""Exercise only the actual workflow's output guard against labelled fixtures.

No fixture is a Rust test result or a qualification result. Frozen source remains
unchanged; this file and all outputs live outside either repository worktree.
"""
from pathlib import Path
import ast
import difflib
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import textwrap
import yaml

ROOT = Path(__file__).resolve().parent
NAME = '.github/workflows/pon-w1-work-security.yml'
SOURCE = ROOT.parent / 'C2-reuse-audit/trillionnium/crates/trnm-crypto-primitives/src/pon_work/legal_attempt.rs'
OUTPUT = ROOT / 'guard-controls'

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()

def source_guard(document):
    step = next(s for s in document['jobs']['legal-factorial']['steps']
                if s['name'] == 'Execute native producer, header, History and CPU cancellation controls')
    before, rest = step['run'].split("python3 - \"$OUT\" <<'PYTEST'\n", 1)
    body, after = rest.split('\nPYTEST', 1)
    ast.parse(body)
    return step, before, body, after

def main():
    OUTPUT.mkdir(exist_ok=False)
    base_raw = (ROOT / 'base' / NAME).read_bytes()
    candidate_raw = (ROOT / 'candidate' / NAME).read_bytes()
    assert blob(base_raw) == 'aa9d7597904d2d0bec32a502160c46ae255381be'
    documents = [yaml.safe_load(raw) for raw in (base_raw, candidate_raw)]
    guards = [source_guard(d) for d in documents]
    # Every runner, resource, command, budget and unrelated step is identical.
    assert guards[0][1] == guards[1][1] and guards[0][3] == guards[1][3]
    guards[1][0]['run'] = guards[0][0]['run']
    assert documents[0] == documents[1]
    source_raw = SOURCE.read_bytes()
    assert blob(source_raw) == 'b1c5952de1a4b957f85f418d3e6ab66d8a64607a'
    names = re.findall(r'#\[test\]\s+fn ([a-zA-Z0-9_]+)\(', source_raw.decode())
    assert len(names) == len(set(names)) == 9
    body = guards[1][2]
    assert all(repr(name) in body for name in names)
    specs = {'factorial-kernel-tests': (9, 0), 'factorial-example-tests': (6, 0),
             'header-binding-tests': (1, 0), 'history-w1-tests': (5, 0),
             'history-import-tests': (28, 1), 'cpu-completion-tests': (11, 0)}
    history_names = ['ingress::history_import::tests::deadline_controls::' + n for n in (
        'final_resource_completion_preserves_error_priority_and_original_deadline',
        'final_resource_expiry_keeps_committed_history_and_settled_cpu')]
    history_names.append('ingress::history_import::tests::history_codec_snapshot_preserves_legacy_bytes_identity_and_deferred_profile_errors')
    kernel = lambda n: 'pon_work::legal_attempt::tests::' + n
    fixtures = [
        ('base-original-six', 0, names[:6], 6, True),
        ('base-real-nine-rejected', 0, names, 9, False),
        ('candidate-all-nine', 1, names, 9, True),
        ('candidate-original-six-rejected', 1, names[:6], 6, False),
        ('candidate-missing-original-rejected', 1, names[1:], 9, False),
        ('candidate-missing-new-rejected', 1, names[:-1], 9, False),
        ('candidate-duplicate-original-rejected', 1, names + [names[0]], 9, False),
        ('candidate-duplicate-new-rejected', 1, names + [names[-1]], 9, False),
    ]
    observations = []
    for label, version, selected, count, expected in fixtures:
        fixture = OUTPUT / label
        fixture.mkdir()
        for name, (passed, ignored) in specs.items():
            actual = count if name == 'factorial-kernel-tests' else passed
            prefix = ''.join('test ' + kernel(n) + ' ... ok\n' for n in selected) if name == 'factorial-kernel-tests' else ''
            if name == 'history-import-tests':
                prefix = ''.join('test ' + n + ' ... ok\n' for n in history_names)
            (fixture / (name + '.log')).write_text(prefix + f'test result: ok. {actual} passed; 0 failed; {ignored} ignored; 0 measured; 0 filtered out; finished in 0.00s\n')
        script = fixture / 'extracted-workflow-guard.py'
        script.write_text(guards[version][2])
        result = subprocess.run([sys.executable, '-B', str(script), str(fixture)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        (fixture / 'stdout').write_bytes(result.stdout)
        (fixture / 'stderr').write_bytes(result.stderr)
        observations.append(dict(name=label, fixture_only=True, exit_code=result.returncode,
            expected_acceptance=expected, passed=(result.returncode == 0) == expected,
            stdout_sha256=digest(result.stdout), stderr_sha256=digest(result.stderr)))
    corpus = (ROOT / 'read-base/config/pon/pq-cross-branch-corpus-v1.json').read_bytes()
    assert blob(corpus) == 'c8486ca9cce475d429b2a3b4bc43ce9ffec57ddc'
    assert NAME not in corpus.decode()
    report = dict(schema='chain-c3-legal-factorial-registration-component-v1',
        candidate_committed=False, native_tests_executed=False,
        parent_commit='03521b2f32346a49cccde8ff72e8c7b886b31222',
        changed_files=[dict(path=NAME, base_git_blob=blob(base_raw),
            candidate_git_blob=blob(candidate_raw), sha256=digest(candidate_raw))],
        retained_original_names=names[:6], additional_names=names[6:],
        exact_filtered_source_tests=names, original_budget_commands_resources_unchanged=True,
        pq_corpus_workflow_pin_present=False, pq_corpus_changed=False,
        source_inventory_changed=False, observations=observations,
        passed=all(o['passed'] for o in observations),
        qualification_status='HOLD', production_activation=False)
    (OUTPUT / 'manifest.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report['passed'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
