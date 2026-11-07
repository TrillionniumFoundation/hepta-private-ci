from pathlib import Path, PurePosixPath
import gzip
import hashlib
import io
import json
import shutil
import tarfile


ROOT = Path('/workspace/scratch/08f5efd48967')
ARCHIVE = ROOT / 'native-validation-results/checkpoint-r23-closed.tar.gz'
CHECKPOINT = ROOT / 'native-validation-results/checkpoint-r23'
DEST = ROOT / 'hepta-cell/qualification/cell-unification-20261106/native-evidence/r23-workspace-checkpoint'
ARCHIVE_SHA = '0e7f39f14a68e20bdaefa9646177bc5879098285e45ca42c6d13b81180fa7ee6'
TREE = 'be34ab1afe622ad3b8f030c8c5018f4f54fbc304'
COMMIT = '50dd4bedefcd1b8e2e8cd5cf5023c60a86d38d0a'


def pin(raw):
    return {
        'bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
        'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(),
    }


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()


def gz(raw):
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode='wb', filename='', compresslevel=9, mtime=0) as stream:
        stream.write(raw)
    result = output.getvalue()
    assert int.from_bytes(result[4:8], 'little') == 0
    assert gzip.decompress(result) == raw
    return result


assert not DEST.exists()
assert shutil.disk_usage(DEST.parent).free > 100_000_000
archive_raw = ARCHIVE.read_bytes()
assert len(archive_raw) == 2_165_685 and pin(archive_raw)['sha256'] == ARCHIVE_SHA
with tarfile.open(ARCHIVE) as archive:
    members = archive.getmembers()
    assert len(members) == 211
    assert len({member.name for member in members}) == 211
    assert all(member.isfile() and not PurePosixPath(member.name).is_absolute()
               and '..' not in PurePosixPath(member.name).parts for member in members)
    contents = {member.name: archive.extractfile(member).read() for member in members}
    modes = {member.name: format(member.mode, '04o') for member in members}
index_raw = contents['INDEX.json']
index = json.loads(index_raw)
assert len(index) == 210
assert set(contents) == {entry['path'] for entry in index} | {'INDEX.json'}
for entry in index:
    data = contents[entry['path']]
    assert len(data) == entry['bytes'] and pin(data)['sha256'] == entry['sha256']
    assert modes[entry['path']] == entry['mode']
    assert data == (CHECKPOINT / entry['path']).read_bytes()
assert index_raw == (CHECKPOINT / 'INDEX.json').read_bytes()
source_names = [name for name in contents if name.startswith('source/')]
evidence_names = [name for name in contents if name.startswith('evidence/')]
input_names = [name for name in contents if name.startswith('input/')]
assert (len(source_names), len(evidence_names), len(input_names)) == (188, 16, 6)
source_manifest = json.loads(contents['evidence/native-candidate-r22-source.json'])
assert source_manifest['source_tree'] == TREE and source_manifest['source_commit'] == COMMIT
assert len(source_manifest['changed_files']) == 188
for entry in source_manifest['changed_files']:
    data = contents['source/' + entry['path']]
    assert pin(data) == {key: entry[key] for key in ['bytes', 'sha256', 'git_blob']}
assert pin(contents['input/Cargo.lock'])['sha256'] == source_manifest['lock_sha256']
root_report = json.loads((ROOT / 'r23-root-review/ROOT-RESULT-READBACK.json').read_bytes())
assert root_report['source_tree'] == TREE
assert (root_report['unique_executed_tests'], root_report['passed'], root_report['failed'],
        root_report['timed_out'], root_report['reported_skipped']) == (20228, 20220, 7, 1, 130)
assert root_report['raw_exit_code'] == root_report['natural_outer_exit_code'] == 100
assert root_report['gate_pass'] is False and root_report['evidence_readback_pass'] is True
independent = ROOT / 'r23-independent-readback'
independent_manifest_raw = (independent / 'HANDOFF-MANIFEST.json').read_bytes()
assert pin(independent_manifest_raw)['sha256'] == '6de9bf46f7fa3fe0c560622c29f92a18d18eae845371a9d3c9b92873bc9f2401'
independent_manifest = json.loads(independent_manifest_raw)
assert len(independent_manifest['files']) == 20 and independent_manifest['source_tree'] == TREE
for entry in independent_manifest['files']:
    assert pin((independent / entry['path']).read_bytes()) == {
        key: entry[key] for key in ['bytes', 'sha256', 'git_blob']}

DEST.mkdir()
mappings = []


def carry(path, raw, origin, compress=False):
    raw.decode('utf-8') if compress else None
    output_path = path + '.gz' if compress else path
    output_raw = gz(raw) if compress else raw
    destination = DEST / output_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as stream:
        stream.write(output_raw)
    assert destination.read_bytes() == output_raw
    mappings.append({'origin': origin, 'original': pin(raw), 'destination': output_path,
                     'stored': pin(output_raw), 'encoding': 'gzip-mtime0' if compress else 'identity'})


carry('archive/checkpoint-r23-closed.tar.gz', archive_raw, str(ARCHIVE.relative_to(ROOT)))
carry('archive/INDEX.json', index_raw, 'archive:INDEX.json')
for name in sorted(evidence_names + input_names):
    data = contents[name]
    carry('original/' + name, data, 'archive:' + name, compress=len(data) > 65536)
for path in sorted((ROOT / 'r23-root-review').iterdir()):
    if path.is_file():
        raw = path.read_bytes()
        carry('root-readback/' + path.name, raw, str(path.relative_to(ROOT)),
              compress=len(raw) > 65536 and path.suffix != '.bin')
for path in sorted((ROOT / 'native-validation-results/r23-native-export-originals').iterdir()):
    if path.is_file():
        raw = path.read_bytes()
        carry('native-export/' + path.name, raw, str(path.relative_to(ROOT)), compress=len(raw) > 65536)
for name in ['checkpoint-r23-export.json', 'native-workspace-r23-closed-failure-ids.json']:
    path = ROOT / 'native-validation-results/r23-terminal-small' / name
    carry('native-export/' + name, path.read_bytes(), str(path.relative_to(ROOT)))
for entry in independent_manifest['files']:
    path = independent / entry['path']
    carry('independent-readback/' + entry['path'], path.read_bytes(), str(path.relative_to(ROOT)))
carry('independent-readback/HANDOFF-MANIFEST.json', independent_manifest_raw,
      'r23-independent-readback/HANDOFF-MANIFEST.json')
script = Path(__file__)
carry('assemble_checkpoint.py', script.read_bytes(), str(script.relative_to(ROOT)))

closure = {
    'schema': 'hepta.r23-formal-workspace-checkpoint.v1',
    'state': 'SEALED_FAILED_WORKSPACE_GATE',
    'source_commit': COMMIT, 'source_tree': TREE, 'changed_source_paths': 188,
    'archive': pin(archive_raw), 'archive_regular_members': 211, 'original_index_entries': 210,
    'source_files_remain_only_in_original_archive': True,
    'original_evidence_files': 16, 'original_input_files': 6,
    'original_command': ['just', 'test', '--locked', '--retries', '0'],
    'default_workspace_members': 193,
    'original_workspace_job': '1a1b0f18be6-fc05-7441',
    'original_workspace_raw_exit_code': 100, 'original_workspace_outer_exit_code': 100,
    'original_workspace_outer_state': 'failed',
    'unique_executed_tests': 20228, 'passed': 20220, 'failed': 7, 'timed_out': 1,
    'reported_original_skips': 130,
    'command_elapsed_seconds_including_build': 2128.745448589325,
    'nextest_summary_seconds': 1671.481,
    'native_export_job': '1a1b116bcb7-fc05-75a7', 'native_export_exit_code': 0,
    'native_export_success_is_not_workspace_pass': True,
    'root_readback_separate_from_native_originals': True,
    'independent_readback_files_carried_byte_exact': 20,
    'independent_handoff_carried_byte_exact': True,
    'large_original_utf8_compression': 'reversible gzip, empty filename and mtime=0',
    'original_index_unchanged': True, 'gate_pass': False,
    'source_modified': False, 'new_rust_execution': False, 'fix_fmt_executed': False,
    'qualification_or_scientific_disposition_changed': False,
}
(DEST / 'CLOSURE.json').write_bytes(json_bytes(closure))
(DEST / 'SOURCE-TO-DESTINATION.json').write_bytes(json_bytes({
    'schema': 'hepta.r23-checkpoint-source-destination.v1', 'entries': mappings,
    'copied_source_tree_files': 0, 'original_tar_index_entries_verified': 210}))
(DEST / 'README.md').write_text('''# r23 default-workspace checkpoint

The original source49 default-workspace gate failed with natural exit code 100. It executed 20,228 unique tests: 20,220 passed, seven failed and one timed out. The original nextest summary reports 130 skipped tests. This group preserves a failed gate and does not grant qualification.

The command was `just test --locked --retries 0`, with all 193 default workspace members. The source tree is `be34ab1afe622ad3b8f030c8c5018f4f54fbc304` at source commit `50dd4bedefcd1b8e2e8cd5cf5023c60a86d38d0a`.

- `archive/` contains the byte-exact original archive and its untouched 210-entry INDEX. The 188 source files remain inside the archive and are not duplicated in this group.
- `original/` carries all 16 evidence files and six input files. Large UTF-8 files use reversible gzip with mtime zero; `SOURCE-TO-DESTINATION.json` binds the original and stored bytes.
- `root-readback/` contains the root agent's independent reads and result reconstruction.
- `independent-readback/` carries all 20 frozen historical-agent artifacts and their original handoff manifest without alteration, including the independent full-tree and full-log reconstruction.
- `native-export/` separates the successful pure-Python exporter from the failed Rust test gate. Its original controller captures, stdout, stderr and exact exporter scripts are retained. The failure-ID supplement was created after the archive and is labeled separately here.

No tests, source changes, final fixes, formatting or publication occurred while assembling this evidence group. The failure blocks, original assertions, timeouts and skipped-test reporting are preserved.
''')
binaries = []
for path in sorted(DEST.rglob('*')):
    if not path.is_file():
        continue
    raw = path.read_bytes()
    if path.suffix not in {'.gz', '.bin'}:
        continue
    entry = {'path': str(path.relative_to(DEST)), **pin(raw), 'uploaded_by_this_assembly': False,
             'git_action': 'ROOT_RESOLVE_OR_REGISTER_EXACT_BLOB'}
    if path.suffix == '.gz':
        entry['gzip_mtime_zero'] = int.from_bytes(raw[4:8], 'little') == 0
        entry['decompressed'] = pin(gzip.decompress(raw))
    binaries.append(entry)
(DEST / 'BINARY-PLAN.json').write_bytes(json_bytes({
    'schema': 'hepta.r23-checkpoint-binary-plan.v1', 'entries': binaries,
    'binary_path_count': len(binaries), 'unique_blob_count': len({x['git_blob'] for x in binaries}),
    'git_upload_performed': False}))
entries = [{'path': str(path.relative_to(DEST)), **pin(path.read_bytes())}
           for path in sorted(DEST.rglob('*')) if path.is_file()]
(DEST / 'HANDOFF-MANIFEST.json').write_bytes(json_bytes({
    'schema': 'hepta.r23-checkpoint-handoff.v1', 'status': 'FROZEN_FAILED_GATE_EVIDENCE',
    'source_tree': TREE, 'source_commit': COMMIT, 'files': entries, 'file_count': len(entries),
    'total_bytes': sum(x['bytes'] for x in entries), 'root_upload_and_registration_pending': True,
    'global_index_or_ledger_modified': False}))
for entry in entries:
    assert pin((DEST / entry['path']).read_bytes()) == {
        key: entry[key] for key in ['bytes', 'sha256', 'git_blob']}
print(json.dumps({'directory': str(DEST), 'file_count_excluding_handoff': len(entries),
                  'total_bytes_excluding_handoff': sum(x['bytes'] for x in entries),
                  'handoff': pin((DEST / 'HANDOFF-MANIFEST.json').read_bytes()),
                  'binary_plan': pin((DEST / 'BINARY-PLAN.json').read_bytes())}))
