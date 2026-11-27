"""Validate and index restored native cost originals; never import model code."""

import hashlib
import json
from pathlib import Path
import zipfile


ROOT = Path('/workspace/scratch/c385a7439f8e/native-hcsn-cost-recovery-v1')
DEST = 'qualification/hcsn_differentiable/evidence/p0p5-20261110/p2/native-cost-originals-v1'
REPO = Path('/workspace/scratch/c385a7439f8e/hcsn-repo')
GROUPS = {
    'hcsn-cost-v1': ('v3', ['g128-uncached-b1', 'g128-cached-b1', 'g256-cached-b32']),
    'hcsn-effective32-cost-v6': ('v6', ['micro4', 'micro8']),
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def info(path):
    data = path.read_bytes()
    return {'path': path.relative_to(ROOT).as_posix(), 'bytes': len(data), 'sha256': digest(data)}


def read(path):
    return json.loads(path.read_bytes())


def write_exact(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == data, path
    else:
        with path.open('xb') as stream:
            stream.write(data)


def write_json(path, obj):
    write_exact(path, (json.dumps(obj, indent=2, ensure_ascii=False) + '\n').encode())


def main():
    originals, checks, source_checks = [], [], []
    receipt = read(ROOT / 'binary-read-receipts-final-metadata.json')
    for item in receipt['files']:
        path = ROOT / item['group'] / item['relative']
        actual = info(path)
        assert actual['bytes'] == item['bytes']
        assert actual['sha256'] == item['sha256']
        assert item['read_receipt']['eof'] is True
        assert item['read_receipt']['chunk_sha256'] == actual['sha256']
        originals.append(actual)
    assert len(originals) == 39

    archive_files = {}
    for version in ('v3', 'v6'):
        path = ROOT / 'source-identities' / f'training-source-{version}.zip'
        originals.append(info(path))
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
            manifest = json.loads(archive.read('SOURCE_MANIFEST.json'))
            members = {name: digest(archive.read(name)) for name in archive.namelist()}
            for name, expected in manifest['files'].items():
                assert members[name] == expected, (version, name)
            archive_files[version] = members
            source_checks.append({'version': version, 'archive': info(path),
                                  'manifest_members_verified': len(manifest['files']),
                                  'zip_crc_verified': True,
                                  'source_manifest_sha256': members['SOURCE_MANIFEST.json']})

    cases, controllers, missing_large = [], [], []
    for group, (version, names) in GROUPS.items():
        controller_path = ROOT / group / 'RESULT.json'
        controller = read(controller_path)
        indexed_attempts = {x['name']: x for x in controller['attempts']}
        group_rows = []
        for name in names:
            base = ROOT / group / name
            result = read(base / 'RESULT.json')
            outer = read(ROOT / group / f'{name}-receipt.json')
            assert outer == indexed_attempts[name]
            assert info(base / 'plan.json')['sha256'] == result['plan_sha256']
            assert result['source_before'] == result['source_after']
            assert result['source_unchanged'] is True
            assert result['common_weights_unchanged'] is True
            project_count = 0
            external_hashes = {}
            prefix = f'/run-source-{version}/'
            for source, expected in result['source_before'].items():
                if prefix in source:
                    relative = source.split(prefix, 1)[1]
                    assert archive_files[version][relative] == expected, relative
                    project_count += 1
                else:
                    external_hashes[source] = expected
            for stream in ('stdout', 'stderr'):
                path = ROOT / group / f'{name}.{stream}'
                assert info(path)['sha256'] == outer[f'{stream}_sha256']
            artifacts = {}
            for relative, expected in result['artifacts'].items():
                path = base / relative
                if path.exists():
                    entry = info(path)
                    assert entry['sha256'] == expected, path
                    artifacts[relative] = entry
                    if relative.endswith('.pt'):
                        originals.append(entry)
                else:
                    missing_large.append({'path': f'{group}/{name}/{relative}',
                                          'expected_sha256_from_original_result': expected,
                                          'local_copy_recovered': False})
            row = {'group': group, 'case': name, 'source_version': version,
                   'result': info(base / 'RESULT.json'), 'process_receipt': info(ROOT / group / f'{name}-receipt.json'),
                   'plan': info(base / 'plan.json'), 'status': result['status'],
                   'returncode': outer['returncode'], 'updates_completed': len(result['steps']),
                   'complete_training_epochs': result['complete_training_epochs'],
                   'inner_profile_wall_seconds': result['wall_seconds'],
                   'inner_profile_cpu_seconds': result['cpu_seconds'],
                   'whole_process_wall_seconds': outer['whole_process_wall_seconds'],
                   'peak_rss_bytes': result['peak_rss_bytes'],
                   'data_manifest_sha256': result['data_manifest_sha256'],
                   'source_archive_sha256': info(ROOT / 'source-identities' / f'training-source-{version}.zip')['sha256'],
                   'bound_project_source_files_verified': project_count,
                   'external_source_hashes_recorded_not_copied': external_hashes,
                   'artifacts_recovered': artifacts,
                   'energy_joules': None, 'currency_cost': None,
                   'scientific_admission': 'HOLD', 'numerical_admission': 'HOLD'}
            if name == 'g256-cached-b32':
                assert outer['returncode'] == 2 and not result['steps']
                assert 'DefaultCPUAllocator' in result['error']
                assert 'Error code 12 (Cannot allocate memory)' in result['error']
                row['failure'] = {'kind': 'handled_CPU_allocator_failure',
                                  'requested_allocation_bytes': 16842752,
                                  'address_space_limit_bytes': 8589934592,
                                  'OS_OOM_kill_claimed': False,
                                  'error_original': f'{group}/{name}/RESULT.json:error'}
            group_rows.append(row)
            cases.append(row)
        controllers.append({'group': group, 'original': info(controller_path),
                            'whole_controller_wall_seconds': controller['whole_wall_seconds'],
                            'controller_children_cpu_seconds': controller['children_cpu_seconds'],
                            'sum_child_process_wall_seconds': sum(x['whole_process_wall_seconds'] for x in group_rows),
                            'sum_inner_profile_wall_seconds': sum(x['inner_profile_wall_seconds'] for x in group_rows),
                            'sum_inner_profile_cpu_seconds': sum(x['inner_profile_cpu_seconds'] for x in group_rows),
                            'timing_relationship': 'Nested scopes; do not add the controller, process, and inner values.'})

    originals = sorted({x['path']: x for x in originals}.values(), key=lambda x: x['path'])
    assert len(originals) == 46
    derived_path = REPO / 'qualification/hcsn_differentiable/evidence/p0p5-20261110/p2/hcsn-effective32-derived-summary.json'
    derived_bytes = derived_path.read_bytes()
    derived = json.loads(derived_bytes)
    assert derived['outer'] == read(ROOT / 'hcsn-effective32-cost-v6/RESULT.json')
    for name in ('micro4', 'micro8'):
        sha = info(ROOT / 'hcsn-effective32-cost-v6' / name / 'RESULT.json')['sha256']
        assert sha in derived_bytes.decode()
    checks.append({'kind': 'existing_derived_view_binding', 'path': str(derived_path),
                   'sha256': digest(derived_bytes), 'controller_exact_match': True,
                   'both_original_result_hashes_match': True, 'derived_file_unchanged': True})

    summary = {'schema': 'native-cost-original-recovery-v1',
               'kind': 'new_recovery_index_not_an_original_execution_summary',
               'native_host': 'desktop',
               'native_root': '/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training',
               'original_files': len(originals), 'original_bytes': sum(x['bytes'] for x in originals),
               'metadata_original_files': 39, 'small_checkpoint_files': 5, 'source_archives': 2,
               'checkpoint_transfer_note': 'Four checkpoints directly read with chunk receipts; uncached after.pt materialized from verified identical cached bytes and both original RESULT hashes. See separate receipt. No pickle/model execution.',
               'source_verification': source_checks, 'checks': checks,
               'cases': cases, 'controllers': controllers,
               'not_copied_here': missing_large,
               'old_cost_v1_complete_context_archive': {'asset_id': 731775347, 'bytes': 18118346,
                    'sha256': 'b40b214bbee098e4fe4d74986faf410068011d967ac50c8e6b60d3c4da5eb56c',
                    'authenticated_readback_verified_in_prior_publication_receipt': True,
                    'archive_members_not_reopened_in_this_recovery': True},
               'cost_accounting': {'add_v3_attempts_if_previously_missing': True,
                    'micro4_micro8_existing_costs_replace_evidence_reference_not_add_duplicate_cost': True,
                    'profile_timer_scope': 'Starts after imports, argument parsing, output directory and thread setup; ends in finally before source-after/artifact-hash work and RESULT serialization.',
                    'profile_cpu_scope': 'time.process_time delta over the profile timer interval',
                    'outer_process_scope': 'Original process receipt whole_process_wall_seconds',
                    'controller_scope': 'Original group RESULT whole_wall_seconds and children_cpu_seconds; overlaps the child intervals',
                    'new_training_or_numerical_computation': False}}
    write_json(ROOT / 'RECOVERY_INDEX.json', summary)

    text = '''# Native HCSN cost originals recovered

This is a new recovery index. The execution files beneath `hcsn-cost-v1/` and
`hcsn-effective32-cost-v6/` retain their original bytes. No training or numerical
qualification was rerun. Existing derived views are preserved separately.

There are 39 original JSON/log/launch/process/controller files, 5 small checkpoints,
and 2 exact source ZIPs. The four directly transferred checkpoints have pinned
binary chunk receipts. The uncached128 `after.pt` is a content-addressed copy of
the directly verified cached128 bytes: both original RESULTs specify the same
SHA256. This exception is explicit in its separate receipt; no direct target read
or pickle execution is claimed. Large successful traces remain outside this small
recovery bundle. Full old cost-v1 originals remain in the previously authenticated
context archive identified in RECOVERY_INDEX.json.

The source-v3 batch32 attempt failed before a completed update, with exit code 2
and an explicit CPU allocator error under an 8 GiB address-space limit. Its peak
RSS is 4,383,834,112 bytes. This is a handled allocation failure; an OS OOM kill is
not inferred. The successful source-v6 micro4/micro8 attempts are separate later
configurations with a learned common core adapter. They do not replace that cost.

Use `RECOVERY_INDEX.json` for exact inner wall/CPU, complete process wall, controller
wall/children CPU, return codes, project-source bindings, and missing artifact
identities. These timers overlap: do not add levels. When referencing the restored
micro4/micro8 originals, retain their previously charged costs rather than adding
the same attempts again. All five remain bounded cost probes, with no completed
training epoch and no new scientific or numerical admission.

`COPY_PROPOSAL.json` specifies the immutable small files for the repository.
`RECOVERED_MANIFEST.json` hashes the complete proposed payload. Transfer scratch
chunks and interim receipts are excluded from the proposed payload.
'''
    write_exact(ROOT / 'README.md', text.encode())

    selected = {x['path'] for x in originals}
    selected.update({'binary-read-receipts-final-metadata.json',
                     'checkpoint-content-addressed-copy-receipt.json',
                     'source-identities/training-source-v3.zip.binary-read.json',
                     'source-identities/training-source-v6.zip.binary-read.json',
                     'RECOVERY_INDEX.json', 'README.md'})
    selected.update(p.relative_to(ROOT).as_posix() for p in (ROOT / 'checkpoint-binary-receipts').rglob('*.json'))
    write_exact(ROOT / 'build_recovery_index.py', Path(__file__).read_bytes())
    selected.add('build_recovery_index.py')
    entries = [info(ROOT / relative) for relative in sorted(selected)]
    assert all(x['bytes'] <= 512000 for x in entries)
    manifest = {'schema': 'native-cost-recovery-manifest-v1', 'files': entries,
                'files_total': len(entries), 'bytes_total': sum(x['bytes'] for x in entries)}
    write_json(ROOT / 'RECOVERED_MANIFEST.json', manifest)
    proposal_entries = entries + [info(ROOT / 'RECOVERED_MANIFEST.json')]
    proposal = {'schema': 'native-cost-recovery-copy-proposal-v1',
                'source_root': str(ROOT), 'destination_root_in_repository': DEST,
                'files': proposal_entries, 'include_this_proposal_at_destination': True,
                'global_index_changes_performed': False,
                'existing_derived_view_modified': False}
    write_json(ROOT / 'COPY_PROPOSAL.json', proposal)
    print(json.dumps({'summary': info(ROOT / 'RECOVERY_INDEX.json'),
                      'manifest': info(ROOT / 'RECOVERED_MANIFEST.json'),
                      'proposal': info(ROOT / 'COPY_PROPOSAL.json'),
                      'original_files': len(originals), 'proposed_payload_files': len(proposal_entries) + 1,
                      'controllers': controllers}, indent=2))


if __name__ == '__main__':
    main()
