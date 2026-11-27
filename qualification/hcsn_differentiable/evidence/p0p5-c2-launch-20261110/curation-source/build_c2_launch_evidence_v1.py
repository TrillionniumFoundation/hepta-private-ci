"""Freeze completed C2 preparation and first-step observations, without model work."""

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import time
import zipfile


ROOT = Path('/workspace/scratch/c385a7439f8e')
DEST = ROOT / 'hcsn-repo/qualification/hcsn_differentiable/evidence/p0p5-c2-launch-20261110'
COPIED = []


def identity_bytes(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def identity(path):
    return identity_bytes(path.read_bytes())


def write(relative, value):
    path = DEST / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    data = value if isinstance(value, str) else json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n'
    with path.open('x') as stream:
        stream.write(data)


def copy(source, relative, expected=None):
    source = Path(source)
    before = identity(source)
    if expected is not None:
        assert before == {'bytes': expected['bytes'], 'sha256': expected['sha256']}, source
    target = DEST / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream:
        stream.write(source.read_bytes())
    assert identity(target) == identity(source) == before
    COPIED.append({'source': str(source), 'target': relative, **before})


def copy_dir(source, relative):
    directory = ROOT / source
    for path in sorted(directory.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            copy(path, relative + '/' + path.relative_to(directory).as_posix())


def copy_handoff(source, relative):
    listing = ROOT / source / 'COPY_LIST.json'
    for row in json.loads(listing.read_text())['files']:
        path = Path(row['path'])
        destination = relative + '/' + path.name
        if path.parent.name == 'c2-native-execution-preparation-v1':
            destination = 'launch/' + path.name
        copy(path, destination, row)
    copy(listing, relative + '/COPY_LIST.json')


def zip_members(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert len(names) == len(set(names))
        return {name: identity_bytes(archive.read(name)) for name in names if not name.endswith('/')}


def row_cost(identifier, artifact, fields, scope, member=None):
    path = DEST / artifact
    if member is None:
        data = json.loads(path.read_text())
        bound = identity(path)
    else:
        with zipfile.ZipFile(path) as archive:
            original = archive.read(member)
        data, bound = json.loads(original), identity_bytes(original)
    return {'id': identifier, 'artifact': artifact, 'member': member, 'identity': bound,
            'measurements': {key: data[key] for key in fields}, 'scope': scope}


def main():
    start, cpu = time.perf_counter(), time.process_time()
    DEST.mkdir(exist_ok=False)
    for source, target in [
        ('c2-candidate-handoff-v1', 'preparation/v1'),
        ('c2-candidate-handoff-v2', 'preparation/v2'),
        ('c2-candidate-handoff-v4', 'preparation/v4'),
        ('c2-native-preflight-recovered-v1', 'native-preflight'),
        ('c2-start-observation-recovered-v1', 'first-step'),
    ]:
        copy_handoff(source, target)
    for source, target in [
        ('c2-execution-independent-review-v1', 'preparation/v3-review'),
        ('c2-v4-budget-reporting-independent-review-v1', 'preparation/v4-review'),
        ('c2-execution-decision-v1', 'decision'),
        ('c2-decision-independent-review-v1', 'decision-review'),
        ('c2-first14-provenance-independent-closure-v1', 'decision-provenance-review'),
        ('logrisk-json-independent-review-v1', 'numeric-context/logrisk-review'),
    ]:
        copy_dir(source, target)
    for source, target in [
        ('c2-execution-independent-review-v1.zip', 'preparation/v3-review-original.zip'),
        ('c2-execution-validation-attempt-05/TESTED-SOURCE.zip', 'launch/source-v4.zip'),
        ('c2-execution-validation-attempt-05/RESULT.json', 'preparation/v4/VALIDATION-RESULT.json'),
        ('c2-execution-candidate-v4/PROGRAM-MANIFEST.json', 'launch/PROGRAM-MANIFEST.json'),
        ('c2-execution-candidate-v4/CONTRACT.json', 'launch/CONTRACT.json'),
        ('c2-execution-candidate-v4/OPTIMIZATION-POSTERIOR-POLICY-v2.json', 'launch/OPTIMIZATION-POSTERIOR-POLICY-v2.json'),
        ('c2-execution-candidate-v4/POSTERIOR-POLICY.json', 'launch/POSTERIOR-POLICY.json'),
        ('native_c2_execution_bootstrap_v1.py', 'launch/bootstrap.py'),
        ('c2-native-execution-preparation-v1/SOURCE-PREPARED.json', 'launch/SOURCE-PREPARED.json'),
        ('c2-native-execution-preparation-v1/LAUNCH-DISPATCH.json', 'launch/LAUNCH-DISPATCH.json'),
        ('six-logrisk-query-confirmation-v1.zip', 'numeric-context/six-logrisk-originals.zip'),
        ('six-logrisk-query-confirmation-v1/RESULT.json', 'numeric-context/six-logrisk-RESULT.json'),
        ('terminal-finite-first14-provenance-v1.zip', 'numeric-context/first14-originals.zip'),
        ('terminal-finite-first14-provenance-v1/RESULT.json', 'numeric-context/first14-RESULT.json'),
        ('final-numerics-provisional-2056-v1/hcsn-s101-lr0.003__finite-best-2.json', 'numeric-context/rare-count-original.json'),
        ('terminal-six-model-pressure-summary-v1.zip', 'numeric-context/six-model-pressure-originals.zip'),
        ('terminal-six-model-pressure-summary-v1/RESULT.json', 'numeric-context/six-model-pressure-RESULT.json'),
        ('build_c2_launch_evidence_v1.py', 'curation-source/build_c2_launch_evidence_v1.py'),
        ('c2_launch_evidence_readme_v1.md', 'README.md'),
    ]:
        copy(ROOT / source, target)

    archive_index = []
    for path in sorted(DEST.rglob('*.zip')):
        data = path.read_bytes()
        archive_index.append({'path': path.relative_to(DEST).as_posix(), **identity_bytes(data),
                              'members': zip_members(data)})
    for stem, expected in [
        ('hcsn-c2-native-preflight-20261110-v1.zip', '6bfe207f36b47472964d7992b5881f4775775333f6b8cb0d09366321ccf4699c'),
        ('control-plane-originals-v1.zip', '1c7d230ea27bf82ccbe2b7dcb1f0199c0145fe9d9eb0f6f3b6ec852f29a09144'),
    ]:
        parts = sorted((DEST / 'native-preflight').glob(stem + '.part-*'))
        assert len(parts) == 2
        data = b''.join(path.read_bytes() for path in parts)
        assert identity_bytes(data)['sha256'] == expected
        archive_index.append({'path': None, 'reassemble_in_order': [p.relative_to(DEST).as_posix() for p in parts],
                              **identity_bytes(data), 'members': zip_members(data)})
    write('ARCHIVES.json', {'schema': 'c2-launch-original-archives-v1', 'archives': archive_index,
                           'reassembly_rule': 'Concatenate listed original byte parts without recompression. ZIP member identities bind stored originals, not new executions.'})

    decision = json.loads((DEST / 'decision/DECISION.json').read_text())
    inputs = []
    for original, expected in decision['evidence_inputs'].items():
        candidates = [c['target'] for c in COPIED if c['source'] == original]
        if candidates:
            location = candidates[0]
        elif original.startswith(str(ROOT / 'hcsn-repo') + '/'):
            location = str(Path(original).relative_to(DEST.parent))
        else:
            raise AssertionError('Unresolved decision input: ' + original)
        path = Path(original)
        assert identity(path) == expected
        inputs.append({'original': original, 'archive_location': location,
                       'relative_to': 'this directory' if candidates else 'parent evidence directory', **expected})
    write('decision/INPUT-LOCATORS.json', {'schema': 'c2-decision-input-closure-v1', 'inputs': inputs,
          'first14_count_appendix': '../decision-provenance-review/RESULT.json',
          'original_decision_unchanged': True})

    summary = json.loads((DEST / 'first-step/SUMMARY.json').read_text())
    fits = []
    assert [f['name'] for f in summary['fits']] == decision['fit_names']
    for fit in summary['fits']:
        witness, capture = fit['resume_start'], fit['observations'][0]
        assert witness['actual_restored_state_equal_parent_last']
        assert witness['new_optimizer_steps_before_receipt'] == 0
        assert capture['capture']['capture_grad_enabled']
        assert capture['step_completed']['optimizer_step_completed']
        assert capture['step_completed']['new_step'] == 1
        fits.append({'name': fit['name'], 'pid_at_dispatch': fit['dispatch']['pid'],
                     'dispatch_utc': fit['dispatch']['dispatch_utc'],
                     'restored_complete_epoch': capture['capture']['epoch'] - 1,
                     'discarded_parent_completed_updates': witness['discarded_parent_work']['completed_updates_after_anchor'],
                     'inflight_optimizer_updates_unknown_interval': witness['discarded_parent_work']['inflight_optimizer_updates_unknown_interval'],
                     'parent_full_outer_wall_charged': witness['parent_complete_outer_wall_charged'],
                     'remaining_at_dispatch_seconds': fit['dispatch']['remaining_at_dispatch_seconds'],
                     'full_state_equal_parent_before_first_step_reported': True,
                     'first_actual_gradient_capture': capture,
                     'observed_new_optimizer_completions': fit['optimizer_completion_events_observed'],
                     'last_complete_epoch_event_at_observation': fit['last_complete_epoch_event']})
    write('FIRST-STEP-INDEX.json', {'schema': 'c2-first-step-original-receipt-index-v1',
          'original_summary': 'first-step/SUMMARY.json', 'original_summary_identity': identity(DEST / 'first-step/SUMMARY.json'),
          'observed_utc': summary['observed_utc'], 'fits': fits,
          'capture_receipt_total_time_rows': sum(f['first_actual_gradient_capture']['capture']['coverage_verified']['retained_time_rows'] for f in fits),
          'capture_receipt_total_valid_sample_states': sum(f['first_actual_gradient_capture']['capture']['coverage_verified']['retained_valid_sample_states'] for f in fits),
          'scope': 'Existing producer witnesses, capture receipts and optimizer event originals. Complete probability trace arrays and checkpoint tensors have not been independently reread by this index.',
          'whole_training_numerical_admission': 'HOLD'})

    costs = []
    for index, artifact, member in [
        (1, 'preparation/v1/hcsn-c2-execution-candidate-20261110-v1.zip', 'attempt-01/RESULT.json'),
        (2, 'preparation/v1/hcsn-c2-execution-candidate-20261110-v1.zip', 'attempt-02/RESULT.json'),
        (3, 'preparation/v2/hcsn-c2-execution-candidate-20261110-v2.zip', 'c2-execution-validation-attempt-03/RESULT.json'),
        (4, 'preparation/v3-review-original.zip', 'owner-validation-attempt-04/RESULT.json'),
        (5, 'preparation/v4/VALIDATION-RESULT.json', None),
    ]:
        costs.append(row_cost('software-attempt-' + str(index), artifact,
                              ['whole_process_wall_seconds', 'children_cpu_seconds'],
                              'Distinct cloud synthetic software test attempt; no production fit. Nested per-test timers are not added.', member))
    for identifier, path in [
        ('v4-independent-static-review', 'preparation/v4-review/RECEIPT.json'),
        ('decision-independent-review', 'decision-review/RECEIPT.json'),
        ('first14-provenance-independent-closure', 'decision-provenance-review/RECEIPT.json'),
    ]:
        costs.append(row_cost(identifier, path, ['whole_child_wall_seconds', 'whole_waited_child_cpu_seconds'],
                              'Complete local stdlib metadata review child; no model or numerical oracle execution.'))
    costs.append(row_cost('v3-native-preflight-and-separate-archive', 'native-preflight/HANDOFF.json',
                          ['gnu_outer_full_wall_seconds_rounded', 'gnu_outer_user_seconds_rounded', 'gnu_outer_system_seconds_rounded',
                           'native_archive_gnu_full_wall_seconds_rounded', 'native_archive_gnu_user_system_seconds_rounded'],
                          'Preflight and archive are distinct processes. GNU preflight totals contain 53 tests, six bind-only checks and controller work; do not add their child timers.'))
    costs.append(row_cost('readonly-first-step-observer', 'first-step/HANDOFF.json',
                          ['observer_gnu_full_wall_seconds_rounded', 'observer_gnu_user_system_seconds_rounded'],
                          'Complete read-only observer, including its archive work. Its six observed optimizer steps belong to the ongoing C2 fits, not the observer.'))
    costs.append({'id': 'retained-counterexamples-and-transport', 'artifacts': ['preparation/v2/hcsn-c2-execution-candidate-20261110-v2.zip',
                  'preparation/v3-review-original.zip', 'native-preflight/CONTROL-PLANE-ARCHIVE.json', 'first-step/CONTROL-PLANE-ARCHIVE.json'],
                  'scope': 'Original counterexample costs, transfer failures, same-ID reconciliations, duplicate read observations, packaging and byte-recovery measurements remain in original receipts. Partial/main-entry/CPU-prefix timers are not complete process totals.',
                  'complete_summed_wall_seconds': None, 'complete_summed_CPU_seconds': None})
    costs.append({'id': 'ongoing-c2-six-fits', 'artifact': 'launch/FIRST-COMMANDS.jsonl',
                  'scope': 'Cumulative 43200-second allowance per fit includes original full outer wall and all new work. No discarded-work refund. Ongoing fits have no final process totals in this snapshot.',
                  'parent_summed_full_outer_wall_seconds': sum(f['parent_full_outer_wall_charged'] for f in fits),
                  'c2_complete_summed_wall_seconds': None, 'c2_complete_summed_CPU_seconds': None,
                  'energy_joules': None, 'billed_currency': None})
    write('COSTS.json', {'schema': 'c2-launch-cost-index-v1', 'rows': costs, 'accounting_complete': False,
          'additive_grand_total': None, 'energy_joules': None, 'billed_currency': None,
          'rule': 'Retain every failed preparation and original partial training work. Do not add nested/overlapping timers. Unknown is not zero.',
          'curation_cost': 'COPY-RECEIPT.json'})
    write('STATUS.json', {'schema': 'c2-launch-status-v1', 'record_sealed_utc': datetime.now(timezone.utc).isoformat(),
          'observation_asof_utc': summary['observed_utc'], 'actual_continuations_started': 6,
          'fresh_independent_fits_started': 0, 'first_step_witnesses_observed': 6,
          'continuation_complete_epochs_at_this_observation': 0, 'training_terminal_status': 'pending_at_observation',
          'training_adequacy': 'not_yet_granted', 'whole_training_numerical_admission': 'HOLD',
          'scientific_admission': 'HOLD', 'P5_benefit_gate': 'unchanged',
          'old_same_budget_results_unchanged': True, 'release_published': False, 'main_merged': False,
          'future_terminal_evidence': 'A separate immutable appendix is required; this snapshot must not be rewritten.'})
    assert all(identity(Path(c['source'])) == identity(DEST / c['target']) == {'bytes': c['bytes'], 'sha256': c['sha256']} for c in COPIED)
    write('COPY-RECEIPT.json', {'schema': 'c2-launch-exact-copy-v1', 'copied': COPIED,
          'source_files_unchanged': True, 'main_entry_wall_seconds': time.perf_counter() - start,
          'main_entry_CPU_seconds': time.process_time() - cpu,
          'scope': 'Local exact copies, archive CRC/member hashes and saved-scalar indexing. Excludes imports, final receipt/manifest write and process exit.',
          'model_or_oracle_execution': False})
    files = {p.relative_to(DEST).as_posix(): identity(p) for p in sorted(DEST.rglob('*')) if p.is_file()}
    write('MANIFEST.json', {'schema': 'c2-launch-evidence-manifest-v1', 'files': files,
          'scientific_admission': 'HOLD', 'whole_training_numerical_admission': 'HOLD'})
    print(json.dumps({'members': len(files), 'manifest': identity(DEST / 'MANIFEST.json'),
                      'archive_count': len(archive_index), 'actual_continuations_observed': 6}))


if __name__ == '__main__':
    main()
