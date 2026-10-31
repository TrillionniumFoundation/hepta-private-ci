"""Prepare exact control custody inputs and small source snapshots; do not pack."""

import ast
from collections import defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import time


CONTROL = Path(__file__).resolve().parents[1]
ADVANCE = CONTROL.parent
REPO = ADVANCE.parents[2]
WORK = REPO.parent
RAW = Path('/tmp/hepta-ndu-advance-control')
EVIDENCE = WORK / 'ndu-evidence'
OLD = ADVANCE.parent / 'next_20261025'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False); stream.write('\n')


def collect_pins(value, origin, pins):
    if isinstance(value, dict):
        for key, child in value.items():
            if key.startswith('/') and isinstance(child, str) and re.fullmatch('[0-9a-f]{64}', child):
                pins[(Path(key), child)].add(str(origin))
            else:
                collect_pins(child, origin, pins)
    elif isinstance(value, list):
        for child in value:
            collect_pins(child, origin, pins)


def source_dependencies(logical, physical):
    if not logical.is_relative_to(REPO):
        return []
    module = logical.relative_to(REPO).with_suffix('').parts
    package = '.'.join(module[:-1])
    imports = set()
    for node in ast.walk(ast.parse(physical.read_text())):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            name = '.' * node.level + (node.module or '')
            name = importlib.util.resolve_name(name, package) if node.level else name
            imports.add(name)
            imports.update(name + '.' + alias.name for alias in node.names if alias.name != '*')
    found = set()
    for name in imports:
        for suffix in ('.py', '/__init__.py'):
            path = REPO / (name.replace('.', '/') + suffix)
            if path.is_file():
                found.add(path)
                for parent in path.parents:
                    if parent == REPO:
                        break
                    if (parent / '__init__.py').is_file():
                        found.add(parent / '__init__.py')
    return sorted(found)


def main():
    output = CONTROL / 'RAW_ARCHIVE_INPUT_SPEC.json'
    snapshots = RAW / 'source-snapshots-001'
    if output.exists() or snapshots.exists():
        raise FileExistsError('Custody registration must use new paths')
    pins = defaultdict(set)
    documents = sorted(CONTROL.rglob('*.json')) + sorted(RAW.rglob('*registration.json'))
    for path in documents:
        collect_pins(read(path), path, pins)
    wrapper = Path('/tmp/hepta-ndu-next-native-h2/measure_stage.py')
    for path in RAW.glob('*.process.json'):
        pins[(wrapper, read(path)['wrapper_sha256'])].add(str(path))
    for path in CONTROL.rglob('*.py'):
        pins[(path, sha(path))].add('current control implementation or independent audit')
    for path in (ADVANCE / 'cases.py', ADVANCE / 'input_codec.py', ADVANCE / 'joint/confirmation_data.py'):
        pins[(path, sha(path))].add('shared-input audit dependency snapshot')
    historical = RAW / 'confirmation-smoke-001/source-snapshot/register_confirm.py'
    historical_sha = sha(historical)
    resolved, external, queue = {}, [], []
    for (path, digest), origins in sorted(pins.items()):
        physical = path
        if path.name == 'register_confirm.py' and digest == historical_sha:
            physical = historical
        if not physical.is_file():
            raise FileNotFoundError(str(physical))
        size = physical.stat().st_size
        verified = size < 16 * 1024 * 1024
        if verified and sha(physical) != digest:
            raise ValueError('Recorded dependency changed: ' + str(path))
        record = dict(original_path=str(path), path=str(physical), sha256=digest, bytes=size,
                      recorded_in=sorted(origins), rehashed_for_this_spec=verified)
        resolved[path, digest] = record
        if path.suffix == '.py':
            queue.append((path, physical, digest))
        elif not path.is_relative_to(REPO) and not path.is_relative_to(RAW):
            external.append(record)
    snapshots.mkdir()
    source_index, seen = [], set()
    while queue:
        logical, physical, digest = queue.pop()
        if (logical, digest) in seen:
            continue
        seen.add((logical, digest))
        data = physical.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('Source snapshot changed during preparation')
        destination = snapshots / (digest + '.py')
        if not destination.exists():
            destination.write_bytes(data)
        source_index.append({'original_path': str(logical), 'sha256': digest,
            'snapshot': str(destination), 'bytes': len(data),
            'identity_references': sorted(pins.get((logical, digest), [])),
            'pin_basis': 'retained document pin' if any(origin.startswith('/')
                for origin in pins.get((logical, digest), []))
                else 'post-execution source snapshot; not a new prospective pin'})
        for dependency in source_dependencies(logical, physical):
            queue.append((dependency, dependency, sha(dependency)))
    write(snapshots / 'INDEX.json', {'schema': 'hepta.advance.control-source-snapshots.v1',
        'historical_smoke_source_preserved': str(historical),
        'sources': sorted(source_index, key=lambda row: (row['original_path'], row['sha256']))})

    files = {}
    def add(path, member):
        path = Path(path)
        if path.suffix == '.pyc' or '__pycache__' in path.parts:
            return
        files[str(path)] = {'path': str(path), 'name': member, 'bytes': path.stat().st_size, 'sha256': sha(path)}
    for folder, prefix in ((RAW, 'raw/control'), (CONTROL, 'source/control')):
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                add(path, prefix + '/' + path.relative_to(folder).as_posix())
    for (path, digest), record in resolved.items():
        if path.suffix != '.py' and path.is_relative_to(REPO) and not path.is_relative_to(CONTROL):
            add(path, 'source/repository/' + path.relative_to(REPO).as_posix())
    for name, digest in read(ADVANCE / 'SOURCE_ALLOCATION.json')['previous_allocation_sha256'].items():
        path = OLD / name
        if sha(path) != digest:
            raise ValueError('Previous source allocation differs')
        add(path, 'source/old-allocations/' + name)
    add(ADVANCE / 'evidence/AUDIO_RESTORE_001.json', 'source/advance/AUDIO_RESTORE_001.json')
    archive_links = []
    names = ['hepta-ndu-shared-inputs-20261025', 'hepta-ndu-next-sources-20261026',
             'hepta-ndu-next-control-20261026', 'hepta-ndu-next-action-value-20261026',
             'hepta-ndu-next-native-h1-20261026', 'hepta-ndu-next-native-h2-20261026',
             'hepta-ndu-next-media-runs-20261026', 'hepta-ndu-next-media-asr-assets-20261026',
             'hepta-ndu-next-joint-20261026']
    for name in names:
        archive = EVIDENCE / (name + '.tar.gz')
        receipt = EVIDENCE / (name + '.tar.gz.receipt.json')
        if not receipt.exists() and name == 'hepta-ndu-next-control-20261026':
            receipt = OLD / 'control/EVIDENCE_ARCHIVE.json'
        record = read(receipt)
        if archive.stat().st_size != record['archive_bytes']:
            raise ValueError('Linked archive size differs from its receipt')
        archive_links.append({'path': str(archive), 'bytes': record['archive_bytes'],
            'sha256': record['archive_sha256'], 'receipt': str(receipt),
            'receipt_sha256': sha(receipt), 'archive_rehashed_in_this_spec': False})
        add(receipt, 'upstream/' + name + '.receipt.json')
    allocation = read(ADVANCE / 'SOURCE_ALLOCATION.json')
    new_waves = {}
    for role in allocation['roles'].values():
        for row in role.get('audio_rows_by_source_digit', role.get('recordings', [])):
            new_waves[row['path']] = row['sha256']
    old_audio = read(OLD / 'media/AUDIO_SOURCE_ALLOCATION.json')['roles']['qualification']
    wave_groups = [dict(scope='old likelihood development',
        root=str(WORK / 'ndu-next-assets/media/new-assets/speech-commands-v002-digits'),
        files={row['path']: row['sha256'] for row in old_audio}),
        dict(scope='new allocated identities, shared with native/joint custody',
        root=str(WORK / 'ndu-advance-assets/speech-commands-v002-digits'), files=new_waves)]
    result = {'schema': 'hepta.advance.control-raw-archive-input-spec.v1', 'prepared_ns': time.time_ns(),
        'status': 'inputs prepared; root packaging and closed-member verification pending',
        'files': sorted(files.values(), key=lambda row: row['name']),
        'source_snapshot_index': str(snapshots / 'INDEX.json'), 'source_snapshot_count': len(source_index),
        'external_pinned_dependencies': external, 'linked_existing_archives': archive_links,
        'required_source_waveform_sets': wave_groups,
        'required_official_image_sources': {'root': str(WORK / 'ndu-next-assets/qmnist'),
            'files': allocation['archive_sha256'], 'complete_archive': archive_links[1]},
        'required_native_audit_run': {'path': '/tmp/hepta-ndu-advance-native/qualification-001',
            'full_actual_owner_media_tree_required': True, 'packaging_owner': 'root/native separate archive',
            'identity_receipt': str(CONTROL / 'review/NATIVE_QUALIFICATION_CENSUS.json'),
            'original_outer_exit_code': 1, 'report_recovery_preserved': True},
        'packaging_rules': ['Include this input spec itself when sealing; its own hash is recorded by the archive manifest.',
            'Verify every listed member after closing the archive. This document is not that verification.',
            'External pinned inputs may be included directly or resolved by exact members in linked complete archives.',
            'Do not discard any ridge candidate, backup, raw alternative, content rejection, failed attempt, original process exit, or recovery record.',
            'Keep formal and old-smoke source versions at their recorded distinct hashes.',
            'A separate future native confirmation census requires a new addendum, not alteration of this specification.',
            'No raw upload, source/model rerun, compression or archive extraction is performed by this script.'],
        'runtime_scope': 'Exact Python/Torch/NumPy versions and process commands are in frozen receipts; no complete operating-system or virtual-environment image is claimed.',
        'compressed_archive_created': False, 'new_model_or_source_execution': False,
        'script_sha256': sha(__file__)}
    write(output, result)
    print(json.dumps({'output': str(output), 'files': len(files), 'source_snapshots': len(source_index),
        'listed_file_bytes': sum(row['bytes'] for row in files.values()), 'external_pins': len(external),
        'old_waves': len(wave_groups[0]['files']), 'new_waves': len(new_waves), 'sha256': sha(output)}))


if __name__ == '__main__':
    main()
