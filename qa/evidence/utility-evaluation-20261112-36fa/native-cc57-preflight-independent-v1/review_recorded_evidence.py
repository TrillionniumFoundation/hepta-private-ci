#!/usr/bin/env python3
"""Pure offline comparison of previously captured originals; no host/Git commands."""
import ast
import base64
import datetime
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
NATIVE = Path('/tmp/hepta-36fa-native-gates-cc57-v1')
SOURCE = Path('/tmp/hepta-36fa-source-qualification-cc57-launch-v2/origin-and-clone-originals')
ALIGN = Path('/tmp/hepta-36fa-source-repair-canonical-alignment-launch-v1')
CAPTURE = Path('/tmp/hepta-36fa-cc57-source-inventory-readonly-capture-v1')
HEAD = 'cc57c7198db6293ccca562253c42fffbe2a04633'
TREE = 'b7b357c07b5539769a068c6b9b009629f5612d1e'
INPUTS = []


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def read(path):
    raw = path.read_bytes()
    INPUTS.append({'local_path': str(path), **identity(raw),
                   'identity_kind': 'computed from complete locally retained original bytes'})
    return raw


def obj(path):
    return json.loads(read(path))


def sdk(path):
    value = obj(path)
    if value.get('structuredContent') is not None:
        return value['structuredContent']
    return json.loads(value['content'][0]['text'])


def binary_read(path):
    value = sdk(path)
    raw = base64.b64decode(value['data_base64'], validate=True)
    assert value['offset'] == 0 and value['eof'] is True
    assert len(raw) == value['size'] == value['next_offset']
    assert hashlib.sha256(raw).hexdigest() == value['chunk_sha256']
    return value, raw


def utc_ns(ns):
    seconds, nano = divmod(ns, 1_000_000_000)
    return datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + f'.{nano:09d}Z'


def version(value):
    device, inode, size, mtime, ctime = map(int, value.split(':'))
    return {'device': device, 'inode': inode, 'bytes': size, 'mtime_ns': mtime,
            'ctime_ns': ctime, 'mtime_utc': utc_ns(mtime), 'ctime_utc': utc_ns(ctime)}


result = obj(NATIVE / 'RESULT.json')
summary = obj(NATIVE / 'source-after.json')
terminal = sdk(NATIVE / 'STATUS_01.original.json')
assert result['source_sha'] == HEAD and result['source_tree'] == TREE
assert result['behavioral_tests_started'] is False and result['stages'] == []
assert result['source_before'] is None and result['source_comparison'] == 'unknown_missing_before'
assert result['error'] == 'ValueError: unchanged detached HEAD/no refs'
assert result['source_after'] == summary
assert terminal['job_id'] == '1a1d26326ac-2564-1cd4' and terminal['exit_code'] == 1
assert terminal['timed_out'] is False and terminal['output_complete'] is True

before_raw = read(SOURCE / 'GIT_STATE.before.json')
after_raw = read(SOURCE / 'GIT_STATE.after.json')
assert before_raw == after_raw
prior = json.loads(after_raw)
assert prior['head'] == HEAD and prior['tree'] == TREE and prior['refs_bytes'] == 0
commands = obj(SOURCE / 'READONLY_COMMANDS.json')
assert len(commands) == 13 and all(c['returncode'] == 0 for c in commands)
git_commands = [c for c in commands if c['argv'][0] == '/usr/bin/git']
assert len(git_commands) == 10
allowed = {'rev-parse', 'for-each-ref'}
for c in git_commands:
    assert '--no-optional-locks' in c['argv']
    assert c['argv'][c['argv'].index('-C') + 2] in allowed
ref_commands = [c for c in git_commands if 'for-each-ref' in c['argv']]
assert len(ref_commands) == 2 and all(c['stdout_bytes'] == 0 for c in ref_commands)
last_empty_ref = ref_commands[-1]['finished_at']

head_sdk, head_raw = binary_read(NATIVE / 'ACTUAL_HEAD.READ_01.original.json')
ref_sdk, ref_raw = binary_read(NATIVE / 'OBSERVED_REF.READ_01.original.json')
assert head_raw == ref_raw == (HEAD + '\n').encode()
index = sdk(NATIVE / 'ACTUAL_INDEX.FILE_INFO.original.json')
config = sdk(NATIVE / 'ACTUAL_CONFIG.FILE_INFO.original.json')
snapshot_gzip = sdk(NATIVE / 'ACTUAL_SNAPSHOT_GZIP.FILE_INFO.original.json')
assert config['size'] == prior['config_bytes'] and config['sha256'] == prior['config_sha256']
assert identity(head_raw)['sha256'] == prior['head_raw_sha256']
assert index['size'] == 2072293 and prior['index_bytes'] == 2072488
assert index['sha256'] != prior['index_sha256']

aligned = obj(ALIGN / 'RESULT.json')
assert aligned['status'] == 'CANONICAL_SOURCE_ALIGNED_CLEAN_ONLY'
metadata = obj(ALIGN / 'GIT_METADATA.final.json')
old_index = next(x for x in metadata['files'] if x['path'] == 'index')
assert old_index['sha256'] == prior['index_sha256']
alignment_mutations = [{k: x[k] for k in ('action', 'at', 'completed_at', 'terminal')}
                       for x in aligned['mutation_intents'][-4:]]
assert all(x['terminal'] == 'observed' for x in alignment_mutations)

capture_source = read(CAPTURE / 'CAPTURE.HOLD.py').decode()
capture_ast = ast.parse(capture_source)
capture_calls = sorted({ast.unparse(n.func) for n in ast.walk(capture_ast) if isinstance(n, ast.Call)})
assert not any(x.startswith(('subprocess.', 'os.exec', 'os.spawn', 'os.system')) for x in capture_calls)
assert 'os.O_RDONLY' in capture_source and 'os.O_WRONLY' not in capture_source and 'os.O_RDWR' not in capture_source
capture_admission = sdk(CAPTURE / 'CAPTURE_ADMISSION.original.json')
capture_terminal = sdk(CAPTURE / 'STATUS_01.original.json')
assert capture_terminal['exit_code'] == 0 and capture_terminal['job_id'] == '1a1d25d4534-2564-1cd2'
publication = obj(Path('/tmp/hepta-36fa-cc57-evidence-publication-v1/PUBLISHED_3328_ANCHORS.json'))

admission_text = read(Path('/tmp/hepta-36fa-cc57-admission-successor-v2/qualification-admission.cc57.HOLD.py')).decode()
assert admission_text.index("m.HEAD = cfg['source']; m.TREE = cfg['tree']") < admission_text.index('self.initial_git = m.git_state()')
maintenance_text = read(Path('/tmp/hepta-36fa-successor-maintenance-v5/driver-v5.py')).decode()
native_text = read(Path('/tmp/hepta-36fa-final-qualification-hold-v1/native-wrapper.HOLD.py')).decode()
native_ast = ast.parse(native_text)
snapshot_function = next(n for n in native_ast.body if isinstance(n, ast.FunctionDef) and n.name == 'snapshot')
snapshot_text = ast.get_source_segment(native_text, snapshot_function)
assert 'meta.st_mode&0o111' in snapshot_text and '"missing":True' in snapshot_text

canonical_raw = read(Path('/tmp/hepta-36fa-source-repair-canonical-packet-v1/CANONICAL_CLEAN_INVENTORY.expected.json'))
canonical = json.loads(canonical_raw)
assert identity(canonical_raw)['sha256'] == '13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9'
rows = []
for r in sorted(canonical['files'], key=lambda r: r['path'].encode()):
    assert r['stable'] is True and r['matches_index'] is True
    mode = '120000' if r['kind'] == 'symlink' else '100755' if r['permissions'] & 0o111 else '100644'
    rows.append({'path': r['path'], 'mode': mode, 'bytes': r['bytes'],
                 'sha256': r['sha256'], 'blob': r['working_blob']})
compact_raw = json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()
assert len(rows) == 15188
assert hashlib.sha256(compact_raw).hexdigest() == '20008a0cb7bbfd5ed67396a301e2bfdbbd30f336d0f962cac23e5d1601f660d9'
assert summary['inventory_sha256'] != hashlib.sha256(compact_raw).hexdigest()

report = {
    'format': 'hepta-cc57-native-preflight-independent-recorded-evidence-review-v1',
    'scope': 'Offline analysis of already captured originals and fixed control source. No host observation, source/Git mutation, Cargo, test, or gate execution.',
    'native_attempt': {'job': terminal['job_id'], 'started_at': result['started_at'],
                       'finished_at': result['finished_at'], 'result': result,
                       'supervisor_exit_code': terminal['exit_code'], 'timed_out': terminal['timed_out']},
    'prior_source_gate_git': {'before_after_equal': before_raw == after_raw, 'state': prior,
                              'last_observed_empty_ref_command_finished_at': last_empty_ref,
                              'commands': [{'argv': c['argv'], 'started_at': c['started_at'],
                                            'finished_at': c['finished_at'], 'returncode': c['returncode']}
                                           for c in commands]},
    'current_recorded_metadata': {
        'head_body': head_raw.decode(), 'head_version': version(head_sdk['version']),
        'head_and_config_identity_equal_prior': True,
        'config': config, 'old_index': old_index, 'new_index': index,
        'new_index_version': version(index['version']),
        'index_size_delta_bytes': index['size'] - prior['index_bytes'],
        'observed_ref_path': ref_sdk['path'], 'observed_ref_body': ref_raw.decode(),
        'observed_ref_version': version(ref_sdk['version']),
        'ref_to_index_mtime_gap_ns': version(index['version'])['mtime_ns'] - version(ref_sdk['version'])['mtime_ns'],
        'index_raw_body_available_for_this_review': False,
        'exact_failure_time_for_each_ref_stdout_available': False},
    'examined_action_windows': {
        'canonical_alignment_last_four_mutations': alignment_mutations,
        'canonical_alignment_finished_at': aligned['finished_at'],
        'evidence_publication_remote_api_at': publication['at'],
        'evidence_publication_is_not_native_repository_write_evidence': True,
        'inventory_capture_job': capture_terminal['job_id'],
        'inventory_capture_created_unix_ms': capture_admission['job']['created_unix_ms'],
        'inventory_capture_terminal_at_unix_ms': capture_terminal['at_unix_ms'],
        'inventory_capture_scope': 'Reads retained nine inventory artifacts/parts, not current source physical rows; O_RDONLY only, no child process.'},
    'compact_comparison': {'canonical_projection': identity(compact_raw), 'canonical_rows': len(rows),
                           'actual_after_summary': summary, 'actual_after_gzip_metadata': snapshot_gzip,
                           'actual_after_rows_not_yet_available_in_this_review': True,
                           'raw_index_stat_or_extension_is_not_a_compact_row_field': True,
                           'equal_counts_and_clean_status_do_not_prove_equal_row_content': True},
    'findings': [
        'The admitted module sets m.HEAD/m.TREE from the exact current config before its first git_state call; an old hardcoded HEAD in this predicate is not the explanation.',
        'The first failure is the existing detached HEAD/no refs predicate before initial_git is assigned and before complete physical/environment admission. Its final repeated failure does not prove this attempt changed source.',
        'Observed HEAD/config match the last recorded state. The observed additional ref points to the same cc57 commit but still violates the no-ref invariant; no deletion or whitelist bypass is proposed.',
        'Current index identity, inode and size differ from the last recorded canonical/source-gate index. Its recorded mtime precedes the native attempt. The raw index has not been compared, so stat-only, TREE-extension-only, entry/flag changes remain unproven.',
        'The latest empty-ref command is 00:24:58; the observed ref/index mtimes are 00:30:41.499/519. Their roughly 20ms adjacency does not identify a shared writer or authorize attributing them to a retirement service.',
        'The examined canonical writes ended at 23:42:18 and subsequent source admission recorded equal raw metadata. The 1cd2 retained-file reader and remote GitHub publication are not evidence of a source ref/index write.',
        'The actual compact digest differs from the independently reproduced canonical projection. Compact rows hash actual path/mode/content, not index stat or extension bytes. An index-only metadata explanation is insufficient unless it also changes the enumerated path set.',
        'Writer and causal mechanism remain Unknown. No behavioral test result is inferred.'
    ],
    'needed_to_resolve': [
        'Compare the actual completed 1cd4 compact payload with the actual canonical/source-gate full inventory projected through the same five fields.',
        'Compare complete raw index semantic entries, flags, padding and extensions if those already-authorized originals become available; size delta alone is insufficient.',
        'Preserve the ref bytes/metadata and existing records; associate with an actual recorded writer only if command/process evidence exists.'
    ],
    'input_pins': INPUTS,
    'limitations': 'This frozen review does not exhaust every host process or operation. Native/root own all additional host reads. No physical mutation or repair has been attempted.'
}
target = OUT / 'REVIEW.json'
with target.open('x', encoding='utf-8') as f:
    json.dump(report, f, ensure_ascii=False, indent=2, sort_keys=True)
    f.write('\n')
print(json.dumps({'report': str(target), **identity(target.read_bytes()), 'inputs': len(INPUTS)}))
