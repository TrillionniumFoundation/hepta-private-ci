"""Prepare one explicit successor cut, pack it, and restore every original.

No host/network/Git/test calls. Draft preparation is separate from final freeze.
All state claims come from bound receipts; storage success is not experiment success.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import tarfile
import time

sys.dont_write_bytecode = True
from closeout_validation import retained_bytecode, verify_bytecode, validate_terminal_slot, validate_source_contract, TERMINAL_PROFILES
ROOT = Path('/workspace/scratch/e9e051ab0825')
MAX_FILE = 480000
MAX_ORIGINAL = 64 * 1024 * 1024
HERE = Path(__file__).resolve().parent
BASE = ROOT / 'metrics_integration/final_evidence_publication_work/FROZEN_599_FILES.json'
BASE_SHA = '53e184aa7254ae0d4dc7b55d276b536d2610fa8d6cb71022ba8ac127deb18b61'
OLD = ROOT / 'e6_startup_recovery_evidence_1'
OLD_FREEZE_SHA = '39d326f055ce339cc6437646af597b30ce094ca4fa7b53341bd103f004bdf720'
PREP5_SPEC = {
    'path': 'metrics_integration/execution-readout-intake-diagnostic-6/final-successor-preparation-5/ASSEMBLY_SPEC_DRAFT.json',
    'bytes': 164263,
    'sha256': '85ada44e3e055ac2abcc626ce74881feaed8efda8ae503d06e5c09649f27e2ca',
    'git_blob': '5d5ebf1182c711d8215f877516f143ed11f919e7',
}
FORBIDDEN_INPUTS = {
    'metrics_integration/EXECUTION_READOUT_20261120.md',
    'metrics_integration/execution-readout-publication/evidence/e1e6-execution-readout-20261120/EXECUTION_READOUT_20261120.md',
    'metrics_integration/execution-readout-publication/evidence/e1e6-execution-readout-20261120/REFERENCE_MANIFEST.json',
}


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def identity(body):
    return {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest()}


def key(row):
    return row['bytes'], row['sha256'], row.get('git_blob', row.get('git_blob_sha1'))


def safe(name):
    path = PurePosixPath(name)
    require(bool(name) and not path.is_absolute() and str(path) == name and '..' not in path.parts
            and '\\' not in name and '\0' not in name, 'unsafe relative path: ' + repr(name))
    return name


def read(path, expected=None):
    path = Path(path)
    name = path.name.lower()
    require(not name.endswith(('.key', '.pem', '.p12', '.pfx', '.jks'))
            and name not in {'id_rsa', 'id_dsa', 'id_ed25519', 'id_ecdsa'}, 'excluded body: ' + str(path))
    approved_bytecode = retained_bytecode(path, expected, ROOT)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_ORIGINAL, 'not bounded regular file: ' + str(path))
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        require((os.fstat(fd).st_dev, os.fstat(fd).st_ino) == (before.st_dev, before.st_ino), 'opened identity differs')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            body = stream.read(MAX_ORIGINAL + 1)
    finally:
        os.close(fd)
    after = path.lstat()
    fields = ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    require(all(getattr(before, f) == getattr(after, f) for f in fields) and len(body) == before.st_size, 'changed input: ' + str(path))
    require(not body.startswith(b'\x7fELF'), 'ELF bodies are excluded; use existing metadata')
    actual = identity(body)
    verify_bytecode(actual, approved_bytecode)
    if expected:
        for field in ('bytes', 'sha256', 'git_blob'):
            value = expected.get(field, expected.get('git_blob_sha1') if field == 'git_blob' else None)
            if value is not None:
                require(actual[field] == value, 'identity mismatch: ' + str(path) + ':' + field)
    return body, actual


def load(path, expected=None):
    return json.loads(read(path, expected)[0])


def put(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(body)


def blob_row(row):
    return {k: row[k] for k in ('path', 'bytes', 'sha256', 'git_blob')}


def baseline():
    rows = load(BASE, {'sha256': BASE_SHA})
    require(len(rows) == 599 and len({r['path'] for r in rows}) == 599, 'old599 path set differs')
    by_key = defaultdict(list)
    for row in rows:
        safe(row['path'])
        require(row['git_blob'] == row['server_sha'], 'old599 server OID differs')
        read(row['local_path'], row)
        by_key[key(row)].append(row)
    return rows, by_key


def repo_reader(rows=None, checkout=None):
    by_path = {r['path']: r for r in (rows or [])}
    def get(row):
        relative = safe(row['path'])
        if checkout is None:
            existing = by_path[relative]
            require(key(existing) == key(row), 'repository identity differs')
            path = Path(existing['local_path'])
        else:
            path = Path(checkout) / relative
        return read(path, row)[0]
    return get


def old_catalog(by_key):
    prior = load(OLD / 'frozen-cut-1/FREEZE.json', {'sha256': OLD_FREEZE_SHA})
    prior_pins = {r['path']: r for r in prior['files']}
    publication = OLD / 'publication'
    descriptions = load(publication / 'DEPENDENCIES.json', prior_pins['DEPENDENCIES.json'])['archives']
    catalog = {r['id']: r for r in descriptions}
    parts = load(publication / 'archive-parts.json', {'sha256': '1035164f382a128d135b3230334ed88ff3d579a09917480c9cb6174d9cd2141d'})
    mapped = []
    for part in parts['parts']:
        _, actual = read(publication / safe(part['path']), part)
        matches = by_key[key(actual)]
        require(bool(matches), 'old572 archive part absent from599')
        mapped.append({'name': part['path'], **actual, 'repository_file': blob_row(sorted(matches, key=lambda r: r['path'])[0])})
    catalog['startup572'] = {'id': 'startup572', **{k: parts[k] for k in ('bytes', 'sha256', 'git_blob')}, 'parts': mapped}
    candidates = defaultdict(list)
    for row in load(publication / 'ARCHIVE_MEMBERS.json', {'sha256': '815c9c04bcdaabb5b73e65102db80fefe95572c79d284934ae5b4536e6adb31f'})['members']:
        candidates[key(row)].append({'archive_id': 'startup572', 'member': row['path'], **identity_fields(row)})
    # Explicitly retained old member descriptions only; never discover a host tree.
    for row in load(OLD / 'frozen-cut-1/INPUT_MANIFEST.json', prior_pins['INPUT_MANIFEST.json'])['files']:
        storage = row['storage']
        if storage['kind'] == 'existing_archive_member':
            candidates[key(row)].append({'archive_id': storage['archive_id'], 'member': storage['member'], **identity_fields(row)})
    return catalog, candidates


def identity_fields(row):
    return {k: row[k] for k in ('bytes', 'sha256', 'git_blob')}


def expected_identity(row):
    result = {k: row[k] for k in ('bytes', 'sha256') if k in row}
    require(set(result) == {'bytes', 'sha256'}, 'original manifest must pin length and SHA')
    if row.get('git_blob', row.get('git_blob_sha1')) is not None:
        result['git_blob'] = row.get('git_blob', row.get('git_blob_sha1'))
    return result


def extract_selected(archives, wanted, get_repo):
    result = {}
    for description in archives:
        selected = wanted.get(description['id'], {})
        if not selected:
            continue
        body = b''.join(get_repo(p['repository_file']) for p in description['parts'])
        require(identity(body) == identity_fields(description), 'old archive identity differs')
        seen = set()
        with tarfile.open(fileobj=io.BytesIO(body), mode='r|xz') as archive:
            all_names = set()
            for member in archive:
                safe(member.name)
                require(member.isfile() and member.name not in all_names, 'unsafe or duplicate old tar member')
                all_names.add(member.name)
                if member.name not in selected:
                    continue
                require(member.size == selected[member.name]['bytes'] and member.size <= MAX_ORIGINAL, 'old member length differs')
                data = archive.extractfile(member).read()
                require(identity(data) == identity_fields(selected[member.name]), 'old selected member differs')
                result[(description['id'], member.name)] = data
                seen.add(member.name)
        require(seen == set(selected), 'selected old members missing')
    require(len(result) == sum(len(rows) for rows in wanted.values()), 'archive description missing')
    return result


def check_slots(spec, paths):
    require(len({s['id'] for s in spec['terminal_slots']}) == len(spec['terminal_slots']), 'duplicate terminal slot')
    prior = load(ROOT / PREP5_SPEC['path'], PREP5_SPEC)
    historical = {s['id']: s for s in prior['terminal_slots'] if s['id'] != 'future_diagnostic_scope'}
    require(len(historical) == 5 and {s['id'] for s in spec['terminal_slots']} == set(historical) | set(TERMINAL_PROFILES),
            'five exact historical slots and four reviewed actual slots required')
    contract_ref = spec['reviewed_source_contract']
    require(contract_ref['path'] in paths and key(contract_ref) == key(paths[contract_ref['path']]),
            'reviewed source contract is not retained by the cut')
    source_contract = validate_source_contract(contract_ref, lambda ref: read(ROOT / safe(ref['path']), ref), ROOT)
    require(set(source_contract['contract']['stages']) ==
            {s['id'] for s in spec['terminal_slots'] if s['id'] in TERMINAL_PROFILES and s['state'] == 'terminal'},
            'reviewed source stage set differs from admitted terminals')
    for evidence in source_contract['evidence']:
        require(evidence['path'] in paths and key(evidence) == key(paths[evidence['path']]),
                'reviewed source/runner identity is not retained by the cut')
    for slot in spec['terminal_slots']:
        if slot['id'] in historical:
            require(slot == historical[slot['id']], 'historical terminal receipt was changed or reassigned')
        require(slot['state'] in {'terminal', 'not_executed'}, 'future slot is still pending: ' + slot['id'])
        reference = slot['result'] if slot['state'] == 'terminal' else slot['root_closeout']
        require(reference and reference['path'] in paths, 'slot receipt not in explicit input set')
        require(key(reference) == key(paths[reference['path']]), 'slot pin differs from retained original')
        value = load(ROOT / safe(reference['path']), reference)
        if slot['state'] == 'terminal':
            if slot['id'] in TERMINAL_PROFILES:
                require(slot['reviewed_source_contract'] == contract_ref, 'slot borrows another source contract')
                for field in ('owner_start', 'owner_terminal', 'result_capture'):
                    evidence = slot[field]
                    require(evidence['path'] in paths and key(evidence) == key(paths[evidence['path']]),
                            'terminal owner/capture evidence is not retained by the cut')
                validate_terminal_slot(slot, lambda ref: read(ROOT / safe(ref['path']), ref))
            require(type(value.get('successful')) is bool, 'terminal RESULT lacks explicit successful boolean')
            require(value.get('status') not in {'running', 'preflight', 'RUNNING'}, 'nonterminal RESULT')
        else:
            require(bool(slot.get('reason')), 'unexecuted stage needs explicit reason, not implied failure')


def freeze(spec_path, output):
    spec_bytes, spec_identity = read(spec_path)
    spec = json.loads(spec_bytes)
    require(spec['state'] == 'READY_FOR_SINGLE_FINAL_FREEZE', 'draft spec cannot be frozen')
    output.mkdir(exist_ok=False)
    rows = {}
    metadata = {'ASSEMBLY_SPEC.json': spec_bytes}
    # Existing184 are immutable. Later inputs are explicitly added, not rglobbed.
    for index in spec['prior_successor_indexes']:
        data, actual = read(ROOT / safe(index['path']), index)
        meta_name = 'indexes/' + Path(index['path']).name
        require(meta_name not in metadata, 'duplicate prior index metadata name')
        metadata[meta_name] = data
        for row in json.loads(data)['files']:
            path = safe(row['workspace_path'])
            require(path not in rows, 'duplicate old successor logical path')
            read(ROOT / path, row)
            rows[path] = {'workspace_path': path, 'local_path': str(ROOT / path), **identity_fields(row), 'roles': row.get('roles', [])}
    require(len(rows) == 184, 'old successor184 composition differs')
    explicit = list(spec['explicit_files'])
    for source in spec['manifest_groups']:
        data, actual = read(ROOT / safe(source['path']), source)
        explicit.append({'path': source['path'], **actual, 'roles': source.get('roles', [])})
        manifest = json.loads(data)
        for row in manifest[source['rows_key']]:
            child = safe(row[source.get('member_key', 'path')])
            prefix = source['member_root']
            path = safe(prefix + '/' + child if prefix else child)
            explicit.append({'path': path, **expected_identity(row), 'roles': source.get('roles', [])})
    for row in explicit:
        path = safe(row['path'])
        require(path not in FORBIDDEN_INPUTS, 'formal mutable document is not an input')
        _, actual = read(ROOT / path, row)
        candidate = {'workspace_path': path, 'local_path': str(ROOT / path), **actual, 'roles': row.get('roles', [])}
        if path in rows:
            require(key(rows[path]) == key(candidate), 'logical input overwritten')
            rows[path]['roles'] = sorted(set(rows[path]['roles'] + candidate['roles']))
        else:
            rows[path] = candidate
    check_slots(spec, rows)
    existing, by_key = baseline()
    archives, candidates = old_catalog(by_key)
    needed = defaultdict(dict)
    for row in rows.values():
        direct = by_key.get(key(row), [])
        archived = candidates.get(key(row), [])
        if direct:
            row['storage'] = {'kind': 'existing_repository_file', 'repository_file': blob_row(sorted(direct, key=lambda r: r['path'])[0])}
        elif archived:
            selected = sorted(archived, key=lambda r: (r['archive_id'], r['member']))[0]
            row['storage'] = {'kind': 'existing_archive_member', **selected}
            needed[selected['archive_id']][selected['member']] = row
        else:
            row['storage'] = {'kind': 'new_archive_object', 'member': 'objects/' + row['sha256'] + '.bin'}
    dependencies = {'baseline599_sha256': BASE_SHA, 'old572_freeze_sha256': OLD_FREEZE_SHA,
                    'archives': [archives[k] for k in sorted(needed)]}
    extract_selected(dependencies['archives'], needed, repo_reader(existing))
    metadata['INPUT_MANIFEST.json'] = encoded({'files': sorted(rows.values(), key=lambda r: r['workspace_path']), 'logical_files': len(rows)})
    metadata['DEPENDENCIES.json'] = encoded(dependencies)
    metadata['SCOPE.json'] = encoded(spec['scope'])
    for name, data in metadata.items():
        put(output / safe(name), data)
    controllers = []
    for path in [Path(__file__), HERE / 'render_readout.py', HERE / 'closeout_validation.py', HERE / 'RETAINED_BYTECODE_PROVENANCE.json']:
        body, actual = read(path)
        controllers.append({'path': str(path), **actual})
    result = {'state': 'FROZEN_NOT_PACKED', 'assembly_spec': spec_identity,
              'files': [{'path': name, **identity(data)} for name, data in sorted(metadata.items())],
              'controllers': controllers, 'baseline599_sha256': BASE_SHA, 'logical_originals': len(rows),
              'publication_prefix': safe(spec['publication_prefix']), 'host_network_git_native_model_actions': 0}
    put(output / 'FREEZE.json', encoded(result))
    return result


def stage_bytes(publication, logical_name, data, files):
    """Recursive exact-byte representation; even a descriptor can be split."""
    safe(logical_name)
    if len(data) <= MAX_FILE:
        path = publication / logical_name
        put(path, data)
        row = {'path': logical_name, 'local_path': str(path), **identity(data)}
        require(logical_name not in files, 'duplicate staged path')
        files[logical_name] = row
        return {'encoding': 'identity', 'file': row}
    bundle = hashlib.sha256(logical_name.encode()).hexdigest() + '-' + identity(data)['sha256']
    parts = []
    for ordinal, offset in enumerate(range(0, len(data), MAX_FILE)):
        body = data[offset:offset + MAX_FILE]
        representation = stage_bytes(publication, f'metadata-parts/{bundle}/part-{ordinal:05d}', body, files)
        parts.append({'offset': offset, 'file': representation['file']})
    descriptor = {'schema': 'exact-original-bytes.v1', 'original': {'name': logical_name, **identity(data)}, 'parts': parts}
    return {'encoding': 'byte-parts', 'original': descriptor['original'],
            'descriptor': stage_bytes(publication, f'metadata-parts/{bundle}/REASSEMBLY.json', encoded(descriptor), files)}


def restore_representation(rep, reader):
    if rep['encoding'] == 'identity':
        row = rep['file']; body = reader(row)
    else:
        require(rep['encoding'] == 'byte-parts', 'unknown metadata representation')
        descriptor = json.loads(restore_representation(rep['descriptor'], reader))
        require(descriptor['original'] == rep['original'], 'descriptor identity differs')
        chunks, offset, seen = [], 0, set()
        for part in descriptor['parts']:
            require(part['offset'] == offset and part['file']['path'] not in seen, 'part offset/identity reused')
            seen.add(part['file']['path'])
            chunk = reader(part['file'])
            require(0 < len(chunk) <= MAX_FILE, 'part size outside bound')
            chunks.append(chunk); offset += len(chunk)
        body = b''.join(chunks); row = rep['original']
    require(identity(body) == identity_fields(row), 'metadata restoration differs')
    return body


def restore(publication, repository_map, output, checkout=None):
    output.mkdir(exist_ok=False)
    components = load(publication / 'RESTORE_INDEX.json')
    reader = lambda row: read(publication / safe(row['path']), row)[0]
    metadata = {name: restore_representation(rep, reader) for name, rep in components['metadata'].items()}
    index = json.loads(metadata['archive-parts.json'])
    chunks, offset = [], 0
    for part in index['parts']:
        require(part['offset'] == offset and 0 < part['bytes'] <= MAX_FILE, 'archive part offset/length mismatch')
        chunk = reader(part); chunks.append(chunk); offset += len(chunk)
    archive_body = b''.join(chunks)
    require(identity(archive_body) == identity_fields(index), 'archive restoration differs')
    expected = {r['path']: r for r in json.loads(metadata['ARCHIVE_MEMBERS.json'])['members']}
    require(len(expected) == len(json.loads(metadata['ARCHIVE_MEMBERS.json'])['members']), 'duplicate expected tar members')
    actual = {}
    with tarfile.open(fileobj=io.BytesIO(archive_body), mode='r|xz') as archive:
        for member in archive:
            safe(member.name)
            require(member.isfile() and member.name in expected and member.name not in actual, 'unexpected/duplicate/nonregular member')
            require(member.size == expected[member.name]['bytes'] and member.size <= MAX_ORIGINAL, 'tar member length outside expected bound')
            data = archive.extractfile(member).read()
            require(member.size == len(data) and identity(data) == identity_fields(expected[member.name]), 'tar member differs')
            actual[member.name] = data
    require(set(actual) == set(expected), 'tar members incomplete')
    inputs = json.loads(metadata['INPUT_MANIFEST.json'])
    dependencies = json.loads(metadata['DEPENDENCIES.json'])
    for name, body in metadata.items():
        if 'metadata/' + name in actual:
            require(actual['metadata/' + name] == body, 'external metadata differs from tar')
    needed = defaultdict(dict)
    for row in inputs['files']:
        if row['storage']['kind'] == 'existing_archive_member':
            needed[row['storage']['archive_id']][row['storage']['member']] = row
    repo = repo_reader(load(repository_map) if repository_map else [], checkout)
    old = extract_selected(dependencies['archives'], needed, repo)
    restored = []
    require(len({r['workspace_path'] for r in inputs['files']}) == len(inputs['files']), 'duplicate logical output paths')
    for row in inputs['files']:
        storage = row['storage']
        if storage['kind'] == 'new_archive_object': data = actual[storage['member']]
        elif storage['kind'] == 'existing_repository_file': data = repo(storage['repository_file'])
        elif storage['kind'] == 'existing_archive_member': data = old[(storage['archive_id'], storage['member'])]
        else: raise ValueError('unknown storage kind')
        require(identity(data) == identity_fields(row), 'logical original differs')
        destination = output / 'originals' / safe(row['workspace_path'])
        put(destination, data)
        require(read(destination, row)[0] == data, 'restored file readback differs')
        restored.append({'workspace_path': row['workspace_path'], **identity(data), 'storage_kind': storage['kind']})
    result = {'state': 'ALL_LOGICAL_ORIGINALS_RESTORED', 'files': restored, 'logical_files': len(restored),
              'archive': identity(archive_body), 'archive_members': len(actual), 'experiment_qualification': False}
    put(output / 'RESTORE_READBACK.json', encoded(result))
    return result


def pack(frozen, output):
    freeze_data, freeze_pin = read(frozen / 'FREEZE.json')
    frozen_meta = json.loads(freeze_data)
    for row in frozen_meta['controllers']: read(row['path'], row)
    metadata = {r['path']: read(frozen / safe(r['path']), r)[0] for r in frozen_meta['files']}
    metadata['FREEZE.json'] = freeze_data
    for row in frozen_meta['controllers']: metadata['controllers/' + Path(row['path']).name] = read(row['path'], row)[0]
    inputs = json.loads(metadata['INPUT_MANIFEST.json'])
    output.mkdir(exist_ok=False); publication = output / 'publication'; publication.mkdir()
    started = time.monotonic(); complete = False
    try:
        existing, _ = baseline()
        unique = {}
        for row in inputs['files']:
            read(row['local_path'], row)
            if row['storage']['kind'] == 'new_archive_object':
                previous = unique.setdefault(row['sha256'], row)
                require(key(previous) == key(row), 'same SHA with inconsistent byte identity')
        archive_path = output / 'successor-originals.tar.xz'; members = {}
        with tarfile.open(archive_path, 'w:xz', format=tarfile.USTAR_FORMAT, preset=6) as archive:
            for name, body in sorted(metadata.items()):
                member = 'metadata/' + safe(name)
                info = tarfile.TarInfo(member); info.size = len(body); info.mode = 0o644
                archive.addfile(info, io.BytesIO(body)); members[member] = identity(body)
            for sha, row in sorted(unique.items()):
                body = read(row['local_path'], row)[0]; member = safe(row['storage']['member'])
                info = tarfile.TarInfo(member); info.size = len(body); info.mode = 0o644
                archive.addfile(info, io.BytesIO(body)); members[member] = identity(body)
        archive_body = archive_path.read_bytes(); files = {}; parts = []; offset = 0
        while offset < len(archive_body):
            end = min(offset + MAX_FILE, len(archive_body))
            if end < len(archive_body):
                boundary = archive_body.rfind(b'\0', offset + 1, end + 1)
                require(boundary > offset, 'no original NUL boundary in bounded archive part')
                end = boundary
            body = archive_body[offset:end]
            require(b'\0' in body[:1024], 'archive part lacks binary classification prefix')
            rep = stage_bytes(publication, f'successor-originals.tar.xz.part-{len(parts):03d}', body, files)
            parts.append({'offset': offset, **rep['file']}); offset = end
        metadata['archive-parts.json'] = encoded({'archive_name': archive_path.name, **identity(archive_body), 'parts': parts})
        metadata['ARCHIVE_MEMBERS.json'] = encoded({'members': [{'path': name, **value} for name, value in sorted(members.items())]})
        representations = {name: stage_bytes(publication, name, body, files) for name, body in sorted(metadata.items())}
        # This small root points to recursively bounded descriptors, never to itself.
        index = encoded({'metadata': representations})
        require(len(index) <= MAX_FILE, 'root restore map exceeds fixed bound')
        stage_bytes(publication, 'RESTORE_INDEX.json', index, files)
        restored = restore(publication, BASE, output / 'independent-restoration-1')
        require(restored['logical_files'] == len(inputs['files']), 'not all logical originals restored')
        for row in inputs['files']:
            require(read(row['local_path'], row)[0] == read(output / 'independent-restoration-1/originals' / row['workspace_path'], row)[0], 'original/restored bytes differ')
        restore_rep = stage_bytes(publication, 'RESTORE_READBACK.json', encoded(restored), files)
        stage_bytes(publication, 'RESTORE_READBACK_REPRESENTATION.json', encoded(restore_rep), files)
        baseline()
        for row in frozen_meta['files']: read(frozen / row['path'], row)
        for row in frozen_meta['controllers']: read(row['path'], row)
        prefix = safe(frozen_meta['publication_prefix']); old_paths = {r['path'] for r in existing}
        for rep in representations.values():
            restore_representation(rep, lambda row: read(publication / row['path'], row)[0])
        for row in files.values():
            require(row['bytes'] <= MAX_FILE and prefix + '/' + row['path'] not in old_paths, 'publication limit/collision')
            read(row['local_path'], row)
        result = {'state': 'CLOUD_EVIDENCE_PACK_ALL_ORIGINALS_AND_PUBLICATION_VERIFIED', 'package_successful': True,
                  'logical_originals': len(inputs['files']), 'archive_members': len(members),
                  'archive': identity(archive_body), 'archive_parts': len(parts), 'freeze': freeze_pin,
                  'all_originals_byte_equal_after_restore': True, 'raw_RPC_fields_removed': 0,
                  'experiment_qualification_inferred': False, 'host_network_git_native_model_test_actions': 0,
                  'wall_seconds_before_success_marker': time.monotonic() - started}
        result_bytes = encoded(result); require(len(result_bytes) <= MAX_FILE, 'result exceeds fixed limit')
        result_row = {'path': prefix + '/RESULT.json', 'local_path': str(publication / 'RESULT.json'), **identity(result_bytes), 'mode': '100644'}
        require(result_row['path'] not in old_paths, 'final RESULT would replace an old599 path')
        publication_rows = [{'path': prefix + '/' + r['path'], 'local_path': r['local_path'], **identity_fields(r), 'mode': '100644'} for r in files.values()] + [result_row]
        require(len({r['path'] for r in publication_rows}) == len(publication_rows), 'duplicate final publication path')
        put(output / 'PUBLICATION_FILES.json', encoded({'state': 'PREPARED_EXPECTED_FILE_MAP_RESULT_WRITTEN_LAST', 'files': sorted(publication_rows, key=lambda r: r['path']),
            'baseline599_sha256': BASE_SHA, 'old572_unchanged': True, 'no_git_action': True}))
        pending = output / 'VERIFIED_RESULT.pending.json'; put(pending, result_bytes)
        require(read(pending, result_row)[0] == result_bytes, 'pending final receipt mismatch')
        os.link(pending, publication / 'RESULT.json')
        complete = True
        return result
    except BaseException as error:
        if not complete:
            put(output / 'FAILURE.json', encoded({'package_successful': False, 'error_class': type(error).__name__, 'error': str(error), 'wall_seconds': time.monotonic() - started}))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['freeze', 'pack', 'restore'])
    parser.add_argument('--spec', type=Path); parser.add_argument('--frozen', type=Path)
    parser.add_argument('--publication', type=Path); parser.add_argument('--repository-map', type=Path)
    parser.add_argument('--repository-root', type=Path); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'freeze': result = freeze(args.spec, args.output)
    elif args.action == 'pack': result = pack(args.frozen, args.output)
    else: result = restore(args.publication, args.repository_map, args.output, args.repository_root)
    print(json.dumps({k: v for k, v in result.items() if k != 'files'}, ensure_ascii=False))
