#!/usr/bin/env python3
"""Assemble only frozen actual-format inputs in an isolated, auditable overlay.

No repository config, global CALLERS, allowlist, remote service, formatter or
native process is accessed. Content conflicts are preserved and never guessed.
"""

from pathlib import Path
import ast
import base64
import difflib
import gzip
import hashlib
import json
import re
import shutil
import subprocess


ROOT = Path('/workspace/scratch/037c0371c195')
OUT = Path(__file__).resolve().parent
COMMIT = 'a96d1b821d10ed3d9e99dd06c5141f9f242ae318'
TREE = 'f96bebefbc1e7d8187efadb62f88d524cdd18451'
BASE = OUT / 'base'
WORK = OUT / 'work'
EVIDENCE = OUT / 'merge-evidence'
EMPTY = b''


def ident(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def verify(data, expected):
    actual = ident(data)
    for key in ('bytes', 'sha256', 'blob'):
        if key in expected:
            assert actual[key] == expected[key], (key, actual, expected)
    if 'git_blob' in expected:
        assert actual['blob'] == expected['git_blob'], (actual, expected)
    return actual


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def json_save(path, obj):
    save(path, (json.dumps(obj, ensure_ascii=False, indent=2) + '\n').encode())


input_files = {}


def read_input(path):
    path = Path(path)
    data = path.read_bytes()
    previous = input_files.setdefault(str(path), ident(data))
    assert previous == ident(data), ('input changed during assembly', path)
    return data


def read_json(path):
    data = read_input(path)
    if str(path).endswith('.gz'):
        data = gzip.decompress(data)
    return json.loads(data)


def safe_path(path):
    assert path.startswith(('codex-rs/hepta-agentd/src/', 'qa/b4-no-bypass/')), path
    assert '..' not in Path(path).parts, path
    assert path.endswith(('.rs', '.py')), path
    assert 'CALLERS' not in path and 'allowlist' not in path, path
    return path


def original_bytes(record, base_dir=None, payload=None):
    expected = record['base']
    exists = record.get('base_exists', expected['bytes'] != 0)
    if not exists:
        verify(EMPTY, expected)
        return False, EMPTY
    if payload is not None:
        row = payload[record['path']]
        assert row['base'] == expected, (record['path'], row['base'], expected)
        if 'base_utf8' in row:
            data = row['base_utf8'].encode()
        else:
            data = base64.b64decode(row['base_base64'], validate=True)
    else:
        data = read_input(base_dir / record['path'])
    verify(data, expected)
    return True, data


layers = []


def formatted_layer(name, directory, verified_name, pure_a96, payload_path=None):
    directory = ROOT / directory
    manifest_path = directory / 'manifest.json'
    manifest = read_json(manifest_path)
    verified = read_json(directory / verified_name)
    assert manifest['source_commit'] == COMMIT
    assert manifest['source_tree'] == TREE
    assert manifest['returncode'] == 0 and manifest['error'] is None
    if 'manifest' in verified:
        verify(read_input(manifest_path), verified['manifest'])
    payload = None
    if payload_path:
        payload_json = read_json(ROOT / payload_path)
        payload = {row['path']: row for row in payload_json['files']}
    records = []
    for row in manifest['files']:
        exists, base = original_bytes(row, directory / 'base', payload)
        after_path = directory / 'postimages' / row['path']
        after = read_input(after_path)
        verify(after, row['after'])
        records.append({'path': safe_path(row['path']), 'base_exists': exists,
                        'base_bytes': base, 'after_bytes': after,
                        'after_source': str(after_path), 'raw_record': row})
    layers.append({'name': name, 'kind': 'actual_rustfmt', 'pure_a96': pure_a96,
                   'manifest_path': str(manifest_path), 'verified_path': str(directory / verified_name),
                   'returncode': manifest['returncode'], 'records': records})


formatted_layer('01-C14', 'candidate-evaluated-c-remote-formatted-v1', 'VERIFIED_MANIFEST.json', True)
formatted_layer('02-S12', 'candidate-evaluated-s-command-formatted-v1', 'VERIFIED_MANIFEST.json', False)
formatted_layer('03-C11', 'candidate-evaluated-c-command-formatted-v1', 'VERIFIED_MANIFEST.json', False)
formatted_layer('04-Current13', 'candidate-current-formatted-v1', 'VERIFIED_MANIFEST.json', True,
                'candidate-current-format-v1/input-payload.json.gz')
formatted_layer('05-Root12', 'root-evaluated-candidate-formatted-v1', 'VERIFIED_MANIFEST.json', True)

# The actual one-file UFCS correction deliberately uses the actual Root12
# postimage as its preimage, rather than pretending it is an a96 source file.
caller_dir = ROOT / 'root-evaluated-candidate-caller-formatted-v2'
caller_verified = read_json(caller_dir / 'VERIFIED_POSTIMAGES.json')
caller_payload = read_json(ROOT / 'root-evaluated-candidate-caller-format-v2/input-payload.json')
assert caller_verified['actual_returncode'] == 0 and caller_verified['actual_output_complete'] is True
assert caller_verified['actual_capture_error'] is None
caller_records = []
for row in caller_payload['files']:
    exists, base = original_bytes(row, payload={row['path']: row})
    verified = next(v for v in caller_verified['actual_postimages'] if v['path'] == row['path'])
    after_path = caller_dir / 'postimages' / row['path']
    after = read_input(after_path)
    verify(after, verified['after'])
    caller_records.append({'path': safe_path(row['path']), 'base_exists': exists,
                           'base_bytes': base, 'after_bytes': after, 'after_source': str(after_path),
                           'raw_record': {'base': row['base'], 'after': verified['after']}})
layers.append({'name': '06-RootUFCS-V2', 'kind': 'actual_rustfmt', 'pure_a96': False,
               'manifest_path': str(caller_dir / 'VERIFIED_POSTIMAGES.json'), 'returncode': 0,
               'records': caller_records})

formatted_layer('07-Version40', 'profile-evaluated-version-formatted-v3', 'ROOT_POSTIMAGE_VERIFICATION.json', True,
                'profile-evaluated-version-format-v3-argv-v1/input-payload.json')

# Diagnostic5 is based on exact 4ab. Its stored complete GitHub comparison
# proves that none of these five paths changed on 4ab -> a96; the original
# result, including its source identity and completeness flag, is preserved.
diagnostic_dir = ROOT / 'root-native-diagnostic-five-v3'
diagnostic = read_json(diagnostic_dir / 'VERIFIED_MANIFEST.json')
compare = read_json(diagnostic_dir / 'compare-4ab-a96.original.json')['structuredContent']
published = read_json(diagnostic_dir / 'PUBLISHED_COMPARE.original.json')['structuredContent']
assert compare['base'] == diagnostic['source_commit'] and compare['head'] == COMMIT
assert compare['too_large'] is None and compare['behind_by'] == 0
diagnostic_paths = {v['path'] for v in diagnostic['files']}
assert not diagnostic_paths.intersection(v['filename'] for v in compare['files'])
assert published['head'] == '00378c2e33ede95f4a93bf96f6d87b3bd415d337'
assert published['too_large'] is None and {v['filename'] for v in published['files']} == diagnostic_paths
assert diagnostic['actual_format_returncode'] == 0 and diagnostic['actual_format_error'] is None
payload = {r['path']: r for r in read_json(diagnostic_dir / 'format-request/input-payload.json')['files']}
diagnostic_records = []
for row in diagnostic['files']:
    exists, base = original_bytes(row, payload=payload)
    after_path = diagnostic_dir / 'postimages' / row['path']
    after = read_input(after_path)
    verify(after, row['after'])
    diagnostic_records.append({'path': safe_path(row['path']), 'base_exists': exists,
                               'base_bytes': base, 'after_bytes': after, 'after_source': str(after_path),
                               'raw_record': row})
layers.append({'name': '08-Diagnostic5-00378', 'kind': 'actual_rustfmt', 'pure_a96': True,
               'manifest_path': str(diagnostic_dir / 'VERIFIED_MANIFEST.json'), 'returncode': 0,
               'a96_preimage_proof': str(diagnostic_dir / 'compare-4ab-a96.original.json'),
               'records': diagnostic_records})


def qa_record(path, base_path, after_path, base_expected, after_expected):
    base_exists = base_path is not None
    base = read_input(base_path) if base_exists else EMPTY
    after = read_input(after_path)
    verify(base, base_expected)
    verify(after, after_expected)
    ast.parse(after.decode(), filename=path)
    return {'path': safe_path(path), 'base_exists': base_exists, 'base_bytes': base,
            'after_bytes': after, 'after_source': str(after_path),
            'raw_record': {'base': base_expected, 'after': after_expected}}


qa_records = []
legacy_dir = ROOT / 'candidate-legacy-qa-migration-a96-v1'
legacy = read_json(legacy_dir / 'MANIFEST_V1.json')
for row in legacy['files']:
    qa_records.append(qa_record(row['path'], legacy_dir / 'base' / row['path'],
                                legacy_dir / 'postimages' / row['path'], row['base'], row['after']))

command_dir = ROOT / 'candidate-evaluated-command-guards-a96-v1'
command = read_json(command_dir / 'MANIFEST_V2.json')
path = 'qa/b4-no-bypass/test_evaluated_retention_command_source_closure.py'
qa_records.append(qa_record(path, None, command_dir / 'postimages' / path, ident(EMPTY),
                            command['files']['postimages/' + path]))

current_dir = ROOT / 'candidate-current-protocol-a96-v1'
current = read_json(current_dir / 'DELIVERY.json')
for row in current['qa_files']:
    base_path = current_dir / 'base' / row['path'] if row['base']['bytes'] else None
    qa_records.append(qa_record(row['path'], base_path, Path(row['postimage']), row['base'], row['after']))

root_qa_dir = ROOT / 'candidate-root-progress-postread-guards-v2'
read_json(root_qa_dir / 'MANIFEST.json')
path = 'qa/b4-no-bypass/test_evaluated_candidate_continuation_source_closure.py'
qa_records.append(qa_record(path, None, root_qa_dir / 'postimages' / path, ident(EMPTY),
                            {'bytes': 31602, 'sha256': 'cef8f018ead5711b7cf228a9e5fcbd07656519f3397ebaa964cd8f309c35f741',
                             'blob': 'b1610eb0463cfaeb964d26386030824d50ebf5ad'}))
layers.append({'name': '09-FrozenQA7', 'kind': 'frozen_python_source_qa', 'pure_a96': True,
               'records': qa_records, 'not_executed_on_assembled_tree': True})

# Preserve Profile's explicit assembly guidance as an input record, while
# deliberately excluding its unfinished V4/QA from this actual-only cohort.
plan_path = ROOT / 'profile-evaluated-version-guards-v4-actual/ASSEMBLY_PLAN.json'
read_json(plan_path)

for directory in (BASE, WORK, EVIDENCE):
    assert not directory.exists(), ('refusing to replace an earlier assembly', directory)
    directory.mkdir(parents=True)

ancestor = {}
history = {}
events = []
conflicts = []
layer_summary = []
for layer in layers:
    stats = {'name': layer['name'], 'kind': layer['kind'], 'files': len(layer['records']),
             'pure_a96': layer['pure_a96'], 'exact_applies': 0, 'already_equal': 0, 'clean_merges': 0,
             'explicit_fixture_module_unions': 0, 'conflicts': 0}
    for key in ('manifest_path', 'verified_path', 'returncode', 'a96_preimage_proof', 'not_executed_on_assembled_tree'):
        if key in layer:
            stats[key] = layer[key]
    for row in layer['records']:
        path = row['path']
        incoming_base = row['base_bytes']
        incoming_after = row['after_bytes']
        dest = WORK / path
        if path not in ancestor:
            ancestor[path] = {'exists': row['base_exists'], 'identity': ident(incoming_base),
                              'first_layer': layer['name'], 'preimage_source': layer.get('manifest_path')}
            if row['base_exists']:
                save(BASE / path, incoming_base)
                save(dest, incoming_base)
        if layer['pure_a96']:
            assert ancestor[path]['exists'] == row['base_exists'] and ancestor[path]['identity'] == ident(incoming_base), \
                ('conflicting claimed a96 preimage', layer['name'], path, ancestor[path], ident(incoming_base))
        current = dest.read_bytes() if dest.exists() else EMPTY
        event = {'layer': layer['name'], 'path': path, 'a96_base': ancestor[path],
                 'incoming_base_exists': row['base_exists'], 'incoming_base': ident(incoming_base),
                 'current_before': ident(current), 'incoming_after': ident(incoming_after),
                 'incoming_after_source': row['after_source']}
        if current == incoming_after:
            result = current
            event['method'] = 'already exact incoming after'
            stats['already_equal'] += 1
        elif current == incoming_base and dest.exists() == row['base_exists']:
            result = incoming_after
            event['method'] = 'exact preimage identity replacement'
            stats['exact_applies'] += 1
        else:
            record_dir = EVIDENCE / layer['name'] / path
            record_dir.mkdir(parents=True)
            for name, content in [('current', current), ('incoming-base', incoming_base), ('incoming-after', incoming_after)]:
                save(record_dir / name, content)
            command = ['git', 'merge-file', '-p', '-L', 'current-assembled', '-L', 'incoming-base', '-L', layer['name'],
                       str(record_dir / 'current'), str(record_dir / 'incoming-base'), str(record_dir / 'incoming-after')]
            merge = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            save(record_dir / 'result', merge.stdout)
            save(record_dir / 'stderr', merge.stderr)
            event.update({'method': 'git merge-file three-way', 'merge_evidence': str(record_dir),
                          'merge_returncode': merge.returncode, 'merge_stderr': ident(merge.stderr)})
            if merge.returncode != 0:
                event['conflict_output'] = ident(merge.stdout)
                if (layer['name'] == '07-Version40'
                        and path == 'codex-rs/hepta-agentd/src/circuit_evaluated_retention_receipt_tests.rs'
                        and merge.returncode == 1):
                    # Explicitly approved by Root and the Profile assembly plan:
                    # two independent test modules appended at one empty base
                    # location. Do not apply a general ours/theirs preference.
                    block = (b'<<<<<<< current-assembled\n'
                             b'#[path = "circuit_evaluated_selection_command_tests.rs"]\n'
                             b'mod command_tests;\n=======\n'
                             b'#[path = "circuit_evaluated_version_support_tests.rs"]\n'
                             b'mod version_tests;\n>>>>>>> 07-Version40\n')
                    union = (b'#[path = "circuit_evaluated_selection_command_tests.rs"]\n'
                             b'mod command_tests;\n\n'
                             b'#[path = "circuit_evaluated_version_support_tests.rs"]\n'
                             b'mod version_tests;\n')
                    assert merge.stdout.count(block) == 1, (path, 'unexpected conflict shape')
                    result = merge.stdout.replace(block, union, 1)
                    reference_path = ROOT / 'candidate-legacy-qa-migration-a96-v2-actual/merge-evidence' / path
                    reference = read_input(reference_path)
                    verify(reference, {'bytes': 15513,
                                       'sha256': '28c5131f78a1671e4e7ba4b0918a1c9ae825f8d6c87fb2f6ae3540930cfaad1f'})
                    assert result == reference, (path, 'union differs from reviewed actual43 bytes')
                    event['resolution'] = 'Root-approved exact dual-module union; full bytes equal actual43 reviewed fixture'
                    event['resolution_reference'] = {'path': str(reference_path), **ident(reference)}
                    save(record_dir / 'union-result', result)
                    json_save(record_dir / 'resolution.json', event)
                    stats['explicit_fixture_module_unions'] += 1
                else:
                    event['resolution'] = 'UNRESOLVED; existing assembled current retained'
                    conflicts.append(event)
                    events.append(event)
                    stats['conflicts'] += 1
                    continue
            else:
                result = merge.stdout
                stats['clean_merges'] += 1
            assert not re.search(rb'^(<<<<<<<|=======|>>>>>>>)', result, re.M), path
        save(dest, result)
        event['result'] = ident(result)
        history.setdefault(path, []).append(layer['name'])
        events.append(event)
    layer_summary.append(stats)

# The final changed-file list, not the union of every formatting payload,
# defines what the root integrator should commit over exact a96.
changed = []
unchanged = []
patch_parts = []
for path in sorted(ancestor):
    row = ancestor[path]
    before = (BASE / path).read_bytes() if row['exists'] else EMPTY
    after = (WORK / path).read_bytes()
    record = {'path': path, 'status': 'modified' if row['exists'] else 'added',
              'base': ident(before), 'after': ident(after), 'layers': history.get(path, [])}
    if before == after and row['exists']:
        unchanged.append(record)
        continue
    changed.append(record)
    patch_parts.extend(difflib.unified_diff(before.decode().splitlines(True), after.decode().splitlines(True),
                                           fromfile='a/' + path if row['exists'] else '/dev/null', tofile='b/' + path))
patch = ''.join(patch_parts).encode()
save(OUT / 'assembled-actual-v1.patch', patch)

# Independent strict patch replay; no fuzzy/context repair or repository
# checkout is involved. A mismatch remains a failed preparation result.
replay_dir = OUT / 'patch-roundtrip'
shutil.copytree(BASE, replay_dir)
applied = subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(OUT / 'assembled-actual-v1.patch')],
                         cwd=replay_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
save(OUT / 'patch-roundtrip.stdout.log', applied.stdout)
save(OUT / 'patch-roundtrip.stderr.log', applied.stderr)
replayed = all((replay_dir / row['path']).read_bytes() == (WORK / row['path']).read_bytes() for row in changed) if applied.returncode == 0 else False
roundtrip = {'returncode': applied.returncode, 'exact_changed_files': len(changed) if replayed else 0,
             'files_equal': replayed, 'no_offset_or_fuzz': b'offset' not in applied.stdout and b'fuzz' not in applied.stdout,
             'stdout': ident(applied.stdout), 'stderr': ident(applied.stderr)}
assert applied.returncode == 0 and replayed and roundtrip['no_offset_or_fuzz'], roundtrip

qa_syntax = []
for row in changed:
    if row['path'].endswith('.py'):
        ast.parse((WORK / row['path']).read_text(), filename=row['path'])
        qa_syntax.append(row['path'])

pending = [
    {'id': 'Root3-actual', 'status': 'WAITING_FOR_ROOT_ACTUAL_FORMATTED_POSTIMAGES',
     'impact': 'Root20 QA expects progress and 75-to-66 postread source; neither prefmt product input is silently included.'},
    {'id': 'VersionV4-actual', 'status': 'WAITING_FOR_ROOT_ACTUAL_FORMATTED_POSTIMAGES',
     'impact': 'Profile typed progress and already-bound-read removal are absent until actual V4 is supplied.'},
    {'id': 'Profile-final-QA4', 'status': 'WAITING_FOR_PROFILE_FINAL_ACTUAL_INPUT_QA',
     'impact': 'Published-read, evaluated-retention, retained-version-issuer migrations and new Version suite not substituted by old design versions.'},
    {'id': 'central-CALLERS-and-allowlist', 'status': 'ROOT_OWNED_EXCLUDED',
     'impact': 'No global registry/allowlist is created or modified; source suites are not claimed to pass this assembly.'},
    {'id': 'Training-v3', 'status': 'EXCLUDED_AS_INSTRUCTED',
     'impact': 'Unfinished Training transaction changes are not part of this candidate.'},
]

comparison = []
for name in ('lib.rs', 'circuit_evaluated_retention_receipt_tests.rs'):
    path = 'codex-rs/hepta-agentd/src/' + name
    previous = ROOT / 'candidate-legacy-qa-migration-a96-v2-actual/merge-evidence' / path
    data = read_input(previous)
    comparison.append({'path': path, 'previous_actual40_merge': ident(data),
                       'current': ident((WORK / path).read_bytes()),
                       'bytes_equal': data == (WORK / path).read_bytes()})
assert all(row['bytes_equal'] for row in comparison), comparison

# Verify every input, including the separately reviewed shared-file references.
input_check = []
for path, expected in sorted(input_files.items()):
    actual = ident(Path(path).read_bytes())
    assert actual == expected, ('immutable input changed', path)
    input_check.append({'path': path, **actual})

summary = {'source_commit': COMMIT, 'source_tree': TREE, 'status': 'ACTUAL_ONLY_INITIAL_ASSEMBLY_WITH_EXPLICIT_PENDING_LAYERS',
           'layers': layer_summary, 'paths_in_overlay': len(ancestor), 'changed_files': len(changed),
           'changed_rust_files': sum(r['path'].endswith('.rs') for r in changed),
           'changed_qa_files': len(qa_syntax), 'unchanged_payload_paths': len(unchanged),
           'clean_mechanical_merges': sum(x['clean_merges'] for x in layer_summary),
           'explicit_fixture_module_unions': sum(x['explicit_fixture_module_unions'] for x in layer_summary),
           'unresolved_content_conflicts': len(conflicts), 'patch_roundtrip': roundtrip,
           'frozen_inputs_unchanged': True, 'all_rust_incoming_inputs_actual_formatted': True,
           'mechanical_merge_outputs_separately_formatted': False,
           'source_qa_executed_on_assembly': False, 'native_tests_run': False, 'fullcaller_run': False,
           'global_registry_or_allowlist_written': False, 'ordinary_qualification': 0,
           'pending': pending}
json_save(OUT / 'LAYER_EVENTS.json', events)
json_save(OUT / 'SOURCE_INPUT_MANIFEST.json', input_check)
json_save(OUT / 'COMMIT_FILES.json', changed)
json_save(OUT / 'UNCHANGED_PAYLOAD_FILES.json', unchanged)
json_save(OUT / 'UNRESOLVED.json', {'content_conflicts': conflicts, 'pending': pending})
json_save(OUT / 'SHARED_FILE_COMPARISON.json', comparison)
json_save(OUT / 'PATCH_ROUNDTRIP.json', roundtrip)
json_save(OUT / 'QA_SYNTAX_ONLY.json', {'parsed_files': qa_syntax, 'test_execution': False})
json_save(OUT / 'ASSEMBLY_MANIFEST.json', summary)
print(json.dumps({k: summary[k] for k in ['status', 'paths_in_overlay', 'changed_files', 'changed_rust_files',
                                       'changed_qa_files', 'clean_mechanical_merges', 'unresolved_content_conflicts']}, ensure_ascii=False))
