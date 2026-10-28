"""Package completed scopes and actually restore each bundle without new inference."""

import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import time

from experiments.analytic_event_neuron.round2 import restore_evidence
from experiments.analytic_event_neuron.round3 import freeze
from experiments.analytic_event_neuron.round3.evidence.package_evidence import package, sha


def execute(selections):
    root = Path('/tmp/aen-round3-20261028')
    repo = Path('/workspace/scratch/d831a963ef2f/hepta-analytic')
    destination = repo / 'experiments/analytic_event_neuron/round3/evidence/confirmation'
    descriptions = Path('/tmp/aen-r3-feedback-runtime-archives.json')
    frozen = freeze.verify(root)
    document = json.loads(descriptions.read_text()) if descriptions.exists() else {
        'schema': 'hepta.round3.feedback-runtime-archive-descriptors.v1',
        'source_commit': frozen['source_commit'], 'archives': []}
    if document['source_commit'] != frozen['source_commit']:
        raise ValueError('Descriptor source identity differs')
    reviews = root / 'archival_reviews'
    reviews.mkdir(exist_ok=True)
    for selection in selections:
        free_before = os.statvfs('/tmp').f_bfree * os.statvfs('/tmp').f_frsize
        if free_before < 250_000_000:
            raise RuntimeError('Below authorized 250MB free-space threshold; no bundle started')
        phase = 'runtime' if selection == 'runtime' else 'feedback'
        index = json.loads((root / (phase.upper() + '_INDEX.json')).read_text())
        if not index['complete'] or index['source_commit'] != frozen['source_commit']:
            raise ValueError('Phase is not complete and frozen')
        if selection == 'runtime':
            name, selected_scopes, relative = 'RUNTIME_CONFIRMATION', index['scopes'], ['runtime_confirmation']
        else:
            seed = int(selection)
            selected_scopes = [s for s in index['scopes'] if s['seed'] == seed]
            if len(selected_scopes) != 1:
                raise ValueError('Unregistered or duplicated feedback seed')
            name, relative = f'FEEDBACK_CONFIRMATION_{seed}', [f'feedback_confirmation/seed_{seed}']
        if any(row['name'] == name for row in document['archives']):
            raise ValueError('Bundle already registered; do not repack completed evidence')
        expected_files = {path: digest for scope in selected_scopes for path, digest in scope['files_sha256'].items()}
        for path, expected in expected_files.items():
            if sha(root / path) != expected:
                raise ValueError('Original scope changed: ' + path)
        started = time.perf_counter_ns()
        descriptor = package(root, relative, repo, destination, name, restore_root='run')
        package_ns = time.perf_counter_ns() - started
        document['archives'].append(descriptor)
        temporary_descriptor = descriptions.with_suffix('.json.pending')
        temporary_descriptor.write_text(json.dumps(document, sort_keys=True, indent=2) + '\n')
        temporary_descriptor.replace(descriptions)
        restored_started = time.perf_counter_ns()
        temporary = Path(tempfile.mkdtemp(prefix='aen-r3-feedback-runtime-restore-'))
        receipt = {'schema': 'hepta.round3.bundle-restoration-review.v1',
            'name': name, 'source_commit': frozen['source_commit'], 'archive_sha256': descriptor['sha256'],
            'archive_bytes': descriptor['bytes'], 'data_members': descriptor['data_members'],
            'source_manifest_matches_completed_phase_index': False, 'restored': False,
            'temporary_restore_directory_removed': False, 'scientific_data_regenerated': False,
            'original_scope_or_prepared_files_changed': False, 'package_ns': package_ns,
            'free_bytes_before': free_before, 'restore_script_sha256': sha(Path(restore_evidence.__file__)),
            'packager_sha256': sha(Path(__file__)), 'passed': False}
        try:
            materialized = restore_evidence.materialize(repo, descriptor, temporary)
            expected = restore_evidence.verify_members(materialized, descriptor['member_manifest'])
            if expected != expected_files:
                raise ValueError('Bundle inventory differs from completed phase index')
            receipt['source_manifest_matches_completed_phase_index'] = True
            restored = temporary / 'restored' / descriptor['restore_root']
            restore_evidence.restore(materialized, restored, descriptor['member_manifest'], expected)
            for relative_name, expected_sha in expected.items():
                original, copy = root / relative_name, restored / relative_name
                if sha(original) != expected_sha or sha(copy) != expected_sha:
                    raise ValueError('Restored data or original scope changed')
                if stat.S_IMODE(original.stat().st_mode) != stat.S_IMODE(copy.stat().st_mode):
                    raise ValueError('Restored file permissions differ')
            receipt.update(restored=True, restored_file_hashes=expected, file_bytes_and_modes_match_original=True,
                           member_hashes_verified=True, passed=True)
        finally:
            shutil.rmtree(temporary)
            receipt.update(temporary_restore_directory_removed=not temporary.exists(),
                restore_verification_ns=time.perf_counter_ns() - restored_started,
                free_bytes_after=os.statvfs('/tmp').f_bfree * os.statvfs('/tmp').f_frsize)
            with (reviews / (name + '_RESTORE.json')).open('x') as stream:
                json.dump(receipt, stream, sort_keys=True, indent=2)
                stream.write('\n')
        freeze.verify(root)
        print(json.dumps({'name': name, 'bytes': descriptor['bytes'], 'data_members': descriptor['data_members'],
                          'restored': receipt['restored'], 'passed': receipt['passed'],
                          'free_bytes_after': receipt['free_bytes_after']}), flush=True)
    return document


if __name__ == '__main__':
    execute(sys.argv[1:])
