#!/usr/bin/env python3
"""Freeze and archive saved 1a979 evidence in the cloud; never contact a host."""

import argparse
from collections import Counter, defaultdict
from hashlib import sha1, sha256
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import time

ROOT = Path('/workspace/scratch/e9e051ab0825')
HERE = Path(__file__).resolve().parent
PREFIX = 'evidence/e6-c-generation-original-readback-20261120'
SOURCE = '1a9799686243c2be0ee393ba364e091029cfb944'
TREE = '931a344b1ea3e2ddf45e917ea4b3ae37c504ed05'
MAX_PART = 480000
BASE = ROOT / 'metrics_integration/final_evidence_publication_work/FROZEN_535_FILES.json'
BASE_SHA = '10e1e469f5f2fa85daab4fb6ea9244d3babbb5beb2fb0ed55347422e7cbe371a'
READBACK = ROOT / 'e6_c_generation_actual_readback_1'
READBACK_MANIFEST_SHA = '5d9e9be084eb18958c22d07e74361d8b5a176f179854809a7cd6d54ff5fb433a'
READBACK_SHA = '63a6857543066310ae859724dd60131d1cda723248e59ffff9d30b1deba2a1f6'


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def digest(data):
    return {'bytes': len(data), 'sha256': sha256(data).hexdigest(),
            'git_blob': sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def read(path, expected=None):
    path = Path(path)
    assert path.is_file() and not path.is_symlink(), str(path)
    data = path.read_bytes()
    pin = digest(data)
    if expected:
        for key in ('bytes', 'sha256', 'git_blob'):
            if key in expected:
                assert pin[key] == expected[key], (str(path), key)
    return data, pin


def load(path, expected=None):
    return json.loads(read(path, expected)[0])


def safe(path):
    p = PurePosixPath(path)
    assert not p.is_absolute() and path and '..' not in p.parts and '.' not in p.parts
    assert '\\' not in path and '\0' not in path
    return path


def row_for_repo(row):
    return {key: row[key] for key in ('path', 'bytes', 'sha256', 'git_blob')}


def existing_catalog():
    baseline = load(BASE, {'sha256': BASE_SHA})
    assert len(baseline) == 535 and len({r['path'] for r in baseline}) == 535
    by_hash = defaultdict(list)
    for row in baseline:
        safe(row['path'])
        read(row['local_path'], row)
        assert row['git_blob'] == row['server_sha']
        by_hash[row['sha256']].append(row)
    for rows in by_hash.values():
        rows.sort(key=lambda row: row['path'])
    return baseline, by_hash


def archive_catalog(by_hash):
    descriptions = [
        ('dbd6-host', ROOT / 'e6_diagnostic_host_archive_readback_1/retained',
         ROOT / 'e6_diagnostic_host_archive_readback_1/restored/MANIFEST.json', 'files', 'path'),
        ('dbd6-cloud', ROOT / 'e6_diagnostic_cloud_archive_1/pack-2-actual-host-closure',
         ROOT / 'e6_diagnostic_cloud_archive_1/pack-2-actual-host-closure/MANIFEST.json', 'originals', 'member'),
    ]
    archives = {}
    member_by_hash = defaultdict(list)
    for label, folder, manifest_path, entries, member_key in descriptions:
        part_index_path = folder / 'archive-parts.json'
        part_index_bytes, part_index_pin = read(part_index_path)
        assert part_index_pin['sha256'] in by_hash
        index = json.loads(part_index_bytes)
        whole = folder / index['archive_name']
        _, whole_pin = read(whole, {'bytes': index['archive_bytes'], 'sha256': index['archive_sha256']})
        joined = sha256()
        total = 0
        parts = []
        for part in index['parts']:
            data, actual = read(folder / part['name'], part)
            assert actual['sha256'] in by_hash
            joined.update(data)
            total += len(data)
            parts.append({'name': part['name'], **actual,
                          'repository_file': row_for_repo(by_hash[actual['sha256']][0])})
        assert total == whole_pin['bytes'] and joined.hexdigest() == whole_pin['sha256']
        mb, mpin = read(manifest_path)
        manifest = json.loads(mb)
        archives[label] = {
            'id': label, 'local_archive': str(whole), **whole_pin,
            'original_manifest': {'local_path': str(manifest_path), **mpin},
            'part_index_repository_file': row_for_repo(by_hash[part_index_pin['sha256']][0]),
            'parts': parts,
        }
        for row in manifest[entries]:
            safe(row[member_key])
            member_by_hash[row['sha256']].append({
                'archive_id': label, 'member': row[member_key],
                'bytes': row['bytes'], 'sha256': row['sha256'],
            })
    return archives, member_by_hash


def prepare():
    out = HERE / 'frozen-inputs-2'
    assert not out.exists(), 'do not replace a frozen input set'
    out.mkdir(parents=True)
    started = time.monotonic()
    baseline, by_hash = existing_catalog()
    archives, archived = archive_catalog(by_hash)
    selected = {}

    def add(path, role, expected=None):
        path = Path(path)
        rel = safe(str(path.relative_to(ROOT)))
        _, pin = read(path, expected)
        if rel in selected:
            assert all(selected[rel][key] == pin[key] for key in pin)
            if role not in selected[rel]['roles']:
                selected[rel]['roles'].append(role)
        else:
            selected[rel] = {'workspace_path': rel, 'local_path': str(path),
                             **pin, 'roles': [role]}

    package = load(READBACK / 'MANIFEST.json', {'sha256': READBACK_MANIFEST_SHA})
    assert package['count'] == len(package['files']) == 363
    add(READBACK / 'MANIFEST.json', 'finite_actual_readback_manifest')
    for row in package['files']:
        add(READBACK / safe(row['path']), 'finite_actual_readback_saved_member', row)
    actual = load(READBACK / 'READBACK_MANIFEST.json', {'sha256': READBACK_SHA})
    assert actual['source'] == SOURCE and actual['tree'] == TREE
    assert actual['logical_paths'] == 256
    assert actual['status_counts'] == {
        'COMPLETE_EXACT_BODY': 160,
        'EXACT_BODY_REUSED_BY_OBSERVED_OR_EXECUTION_BOUND_SHA': 90,
        'PRESERVED_PRIOR_MISSING_OBSERVATION': 6,
    }
    assert actual['new_purpose_built_read_RPC_count'] == 201
    assert len(list((READBACK / 'rpc').glob('*.json'))) == 201

    def known_paths(value):
        if isinstance(value, str) and value.startswith(str(ROOT) + '/'):
            add(value, 'literal_local_dependency_of_finite_readback')
        elif isinstance(value, list):
            for child in value:
                known_paths(child)
        elif isinstance(value, dict):
            for child in value.values():
                known_paths(child)
    known_paths(actual)

    plan_root = ROOT / 'e6_c_generation_evidence_plan_1'
    pm = load(plan_root / 'MANIFEST.json', {'sha256': '04ddfe2d85da9704d0a42cca1dd707ebb3b7ab9300b5bb30f2b8d7ae3b15f7da'})
    add(plan_root / 'MANIFEST.json', 'original_finite_plan_manifest')
    for row in pm['files']:
        add(plan_root / safe(row['path']), 'original_finite_plan_member', row)
    planned = load(plan_root / 'CLOUD_INPUTS.json')
    assert len(planned['files']) == 187
    for row in planned['files']:
        add(row['local_path'], 'prior_frozen_plan:' + row['role'], row)

    for relative, role in (
        ('e6_c_generation_full_original_readback_1', 'root_three_actual_originals_and_literal_chunk_RPC'),
        ('e6_owner_work/c_generation_noupdate13_failure/childlogs-independent-2', 'independent_twelve_actual_child_logs_and_capture_receipts'),
    ):
        folder = ROOT / relative
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                add(path, role)
    # Close actual capture/lstat failures and the successful independent capture's
    # existing source/payload/RPC receipts, without silently taking future files.
    failure_root = ROOT / 'e6_owner_work/c_generation_noupdate13_failure'
    explicit = [
        'TARGET_LSTAT_RESULT.json', 'TARGET_LSTAT_TERMINAL.json',
        'CHILD_LOG_CAPTURE_TERMINAL.json', 'CAPTURE_LOCK_PATH_READBACK_0.json',
        'CAPTURE_LOCK_PATH_READBACK_1.json', 'CHILD_LOG_NATIVE_READ_1.json',
        'CHILD_LOG_INDEPENDENT_CAPTURE_BODIES_READBACK.json',
        'CHILD_LOG_INDEPENDENT_CAPTURE_META_READBACK.json',
        'CHILD_LOG_INDEPENDENT_CAPTURE_META_READBACK_2.json',
        'CHILD_LOG_INDEPENDENT_CAPTURE_OWNER_START.json',
        'CHILD_LOG_INDEPENDENT_CAPTURE_TERMINAL.json',
        'ROOT_CHILD_LOG_INDEPENDENT_CAPTURE_REVIEW.json',
    ]
    for name in explicit:
        add(failure_root / name, 'literal_missing_or_failed_read_evidence')

    add(READBACK / 'ROOT_LOCAL_READBACK.json', 'independent_root_readback_of_all363_members_and177_body_references',
        {'sha256': '6fe43d300759f29249ddd4917f117930690a6309e0fd1cdea3b001e9fe81889b'})
    for path in sorted((HERE / 'frozen-inputs-1').iterdir()):
        if path.is_file():
            add(path, 'first_preparation_scope_retained_no_archive_was_run')
    add(HERE / 'archive_finite_readback.py', 'original_cloud_archive_controller_v1_retained')
    add(HERE / 'PREPARATION_SCOPE_DELTA.json', 'explicit_prepack_scope_addendum')
    add(HERE / 'CONTROLLER_V2.diff', 'explicit_prepack_controller_delta')
    add(BASE, 'existing_535_repository_file_inventory')
    add(Path(__file__), 'cloud_only_archive_controller')
    files = sorted(selected.values(), key=lambda row: row['workspace_path'])
    needs_embedded = defaultdict(dict)
    for row in files:
        h = row['sha256']
        if h in by_hash:
            row['storage'] = {'kind': 'existing_repository_file',
                              'repository_file': row_for_repo(by_hash[h][0])}
        elif h in archived:
            original = sorted(archived[h], key=lambda item: (item['archive_id'], item['member']))[0]
            assert row['bytes'] == original['bytes']
            row['storage'] = {'kind': 'existing_archive_member', **original}
            needs_embedded[original['archive_id']][original['member']] = original
        else:
            row['storage'] = {'kind': 'new_archive_object', 'member': 'objects/' + h + '.bin'}
    embedded_readback = []
    for archive_id, members in needs_embedded.items():
        seen = set()
        with tarfile.open(archives[archive_id]['local_archive'], 'r|xz') as tar:
            for member in tar:
                safe(member.name)
                if member.name in members:
                    assert member.name not in seen and member.isfile()
                    data = tar.extractfile(member).read()
                    expected = members[member.name]
                    assert len(data) == expected['bytes'] and sha256(data).hexdigest() == expected['sha256']
                    embedded_readback.append({'archive_id': archive_id, **expected, 'actual_member_readback': True})
                    seen.add(member.name)
        assert seen == set(members)

    lstat_path = failure_root / 'TARGET_LSTAT_RESULT.json'
    lstat = load(lstat_path)
    observed = {row['path']: row for row in lstat['paths']}
    missing = []
    for row in actual['files']:
        if row['status'] == 'PRESERVED_PRIOR_MISSING_OBSERVATION':
            fact = observed[row['path']]
            assert fact.get('exists') is False
            missing.append({'path': row['path'], 'original_readback_status': row['status'],
                            'actual_lstat_fact': fact, 'evidence_workspace_path': str(lstat_path.relative_to(ROOT)),
                            'evidence_sha256': digest(lstat_path.read_bytes())['sha256'],
                            'later_file_state_or_cause_inferred': False})
    assert len(missing) == 6
    path_index = {row['local_path']: row for row in files}
    source_map = []
    for row in actual['files']:
        item = {'original_host_path': row['path'], 'readback_status': row['status'],
                'roles': row['roles'], 'conditional': row['conditional']}
        if 'body' in row:
            body = row['body']
            chosen = path_index[body['local_path']]
            assert chosen['bytes'] == body['bytes'] and chosen['sha256'] == body['sha256']
            item.update({'body_workspace_path': chosen['workspace_path'], 'bytes': chosen['bytes'],
                         'sha256': chosen['sha256'], 'storage': chosen['storage']})
        else:
            assert row['status'] == 'PRESERVED_PRIOR_MISSING_OBSERVATION'
            item['body'] = None
        source_map.append(item)

    followups = []
    for relative in (
        'e6_owner_work/historical_startup_recovery/rev2/PREFLIGHT_RESULT.json',
        'e6_owner_work/historical_startup_recovery/rev3/PREFLIGHT_RESULT.json',
        'e6_startup_policy_candidate_1/SOURCE_MANIFEST_1.json',
        'e6_startup_policy_candidate_1/MANIFEST.json',
        'e6_noupdate13_startup_policy_peer_1/MANIFEST.json',
    ):
        path = ROOT / relative
        _, pin = read(path)
        assert relative not in selected
        followups.append({'workspace_path': relative, **pin,
                          'disposition': 'separate_future_evidence_layer_not_packaged_as_1a_execution_input'})
    counts = Counter(row['storage']['kind'] for row in files)
    objects = {row['sha256']: row for row in files if row['storage']['kind'] == 'new_archive_object'}
    input_manifest = {
        'schema': 'hepta.e6.1a979.cloud-finite-evidence-inputs.v1',
        'source': SOURCE, 'tree': TREE, 'files': files,
        'logical_saved_files': len(files), 'logical_bytes': sum(row['bytes'] for row in files),
        'storage_counts': dict(counts), 'new_unique_objects': len(objects),
        'new_unique_bytes': sum(row['bytes'] for row in objects.values()),
        'existing_535': {'workspace_path': str(BASE.relative_to(ROOT)), **digest(BASE.read_bytes())},
        'finite_host_path_counts': actual['status_counts'],
        'new_read_RPCs_already_saved': 201, 'new_failed_read_RPCs_preserved': 3,
        'source_map_entries': 256,
        'host_archive_controller_reused': False,
        'host_processes_or_reads_during_cloud_archive': 0,
        'new_tests_models_or_training': 0,
        'whole_noupdate13': 'FAIL', 'new_c_drain_reached': False,
        'new_business_physical_closure': False,
        'scope': 'Only finite saved source/owner/result/output/readback evidence. No recovered ELF, lock, or new native qualification.',
    }
    dependency_data = {
        'baseline_manifest': {'workspace_path': str(BASE.relative_to(ROOT)), **digest(BASE.read_bytes())},
        'archives': [archives[key] for key in sorted(needs_embedded)],
        'selected_existing_archive_members_actual_readback': embedded_readback,
        'baseline_new_copy_not_required': True,
    }
    generated = {
        'INPUT_MANIFEST.json': input_manifest,
        'SOURCE_REUSE_MAP.json': {'schema': 'hepta.e6.finite-host-to-cloud-body-map.v1', 'source': SOURCE, 'files': source_map},
        'MISSING.json': {'scope': 'Six actual prior missing observations, not newly probed and no cause inference', 'files': missing},
        'DEPENDENCIES.json': dependency_data,
        'FOLLOWUPS_NOT_INCLUDED.json': {'qualification_inherited': False, 'files': followups},
    }
    for name, value in generated.items():
        (out / name).write_bytes(encoded(value))
    frozen_files = [{'path': name, **digest((out / name).read_bytes())} for name in sorted(generated)]
    frozen = {'status': 'FROZEN_BEFORE_CLOUD_PACK', 'source': SOURCE, 'tree': TREE,
              'files': frozen_files, 'archive_controller': {'path': str(Path(__file__)), **digest(Path(__file__).read_bytes())},
              'preparation_wall_seconds': time.monotonic() - started,
              'host_actions': 0, 'test_model_native_runs': 0, 'git_operations': 0}
    (out / 'FREEZE.json').write_bytes(encoded(frozen))
    print(json.dumps({'frozen': str(out / 'FREEZE.json'), **digest((out / 'FREEZE.json').read_bytes()),
                      'logical_files': len(files), 'storage_counts': dict(counts),
                      'new_objects': len(objects), 'new_bytes': input_manifest['new_unique_bytes']}))


def add_tar(tar, name, data):
    safe(name)
    item = tarfile.TarInfo(name)
    item.size = len(data)
    item.mode = 0o644
    item.uid = item.gid = item.mtime = 0
    item.uname = item.gname = ''
    tar.addfile(item, io.BytesIO(data))


def write_publication_value(folder, name, data):
    if len(data) <= MAX_PART:
        (folder / name).write_bytes(data)
        return {'name': name, 'kind': 'whole', **digest(data)}
    pieces = []
    partdir = folder / 'metadata-parts' / name
    partdir.mkdir(parents=True)
    for index, offset in enumerate(range(0, len(data), MAX_PART)):
        part = data[offset:offset + MAX_PART]
        rel = str((partdir / f'part-{index:04d}').relative_to(folder))
        (folder / rel).write_bytes(part)
        pieces.append({'path': rel, 'offset': offset, **digest(part)})
    index_name = name + '.reassembly.json'
    index = {'logical_name': name, **digest(data), 'parts': pieces,
             'all_original_bytes_retained': True}
    (folder / index_name).write_bytes(encoded(index))
    return {'name': name, 'kind': 'byte_parts', 'index': index_name, **digest(data)}


def pack():
    freeze_dir = HERE / 'frozen-inputs-2'
    freeze = load(freeze_dir / 'FREEZE.json')
    read(__file__, freeze['archive_controller'])
    for row in freeze['files']:
        read(freeze_dir / row['path'], row)
    inputs = load(freeze_dir / 'INPUT_MANIFEST.json')
    assert inputs['source'] == SOURCE and inputs['tree'] == TREE
    out = HERE / 'pack-1'
    assert not out.exists(), 'preserve previous pack attempts; never overwrite'
    out.mkdir()
    publication = HERE / 'publication'
    assert not publication.exists()
    publication.mkdir()
    started = time.monotonic()
    success = False
    try:
        baseline, by_hash = existing_catalog()
        for row in inputs['files']:
            read(row['local_path'], row)
        unique = {}
        for row in inputs['files']:
            if row['storage']['kind'] == 'new_archive_object':
                unique.setdefault(row['sha256'], row)
        metadata = {row['path']: (freeze_dir / row['path']).read_bytes() for row in freeze['files']}
        metadata['FREEZE.json'] = (freeze_dir / 'FREEZE.json').read_bytes()
        tar_path = out / 'cloud-1a979-finite-originals.tar.xz'
        expected_members = {}
        with tarfile.open(tar_path, 'w:xz', format=tarfile.USTAR_FORMAT, preset=6) as tar:
            for name, data in sorted(metadata.items()):
                member = 'metadata/' + name
                add_tar(tar, member, data)
                expected_members[member] = digest(data)
            for h, row in sorted(unique.items()):
                data, pin = read(row['local_path'], row)
                member = row['storage']['member']
                add_tar(tar, member, data)
                expected_members[member] = pin
        tar_bytes = tar_path.read_bytes()
        archive_pin = digest(tar_bytes)
        seen = set()
        with tarfile.open(tar_path, 'r|xz') as tar:
            for member in tar:
                safe(member.name)
                assert member.isfile() and member.name not in seen
                data = tar.extractfile(member).read()
                assert digest(data) == expected_members[member.name]
                seen.add(member.name)
        assert seen == set(expected_members)
        parts = []
        offset = 0
        while offset < len(tar_bytes):
            end = min(offset + MAX_PART, len(tar_bytes))
            # Move a boundary to an existing NUL byte when possible. This does
            # not add/change any byte; subsequent binary parts begin at NUL.
            if end < len(tar_bytes):
                nul = tar_bytes.rfind(b'\0', offset + 1, end + 1)
                if nul > offset:
                    end = nul
            assert offset < end <= offset + MAX_PART
            data = tar_bytes[offset:end]
            name = f'cloud-1a979-finite-originals.tar.xz.part-{len(parts):03d}'
            (publication / name).write_bytes(data)
            parts.append({'path': name, 'offset': offset, **digest(data),
                          'first_NUL_offset': data.find(b'\0'),
                          'codespell_2_4_3_first_1024_contains_NUL': b'\0' in data[:1024]})
            offset = end
        joined = b''.join((publication / row['path']).read_bytes() for row in parts)
        assert joined == tar_bytes
        assert all(row['codespell_2_4_3_first_1024_contains_NUL'] for row in parts)
        part_index = {'archive_name': tar_path.name, **archive_pin, 'max_part_bytes': MAX_PART,
                      'parts': parts, 'exact_reassembly_verified': True,
                      'split_policy': 'At most480000 bytes; when needed use an existing NUL as the next part start, never alter archive bytes.'}
        (publication / 'archive-parts.json').write_bytes(encoded(part_index))
        member_manifest = {'schema': 'hepta.e6.cloud-finite-archive-members.v1',
                           'source': SOURCE, 'tree': TREE, 'archive': archive_pin,
                           'members': [{'path': k, **v} for k, v in sorted(expected_members.items())],
                           'member_count': len(expected_members), 'every_member_read_back': True}
        metadata['ARCHIVE_MEMBERS.json'] = encoded(member_manifest)
        metadata[Path(__file__).name] = Path(__file__).read_bytes()
        storage = [write_publication_value(publication, name, data) for name, data in sorted(metadata.items())]
        (publication / 'METADATA_STORAGE.json').write_bytes(encoded({'files': storage}))
        for item in storage:
            if item['kind'] == 'whole':
                restored = (publication / item['name']).read_bytes()
            else:
                info = load(publication / item['index'])
                restored = b''.join(read(publication / row['path'], row)[0] for row in info['parts'])
            assert digest(restored) == {key: item[key] for key in ('bytes', 'sha256', 'git_blob')}
            assert restored == metadata[item['name']]
        # Recheck every finite original and baseline reference before committing
        # a success receipt. Nothing in the old archives or source is written.
        for row in inputs['files']:
            read(row['local_path'], row)
        existing_catalog()
        for row in freeze['files']:
            read(freeze_dir / row['path'], row)
        read(__file__, freeze['archive_controller'])
        result = {'status': 'CLOUD_FINITE_EVIDENCE_ARCHIVE_VERIFIED',
                  'source': SOURCE, 'tree': TREE,
                  'input_freeze_sha256': digest((freeze_dir / 'FREEZE.json').read_bytes())['sha256'],
                  'archive': archive_pin, 'archive_members': len(expected_members),
                  'parts': len(parts), 'all_parts_and_metadata_reassembled_exactly': True,
                  'all_selected_originals_unchanged': True,
                  'logical_saved_files': len(inputs['files']), 'storage_counts': inputs['storage_counts'],
                  'finite_host_path_counts': inputs['finite_host_path_counts'],
                  'wall_seconds': time.monotonic() - started,
                  'host_actions': 0, 'native_tests': 0, 'model_calls_or_training': 0,
                  'git_operations': 0, 'source_changes': 0,
                  'whole_noupdate13': 'FAIL', 'new_c_drain_reached': False,
                  'new_business_physical_closure': False,
                  'original_host_pack_not_used_or_repaired': True}
        (publication / 'RESULT.json').write_bytes(encoded(result))
        success = True
        print(json.dumps(result))
    finally:
        if not success:
            (out / 'FAILURE.json').write_bytes(encoded({
                'status': 'INCOMPLETE_CLOUD_ARCHIVE_ATTEMPT',
                'overall_success': False, 'wall_seconds': time.monotonic() - started,
                'host_actions': 0, 'new_native_model_tests': 0,
            }))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'pack'])
    args = parser.parse_args()
    {'prepare': prepare, 'pack': pack}[args.action]()
