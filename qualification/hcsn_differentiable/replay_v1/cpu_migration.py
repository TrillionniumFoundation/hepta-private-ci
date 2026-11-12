"""Byte-preserving archive relocation for a separately declared CPU replay profile."""
import copy
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import stat
import zipfile

from checkpoint_replay import digest, require, write_json

ARCHIVE_BYTES = 11397159
ARCHIVE_SHA256 = '37d387507ec150abfdad4065c23612e18fca6643d489f3555874c8e57a514b75'
SOURCE_COMMIT = '5cb83d9c76beedf4c1c917e4bf561f5f26261ce7'
NATIVE_PREEXECUTION_SHA256 = '49a624205233078044c3dcf5d53f26ca83a76f4e0e897dc39c98ffb9d5f41653'
MAX_RAW_BYTES = 128 * 1024 * 1024


def object_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    def constant(token):
        raise ValueError('nonfinite JSON constant: ' + token)
    def finite(token):
        value = float(token)
        require(math.isfinite(value), 'overflowed JSON float')
        return value
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=finite)
    require(type(value) is dict, 'expected JSON object')
    return value


def safe_member(name):
    path = PurePosixPath(name)
    require(type(name) is str and name and '\\' not in name and '\x00' not in name
            and not path.is_absolute() and all(part not in ('', '.', '..') for part in path.parts)
            and path.as_posix() == name, 'noncanonical archive path')
    return path


def assemble_parts(manifest_path, target, expected):
    manifest_path, target = Path(manifest_path), Path(target)
    manifest = object_json(manifest_path.read_bytes())
    require(manifest['schema'] == 'hcsn-real-replay-export-parts-v1'
            and manifest['archive'] == expected, 'archive commitment differs')
    parts = manifest['parts']
    require(type(parts) is list and 0 < len(parts) <= 128, 'invalid ordered part count')
    seen, total, aggregate = set(), 0, hashlib.sha256()
    with target.open('xb') as output:
        for item in parts:
            name = item['path']
            require(safe_member(name).parent == PurePosixPath('.') and name not in seen,
                    'part must be a unique filename in the manifest directory')
            seen.add(name)
            part = manifest_path.parent / name
            require(part.is_file() and not part.is_symlink() and digest(part) == {
                'bytes': item['bytes'], 'sha256': item['sha256']}, 'part identity differs')
            with part.open('rb') as stream:
                for raw in iter(lambda: stream.read(1024 * 1024), b''):
                    total += len(raw)
                    require(total <= expected['bytes'], 'part aggregate exceeds archive bound')
                    aggregate.update(raw)
                    output.write(raw)
    require({'bytes': total, 'sha256': aggregate.hexdigest()} == expected, 'reassembled archive differs')
    return target


def extract_verified(archive_path, destination, expected):
    """The explicit identity argument lets tests use labelled synthetic archives."""
    archive_path, destination = Path(archive_path), Path(destination)
    require(digest(archive_path) == expected, 'archive identity differs')
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        require(len(infos) <= 2001 and len(names) == len(set(names)), 'duplicate/excess archive members')
        require(sum(item.file_size for item in infos) <= MAX_RAW_BYTES, 'archive expansion exceeds bound')
        for item in infos:
            safe_member(item.filename)
            mode = item.external_attr >> 16
            require(not item.is_dir() and stat.S_IFMT(mode) in (0, stat.S_IFREG)
                    and not item.flag_bits & 1, 'nonregular/encrypted archive member')
        require('INDEX.json' in names and archive.getinfo('INDEX.json').file_size <= 2 * 1024 * 1024,
                'archive index missing/oversized')
        raw_index = archive.read('INDEX.json')
        index = object_json(raw_index)
        require(index['schema'] == 'hcsn-six-real-checkpoint-export-v1'
                and index['source_commit'] == SOURCE_COMMIT and index['model_executions'] == 0,
                'unrecognized original export')
        mapping, expected_members = {}, set()
        for item in index['files']:
            original, member = item['original_path'], item['member']
            original_path = PurePosixPath(original)
            require(original_path.is_absolute() and original_path.as_posix() == original
                    and not original.startswith('//') and '\\' not in original
                    and '..' not in original_path.parts and original not in mapping,
                    'duplicate/noncanonical original path')
            require(member == 'root/' + original.lstrip('/') and safe_member(member)
                    and member not in expected_members and member in names,
                    'index member differs from original path')
            require(type(item['bytes']) is int and 0 <= item['bytes'] <= MAX_RAW_BYTES
                    and archive.getinfo(member).file_size == item['bytes'], 'member size differs')
            mapping[original], expected_members = item, expected_members | {member}
        require(expected_members | {'INDEX.json'} == set(names), 'unindexed or missing archive member')
        destination.mkdir(exist_ok=False)
        for item in mapping.values():
            target = destination / item['member']
            target.parent.mkdir(parents=True, exist_ok=True)
            value = hashlib.sha256()
            with archive.open(item['member']) as source, target.open('xb') as output:
                for raw in iter(lambda: source.read(1024 * 1024), b''):
                    value.update(raw)
                    output.write(raw)
            require(value.hexdigest() == item['sha256'], 'member byte hash differs')
        (destination / 'INDEX.original.json').write_bytes(raw_index)
    return index


def derive_cpu_plan(native, index, extracted, derived, program_paths, torch_root, runtime, selection):
    """Rebase locations, preserving every checkpoint, episode and repository source byte."""
    extracted, derived, torch_root = Path(extracted), Path(derived), Path(torch_root)
    entries = {row['original_path']: row for row in index['files']}
    def relocated(name):
        require(name in entries, 'required original file absent from export: ' + name)
        result = extracted / entries[name]['member']
        require(digest(result) == {'bytes': entries[name]['bytes'], 'sha256': entries[name]['sha256']},
                'extracted original changed')
        return result
    def directory(name):
        value = PurePosixPath(name)
        require(value.is_absolute() and value.as_posix() == name and not name.startswith('//')
                and '\\' not in name and '..' not in value.parts
                and any(original.startswith(name + '/') for original in entries), 'unbound original directory')
        return extracted / 'root' / name.lstrip('/')
    require(native['schema'] == 'hcsn-real-checkpoint-replay-plan-v1' and native['steps'] == 2
            and native['confirmation_access'] is False and len(native['fits']) == 6,
            'native diagnostic plan differs')
    require(runtime['torch_version'] == '2.8.0+cpu' and runtime['cuda_build'] is None
            and type(runtime['torch_build']) is str, 'CPU runtime profile differs')
    fixed = {row['fit']: row for row in selection['fits']}
    require(len(fixed) == 6 and {row['fit'] for row in native['fits']} == set(fixed), 'six-fit roster differs')
    derived.mkdir(exist_ok=False)
    plan, changes = copy.deepcopy(native), []
    plan.update(torch_version=runtime['torch_version'], torch_build=runtime['torch_build'],
        python=runtime['executable'], study_source=str(directory(native['study_source'])),
        program_inputs={str(Path(path).resolve()): digest(path) for path in program_paths})
    for row in plan['fits']:
        selected = fixed[row['fit']]
        require(row['checkpoint_identity'] == selected['identity']
                and row['expected_epoch'] == selected['epoch']
                and row['expected_main_updates'] == selected['logical_main_updates'], 'selected real checkpoint differs')
        old_plan = relocated(row['training_plan'])
        original_training = object_json(old_plan.read_bytes())
        amended_training = {**original_training, 'prepared': str(directory(original_training['prepared']))}
        training_path = derived / (row['fit'] + '.training-plan.json')
        write_json(training_path, amended_training)
        row['inputs'] = {str(relocated(name)): expected for name, expected in row['inputs'].items()}
        row['checkpoint'] = str(relocated(row['checkpoint']))
        row['training_plan'] = str(training_path)
        row['inputs'][str(training_path)] = digest(training_path)
        sources, torch_count = {}, 0
        for original, expected_sha in row['model_sources'].items():
            if '/site-packages/torch/' in original:
                relative = original.split('/site-packages/torch/', 1)[1]
                require(relative in {'nn/modules/activation.py', 'nn/modules/container.py', 'nn/modules/linear.py'},
                        'unreviewed Torch source relocation')
                active = (torch_root / relative).resolve()
                require(digest(active)['sha256'] == expected_sha, 'CPU Torch Python source differs from original')
                torch_count += 1
            else:
                require(original.startswith(native['study_source'] + '/'), 'source outside frozen study')
                active = relocated(original)
            sources[str(active)] = expected_sha
            row['inputs'][str(active)] = digest(active)
        require(torch_count == 3 and len(sources) == 37, 'expected original 34 repository and three Torch sources')
        row['model_sources'] = sources
        changes.append({'fit': row['fit'], 'original_training_plan': digest(old_plan),
            'derived_training_plan': digest(training_path), 'changed_fields': ['prepared'],
            'checkpoint_bytes_unchanged': True, 'model_repository_source_bytes_unchanged': True})
    plan['profile_amendment'] = {'schema': 'hcsn-cpu-replay-profile-amendment-v1',
        'original_source_commit': SOURCE_COMMIT, 'original_torch_version': native['torch_version'],
        'original_torch_build': native['torch_build'], 'new_runtime': runtime,
        'original_native_optimizer_steps': 'UNKNOWN', 'inherits_original_cuda_qualification': False,
        'independent_complete_training_replays_added': 0, 'training_plan_changes': changes}
    return plan
