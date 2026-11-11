"""Freeze C2 observations and separately bounded, unexecuted follow-up plans."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import zipfile


ROOT = Path('/workspace/scratch/c385a7439f8e')
DEST = ROOT / 'hcsn-repo/qualification/hcsn_differentiable/evidence/p0p5-c2-progress-20261110'
COPIES = []


def identity(path):
    data = path.read_bytes()
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def write(name, value):
    path = DEST / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        stream.write(value if isinstance(value, str) else json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def copy(path, name, expected=None):
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    before = identity(path)
    assert not path.is_symlink() and (expected is None or before == expected)
    target = DEST / name
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream:
        stream.write(path.read_bytes())
    assert identity(path) == identity(target) == before
    COPIES.append({'source': str(path), 'target': name, **before})


def directory(source, target):
    base = ROOT / source
    manifest = base / 'MANIFEST.json'
    if manifest.exists():
        for name, row in json.loads(manifest.read_bytes())['files'].items():
            assert identity(base / name) == {k: row[k] for k in ('bytes', 'sha256')}
    for path in sorted(base.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            copy(path, target + '/' + path.relative_to(base).as_posix())


def copy_list(source, target):
    base = ROOT / source
    document = json.loads((base / 'COPY_LIST.json').read_bytes())
    copy(base / 'COPY_LIST.json', target + '/COPY_LIST.json')
    rows = document.get('entries', document.get('files'))
    manifest = json.loads((base / 'MANIFEST.json').read_bytes())['files'] if (base / 'MANIFEST.json').exists() else None
    for row in rows:
        if isinstance(row, str):
            path = base / row
            expected = manifest[row] if row != 'MANIFEST.json' else None
            relative = row
        else:
            path = Path(row.get('source', row.get('path')))
            relative = row.get('suggested_name', path.relative_to(base).as_posix())
            expected = {k: row[k] for k in ('bytes', 'sha256')}
        copy(path, target + '/' + relative, expected)


def zip_originals(name, inputs):
    path = DEST / name
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with zipfile.ZipFile(path, 'x', zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for source in inputs:
            item = ROOT / source
            before = identity(item)
            zipped.writestr(source, item.read_bytes())
            assert identity(item) == before
            rows.append({'source': str(item), 'member': source, **before})
        zipped.writestr('MEMBER-MANIFEST.json', json.dumps({'files': rows}, indent=2, sort_keys=True) + '\n')
    with zipfile.ZipFile(path) as zipped:
        assert zipped.testzip() is None
        for row in rows:
            data = zipped.read(row['member'])
            assert len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256']
    write(name + '.json', {'schema': 'original-byte-archive-v1', 'archive': name, **identity(path), 'members': rows})


def main():
    start, cpu = time.monotonic(), time.process_time()
    DEST.mkdir(exist_ok=False)
    for source, target in [
        ('c2-epoch-observation-recovered-v1', 'observations/first-epochs'),
        ('c2-epoch-observation-recovered-v2', 'observations/at-220042'),
        ('c2-first-terminal-receipts-v1', 'first-terminal'),
        ('c2-terminal-auditor-preparation-evidence-v1', 'terminal-auditor/preparation'),
    ]:
        copy_list(source, target)
    for source, target in [
        ('c2-terminal-auditor-root-preparation-v1', 'terminal-auditor/root-source-review'),
        ('c2-resource-analysis-plan-v1', 'resource-plan'),
        ('c2-resource-plan-independent-review-v1', 'resource-plan-review'),
        ('prospective-confirmation-E-candidate-v1', 'confirmation-E-proposal'),
        ('prospective-E-training-interface-review-v1', 'confirmation-E-interface-review'),
        ('current-c2-launch-final-validation-v1', 'prior-head-checks/worktree'),
        ('current-c2-launch-git-proof-v1', 'prior-head-checks/committed-blobs'),
        ('terminal-numerics-uploader-root-static-review-v1', 'publication-preparation/root-static-review'),
    ]:
        directory(source, target)
    for source, target in [
        ('c2-terminal-independent-auditor-v1/PLAN.json', 'terminal-auditor/PLAN.json'),
        ('c2-terminal-independent-auditor-v1/MANIFEST.json', 'terminal-auditor/PROGRAM-MANIFEST.json'),
        ('hcsn-c2-launch-local-stages-v1.json', 'publication/local-stages.json'),
        ('hcsn-c2-launch-api-progress-v1.json', 'publication/api-progress.json'),
        ('hcsn_c2_launch_publish_helpers_v1.js', 'publication/publish_helpers.js'),
        ('hcsn-c2-launch-pr-created-v1.json', 'publication/PR5856-created.json'),
        ('terminal-numerics-draft-uploader-preparation-v1/uploader.py', 'publication-preparation/uploader.py'),
        ('build_c2_progress_evidence_v1.py', 'curation-source/build_c2_progress_evidence_v1.py'),
        ('c2_progress_evidence_readme_v1.md', 'README.md'),
    ]:
        copy(source, target)
    zip_originals('prior-head-checks/codespell-red-green.zip', [
        'current-c2-launch-codespell-v1/EXECUTION.json',
        'current-c2-launch-codespell-v1/stdout',
        'current-c2-launch-codespell-v1/stderr',
        'current-c2-launch-codespell-v2/EXECUTION.json',
        'current-c2-launch-codespell-v2/stdout',
        'current-c2-launch-codespell-v2/stderr',
    ])
    zip_originals('ci/observations-original.zip', [
        'hcsn-ci-c2-launch-head-observation-v1.json',
        'hcsn-c2-launch-blocking-jobs-v1.json',
    ])
    observed = json.loads((DEST / 'observations/at-220042/HANDOFF.json').read_bytes())
    first = json.loads((DEST / 'first-terminal/HANDOFF.json').read_bytes())
    costs = json.loads((DEST / 'first-terminal/COST-SCOPE-ADDENDUM.json').read_bytes())
    assert observed['observed_utc'] == '2026-11-10T22:00:42.152837+00:00'
    assert len(observed['fits']) == 6 and sum(row['pid_exists'] for row in observed['fits']) == 5
    assert first['same_selected_best_bytes_as_original'] and first['no_observed_selected_quality_improvement']
    roster = [{k: row[k] for k in ('name', 'epoch', 'pid_exists', 'fit_terminal_report_observed', 'stopping')}
              for row in observed['fits']]
    write('STATUS.json', {
        'schema': 'c2-progress-and-preparation-v1', 'training_observed_utc': observed['observed_utc'],
        'training_job': '1a1c74f3308-be2a-75', 'training_key': 'hcsn-c2-native-execution-c385-v1',
        'roster': roster, 'producer_terminal_count': 1, 'producer_adequate_count': 1,
        'independent_terminal_audit': 'prepared, frozen, not executed', 'independently_admitted_adequate_count': 0,
        'terminal_best_checkpoint_changed': False, 'new_common_LR_selection': False,
        'all_six_terminal': False, 'confirmation_E_read': False,
        'resource_analysis': 'plan frozen after launch and first outcomes; analysis not executed',
        'confirmation_E': 'separate unexecuted proposal; not the original formal confirmation recipe',
        'numerical_audit': 'separate original job; this snapshot does not assert its later terminal outcome',
        'whole_training_numerical_admission': 'HOLD', 'scientific_benefit': 'HOLD', 'P5': 'benefit-gated',
    })
    write('COSTS.json', {
        'schema': 'c2-progress-cost-index-v1',
        'first_terminal': {'candidate': first['candidate'], 'receipt': 'first-terminal/COST-SCOPE-ADDENDUM.json', **costs},
        'read_only_observers': [
            {'receipt': 'observations/first-epochs/GNU-TIME.txt', 'whole_process_wall_seconds_rounded': 0.22,
             'user_seconds_rounded': 0.16, 'system_seconds_rounded': 0.03},
            {'receipt': 'observations/at-220042/GNU-TIME.txt', 'whole_process_wall_seconds_rounded': 0.35,
             'user_seconds_rounded': 0.32, 'system_seconds_rounded': 0.03},
            {'receipt': 'first-terminal/ARCHIVE-GNU-TIME.txt', 'whole_process_wall_seconds_rounded': 0.28,
             'user_seconds_rounded': 0.23, 'system_seconds_rounded': 0.03},
        ],
        'preparation_receipts': ['terminal-auditor/preparation/SUMMARY.json', 'resource-plan/PREPARATION.json',
             'resource-plan-review/RESULT.json', 'confirmation-E-proposal/ASSEMBLY-RECEIPT.json'],
        'verification_receipts': ['prior-head-checks/worktree/EXECUTION.json', 'prior-head-checks/committed-blobs/EXECUTION.json',
             'prior-head-checks/codespell-red-green.zip.json'],
        'failed_control_plane_reads': 'Two120s first-terminal binary RPC timeouts are retained in the original control ZIP; neither reran training.',
        'cloud_read_interruption': 'publication-preparation/root-static-review/CLOUD-READ-INTERRUPTION.json',
        'total_C2_cost': None, 'exact_cumulative_training_CPU': None, 'energy_joules': None, 'billing': None,
        'additive_grand_total': None,
        'rule': 'C2 remains active at the stated observation. Keep full attempt-wrapper tails and all failures. GNU, child, phase and script-prefix views overlap. Unknown is not zero.',
    })
    archives = []
    for path in sorted(DEST.rglob('*.zip')):
        with zipfile.ZipFile(path) as zipped:
            assert zipped.testzip() is None
            names = zipped.namelist()
            assert len(names) == len(set(names))
            members = {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                       for name in names if not name.endswith('/') for data in [zipped.read(name)]}
        archives.append({'path': path.relative_to(DEST).as_posix(), **identity(path), 'members': members, 'CRC_passed': True})
    write('ARCHIVES.json', {'schema': 'c2-progress-archive-identities-v1', 'archives': archives})
    assert all(identity(Path(row['source'])) == identity(DEST / row['target']) ==
               {k: row[k] for k in ('bytes', 'sha256')} for row in COPIES)
    write('COPY-RECEIPT.json', {
        'schema': 'c2-progress-original-copy-v1', 'copied': COPIES, 'source_files_unchanged': True,
        'recorded_utc': datetime.now(timezone.utc).isoformat(),
        'main_entry_wall_seconds': time.monotonic() - start, 'main_entry_CPU_seconds': time.process_time() - cpu,
        'scope': 'Local mechanical copies, saved-metadata indexes and archive verification; excludes imports, final receipt/manifest write and exit. No native model, optimizer, oracle, E or CI rerun.',
    })
    write('MANIFEST.json', {
        'schema': 'c2-progress-manifest-v1',
        'files': {p.relative_to(DEST).as_posix(): identity(p) for p in sorted(DEST.rglob('*')) if p.is_file()},
        'whole_training_numerical_admission': 'HOLD', 'scientific_benefit': 'HOLD',
    })
    print(json.dumps({'manifest': identity(DEST / 'MANIFEST.json'), 'files': len(json.loads((DEST / 'MANIFEST.json').read_bytes())['files'])}))


if __name__ == '__main__':
    main()
