#!/usr/bin/env python3
"""Retain the original-binary diagnosis separately from v4 qualification."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import stat
import xml.etree.ElementTree as ET
import zipfile

import msgpack


ROOT = Path('/workspace/scratch/95988d8d3ab1')
OWN = ROOT / 'ndu-matrix-reopen-diagnosis-v4-001'
REMOTE = ROOT / 'ndu-port-remote-3a779a6'
REPO = ROOT / 'hepta-private-ci'
OUT = REPO / 'experiments/multimodal_output_portfolio/closure_v2_20261027/ci/port-remediation/v4-evidence/matrix-reopen-diagnosis'


def identity(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(data)
    return {'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}


def file_tree(root):
    return {str(path.relative_to(root)): identity(path)
            for path in sorted(root.rglob('*')) if path.is_file()}


OUT.mkdir(exist_ok=False)
copied = {}


def retain(source, relative):
    destination = OUT / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    assert identity(destination) == identity(source)
    copied[relative] = identity(destination)


retain(Path(__file__), 'capture-source.py')
retain(OWN / 'DB_SCHEMAS.json', 'DB_SCHEMAS.json')
for name in ('run_sealed_binary.py', 'run_sealed_binary_002.py',
             'run_sealed_binary_003.py', 'inspect_sealed_symbols_004.py',
             'run_sealed_binary_005.py'):
    retain(OWN / name, 'drivers/' + name)
retain(OWN / 'symbols-004/selected-symbols.txt', 'symbols-004/selected-symbols.txt')
retain(OWN / 'symbols-004/RESULT.json', 'symbols-004/RESULT.json')

attempts = []
for execution in ('execution-001', 'execution-002', 'execution-003', 'execution-005'):
    folder = OWN / execution
    record = json.loads((folder / 'RESULT.json').read_text())
    retain(folder / 'RESULT.json', execution + '/RESULT.json')
    for path in sorted(folder.glob('*.log')):
        retain(path, execution + '/' + path.name)
    if (folder / 'FROZEN_INPUTS.json').exists():
        retain(folder / 'FROZEN_INPUTS.json', execution + '/FROZEN_INPUTS.json')
    observed = []
    for arm in record['arms']:
        label = arm['label']
        for name in ('network-syscalls.log', 'file-network-syscalls.log',
                     'debugger.log', 'observe-error-branch.gdb',
                     'nextest-gdb-runner.py', 'nextest-store.toml',
                     'nextest-store/default/junit.xml'):
            path = folder / label / name
            if path.exists():
                retain(path, execution + '/' + label + '/' + name)
        junit = ET.parse(folder / label / 'nextest-store/default/junit.xml').getroot()
        cases = list(junit.iter('testcase'))
        assert len(cases) == 1 and cases[0].get('name') == 'reopen_old_version_fixture'
        assert cases[0].find('failure') is not None and cases[0].find('skipped') is None
        assert arm['before_files'] == record['pristine_fixture']
        observed.append({'label': label, 'session_mode': oct(arm['session_mode']),
                         'exit_code': arm['exit_code'], 'test_seconds': float(cases[0].get('time')),
                         'executed': 1, 'passed': 0, 'failed': 1, 'skipped': 0, 'retries': 0,
                         'input_bytes_match_pristine_old_fixture': True})
    attempts.append({'name': execution, 'scope': record['scope'], 'cases': observed,
                     'commands_started': len(record['commands']),
                     'status': record.get('status', 'aborted_before_any_command; original exception text not retained')})

producer = REMOTE / 'old-matrix-small/RESULT.json'
old_record = json.loads(producer.read_text())
original = REMOTE / 'old-matrix-small/fixture'
assert file_tree(original) == old_record['fixture_files']
old_zip = REMOTE / 'raw/ndu-matrix-018-fixture-40503203294-1.zip'
new_zip = REMOTE / 'raw/ndu-port-tests-matrix-40503203294-1.zip'
zip_modes = {}
with zipfile.ZipFile(old_zip) as archive:
    for member in archive.infolist():
        if member.filename.startswith('fixture/') and not member.is_dir():
            zip_modes[member.filename.removeprefix('fixture/')] = oct(stat.S_IMODE(member.external_attr >> 16))
assert set(zip_modes) == set(old_record['fixture_files'])
arrived_modes = {str(path.relative_to(original)): oct(stat.S_IMODE(path.stat().st_mode))
                 for path in sorted(original.rglob('*')) if path.is_file()}
old_identity = identity(old_zip)
new_identity = identity(new_zip)
assert old_identity['sha256'] == 'd3ae752d0bbe2f6e1c08a3cfd7b3b88cc89651d8b6af861c2872a2092b08612a'
assert new_identity['sha256'] == 'ac5260d4cb487988c470b3cf4dfd4ac5817f84a424c64b26628be76e7074fbf5'

stores = {}
for path in sorted((OWN / 'db-readback/old').rglob('matrix-sdk-*.sqlite3')):
    relative = path.relative_to(OWN / 'db-readback/old')
    rows = {}
    for label in ('old', 'failed'):
        db = OWN / 'db-readback' / label / relative
        with sqlite3.connect('file:' + str(db) + '?mode=ro', uri=True) as connection:
            connection.execute('PRAGMA query_only=ON')
            raw = connection.execute("SELECT value FROM kv WHERE key = 'cipher'").fetchone()[0]
            version = connection.execute("SELECT value FROM kv WHERE key = 'version'").fetchone()[0]
        value = msgpack.unpackb(raw, raw=False)['kdf_info']
        algorithm, parameters = next(iter(value.items()))
        rows[label] = {'version': int.from_bytes(version, 'little'),
                       'cipher_sha256': hashlib.sha256(raw).hexdigest(),
                       'cipher_bytes': len(raw), 'kdf': algorithm, 'rounds': parameters['rounds']}
    assert rows['old']['cipher_sha256'] == rows['failed']['cipher_sha256']
    assert rows['old']['rounds'] == rows['failed']['rounds'] == 200_000
    stores[str(relative)] = rows

mode_receipt = ROOT / 'ndu-matrix-gap-fill-019-001/mode-custody-real-fixture-001/RESULT.json'
retain(mode_receipt, 'REAL_FIXTURE_MODE_RESTORATION.json')
candidate = OWN / 'startup-budget-proposal-001'
for source, destination in (
    ('STARTUP_BUDGET_FORMATTED.patch', 'candidate/STARTUP_BUDGET_FORMATTED.patch'),
    ('STARTUP_BUDGET_REVIEW.json', 'candidate/STARTUP_BUDGET_REVIEW.json'),
    ('source-before/codex-rs/hepta-matrix-sdk/src/sdk.rs', 'candidate/source-before-sdk.rs'),
    ('proposed-formatted/codex-rs/hepta-matrix-sdk/src/sdk.rs', 'candidate/proposed-sdk.rs'),
    ('proposed-formatted/codex-rs/hepta-matrix-sdk/src/startup_deadline_tests.rs', 'candidate/startup_deadline_tests.rs'),
    ('rustfmt.stdout', 'candidate/rustfmt.stdout'), ('rustfmt.stderr', 'candidate/rustfmt.stderr')
):
    retain(candidate / source, destination)

file_trace = (OWN / 'execution-003/restored-mode-0600/file-network-syscalls.log').read_text()
debugger_log = (OWN / 'execution-005/restored-mode-0600/debugger.log').read_text()
assert 'session.json' not in file_trace and 'AF_INET' not in file_trace
assert 'HEPTA_DIAG_BUILD_TIMEOUT_ERROR_BRANCH' in debugger_log
assert 'HEPTA_DIAG_LOAD_SESSION_REACHED' not in debugger_log
report = {
    'schema': 'hepta.matrix-reopen.root-cause.v1',
    'time': datetime.now(timezone.utc).isoformat(),
    'status': 'original_binary_failure_explained; candidate_pending_new_source_execution',
    'all_blockers_closed': False,
    'migration_qualified': False,
    'original_ci': {'run_id': 40503203294, 'run_attempt': 1, 'consumer_job_id': 122189367737,
                    'source': '3a779a6e52138d63056fdb00e1e477c8db6517f8',
                    'actual_reopen_cases': 1, 'passed': 0, 'seconds': 5.530},
    'finding': 'The unchanged real CI binary reaches the Self::build timeout error branch before load_session. A separate artifact mode-loss defect would reject the session after build succeeds.',
    'mechanism': [
        'The SDK wraps Self::build in the 5s startup request timeout.',
        'The configured SQLite builder opens four encrypted stores with try_join on one task.',
        'The upstream async get_or_create_store_cipher invokes synchronous StoreCipher::import for human passphrases.',
        'Each original cipher retains its full 200000-round PBKDF2 metadata. Local migration/unlock consumes approximately 5.9-6.2 seconds in the unchanged opt-level=0 CI executable.',
        'The 0600 pristine reproduction records no session file stat/open and no AF_INET network call.',
        'An observation-only debugger reproduction hits the sole login_or_restore timeout map_err closure and never hits load_session.',
        'Original producer ZIP file modes include 0600 session.json and matrix_1.sqlite3; the received artifact tree has 0644. The old consumer copied modes and only ORed owner-write, so private session permissions were not recovered.'
    ],
    'causal_limits': [
        'The debugger observation is a local reproduction of the exact original CI executable, not a trace of the historical CI process.',
        'The debugger observes only break/echo/backtrace/continue after the timeout error branch. It does not set program variables/registers, call program functions, force return, or jump.',
        'GDB and strace add overhead. Independent non-GDB runs already failed before session access; timing is diagnostic, not a performance benchmark.',
        'Mode correction alone did not fix the unchanged binary. Both 0644 and 0600 arms failed, and every arm started from a separate pristine old fixture.',
        'Cipher byte preservation and schema migration are not an end-to-end restore pass. Every recorded runtime case here fails; none qualifies v4.',
        'execution-001 aborted before any inventory or testcase command. Its original exception text was not retained; no result is inferred from it.'
    ],
    'attempts': attempts,
    'retained_original_inputs': {
        'producer_result': {'path': str(producer), **identity(producer)},
        'producer_zip': {'path': str(old_zip), **old_identity},
        'consumer_zip': {'path': str(new_zip), **new_identity},
        'actual_consumer_elf_sha256': '12e53b85e42fbb8e42658a987523425bd1dc3ada4d545d1f1ac0ba3710859448',
        'elf_execution': 'Anonymous memfd sealed against writes/grow/shrink/further seals (15); SHA verified before and after each diagnostic; no ELF persisted to disk.',
        'original_fixture_bytes_still_match_producer': True,
        'original_fixture_files': old_record['fixture_files'],
        'original_zip_file_modes': zip_modes,
        'received_file_modes_after_diagnostics': arrived_modes,
        'mode_copy_receipt': 'REAL_FIXTURE_MODE_RESTORATION.json',
        'mode_copy_receipt_boundary': 'Original v1 did not bind directory modes; its copy probe restores ZIP file modes and uses received directory modes. New v2 producer binds both file and directory modes.'
    },
    'stores': stores,
    'proposed_fix': {
        'runtime_patch': 'candidate/STARTUP_BUDGET_FORMATTED.patch',
        'runtime_review': 'candidate/STARTUP_BUDGET_REVIEW.json',
        'runtime_source_changes': ['codex-rs/hepta-matrix-sdk/src/sdk.rs', 'codex-rs/hepta-matrix-sdk/src/startup_deadline_tests.rs'],
        'startup_budget_seconds': 20, 'per_request_budget_seconds': 5,
        'deadline_scope': 'One original tokio Instant shared by initialization, authentication and fresh-client fallback; no renewed startup window.',
        'late_ready': 'Build and authentication reject completion at or after their absolute deadline; an already-expired fallback is rejected before creating stores.',
        'runtime_limit': 'Cooperative timer/acceptance budget, not preemption of synchronous KDF or a hard wall-clock stop. Supervisor outer 60s remains independently enforced.',
        'unchanged': ['KDF rounds and human-passphrase API', 'encryption and crypto identities', 'original old producer fixture and assertions', 'vendor implementation and fingerprint set', 'all original runtime migration and queue assertions'],
        'separate_transport_fix': 'Hash-bound producer file+directory mode metadata and exact-mode restoration on a fresh copy; original fixture bytes and modes preserved.',
        'qualification_still_required': ['Compile exact v4 source', 'Run SDK unit/integration tests through just test', 'Produce an independent original 0.18 fixture with new driver binding', 'Execute exact single reopen_old_version_fixture on its fresh restored copy and retain executable/JUnit', 'Preserve remaining platform, feature, policy and baseline gates']
    },
    'retained_files': copied,
}
(OUT / 'DIAGNOSIS.json').write_text(json.dumps(report, indent=2) + '\n')
manifest = {str(path.relative_to(OUT)): identity(path) for path in sorted(OUT.rglob('*')) if path.is_file()}
(OUT / 'FILES.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps({'output': str(OUT), 'diagnosis': identity(OUT / 'DIAGNOSIS.json'),
                  'file_count_before_manifest': len(manifest),
                  'retained_bytes_before_manifest': sum(row['bytes'] for row in manifest.values())}, indent=2))
