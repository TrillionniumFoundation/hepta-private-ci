from pathlib import Path
import base64
import difflib
import gzip
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parent
PREFMT = ROOT.parent / 'recovery-b-panel-training-proof-57b-v2'
RECORDS = ROOT / 'complete-delivery-replay-v1'
RECORDS.mkdir()


def meta(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


compat = json.loads((ROOT / 'D397-COMPATIBILITY.json').read_text())
assert compat['all_b_rust_paths_unchanged_between_base_and_head']
assert compat['new_b_qa_path_unchanged_absence']
delivery = json.loads((ROOT / 'VERIFIED_MANIFEST.json').read_text())
payload = json.loads(gzip.decompress((PREFMT / 'format-request-v1/input-payload.json.gz').read_bytes()))
inputs = {row['path']: row for row in payload['files']}
files = {}
for row in delivery['files']:
    path = row['path']
    after = (ROOT / row['local_area'] / path).read_bytes()
    assert meta(after) == row['after']
    if path in inputs:
        base = None if row['base'] is None else base64.b64decode(inputs[path]['base_base64'])
    elif row['base'] is None:
        base = None
    else:
        base = (ROOT / 'legacy-qa-review/base' / Path(path).name).read_bytes()
    assert base is None if row['base'] is None else meta(base) == row['base']
    files[path] = {'base': base, 'after': after}
assert len(files) == 16 and sum(x['base'] is None for x in files.values()) == 6

parts = []
for path, item in sorted(files.items()):
    before = item['base']
    after = item['after']
    parts.append('diff --git a/' + path + ' b/' + path + '\n')
    if before is None:
        parts.append('new file mode 100644\nindex ' + '0' * 40 + '..' + meta(after)['blob'] + '\n')
    else:
        parts.append('index ' + meta(before)['blob'] + '..' + meta(after)['blob'] + ' 100644\n')
    parts.extend(difflib.unified_diff((before or b'').decode().splitlines(True), after.decode().splitlines(True),
        fromfile='/dev/null' if before is None else 'a/' + path, tofile='b/' + path, n=3))
patch = ROOT / 'panel-training-d397-complete.patch'
patch.write_text(''.join(parts))
repo = RECORDS / 'd397-touched-paths'
repo.mkdir()
for path, item in files.items():
    if item['base'] is not None:
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item['base'])
commands = []
for index, args in enumerate([
    ['init', '-q'], ['add', '--', '.'],
    ['apply', '--check', '--index', '--whitespace=error-all', str(patch)],
    ['apply', '--index', '--verbose', '--whitespace=error-all', str(patch)],
]):
    command = ['git', '-C', str(repo), *args]
    result = subprocess.run(command, capture_output=True)
    raw = result.stdout + result.stderr
    (RECORDS / f'{index}.raw.log').write_bytes(raw)
    commands.append({'command': command, 'returncode': result.returncode, 'raw_log': meta(raw)})
    assert result.returncode == 0 and b'offset' not in raw.lower() and b'fuzz' not in raw.lower(), raw.decode()
for path, item in files.items():
    assert (repo / path).read_bytes() == item['after']
observed = subprocess.run(['git', '-C', str(repo), 'ls-files', '--stage', '-z'], capture_output=True, check=True).stdout
index = {}
for record in observed.split(b'\0'):
    if not record:
        continue
    left, path = record.decode().split('\t')
    mode, blob, stage = left.split()
    assert mode == '100644' and stage == '0'
    index[path] = blob
assert index == {path: meta(item['after'])['blob'] for path, item in files.items()}
result = {'status': 'PASS', 'base_commit': compat['head'],
          'scope': 'All 16 complete repository-relative touched paths. Path-limited exact preimages, not a full source/caller or native gate.',
          'patch': meta(patch.read_bytes()), 'files': 16, 'new_paths': 6,
          'rust_files': 14, 'python_qa_files': 2,
          'global_callers_in_patch': False, 'offset_or_fuzz': False,
          'commands': commands, 'native_tests_run': False}
(RECORDS / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
