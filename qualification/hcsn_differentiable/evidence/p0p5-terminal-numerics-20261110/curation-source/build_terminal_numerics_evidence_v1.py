"""Freeze the completed numerical postmortem, local diagnosis and scope corrections."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import zipfile


ROOT = Path('/workspace/scratch/c385a7439f8e')
DEST = ROOT / 'hcsn-repo/qualification/hcsn_differentiable/evidence/p0p5-terminal-numerics-20261110'
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
    assert base.is_dir(), source
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
    for row in document.get('entries', document.get('files')):
        assert isinstance(row, dict)
        path = Path(row.get('source', row.get('path')))
        relative = row.get('relative_destination') or row.get('relative_path') or row.get('suggested_name')
        if relative is None:
            relative = path.relative_to(base).as_posix()
        assert not Path(relative).is_absolute() and '..' not in Path(relative).parts
        expected = {k: row[k] for k in ('bytes', 'sha256')}
        assert expected['bytes'] <= 500000
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
        ('terminal-numerics-final-evidence-v1', 'numerical-audit'),
        ('terminal-numerics-draft-upload-recovered-v1', 'publication-originals'),
        ('p1-short-time-toy-delivery-v1', 'local-diagnosis'),
        ('c2-epoch-observation-recovered-v3', 'c2-at-222353'),
        ('c2-epoch-observation-recovered-v4', 'c2-at-224540'),
    ]:
        copy_list(source, target)
    for source, target in [
        ('p1-fixed-grid-short-time-diagnosis-v1', 'mathematical-diagnosis'),
        ('c2-progress-and-uploader-independent-review-v1', 'progress-review'),
        ('terminal-numerics-independent-json-review-v1', 'numerics-independent-review'),
        ('postmortem-outer-budget-counterexample-v1', 'collector-preparation/independent-budget-counterexample'),
        ('c2-progress-package-build-v1', 'previous-appendix-checks/package-build'),
        ('c2-progress-local-checks-v1', 'previous-appendix-checks/local-checks'),
        ('c2-progress-publication-screen-v1', 'previous-appendix-checks/publication-screen'),
    ]:
        directory(source, target)
    for source, target in [
        ('current-c2-ci-log-observation-v1/ORIGINALS.zip', 'ci-current/ORIGINALS.zip'),
        ('current-c2-ci-log-observation-v1/RECEIPT.json', 'ci-current/RECEIPT.json'),
        ('current-c2-ci-log-observation-v1/CONTRACT-EXPLANATION.json', 'ci-current/CONTRACT-EXPLANATION.json'),
        ('terminal-numerics-independent-json-review-v1-COPY_LIST.json', 'numerics-independent-review/COPY_LIST.json'),
        ('terminal-numerics-independent-json-review-v1.zip', 'numerics-independent-review/complete-review.zip'),
        ('c2-progress-local-commit-v1/RESULT.json', 'previous-appendix-checks/LOCAL-COMMIT.json'),
        ('postmortem-outer-budget-closure-v1.zip', 'collector-preparation/independent-budget-closure.zip'),
        ('terminal-numerics-curation-source-write-v1.json', 'curation-source/source-write-observation.json'),
        ('build_terminal_numerics_evidence_v1.py', 'curation-source/build_terminal_numerics_evidence_v1.py'),
        ('terminal_numerics_evidence_readme_v1.md', 'README.md'),
    ]:
        copy(source, target)
    index = json.loads((DEST / 'numerical-audit/INDEX.json').read_bytes())
    collection = json.loads((DEST / 'numerical-audit/postmortem/COLLECTION-RECEIPT.json').read_bytes())
    upload = json.loads((DEST / 'publication-originals/RESULT.json').read_bytes())
    observed = json.loads((DEST / 'c2-at-224540/HANDOFF.json').read_bytes())
    assert index['planned_stages'] == 96 and index['planned_finite_fixtures'] == 60
    assert index['qualified_named_finite_fixtures'] == 49
    assert index['stage_observations'] == {
        'attempt_artifacts_without_outer_completion': 1,
        'completed_artifact_chain': 85,
        'not_observed_to_have_started': 10,
    }
    assert collection['metadata_collection_status'] == 'completed'
    assert collection['original_controller_aggregate_present'] is False
    assert upload['status'] == 'both_assets_authenticated_verified_draft_unchanged'
    assert upload['assets'][0]['sha256'] == collection['archive']['sha256']
    assert observed['observed_utc'] == '2026-11-10T22:45:40.491673+00:00'
    assert identity(DEST / 'c2-at-222353/hcsn-c2-epoch-observation-20261110-v3.zip') == {
        k: observed['parent_archive'][k] for k in ('bytes', 'sha256')}
    write('STATUS.json', {
        'schema': 'bounded-numerics-terminal-and-followup-v1',
        'original_numerical_attempt_status': index['original_attempt_status'],
        'original_numerical_attempt_returncode': index['original_attempt_returncode'],
        'original_hard_wall_seconds': 10800,
        'original_stages': index['stage_observations'],
        'finite_completed_named_passes': 49, 'finite_roster': 60,
        'maximum_scaled_error': index['maximum_scaled_error'],
        'maximum_ordinary_relative_error': index['maximum_relative_error'],
        'relative_error_is_not_the_general_gate': True,
        'pressure_failures': 12, 'pressure_sentinels': 18,
        'logrisk_primary_false': 6, 'direct_FD_inconclusive': 576,
        'direct_FD_resolved_disagreements': 6,
        'original_aggregate_absent': True,
        'postmortem_collection': 'separate metadata-only task after all original numerical processes stopped',
        'c2_observed_utc': observed['observed_utc'], 'c2_producer_terminal_count': 1,
        'c2_active_count': 5, 'C2_independent_terminal_audit': 'not executed in this snapshot',
        'local_48_case_diagnostic': 'separate FP64 scalar mechanism checks, not trained-model qualification',
        'confirmation_E_scope': 'This campaign has not used E for model scoring. The historical full-data loader interpreted E schema, coordinates, label validity, clock and global gaps; historical feature/schema blindness is not claimed.',
        'scientific_admission': 'HOLD', 'whole_training_numerical_admission': 'HOLD', 'P5': 'benefit-gated',
    })
    write('SCOPE-CORRECTIONS.json', {
        'schema': 'append-only-research-scope-corrections-v1',
        'E-EXPOSURE-01': {
            'affected_snapshot': '../p0p5-c2-progress-20261110/README.md',
            'affected_phrase': 'E remains unread',
            'correction': 'E remains unscored by this campaign. This preparation and C2 do not interpret E. The historical full-data loader processed E schema, coordinates, label validity, clock and global gaps. This is not a claim of historical schema/feature blindness or of all historical work never scoring E.',
            'evidence': 'progress-review/RESULT.json',
            'frozen_snapshot_rewritten': False,
        },
        'NUMERICAL-TERMINAL-01': {
            'correction': 'The original unique audit exhausted its unchanged three-hour envelope. The completed metadata collector is not completion or success of that numerical audit.',
            'evidence': 'numerical-audit/original-terminal/launch-receipt.json',
            'uncompleted_cases_receive_no_admission': True,
        },
    })
    write('COSTS.json', {
        'schema': 'terminal-numerics-cost-source-index-v1',
        'original_numerics_and_collection': 'numerical-audit/COST-RECORDS.json',
        'publication_whole_GNU': 'publication-originals/GNU-TIME.txt',
        'publication_whole_wall_seconds_rounded': 62.92,
        'publication_whole_user_plus_system_seconds_rounded': 8.11,
        'publication_inventory_GNU': 'publication-originals/INVENTORY-GNU-TIME.txt',
        'publication_control_archive_GNU': 'publication-originals/ARCHIVE-GNU-TIME.txt',
        'C2_observers': [
            {'receipt': 'c2-at-222353/GNU-TIME.txt', 'whole_wall_seconds_rounded': 0.46,
             'user_plus_system_seconds_rounded': 0.44},
            {'receipt': 'c2-at-224540/GNU-TIME.txt', 'whole_wall_seconds_rounded': 0.41,
             'user_plus_system_seconds_rounded': 0.40},
        ],
        'local_scalar_diagnostic': 'local-diagnosis/fixed48/COSTS.json',
        'mathematical_source_assembly': 'mathematical-diagnosis/PREPARATION-RECEIPT.json',
        'independent_metadata_review': ['numerics-independent-review/EXECUTION.json',
             'numerics-independent-review/CLOSURE-EXECUTION.json'],
        'prior_appendix_verification': 'previous-appendix-checks/local-checks/EXECUTION.json',
        'current_CI_API_observation_cost': None, 'energy_joules': None, 'billing': None,
        'additive_grand_total': None,
        'rule': 'Original, collector, publisher and scalar jobs are separate. Their nested bootstrap/worker/stage/prefix measurements are not additive. The killed unreaped numerical worker CPU and historical unmeasured wrappers remain unknown, not zero.',
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
    write('ARCHIVES.json', {'schema': 'terminal-numerics-local-archive-identities-v1', 'archives': archives,
          'large_remote_archive': collection['archive'], 'remote_readback_original': 'publication-originals/RESULT.json',
          'large_archive_redownloaded_by_builder': False})
    assert all(identity(Path(row['source'])) == identity(DEST / row['target']) ==
               {k: row[k] for k in ('bytes', 'sha256')} for row in COPIES)
    write('COPY-RECEIPT.json', {
        'schema': 'terminal-numerics-original-copy-v1', 'copied': COPIES, 'source_files_unchanged': True,
        'recorded_utc': datetime.now(timezone.utc).isoformat(),
        'main_entry_wall_seconds': time.monotonic() - start, 'main_entry_CPU_seconds': time.process_time() - cpu,
        'scope': 'Local exact copies, saved-metadata indexes and ZIP verification; excludes imports, final receipt/manifest write and exit. No original numerical case, model, optimizer, E, native job, publication or CI rerun.',
    })
    write('MANIFEST.json', {
        'schema': 'terminal-numerics-evidence-manifest-v1',
        'files': {p.relative_to(DEST).as_posix(): identity(p) for p in sorted(DEST.rglob('*')) if p.is_file()},
        'whole_training_numerical_admission': 'HOLD', 'scientific_admission': 'HOLD',
    })
    print(json.dumps({'manifest': identity(DEST / 'MANIFEST.json'), 'files': len(json.loads((DEST / 'MANIFEST.json').read_bytes())['files'])}))


if __name__ == '__main__':
    main()
