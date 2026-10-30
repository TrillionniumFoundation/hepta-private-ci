"""Tiny isolated bundles exercise destination mapping, reuse and rejection."""

import hashlib
import json
from pathlib import Path
import tempfile

from experiments.hcsn_free_boundary_v1 import archive
from experiments.hcsn_distributional_v2 import restore_artifacts as restored


HERE = Path(__file__).resolve().parent


def small_bundle(source, artifact_dir, name, member, payload):
    (source / member).parent.mkdir(parents=True, exist_ok=True)
    (source / member).write_bytes(payload)
    archive.pack(source, artifact_dir, name, part_bytes=4096)


checks = {}
with tempfile.TemporaryDirectory(prefix='tiny_fixture_', dir=HERE) as temporary:
    base = Path(temporary)
    checkout, raw = base / 'checkout', base / 'explicit_raw'
    v1 = checkout / 'experiments/hcsn_free_boundary_v1'
    v2 = checkout / 'experiments/hcsn_distributional_v2'
    cases = [
        ('original_data', 'mnist/raw_fixture.txt', raw, b'raw fixture\n'),
        ('auxiliary_evidence', 'data/study001/aux_fixture.txt', v1, b'aux fixture\n'),
        ('study001_evidence', 'results/study001/main_fixture.txt', v1, b'main fixture\n'),
        ('conditional001_evidence', 'results/conditional001/conditional_fixture.txt', v1, b'conditional fixture\n'),
        ('equal_updates_core002_evidence', 'equal_fixture.txt', v1 / 'results/equal_updates_core002', b'equal fixture\n'),
    ]
    for name, member, target, payload in cases:
        small_bundle(base / ('source_' + name), v1 / 'artifacts', name, member, payload)
    small_bundle(base / 'v2_source', v2 / 'artifacts', 'some_new_main_name',
                 'results/main_fixture001/value.txt', b'v2 initial fixture\n')
    (v2 / 'artifacts/sidecar.json').write_text('{"schema":"execution-receipt.v1","status":"completed"}\n')
    catalog = restored.discover(checkout, raw)
    checks['five_v1_and_schema_discovered_v2'] = len(catalog['bundles']) == 6
    checks['equal_updates_destination_is_its_study_root'] = next(
        row['destination'] for row in catalog['bundles'] if row['name'] == 'equal_updates_core002_evidence') == str(v1 / 'results/equal_updates_core002')
    restored.run('list', checkout_root=checkout, raw_root=raw, receipt_dir=HERE / 'list_fixture')
    checks['listing_did_not_extract'] = not (raw / 'mnist/raw_fixture.txt').exists()
    restored.run('restore', checkout_root=checkout, raw_root=raw, receipt_dir=HERE / 'first_restore')
    checks['all_five_v1_destinations_correct'] = all((target / member).read_bytes() == payload
                                                   for _, member, target, payload in cases)
    checks['v2_restored_to_package_root'] = (v2 / 'results/main_fixture001/value.txt').read_bytes() == b'v2 initial fixture\n'
    restored.run('restore', checkout_root=checkout, raw_root=raw, receipt_dir=HERE / 'identical_restore')
    checks['identical_existing_files_reused'] = all((target / member).read_bytes() == payload
                                                   for _, member, target, payload in cases)
    conflict = raw / 'mnist/raw_fixture.txt'
    conflict.write_bytes(b'preexisting different bytes\n')
    try:
        restored.run('restore', checkout_root=checkout, raw_root=raw, receipt_dir=HERE / 'different_existing_rejected')
    except RuntimeError:
        checks['different_existing_content_refused_and_preserved'] = conflict.read_bytes() == b'preexisting different bytes\n'
    else:
        checks['different_existing_content_refused_and_preserved'] = False
    small_bundle(base / 'future_source', v2 / 'artifacts/nested_future', 'later_lif_bundle',
                 'results/future_lif001/value.txt', b'future bundle discovered\n')
    only_v2 = restored.discover(checkout, only_v2=True)
    checks['later_nested_v2_manifest_auto_discovered'] = len(only_v2['bundles']) == 2
    restored.run('restore', checkout_root=checkout, only_v2=True, receipt_dir=HERE / 'v2_only_future_restore')
    checks['only_v2_skips_v1_conflict_and_needs_no_raw_root'] = (
        (v2 / 'results/future_lif001/value.txt').read_bytes() == b'future bundle discovered\n'
        and conflict.read_bytes() == b'preexisting different bytes\n')
    try:
        restored.run('restore', checkout_root=checkout, receipt_dir=HERE / 'raw_root_required')
    except ValueError as error:
        checks['full_restore_requires_explicit_raw_root'] = '--raw-root' in str(error)
    else:
        checks['full_restore_requires_explicit_raw_root'] = False
    try:
        restored.ensure_receipt_scope(v2 / 'results/sealed001/receipt', checkout)
    except ValueError:
        checks['sealed_fixture_receipt_destination_rejected'] = True
    else:
        checks['sealed_fixture_receipt_destination_rejected'] = False
    try:
        restored.ensure_receipt_scope(restored.ROOT / 'experiments/hcsn_distributional_v2/results/task_value002/bad_receipt')
    except ValueError:
        checks['sealed_real_receipt_destination_rejected_without_write'] = True
    else:
        checks['sealed_real_receipt_destination_rejected_without_write'] = False

result = {'status': 'passed' if all(checks.values()) else 'failed', 'checks': checks,
          'large_project_bundles_restored': 0, 'new_training_or_inference': False,
          'restore_source_sha256': hashlib.sha256(Path(restored.__file__).read_bytes()).hexdigest(),
          'archive_source_sha256': hashlib.sha256(Path(archive.__file__).read_bytes()).hexdigest(),
          'scope': 'Only tiny temporary fixtures; expected failures are retained in their own receipt directories'}
(HERE / 'RESULTS.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
assert all(checks.values()), checks
print(json.dumps(result), flush=True)
