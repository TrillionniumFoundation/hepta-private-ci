from pathlib import Path
import hashlib
import json
import subprocess
import time

repo = Path('/dev/shm/hepta-ndu-unified-20261028/repo')
out = Path('/workspace/scratch/627fa3bea56c/architecture792_restart_snapshot_repair_001')
paths = [
    'codex-rs/hepta-supervisor/src/model.rs',
    'codex-rs/hepta-supervisor/tests/restart_budget_recovery.rs',
]
getter = '''impl AgentSupervisorSnapshot {
    /// Restart-attempt counter captured by this snapshot.
    pub fn restart_attempt(&self) -> u32 {
        self.restart_attempt
    }

    /// Whether this snapshot records a queued restart.
    pub fn restart_pending(&self) -> bool {
        self.restart_pending
    }
}

'''
model = (repo / paths[0]).read_text()
before_model = (out / 'before' / paths[0]).read_text()
test = (repo / paths[1]).read_text()
before_test = (out / 'before' / paths[1]).read_text()
assert model.count(getter) == 1 and model.replace(getter, '') == before_model
assert test.count('snapshot.restart_attempt()') == 3
assert test.count('snapshot.restart_pending()') == 3
assert test.replace('snapshot.restart_attempt()', 'snapshot.restart_attempt').replace(
    'snapshot.restart_pending()', 'snapshot.restart_pending'
) == before_test
assert 'pub(crate) restart_attempt: u32' in model
assert 'pub(crate) restart_pending: bool' in model
files = []
for relative in paths:
    data = (repo / relative).read_bytes()
    old = (out / 'before' / relative).read_bytes()
    files.append({
        'path': relative,
        'bytes': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
        'before_bytes': len(old),
        'before_sha256': hashlib.sha256(old).hexdigest(),
    })
patch = subprocess.run(
    ['git', 'diff', '--', *paths], cwd=repo, capture_output=True, text=True, check=True
).stdout
(out / 'repair.patch').write_text(patch)
snapshot = repo / 'experiments/multimodal_output_portfolio/closure_20261028/natural_completed_snapshot_005.json'
snapshot_data = json.loads(snapshot.read_text())
for row in snapshot_data['files']:
    data = (repo / row['path']).read_bytes()
    assert len(data) == row['bytes'], row['path']
    assert hashlib.sha256(data).hexdigest() == row['sha256'], row['path']
log = Path('/workspace/scratch/627fa3bea56c/architecture792-source-head-job122778615741.log')
records = []
for line in log.read_text().splitlines():
    if '"command"' in line and 'runtime-module-supervisor.json' in line:
        records.append(json.loads(line[line.index('{'):]))
assert len(records) == 1
validation = {
    'scope': 'Two public read-only snapshot accessors and six integration-test call sites; all original assertion operands and expected tuples retained.',
    'original_model_except_getters_exactly_preserved': True,
    'original_test_except_six_calls_exactly_preserved': True,
    'field_visibility_unchanged': True,
    'natural005_unchanged_files_verified': len(snapshot_data['files']),
    'natural005_manifest_sha256': hashlib.sha256(snapshot.read_bytes()).hexdigest(),
    'just_test': {
        'command': ['just', 'test', '--locked', '-p', 'codex-hepta-supervisor', '--test', 'restart_budget_recovery'],
        'rust_version': '1.96.0',
        'exit_code': 101,
        'native_test_execution_passed': False,
        'phase': 'Workspace manifest loading before compilation',
        'blocker': 'Sparse local checkout lacks codex-rs/aws-auth/Cargo.toml',
        'log': 'just-test.log',
    },
    'scoped_format': {'files': paths, 'rustfmt_version': '1.96.0', 'exit_codes': [0, 0], 'details': 'scoped-format.json'},
    'just_fmt_check': {'exit_code': 0, 'log': 'just-fmt-check.log'},
    'diff_check': {'exit_code': 0},
    'codespell_existing_repository_config': {'exit_code': 0},
    'tests_rerun_after_final_format': False,
    'required_followup': 'Run actual supervisor integration and module_runtime tests in the complete native CI checkout; no test pass is inferred from formatting.',
}
report = {
    'schema': 'architecture-restart-snapshot-repair/v1',
    'created_at_unix': time.time(),
    'run_url': 'https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40677089531',
    'source_sha': '792beb14600f9b49b04ed18f9061e11d0e163759',
    'source_tree': '1fc4042c047ae66720ad4c56adeb23a9bc9e679b',
    'source_job_id': 122778615741,
    'diagnosis': 'The supervisor module_runtime command compiles the external restart_budget_recovery integration target, which illegally accessed two pub(crate) snapshot fields at six sites. E0616 occurs before any selected supervisor test passes. This is not evidence of a failing migration rollback runtime assertion.',
    'source_command_receipt': records[0],
    'base_merge_evidence': 'remote-lanes.json',
    'base_merge_claim': 'The identical-tree base-merge lane skipped native execution and required source-head success; the required architecture aggregator failed. Its green job is not a separate native pass.',
    'changes': files,
    'validation': validation,
    'retained_decoded_source_log': {
        'path': str(log),
        'bytes': log.stat().st_size,
        'sha256': hashlib.sha256(log.read_bytes()).hexdigest(),
        'scope': 'Locally retained decoded job log; not asserted to be the original GitHub ZIP/member byte stream.',
    },
    'evidence_files': [],
}
for path in sorted(out.iterdir()):
    if path.is_file() and path.name not in ['REPORT.json', 'MANIFEST.json']:
        data = path.read_bytes()
        report['evidence_files'].append({'path': path.name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
(out / 'REPORT.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
manifest = {
    'schema': 'two-file-source-publication/v1',
    'repo': str(repo),
    'files': files,
    'report': {
        'path': str(out / 'REPORT.json'),
        'bytes': (out / 'REPORT.json').stat().st_size,
        'sha256': hashlib.sha256((out / 'REPORT.json').read_bytes()).hexdigest(),
    },
    'frozen_natural005_not_changed': True,
    'native_tests_passed': False,
}
(out / 'MANIFEST.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
for name in ['REPORT.json', 'MANIFEST.json', 'repair.patch']:
    path = out / name
    data = path.read_bytes()
    print(json.dumps({'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}))
print(json.dumps({'source_files': files, 'natural005_verified': len(snapshot_data['files'])}))
