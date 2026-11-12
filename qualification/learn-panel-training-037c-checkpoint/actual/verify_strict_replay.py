from pathlib import Path
import base64
import difflib
import gzip
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parent
PREFMT = ROOT.parent / 'recovery-b-panel-training-proof-57b-v2'
RECORDS = ROOT / 'strict-replay-v1'
RECORDS.mkdir()


def meta(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


manifest = json.loads((ROOT / 'manifest.json').read_text())
assert manifest['returncode'] == 0 and manifest['error'] is None
assert manifest['source_commit'] == '57b27c81d0d5321b873ee751fd0e58e1d905b988'
assert manifest['source_tree'] == '3db894ee96d358c583bbf4ea15163a0d2bd96258'
compressed = (PREFMT / 'format-request-v1/input-payload.json.gz').read_bytes()
assert meta(compressed) == manifest['input_gzip']
payload_bytes = gzip.decompress(compressed)
assert meta(payload_bytes) == manifest['input_json']
payload = json.loads(payload_bytes)
actual = {row['path']: row for row in manifest['files']}
assert len(actual) == len(payload['files']) == 14
files = {}
for row in payload['files']:
    path = row['path']
    assert path in actual and path not in files
    base = base64.b64decode(row['base_base64'], validate=True)
    before = base64.b64decode(row['before_base64'], validate=True)
    after = (ROOT / 'postimages' / path).read_bytes()
    observed = actual[path]
    assert meta(base) == observed['base'] and meta(before) == observed['before']
    assert meta(after) == observed['after'] and row['origin'] == observed['origin']
    absent = observed['origin']['base_absent']
    if absent:
        assert base == b''
    else:
        assert (PREFMT / 'base' / path).read_bytes() == base
    assert (PREFMT / 'work' / path).read_bytes() == before
    files[path] = {'base': base, 'before': before, 'after': after, 'base_absent': absent}


def make_patch(before_key, after_key, corrected_new_files):
    parts = []
    for path, item in sorted(files.items()):
        before, after = item[before_key], item[after_key]
        if before == after:
            continue
        is_new = corrected_new_files and before_key == 'base' and item['base_absent']
        parts.append('diff --git a/' + path + ' b/' + path + '\n')
        if is_new:
            parts.append('new file mode 100644\n')
            parts.append('index ' + '0' * 40 + '..' + meta(after)['blob'] + '\n')
        else:
            parts.append('index ' + meta(before)['blob'] + '..' + meta(after)['blob'] + ' 100644\n')
        parts.extend(difflib.unified_diff(before.decode().splitlines(True), after.decode().splitlines(True),
            fromfile='/dev/null' if is_new else 'a/' + path, tofile='b/' + path, n=3))
    return ''.join(parts).encode()


artifacts = {row['path']: row for row in manifest['artifacts']}
for name, before_key, after_key in [
    ('panel-training-prefmt.patch', 'base', 'before'),
    ('panel-training-formatted.patch', 'base', 'after'),
    ('format-only.patch', 'before', 'after'),
]:
    rebuilt = make_patch(before_key, after_key, False)
    assert meta(rebuilt) == {key: artifacts[name][key] for key in ('bytes', 'sha256', 'blob')}, name
    if name == 'panel-training-formatted.patch':
        assert rebuilt == (ROOT / name).read_bytes()
    else:
        (ROOT / name).write_bytes(rebuilt)

corrected = ROOT / 'panel-training-57b-corrected.patch'
corrected.write_bytes(make_patch('base', 'after', True))
prefmt_corrected = ROOT / 'panel-training-prefmt-57b-corrected.patch'
prefmt_corrected.write_bytes(make_patch('base', 'before', True))

commands = []


def run(name, repo, args, expect_success=True):
    command = ['git', '-C', str(repo), *args]
    result = subprocess.run(command, capture_output=True)
    raw = result.stdout + result.stderr
    path = RECORDS / (name + '.raw.log')
    path.write_bytes(raw)
    commands.append({'name': name, 'command': command, 'returncode': result.returncode,
                     'log': {'path': path.name, **meta(raw)}})
    if expect_success:
        assert result.returncode == 0, (name, raw.decode(errors='replace'))
        assert b'offset' not in raw.lower() and b'fuzz' not in raw.lower(), name
    return result


def materialize(name, which):
    repo = RECORDS / name
    repo.mkdir()
    for path, item in sorted(files.items()):
        if which == 'base' and item['base_absent']:
            assert not (repo / path).exists()
            continue
        destination = repo / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(item[which])
    run(name + '-init', repo, ['init', '-q'])
    run(name + '-add-base', repo, ['add', '--', '.'])
    require_bytes(repo, which)
    return repo


def require_bytes(repo, which):
    expected = {path: item for path, item in files.items()
                if not (which == 'base' and item['base_absent'])}
    actual_paths = {p.relative_to(repo).as_posix() for p in repo.rglob('*')
                    if p.is_file() and '.git' not in p.relative_to(repo).parts}
    assert actual_paths == set(expected)
    for path, item in expected.items():
        assert (repo / path).read_bytes() == item[which], (repo.name, path)
    index = subprocess.run(['git', '-C', str(repo), 'ls-files', '--stage', '-z'], capture_output=True, check=True).stdout
    observed = {}
    for record in index.split(b'\0'):
        if not record:
            continue
        front, path = record.decode().split('\t')
        mode, blob, stage = front.split()
        assert mode == '100644' and stage == '0'
        observed[path] = blob
    assert observed == {path: meta(item[which])['blob'] for path, item in expected.items()}


def apply(name, repo, patch):
    run(name + '-check', repo, ['apply', '--check', '--index', '--whitespace=error-all', str(patch)])
    run(name + '-apply', repo, ['apply', '--index', '--verbose', '--whitespace=error-all', str(patch)])


base_actual = materialize('exact57b-paths-to-actual', 'base')
raw_check = run('original-formatter-new-file-header-check', base_actual,
                ['apply', '--check', '--index', '--whitespace=error-all', str(ROOT / 'panel-training-formatted.patch')], False)
require_bytes(base_actual, 'base')
apply('corrected-exact57b-to-actual', base_actual, corrected)
require_bytes(base_actual, 'after')

before_actual = materialize('prefmt-to-actual', 'before')
apply('actual-format-only', before_actual, ROOT / 'format-only.patch')
require_bytes(before_actual, 'after')

base_before_actual = materialize('exact57b-via-prefmt-to-actual', 'base')
apply('corrected-exact57b-to-prefmt', base_before_actual, prefmt_corrected)
require_bytes(base_before_actual, 'before')
apply('prefmt-then-format-only', base_before_actual, ROOT / 'format-only.patch')
require_bytes(base_before_actual, 'after')

result = {
    'status': 'PASS', 'source_commit': manifest['source_commit'], 'source_tree': manifest['source_tree'],
    'scope': 'All 14 complete repository-relative touched paths; exact nine verified 57b blobs and five absent paths. This is a path-limited replay, not a full repository checkout or full gate.',
    'existing_paths': sum(not item['base_absent'] for item in files.values()),
    'new_paths': sum(item['base_absent'] for item in files.values()),
    'roundtrips': 3, 'offset_or_fuzz': False,
    'original_formatter_patch_check_returncode': raw_check.returncode,
    'corrected_patch': meta(corrected.read_bytes()),
    'corrected_prefmt_patch': meta(prefmt_corrected.read_bytes()),
    'original_formatter_patch': meta((ROOT / 'panel-training-formatted.patch').read_bytes()),
    'reconstructed_manifest_pinned_format_only': meta((ROOT / 'format-only.patch').read_bytes()),
    'after_files': [{'path': path, **meta(item['after'])} for path, item in sorted(files.items())],
    'commands': commands,
    'native_tests_run': False,
}
(RECORDS / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({key: value for key, value in result.items() if key not in ('after_files', 'commands')}, indent=2))
